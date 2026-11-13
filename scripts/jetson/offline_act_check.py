#!/usr/bin/env python3
"""Export one LeRobot observation and check ACT offline without opening hardware."""
import argparse
import io
import json
import time
from pathlib import Path

import numpy as np

OBS_KEYS = ('observation.state', 'observation.images.top', 'observation.images.wrist')


def export_sample(args):
    import pyarrow.parquet as pq
    from PIL import Image

    root = Path(args.dataset_root)
    info = json.loads((root / 'meta/info.json').read_text())
    features = info['features']
    required = (*OBS_KEYS, 'action')
    missing = [key for key in required if key not in features]
    if missing:
        raise ValueError(f'数据集缺少必要字段: {missing}')
    state_names, action_names = features['observation.state'].get('names'), features['action'].get('names')
    if not state_names or state_names != action_names or len(state_names) != 6:
        raise ValueError('数据集状态与动作字段的六关节名称或顺序不一致')
    for key in OBS_KEYS[1:]:
        if features[key].get('dtype') != 'image':
            raise ValueError(f'{key} 不是图像特征')
    files = sorted((root / 'data').rglob('*.parquet'))
    if not files or args.index < 0:
        raise ValueError('数据文件缺失或帧编号为负数')
    # Parquet batches read the requested row without building a full Arrow dataset cache.
    remaining = args.index
    frame = None
    for path in files:
        parquet = pq.ParquetFile(path)
        if remaining >= parquet.metadata.num_rows:
            remaining -= parquet.metadata.num_rows
            continue
        for batch in parquet.iter_batches(batch_size=8, columns=[*required, 'task_index', 'index']):
            if remaining >= batch.num_rows:
                remaining -= batch.num_rows
                continue
            frame = batch.slice(remaining, 1).to_pylist()[0]
            break
        break
    if frame is None:
        raise ValueError(f'帧编号超出数据范围: {args.index}')
    if frame['index'] != args.index:
        raise ValueError('Parquet 顺序与全局帧编号不一致；请检查数据集完整性')
    arrays = {key: np.asarray(frame[key], dtype=np.float32) for key in ('action', 'observation.state')}
    for key in OBS_KEYS[1:]:
        image = frame[key]
        if not isinstance(image, dict) or not image.get('bytes'):
            raise ValueError(f'{key} 不含嵌入图像字节；请检查数据格式')
        with Image.open(io.BytesIO(image['bytes'])) as decoded:
            pixels = np.asarray(decoded.convert('RGB'), dtype=np.float32) / 255.0
        arrays[key] = pixels.transpose(2, 0, 1)
    tasks = pq.read_table(root / 'meta/tasks.parquet').to_pylist()
    matching = [row['task'] for row in tasks if row['task_index'] == frame['task_index']]
    if len(matching) != 1:
        raise ValueError('任务编号无法在元数据中唯一匹配')
    if any(not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError('样本包含非有限值')
    if arrays['observation.state'].shape != (6,) or arrays['action'].shape != (6,):
        raise ValueError('动作或关节状态不是六维')
    for key in OBS_KEYS[1:]:
        if arrays[key].ndim != 3 or arrays[key].shape[0] != 3:
            raise ValueError(f'相机帧不是 CHW 图像: {key}: {arrays[key].shape}')
        if arrays[key].min() < 0 or arrays[key].max() > 1:
            raise ValueError(f'相机帧不在 0..1 范围: {key}')
    metadata = {'repo_id': args.repo_id, 'index': args.index, 'fps': info['fps'],
                'joint_names': state_names, 'task': matching[0],
                'image_shapes': {key: list(arrays[key].shape) for key in OBS_KEYS[1:]}}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as handle:
        np.savez_compressed(handle, **arrays, metadata=np.array(json.dumps(metadata, ensure_ascii=False)))
    print('SAMPLE_EXPORTED', output, 'frame', args.index, 'joint_names', state_names)
    print('包含真实相机画面，请按数据隐私要求保存和传输。')


def infer(args):
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    model_dir, sample_path = Path(args.model).resolve(), Path(args.sample).resolve()
    for name in ('config.json', 'model.safetensors', 'policy_preprocessor.json', 'policy_postprocessor.json'):
        if not (model_dir / name).is_file():
            raise FileNotFoundError(f'checkpoint 缺少 {name}；请复制完整 pretrained_model 目录')
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('GPU 不可用；请使用 so101-gpu-python，禁止自动回退 CPU')
    with np.load(sample_path, allow_pickle=False) as sample:
        metadata = json.loads(str(sample['metadata'].item()))
        obs = {key: np.array(sample[key], copy=True) for key in OBS_KEYS}
        reference = np.array(sample['action'], copy=True)
    if len(metadata.get('joint_names', [])) != 6 or reference.shape != (6,):
        raise ValueError('样本关节顺序或动作不是六维')
    config = PreTrainedConfig.from_pretrained(model_dir, local_files_only=True)
    if config.type != 'act':
        raise ValueError(f'仅支持 SO-101 ACT，当前模型类型: {config.type}')
    for key in OBS_KEYS:
        feature = config.input_features.get(key)
        if feature is None or tuple(feature.shape) != tuple(obs[key].shape):
            raise ValueError(f'模型与样本特征不匹配: {key}, 模型={getattr(feature, "shape", None)}, 样本={obs[key].shape}')
    if tuple(config.output_features['action'].shape) != (6,):
        raise ValueError('模型输出动作不是六维')
    if any(not np.isfinite(value).all() for value in obs.values()):
        raise ValueError('样本含非有限值')
    config.device = args.device
    # All learned backbone parameters are in the checkpoint; avoid downloading ImageNet weights.
    config.pretrained_backbone_weights = None
    policy = ACTPolicy.from_pretrained(model_dir, config=config, local_files_only=True, strict=True).eval()
    pre, post = make_pre_post_processors(policy_cfg=config, pretrained_path=str(model_dir),
                                         preprocessor_overrides={'device_processor': {'device': args.device}})
    batch = {key: torch.from_numpy(value) for key, value in obs.items()}
    batch['task'] = metadata.get('task', '')
    batch['robot_type'] = 'so101_follower'
    with torch.inference_mode():
        start = time.perf_counter()
        prepared = pre(batch)
        if args.device == 'cuda':
            torch.cuda.synchronize()
        policy.reset()
        started = time.perf_counter()
        prediction = policy.select_action(prepared)
        if args.device == 'cuda':
            torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - started
        result = post(prediction).detach().cpu().reshape(-1)
        total_seconds = time.perf_counter() - start
    if result.numel() != 6 or not torch.isfinite(result).all():
        raise ValueError('反归一化动作不是有限六维结果')
    print('OFFLINE_ACT_OK', 'device', args.device, 'frame', metadata.get('index'), 'joints', metadata['joint_names'])
    print('action', result.tolist(), 'reference_action', reference.tolist())
    print('single_policy_seconds', round(inference_seconds, 4), 'with_pre_post_seconds', round(total_seconds, 4))
    print('仅离线单帧；动作与示教对照不能证明任务成功，关节顺序须与训练记录人工核对。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='从本机数据集中导出一帧（含两路图像）')
    export.add_argument('--dataset-root', required=True)
    export.add_argument('--repo-id', required=True)
    export.add_argument('--index', type=int, default=0)
    export.add_argument('--output', required=True)
    export.set_defaults(func=export_sample)
    check = commands.add_parser('infer', help='加载 checkpoint 并进行单帧离线推理')
    check.add_argument('--model', required=True)
    check.add_argument('--sample', required=True)
    check.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    check.set_defaults(func=infer)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
