"""Exercise HF menu using stubs only; no network or user credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class HuggingFaceMenuTest(unittest.TestCase):
    def test_login_and_upload_require_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('interactive_collection.sh', 'lib.sh', 'fms688.env.example'):
                shutil.copy(ROOT / name, root / name)
            for name, code in {
                'lerobot-record': 'exit 0',
                'hf': 'printf "hf %s\\n" "$*" >> "$CALLS_FILE"',
                'collect.sh': 'printf "collect %s\\n" "$*" >> "$CALLS_FILE"',
            }.items():
                p = root / name
                p.write_text('#!/bin/bash\n' + code + '\n')
                p.chmod(0o755)
            config = root / 'fms688.env.example'
            calls = root / 'calls'
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], CALLS_FILE=str(calls))
            command = 'bash ' + __import__('shlex').quote(str(root / 'interactive_collection.sh')) + ' --config ' + __import__('shlex').quote(str(config))
            proc = subprocess.run(['script', '-q', '-e', '-c', command, '/dev/null'],
                                  input='12\nLOGIN\n13\nNO\n13\nPUBLIC\n0\n',
                                  text=True, capture_output=True, env=env, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            calls_text = calls.read_text()
            self.assertIn('hf auth login', calls_text)
            self.assertEqual(calls_text.count('upload --confirm-public'), 1)
            self.assertIn('已取消上传', proc.stdout)
            self.assertIn('公开上传', proc.stdout)

if __name__ == '__main__':
    unittest.main()
