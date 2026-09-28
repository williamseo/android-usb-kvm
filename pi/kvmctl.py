#!/usr/bin/env python3
import os
import socket
import sys
import time

PHONE = (os.environ.get("KVM_PHONE", "192.168.1.50"),
         int(os.environ.get("KVM_PHONE_PORT", "4711")))

LETTERS = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "1234567890"
SHIFTED = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7',
    '*': '8', '(': '9', ')': '0', '_': '-', '+': '=', '{': '[', '}': ']',
    '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/', '~': '`',
}
PUNCT = {
    ' ': '2c', '-': '2d', '=': '2e', '[': '2f', ']': '30', '\\': '31',
    ';': '33', "'": '34', '`': '35', ',': '36', '.': '37', '/': '38',
}
NAMED = {
    'enter': '28', 'return': '28', 'esc': '29', 'escape': '29',
    'backspace': '2a', 'tab': '2b', 'space': '2c', 'capslock': '39',
    'f1': '3a', 'f2': '3b', 'f3': '3c', 'f4': '3d', 'f5': '3e', 'f6': '3f',
    'f7': '40', 'f8': '41', 'f9': '42', 'f10': '43', 'f11': '44', 'f12': '45',
    'insert': '49', 'home': '4a', 'pageup': '4b', 'delete': '4c', 'del': '4c',
    'end': '4d', 'pagedown': '4e', 'right': '4f', 'left': '50',
    'down': '51', 'up': '52',
}
MODS = {'ctrl': 0x01, 'shift': 0x02, 'alt': 0x04, 'gui': 0x08, 'win': 0x08}


def ch_to_hid(ch):
    if ch in LETTERS:
        return 0x00, 0x04 + LETTERS.index(ch)
    if ch in DIGITS:
        return 0x00, 0x1E + DIGITS.index(ch)
    if ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        return 0x02, 0x04 + LETTERS.index(ch.lower())
    if ch in SHIFTED:
        m, k = ch_to_hid(SHIFTED[ch])
        return 0x02, k
    if ch in PUNCT:
        return 0x00, int(PUNCT[ch], 16)
    if ch == '\n':
        return 0x00, 0x28
    if ch == '\t':
        return 0x00, 0x2B
    if ch == '\b':
        return 0x00, 0x2A
    return None


class Phone:
    def __init__(self, addr=PHONE, timeout=5):
        self.s = socket.create_connection(addr, timeout)
        self.buf = b""

    def _readline(self):
        while b"\n" not in self.buf:
            data = self.s.recv(256)
            if not data:
                break
            self.buf += data
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode(errors="replace").strip()

    def cmd(self, line):
        self.s.sendall((line + "\n").encode())
        return self._readline()

    def tap(self, mod, key):
        return self.cmd("K %02x %02x" % (mod, key))

    def type(self, text):
        for ch in text:
            r = ch_to_hid(ch)
            if r is None:
                continue
            self.cmd("K %02x %02x" % r)

    def key(self, name):
        name = name.lower()
        if name in NAMED:
            return self.cmd("K 00 %s" % NAMED[name])
        if name in MODS:
            return self.cmd("K %02x 00" % MODS[name])
        if len(name) == 1:
            r = ch_to_hid(name)
            if r:
                return self.cmd("K %02x %02x" % r)
        return "ERR"

    def combo(self, names):
        mod = 0
        key = 0x00
        for n in names:
            n = n.lower()
            if n in MODS:
                mod |= MODS[n]
            elif n in NAMED:
                key = int(NAMED[n], 16)
            elif len(n) == 1:
                r = ch_to_hid(n)
                if r:
                    mod |= r[0]
                    key = r[1]
        return self.cmd("K %02x %02x" % (mod, key))

    def close(self):
        self.s.close()


def main():
    if len(sys.argv) < 2:
        print("usage: kvmctl.py <ping|type <text>|key <name>|combo <k>...>")
        return 1
    p = Phone()
    cmd = sys.argv[1]
    if cmd == "ping":
        print(p.cmd("PING"))
    elif cmd == "type":
        p.type(" ".join(sys.argv[2:]))
        print("OK")
    elif cmd == "key":
        print(p.key(sys.argv[2]))
    elif cmd == "combo":
        print(p.combo(sys.argv[2:]))
    else:
        print("unknown")
        return 1
    p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
