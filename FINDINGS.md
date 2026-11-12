# Thotcon 0xC Badge — Reverse Engineering Findings

**Target:** Thotcon 0xC conference badge (ESP32-based)
**Interface:** FTDI FT231X USB-UART → `/dev/ttyUSB0`
**Scope:** Authorized reverse engineering of a badge physically owned by the operator.
**Status:** All subsystems reverse-engineered; 3 flags recovered.

---

## 1. Executive Summary

The badge is an **ESP32-D0WDQ6** (dual-core LX6, 4 MB flash) running an **Arduino-ESP32**
firmware (ESP-IDF v4.4.4, built Apr 2023). It exposes a UART CLI, a capacitive-touch
button game, a Wi-Fi/IRC "BadgeNET" client, and an IR (NEC) laser-tag combat system.

### Flags recovered

| Flag | Subsystem | How it is obtained |
|------|-----------|--------------------|
| `flag{welcome_to_the_8bit_world}` | UART boot banner | Printed in plaintext at every boot |
| `flag{lets_fight!}` | Touch buttons | Enter the **Konami Code**: `Up Up Down Down Left Right Left Right Select` |
| `flag{byte_fu}` | UART `flag` command | **Not obtainable at runtime** — the command is hardcoded to deny; recovered only by decompiling the handler |

### Key findings

- **The `flag` CLI command is a decoy.** The dispatcher hardcodes a string compare: any
  input equal to `"flag"` is routed to `ERR: Permission denied!` *before* the handler runs.
  No developer mode, IR code, or network event unlocks it. The real flag `flag{byte_fu}`
  is built at runtime inside the never-executed handler and is recoverable only by RE.
- **`flag{lets_fight!}` is a Konami-Code easter egg** on the capacitive touch pads, detected
  by a 9-slot circular-buffer comparator.
- **BadgeNET** is an IRC client (port 6667, host `TC0xCBADGE`) that joins `#snowfield`
  (key `RAR`) and `#battles` (key `CONTRA`) and acts as a chat-bot responding to
  bang-commands (`!firmware`, `!update`, `!boot`, `!play`, `!uptime`, `!restart`).
- **`!update` performs an HTTPS OTA** from `tc0xb.s3.us-east-2.amazonaws.com` — a bucket
  that **no longer exists** (`NoSuchBucket`). The name is unclaimed, which is a latent
  OTA/supply-chain takeover vector (not acted upon).
- **IR Lock-On is laser-tag combat**, not a flag gate. Each valid NEC frame received =
  1 damage, reported to `#battles` over IRC.
- **Hardware caveat:** the badge brownout-resets when Wi-Fi powers up on bus power; a
  live IRC session needs a powered USB hub or external supply.

---

## 2. Target Overview

| Property | Value |
|----------|-------|
| MCU | ESP32-D0WDQ6, revision v1.0 (dual-core Xtensa LX6, 240 MHz, Wi-Fi + BT) |
| Crystal | **26 MHz** (not the usual 40 MHz — see note below) |
| Flash | Winbond W25Q32, **4 MB** (JEDEC `ef:4016`), 3.3 V, DIO mode |
| MAC | `7c:9e:bd:79:dd:58` |
| USB-UART | FTDI FT231X (VID:PID `0403:6015`), DTR/RTS auto-reset wired |
| Firmware | Arduino-ESP32 sketch, ESP-IDF v4.4.4 (`arduino-lib-builder`), built Apr 20 2023 |
| Flash MD5 | `267eeb22b7347d95c12803129fae9637` |

> **26 MHz crystal note:** the ESP32 ROM bootloader assumes a 40 MHz crystal when
> computing its UART divisor, so the very first boot-ROM banner is emitted at the wrong
> baud and looks like garbage at 115200. The *application's* own output (Arduino
> `Serial` at 115200) is clean. This is why early captures showed a readable app log
> preceded by a short burst of garbled bytes.

---

## 3. Repository Layout

