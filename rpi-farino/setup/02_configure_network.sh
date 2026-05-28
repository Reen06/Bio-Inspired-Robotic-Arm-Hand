#!/usr/bin/env bash
# Configure static IP on eth0 for the FR-3 robot control box connection.
# Called by setup_on_pi.sh — runs directly on the Pi.
#
# Assigns eth0 → 192.168.58.100/24 (direct cable to FR-3 control box at 192.168.58.2).
# All other interfaces (wlan0, etc.) are left untouched.
set -euo pipefail

NETD=/etc/systemd/network

echo "=== Configuring eth0 static IP (192.168.58.100/24) ==="

sudo mkdir -p "$NETD"
sudo tee "$NETD/20-robot-eth.network" > /dev/null <<'EOF'
[Match]
Name=eth0

[Network]
Address=192.168.58.100/24

[Link]
RequiredForOnline=no
EOF

echo "=== Enabling systemd-networkd ==="
sudo systemctl enable systemd-networkd 2>/dev/null || true
sudo systemctl restart systemd-networkd 2>/dev/null || true

echo "=== Network config written: $NETD/20-robot-eth.network ==="
echo "    eth0 → 192.168.58.100/24 (static, robot connection)"
echo "    Other interfaces are unaffected."
