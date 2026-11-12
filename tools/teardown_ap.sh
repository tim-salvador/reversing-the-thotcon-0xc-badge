#!/usr/bin/env bash
# Remove the THOTCON-Open AP and the BadgeNET DNS override.  Run with sudo.
set -uo pipefail
CON="thotcon-open"
nmcli connection down "$CON" 2>/dev/null || true
nmcli connection delete "$CON" 2>/dev/null || true
rm -f /etc/NetworkManager/dnsmasq-shared.d/badgenet.conf
echo "[+] AP '$CON' removed and DNS override deleted."
echo "    (Wi-Fi dongle is free again; ethernet was never touched.)"
