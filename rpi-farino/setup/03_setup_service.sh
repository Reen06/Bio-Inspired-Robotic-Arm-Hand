#!/usr/bin/env bash
# Install the farino-wave systemd service.
# Called by setup_on_pi.sh — runs directly on the Pi (not in a chroot).
set -euo pipefail

echo "=== Writing farino-wave.service ==="

sudo tee /etc/systemd/system/farino-wave.service > /dev/null <<'EOF'
[Unit]
Description=Farino FR-3 Wave Demo
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker stop farino-wave
ExecStartPre=-/usr/bin/docker rm farino-wave
ExecStart=/usr/bin/docker run \
    --rm \
    --name farino-wave \
    --network host \
    -e FARINO_DRY_RUN=0 \
    farino-wave:latest
ExecStop=/usr/bin/docker stop farino-wave
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable farino-wave.service

echo ""
echo "    farino-wave.service installed and enabled."
echo "    Logs:   journalctl -u farino-wave -f"
echo "    Stop:   sudo systemctl stop farino-wave"
echo "    Manual: sudo docker run --rm --network=host -e FARINO_DRY_RUN=1 farino-wave:latest"
