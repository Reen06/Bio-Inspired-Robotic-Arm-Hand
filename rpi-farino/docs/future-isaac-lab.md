# Future: Isaac Lab Policy Node

Installed at: `/home/robotics/plans/future-isaac-lab.md`

## Overview

Phase 2 replaces (or supplements) the hard-coded wave sequence with a neural
policy trained in Isaac Lab. The policy takes the current joint state as input
and outputs joint position targets at ~50 Hz.

## How to Add

1. **Train a policy in Isaac Lab** on the FR-3 URDF → export as `policy.pt`
   (TorchScript via `torch.jit.script` or `torch.jit.trace`).

2. **Copy the model to the Pi:**
   ```bash
   rpi put ros-farino policy.pt /home/robotics/policy.pt
   ```

3. **Create a new ROS2 package** `farino_isaaclab` in `ros2_ws/src/`:
   ```
   farino_isaaclab/
     policy_node.py    ← loads policy.pt, runs inference loop
     package.xml
     setup.py
   ```

4. **`policy_node.py` outline:**
   ```python
   import torch
   from farino_wave.farino_client import FarinoClient

   class PolicyNode(Node):
       def __init__(self):
           super().__init__("policy_node")
           self._model = torch.jit.load("/home/robotics/policy.pt")
           self._model.eval()
           self._client = FarinoClient(logger=self.get_logger())

       def _inference_loop(self):
           rate = 50  # Hz
           while self._running:
               start = time.time()
               obs = self._get_observation()        # joint pos + vel from robot
               with torch.no_grad():
                   action = self._model(obs)         # → target joint positions
               self._client.move_j(action.tolist(), vel=80, blend_ms=20)
               elapsed = time.time() - start
               time.sleep(max(0, 1/rate - elapsed))
   ```

5. **Add a new systemd service** `farino-policy.service` (same pattern as
   `farino-wave.service`) or modify provision.sh step 7 to point at
   `policy_node` instead of `wave_node`.

## Dependencies to Add on Pi

```bash
pip3 install torch --index-url https://download.pytorch.org/whl/cpu
# or use the Pi-optimized wheel from https://torch.kmtea.eu/whl/stable.html
```

## Isaac Lab FR-3 Setup

- URDF/XACRO for FR-3: available in frcobot_ros2 package (fairino3 model)
- Isaac Lab environment: use `DirectRLEnv` or `ManagerBasedRLEnv`
- Observation space: joint positions [6] + joint velocities [6] + goal [3+]
- Action space: joint position deltas [6] or absolute targets [6]

## frcobot_ros2 (MoveIt2 Integration)

For more sophisticated path planning (collision-aware trajectories, workspace
constraints), the `frcobot_ros2` package from the Farino Docs provides a full
MoveIt2 hardware interface. Install it alongside `farino_wave` in the same
workspace:

```bash
# On the Pi
cd ~/ros2_ws/src
cp -r "/path/to/frcobot_ros2-main" .
cd ~/ros2_ws
colcon build --packages-select fairino_hardware_v3_9_6 fairino_msgs fairino3_moveit2_config
```

Then the Isaac Lab policy node can send `JointTrajectory` messages to MoveIt2
instead of calling `FarinoClient.move_j()` directly.
