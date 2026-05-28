#!/usr/bin/env bash
# Install and enable the farino-wave Docker-based systemd services.
# Runs inside the Pi via provision.sh.
set -euo pipefail

echo "=== Writing systemd services ==="

# One-shot service: loads the pre-built arm64 Docker image on first boot.
# After loading, the tar is removed to free space.
cat > /etc/systemd/system/farino-wave-load.service <<'EOF'
[Unit]
Description=Load Farino Wave Docker Image
Documentation=file:///home/robotics/plans/architecture.md
After=docker.service
Requires=docker.service
Before=farino-wave.service
ConditionPathExists=/home/robotics/farino-wave.tar.gz

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'docker load < /home/robotics/farino-wave.tar.gz && rm -f /home/robotics/farino-wave.tar.gz'
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/farino-wave.service <<'EOF'
[Unit]
Description=Farino FR-3 Wave Demo
Documentation=file:///home/robotics/plans/architecture.md
After=docker.service farino-wave-load.service
Requires=docker.service
Wants=network-online.target farino-wave-load.service

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

echo "=== Enabling services ==="
# daemon-reload and enable fail in a chroot (no D-Bus), so we create the
# WantedBy symlinks directly. systemd picks them up on first real boot.
WANTED_BY=/etc/systemd/system/multi-user.target.wants
mkdir -p "$WANTED_BY"
ln -sf /etc/systemd/system/farino-wave-load.service "$WANTED_BY/farino-wave-load.service"
ln -sf /etc/systemd/system/farino-wave.service "$WANTED_BY/farino-wave.service"

echo ""
echo "=== Services installed ==="
echo "    farino-wave-load.service — runs once on first boot to docker load the image"
echo "    farino-wave.service      — runs the wave node via Docker on every boot"
echo ""
echo "    To watch logs: journalctl -u farino-wave -f"
echo "    To stop:       systemctl stop farino-wave"
echo "    To run manually: docker run --rm --network=host -e FARINO_DRY_RUN=0 farino-wave:latest"