```
0xC-Badge/
├── FINDINGS.md                 ← this report
├── dump/
│   ├── badge-flash-4MB.bin      full 4 MB flash image (md5 267eeb22…)
│   └── parts/
│       ├── app0.bin             active OTA app slot (factory image, analysed)
│       ├── app1.bin             second OTA slot (same firmware, distinct image)
│       ├── nvs.bin              NVS key/value store (settings)
│       ├── otadata.bin          OTA selector
│       ├── spiffs.bin           SPIFFS filesystem (100% erased / empty)
│       ├── seg0_drom_0x3f400020.bin   carved rodata segment (.rodata/strings)
│       └── seg3_irom_0x400d0020.bin   carved code segment (Xtensa)
├── tools/
│   ├── esp-venv/                Python venv with esptool v5.6.0
│   ├── baudscan.py              passive baud-rate scanner
│   ├── cli.py                   interactive UART CLI driver (filters heartbeat)
│   ├── badgenet_server.py       fake BadgeNET IRC server
│   ├── setup_ap.sh              stand up the open "THOTCON-Open" AP + DNS (needs root)
│   └── teardown_ap.sh           remove the AP + DNS override (needs root)
├── analysis/
│   ├── map.rz                   rizin segment-mapping + arch script (reused everywhere)
│   ├── full.txt                 linear disassembly of the code segment (reference)
│   └── disp.txt                 disassembly of the CLI dispatcher (reference)
└── logs/
    ├── dump.log                 esptool read_flash transcript
    └── badgenet.log             IRC server transcript (early)
```

---

## 4. Methodology — Step by Step (from the beginning)

Every command below is reproducible. Paths are written relative to the project root
`~/revEng-proj/Thotcon/0xC-Badge` (abbreviated `$PROJ`). The esptool wrapper is
`$PROJ/tools/esp-venv/bin/esptool`.

### Phase 0 — Identify the interface

**Goal:** learn what the USB device is before touching it.

```bash
# What did the kernel enumerate?
udevadm info -q property -n /dev/ttyUSB0 | grep -E 'ID_(VENDOR|MODEL|SERIAL)'
# Who can open the port?
ls -l /dev/ttyUSB0           # crw-rw---- root dialout  → need dialout group or an ACL
```

**Reasoning:** the udev properties identify the bridge chip (FTDI FT231X) without sending
a single byte. The permissions tell us we cannot open the port yet (owned by
`root:dialout`). The operator granted access via an ACL (`setfacl -m u:moth:rw`).

### Phase 1 — Passive serial recon & baud discovery

**Goal:** find the console baud rate and see if anything talks first. Listen before speaking.

```bash
# Listen at 115200 for 5 s, print raw bytes
python3 -I -c "
import serial,time
s=serial.Serial('/dev/ttyUSB0',115200,timeout=0.2)
buf=b''; end=time.time()+5
while time.time()<end: buf+=s.read(4096)
print('bytes:',len(buf)); print(repr(buf[:1500]))"
```

**Result:** a `.` character arrived every ~0.5 s — a firmware heartbeat. 115200 was correct
(clean ASCII). A full baud sweep script is saved as `tools/baudscan.py` for the general case.

**Probe the console** — the key discovery was the *line terminator*:

```bash
# '\r' alone is ignored; '\n' triggers command processing
python3 -I -c "
import serial,time
s=serial.Serial('/dev/ttyUSB0',115200,timeout=0.2)
s.write(b'\n'); time.sleep(0.6); s.read(4096)   # flush
s.write(b'help\n'); s.flush(); time.sleep(3)
print(s.read(4096).decode('utf-8','replace'))"
```

**Reasoning:** sending `help\r` produced nothing, but a bare `\n` caused the ESP32 to dump
its boot banner (an input-triggered watchdog reset revealed the ROM signature). This told us
two things at once: the console is **newline-terminated**, and the chip is an **ESP32**
(`ets Jun 8 2016`, `rst:0x8 (TG1WDT_SYS_RESET)`, `boot:0x12 (SPI_FAST_FLASH_BOOT)`).

### Phase 2 — Fingerprint the chip with esptool

**Goal:** confirm the exact ESP32 variant and flash size.

```bash
# Create an isolated venv (keeps system Python clean) and install esptool
python3 -m venv $PROJ/tools/esp-venv
$PROJ/tools/esp-venv/bin/pip install -q --upgrade esptool

# Identify chip + flash. esptool toggles DTR/RTS to enter download mode automatically.
$PROJ/tools/esp-venv/bin/esptool --port /dev/ttyUSB0 flash-id
```

