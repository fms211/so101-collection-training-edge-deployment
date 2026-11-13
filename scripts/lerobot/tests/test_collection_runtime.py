"""Real LeRobot disk/image integration; hardware and network remain mocked."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from lerobot.configs.dataset import DatasetRecordConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collection', SCRIPTS/'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class CollectionIntegration(unittest.TestCase):
    def setUp(self):
        # This suite mocks hardware; the startup Goal=Present guard is covered by test_goal_init.py.
        patcher = patch.object(flow, 'initialize_follower_goal')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_clean_empty_first_dataset_can_resume_without_deleting_files(self):
        with tempfile.TemporaryDirectory(prefix='so101-empty-resume-') as tmp:
            base = Path(tmp)
            cfg = (SCRIPTS/'fms688.env.example').read_text().replace(
                'FMS688_DATA="$HOME/fms688_data"', f'FMS688_DATA="{base}/data"')
            cfg = cfg.replace('="640"', '="64"').replace('="480"', '="48"')
            config = base/'config.env'
            config.write_text(cfg)
            raw = subprocess.check_output(['bash', '-c', 'source "$1/lib.sh"; load_config "$2"; env -0',
                                           'test', str(SCRIPTS), str(config)])
            values = dict(s.decode().split('=', 1) for s in raw.split(b'\0') if s)
            with patch.dict(os.environ, values):
                subprocess.run(['bash', str(SCRIPTS/'init_round.sh'), '--config', str(config)], check=True)
                features = {'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
                            'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]}}
                for name in ('top', 'wrist'):
                    features[f'observation.images.{name}'] = {'dtype': 'image', 'shape': (48, 64, 3),
                                                              'names': ['height', 'width', 'channels']}
                def start_then_fail_before_first_frame(command):
                    self.assertNotIn('--resume=true', command)
                    dataset = LeRobotDataset.create(flow.env('DATASET_ID'), 30, root=flow.root(),
                                                    features=features, robot_type='so101_follower', use_videos=False)
                    dataset.finalize()
                    return 1

                with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(flow, 'hardware'), \
                     patch.object(flow.subprocess, 'call', side_effect=start_then_fail_before_first_frame):
                    with self.assertRaisesRegex(RuntimeError, 'no episodes saved'):
                        flow.run_record(['lerobot-record'])
                self.assertEqual(flow.session()['status'], 'needs_review')
                self.assertEqual(flow.session()['saved_episodes'], 0)
                info_path = flow.root()/'meta/info.json'
                original_info = info_path.read_bytes()
                external = base/'outside.txt'
                external.write_text('outside data')
                link = flow.root()/'unexpected-link'
                link.symlink_to(external)
                with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(flow, 'hardware'), \
                     patch.object(flow.subprocess, 'call') as recording:
                    with self.assertRaisesRegex(RuntimeError, 'symlink'):
                        flow.run_record(['lerobot-record'])
                    recording.assert_not_called()
                self.assertEqual(external.read_text(), 'outside data')
                link.unlink()
                stray = flow.root()/'images/leftover.png'
                stray.parent.mkdir()
                stray.write_bytes(b'preserve me')
                with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(flow, 'hardware'), \
                     patch.object(flow.subprocess, 'call') as recording:
                    with self.assertRaisesRegex(RuntimeError, 'orphan|extra'):
                        flow.run_record(['lerobot-record'])
                    recording.assert_not_called()
                self.assertEqual(stray.read_bytes(), b'preserve me')
                stray.unlink()

                def resume_and_record(command):
                    self.assertIn('--resume=true', command)
                    self.assertEqual(info_path.read_bytes(), original_info)
                    ds = LeRobotDataset.resume(flow.env('DATASET_ID'), root=flow.root(), image_writer_threads=2)
                    for i in range(3):
                        frame = {'action': np.zeros(6, dtype=np.float32),
                                 'observation.state': np.zeros(6, dtype=np.float32),
                                 'task': flow.env('TASK_DESCRIPTION')}
                        frame.update({f'observation.images.{name}': np.zeros((48, 64, 3), dtype=np.uint8)
                                      for name in ('top', 'wrist')})
                        ds.add_frame(frame)
                    ds.save_episode()
                    ds.finalize()
                    return 0

                with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(flow, 'hardware'), \
                     patch.object(flow.subprocess, 'call', side_effect=resume_and_record):
                    flow.run_record(['lerobot-record'])
                self.assertEqual(flow.count(), 1)
                self.assertEqual(flow.session()['saved_episodes'], 1)
                flow.validate()

    def test_camera_identity_rejects_builtin_and_duplicate_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            top, wrist = Path(tmp)/'top', Path(tmp)/'wrist'
            top.touch()
            wrist.touch()
            with patch.dict(os.environ, {'TOP_CAMERA':str(top), 'WRIST_CAMERA':str(wrist)}):
                with patch.object(flow.subprocess, 'check_output', return_value='ID_VENDOR_ID=5959\nID_MODEL_ID=0107\n'):
                    with self.assertRaisesRegex(RuntimeError, 'built-in'):
                        flow.camera_identity()
                wrist.unlink()
                wrist.symlink_to(top)
                with self.assertRaisesRegex(RuntimeError, 'same device'):
                    flow.camera_identity()

    def test_real_create_resume_review_and_retry_upload(self):
        with tempfile.TemporaryDirectory(prefix='so101-integration-') as tmp:
            base = Path(tmp)
            cfg = (SCRIPTS/'fms688.env.example').read_text().replace('FMS688_DATA="$HOME/fms688_data"', f'FMS688_DATA="{base}/data"')
            cfg = cfg.replace('="640"', '="64"').replace('="480"', '="48"')
            cfg = cfg.replace('EPISODES_THIS_ROUND="5"', 'EPISODES_THIS_ROUND="7"')
            cfg = cfg.replace('HF_REPO_ID=""', 'HF_REPO_ID="fms688/arm101_desktop_collection"')
            config = base/'config.env'
            config.write_text(cfg)
            raw = subprocess.check_output(['bash', '-c', 'source "$1/lib.sh"; load_config "$2"; env -0', 'test', str(SCRIPTS), str(config)])
            values = dict(s.decode().split('=', 1) for s in raw.split(b'\0') if s)
            with patch.dict(os.environ, values):
                subprocess.run(['bash', str(SCRIPTS/'init_round.sh'), '--config', str(config)], check=True)
                self.assertFalse(flow.root().exists(), 'init must not create the dataset directory')
                original_task = flow.env('TASK_DESCRIPTION')
                with patch.dict(os.environ, {'TASK_DESCRIPTION': 'a different task'}):
                    with self.assertRaisesRegex(RuntimeError, 'Configuration changed'):
                        flow.session()
                self.assertEqual(flow.env('TASK_DESCRIPTION'), original_task)
                with flow.lock():
                    with self.assertRaisesRegex(RuntimeError, 'Another recording'):
                        with flow.lock():
                            pass
                identity = DatasetRecordConfig(repo_id=flow.env('DATASET_ID'), no_stamp=True)
                identity.stamp_repo_id()
                self.assertEqual(identity.repo_id, 'fms688/arm101_desktop_collection')
                dry = subprocess.check_output(['bash', str(SCRIPTS/'record_round.sh'), '--config', str(config), '--dry-run'], text=True)
                self.assertIn('--dataset.no_stamp=true', dry)
                self.assertIn('--dataset.repo_id=fms688/arm101_desktop_collection', dry)
                self.assertIn('--dataset.video=false', dry)
                features = {'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
                            'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]}}
                features.update({f'observation.images.{n}': {'dtype': 'image', 'shape': (48, 64, 3), 'names': ['height', 'width', 'channels']}
                                 for n in ['top', 'wrist']})
                ds = LeRobotDataset.create(identity.repo_id, 30, root=flow.root(), features=features,
                    robot_type='so101_follower', image_writer_threads=2, use_videos=False)

                def episode(dataset):
                    for i in range(3):
                        frame = {'action': np.zeros(6, dtype=np.float32), 'observation.state': np.zeros(6, dtype=np.float32),
                                 'task': flow.env('TASK_DESCRIPTION')}
                        frame.update({f'observation.images.{n}': np.full((48, 64, 3), i*40, dtype=np.uint8) for n in ['top', 'wrist']})
                        dataset.add_frame(frame)
                    dataset.save_episode()

                episode(ds)
                ds.finalize()
                self.assertEqual(flow.count(), 1)
                self.assertTrue(list((flow.root()/'data').rglob('*.parquet')))
                self.assertFalse((flow.root()/'videos').exists())
                stray = flow.root()/'videos'/'stray.mp4'
                stray.parent.mkdir()
                stray.write_bytes(b'unexpected')
                with self.assertRaisesRegex(RuntimeError, 'Unexpected video files'):
                    flow.validate()
                stray.unlink()
                flow.validate()
                with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(flow, 'hardware'), patch.object(flow.subprocess, 'call', return_value=1) as called:
                    with self.assertRaisesRegex(RuntimeError, 'Recording exited'):
                        flow.run_record(['lerobot-record', '--dataset.num_episodes=7'])
                    self.assertIn('--dataset.num_episodes=6', called.call_args.args[0])
                    self.assertIn('--resume=true', called.call_args.args[0])
                self.assertEqual(flow.session()['status'], 'needs_review')
                resumed = LeRobotDataset.resume(identity.repo_id, root=flow.root(), image_writer_threads=2)
                for _ in range(6):
                    episode(resumed)
                resumed.finalize()
                flow.review()
                with self.assertRaisesRegex(RuntimeError, 'human'):
                    flow.close_round()
                with (flow.round_dir()/'QA.csv').open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=['episode','item','result','privacy','notes'])
                    writer.writeheader()
                    for i, item in enumerate(['鼠标','充电宝','U盘','带帽笔','剪刀','胶带卷','纸巾']):
                        writer.writerow({'episode':i,'item':item,'result':'pass','privacy':'pass','notes':'synthetic test only'})
                flow.close_round()
                self.assertEqual(flow.session()['status'], 'closed')
                with patch.object(sys.stdin, 'isatty', return_value=True):
                    with self.assertRaisesRegex(RuntimeError, 'already closed'):
                        flow.run_record(['lerobot-record'])
                Path(flow.env('DATASET_SEAL')).write_text('sealed')
                with self.assertRaisesRegex(RuntimeError, 'sealed'):
                    flow.writable()
                Path(flow.env('DATASET_SEAL')).unlink()
                Path(flow.env('DATASET_QUARANTINE')).write_text('quarantine')
                with self.assertRaisesRegex(RuntimeError, 'quarantined'):
                    flow.writable()
                Path(flow.env('DATASET_QUARANTINE')).unlink()

                class FakeApi:
                    fail = True
                    sha = 'base'
                    tags = {}
                    def whoami(self): return {'name':'fms688'}
                    def dataset_info(self, repo, **kw):
                        if kw.get('files_metadata'):
                            return SimpleNamespace(sha=self.sha, siblings=[SimpleNamespace(rfilename=p,size=(flow.root()/p).stat().st_size) for p in flow.snapshot()])
                        return SimpleNamespace(private=False,sha=self.tags.get(kw.get('revision'),self.sha),siblings=[SimpleNamespace(rfilename='README.md')])
                    def list_repo_refs(self, repo, **kw):
                        return SimpleNamespace(tags=[SimpleNamespace(name=n,target_commit=c) for n,c in self.tags.items()])
                    def create_tag(self, repo, tag, revision, **kw): self.tags[tag] = revision
                    def delete_tag(self, repo, tag, **kw): del self.tags[tag]
                    def create_commit(self, **kw):
                        self.paths = [op.path_in_repo for op in kw['operations']]
                        if self.fail: raise ConnectionError('simulated offline')
                        self.sha = 'test-commit'
                        return SimpleNamespace(oid='test-commit')
                api = FakeApi()
                with self.assertRaises(ConnectionError): flow.upload(api)
                self.assertFalse((flow.round_dir()/'UPLOAD.json').exists())
                api.fail = False
                with patch.object(api, 'create_tag', side_effect=ConnectionError('tag update interrupted')):
                    with self.assertRaises(ConnectionError): flow.upload(api)
                self.assertFalse((flow.round_dir()/'UPLOAD.json').exists())
                flow.upload(api)
                self.assertNotIn('README.md', api.paths)
                self.assertTrue(any(path.startswith('data/') and path.endswith('.parquet') for path in api.paths))
                self.assertFalse(any(path.startswith('videos/') for path in api.paths))
                self.assertFalse(flow.read_json(flow.round_dir()/'UPLOAD.json')['browser_verified'])
                self.assertEqual(api.tags['v3.0'], 'test-commit')
                self.assertEqual(flow.count(),7)
                with (flow.root()/'meta/info.json').open('a') as stream: stream.write(' ')
                with self.assertRaisesRegex(RuntimeError, 'Data changed'):
                    flow.upload(api)


if __name__ == '__main__':
    unittest.main()
