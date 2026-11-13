"""Goal_Position must be initialized to Present before torque is enabled."""
import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class FakeBus:
    def __init__(self, torque=None, fail_goal=False, fail_enable=False):
        self.motors = {'wrist_roll': SimpleNamespace(id=5), 'gripper': SimpleNamespace(id=6)}
        self.torque = {m: 0 for m in self.motors} if torque is None else dict(torque)
        self.present = {'wrist_roll': 2100, 'gripper': 2050}
        self.goal = {m: 0 for m in self.motors}
        self.calls = []
        self.is_connected = False
        self.fail_goal = fail_goal
        self.fail_enable = fail_enable

    def connect(self):
        self.calls.append('connect')
        self.is_connected = True

    def read(self, name, motor, normalize=True):
        self.calls.append(('read', name, motor, normalize))
        if name == 'Torque_Enable':
            return self.torque[motor]
        if name == 'Goal_Position':
            return self.goal[motor]
        raise AssertionError(name)

    def sync_read(self, name, normalize=True):
        self.calls.append(('sync_read', name, normalize))
        return dict(self.present)

    def sync_write(self, name, values, normalize=True):
        self.calls.append(('sync_write', name, dict(values), normalize))
        if name != 'Goal_Position':
            raise AssertionError(name)
        if not self.fail_goal:
            self.goal = dict(values)

    def enable_torque(self, motors=None, num_retry=0):
        self.calls.append('enable_torque')
        if not self.fail_enable:
            self.torque = {m: 1 for m in self.motors}

    def disable_torque(self, motors=None, num_retry=0):
        self.calls.append('disable_torque')
        self.torque = {m: 0 for m in self.motors}

    def disconnect(self, disable_torque=True):
        self.calls.append(('disconnect', disable_torque))
        self.is_connected = False