**Result:** `ESP32-D0WDQ6 (revision v1.0)`, 26 MHz crystal, MAC `7c:9e:bd:79:dd:58`,
flash `Manufacturer: ef  Device: 4016  → 4MB` (Winbond W25Q32). The automatic DTR/RTS reset
worked, so no BOOT button is needed.

### Phase 3 — Dump and verify the flash (non-destructive)

**Goal:** make a perfect, offline copy so all further work carries zero risk to the badge.

```bash
# First attempt at 460800 failed with "Corrupt data" — the FTDI link isn't reliable that fast.
# Drop to 115200 (slower but solid). ~7 min for 4 MB.
$PROJ/tools/esp-venv/bin/esptool --port /dev/ttyUSB0 --baud 115200 \
    read-flash 0x0 0x400000 $PROJ/dump/badge-flash-4MB.bin

# Prove the copy is bit-perfect against the chip (read-only; verify-flash does NOT write).
$PROJ/tools/esp-venv/bin/esptool --port /dev/ttyUSB0 --baud 115200 \
    verify-flash 0x0 $PROJ/dump/badge-flash-4MB.bin
# → "Verification successful (digest matched)."
md5sum $PROJ/dump/badge-flash-4MB.bin     # 267eeb22b7347d95c12803129fae9637
```

**Reasoning:** `read-flash` is read-only. `verify-flash` re-reads flash and MD5-compares it
to our file; a match means the dump is complete and uncorrupted. From here everything is
done on `badge-flash-4MB.bin` — the badge is only needed again for live tests.

### Phase 4 — Carve the partition table and segments

**Goal:** locate the app, filesystem, and config regions. ESP32 partition tables live at a
fixed offset `0x8000`; each entry is 32 bytes beginning with magic `0xAA 0x50`.

```bash
python3 -I -c "
import struct
d=open('$PROJ/dump/badge-flash-4MB.bin','rb').read()
pt=d[0x8000:0x8000+0xC00]
for i in range(0,len(pt),32):
    e=pt[i:i+32]
    if e[0:2]!=b'\xaa\x50': break
    t,st=e[2],e[3]; off,size=struct.unpack('<II',e[4:12])
    print(e[12:28].split(b'\x00')[0].decode(),hex(off),hex(size))"
```

**Partition table:**

| Label | Type | Offset | Size | Notes |
|-------|------|--------|------|-------|
| nvs | data/nvs | 0x9000 | 20 KB | settings (LED, dev-mode value) |
| otadata | data | 0xe000 | 8 KB | selects active app (seq0=5 > seq1=4 → **app0 active**) |
| app0 | app/ota_0 | 0x10000 | 1280 KB | **analysed image** |
| app1 | app/ota_1 | 0x150000 | 1280 KB | same firmware, distinct image (different md5/length, not byte-identical) |
| spiffs | data/spiffs | 0x290000 | 1472 KB | **100% erased (0xFF) — empty** |

The app image (starts with magic `0xE9`) was then split into its load segments. The ESP-IDF
app descriptor (`esp_app_desc_t`, magic `0xABCD5432`) at offset `+0x20` confirmed the
Arduino build identity. Segments were carved to `dump/parts/seg{0,3}_*.bin`:

| Segment | Load VA | File offset | Size | Contents |
|---------|---------|-------------|------|----------|
| 0 | `0x3f400020` | `0x030/0x20` | 132 KB | DROM (`.rodata`, strings) |
| 1 | `0x3ffbdb60` | `0x02047c` | 27 KB | `.data` |
| 2 | `0x40080000` | `0x026f14` | 37 KB | IRAM code |
| 3 | `0x400d0020` | `0x030020` | 590 KB | **IROM code (main app)** |
| 4 | `0x40089104` | `0x0c0374` | 50 KB | IRAM code |

> **Address ↔ file-offset rule for segment 3:** `file_offset = vaddr − 0x400a0000`.
> (e.g. the `flag` callback VA `0x400d3450` is at file offset `0x033450`.)

### Phase 5 — String triage

**Goal:** fast situational awareness — what features exist, and any plaintext flags.

```bash
strings -n 4 $PROJ/dump/parts/app0.bin | \
  grep -iE 'flag|thotcon|badge|command|unknown|secret|passw|irc|join' | sort -u
```

