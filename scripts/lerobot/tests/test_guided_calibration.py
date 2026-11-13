"""Calibration backups and torque checks, using a fake bus only."""
import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class Bus:
    def __init__(self, torque=0):
        self.motors = {'elbow': object()}
        self.torque = torque
        self.is_connected = False
        self.is_calibrated = True
    def connect(self): self.is_connected = True
    def read(self, *args, **kwargs): return self.torque
    def disconnect(self, disable_torque=True): self.is_connected = False


class GuidedCalibrationTest(unittest.TestCase):
    def run_calibration(self, root, torque=0):
        bus = Bus(torque)
        called = []
        device = SimpleNamespace(bus=bus, calibrate=lambda: called.append(True))
        module = SimpleNamespace(SO101Follower=lambda cfg: device, SO101FollowerConfig=lambda **kw: kw)
        leader = SimpleNamespace(SO101Leader=lambda cfg: device, SO101LeaderConfig=lambda **kw: kw)
        values = {'FMS688_DATA': str(root), 'CALIBRATION_ROOT': str(root / 'cal'),
                  'FOLLOWER_PORT': 'f', 'FOLLOWER_ID': 'fid'}
        with patch.dict(sys.modules, {'lerobot.robots.so_follower': module, 'lerobot.teleoperators.so_leader': leader}), \
             patch.object(flow, 'env', side_effect=lambda key: values[key]), \
             patch.object(flow.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='CALIBRATE'), \
             patch.object(flow, 'hardware'), patch.object(flow, 'lock', return_value=contextlib.nullcontext()):
            try:
                flow.guided_calibration('follower')
            finally:
                self.assertFalse(bus.is_connected)
        return called

    def test_existing_calibration_backed_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'cal/robots/so_follower/fid.json'
            path.parent.mkdir(parents=True)
            path.write_text('original')
            self.assertEqual(self.run_calibration(root), [True])
            self.assertEqual([p.read_text() for p in (root / 'calibration-backups').glob('*.json')], ['original'])

    def test_enabled_torque_aborts_before_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, 'Torque must already be disabled'):
                self.run_calibration(Path(temp), torque=1)

    def test_incident_hold_blocks_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'PHYSICAL_SAFETY_HOLD.md').write_text('hold')
            with patch.object(flow, 'env', return_value=str(root)), self.assertRaisesRegex(RuntimeError, 'PHYSICAL_SAFETY_HOLD'):
                flow.guided_calibration('follower')


if __name__ == '__main__':
    unittest.main()
