# Farino FR-3 ROS2 Control — Architecture

Installed at: `/home/robotics/plans/architecture.md`

## System Layout

```
Raspberry Pi 4B  (this device)
  eth0 → 192.168.58.100/24

  ~/ros2_ws/src/farino_wave/
    wave_node.py        ← main node (auto-starts via systemd)
    farino_client.py    ← SDK wrapper / dry-run fallback

  ~/fairino_sdk/        ← Fairino Python SDK (fairino/ package + libfairino/)
  ~/plans/              ← this documentation

  systemd: farino-wave.service

  ─── Ethernet cable ──────────────────────────────────
  FR-3 Control Box   192.168.58.2   TCP port 8083 (status)
                                    SDK command port (handled by SDK)
```

## ROS2 Interface

| Topic / Service        | Type                  | Description                         |
|------------------------|-----------------------|-------------------------------------|
| `/wave_node/status`    | `std_msgs/String`     | Current state: waving / stopped / error |
| `/wave_node/stop`      | `std_srvs/Trigger`    | Stop the wave loop gracefully       |

## Robot Connection

The Farino FR-3 uses the **Fairino Python SDK** (`Robot.RPC('192.168.58.2')`).

The SDK connects to the robot's control box over Ethernet. Port 8083 is the
real-time status feedback port (100 ms interval); the command port is handled
by the SDK internally.

**If libfairino.so is not arm64-compatible**, the node logs a warning and runs
in dry-run mode (motion commands are logged, not executed). Request arm64
binaries from Fairino support or compile from source.

## Wave Sequence

Joint positions in degrees for a 6-DOF wrist wave (tune for your installation):

| Step       | J1 | J2  | J3  | J4  | J5 | J6 |
|------------|-----|-----|-----|-----|----|----|
| home       | 0  | -90 | 90  | 0   | 90 | 0  |
| raise      | 0  | -60 | 80  | 0   | 70 | 0  |
| wave right | 0  | -60 | 80  | +25 | 70 | 0  |
| wave left  | 0  | -60 | 80  | -25 | 70 | 0  |
| (×3 wave)  |    |     |     |     |    |    |
| home       | 0  | -90 | 90  | 0   | 90 | 0  |

Speed: 30%, blending: 150 ms. Adjust in `farino_client.py:WAVE_SEQUENCE`.

## Collision Safety

- `SetAnticollision(3)` — level 3 (1=soft, 10=hard); set in `farino_client.py`
- `SetCollisionStrategy(0)` — robot stops automatically on collision
- Safety thread polls `GetRobotErrorCode()` at 10 Hz; non-zero → stop

## Useful Commands

```bash
# Check wave node logs
journalctl -u farino-wave -f

# Stop / start the service
systemctl stop farino-wave
systemctl start farino-wave

# Manual dry-run test (no robot needed)
FARINO_DRY_RUN=1 ros2 run farino_wave wave_node

# Stop wave via ROS2 service
ros2 service call /wave_node/stop std_srvs/srv/Trigger

# Watch status topic
ros2 topic echo /wave_node/status
```

## File Locations

| Path | Purpose |
|------|---------|
| `~/ros2_ws/src/farino_wave/` | ROS2 package source |
| `~/ros2_ws/install/farino_wave/` | Built package |
| `~/fairino_sdk/` | Fairino Python SDK |
| `~/plans/` | This documentation |
| `/etc/systemd/network/20-robot-eth.network` | eth0 static IP config |
| `/etc/systemd/system/farino-wave.service` | Systemd service unit |
