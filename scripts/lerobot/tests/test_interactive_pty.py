"""Exercise terminal follow-start and Ctrl+C using a simulated process, never hardware."""
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]


class MenuTest(unittest.TestCase):
    def test_stopping_follow_returns_to_menu(self):
        with tempfile.TemporaryDirectory(prefix='so101-menu-') as tmp:
            root = Path(tmp)
            for name in ('interactive_collection.sh', 'lib.sh', 'fms688.env.example'):
                shutil.copy(SCRIPTS / name, root / name)
            config = root / 'fms688.env.example'
            config.write_text(config.read_text().replace('FMS688_DATA="$HOME/fms688_data"',
                                                        f'FMS688_DATA="{root / "data"}"'))
            (root / 'lerobot-record').write_text('#!/bin/sh\nexit 0\n')
            (root / 'lerobot-record').chmod(0o755)
            (root / 'collect.sh').write_text(
                "#!/bin/bash\ntrap 'echo FAKE_FOLLOW_STOPPED; exit 1' INT\n"
                "echo FAKE_ARGS=\"$*\"\necho FAKE_FOLLOW_ACTIVE\nwhile :; do sleep 0.1; done\n")
            pid, master = pty.fork()
            if pid == 0:
                os.environ['PATH'] = str(root) + os.pathsep + os.environ['PATH']
                os.execvp('bash', ['bash', str(root / 'interactive_collection.sh'),
                                   '--config', str(root / 'fms688.env.example')])
            output = b''
            try:
                def wait_for(token, start=0):
                    nonlocal output
                    deadline = time.monotonic() + 5
                    while token not in output[start:] and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            try:
                                output += os.read(master, 8192)
                            except OSError:
                                break
                    self.assertIn(token, output[start:], output.decode(errors='replace'))

                wait_for('选择: '.encode())
                os.write(master, b'2\n')
                wait_for(b'YES')
                os.write(master, b'YES\n')
                wait_for(b'FAKE_FOLLOW_ACTIVE')
                self.assertIn(b'teleop --with-cameras --confirm-physical', output)
                mark = len(output)
                os.write(master, b'\x03')
                wait_for(b'FAKE_FOLLOW_STOPPED', mark)
                wait_for('选择: '.encode(), mark)
                os.write(master, b'0\n')
                _, status = os.waitpid(pid, 0)
                pid = 0
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            finally:
                if pid:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        os.waitpid(pid, 0)
                    except ProcessLookupError:
                        pass
                os.close(master)


if __name__ == '__main__':
    unittest.main()
