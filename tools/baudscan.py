#!/usr/bin/env python3
"""Passive baud-rate scanner for an unknown serial target.

Listens at each common rate and scores how printable the output is, so you can
tell which baud the device is actually talking at without sending anything.
Optionally pulses DTR/RTS to reset the target first (many boards wire these to
the MCU's reset/boot pins) so you capture a boot banner.

Usage:
    baudscan.py [PORT] [--reset] [--secs N]

The highest printable-ratio row is almost always the real console baud.
Common oddballs worth noting: 74880 (ESP8266 ROM), 115200 (most Arduino/ESP),
9600 (many simple MCUs), 1500000 (some nRF/J-Link CDC).
"""
import sys, time
try:
    import serial
except ImportError:
    sys.exit("pyserial missing: pip install pyserial")

PORT = next((a for a in sys.argv[1:] if not a.startswith("-")), "/dev/ttyUSB0")
RESET = "--reset" in sys.argv
SECS = next((float(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--secs"), 2.5)
RATES = [115200, 9600, 57600, 38400, 19200, 74880, 230400,
         250000, 460800, 921600, 1000000, 1500000, 2000000]

def printable_ratio(b):
    if not b:
        return 0.0
    ok = sum(1 for c in b if 32 <= c < 127 or c in (9, 10, 13))
    return ok / len(b)

print(f"# scanning {PORT} ({SECS}s/rate, reset={RESET})")
for rate in RATES:
    try:
        with serial.Serial(PORT, rate, timeout=0.2) as s:
            if RESET:
                s.dtr = False; s.rts = True; time.sleep(0.12); s.rts = False
            else:
                s.reset_input_buffer()
            buf = b""; end = time.time() + SECS
            while time.time() < end:
                buf += s.read(4096)
        print(f"{rate:>8}  bytes={len(buf):5d}  printable={printable_ratio(buf):.2f}  {buf[:120]!r}")
    except Exception as e:
        print(f"{rate:>8}  ERROR {e}")
