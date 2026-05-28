"""
Thin wrapper around the Fairino Python SDK with a dry-run fallback.

Set FARINO_DRY_RUN=1 to run without a connected robot (logs commands instead).

The SDK (fairino/Robot.py) is pure Python — xmlrpc.client + ctypes from stdlib.
It lives at /home/robotics/fairino_sdk/fairino/Robot.py on the Pi, installed by
provision.sh. No C extension or arm64 compilation needed.
"""

import os
import sys
import time

_DRY_RUN = os.getenv("FARINO_DRY_RUN", "0") == "1"
_SDK_PATH = "/home/robotics/fairino_sdk"

_SDK_AVAILABLE = False
_FairinoRPC = None

if not _DRY_RUN:
    if os.path.isdir(_SDK_PATH) and _SDK_PATH not in sys.path:
        sys.path.insert(0, _SDK_PATH)
    try:
        from fairino import Robot as _FairinoRPC  # noqa: F401
        _SDK_AVAILABLE = True
    except ImportError:
        pass  # SDK not installed — wave_node will warn and use dry-run mode


class FarinoClient:
    """
    Wraps the Fairino SDK for commands and status polling.

    In dry-run mode (no SDK or FARINO_DRY_RUN=1) all methods log their
    intended action and return immediately so the node lifecycle still works.
    """

    ROBOT_IP = "192.168.58.2"

    # Joint positions for the wave sequence (degrees, 6-DOF FR-3).
    # Tune these for your specific robot installation.
    WAVE_SEQUENCE = [
        # label          J1    J2    J3    J4    J5    J6
        ("home",        [0,  -90,   90,    0,   90,    0]),
        ("raise",       [0,  -60,   80,    0,   70,    0]),
        ("wave_right",  [0,  -60,   80,   25,   70,    0]),
        ("wave_left",   [0,  -60,   80,  -25,   70,    0]),
        ("wave_right",  [0,  -60,   80,   25,   70,    0]),
        ("wave_left",   [0,  -60,   80,  -25,   70,    0]),
        ("wave_right",  [0,  -60,   80,   25,   70,    0]),
        ("wave_left",   [0,  -60,   80,  -25,   70,    0]),
        ("home",        [0,  -90,   90,    0,   90,    0]),
    ]

    # Speed percentage and blending time for each move.
    WAVE_SPEED = 30   # percent of max speed
    WAVE_BLEND = 150  # ms — blending window between consecutive moves (smooth motion)
    HOME_BLEND = -1   # block (wait for full stop) at home position

    # Anticollision sensitivity: 1 (least sensitive) – 10 (most sensitive).
    COLLISION_LEVEL = 3

    def __init__(self, logger=None):
        self._robot = None
        self._logger = logger
        self._dry_run = _DRY_RUN or not _SDK_AVAILABLE

    # ── connection / lifecycle ─────────────────────────────────────────────────

    def connect(self, ip: str = ROBOT_IP) -> bool:
        if self._dry_run:
            self._log(f"[DRY-RUN] Would connect to {ip}:8083")
            return True
        try:
            self._robot = _FairinoRPC.RPC(ip)
            return True
        except Exception as exc:
            self._log(f"Connection failed: {exc}", error=True)
            return False

    def enable(self):
        if self._robot:
            self._robot.Mode(0)          # automatic mode
            self._robot.RobotEnable(1)
            # SetAnticollision(mode, level_per_joint[6], config)
            # mode=0: level-based (1–10); level list: same value for all 6 joints; config=0: don't persist
            lvl = float(self.COLLISION_LEVEL)
            self._robot.SetAnticollision(0, [lvl] * 6, 0)
            self._robot.SetCollisionStrategy(0)  # 0=stop on collision
        else:
            self._log("[DRY-RUN] Enable robot, set auto mode, collision level "
                      f"{self.COLLISION_LEVEL}")

    def disable(self):
        if self._robot:
            self._robot.RobotEnable(0)
        else:
            self._log("[DRY-RUN] Disable robot")

    def stop_motion(self):
        if self._robot:
            self._robot.StopMotion()
        else:
            self._log("[DRY-RUN] StopMotion")

    # ── motion ─────────────────────────────────────────────────────────────────

    def move_j(self, joints: list, vel: int = WAVE_SPEED, blend_ms: int = WAVE_BLEND):
        """
        Joint-space move. blend_ms=-1 blocks until motion completes.
        joints: list of 6 floats [J1..J6] in degrees.
        """
        if self._robot:
            # desc_pos, exaxis_pos, offset_pos default to zeros; ovl=100 (full speed scaling)
            self._robot.MoveJ(
                joints, 0, 0,
                vel=float(vel),
                blendT=float(blend_ms),
            )
        else:
            self._log(f"[DRY-RUN] MoveJ {joints} vel={vel}% blend={blend_ms}ms")
            time.sleep(max(0.3, 500 / max(vel, 1) * 0.1))

    # ── status ─────────────────────────────────────────────────────────────────

    def is_estop_or_collision(self) -> bool:
        """Returns True if the robot has a non-zero error (e-stop or collision)."""
        if self._robot:
            ret, codes = self._robot.GetRobotErrorCode()
            if ret != 0:
                return False  # RPC call failed — treat as unknown, not collision
            main_code, sub_code = codes
            return main_code != 0 or sub_code != 0
        return False  # dry-run: never collide

    # ── helpers ────────────────────────────────────────────────────────────────

    def is_dry_run(self) -> bool:
        return self._dry_run

    def _log(self, msg: str, error: bool = False):
        if self._logger is None:
            print(msg)
        elif error:
            self._logger.error(msg)
        else:
            self._logger.info(msg)
