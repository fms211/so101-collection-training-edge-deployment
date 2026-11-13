"""Exercise control socket with real LeRobot episode saving and fake devices."""
import importlib.util
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np
from lerobot.configs.dataset import DatasetRecordConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.robots.so_follower import SO101FollowerConfig
from lerobot.scripts import lerobot_record
from lerobot.teleoperators.so_leader import SO101LeaderConfig

spec = importlib.util.spec_from_file_location('control', Path(__file__).resolve().parents[1] / 'record_control.py')
control = importlib.util.module_from_spec(spec); spec.loader.exec_module(control)

class Device:
    name='so101_follower'; cameras={}; action_features={}; observation_features={}; is_connected=False
    def connect(self): self.is_connected=True
    def disconnect(self): self.is_connected=False

class IntegrationTest(unittest.TestCase):
    def test_start_then_quit_saves_real_dataset(self):
        listener = control.ControlListener(launch=False)
        ready = threading.Event()
        def client():
            with socket.socket(socket.AF_UNIX) as sock:
                sock.connect(listener.path)
                with sock.makefile('r') as replies:
                    sock.sendall(b's\n'); replies.readline()
                    if not ready.wait(10): return
                    sock.sendall(b'q\n'); replies.readline()
        thread = threading.Thread(target=client, daemon=True); thread.start()
        features = {'action': {'dtype':'float32', 'shape':(6,), 'names':[f'j{i}' for i in range(6)]},
                    'observation.state': {'dtype':'float32', 'shape':(6,), 'names':[f'j{i}' for i in range(6)]}}
        robot, teleop = Device(), Device()
        def capture(**kw):
            ds = kw['dataset']
            ds.add_frame({'action':np.zeros(6,dtype=np.float32), 'observation.state':np.zeros(6,dtype=np.float32), 'task':'test'})
            ready.set()
            for _ in range(100):
                if listener.events['stop_recording']: return
                threading.Event().wait(.01)
            raise RuntimeError('control q not received')
        def init():
            self.assertTrue(listener.ready.wait(5))
            return listener, listener.events
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'dataset'
            cfg = lerobot_record.RecordConfig(robot=SO101FollowerConfig(port='/dev/null'), teleop=SO101LeaderConfig(port='/dev/null'),
                dataset=DatasetRecordConfig(repo_id='test/control', root=root, fps=30, single_task='test', num_episodes=2, video=False, push_to_hub=False, no_stamp=True),
                display_data=False, play_sounds=False)
            with patch.object(lerobot_record,'make_robot_from_config',return_value=robot), patch.object(lerobot_record,'make_teleoperator_from_config',return_value=teleop), \
                 patch.object(lerobot_record,'make_default_processors',return_value=(object(),object(),object())), \
                 patch.object(lerobot_record,'aggregate_pipeline_dataset_features',return_value={}), patch.object(lerobot_record,'combine_feature_dicts',return_value=features), \
                 patch.object(lerobot_record,'init_keyboard_listener',side_effect=init), patch.object(lerobot_record,'record_loop',side_effect=capture):
                lerobot_record.record(cfg)
            self.assertEqual(LeRobotDataset('test/control', root=root).meta.total_episodes, 1)
            self.assertFalse(robot.is_connected)
        thread.join(timeout=2)

if __name__ == '__main__': unittest.main()
