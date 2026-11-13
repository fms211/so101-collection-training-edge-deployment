"""Exercise LeRobot's stop-and-save path using simulated hardware and real disk data."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from lerobot.configs.dataset import DatasetRecordConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.robots.so_follower import SO101FollowerConfig
from lerobot.scripts import lerobot_record
from lerobot.teleoperators.so_leader import SO101LeaderConfig
from lerobot.utils.keyboard_input import apply_recording_control


class FakeDevice:
    name = 'so101_follower'
    cameras = {'top': object(), 'wrist': object()}
    action_features = {}
    observation_features = {}
    is_connected = False

    def connect(self):
        self.is_connected = True

    def disconnect(self):
        self.is_connected = False


class TestStopAndSave(unittest.TestCase):
    def test_quit_saves_current_episode_and_finalizes_for_reopening(self):
        self.check_scenario('quit_during_record')

    def test_quit_during_reset_saves_previous_episode(self):
        self.check_scenario('quit_during_reset')

    def test_rerecord_discards_first_episode_before_quit(self):
        self.check_scenario('rerecord')

    def test_quit_before_first_frame_keeps_empty_dataset_recoverable(self):
        self.check_scenario('quit_empty')

    def check_scenario(self, scenario):
        features = {
            'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
            'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
        }
        for camera in ('top', 'wrist'):
            features[f'observation.images.{camera}'] = {
                'dtype': 'image', 'shape': (48, 64, 3), 'names': ['height', 'width', 'channels']}
        robot, teleop = FakeDevice(), FakeDevice()
        events = {'exit_early': False, 'rerecord_episode': False, 'stop_recording': False}
        calls = []

        def simulate_capture(**kwargs):
            dataset = kwargs.get('dataset')
            calls.append('record' if dataset is not None else 'reset')
            if dataset is None:
                if scenario == 'quit_during_reset':
                    apply_recording_control('esc', events)
                else:
                    self.assertTrue(events['rerecord_episode'])
                    events['exit_early'] = False
                return
            for index in range(0 if scenario == 'quit_empty' else 3):
                marker = index + (10 if scenario == 'rerecord' and calls.count('record') == 1 else 0)
                frame = {'action': np.full(6, marker, dtype=np.float32),
                         'observation.state': np.full(6, index, dtype=np.float32), 'task': 'test'}
                frame.update({f'observation.images.{name}': np.full((48, 64, 3), index * 40, dtype=np.uint8)
                              for name in ('top', 'wrist')})
                dataset.add_frame(frame)
            if scenario == 'rerecord' and calls.count('record') == 1:
                apply_recording_control('left', events)
            elif scenario == 'quit_during_reset':
                apply_recording_control('right', events)
                events['exit_early'] = False  # consumed by the real record loop
            else:
                apply_recording_control('esc', events)

        with tempfile.TemporaryDirectory(prefix='so101-stop-test-') as tmp:
            root = Path(tmp) / 'dataset'
            cfg = lerobot_record.RecordConfig(
                robot=SO101FollowerConfig(port='/dev/null'), teleop=SO101LeaderConfig(port='/dev/null'),
                dataset=DatasetRecordConfig(repo_id='test/stop', root=root, fps=30, single_task='test',
                                            num_episodes=3, video=False, push_to_hub=False, no_stamp=True),
                display_data=False, play_sounds=False)
            with patch.object(lerobot_record, 'make_robot_from_config', return_value=robot), \
                 patch.object(lerobot_record, 'make_teleoperator_from_config', return_value=teleop), \
                 patch.object(lerobot_record, 'make_default_processors', return_value=(object(), object(), object())), \
                 patch.object(lerobot_record, 'aggregate_pipeline_dataset_features', return_value={}), \
                 patch.object(lerobot_record, 'combine_feature_dicts', return_value=features), \
                 patch.object(lerobot_record, 'init_keyboard_listener', return_value=(None, events)), \
                 patch.object(lerobot_record, 'record_loop', side_effect=simulate_capture):
                if scenario == 'quit_empty':
                    with self.assertRaisesRegex(ValueError, 'add one or several frames'):
                        lerobot_record.record(cfg)
                else:
                    lerobot_record.record(cfg)
            self.assertFalse(robot.is_connected)
            self.assertFalse(teleop.is_connected)
            if scenario == 'quit_empty':
                resumed = LeRobotDataset.resume('test/stop', root=root, image_writer_threads=2)
                for i in range(3):
                    frame = {'action': np.full(6, i, dtype=np.float32),
                             'observation.state': np.zeros(6, dtype=np.float32), 'task': 'test'}
                    frame.update({f'observation.images.{name}': np.zeros((48, 64, 3), dtype=np.uint8)
                                  for name in ('top', 'wrist')})
                    resumed.add_frame(frame)
                resumed.save_episode()
                resumed.finalize()
            reopened = LeRobotDataset('test/stop', root=root)
            self.assertEqual(len(reopened), 3)
            self.assertEqual(reopened.meta.total_episodes, 1)
            self.assertEqual(tuple(reopened[2]['observation.images.top'].shape), (3, 48, 64))
            self.assertEqual(tuple(reopened[2]['observation.images.wrist'].shape), (3, 48, 64))
            self.assertEqual(reopened[2]['action'].tolist(), [2.0] * 6)
            expected = {'quit_during_record': ['record'], 'quit_during_reset': ['record', 'reset'],
                        'rerecord': ['record', 'reset', 'record'], 'quit_empty': ['record']}
            self.assertEqual(calls, expected[scenario])


if __name__ == '__main__':
    unittest.main()
