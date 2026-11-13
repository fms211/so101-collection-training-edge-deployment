"""Drive menu 3 through task selection with simulated preflight and terminal."""
import os
from pathlib import Path
import pty
import select
import shutil
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1]

class MenuDatedRecordTest(unittest.TestCase):
    def test_new_task_reaches_record_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('interactive_collection.sh', 'configure_collection.py', 'lib.sh', 'fms688.env.example'):
                shutil.copy(SOURCE / name, root / name)
            data = root / 'data'
            data.mkdir()
            config = root / 'fms688.env.example'
            config.write_text(config.read_text().replace('FMS688_DATA="$HOME/fms688_data"', f'FMS688_DATA="{data}"'))
            for name, contents in {
                'lerobot-record': 'exit 0',
                'preflight_collection.sh': 'echo PRECHECK_OK',
                'init_round.sh': 'echo INIT_OK',
                'gnome-terminal': 'printf "TERMINAL_ARGS: %s\\n" "$*"',
            }.items():
                p = root / name
                p.write_text('#!/bin/bash\n' + contents + '\n')
                p.chmod(0o755)
            pid, master = pty.fork()
            if pid == 0:
                os.environ['PATH'] = str(root) + os.pathsep + os.environ['PATH']
                os.execvp('bash', ['bash', str(root / 'interactive_collection.sh'), '--config', str(config)])
            output = b''
            def wait(text):
                nonlocal output
                target = text.encode()
                end = time.monotonic() + 8
                while target not in output and time.monotonic() < end:
                    if select.select([master], [], [], .1)[0]:
                        output += os.read(master, 8192)
                self.assertIn(target, output, output.decode(errors='replace'))
            try:
                wait('选择: ')
                os.write(master, b'3\n')
                wait('新任务按回车: '); os.write(master, b'\n')
                wait('新任务英文名称'); os.write(master, b'pick_test\n')
                wait('任务描述'); os.write(master, b'\n')
                wait('本组轨迹条数'); os.write(master, b'42\n')
                wait('输入 YES 确认'); os.write(master, b'YES\n')
                wait('输入 YES 开始'); os.write(master, b'YES\n')
                wait('TERMINAL_ARGS:')
                self.assertIn('EPISODES_THIS_ROUND=42', config.read_text())
                self.assertIn('pick_test', config.read_text())
                self.assertIn(b'PRECHECK_OK', output)
                self.assertIn(b'INIT_OK', output)
                os.write(master, b'0\n')
                _, status = os.waitpid(pid, 0); pid = 0
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            finally:
                if pid:
                    os.kill(pid, 9); os.waitpid(pid, 0)
                os.close(master)

if __name__ == '__main__': unittest.main()
