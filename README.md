# reversing-the-thotcon-0xc-badge

Originally published at https://www.timsalvador.com/blog/reversing-the-thotcon-0xc-badge/

A full software teardown of a **Thotcon 0xC conference badge** (an **ESP32-D0WDQ6**, 4 MB flash). I dump the flash read-only with **esptool**, decompile the **Xtensa** firmware with **rizin**, drive the UART console, and stand up a **fake conference Wi-Fi + IRC network** to talk to the badge. Three flags recovered, including one from a `flag` command that is hardcoded to refuse and whose real value only exists in dead code.

> Built and validated on a Linux workstation with the badge on an FTDI FT231X USB-UART bridge (`/dev/ttyUSB0`). The esptool and rizin steps are specific to ESP32/Xtensa; the method (identify, dump, verify, carve, decompile, emulate) generalizes to any badge.

**📖 The full story, including the dead ends and lessons, is at [timsalvador.com/blog/reversing-the-thotcon-0xc-badge](https://www.timsalvador.com/blog/reversing-the-thotcon-0xc-badge/) and in [docs/writeup.md](docs/writeup.md).** It reads as a blog post and doubles as a build log.

---

## Results

| Flag | Where it lives | How to get it |
|---|---|---|
| `flag{welcome_to_the_8bit_world}` | UART boot banner | Read the serial console at boot |
| `flag{lets_fight!}` | Touch buttons | Enter the Konami code: `Up Up Down Down Left Right Left Right Select` |
| `flag{byte_fu}` | The `flag` command's dead-code handler | Decompile it; the command itself always refuses |

Target: ESP32-D0WDQ6 rev v1.0, 26 MHz crystal, 4 MB Winbond W25Q32 (`ef:4016`), MAC `7c:9e:bd:79:dd:58`. Flash image md5 `267eeb22b7347d95c12803129fae9637`.

---

## What's here

```
docs/            the writeup (Markdown) and image folder
FINDINGS.md      the full technical report: every phase, command, and address
tools/
  baudscan.py          passive baud discovery (optionally resets to catch a banner)
  serial_console.py    UART console driver: filters the heartbeat, tries line terminators
  badgenet_server.py   minimal fake IRC server the badge will register and join against
  setup_ap.sh          stand up the open "THOTCON-Open" AP + DNS override (needs root)
  teardown_ap.sh       remove the AP + DNS override (needs root)
analysis/
  map.rz               rizin segment map (load addresses) for disassembling the app image
dump/            not committed: the firmware is yours to dump (see dump/README.md)
```

The flash dump, logs, and the large linear-disassembly text are intentionally left out (see `.gitignore`): the firmware is the vendor's to distribute, and everything derived from it is reproducible from the commands in the writeup.

---

## Quick start

```bash
git clone https://github.com/tim-salvador/reversing-the-thotcon-0xc-badge.git
cd reversing-the-thotcon-0xc-badge

# 1. Find the console baud (and optionally catch a boot banner)
python3 tools/baudscan.py /dev/ttyUSB0 --reset

# 2. Drive the console (this firmware acts on \n; mind the heartbeat)
python3 tools/serial_console.py "help" "flag"

# 3. Identify + dump + VERIFY the flash (read-only), then analyze the copy offline
esptool --port /dev/ttyUSB0 flash-id
esptool --port /dev/ttyUSB0 --baud 115200 read-flash   0x0 0x400000 dump/flash.bin
esptool --port /dev/ttyUSB0 --baud 115200 verify-flash 0x0 dump/flash.bin

# 4. Disassemble the carved app image with the segment map
rizin -q -N -a xtensa -i analysis/map.rz -c "s 0x400d3450; pd 40" dump/parts/app0.bin
```

---

## Design principles

- **Read-only until verified.** Dump the flash, prove it matches the chip, then never write to the badge. A dump you have not verified is a liability.
- **Listen before you speak.** Idle heartbeats and boot banners identify the chip and baud for free.
- **Trust the silicon, not the prompt.** The `flag` command refuses on purpose; its real value is in a handler the dispatcher never calls.
- **Emulate dead infrastructure.** The conference network is gone, so the repo includes a fake AP recipe and IRC server to revive the Wi-Fi features.

---

## Requirements

- Linux with `python3` (+ `pyserial`), `esptool`, and `rizin` (Xtensa plugin).
- An FTDI/CP210x/CH340 USB-UART link to the badge (`/dev/ttyUSB0`).
- For the Wi-Fi emulation: an AP-capable Wi-Fi adapter, NetworkManager + dnsmasq, and root.

---

## Caveats, in brief

- **Wi-Fi brownout.** The badge resets when its radio powers up on bus power; the networked features need a powered USB hub or external supply.
- **Dead OTA endpoint.** The `!update` command fetches firmware from an S3 bucket that no longer exists; the name is unclaimed, a latent takeover vector (not acted on).
- **ESP32-specific tooling.** esptool and the Xtensa disassembly apply to this chip; the overall method generalizes to other badges.

Full detail on all of these in the writeup.

---

## License

MIT. See [LICENSE](LICENSE).

## Author

Tim Salvador · [timsalvador.com](https://timsalvador.com) · [github.com/tim-salvador](https://github.com/tim-salvador) · [linkedin.com/in/tim-salvador](https://linkedin.com/in/tim-salvador)
