#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEV = "/dev/video0"
WIDTH = 1920
HEIGHT = 1080
PORT = 8080
PHONE_HOST = os.environ.get("KVM_PHONE", "192.168.1.50")
PHONE_PORT = int(os.environ.get("KVM_PHONE_PORT", "4711"))
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "machines.json")
AUTH_FILE = os.path.join(HERE, "auth.json")

DEFAULTS = {"power": 500, "reset": 500, "forceoff": 10000}

latest = None
flock = threading.Lock()

try:
    with open(CONFIG) as fh:
        MACHINES = json.load(fh)
except Exception:
    MACHINES = {"machine1": {"ip": "192.168.1.10", "power": 17, "reset": 27}}

try:
    with open(AUTH_FILE) as fh:
        _a = json.load(fh)
    AUTH_USER = _a.get("user", "admin")
    AUTH_PASS = _a.get("password", "")
except Exception:
    AUTH_USER, AUTH_PASS = "admin", ""

AUTH_TOKEN = base64.b64encode((AUTH_USER + ":" + AUTH_PASS).encode()).decode()

_pins = {}
RELAY_OK = False
try:
    import lgpio
    _chip = lgpio.gpiochip_open(0)
    _rlock = threading.Lock()
    for _m, _c in MACHINES.items():
        for _a in ("power", "reset"):
            _p = _c.get(_a)
            if _p is None:
                continue
            try:
                lgpio.gpio_claim_output(_chip, _p, 1, lgpio.SET_OPEN_DRAIN)
                _pins[(_m, _a)] = _p
                print("relay ok", _m, _a, "gpio", _p, flush=True)
            except Exception as _pe:
                print("relay FAIL", _m, _a, "gpio", _p, _pe, flush=True)
    RELAY_OK = True
except Exception as _e:
    print("lgpio init failed", _e, flush=True)


def relay_pulse(machine, action, ms):
    pin = _pins.get((machine, "power" if action == "forceoff" else action))
    if pin is None:
        return False
    with _rlock:
        lgpio.gpio_write(_chip, pin, 0)
        try:
            time.sleep(ms / 1000.0)
        finally:
            lgpio.gpio_write(_chip, pin, 1)
    return True


def machine_status():
    out = {}
    for name, cfg in MACHINES.items():
        ip = cfg.get("ip")
        if not ip:
            out[name] = {"ip": None, "online": None}
            continue
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out[name] = {"ip": ip, "online": r.returncode == 0}
    return out


def capture():
    global latest
    cmd = ["v4l2-ctl", "-d", DEV,
           "--set-fmt-video=width=%d,height=%d,pixelformat=MJPG" % (WIDTH, HEIGHT),
           "--stream-mmap", "--stream-to=-"]
    while True:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, bufsize=0)
            buf = b""
            while True:
                chunk = p.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    s = buf.find(b"\xff\xd8")
                    if s < 0:
                        buf = b""
                        break
                    e = buf.find(b"\xff\xd9", s + 2)
                    if e < 0:
                        buf = buf[s:]
                        break
                    frame = buf[s:e + 2]
                    buf = buf[e + 2:]
                    if len(frame) >= 100:
                        with flock:
                            latest = frame
        except Exception:
            pass
        time.sleep(0.5)


def ws_read(rfile):
    hdr = rfile.read(2)
    if len(hdr) < 2:
        return None, None
    b1, b2 = hdr[0], hdr[1]
    op = b1 & 0x0F
    masked = b2 & 0x80
    ln = b2 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", rfile.read(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4) if masked else b"\x00\x00\x00\x00"
    data = rfile.read(ln) if ln else b""
    if masked:
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
    return op, data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def authorized(self):
        if not AUTH_PASS:
            return True
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                u, p = base64.b64decode(hdr[6:]).decode().split(":", 1)
                if u == AUTH_USER and p == AUTH_PASS:
                    return True
            except Exception:
                pass
        if ("kvm_auth=" + AUTH_TOKEN) in self.headers.get("Cookie", ""):
            return True
        return False

    def deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="b550-kvm"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "kvm_auth=%s; Path=/; HttpOnly" % AUTH_TOKEN)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if self.headers.get("Upgrade", "").lower() == "websocket":
            if not self.authorized():
                self.deny()
                return
            self.handle_ws()
            return
        if not self.authorized():
            self.deny()
            return
        if path == "/status":
            self.send_json(machine_status())
            return
        if path.startswith("/relay/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                machine, action = parts[1], parts[2]
                ms = DEFAULTS.get(action)
                q = self.path.split("?", 1)[1] if "?" in self.path else ""
                for kv in q.split("&"):
                    if kv.startswith("ms="):
                        try:
                            ms = int(kv[3:])
                        except Exception:
                            pass
                if ms is None:
                    self.send_json({"ok": False, "error": "bad action"})
                    return
                ok = relay_pulse(machine, action, ms)
                self.send_json({"ok": ok, "machine": machine,
                                "action": action, "ms": ms})
                return
            self.send_json({"ok": False, "error": "bad path"})
            return
        if path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            self.close_connection = True
            try:
                while True:
                    with flock:
                        f = latest
                    if f is None:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(f)).encode() + b"\r\n\r\n")
                    self.wfile.write(f)
                    self.wfile.write(b"\r\n")
                    time.sleep(1.0 / 20)
            except Exception:
                return
        elif path.startswith("/snapshot"):
            with flock:
                f = latest
            if f is None:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Set-Cookie", "kvm_auth=%s; Path=/; HttpOnly" % AUTH_TOKEN)
            self.send_header("Content-Length", str(len(f)))
            self.end_headers()
            self.wfile.write(f)
        else:
            try:
                with open(os.path.join(HERE, "kvm.html"), "rb") as fh:
                    body = fh.read()
            except Exception:
                body = b"kvm.html missing"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", "kvm_auth=%s; Path=/; HttpOnly" % AUTH_TOKEN)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

    def handle_ws(self):
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        try:
            phone = socket.create_connection((PHONE_HOST, PHONE_PORT), 3)
            phone.settimeout(3)
        except Exception:
            self.close_connection = True
            return
        try:
            while True:
                op, data = ws_read(self.rfile)
                if op is None or op == 8:
                    break
                if op != 1:
                    continue
                line = data.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    phone.sendall((line + "\n").encode())
                except Exception:
                    try:
                        phone.close()
                        phone = socket.create_connection((PHONE_HOST, PHONE_PORT), 3)
                        phone.settimeout(3)
                        phone.sendall((line + "\n").encode())
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            try:
                phone.close()
            except Exception:
                pass
            self.close_connection = True


threading.Thread(target=capture, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
