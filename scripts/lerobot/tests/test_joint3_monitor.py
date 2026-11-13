import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import contextlib
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('joint3_monitor', Path(__file__).resolve().parents[1]/'joint3_monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class TestMonitor(unittest.TestCase):
    def test_diagnostic_keeps_guards_and_limits_duration(self):
        collection_spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1]/'collection.py')
        flow = importlib.util.module_from_spec(collection_spec)
        collection_spec.loader.exec_module(flow)
        with tempfile.TemporaryDirectory() as tmp:
            def env(name): return tmp if name == 'FMS688_DATA' else 'test'
            with patch.object(flow, 'env', side_effect=env), patch.object(flow.sys.stdin, 'isatty', return_value=True), \
                 patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(flow, 'hardware') as preflight, patch.object(flow, 'initialize_follower_goal') as init, \
                 patch.object(flow.subprocess, 'run') as launch:
                flow.teleop(False, True, diagnose_joint3=True)
                preflight.assert_called_once_with(False)
                init.assert_called_once()
                args = launch.call_args.args[0]
                self.assertIn('--teleop_time_s=10', args)
                self.assertTrue(any(x.startswith('--robot.max_relative_target=') for x in args))
                self.assertIn('SO101_JOINT3_LOG', launch.call_args.kwargs['env'])

    def test_records_target_sent_actual_and_raw_telemetry(self):
        calls = []
        class Bus:
            def read(self, register, motor, normalize=True):
                calls.append((register, motor, normalize))
                return {'Present_Position': 12.0, 'Present_Load': 23, 'Present_Voltage': 50,
                        'Present_Current': 25, 'Status': 0}[register]
        rows = []
        robot = SimpleNamespace(bus=Bus())
        def send(device, action):
            return {'elbow_flex.pos': 14.0}
        wrapped = monitor.wrap_send_action(send, rows.append, interval=0)
        result = wrapped(robot, {'elbow_flex.pos': 30.0})
        self.assertEqual(result['elbow_flex.pos'], 14.0)
        self.assertEqual(rows[0][1:], (30.0, 14.0, 12.0, 23, 50, 25, 0))
        self.assertEqual({x[0] for x in calls}, {'Present_Position', 'Present_Load', 'Present_Voltage',
                                                 'Present_Current', 'Status'})


if __name__ == '__main__':
    unittest.main()
