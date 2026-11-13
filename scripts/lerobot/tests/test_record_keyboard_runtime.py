"""Test the actual LeRobot terminal key listener through a pseudo-terminal; no hardware."""
import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import termios
import time
import unittest


CHILD = r'''
import json, time
from lerobot.utils import keyboard_input
keyboard_input.pynput_can_capture = lambda: False
listener, events = keyboard_input.init_keyboard_listener()
if listener is None:
    raise RuntimeError('no terminal listener')
print('READY', flush=True)
deadline = time.monotonic() + 3
while not (events['exit_early'] or events['stop_recording']) and time.monotonic() < deadline:
    time.sleep(.01)
listener.stop()
print('RESULT=' + json.dumps(events), flush=True)
'''

RECORD_CHILD = r'''
import sys, time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from lerobot.configs.dataset import DatasetRecordConfig
from lerobot.robots.so_follower import SO101FollowerConfig
from lerobot.teleoperators.so_leader import SO101LeaderConfig
from lerobot.scripts import lerobot_record as rec
from lerobot.utils import keyboard_input

keyboard_input.pynput_can_capture = lambda: False
class Fake:
    name = 'so101_follower'
    cameras = {'top': object(), 'wrist': object()}
    action_features = {}
    observation_features = {}
    is_connected = False
    def connect(self): self.is_connected = True
    def disconnect(self): self.is_connected = False

features = {name: {'dtype':'float32','shape':(6,), 'names':[f'joint{i}' for i in range(6)]}
            for name in ('action', 'observation.state')}
for name in ('top', 'wrist'):
    features['observation.images.' + name] = {'dtype':'image', 'shape':(48,64,3),
                                              'names':['height','width','channels']}
def capture(**kw):
    ds, events = kw['dataset'], kw['events']
    assert ds is not None
    for index in range(3):
        frame = {'action':np.full(6,index,dtype=np.float32),
                 'observation.state':np.zeros(6,dtype=np.float32), 'task':'test'}
        for name in ('top', 'wrist'):
            frame['observation.images.'+name] = np.full((48,64,3),index*40,dtype=np.uint8)
        ds.add_frame(frame)
    print('WAITING_FOR_Q', flush=True)
    deadline = time.monotonic() + 8
    while not events['exit_early'] and time.monotonic() < deadline: time.sleep(.01)
    if not events['stop_recording']: raise RuntimeError('q not received')
    events['exit_early'] = False

cfg = rec.RecordConfig(robot=SO101FollowerConfig(port='/dev/null'),
    teleop=SO101LeaderConfig(port='/dev/null'),
    dataset=DatasetRecordConfig(repo_id='test/pty-stop', root=Path(sys.argv[1]),
                               single_task='test', num_episodes=3, video=False,
                               push_to_hub=False, no_stamp=True), play_sounds=False)
with patch.object(rec,'make_robot_from_config',return_value=Fake()), \
     patch.object(rec,'make_teleoperator_from_config',return_value=Fake()), \
     patch.object(rec,'make_default_processors',return_value=(object(),object(),object())), \
     patch.object(rec,'aggregate_pipeline_dataset_features',return_value={}), \
     patch.object(rec,'combine_feature_dicts',return_value=features), \
     patch.object(rec,'record_loop',side_effect=capture):
    rec.record(cfg)
print('RECORD_FINISHED', flush=True)
'''


class KeyboardTest(unittest.TestCase):
    def test_actual_terminal_q_drives_recorder_save(self):
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        with tempfile.TemporaryDirectory(prefix='so101-pty-record-') as tmp:
            root = os.path.join(tmp, 'dataset')
            master, slave = pty.openpty()
            proc = subprocess.Popen([sys.executable, '-c', RECORD_CHILD, root], stdin=slave,
                                    stdout=slave, stderr=slave)
            output = b''
            try:
                deadline = time.monotonic() + 15
                while b'WAITING_FOR_Q' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]: output += os.read(master, 8192)
                self.assertIn(b'WAITING_FOR_Q', output, output.decode(errors='replace'))
                os.write(master, b'q')
                while proc.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]: output += os.read(master, 8192)
                proc.wait(timeout=2)
                while select.select([master], [], [], 0)[0]: output += os.read(master, 8192)
                self.assertEqual(proc.returncode, 0, output.decode(errors='replace'))
                self.assertIn(b'RECORD_FINISHED', output)
                reopened = LeRobotDataset('test/pty-stop', root=root)
                self.assertEqual((len(reopened), reopened.meta.total_episodes), (3, 1))
                self.assertEqual(reopened[2]['action'].tolist(), [2.0] * 6)
                self.assertEqual(tuple(reopened[2]['observation.images.wrist'].shape), (3, 48, 64))
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                os.close(master)
                os.close(slave)

    def test_terminal_controls_and_restore(self):
        for key, expected in [('n', (True, False, False)), ('r', (True, True, False)),
                              ('q', (True, False, True))]:
            with self.subTest(key=key):
                master, slave = pty.openpty()
                before = termios.tcgetattr(slave)
                proc = subprocess.Popen([sys.executable, '-c', CHILD], stdin=slave,
                                        stdout=slave, stderr=slave)
                output = b''
                try:
                    deadline = time.monotonic() + 10
                    while b'READY' not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            output += os.read(master, 4096)
                    self.assertIn(b'READY', output, output.decode(errors='replace'))
                    os.write(master, key.encode())
                    while proc.poll() is None and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            output += os.read(master, 4096)
                    proc.wait(timeout=2)
                    while select.select([master], [], [], 0)[0]:
                        output += os.read(master, 4096)
                    self.assertEqual(proc.returncode, 0, output.decode(errors='replace'))
                    line = next(line for line in output.decode().splitlines() if line.startswith('RESULT='))
                    events = json.loads(line.removeprefix('RESULT='))
                    self.assertEqual(tuple(events[x] for x in ('exit_early', 'rerecord_episode', 'stop_recording')),
                                     expected)
                    self.assertEqual(termios.tcgetattr(slave), before, 'listener must restore terminal settings')
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
                    os.close(master)
                    os.close(slave)


if __name__ == '__main__':
    unittest.main()
