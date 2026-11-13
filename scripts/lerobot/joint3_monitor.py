"""Wrap the existing LeRobot teleop command to sample joint 3 without a second serial reader."""
import csv
import os
from pathlib import Path
import time


def wrap_send_action(original, emit, interval=0.2):
    last = 0.0
    def monitored(robot, action):
        nonlocal last
        sent = original(robot, action)
        now = time.monotonic()
        if now - last >= interval:
            bus = robot.bus
            present = bus.read('Present_Position', 'elbow_flex', normalize=True)
            load = bus.read('Present_Load', 'elbow_flex', normalize=False)
            voltage = bus.read('Present_Voltage', 'elbow_flex', normalize=False)
            current = bus.read('Present_Current', 'elbow_flex', normalize=False)
            status = bus.read('Status', 'elbow_flex', normalize=False)
            emit((now, action['elbow_flex.pos'], sent['elbow_flex.pos'], present, load, voltage, current, status))
            last = now
        return sent
    return monitored


def main():
    from lerobot.robots.so_follower.so_follower import SOFollower
    from lerobot.scripts import lerobot_teleoperate
    output = Path(os.environ['SO101_JOINT3_LOG'])
    with output.open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['monotonic_s', 'target_deg', 'sent_deg', 'present_deg', 'load_register',
                         'voltage_register', 'current_register', 'status_register'])
        original = SOFollower.send_action
        SOFollower.send_action = wrap_send_action(original, writer.writerow)
        try:
            lerobot_teleoperate.main()
        finally:
            SOFollower.send_action = original


if __name__ == '__main__':
    main()