**Result:** immediately surfaced `flag{welcome_to_the_8bit_world}`, `Hadouken! flag{lets_fight!}`,
the CLI vocabulary, and the IRC/BadgeNET strings. It also showed `flag{` as a bare prefix —
a hint that at least one flag is *assembled at runtime* rather than stored whole.

### Phase 6 — Static analysis environment (rizin + Xtensa)

**Goal:** disassemble ESP32 (Xtensa LX6) code with virtual addresses so pointer loads resolve.

REA/Ghidra's raw-binary loader does not support Xtensa, so **rizin** (which has an Xtensa
plugin) was used. The app image is not an ELF, so segments are mapped manually at their load
addresses. This script, `analysis/map.rz`, is reused for every rizin invocation:

```
om-*
om 3 0x400d0020 0x9034c 0x030020 rx seg3_code
om 3 0x3f400020 0x20454 0x20     r  seg0_rodata
om 3 0x3ffbdb60 0x06a90 0x02047c rw seg1_data
om 3 0x40080000 0x09104 0x026f14 rx seg2_iram
om 3 0x40089104 0x0c6ac 0x0c0374 rx seg4_iram
e asm.arch=xtensa
e asm.bits=32
e asm.cpu=esp32
e analysis.cpu=esp32
```

Standard invocation (note: the file path must be the **last** argument, and `-a xtensa`
must appear before `-c`, due to rizin's option parser):

```bash
rizin -q -N -a xtensa -i analysis/map.rz -c "s 0x400d3450; pd 40" dump/parts/app0.bin
```

**Reasoning:** `om 3 <VA> <size> <paddr>` maps file descriptor 3 (the opened `app0.bin`) at
each segment's true virtual address. With all segments mapped, an `l32r` literal load shows
the real pointer, and that pointer (into DROM) resolves to the actual string. Setting
`asm.cpu=esp32` suppresses most LX7-only (`ee.*`) mis-decoding; dense functions still
occasionally desync, which is handled by re-aligning or reading raw bytes.

### Phase 7 — Decompile the CLI and solve the `flag` gate

**Drive the live CLI first** (`tools/cli.py` filters the `.` heartbeat and paces input):

```bash
python3 -I tools/cli.py "help" "flag" "ircode"
```

`help` prints the **entire command table including callback addresses** — a gift:

```
cmd: flag   - desc: print flag        - cb: 0x400D3450 - hidden: 1
cmd: ircode - desc: print last IR code - cb: 0x400D3434 - hidden: 1
...
flag   → ERR: Permission denied!
ircode → Last Code Received: 0
```

`test` and `ircode` are also `hidden:1` yet work, so "hidden" is not the gate. The dispatcher
(`0x400d37f0`/`0x400d4398`) was decompiled. The command-match loop at `0x400d38c2`:

```
a6 = command_table (*(0x400d0094) = 0x3f4018bc, 8 × 16-byte entries)
for each entry:
    if strcmp(input, entry->name) == 0:          # matched a command
        if strcmp(input, "flag") == 0:           # 0x3f401892 = literal "flag"
            → 0x400d38e9 beqz → 0x400d39b9 "Permission denied!"   # ALWAYS
        else:
            call entry->cb                        # test/ircode/etc. run normally
```

Confirming the hardcoded compare target and the sole branch into the deny block:

```bash
# The literal compared against is the string "flag"
rizin -q -N -a xtensa -i analysis/map.rz -c "px 8 @ 0x3f401892" dump/parts/app0.bin
#   0x3f401892  666c 6167 00…  →  "flag"

# Which instruction branches to the "Permission denied" block 0x400d39b9?
python3 -I - <<'PY'
import re
for ln in open('analysis/full.txt'):
    m=re.match(r'^0x([0-9a-f]+)\s+\S+\s+.*?\.\s*([+-]0x[0-9a-f]+)\s*$', ln.strip())
    if m and int(m.group(1),16)+int(m.group(2),16)==0x400d39b9:
        print(ln.strip())
PY
#   0x400d38e9  beqz a10, . +0xd0   → 0x400d39b9     (a10 = result of strcmp(input,"flag"))
```

**The `flag` handler itself** (`0x400d3450`) builds the real flag and is dead code at runtime:

```bash
rizin -q -N -a xtensa -i analysis/map.rz -c "pd 28 @ 0x400d3450" dump/parts/app0.bin
# strcpy(buf,"byte_fu"); append(out,"flag{"); append(out,buf); append(out,"}")
```

The three string literals confirm the content:

```bash
rizin -q -N -a xtensa -i analysis/map.rz \
  -c "px 16 @ 0x3f40161b; px 16 @ 0x3f401623; px 16 @ 0x3f401f5a" dump/parts/app0.bin
#   "byte_fu"   "flag{"   "}"     →   flag{byte_fu}
```

> **Recovered flag: `flag{byte_fu}`** — assembled from three static strings by the handler
> that the dispatcher never calls. "byte_fu" (byte kung-fu) is the author's hint that the
> command is a troll and the flag must be reverse-engineered.

### Phase 8 — The touch-button Konami Code (`flag{lets_fight!}`)

Adjacent to `Hadouken! flag{lets_fight!}` in rodata sits a 9-byte array and the button names:

```bash
rizin -q -N -a xtensa -i analysis/map.rz -c "px 16 @ 0x3f401f5c" dump/parts/app0.bin
#   0x3f401f5c  02 02 00 00 01 03 01 03 04   →  the combo
rizin -q -N -a xtensa -i analysis/map.rz -c "pxw 80 @ 0x3f401f80" dump/parts/app0.bin
#   button table {touchGPIO, index, mask, name*}:
#   Down=GPIO12 idx0 | Left=GPIO2 idx1 | Up=GPIO15 idx2 | Right=GPIO13 idx3 | Select=GPIO14 idx4
```

The comparator at `0x400d5478` loops exactly 9 times, matching the last 9 presses (a circular
buffer) against the array; the game loop at `0x400d54bc` prints the flag on a match:

```bash
rizin -q -N -a xtensa -i analysis/map.rz -c "pd 30 @ 0x400d5478" dump/parts/app0.bin
```

Decoding `[2,2,0,0,1,3,1,3,4]` with the index map:

> **Up, Up, Down, Down, Left, Right, Left, Right, Select** — the **Konami Code**.
> Enter it on the badge's touch pads to print `flag{lets_fight!}`.

### Phase 9 — BadgeNET: Wi-Fi + IRC emulation

**Decompiled protocol** (connection builder `0x400d4174`, message handler `0x400d4398`):

- Joins open AP **`THOTCON-Open`**, then IRC to **`TC0xCBADGE:6667`** (port constant
  `0x1a0b` at pool `0x400d026c`).
- Auto-sends `JOIN #snowfield RAR` and `JOIN #battles CONTRA`.
- Acts as a bot: incoming `PRIVMSG` text is **substring-scanned** (no nick-addressing) for
  `!restart`, `!uptime`, `!firmware`, `!boot`, `!play <x>`, `!update`.

**Emulation environment built** (so the badge connects to us instead of the dead con infra):

```bash
# Host capability check (read-only): the USB Wi-Fi dongle supports AP mode on 2.4 GHz
nmcli -f WIFI-PROPERTIES.AP,WIFI-PROPERTIES.2GHZ device show wlx00c0ca843b57

# Stand up the AP + DNS override (needs root — run in a real terminal):
sudo bash tools/setup_ap.sh
#   - creates OPEN AP "THOTCON-Open" via NetworkManager shared mode (gateway 10.42.0.1)
#   - writes /etc/NetworkManager/dnsmasq-shared.d/badgenet.conf  → address=/TC0xCBADGE/10.42.0.1

# Run the fake IRC server (no root; port 6667 > 1024):
python3 tools/badgenet_server.py
```

**Result:** the badge **associated with the AP and pulled IP `10.42.0.27`**, resolved
`TC0xCBADGE → 10.42.0.1`, and attempted BadgeNET. Two blockers were found:
1. **`ufw` was dropping tcp/6667** — fixed with
   `sudo ufw allow in on wlx00c0ca843b57 to any port 6667 proto tcp` (or disabling ufw).
2. **Brownout:** the ESP32 resets when the Wi-Fi radio powers up on bus power, so it cannot
   reliably hold the TCP session. This needs a **powered USB hub / external 3.3 V** to fully
   demonstrate live.

### Phase 10 — IR "Lock-On" (laser-tag combat)

```bash
# RX task 0x400d3af8: decode NEC → validate checksum → 1 damage → PRIVMSG #battles
# TX task 0x400d3a30: build NEC frame from badge identity → RMT transmit
rizin -q -N -a xtensa -i analysis/map.rz -c "pd 12 @ 0x40155d28" dump/parts/app0.bin
#   NEC validator: ((c ^ c>>8 ^ c>>16) & 0xFF) == (c>>24)
```

**Finding:** every *valid* NEC frame counts as exactly 1 point of damage and is reported to
`#battles` over IRC. There is **no magic IR code and no IR-triggered flag** — it is purely the
BadgeBattles combat input layer. "Infrared Lock-On Achieved. Spectrum Scanning:" is a startup
banner.

### Phase 11 — OTA / S3 recon

```bash
# What host/path does !update fetch? (esp_https_ota)
strings dump/parts/app0.bin | grep -iE 'amazonaws|OTA|Begin OTA'
#   tc0xb.s3.us-east-2.amazonaws.com

# Does the bucket exist / list publicly?
curl -s -i "https://tc0xb.s3.us-east-2.amazonaws.com/" | head -12
#   HTTP/1.1 404 Not Found
#   <Error><Code>NoSuchBucket</Code>…
```

**Finding:** the OTA bucket is **gone** (decommissioned after the con). The name `tc0xb` is
**unclaimed** — anyone re-registering it in `us-east-2` could serve firmware to any badge that
runs `!update`. This is a latent supply-chain takeover; **not acted upon** (it would mean
registering a third party's namespace on live AWS).

---

## 5. Findings by Subsystem

### 5.1 UART CLI
8 registered commands in a 16-byte-entry table at `0x3f4018bc` (`{name, desc, cb, hidden}`):
`test`, `help`, `brightness [0-128]`, `delay [0-693]`, `pattern [0-6]`, `reset`, `flag`, `ircode`.
LED settings persist to NVS. The `flag` command is hardcoded-denied (§4 Phase 7).

### 5.2 Touch game
Capacitive pads on GPIO 12/2/15/13/14 (Down/Left/Up/Right/Select). The Konami Code prints
`flag{lets_fight!}` (§4 Phase 8). The same pads drive BadgeBattles movement.

### 5.3 BadgeNET / IRC
Fredi-Machado Arduino IRC client → `TC0xCBADGE:6667`, channels `#snowfield`/`#battles`.
Chat-bot commands (§4 Phase 9). No flag is emitted by any command; `!firmware` returns a
firmware hash, `!update` triggers OTA.

### 5.4 IR Lock-On
NEC laser-tag combat (§4 Phase 10). RX = taking damage, TX = shooting. No flag.

### 5.5 OTA
HTTPS OTA from a now-dead S3 bucket (§4 Phase 11).

---

## 6. Security Observations

1. **Decoy command / RE-gated secret.** `flag` always denies by design; `flag{byte_fu}` only
   exists in the binary. (Intended challenge behavior, not a vulnerability — documented for
   completeness.)
2. **OTA bucket takeover (latent).** `tc0xb.s3.us-east-2.amazonaws.com` returns `NoSuchBucket`.
   Re-registration would allow firmware injection on any badge reachable on a network where the
   badge resolves and trusts that host. Confirm whether `esp_https_ota` here pins a CA/cert
   before weighting the risk.
3. **Brownout on Wi-Fi.** Not security-relevant, but it makes the networked features unreliable
   on bus power.
4. **Open AP trust.** The badge auto-joins any open SSID named `THOTCON-Open` and connects to a
   DHCP-resolved `TC0xCBADGE`, so a rogue AP fully controls its network peer (demonstrated here
   with the emulation environment).

---

## 7. Live Emulation Environment — How to Run

```bash
# 1) Bring up the fake con network (root; real terminal for the sudo password):
sudo bash tools/setup_ap.sh

# 2) Allow the IRC port through the host firewall:
sudo ufw allow in on wlx00c0ca843b57 to any port 6667 proto tcp

# 3) Start the fake BadgeNET server (foreground; logs every badge line):
python3 tools/badgenet_server.py
#    console: raw <line> | msg <chan> <text> | who | quit
#    e.g. once the badge joins:   msg #snowfield !firmware

# 4) Power the badge from a powered hub / external 3.3 V to avoid brownout, then
#    watch it associate (IP 10.42.0.x), JOIN the channels, and respond to commands.

# Teardown when finished:
sudo bash tools/teardown_ap.sh
```

---

## 8. Alternative Commands (same outcomes, different tools)

This section lists substitute commands for each step, in case a given tool is unavailable or a
different workflow is preferred.

### 8.1 Interface identification
```bash
# instead of: udevadm info -q property -n /dev/ttyUSB0
lsusb -v -d 0403:6015 | grep -iE 'iProduct|iManufacturer|iSerial'   # USB descriptors
dmesg | grep -i ftdi                                                 # kernel attach log
cat /sys/bus/usb-serial/devices/ttyUSB0/../uevent                    # sysfs

# grant port access (alternatives to setfacl)
sudo usermod -aG dialout "$USER"      # then re-login (group-based, permanent)
sudo chmod 666 /dev/ttyUSB0           # quick-and-dirty, resets on replug
```

### 8.2 Serial console
```bash
# instead of the Python one-liners / tools/cli.py — any terminal program:
picocom -b 115200 --omap crlf /dev/ttyUSB0      # --omap crlf: send \n as needed
screen /dev/ttyUSB0 115200                      # (Ctrl-A k to quit)
minicom -D /dev/ttyUSB0 -b 115200
# scripted send without Python:
printf 'help\n' > /dev/ttyUSB0 ; timeout 3 cat /dev/ttyUSB0   # after `stty -F /dev/ttyUSB0 115200 raw`
```

### 8.3 Chip ID & flash dump
```bash
# instead of esptool flash-id / read-flash:
esptool.py ...                       # legacy entrypoint name, identical flags
pip install esptool && esptool ...   # system install instead of a venv
python -m esptool --port /dev/ttyUSB0 flash_id   # module form (underscored subcommands also work)
# dumping via the stub at a safe speed, or in chunks:
esptool --port /dev/ttyUSB0 --baud 230400 read-flash 0x0 0x400000 dump.bin        # try faster first
esptool --port /dev/ttyUSB0 read-flash 0x0        0x200000 half1.bin              # split if flaky
esptool --port /dev/ttyUSB0 read-flash 0x200000   0x200000 half2.bin
# integrity without a second full read:
esptool --port /dev/ttyUSB0 verify-flash 0x0 dump.bin     # vs.  sha256sum dump.bin
```

### 8.4 Partition table & segment carving
```bash
# instead of the hand-rolled Python parser:
python $PROJ/tools/esp-venv/lib/python*/site-packages/esptool/*gen_esp32part* -   # IDF partition tool
$PROJ/tools/esp-venv/bin/esptool image-info --version 2 dump/parts/app0.bin        # app header/segments
# carving bytes without Python:
dd if=dump/badge-flash-4MB.bin of=parts/app0.bin bs=1 skip=$((0x10000)) count=$((0x140000))
# (or:)  tail -c +$((0x10000+1)) dump/badge-flash-4MB.bin | head -c $((0x140000)) > parts/app0.bin
```

### 8.5 String triage
```bash
# instead of strings | grep:
rabin2 -zzq dump/parts/app0.bin                    # radare/rizin string lister
rizin -q -c 'izz~flag' dump/parts/app0.bin         # search strings inside rizin
binwalk -Y dump/badge-flash-4MB.bin                # opcode/arch heuristics over the whole image
```

### 8.6 Disassembly / decompilation
```bash
# instead of rizin -a xtensa -i map.rz:
r2 -a xtensa -b 32 -m 0x400d0020 dump/parts/seg3_irom_0x400d0020.bin   # radare2, map a single segment
objdump -D -b binary -m xtensa seg3_irom_0x400d0020.bin                # if an xtensa-capable binutils exists
xtensa-esp32-elf-objdump -D ...                                        # ESP-IDF toolchain objdump
# Ghidra: install the community Xtensa processor module (github: Ebiroll/ghidra-xtensa),
#         import app0.bin as "raw", set language Xtensa:LE:32, add memory blocks at the
#         segment VAs above — then the decompiler (Ghidra P-code) gives C-like output,
#         which rizin's xtensa plugin does not.
# IDA: load as raw binary, processor "Tensilica Xtensa", create segments at the VAs above.
# one-off instruction decode without a project:
rz-asm -a xtensa -d "$(dd if=seg3_irom_0x400d0020.bin bs=1 skip=$((0x3450)) count=48 2>/dev/null | xxd -p)"
```

### 8.7 Finding cross-references (instead of the Python branch-target scanner)
```bash
rizin -q -N -a xtensa -i analysis/map.rz -c "aa; axt @ 0x3f4017b7" dump/parts/app0.bin  # after analysis
rizin -q -N -a xtensa -i analysis/map.rz -c "/v4 0x3f4017b7" dump/parts/app0.bin        # value (pointer) search
rizin -q -N -a xtensa -i analysis/map.rz -c "/ Permission denied" dump/parts/app0.bin   # raw string search
```

### 8.8 Wi-Fi AP + DNS (instead of NetworkManager shared mode)
```bash
# hostapd + dnsmasq (classic manual stack):
#   /etc/hostapd/hostapd.conf:  interface=wlx…; ssid=THOTCON-Open; channel=6; (no wpa= → open)
sudo hostapd /etc/hostapd/hostapd.conf
sudo dnsmasq --interface=wlx… --dhcp-range=10.42.0.50,10.42.0.150,12h \
             --address=/TC0xCBADGE/10.42.0.1
sudo iptables -t nat -A POSTROUTING -o ens33 -j MASQUERADE    # share the ethernet uplink
# or the all-in-one helper:
sudo create_ap wlx00c0ca843b57 ens33 THOTCON-Open             # (github: oblique/create_ap)
# name resolution alternative (mDNS instead of dnsmasq):
avahi-publish -a TC0xCBADGE.local 10.42.0.1
```

### 8.9 Fake IRC server (instead of tools/badgenet_server.py)
```bash
# any minimal IRC daup will do once DNS points TC0xCBADGE at it:
ngircd -f /etc/ngircd/ngircd.conf        # lightweight ircd
# or inspeircd / oragono(ergo). For pure observation, a logging TCP listener:
ncat -lk -p 6667 -c 'cat'                # see exactly what the badge sends (won't complete registration)
socat -v TCP-LISTEN:6667,reuseaddr,fork STDOUT
```

### 8.10 S3 bucket recon (instead of curl)
```bash
aws s3 ls s3://tc0xb --no-sign-request --region us-east-2     # anonymous listing (awscli)
aws s3api head-bucket --bucket tc0xb --no-sign-request        # existence check
curl -s "https://tc0xb.s3.us-east-2.amazonaws.com/?list-type=2"   # raw ListObjectsV2 XML
wget -qO- "https://s3.us-east-2.amazonaws.com/tc0xb/"             # path-style
```

---

## 9. Appendix — Key Addresses

| Symbol / item | Address | Notes |
|---------------|---------|-------|
| `flag` handler (dead code) | `0x400d3450` | builds `flag{byte_fu}` |
| `ircode` handler | `0x400d3434` | reads last NEC code at `*(ctx+0x3c)+0xc` |
| CLI dispatcher / match loop | `0x400d4398` / `0x400d38c2` | |
| hardcoded `"flag"` compare | `0x400d38e2` vs `0x3f401892` | → deny at `0x400d38e9` |
| "Permission denied" block | `0x400d39b9` | pool `0x400d0104` → `0x3f4017b7` |
| command table | `0x3f4018bc` (via `*(0x400d0094)`) | 8 × 16 bytes |
| Konami comparator | `0x400d5478` | 9-slot circular buffer |
| combo array | `0x3f401f5c` | `02 02 00 00 01 03 01 03 04` |
| button table | `0x3f401f80` | `{touchGPIO, index, mask, name*}` |
| game loop (prints Hadouken) | `0x400d54bc` | |
| IRC connection builder | `0x400d4174` | |
| IRC message handler | `0x400d4398` | bang-command dispatch |
| IRC port 6667 | pool `0x400d026c` = `0x1a0b` | |
| IR RX task | `0x400d3af8` | NEC decode + damage |
| IR TX task | `0x400d3a30` | NEC transmit |
| NEC checksum validator | `0x40155d28` | `((c^c>>8^c>>16)&0xff)==(c>>24)` |
| segment-3 VA→file | `file = VA − 0x400a0000` | |

---

*Report generated during an authorized reverse-engineering session on badge hardware owned by
the operator. All flash access was read-only; the badge firmware was never modified.*
