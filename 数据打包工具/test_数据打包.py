"""Temporary LeRobot dataset packaging and integrity checks; no hardware or network."""
import csv
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

SCRIPT = Path(__file__).with_name('打包数据.py')
spec = importlib.util.spec_from_file_location('so101_package', SCRIPT)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='so101-pack-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'fms688_data'
        self.out = Path(self.temp.name) / 'out'
        (self.root / 'locks').mkdir(parents=True)
        self.out.mkdir()
        self.task = 'pick_test'
        self.version = '20261112_pick_test'
        self.repo = 'test/so101_pick_test'
        self.dataset = self.root / 'datasets' / self.task / self.version
        self.rounds = self.root / 'rounds' / self.task / self.version
        self.round = self.rounds / 'r01'
        self.round.mkdir(parents=True)
        features = {
            'action': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
            'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': [f'joint{i}' for i in range(6)]},
        }
        for camera in ('top', 'wrist'):
            features[f'observation.images.{camera}'] = {
                'dtype': 'image', 'shape': (48, 64, 3), 'names': ['height', 'width', 'channels']}
        ds = LeRobotDataset.create(self.repo, 30, root=self.dataset, features=features,
                                   robot_type='so101_follower', use_videos=False, image_writer_threads=2)
        for i in range(3):
            frame = {'action': np.full(6, i, dtype=np.float32),
                     'observation.state': np.full(6, i + 1, dtype=np.float32), 'task': 'pick'}
            for camera in ('top', 'wrist'):
                frame[f'observation.images.{camera}'] = np.full((48, 64, 3), 30 * i, dtype=np.uint8)
            ds.add_frame(frame)
        ds.save_episode()
        ds.finalize()
        state = {'round': 'r01', 'status': 'closed', 'repo_id': self.repo,
                 'fingerprint': 'a' * 64, 'start_episode': 0, 'target_episodes': 1, 'saved_episodes': 1}
        (self.round / 'SESSION.json').write_text(json.dumps(state), encoding='utf-8')
        (self.round / 'ROUND.md').write_text(
            f'round=r01\ntask={self.task}\nversion={self.version}\ndataset_id={self.repo}\n'
            f'dataset_root={self.dataset}\nquality=pass\nstatus=closed\n', encoding='utf-8')
        with (self.round / 'QA.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['episode', 'item', 'result', 'privacy', 'notes'])
            writer.writeheader()
            writer.writerow({'episode': 0, 'item': 'cube', 'result': 'pass', 'privacy': 'pass', 'notes': ''})
        hashes = {}
        for folder in ('meta', 'data', 'images', 'videos'):
            for path in (self.dataset / folder).rglob('*'):
                if path.is_file():
                    hashes[str(path.relative_to(self.dataset))] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.round / 'VALIDATION.json').write_text(
            json.dumps({'total_episodes': 1, 'files': hashes}), encoding='utf-8')

    def make_package(self):
        return package.create_package(self.root, self.task, self.version, self.out)

    def test_real_dataset_roundtrip_and_external_checksum(self):
        archive, checksum, repo = self.make_package()
        self.assertEqual(repo, self.repo)
        subprocess.run(['sha256sum', '-c', checksum.name], cwd=self.out, check=True,
                       stdout=subprocess.DEVNULL)
        unpacked = Path(self.temp.name) / 'unpacked'
        unpacked.mkdir()
        with tarfile.open(archive, 'r:') as tar:
            tar.extractall(unpacked, filter='data')
        ds = LeRobotDataset(self.repo, root=unpacked / 'datasets' / self.task / self.version)
        self.assertEqual(len(ds), 3)
        self.assertEqual(ds[2]['action'].tolist(), [2.0] * 6)
        self.assertEqual(tuple(ds[2]['observation.images.top'].shape), (3, 48, 64))
        self.assertEqual(tuple(ds[2]['observation.images.wrist'].shape), (3, 48, 64))
        self.assertTrue((unpacked / 'rounds' / self.task / self.version / 'r01' / 'QA.csv').is_file())
        manifest = json.loads((unpacked / 'BUNDLE_MANIFEST.json').read_text())
        self.assertEqual(manifest['episodes'], 1)
        self.assertEqual(manifest['repo_id'], self.repo)
        server = Path(self.temp.name) / 'server'
        server.mkdir()
        helper = SCRIPT.with_name('服务器_校验解包.py')
        system_python = '/usr/bin/python3' if Path('/usr/bin/python3').exists() else sys.executable
        process = subprocess.run([system_python, str(helper), str(archive), '--destination', str(server)],
                                 check=True, capture_output=True, text=True)
        self.assertIn('SHA-256 和文件校验通过', process.stdout)
        imported = next(server.iterdir())
        self.assertFalse((imported / 'IMPORT_INCOMPLETE.txt').exists())
        imported_ds = LeRobotDataset(self.repo, root=imported / 'datasets' / self.task / self.version)
        self.assertEqual(imported_ds[2]['action'].tolist(), [2.0] * 6)

    def test_server_rejects_damaged_archive_before_extracting(self):
        archive, _, _ = self.make_package()
        with archive.open('r+b') as stream:
            stream.seek(1024)
            old = stream.read(1)
            stream.seek(1024)
            stream.write(bytes([old[0] ^ 1]))
        server = Path(self.temp.name) / 'server'
        server.mkdir()
        helper = SCRIPT.with_name('服务器_校验解包.py')
        result = subprocess.run([sys.executable, str(helper), str(archive), '--destination', str(server)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('数据包校验失败', result.stderr)
        self.assertEqual(list(server.iterdir()), [])

    def test_unfinished_round_is_refused(self):
        path = self.round / 'SESSION.json'
        state = json.loads(path.read_text())
        state['status'] = 'needs_review'
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(package.PackageError, '尚未关闭'):
            self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_menu_selects_dataset_and_creates_archive(self):
        answers = f'1\n{self.out}\nYES\n0\n'
        result = subprocess.run([sys.executable, str(SCRIPT), '--data-root', str(self.root)],
                                input=answers, text=True, capture_output=True, check=True)
        self.assertIn('打包并校验完成', result.stdout)
        self.assertEqual(len(list(self.out.glob('*.tar'))), 1)
        self.assertEqual(len(list(self.out.glob('*.tar.sha256'))), 1)

    def test_failed_archive_verification_removes_partial_output(self):
        with patch.object(package, 'verify_archive', side_effect=package.PackageError('simulated archive failure')):
            with self.assertRaisesRegex(package.PackageError, 'simulated archive failure'):
                self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_modified_data_requires_new_qa(self):
        (self.dataset / 'meta' / 'stats.json').write_text('{}')
        with self.assertRaisesRegex(package.PackageError, '审核后发生变化'):
            self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_busy_dataset_is_not_packaged(self):
        name = hashlib.sha256(str(self.dataset).encode()).hexdigest() + '.lock'
        with (self.root / 'locks' / name).open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(package.PackageError, '正在采集或审核'):
                self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_quarantine_is_refused(self):
        (self.rounds / 'DATASET_QUARANTINED.md').write_text('quarantined')
        with self.assertRaisesRegex(package.PackageError, '隔离状态'):
            self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_symlink_and_leftover_images_are_refused(self):
        extra = self.dataset / 'images' / 'orphan.png'
        extra.parent.mkdir(exist_ok=True)
        extra.write_bytes(b'not an episode')
        with self.assertRaisesRegex(package.PackageError, '临时图片'):
            self.make_package()
        extra.unlink()
        (self.dataset / 'badlink').symlink_to(self.dataset / 'meta')
        with self.assertRaisesRegex(package.PackageError, '符号链接'):
            self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_qa_rejection_and_not_enough_space(self):
        qa = self.round / 'QA.csv'
        qa.write_text('episode,item,result,privacy,notes\n0,cube,pending,pass,\n')
        with self.assertRaisesRegex(package.PackageError, '审核未通过'):
            self.make_package()
        qa.write_text('episode,item,result,privacy,notes\n0,cube,pass,pass,\n')
        with patch.object(package.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 1})()):
            with self.assertRaisesRegex(package.PackageError, '输出空间不足'):
                self.make_package()
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
