# dump/

The badge firmware is **not committed** to this repo. It is the vendor's copyrighted
code, and the point of the writeup is to dump your own badge. Reproduce it here:

```bash
# identify the chip + flash size
esptool --port /dev/ttyUSB0 flash-id

# read the whole flash (read-only) and verify the copy byte-for-byte
esptool --port /dev/ttyUSB0 --baud 115200 read-flash   0x0 0x400000 dump/badge-flash-4MB.bin
esptool --port /dev/ttyUSB0 --baud 115200 verify-flash 0x0           dump/badge-flash-4MB.bin
```

Then carve the partitions/segments into `dump/parts/` (see FINDINGS.md, Phase 4). The
analysis commands in the writeup expect `dump/parts/app0.bin` to exist after that step.
