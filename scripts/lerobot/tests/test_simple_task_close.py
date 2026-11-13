import contextlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)

class CloseTest(unittest.TestCase):
    def test_same_item_multiple_episodes_can_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            state = {'start_episode': 0, 'target_episodes': 2}
            (folder / 'VALIDATION.json').write_text(json.dumps({'files': {'data': 'hash'}}))
            (folder / 'QA.csv').write_text('episode,item,result,privacy,notes\n0,小物件,pass,pass,\n1,小物件,pass,pass,\n')
            (folder / 'ROUND.md').write_text('status=ready\n')
            with patch.object(flow, 'round_dir', return_value=folder), \
                 patch.object(flow, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(flow, 'session', return_value=state), patch.object(flow, 'count', return_value=2), \
                 patch.object(flow, 'snapshot', return_value={'data': 'hash'}):
                flow.close_round()
            self.assertEqual(json.loads((folder / 'SESSION.json').read_text())['status'], 'closed')

if __name__ == '__main__': unittest.main()
