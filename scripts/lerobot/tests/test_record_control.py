import importlib.util
from pathlib import Path
import socket
import unittest

spec = importlib.util.spec_from_file_location('control', Path(__file__).resolve().parents[1] / 'record_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

class ControlTest(unittest.TestCase):
    def test_start_commands_and_disconnect(self):
        listener = control.ControlListener(launch=False)
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.connect(listener.path)
                reader = sock.makefile('r')
                sock.sendall(b'n\n'); self.assertIn('尚未开始', reader.readline())
                self.assertFalse(listener.ready.is_set())
                sock.sendall(b's\n'); self.assertIn('已开始', reader.readline())
                self.assertTrue(listener.ready.wait(1))
                sock.sendall(b'n\n'); self.assertIn('下一阶段', reader.readline())
                self.assertTrue(listener.events['exit_early'])
                listener.events['exit_early'] = False
                sock.sendall(b'r\n'); self.assertIn('重录', reader.readline())
                self.assertTrue(listener.events['rerecord_episode'])
                sock.sendall(b'q\n'); self.assertIn('保存', reader.readline())
                self.assertTrue(listener.events['stop_recording'])
                reader.close()
        finally:
            listener.stop()

    def test_cancel_before_start(self):
        listener = control.ControlListener(launch=False)
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.connect(listener.path)
                sock.sendall(b'q\n')
                self.assertIn('未开始', sock.recv(1024).decode())
                self.assertTrue(listener.ready.wait(1))
                self.assertFalse(listener.started)
                self.assertTrue(listener.events['stop_recording'])
        finally:
            listener.stop()

    def test_lost_control_window_requests_stop(self):
        listener = control.ControlListener(launch=False)
        try:
            sock = socket.socket(socket.AF_UNIX)
            sock.connect(listener.path)
            sock.sendall(b's\n')
            sock.recv(1024)
            sock.close()
            listener.thread.join(timeout=2)
            self.assertFalse(listener.thread.is_alive())
            self.assertTrue(listener.events['stop_recording'])
            self.assertTrue(listener.events['exit_early'])
        finally:
            listener.stop()

if __name__ == '__main__': unittest.main()
