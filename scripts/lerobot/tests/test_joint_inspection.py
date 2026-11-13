"""Read-only servo diagnostics: fake buses ensure no write or torque command is used."""
import importlib.util
import contextlib
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
    is_connected = False
    motors = {'wrist_roll': SimpleNamespace(id=5)}

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def connect(self):
        self.calls.append('connect')
        self.is_connected = True

    def sync_read(self, name, normalize):
        self.calls.append(('sync_read', name, normalize))
        if self.fail:
            raise OSError('read failed')
        return {'wrist_roll': 2100}

    def read(self, name, motor, normalize):
        self.calls.append(('read', name, motor, normalize))
        return 0

    def read_calibration(self):
        self.calls.append('read_calibration')
        return {'wrist_roll': SimpleNamespace(range_min=0, range_max=4095, homing_offset=10)}

    def disconnect(self, disable_torque=True):
        self.calls.append(('disconnect', disable_torque))
        self.is_connected = False


class TestJointInspection(unittest.TestCase):
    def test_leader_only_never_reads_follower_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'PHYSICAL_SAFETY_HOLD.md').write_text('incident')
            leader = SimpleNamespace(bus=object(), calibration={})
            follower = SimpleNamespace(bus=object(), calibration={})
            leader_module = SimpleNamespace(SO101Leader=lambda cfg: leader, SO101LeaderConfig=lambda **kw: kw)
            follower_module = SimpleNamespace(SO101Follower=lambda cfg: follower, SO101FollowerConfig=lambda **kw: kw)
            def env(name):
                return tmp if name in ('FMS688_DATA', 'CALIBRATION_ROOT') else 'test'
            with patch.dict(sys.modules, {'lerobot.robots.so_follower': follower_module,
                                          'lerobot.teleoperators.so_leader': leader_module}), \
                 patch.object(flow, 'env', side_effect=env), patch.object(flow.sys.stdin, 'isatty', return_value=True), \
                 patch('builtins.input', return_value='READ'), patch.object(flow, 'hardware'), \
                 patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(flow, 'read_joint_bus', return_value={}) as reader:
                flow.inspect_joints(incident_read_only=True, arm='leader')
            reader.assert_called_once_with(leader.bus)

    def test_detects_range_and_offset_discrepancies_without_assuming_physical_alignment(self):
        readback = {'wrist_roll': {'id': 5, 'position_raw': 2100, 'torque_enabled': 0,
                                   'range_min': 0, 'range_max': 4095, 'homing_offset': 10}}
        saved = {'wrist_roll': SimpleNamespace(id=5, range_min=0, range_max=4095, homing_offset=10)}
        self.assertEqual(flow.compare_joint_calibration(readback, saved), [])
        saved['wrist_roll'].homing_offset = 11
        saved['wrist_roll'].range_max = 4000
        diffs = flow.compare_joint_calibration(readback, saved)
        self.assertEqual({item[1] for item in diffs}, {'homing_offset', 'range_max'})
        self.assertEqual(diffs[0][0], 'wrist_roll')

    def test_read_only_and_preserves_torque_on_disconnect(self):
        bus = FakeBus()
        snapshot = flow.read_joint_bus(bus)
        self.assertEqual(snapshot['wrist_roll']['position_raw'], 2100)
        self.assertEqual(snapshot['wrist_roll']['torque_enabled'], 0)
        self.assertEqual(bus.calls, ['connect', ('sync_read', 'Present_Position', False),
                                     ('read', 'Torque_Enable', 'wrist_roll', False), 'read_calibration',
                                     ('disconnect', False)])

    def test_error_still_closes_without_writing_torque(self):
        bus = FakeBus(fail=True)
        with self.assertRaisesRegex(OSError, 'read failed'):
            flow.read_joint_bus(bus)
        self.assertEqual(bus.calls[-1], ('disconnect', False))
        self.assertFalse(bus.is_connected)


if __name__ == '__main__':
    unittest.main()
