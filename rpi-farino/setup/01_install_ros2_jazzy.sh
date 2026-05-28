#!/usr/bin/env bash
# Install ROS2 Jazzy base on Raspberry Pi OS Trixie (arm64).
# Runs inside a Docker ARM64 chroot via provision.sh.
#
# Uses Ubuntu Noble apt packages — same glibc/libstdc++ era as Debian Trixie arm64.
# software-properties-common is Ubuntu-only and not needed; we add the apt source manually.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== [1/5] Base packages ==="
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    python3-pip \
    python3-dev \
    build-essential

# Use C.UTF-8 — universally available, sufficient for ROS2 tooling
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

echo "=== [2/4] ROS2 apt key ==="
mkdir -p /usr/share/keyrings
curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    | gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg

echo "=== [3/4] ROS2 Jazzy apt repo ==="
echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu noble main" \
    > /etc/apt/sources.list.d/ros2.list

apt-get update -qq

echo "=== [4/4] ROS2 Jazzy base + colcon ==="
apt-get install -y --no-install-recommends \
    ros-jazzy-ros-base \
    python3-colcon-common-extensions \
    python3-colcon-core \
    python3-argcomplete

echo "=== Shell profile ==="
BASHRC=/home/robotics/.bashrc
if ! grep -q "ros/jazzy/setup.bash" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "source /opt/ros/jazzy/setup.bash" >> "$BASHRC"
    echo "source ~/ros2_ws/install/setup.bash 2>/dev/null || true" >> "$BASHRC"
fi

echo ""
echo "=== ROS2 Jazzy installed ==="
/opt/ros/jazzy/bin/ros2 --version
