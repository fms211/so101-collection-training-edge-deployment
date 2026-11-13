"""Progress reflects actual completed work and does not alter data checks."""
import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'collection.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)

class ProgressTest(unittest.TestCase):
    def test_percent_and_hash_completion(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir(); (root / 'data' / 'a').write_bytes(b'a'*2048)
            with patch.object(flow, 'root', return_value=root), contextlib.redirect_stdout(output):
                hashes = flow.snapshot()
        self.assertIn('data/a', hashes)
        self.assertIn('0%', output.getvalue())
        self.assertIn('100%', output.getvalue())

    def test_waiting_never_claims_success_on_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(ValueError):
                with flow.waiting('测试等待'):
                    raise ValueError('fail')
        self.assertIn('无法估算百分比', output.getvalue())
        self.assertNotIn('完成 [测试等待]', output.getvalue())

if __name__ == '__main__': unittest.main()
