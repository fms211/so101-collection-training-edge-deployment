"""Dedicated, per-recording control window and event bridge."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading


class ControlListener:
    def __init__(self, launch=True):
        self.events = {'exit_early': False, 'rerecord_episode': False, 'stop_recording': False}
        self.ready = threading.Event()
        self.started = False
        self.directory = tempfile.TemporaryDirectory(prefix='so101-control-')
        self.path = str(Path(self.directory.name) / 'control.sock')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.server.settimeout(30)
        self.connection = None
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        if launch:
            subprocess.Popen(['gnome-terminal', '--title=SO101 录制控制', '--', sys.executable,
                              str(Path(__file__).resolve()), self.path], close_fds=True)

    def serve(self):
        try:
            conn, _ = self.server.accept()
            self.connection = conn
            with conn, conn.makefile('r', encoding='utf-8') as lines:
                for line in lines:
                    command = line.strip().lower()
                    if not self.started:
                        if command == 's':
                            self.started = True
                            self.ready.set()
                            reply = '已开始：请操作主臂示教。'
                        elif command == 'q':
                            self.events['stop_recording'] = True
                            self.ready.set()
                            reply = '已取消，未开始采集。'
                        else:
                            reply = '尚未开始，请输入 s 或 q。'
                    elif command in ('n', 'r', 'q'):
                        if command == 'r':
                            self.events['rerecord_episode'] = True
                        if command == 'q':
                            self.events['stop_recording'] = True
                        self.events['exit_early'] = True
                        reply = {'n': '已请求进入下一阶段。', 'r': '已请求丢弃并重录。',
                                 'q': '已请求结束；请查看日志窗口确认保存。'}[command]
                    else:
                        reply = '请输入 n、r 或 q。'
                    conn.sendall((reply + '\n').encode())
                    print('控制窗口：' + reply, flush=True)
                    if self.events['stop_recording']:
                        break
        except (OSError, TimeoutError):
            pass
        finally:
            if not self.events['stop_recording']:
                self.events['stop_recording'] = True
                self.events['exit_early'] = True
                print('控制窗口断开：已请求结束录制，请检查保存状态。', flush=True)
            self.ready.set()

    def stop(self):
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.close()
        self.thread.join(timeout=1)
        self.directory.cleanup()


def init_listener():
    listener = ControlListener()
    print('等待录制控制窗口：输入 s 开始第一条；q 取消。', flush=True)
    if not listener.ready.wait(timeout=60):
        listener.stop()
        raise RuntimeError('录制控制窗口未连接或未开始，已停止。')
    return listener, listener.events


def client(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        print('SO101 录制控制：输入命令并按回车。\ns 开始第一条；n 结束当前示教/复位；r 丢弃重录；q 结束并请求保存。\n复位时仍跟随；q 不是急停，异常立即断电。', flush=True)
        with sock.makefile('r', encoding='utf-8') as responses:
            while True:
                try:
                    command = input('控制> ').strip()
                except EOFError:
                    break
                sock.sendall((command + '\n').encode())
                reply = responses.readline()
                if not reply:
                    break
                print(reply, end='', flush=True)
                if command.lower() == 'q':
                    break
    input('控制窗口已结束，按回车关闭。')


if __name__ == '__main__':
    client(sys.argv[1])