class TestGoalInitialization(unittest.TestCase):
    def _run(self, bus, answer='HOLD'):
        device = SimpleNamespace(bus=bus)
        module = SimpleNamespace(SO101Follower=lambda cfg: device, SO101FollowerConfig=lambda **kw: kw)
        values = {'FOLLOWER_PORT': 'test', 'FOLLOWER_ID': 'test', 'CALIBRATION_ROOT': '/tmp'}
        with patch.dict(sys.modules, {'lerobot.robots.so_follower': module}), \
             patch.object(flow, 'env', side_effect=lambda name: values[name]), \
             patch.object(flow.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', return_value=answer), \
             patch.object(flow.time, 'sleep'):
            flow.initialize_follower_goal()

    def test_writes_goal_then_enables_torque(self):
        bus = FakeBus()
        self._run(bus)
        self.assertEqual(bus.goal, bus.present)
        self.assertEqual(bus.torque, {'wrist_roll': 1, 'gripper': 1})
        self.assertIn(('sync_write', 'Goal_Position', bus.present, False), bus.calls)
        self.assertIn('enable_torque', bus.calls)
        self.assertEqual(bus.calls[-1], ('disconnect', False))

    def test_aborts_and_disables_if_goal_write_fails(self):
        bus = FakeBus(fail_goal=True)
        with self.assertRaisesRegex(RuntimeError, 'Goal_Position verification failed'):
            self._run(bus)
        self.assertEqual(bus.torque, {'wrist_roll': 0, 'gripper': 0})
        self.assertIn('disable_torque', bus.calls)

    def test_aborts_and_disables_if_torque_enable_fails(self):
        bus = FakeBus(fail_enable=True)
        with self.assertRaisesRegex(RuntimeError, 'Torque enable failed'):
            self._run(bus)
        self.assertEqual(bus.torque, {'wrist_roll': 0, 'gripper': 0})
        self.assertIn('disable_torque', bus.calls)

    def test_requires_hold_confirmation(self):
        bus = FakeBus()
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            self._run(bus, answer='NO')
        self.assertEqual(bus.calls, [])


class TestGoalInitializationPlacement(unittest.TestCase):
    def test_follow_with_cameras_checks_devices_then_starts_visualization(self):
        order = []
        values = {'FMS688_DATA': tempfile.gettempdir(), 'FOLLOWER_PORT': 'f', 'FOLLOWER_ID': 'fid',
                  'LEADER_PORT': 'l', 'LEADER_ID': 'lid', 'FPS': '30', 'CALIBRATION_ROOT': '/cal'}
        cameras = {name: SimpleNamespace(index_or_path=path, width=640, height=480, fps=30, fourcc='MJPG')
                   for name, path in [('top', '/dev/top'), ('wrist', '/dev/wrist')]}
        def run(args, check):
            order.append('process')
            self.assertIn('--display_data=true', args)
            camera_arg = next(arg for arg in args if arg.startswith('--robot.cameras='))
            config = json.loads(camera_arg.split('=', 1)[1])
            self.assertEqual(set(config), {'top', 'wrist'})
            self.assertEqual(config['top']['index_or_path'], '/dev/top')
            self.assertEqual(config['wrist']['index_or_path'], '/dev/wrist')
        with patch.object(flow, 'env', side_effect=lambda name: values[name]), \
             patch.object(flow, 'camera_configs', return_value=cameras), \
             patch.object(flow, 'require_physical_clearance'), \
             patch.object(flow.sys.stdin, 'isatty', return_value=True), \
             patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
             patch.object(flow, 'hardware', side_effect=lambda cameras: order.append(('hardware', cameras))), \
             patch.object(flow, 'initialize_follower_goal', side_effect=lambda: order.append('goal')), \
             patch.object(flow.subprocess, 'run', side_effect=run):
            flow.teleop(True, True)
        self.assertEqual(order, [('hardware', True), 'goal', 'process'])

    def test_teleop_initializes_goal_before_process(self):
        order = []
        values = {'FMS688_DATA': tempfile.gettempdir(), 'FOLLOWER_PORT': 'f', 'FOLLOWER_ID': 'fid',
                  'LEADER_PORT': 'l', 'LEADER_ID': 'lid', 'FPS': '30', 'CALIBRATION_ROOT': '/cal'}
        with patch.object(flow, 'env', side_effect=lambda name: values[name]), \
             patch.object(flow, 'require_physical_clearance'), \
             patch.object(flow.sys.stdin, 'isatty', return_value=True), \
             patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
             patch.object(flow, 'hardware'), \
             patch.object(flow, 'initialize_follower_goal', side_effect=lambda: order.append('goal')), \
             patch.object(flow.subprocess, 'run', side_effect=lambda args, check: order.append('process')):
            flow.teleop(False, True)
        self.assertEqual(order, ['goal', 'process'])

    def test_record_initializes_goal_before_process(self):
        order = []
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing'
            values = {'FMS688_DATA': tmp, 'ROUND_ID': 'r01', 'DATASET_ROOT': str(missing)}
            state = {'status': 'recording', 'start_episode': 0, 'target_episodes': 1, 'saved_episodes': 0}
            with patch.object(flow, 'require_physical_clearance'), \
                 patch.object(flow, 'writable'), \
                 patch.object(flow.sys.stdin, 'isatty', return_value=True), \
                 patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(flow, 'session', return_value=dict(state)), \
                 patch.object(flow, 'count', return_value=0), \
                 patch.object(flow, 'root', return_value=missing), \
                 patch.object(flow, 'validate'), \
                 patch.object(flow, 'hardware'), \
                 patch.object(flow, 'initialize_follower_goal', side_effect=lambda: order.append('goal')), \
                 patch.object(flow, 'write_json'), \
                 patch.object(flow, 'round_dir', return_value=Path(tmp)), \
                 patch.object(flow, 'env', side_effect=lambda name: values.get(name, 'x')), \
                 patch.object(flow.subprocess, 'call', side_effect=lambda cmd: order.append('process') or 0):
                flow.run_record(['lerobot-record'])
        self.assertEqual(order, ['goal', 'process'])


if __name__ == '__main__':
    unittest.main()
