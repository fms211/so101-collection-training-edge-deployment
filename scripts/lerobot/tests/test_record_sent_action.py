"""Exercise the real LeRobot loop with a clipped simulated follower."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock

from lerobot.scripts import lerobot_record
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.teleoperators.teleoperator import Teleoperator

spec = importlib.util.spec_from_file_location('adapter', Path(__file__).resolve().parents[1] / 'record_sent_action.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class TestRecordedAction(unittest.TestCase):
    def test_real_loop_stores_sent_action_and_restores_hooks(self):
        frames = []
        events = {'exit_early': False}
        dataset = SimpleNamespace(fps=30, features={
            'observation.state': {'dtype': 'float32', 'shape': (1,), 'names': ['elbow.pos']},
            'action': {'dtype': 'float32', 'shape': (1,), 'names': ['elbow.pos']}},
            add_frame=frames.append)
        robot = SimpleNamespace(name='so101_follower', get_observation=lambda: {'elbow.pos': 2.0})
        def send(action):
            events['exit_early'] = True
            return {'elbow.pos': 6.0}
        robot.send_action = send
        teleop = MagicMock(spec=Teleoperator)
        teleop.get_action.return_value = {'elbow.pos': 40.0}
        loop, frame = lerobot_record.record_loop, lerobot_record.build_dataset_frame
        try:
            adapter.install(lerobot_record)
            lerobot_record.record_loop(robot=robot, events=events, fps=30,
                teleop_action_processor=lambda pair: pair[0], robot_action_processor=lambda pair: pair[0],
                robot_observation_processor=lambda obs: obs, dataset=dataset, teleop=teleop,
                control_time_s=1, single_task='test')
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]['action'].tolist(), [6.0])
            self.assertIs(robot.send_action, send)
            self.assertIs(lerobot_record.build_dataset_frame, frame)
        finally:
            lerobot_record.record_loop = loop
            lerobot_record.build_dataset_frame = frame

    def test_sent_action_survives_real_dataset_save_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='so101-sent-action-') as tmp:
            root = Path(tmp) / 'dataset'
            features = {
                'observation.state': {'dtype': 'float32', 'shape': (1,), 'names': ['elbow.pos']},
                'action': {'dtype': 'float32', 'shape': (1,), 'names': ['elbow.pos']},
            }
            dataset = LeRobotDataset.create('test/sent_action', 30, root=root, features=features,
                                            robot_type='so101_follower', use_videos=False)
            events = {'exit_early': False}
            robot = SimpleNamespace(name='so101_follower', get_observation=lambda: {'elbow.pos': 2.0})
            def send(action):
                events['exit_early'] = True
                return {'elbow.pos': 6.0}
            robot.send_action = send
            teleop = MagicMock(spec=Teleoperator)
            teleop.get_action.return_value = {'elbow.pos': 40.0}
            loop, frame = lerobot_record.record_loop, lerobot_record.build_dataset_frame
            try:
                adapter.install(lerobot_record)
                lerobot_record.record_loop(robot=robot, events=events, fps=30,
                    teleop_action_processor=lambda pair: pair[0], robot_action_processor=lambda pair: pair[0],
                    robot_observation_processor=lambda obs: obs, dataset=dataset, teleop=teleop,
                    control_time_s=1, single_task='test')
                dataset.save_episode()
                dataset.finalize()
                reopened = LeRobotDataset('test/sent_action', root=root)
                self.assertEqual(reopened[0]['action'].item(), 6.0)
            finally:
                lerobot_record.record_loop = loop
                lerobot_record.build_dataset_frame = frame

    def test_incomplete_sent_action_fails_closed_and_restores_hooks(self):
        events = {'exit_early': False}
        robot = SimpleNamespace(name='so101_follower', get_observation=lambda: {'elbow.pos': 2.0},
                                send_action=lambda action: {})
        send = robot.send_action
        teleop = MagicMock(spec=Teleoperator)
        teleop.get_action.return_value = {'elbow.pos': 40.0}
        loop, frame = lerobot_record.record_loop, lerobot_record.build_dataset_frame
        try:
            adapter.install(lerobot_record)
            with self.assertRaisesRegex(RuntimeError, 'complete sent action'):
                lerobot_record.record_loop(robot=robot, events=events, fps=30,
                    teleop_action_processor=lambda pair: pair[0], robot_action_processor=lambda pair: pair[0],
                    robot_observation_processor=lambda obs: obs, teleop=teleop,
                    control_time_s=1, single_task='test')
            self.assertIs(robot.send_action, send)
            self.assertIs(lerobot_record.build_dataset_frame, frame)
        finally:
            lerobot_record.record_loop = loop
            lerobot_record.build_dataset_frame = frame


if __name__ == '__main__':
    unittest.main()
