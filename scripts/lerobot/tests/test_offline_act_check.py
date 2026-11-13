"""Offline export and pretrained ACT pipeline with temporary synthetic data only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.act.processor_act import make_act_pre_post_processors

SCRIPT = Path(__file__).resolve().parents[2] / 'jetson/offline_act_check.py'

class OfflineACTTest(unittest.TestCase):
    def test_export_load_and_infer_with_saved_processors(self):
        with tempfile.TemporaryDirectory(prefix='so101-offline-test-') as tmp:
            root = Path(tmp)
            names = ['shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos', 'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos']
            features = {'action': {'dtype':'float32', 'shape':(6,), 'names':names},
                        'observation.state': {'dtype':'float32', 'shape':(6,), 'names':names}}
            for n in ('top', 'wrist'):
                features['observation.images.' + n] = {'dtype':'image', 'shape':(48,64,3), 'names':['height','width','channels']}
            data_root = root / 'dataset'
            ds = LeRobotDataset.create('test/so101_offline', 30, root=data_root, features=features,
                                       robot_type='so101_follower', use_videos=False, image_writer_threads=2)
            for i in range(3):
                frame = {'action':np.full(6, i+1, np.float32), 'observation.state':np.full(6, i, np.float32), 'task':'test'}
                for n in ('top','wrist'):
                    frame['observation.images.'+n] = np.full((48,64,3), i*30, np.uint8)
                ds.add_frame(frame)
            ds.save_episode(); ds.finalize()
            ds = LeRobotDataset('test/so101_offline', root=data_root)
            input_features = {'observation.state':PolicyFeature(type=FeatureType.STATE, shape=(6,))}
            for n in ('top','wrist'):
                input_features['observation.images.'+n] = PolicyFeature(type=FeatureType.VISUAL,shape=(3,48,64))
            cfg = ACTConfig(input_features=input_features, output_features={'action':PolicyFeature(type=FeatureType.ACTION,shape=(6,))},
                            pretrained_backbone_weights=None, device='cpu', chunk_size=4, n_action_steps=1,
                            dim_model=64,n_heads=4,dim_feedforward=128,n_encoder_layers=1,n_decoder_layers=1,n_vae_encoder_layers=1)
            model = root / 'pretrained_model'
            ACTPolicy(cfg).save_pretrained(model)
            pre, post = make_act_pre_post_processors(cfg, dataset_stats=ds.meta.stats)
            pre.save_pretrained(model); post.save_pretrained(model)
            sample = root / 'frame.npz'
            env = {**os.environ, 'HF_HUB_OFFLINE':'1', 'OMP_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
            export = subprocess.run([sys.executable,str(SCRIPT),'export','--dataset-root',str(data_root),
                                     '--repo-id','test/so101_offline','--index','1','--output',str(sample)],
                                    env=env,text=True,capture_output=True,timeout=120)
            self.assertEqual(export.returncode, 0, export.stdout + export.stderr)
            with np.load(sample, allow_pickle=False) as result:
                for key in ('observation.state', 'action', 'observation.images.top', 'observation.images.wrist'):
                    np.testing.assert_allclose(result[key], np.asarray(ds[1][key]), rtol=0, atol=0)
            again = subprocess.run([sys.executable,str(SCRIPT),'export','--dataset-root',str(data_root),
                                    '--repo-id','test/so101_offline','--index','1','--output',str(sample)],
                                   env=env,text=True,capture_output=True,timeout=120)
            self.assertNotEqual(again.returncode, 0, 'existing sample must not be overwritten')
            result = subprocess.run([sys.executable,str(SCRIPT),'infer','--model',str(model),
                                     '--sample',str(sample),'--device','cpu'],env=env,text=True,capture_output=True,timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('OFFLINE_ACT_OK', result.stdout)
            self.assertIn('reference_action [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]', result.stdout)

if __name__ == '__main__': unittest.main()
