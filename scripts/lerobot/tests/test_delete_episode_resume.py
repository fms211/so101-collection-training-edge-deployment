"""Deleting from current round must preserve backups and reopen review."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import filter_episode as editor

class DeleteResumeTest(unittest.TestCase):
    def test_sealed_dataset_is_rejected_before_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            seal = base / 'DATASET_SEALED.md'; seal.write_text('sealed')
            env = {'DATASET_ROOT':str(base / 'data'), 'ROUND_DIR':str(base / 'r01'),
                   'DATASET_QUARANTINE':str(base / 'DATASET_QUARANTINED.md'), 'DATASET_SEAL':str(seal)}
            with patch.dict(os.environ, env), patch.object(editor.collection, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(editor.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'sealed'):
                    editor.delete_current(0)
                run.assert_not_called()

    def test_failed_commit_leaves_backup_and_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); source = base / 'dataset'; folder = base / 'rounds/r01'
            source.mkdir(); folder.mkdir(parents=True)
            (source / 'sentinel').write_text('old')
            state = {'round':'r01', 'status':'needs_review', 'start_episode':0, 'saved_episodes':2, 'target_episodes':3}
            (folder / 'SESSION.json').write_text(json.dumps(state)); (folder / 'ROUND.md').write_text('round=r01\n')
            env = {'FMS688_DATA':str(base), 'DATASET_ROOT':str(source), 'ROUND_DIR':str(folder), 'DATASET_ID':'test/data',
                   'DATASET_QUARANTINE':str(folder.parent/'DATASET_QUARANTINED.md'), 'DATASET_SEAL':str(folder.parent/'DATASET_SEALED.md')}
            def run(args, check):
                stage = Path(next(a.split('=',1)[1] for a in args if a.startswith('--new_root=')))
                stage.mkdir(); (stage / 'sentinel').write_text('new')
            def validate():
                return {'total_episodes': 2 if (Path(os.environ['DATASET_ROOT'])/'sentinel').read_text() == 'old' else 1}
            with patch.dict(os.environ, env), patch.object(editor.collection, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(editor.collection, 'session', return_value=state.copy()), patch.object(editor.collection, 'validate', side_effect=validate), \
                 patch.object(editor.collection, 'snapshot', return_value={'mock':'hash'}), patch.object(editor.subprocess, 'run', side_effect=run), \
                 patch.object(editor.collection, 'write_json', side_effect=OSError('simulated interruption')):
                with self.assertRaisesRegex(OSError, 'simulated interruption'):
                    editor.delete_current(0)
            self.assertTrue(Path(env['DATASET_QUARANTINE']).is_file())
            backup = next((base / 'backups').iterdir())
            self.assertEqual((backup / 'dataset/sentinel').read_text(), 'old')
            self.assertEqual(json.loads((backup / 'round/SESSION.json').read_text()), state)

    def test_delete_current_reopens_round_and_retains_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); source = base / 'datasets/task/day'; folder = base / 'rounds/task/day/r01'
            source.mkdir(parents=True); folder.mkdir(parents=True)
            (source / 'sentinel').write_text('old')
            (folder / 'ROUND.md').write_text('round=r01\nquality=pass\nstatus=closed\n')
            state = {'round':'r01', 'status':'closed', 'start_episode':0, 'saved_episodes':3, 'target_episodes':3}
            (folder / 'SESSION.json').write_text(json.dumps(state))
            (folder / 'QA.csv').write_text('old qa')
            (folder / 'VALIDATION.json').write_text('{}')
            env = {'FMS688_DATA':str(base), 'DATASET_ROOT':str(source), 'ROUND_DIR':str(folder), 'DATASET_ID':'test/data', 'DATASET_VERSION':'day', 'DATASET_QUARANTINE':str(folder.parent/'DATASET_QUARANTINED.md'), 'DATASET_SEAL':str(folder.parent/'DATASET_SEALED.md')}
            def run(args, check):
                output = Path(next(a.split('=',1)[1] for a in args if a.startswith('--new_root=')))
                output.mkdir(); (output / 'sentinel').write_text('new')
            def validate():
                return {'total_episodes': 3 if (Path(os.environ['DATASET_ROOT'])/'sentinel').read_text() == 'old' else 2}
            with patch.dict(os.environ, env), patch.object(editor.collection, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(editor.collection, 'session', return_value=state.copy()), patch.object(editor.collection, 'validate', side_effect=validate), \
                 patch.object(editor.collection, 'snapshot', return_value={'mock':'hash'}), patch.object(editor.subprocess, 'run', side_effect=run):
                backup = editor.delete_current(1)
            self.assertEqual((source / 'sentinel').read_text(), 'new')
            self.assertEqual((backup / 'dataset/sentinel').read_text(), 'old')
            updated = json.loads((folder / 'SESSION.json').read_text())
            self.assertEqual(updated['saved_episodes'], 2)
            self.assertEqual(updated['target_episodes'], 3)
            self.assertEqual(updated['status'], 'needs_review')
            self.assertFalse((folder / 'VALIDATION.json').exists())
            self.assertFalse((folder / 'QA.csv').exists())
            self.assertIn('quality=pending', (folder / 'ROUND.md').read_text())
            self.assertFalse(Path(env['DATASET_QUARANTINE']).exists())

if __name__ == '__main__': unittest.main()
