"""
wave_node — ROS2 node that waves the Farino FR-3 arm and stops on collision.

Runs as a standalone node (auto-starts the wave loop on boot).
Set FARINO_DRY_RUN=1 to test without a connected robot.

ROS2 interface:
  ~/stop  (std_srvs/Trigger)  — stop the wave loop gracefully
  ~/status (std_msgs/String)   — current node state (waving / stopped / error)
"""

import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger

from farino_wave.farino_client import FarinoClient

# Safety thread poll interval (seconds)
_SAFETY_HZ = 10


class WaveNode(Node):
    def __init__(self):
        super().__init__("wave_node")

        self._client = FarinoClient(logger=self.get_logger())
        self._running = False
        self._wave_thread = None
        self._safety_thread = None

        # ROS2 interface
        self._status_pub = self.create_publisher(String, "~/status", 10)
        self._stop_srv = self.create_service(Trigger, "~/stop", self._stop_callback)

        if self._client.is_dry_run():
            self.get_logger().warn(
                "SDK not available or FARINO_DRY_RUN=1 — running in dry-run mode. "
                "No robot will move."
            )

    # ── public ─────────────────────────────────────────────────────────────────

    def start(self):
        self.get_logger().info("Connecting to robot...")
        if not self._client.connect():
            self._publish_status("error: connection failed")
            return

        self._client.enable()
        self._running = True

        self._safety_thread = threading.Thread(
            target=self._safety_loop, daemon=True, name="safety"
        )
        self._safety_thread.start()

        self._wave_thread = threading.Thread(
            target=self._wave_loop, daemon=True, name="wave"
        )
        self._wave_thread.start()
        self.get_logger().info("Wave demo started.")

    def stop(self, reason: str = "requested"):
        if not self._running:
            return
        self._running = False
        self._client.stop_motion()
        self._client.disable()
        self._publish_status(f"stopped: {reason}")
        self.get_logger().info(f"Wave node stopped ({reason})")

    # ── loops ──────────────────────────────────────────────────────────────────

    def _wave_loop(self):
        seq = self._client.WAVE_SEQUENCE
        speed = self._client.WAVE_SPEED
        blend = self._client.WAVE_BLEND

        while self._running:
            for label, joints in seq:
                if not self._running:
                    break
                self.get_logger().debug(f"Move → {label}")
                # last step (return to home) blocks to ensure clean position
                b = self._client.HOME_BLEND if label == "home" else blend
                self._client.move_j(joints, vel=speed, blend_ms=b)

            if self._running:
                self._publish_status("waving")

    def _safety_loop(self):
        while self._running:
            time.sleep(1.0 / _SAFETY_HZ)
            if not self._running:
                break
            if self._client.is_estop_or_collision():
                self.get_logger().error(
                    "E-stop or collision detected — stopping immediately."
                )
                self.stop(reason="collision")
                break

    # ── ROS2 callbacks ─────────────────────────────────────────────────────────

    def _stop_callback(self, _request, response):
        self.stop(reason="service call")
        response.success = True
        response.message = "Wave node stopped"
        return response

    def _publish_status(self, state: str):
        msg = String()
        msg.data = state
        self._status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = WaveNode()

    node.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop(reason="shutdown")
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
