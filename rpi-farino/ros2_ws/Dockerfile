FROM ros:jazzy-ros-base

# Install colcon (not included in ros-base)
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        python3-colcon-common-extensions \
        python3-colcon-core && \
    rm -rf /var/lib/apt/lists/*

# Fairino pure-Python SDK (arm64-compatible, no C extension needed)
# Copy SDK files under fairino/ so "from fairino import Robot" resolves.
COPY fairino_sdk/ /home/robotics/fairino_sdk/fairino/
RUN touch /home/robotics/fairino_sdk/fairino/__init__.py

# Build the farino_wave ROS2 package
WORKDIR /ros2_ws
COPY src/ src/
RUN bash -c "\
    source /opt/ros/jazzy/setup.bash && \
    colcon build --packages-select farino_wave --symlink-install && \
    rm -rf build/ log/"

# Custom entrypoint that sources both ROS2 and the workspace
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "run", "farino_wave", "wave_node"]
