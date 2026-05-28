#!/usr/bin/env bash
# Run this on the Raspberry Pi 4B to set up Farino FR-3 control from scratch.
#
# Usage (on the Pi):
#   git clone https://github.com/Reen06/Bio-Inspired-Robotic-Arm-Hand.git -b RPI
#   cd Bio-Inspired-Robotic-Arm-Hand/rpi-farino
#   ./setup/setup_on_pi.sh
#
# What it does:
#   1. Installs Docker CE (if not already installed)
#   2. Builds the farino-wave Docker image natively on the Pi (~3 min)
#   3. Configures eth0 → 192.168.58.100/24 (static, for FR-3 connection)
#   4. Installs and enables farino-wave systemd service (auto-starts on boot)
#
# Requirements:
#   - Raspberry Pi 4B (arm64)
#   - Debian bookworm / Raspberry Pi OS or Ubuntu 22.04/24.04
#   - sudo access
#   - Internet connection (for Docker CE install and ros:jazzy-ros-base pull)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ok()   { echo "  ✓  $*"; }
info() { echo "  →  $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

# ── Sanity checks ─────────────────────────────────────────────────────────────

[[ "$(uname -m)" == "aarch64" ]] || die "This script must run on an arm64 machine (Raspberry Pi 4B)."
[[ -f "$REPO_DIR/ros2_ws/Dockerfile" ]] || die "Run from the rpi-farino/ directory."

echo ""
echo "=== Farino FR-3 setup ==="
echo ""

# ── Step 1: Install Docker CE ─────────────────────────────────────────────────

if command -v docker &>/dev/null; then
    ok "Docker already installed: $(docker --version | head -1)"
else
    info "Installing Docker CE..."
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings

    # Detect distro for the correct Docker repo
    . /etc/os-release
    case "$ID" in
        debian|raspbian)
            DOCKER_REPO="https://download.docker.com/linux/debian"
            CODENAME="$VERSION_CODENAME"
            ;;
        ubuntu)
            DOCKER_REPO="https://download.docker.com/linux/ubuntu"
            CODENAME="$VERSION_CODENAME"
            ;;
        *)
            die "Unsupported distro: $ID. Install Docker manually then re-run."
            ;;
    esac

    curl -fsSL "$DOCKER_REPO/gpg" | sudo gpg --dearmor -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] $DOCKER_REPO $CODENAME stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io
    sudo systemctl enable --now docker
    ok "Docker CE installed"

    # Add current user to docker group so they don't need sudo for docker commands
    sudo usermod -aG docker "$USER"
    info "Added $USER to docker group (re-login or run 'newgrp docker' for it to take effect)"
fi

# ── Step 2: Build the farino-wave Docker image ───────────────────────────────
# Builds natively on arm64 — no QEMU emulation needed, much faster than host cross-build.

info "Building farino-wave:latest Docker image..."
info "This pulls ros:jazzy-ros-base and builds farino_wave (~3–5 min)."
sudo docker build -t farino-wave:latest "$REPO_DIR/ros2_ws"
ok "Docker image built: farino-wave:latest"

# ── Step 3: Configure eth0 static IP ─────────────────────────────────────────

info "Configuring eth0 → 192.168.58.100/24 for FR-3 connection..."
bash "$SCRIPT_DIR/02_configure_network.sh"
ok "Network configured"

# ── Step 4: Install systemd services ─────────────────────────────────────────

info "Installing farino-wave systemd service..."
bash "$SCRIPT_DIR/03_setup_service.sh"
ok "Service installed"

# ── Step 5: Reload systemd and start ─────────────────────────────────────────

info "Reloading systemd and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable farino-wave.service
sudo systemctl restart farino-wave.service

echo ""
echo "=== Setup complete ==="
echo ""
echo "Service status:"
sudo systemctl status farino-wave --no-pager || true
echo ""
echo "Follow logs:"
echo "  journalctl -u farino-wave -f"
echo ""
echo "Stop / start:"
echo "  sudo systemctl stop farino-wave"
echo "  sudo systemctl start farino-wave"
echo ""
echo "Dry-run test (no robot connected):"
echo "  sudo docker run --rm --network=host -e FARINO_DRY_RUN=1 farino-wave:latest"
echo ""
echo "Stop wave via ROS2:"
echo "  source /opt/ros/jazzy/setup.bash  # if ROS2 installed natively"
echo "  ros2 service call /wave_node/stop std_srvs/srv/Trigger"
