import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wizard', ROOT / 'configure_collection.py')
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)

class TestWizard(unittest.TestCase):
    def test_new_task_and_resume_and_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config.env'
            config.write_text((ROOT / 'fms688.env.example').read_text())
            with patch.dict(os.environ, {'FMS688_DATA': str(root), 'DATASET_NAMESPACE': 'fms688', 'HF_REPO_ID': ''}), patch.object(wizard.sys.stdin, 'isatty', return_value=True):
                with patch('builtins.input', side_effect=['', 'pick_items', '', '', 'YES']):
                    self.assertTrue(wizard.main(str(config)))
                version = wizard.datetime.date.today().strftime('%Y%m%d') + '_pick_items'
                text = config.read_text()
                self.assertIn('DATASET_VERSION=' + version, text)
                self.assertIn('EPISODES_THIS_ROUND=40', text)
                self.assertFalse((root / 'datasets' / 'pick_items' / version).exists())
                folder = root / 'rounds' / 'pick_items' / version / 'r01'
                folder.mkdir(parents=True)
                (folder / 'ROUND.md').write_text('task_description=' + wizard.DESCRIPTION + '\n')
                state = {'round':'r01', 'status':'recording', 'target_episodes':40, 'repo_id': f'fms688/so101_{version}'}
                (folder / 'SESSION.json').write_text(json.dumps(state))
                with patch('builtins.input', side_effect=['1', 'YES']):
                    self.assertTrue(wizard.main(str(config)))
                state['status'] = 'closed'
                (folder / 'SESSION.json').write_text(json.dumps(state))
                with patch('builtins.input', side_effect=['1', '55', 'YES']):
                    self.assertTrue(wizard.main(str(config)))
                self.assertIn('ROUND_ID=r02', config.read_text())
                self.assertIn('EPISODES_THIS_ROUND=55', config.read_text())

    def test_invalid_task_rejected(self):
        with self.assertRaises(ValueError): wizard.validate_task('../bad')

    def test_preserves_hub_id_and_rejects_existing_identity_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config.env'
            config.write_text((ROOT / 'fms688.env.example').read_text().replace('HF_REPO_ID=""', 'HF_REPO_ID="fms688/arm101_desktop_collection"'))
            env = {'FMS688_DATA': str(root), 'DATASET_NAMESPACE': 'fms688', 'HF_REPO_ID': 'fms688/arm101_desktop_collection'}
            with patch.dict(os.environ, env), patch.object(wizard.sys.stdin, 'isatty', return_value=True):
                with patch('builtins.input', side_effect=['', 'pick_items', '', '', 'YES']):
                    self.assertTrue(wizard.main(str(config)))
                self.assertIn('HF_REPO_ID="fms688/arm101_desktop_collection"', config.read_text())
                version = wizard.datetime.date.today().strftime('%Y%m%d') + '_pick_items'
                folder = root / 'rounds' / 'pick_items' / version / 'r01'
                folder.mkdir(parents=True)
                (folder / 'ROUND.md').write_text('task_description=' + wizard.DESCRIPTION + '\n')
                (folder / 'SESSION.json').write_text(json.dumps({'round': 'r01', 'status': 'ready', 'target_episodes': 40, 'repo_id': f'fms688/so101_{version}'}))
                before = config.read_text()
                with patch('builtins.input', return_value='1'), self.assertRaisesRegex(ValueError, '数据集 ID'):
                    wizard.main(str(config))
                self.assertEqual(config.read_text(), before)

if __name__ == '__main__': unittest.main()
