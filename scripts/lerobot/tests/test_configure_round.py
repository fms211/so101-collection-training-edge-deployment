"""Guided round configuration must preserve data and reject conflicting sessions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('configure_round', Path(__file__).resolve().parents[1] / 'configure_round.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class TestRoundConfiguration(unittest.TestCase):
    def test_replace_exactly_two_assignments(self):
        text = '# preserve\nROUND_ID="r01"\nEPISODES_THIS_ROUND="7"\nOTHER="$HOME/example"\n'
        updated = config.update_text(text, 'r02', '10')
        self.assertIn('ROUND_ID=r02\n', updated)
        self.assertIn('EPISODES_THIS_ROUND=10\n', updated)
        self.assertIn('OTHER="$HOME/example"\n', updated)
        self.assertIn('# preserve\n', updated)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            config.update_text(text + 'ROUND_ID="r03"\n', 'r02', '10')

    def test_rejects_unsafe_and_invalid_values(self):
        for round_id, episodes in [('r1', '3'), ('r02;touch /tmp/x', '3'), ('r02', '0'), ('r02', '1$(id)')]:
            with self.subTest(round_id=round_id, episodes=episodes), self.assertRaises(ValueError):
                config.validate_values(round_id, episodes)

    def test_existing_round_target_cannot_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            config.check_existing_round(path, 'r01', '7', 'test/dataset')
            (path / 'ROUND.md').write_text('round=r01\n')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                config.check_existing_round(path, 'r01', '7', 'test/dataset')
            (path / 'SESSION.json').write_text(json.dumps({'round': 'r01', 'repo_id': 'test/dataset',
                                                            'target_episodes': 7}))
            config.check_existing_round(path, 'r01', '7', 'test/dataset')
            with self.assertRaisesRegex(ValueError, 'target'):
                config.check_existing_round(path, 'r01', '8', 'test/dataset')
            with self.assertRaisesRegex(ValueError, 'identity'):
                config.check_existing_round(path, 'r01', '7', 'different/dataset')


if __name__ == '__main__':
    unittest.main()
