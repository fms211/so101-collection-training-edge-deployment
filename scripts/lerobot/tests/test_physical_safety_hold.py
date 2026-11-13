"""A recorded physical incident must block motor-facing operations before hardware access."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class TestPhysicalSafetyHold(unittest.TestCase):
    def test_hold_blocks_record_teleop_and_joint_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'PHYSICAL_SAFETY_HOLD.md').write_text('incident')
            with patch.object(flow, 'env', side_effect=lambda name: tmp if name == 'FMS688_DATA' else 'test'), \
                 patch.object(flow, 'hardware') as hardware, patch.object(flow.subprocess, 'run') as process:
                for action in (lambda: flow.run_record(['lerobot-record']),
                               lambda: flow.teleop(False, True), flow.inspect_joints):
                    with self.assertRaisesRegex(RuntimeError, 'PHYSICAL_SAFETY_HOLD'):
                        action()
                hardware.assert_not_called()
                process.assert_not_called()

    def test_no_hold_allows_read_only_guard(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(flow, 'env', return_value=tmp):
            flow.require_physical_clearance()

    def test_incident_read_requires_explicit_tty_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'PHYSICAL_SAFETY_HOLD.md').write_text('incident')
            with patch.object(flow, 'env', return_value=tmp), patch.object(flow.sys.stdin, 'isatty', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'interactive terminal'):
                    flow.authorize_incident_read()
            with patch.object(flow, 'env', return_value=tmp), patch.object(flow.sys.stdin, 'isatty', return_value=True), \
                 patch('builtins.input', return_value='NO'):
                with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                    flow.authorize_incident_read()
            with patch.object(flow, 'env', return_value=tmp), patch.object(flow.sys.stdin, 'isatty', return_value=True), \
                 patch('builtins.input', return_value='READ'):
                flow.authorize_incident_read()
                self.assertTrue((Path(tmp) / 'PHYSICAL_SAFETY_HOLD.md').exists())


if __name__ == '__main__':
    unittest.main()
