"""Filter a real image dataset in a temporary directory without modifying its source."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import filter_episode as filt

class FilterTest(unittest.TestCase):
    def test_real_image_dataset_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'source'
            features = {'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
                        'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]}}
            for name in ('top', 'wrist'):
                features['observation.images.' + name] = {'dtype': 'image', 'shape': (48, 64, 3), 'names': ['height', 'width', 'channels']}
            ds = LeRobotDataset.create('test/source', 30, root=root, features=features, robot_type='so101_follower', image_writer_threads=2, use_videos=False)
            for episode in range(3):
                frame = {'action': np.full(6, episode, dtype=np.float32), 'observation.state': np.zeros(6, dtype=np.float32), 'task': 'test'}
                frame.update({'observation.images.' + name: np.full((48, 64, 3), episode * 30, dtype=np.uint8) for name in ('top', 'wrist')})
                ds.add_frame(frame); ds.save_episode()
            ds.finalize()
            env = {'FMS688_DATA': str(base), 'DATASET_ROOT': str(root), 'DATASET_ID': 'test/source', 'DATASET_VERSION': '20261112_test', 'TASK_DESCRIPTION': 'test', 'FPS': '30', 'TOP_WIDTH': '64', 'TOP_HEIGHT': '48', 'WRIST_WIDTH': '64', 'WRIST_HEIGHT': '48'}
            with patch.dict(os.environ, env), patch.object(sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=['2', '1', 'COPY']), patch.object(filt.collection, 'session', return_value={}):
                before = filt.collection.snapshot()
                filt.main()
                self.assertEqual(before, filt.collection.snapshot())
            out = next((base / 'exports').iterdir())
            info = json.loads((out / 'meta/info.json').read_text())
            self.assertEqual(info['total_episodes'], 2)
            name = 'test/' + out.name.replace('filtered_20261112_test_', 'filtered_')
            # The actual output repo id is independent of the path; a local root is sufficient here.
            reopened = LeRobotDataset(name, root=out)
            self.assertEqual(reopened[0]['action'].tolist(), [0.0] * 6)
            self.assertEqual(reopened[1]['action'].tolist(), [2.0] * 6)
            self.assertEqual(tuple(reopened[1]['observation.images.wrist'].shape), (3, 48, 64))

    def test_real_delete_and_resume_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'dataset'; folder = base / 'rounds/task/day/r01'
            folder.mkdir(parents=True)
            features = {'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
                        'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]}}
            for name in ('top', 'wrist'):
                features['observation.images.' + name] = {'dtype': 'image', 'shape': (48, 64, 3), 'names': ['height', 'width', 'channels']}
            ds = LeRobotDataset.create('test/source', 30, root=root, features=features, robot_type='so101_follower', image_writer_threads=2, use_videos=False)
            def frame(n):
                row = {'action': np.full(6, n, dtype=np.float32), 'observation.state': np.zeros(6, dtype=np.float32), 'task': 'test'}
                row.update({'observation.images.' + name: np.full((48, 64, 3), n * 30, dtype=np.uint8) for name in ('top', 'wrist')})
                return row
            for n in range(3):
                ds.add_frame(frame(n)); ds.save_episode()
            ds.finalize()
            state = {'round':'r01', 'status':'closed', 'start_episode':0, 'target_episodes':3, 'saved_episodes':3}
            (folder/'SESSION.json').write_text(json.dumps(state)); (folder/'ROUND.md').write_text('round=r01\nquality=pass\nstatus=closed\n')
            (folder/'QA.csv').write_text('old qa'); (folder/'VALIDATION.json').write_text('{}')
            env = {'FMS688_DATA':str(base), 'DATASET_ROOT':str(root), 'ROUND_DIR':str(folder), 'DATASET_ID':'test/source', 'DATASET_VERSION':'day',
                   'DATASET_QUARANTINE':str(folder.parent/'DATASET_QUARANTINED.md'), 'DATASET_SEAL':str(folder.parent/'DATASET_SEALED.md'),
                   'TASK_DESCRIPTION':'test', 'FPS':'30', 'TOP_WIDTH':'64', 'TOP_HEIGHT':'48', 'WRIST_WIDTH':'64', 'WRIST_HEIGHT':'48'}
            with patch.dict(os.environ, env), patch.object(filt.collection, 'session', return_value=state.copy()):
                backup = filt.delete_current(1)
                self.assertEqual(json.loads((folder/'SESSION.json').read_text())['saved_episodes'], 2)
                old = LeRobotDataset('test/source', root=backup/'dataset')
                self.assertEqual(len(old), 3)
                resumed = LeRobotDataset.resume('test/source', root=root, image_writer_threads=2)
                resumed.add_frame(frame(3)); resumed.save_episode(); resumed.finalize()
                reopened = LeRobotDataset('test/source', root=root)
                self.assertEqual(len(reopened), 3)
                self.assertEqual([reopened[i]['action'][0].item() for i in range(3)], [0, 2, 3])

if __name__ == '__main__': unittest.main()
