"""Incident calibration must not use the follower's torque-enabling connect path."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1]/'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class FakeBus:
    motors = {'wrist_flex': SimpleNamespace(id=4), 'wrist_roll': SimpleNamespace(id=5)}
    is_connected = False
    is_calibrated = True

    def __init__(self, torque=0):
        self.torque = torque
        self.calls = []

    def connect(self):
        self.calls.append('bus.connect')
        self.is_connected = True

    def read(self, name, motor, normalize):
        self.calls.append(('read', name, motor, normalize))
        return self.torque

    def disconnect(self, disable_torque=True):
        self.calls.append(('disconnect', disable_torque))
        self.is_connected = False


class FakeFollower:
    def __init__(self, torque=0, fail=False):
        self.bus = FakeBus(torque)
        self.fail = fail
        self.calibrated = False

    def calibrate(self):
        self.bus.calls.append('calibrate')
        if self.fail:
            raise RuntimeError('calibration failed')
        self.calibrated = True

    def connect(self, **kwargs):
        raise AssertionError('follower.connect would re-enable torque')


class TestFollowerCalibrationGuard(unittest.TestCase):
    def test_uses_bus_directly_and_preserves_torque_state_on_disconnect(self):
        follower = FakeFollower()
        flow.calibrate_follower_torque_off(follower)
        self.assertTrue(follower.calibrated)
        self.assertEqual(follower.bus.calls[0], 'bus.connect')
        self.assertEqual(follower.bus.calls[-1], ('disconnect', False))
        self.assertEqual(follower.bus.calls.count('calibrate'), 1)

    def test_refuses_if_torque_enabled_and_disconnects_without_writes(self):
        follower = FakeFollower(torque=1)
        with self.assertRaisesRegex(RuntimeError, 'Torque'):
            flow.calibrate_follower_torque_off(follower)
        self.assertFalse(follower.calibrated)
        self.assertEqual(follower.bus.calls[-1], ('disconnect', False))

    def test_error_during_calibration_still_disconnects_without_enabling_torque(self):
        follower = FakeFollower(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'calibration failed'):
            flow.calibrate_follower_torque_off(follower)
        self.assertEqual(follower.bus.calls[-1], ('disconnect', False))


if __name__ == '__main__':
    unittest.main()
