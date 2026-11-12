#!/usr/bin/env python3
"""Drive an unknown device's serial console, one command per argument.

Sends each argument as a line and prints the reply, with two features that
matter when probing badges:

  * Heartbeat filtering. Many firmwares emit a periodic idle byte (a '.' every
    ~0.5s is common). Naive "read until quiet" loops never see quiet because the
    heartbeat keeps arriving. This script only treats NON-heartbeat bytes as
    activity worth waiting on, and caps total wait, so it can't hang. If your
    target's heartbeat is a different byte, pass --hb <char>.

  * Line terminator discovery. Devices differ: some process on '\n', some '\r',
    some '\r\n'. Default is '\n'; override with --eol crlf|cr|lf. If a device
    echoes your bytes but never acts, try a different terminator before assuming
    the command is wrong.

Usage:
    serial_console.py "help" "version" "?"            # default 115200, \n, '.' heartbeat
    serial_console.py --port /dev/ttyACM0 --baud 9600 --eol crlf "menu"
    serial_console.py --reset "help"                  # pulse DTR/RTS (reboot) before sending

Watch the first run carefully: the command table, prompt, or menu a device
prints in response to 'help'/'?'/'menu'/an empty line is your map of its
attack surface.
"""
import sys, time, re, argparse
try:
    import serial
except ImportError:
    sys.exit("pyserial missing: pip install pyserial")

EOLS = {"lf": b"\n", "cr": b"\r", "crlf": b"\r\n"}

ap = argparse.ArgumentParser()
ap.add_argument("commands", nargs="*")
ap.add_argument("--port", default="/dev/ttyUSB0")
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--eol", choices=list(EOLS), default="lf")
ap.add_argument("--hb", default=".", help="single heartbeat byte to filter from idle output")
ap.add_argument("--reset", action="store_true", help="pulse DTR/RTS to reboot before sending")
ap.add_argument("--wait", type=float, default=1.2, help="quiet window (s) that ends a reply")
ap.add_argument("--cap", type=float, default=8.0, help="hard cap (s) on one reply")
args = ap.parse_args()

eol = EOLS[args.eol]
hb = args.hb.encode()[:1]

s = serial.Serial(args.port, args.baud, timeout=0.15)
if args.reset:
    s.dtr = False; s.rts = True; time.sleep(0.15); s.rts = False; time.sleep(0.5)

def read_reply():
    quiet_until = time.time() + args.wait
    deadline = time.time() + args.cap
    buf = b""
    while time.time() < quiet_until and time.time() < deadline:
        chunk = s.read(4096)
        if chunk:
            buf += chunk
            if chunk.replace(hb, b"").strip():        # real (non-heartbeat) data arrived
                quiet_until = time.time() + 0.8
    return buf

print(f"# {args.port} @ {args.baud} eol={args.eol} hb={args.hb!r}")
time.sleep(0.5); s.read(65536)                          # drain startup noise
for cmd in args.commands:
    s.reset_input_buffer()
    s.write(cmd.encode() + eol); s.flush()
    buf = read_reply()
    dots = buf.count(hb)
    text = re.sub(re.escape(args.hb) + r"{2,}", "", buf.replace(b"\r", b"").decode("utf-8", "replace"))
    print(f"\n>>> {cmd!r}  ({len(buf)} bytes, {dots} heartbeat)")
    print(text)
    time.sleep(0.3)
s.close()
