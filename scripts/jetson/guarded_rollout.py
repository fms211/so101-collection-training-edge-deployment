#!/usr/bin/env python3
"""Run LeRobot rollout with the collection workflow's follower startup guard."""
import argparse
import importlib.util
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-physical', action='store_true')
    parser.add_argument('--collection', required=True, help='Path to collection.py')
    args, rollout_args = parser.parse_known_args()
    if not args.confirm_physical:
        parser.error('real robot operation requires --confirm-physical')
    if not sys.stdin.isatty():
        parser.error('an onsite interactive terminal is required')
    spec = importlib.util.spec_from_file_location('so101_collection', Path(args.collection))
    flow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow)
    from lerobot.robots.so_follower import SO101Follower
    from lerobot.scripts.lerobot_rollout import main as rollout_main

    original_connect = SO101Follower.connect
    original_send = SO101Follower.send_action
    connected = []
    reported = [0.0]
    joints = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll')

    def guarded_connect(robot, *a, **kw):
        if robot.config.port != flow.env('FOLLOWER_PORT') or robot.config.id != flow.env('FOLLOWER_ID'):
            raise RuntimeError('rollout robot identity differs from startup guard')
        flow.initialize_follower_goal()
        connected.append(robot)
        return original_connect(robot, *a, **kw)

    def guarded_send(robot, action):
        sent = original_send(robot, action)
        now = time.monotonic()
        if now - reported[0] < 1.0:
            return sent
        reported[0] = now
        positions = robot.bus.sync_read('Present_Position', normalize=True)
        details = ' '.join(f'{joint}:当前={positions[joint]:.1f},目标={sent[f"{joint}.pos"]:.1f}'
                           for joint in joints if f'{joint}.pos' in sent)
        print(f'关节跟随 {details}', flush=True)
        return sent

    SO101Follower.connect = guarded_connect
    SO101Follower.send_action = guarded_send
    sys.argv = ['lerobot-rollout', *rollout_args]
    try:
        rollout_main()
    finally:
        SO101Follower.connect = original_connect
        SO101Follower.send_action = original_send
        for robot in connected:
            if robot.bus.is_connected:
                try:
                    robot.bus.disable_torque()
                finally:
                    robot.bus.disconnect(disable_torque=False)


if __name__ == '__main__':
    main()
