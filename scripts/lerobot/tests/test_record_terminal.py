"""Check recording terminal PTY, logging and failure status without hardware."""
import os
from pathlib import Path
import pty
import select
import shutil
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RecordTerminalTest(unittest.TestCase):
    def test_interaction_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / 'record_terminal.sh', root)
            (root / 'record_round.sh').write_text('#!/bin/bash\nread -r -p "HOLD: " x\nprintf "accepted:%s\\n" "$x"\nread -r -n1 k\nprintf "\\nsaved:key=%s\\n" "$k"\nexit 7\n')
            log = root / 'record.log'
            pid, fd = pty.fork()
            if pid == 0:
                os.execvp('bash', ['bash', str(root / 'record_terminal.sh'), 'config with spaces', 'r01', str(log)])
            output = b''
            def wait(token):
                nonlocal output
                deadline = time.monotonic() + 8
                while token not in output and time.monotonic() < deadline:
                    if select.select([fd], [], [], .1)[0]:
                        output += os.read(fd, 8192)
                self.assertIn(token, output)
            try:
                wait(b'HOLD: '); os.write(fd, b'HOLD\n')
                wait(b'accepted:HOLD'); os.write(fd, b'q')
                wait(b'saved:key=q'); wait('按回车关闭本窗口'.encode()); os.write(fd, b'\n')
                _, status = os.waitpid(pid, 0); pid = 0
                self.assertEqual(os.waitstatus_to_exitcode(status), 7)
                self.assertIn('saved:key=q', log.read_text())
            finally:
                if pid:
                    os.kill(pid, 9); os.waitpid(pid, 0)
                os.close(fd)

if __name__ == '__main__': unittest.main()
