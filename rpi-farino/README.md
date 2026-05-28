# RPI — Farino FR-3 Robot Arm Control

ROS2 Jazzy node that runs on a Raspberry Pi 4B and controls a Fairino FR-3 6-DOF
robot arm over a direct Ethernet connection. Runs in Docker so it works on any
Pi OS (Raspberry Pi OS, Ubuntu, etc.) without native ROS2 installation.

```
Raspberry Pi 4B
  eth0 → 192.168.58.100/24
  ─── direct Ethernet cable ───────────────────────
  FR-3 Control Box  192.168.58.2
```

On every boot, `farino-wave.service` runs the wave node inside Docker:
- Connects to the robot at `192.168.58.2`
- Enables the arm, sets collision sensitivity
- Runs a continuous joint wave sequence
- Safety thread polls `GetRobotErrorCode()` at 10 Hz — stops on any fault

---

## Setup (run on the Pi)

**Requirements:**
- Raspberry Pi 4B (arm64)
- Existing OS: Raspberry Pi OS (bookworm or later), Ubuntu 22.04/24.04, or similar Debian-based
- Internet connection
- sudo access

```bash
git clone https://github.com/Reen06/Bio-Inspired-Robotic-Arm-Hand.git -b RPI
cd Bio-Inspired-Robotic-Arm-Hand/rpi-farino
./setup/setup_on_pi.sh
```

That's it. The script:
1. Installs Docker CE (skips if already installed)
2. Builds the `farino-wave` Docker image natively on the Pi (~3–5 min)
3. Configures `eth0` → `192.168.58.100/24` via systemd-networkd
4. Installs and starts `farino-wave.service` (auto-starts on every boot)

---

## Verify it's working

```bash
# Live logs
journalctl -u farino-wave -f

# Service status
systemctl status farino-wave

# Dry-run test (no robot connected — logs moves instead of sending them)
sudo docker run --rm --network=host -e FARINO_DRY_RUN=1 farino-wave:latest
```

---

## Control

```bash
# Stop the wave loop
sudo systemctl stop farino-wave

# Start it again
sudo systemctl start farino-wave

# Disable auto-start on boot
sudo systemctl disable farino-wave
```

If ROS2 is installed natively on your Pi you can also use the ROS2 interface:

```bash
source /opt/ros/jazzy/setup.bash
ros2 service call /wave_node/stop std_srvs/srv/Trigger
ros2 topic echo /wave_node/status
```

---

## Tuning the wave sequence

Edit `ros2_ws/src/farino_wave/farino_wave/farino_client.py`, then rebuild and restart:

```bash
sudo docker build -t farino-wave:latest ros2_ws/
sudo systemctl restart farino-wave
```

Key parameters:

```python
WAVE_SEQUENCE = [
    # label       J1   J2   J3   J4   J5   J6  (degrees)
    ("home",      [0, -90,  90,   0,  90,   0]),
    ("raise",     [0, -60,  80,   0,  70,   0]),
    ("wave_right",[0, -60,  80,  25,  70,   0]),
    ("wave_left", [0, -60,  80, -25,  70,   0]),
    # ... repeats 3×, then returns home
]
WAVE_SPEED      = 30    # % of max speed
WAVE_BLEND      = 150   # ms blending between moves
COLLISION_LEVEL = 3     # 1 (soft) – 10 (hard)
```

---

## Directory layout

```
rpi-farino/
  README.md
  ros2_ws/
    Dockerfile                   ← arm64 image: ros:jazzy-ros-base + farino_wave
    entrypoint.sh
    fairino_sdk/Robot.py         ← Fairino pure-Python SDK (bundled)
    src/farino_wave/
      farino_wave/
        farino_client.py         ← SDK wrapper + dry-run fallback
        wave_node.py             ← ROS2 node: wave loop + safety thread
  setup/
    setup_on_pi.sh               ← run this on the Pi to install everything
    02_configure_network.sh      ← eth0 static IP
    03_setup_service.sh          ← systemd unit
  docs/
    architecture.md              ← network layout, joint table, ROS2 interface
    future-isaac-lab.md          ← Phase 2: TorchScript policy + MoveIt2
```

---

## Robot connection details

| Parameter | Value |
|-----------|-------|
| Robot IP | `192.168.58.2` |
| Pi eth0 IP | `192.168.58.100/24` |
| SDK | Fairino Python SDK (`Robot.RPC`) — pure Python, no compilation |
| Protocol | XML-RPC + CNDE socket |

The Fairino SDK (`ros2_ws/fairino_sdk/Robot.py`) is bundled — no separate download needed.

---

## Further reading

- `docs/architecture.md` — full network layout, ROS2 interface, useful commands
- `docs/future-isaac-lab.md` — Phase 2: replace wave sequence with an Isaac Lab TorchScript policy
