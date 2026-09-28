#!/usr/bin/env python3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEV = "/dev/video0"
WIDTH = 1920
HEIGHT = 1080
PORT = 8080
MIN_FRAME = 100
STREAM_FPS = 15

latest = None
lock = threading.Lock()


def capture():
    global latest
    cmd = [
        "v4l2-ctl", "-d", DEV,
        "--set-fmt-video=width=%d,height=%d,pixelformat=MJPG" % (WIDTH, HEIGHT),
        "--stream-mmap", "--stream-to=-",
    ]
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
                    if len(frame) >= MIN_FRAME:
                        with lock:
                            latest = frame
        except Exception:
            pass
        time.sleep(0.5)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with lock:
                        f = latest
                    if f is None:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(f)).encode() + b"\r\n\r\n")
                    self.wfile.write(f)
                    self.wfile.write(b"\r\n")
                    time.sleep(1.0 / STREAM_FPS)
            except Exception:
                return
        elif self.path.startswith("/snapshot"):
            with lock:
                f = latest
            if f is None:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(f)))
            self.end_headers()
            self.wfile.write(f)
        else:
            body = (b"<html><head><title>b550-kvm</title></head>"
                    b"<body style='margin:0;background:#111'>"
                    b"<img src='/stream' style='width:100%;height:auto'>"
                    b"</body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


threading.Thread(target=capture, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
