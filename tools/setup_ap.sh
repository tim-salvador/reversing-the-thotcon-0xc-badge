#!/usr/bin/env bash
# Stand up an OPEN Wi-Fi AP "THOTCON-Open" on the USB Wi-Fi dongle and make the
# badge's IRC server name "TC0xCBADGE" resolve to this host, so the Thotcon 0xC
# badge connects to our fake BadgeNET server.  Run with sudo.  Ethernet stays up.
set -euo pipefail

IFACE="${IFACE:-wlx00c0ca843b57}"   # the AP-capable USB dongle
SSID="THOTCON-Open"
CON="thotcon-open"
GW="10.42.0.1"                       # NetworkManager 'shared' default gateway

echo "[*] Using interface: $IFACE"

# 1) DNS: make TC0xCBADGE resolve to us, BEFORE the shared connection starts
#    (NetworkManager's per-connection dnsmasq reads this dir).
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/badgenet.conf <<EOF
# Resolve the badge's hardcoded IRC host to this AP host
address=/TC0xCBADGE/$GW
address=/tc0xcbadge/$GW
address=/TC0xCBADGE.local/$GW
EOF
echo "[*] Wrote dnsmasq dropin -> TC0xCBADGE = $GW"

# 2) Create the OPEN AP (no password).  Delete any prior copy first.
nmcli connection delete "$CON" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname "$IFACE" con-name "$CON" \
    autoconnect no ssid "$SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg \
    ipv4.method shared >/dev/null
# leave wifi-security unset == OPEN network
nmcli connection up "$CON"

echo
echo "[+] AP '$SSID' is up on $IFACE (open, 2.4GHz), gateway $GW"
echo "[+] TC0xCBADGE now resolves to $GW for AP clients"
echo
echo "Next: run the IRC server on this host (no root needed):"
echo "    python3 $(dirname "$0")/badgenet_server.py"
echo
echo "Watch DHCP leases (badge should appear):"
echo "    journalctl -u NetworkManager -f | grep -i dhcp"
echo "Tear down later with: sudo $(dirname "$0")/teardown_ap.sh"
