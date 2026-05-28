# RPI — Farino FR-3 Robot Arm Control on Raspberry Pi 4B

This directory contains everything needed to provision a Raspberry Pi 4B image
that auto-starts a ROS2 Jazzy node controlling a Fairino FR-3 6-DOF robot arm
over a direct Ethernet connection.

```
Raspberry Pi 4B
  eth0 → 192.168.58.100/24
  ─── direct Ethernet cable ───────────────────────
  FR-3 Control Box  192.168.58.2  (Fairino SDK port)
```

On every boot the Pi runs `farino-wave.service` inside Docker, which:
1. Connects to the robot at `192.168.58.2`
2. Enables the arm and sets collision sensitivity
3. Runs a continuous wrist-wave joint sequence
4. Stops immediately if an e-stop or collision is detected (10 Hz safety poll)

---

## Directory layout

```
rpi-farino/
  README.md                      ← this file
  ros2_ws/
    Dockerfile                   ← arm64 image: ros:jazzy-ros-base + farino_wave
    entrypoint.sh                ← sources ROS2 + workspace before CMD
    fairino_sdk/                 ← Fairino pure-Python SDK (Robot.py)
    src/farino_wave/             ← ROS2 package
      farino_wave/
        farino_client.py         ← SDK wrapper with dry-run fallback
        wave_node.py             ← ROS2 node: wave loop + safety thread
  setup/
    provision.sh                 ← master host-side provisioning script
    01_install_ros2_jazzy.sh     ← (reference only — not used; ROS2 runs in Docker)
    02_configure_network.sh      ← writes eth0 static IP inside Pi image
    03_setup_service.sh          ← installs farino-wave systemd units
  docs/
    architecture.md              ← network layout, joint table, ROS2 interface
    future-isaac-lab.md          ← Phase 2: TorchScript policy + MoveIt2
```

---

## Host requirements (Linux only)

| Dependency | Install |
|------------|---------|
| Docker with buildx | `sudo apt install docker.io` then `docker buildx version` |
| QEMU binfmt (arm64 emulation) | `sudo apt install qemu-user-static binfmt-support` then `docker run --rm --platform linux/arm64 ubuntu:24.04 uname -m` → should print `aarch64` |
| `losetup` / `mount` | Standard Linux (util-linux — already installed) |
| `sudo` access | Required for losetup, mount, chroot |

Verify binfmt is registered:

```bash
sudo update-binfmts --enable
docker run --rm --platform linux/arm64 ubuntu:24.04 uname -m   # → aarch64
```

---

## Getting a base Pi image

Download **Raspberry Pi OS Lite (64-bit)** — the Debian Trixie / bookworm arm64 variant:

```bash
# Download from raspberrypi.com/software/operating-systems/
# Choose: Raspberry Pi OS Lite (64-bit)
# Flash or extract the .img file — do NOT boot it yet; provision.sh handles setup.
```

You need the raw `.img` file (not the `.img.xz` archive — decompress first):

```bash
xz -dk 2024-xx-xx-raspios-bookworm-arm64-lite.img.xz
```

---

## Provisioning

Run once on the host to bake the ROS2 Docker image and systemd services into
the Pi `.img` file. This does **not** require booting the Pi.

```bash
cd rpi-farino
./setup/provision.sh /path/to/raspios-arm64-lite.img
```

What it does:
1. Builds `farino-wave:latest` (arm64 Docker image) via `docker buildx` — ~10 min first run
2. Saves the image as a `.tar.gz`
3. Mounts the Pi `.img` via `losetup` (no boot needed)
4. Creates the `robotics` user (password: `farino`)
5. Installs Docker CE on the Pi (from the official Docker apt repo)
6. Copies the Docker image tar to `/home/robotics/farino-wave.tar.gz`
7. Writes `eth0` static IP config (`192.168.58.100/24`)
8. Installs and enables `farino-wave-load` and `farino-wave` systemd services
9. Copies docs to `/home/robotics/plans/`

---

## Flashing to an SD card

```bash
# Find your SD card device (e.g. /dev/sdb — double-check with lsblk)
sudo dd if=/path/to/raspios-arm64-lite.img of=/dev/sdX bs=4M status=progress conv=fsync
```

Or use **Raspberry Pi Imager** → Custom OS → select the `.img` file.

---

## First boot

1. Insert SD card, connect `eth0` to the FR-3 control box (direct cable)
2. Power on — first boot takes ~2–3 min (Docker image load from the tar)
3. Check service status (SSH in via another interface or serial console):

```bash
systemctl status farino-wave-load farino-wave
journalctl -u farino-wave -f
```

Expected output: `wave_node` connecting to `192.168.58.2` and logging joint moves.

---

## Testing without a robot

Set `FARINO_DRY_RUN=1` — the node runs the full loop but logs moves instead of
sending them to the robot:

```bash
# On the Pi (or any arm64 Docker host)
docker run --rm --network=host -e FARINO_DRY_RUN=1 farino-wave:latest

# Or if ROS2 is installed natively
FARINO_DRY_RUN=1 ros2 run farino_wave wave_node
```

---

## ROS2 interface

| Topic / Service | Type | Description |
|-----------------|------|-------------|
| `/wave_node/status` | `std_msgs/String` | `waving` / `stopped` / `error: …` |
| `/wave_node/stop` | `std_srvs/Trigger` | Stop the wave loop gracefully |

```bash
# On the Pi
ros2 service call /wave_node/stop std_srvs/srv/Trigger
ros2 topic echo /wave_node/status
```

---

## Robot connection details

| Parameter | Value |
|-----------|-------|
| Robot IP | `192.168.58.2` |
| Pi eth0 IP | `192.168.58.100/24` |
| SDK | Fairino Python SDK (`Robot.RPC`) |
| Protocol | XML-RPC + CNDE socket |

The Fairino SDK (`ros2_ws/fairino_sdk/Robot.py`) is pure Python — it uses
`xmlrpc.client` and `ctypes` from the standard library. No compilation needed
on arm64.

---

## Wave sequence (tunable)

Edit `ros2_ws/src/farino_wave/farino_wave/farino_client.py`:

```python
WAVE_SEQUENCE = [
    # label       J1   J2   J3   J4   J5   J6  (degrees)
    ("home",      [0, -90,  90,   0,  90,   0]),
    ("raise",     [0, -60,  80,   0,  70,   0]),
    ("wave_right",[0, -60,  80,  25,  70,   0]),
    ("wave_left", [0, -60,  80, -25,  70,   0]),
    # ...
]
WAVE_SPEED = 30    # % of max speed
WAVE_BLEND = 150   # ms blending between moves
```

After editing, re-run `provision.sh` to rebuild the Docker image and reprovision.

---

## Credentials

| Pi user | `robotics` |
|---------|-----------|
| Password | `farino` |
| sudo | passwordless |

---

## Further reading

- `docs/architecture.md` — full network layout, joint sequence table, useful commands
- `docs/future-isaac-lab.md` — Phase 2: replace wave sequence with an Isaac Lab TorchScript policy
