# SO-101 图像数据直接用于服务器 ACT 训练

本指南对应本仓库 `collect.sh` / `record_round.sh` 采集的 SO-101 单臂数据。**我们已把采集输出固定为 LeRobot v3.0 图像特征**：`--dataset.video=false`。这份数据集经逐轮质检后，整体同步到老师的服务器，服务器直接把同步目录作为 `--dataset.root` 训练；**日常流程不做格式转换、不复制第二份训练集**。

这项选择依据拷回的三份资料：服务器 `station_act` 环境已经用图像特征完成 Station Lite/Lumos ACT 40,000 步训练；该环境的 `torchcodec` 视频解码有问题。SO-101 和 Station Lite 的动作语义不同，所以只复用 LeRobot 训练环境与 ACT CLI，不复用 Station Lite 的 14 维转换脚本、数据集或 checkpoint。服务器资料记载 LeRobot 0.6.2（固定提交 `3f2c29ef...`）；本地采集为 v0.6.1，两边的 LeRobot 数据格式常量同为 `v3.0`。**尚未用真实 SO-101 数据在服务器读回或开训**，到时仍需运行下面的简短检查和冒烟训练。

## 1. 我们现在确定会产出什么

| 项目 | 固定值与检查点 |
|---|---|
| 机器人与动作 | `so101_follower`，`observation.state` 和 `action` 各 6 维；语义按 SO-101 电机位置核对。 |
| 相机 | `observation.images.top`、`observation.images.wrist`，特征类型为 `image`。 |
| 存储 | LeRobot v3.0 数据集根目录含 `meta/` 和 `data/`。**图像嵌入 `data/*.parquet`**；保存 episode 后暂存的 PNG 会清理，因此无需期待持久的 `images/` 文件夹，也不应有 `videos/*.mp4`。 |
| 轮次 | r01、r02… 向同一个 `<task>/<version>` 主数据集追加 episode；`rounds/` 只放轮次清单和 QA，不是训练输入。 |
| 训练输入 | 采集机为 `~/fms688_data/datasets/<task>/<version>/`；现有同步脚本把完整数据集送到服务器账号的**同一相对路径**。服务器这份副本就是 ACT 的 `--dataset.root`。 |

依据：[本地录制参数](../scripts/lerobot/record_round.sh)和[质检逻辑](../scripts/lerobot/collection.py)；服务器固定提交的 [LeRobot 图像嵌入 Parquet 实现](https://github.com/huggingface/lerobot/blob/3f2c29ef7e44b1ddccbcda3b6a63939e9e/src/lerobot/datasets/dataset_writer.py)。旧手册中“图像集必须有 `images/` 目录”和“先将视频转图像”的说法不适用于本仓库**新采集**的数据。

采集前在笔记本运行（配置中的任务名、版本、硬件路径按实际填写）：

```bash
source "$HOME/so101-lab/activate-lerobot.sh"
bash scripts/lerobot/record_round.sh \
  --config scripts/lerobot/fms688.env --round r01 --dry-run
# 在 Command 行确认 --dataset.video=false、repo_id、root、top/wrist 均正确
```

图像嵌入 Parquet 通常比 MP4 占更多空间。首轮先录少量数据，测量实际每集体积，再设置配置中的 `MIN_FREE_GB` 和每轮条数；正式采集始终写本地 SSD。**若已有同 task/version 的旧视频数据，不能向它续录图像**；另起数据集版本，例如 `v002`，并从 `r01` 重新初始化。

## 2. 逐轮质检，同步整份数据集

按 `SO101 主从臂寝室数据采集操作手册.md` 完成录制、`review`、人工逐集 QA 和 `close`。现有 `collection.py` 会读取每一帧的两路图像以及状态、动作；有缺帧、尺寸错误、NaN 或任务身份变化则拒绝通过。只有本轮 `quality=pass` 且 `status=closed` 后才同步：

```bash
# 在采集机、本仓库根目录执行；轮次按实际改 r01/r02/...
bash scripts/lerobot/sync_dataset_to_server.sh \
  --config scripts/lerobot/fms688.env --server so101-train --round r01 --dry-run
bash scripts/lerobot/sync_dataset_to_server.sh \
  --config scripts/lerobot/fms688.env --server so101-train --round r01 --confirm-sync
# 必须看到 SYNC VERIFIED；此脚本传 meta/、data/ 和本轮 ROUND.md，不拆图像与 Parquet
```

`so101-train` 必须是**那台**老师训练服务器的 SSH 别名。服务器旧 SO-101 规划文档示例使用 `~/soarm101_dorm/data/lerobot/soarm101_dorm_act_v1/`；本仓库同步脚本实际放在 `~/fms688_data/datasets/<task>/<version>/`。LeRobot 按 `--dataset.root` 读目录，**不要求目录名是 `soarm101_dorm_act_v1`**；直接指定同步副本，避免额外搬运或复制。训练权重、日志仍写到自己 `~/soarm101_dorm/` 下，绝不写入老师的 `lumousTest/20260914/`。

## 3. 服务器只读确认一次，再封版

登录服务器，在 `station_act` 的 Python 下检查**同步后的真实目录**。`REPO_ID` 来自采集机写入的 r01 清单，不用 Station Lite 的 `station_lite_act_v1`。下例任务名、版本按实际替换：

```bash
export TASK_SLUG=move_blue_cube
export DATASET_VERSION=v001
export DS_ROOT="$HOME/fms688_data/datasets/$TASK_SLUG/$DATASET_VERSION"
export ROUND_ROOT="$HOME/fms688_data/rounds/$TASK_SLUG/$DATASET_VERSION"
export REPO_ID="$(sed -n 's/^dataset_id=//p' "$ROUND_ROOT/r01/ROUND.md" | tail -1)"
export PY=/home/server/miniconda3/envs/station_act/bin/python
export TRAIN=/home/server/miniconda3/envs/station_act/bin/lerobot-train
test -n "$REPO_ID" && test -f "$DS_ROOT/meta/info.json" || { echo '数据或清单缺失'; exit 1; }
"$PY" - <<'PY'
import json, os
from pathlib import Path
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

root = Path(os.environ['DS_ROOT'])
info = json.loads((root / 'meta/info.json').read_text())
features = info['features']
assert info['codebase_version'] == 'v3.0'
assert info['robot_type'] == 'so101_follower'
assert info['total_frames'] > 0 and info['total_episodes'] > 0
assert all(features[k]['shape'] == [6] for k in ('observation.state', 'action'))
cams = ('observation.images.top', 'observation.images.wrist')
assert all(features[k]['dtype'] == 'image' for k in cams)
assert not list((root / 'videos').rglob('*.mp4'))
ds = LeRobotDataset(os.environ['REPO_ID'], root=root)
assert len(ds) == info['total_frames'] and ds.num_episodes == info['total_episodes']
for index in sorted({0, len(ds) // 2, len(ds) - 1}):
    frame = ds[index]
    assert all(np.isfinite(np.asarray(frame[k])).all() for k in ('observation.state', 'action'))
    assert all(np.asarray(frame[k]).shape[0] == 3 for k in cams)
print('DIRECT_IMAGE_OK', 'episodes=', ds.num_episodes,
      'frames=', len(ds), 'repo_id=', os.environ['REPO_ID'])
PY
```

只有 `DIRECT_IMAGE_OK` 才进入训练；元数据和抽样读回并不替代采集机逐集 QC。这里**不加载 torchcodec、不运行视频转换**。如果报形状/字段错误，先核对 SO-101 的六电机名称、单位、两路相机和任务文本；不要拿 Station Lite 的 14 维脚本“修”它。

最后一轮 `SYNC VERIFIED` 后封版。把本仓库 `lib.sh`、`seal_dataset_version.sh` 和对应的可信 `fms688.env` 放到服务器自己的 `~/soarm101_dorm/scripts/lerobot/`；该配置的 `FMS688_DATA` 应按服务器账号的 HOME 展开。封版脚本已适配同步来的 `ROUND.md` 保留采集机绝对路径，仍验证任务/版本/ID、QA 和服务器实际数据：

```bash
# 以下在服务器执行；前提是三个文件已放入该目录
export SERVER_CFG="$HOME/soarm101_dorm/scripts/lerobot/fms688.env"
bash "$HOME/soarm101_dorm/scripts/lerobot/seal_dataset_version.sh" \
  --config "$SERVER_CFG" --dry-run
# 核对 Dataset、Qualified rounds、文件数与字节数后
bash "$HOME/soarm101_dorm/scripts/lerobot/seal_dataset_version.sh" \
  --config "$SERVER_CFG" --confirm-seal
test -f "$ROUND_ROOT/DATASET_SEALED.md" || { echo '未封版'; exit 1; }
```

## 4. 使用现有服务器环境直接训练 ACT

先看 `nvidia-smi`，挑一张空闲且健康的卡。拷回资料记载 GPU0 曾挂死、GPU1 完成了旧训练；这是历史记录，**不等于现在 GPU1 一定空闲**。下面的 `GPU=1` 仅在现场确认后使用。第一次先 20 步冒烟，输出目录全新，数据根就是第 3 节的同步目录：

```bash
export GPU=1
nvidia-smi
export OUT_BASE="$HOME/soarm101_dorm/outputs"
mkdir -p "$OUT_BASE" "$HOME/soarm101_dorm/logs/train"
export SMOKE_RUN="$OUT_BASE/act_${TASK_SLUG}_${DATASET_VERSION}_smoke_$(date +%Y%m%d_%H%M%S)"
set -o pipefail
CUDA_VISIBLE_DEVICES="$GPU" "$TRAIN" \
  --dataset.repo_id="$REPO_ID" --dataset.root="$DS_ROOT" \
  --dataset.eval_split=0 \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --policy.chunk_size=50 --policy.n_action_steps=50 \
  --batch_size=4 --num_workers=0 --steps=20 \
  --eval_steps=0 --env_eval_freq=0 --save_freq=20 \
  --wandb.enable=false --output_dir="$SMOKE_RUN" \
  --job_name="act_${TASK_SLUG}_${DATASET_VERSION}_smoke" \
  2>&1 | tee "$HOME/soarm101_dorm/logs/train/$(basename "$SMOKE_RUN").log"
test -f "$SMOKE_RUN/checkpoints/last/pretrained_model/config.json"
```

冒烟通过条件：退出码 0、走完 20/20 步、checkpoint 可读，无数据解码、维度、NaN、OOM 错误。正式训练用新输出目录。少于 20 集时先关闭离线评估；达到 20 集可暂用 `eval_split=0.13`。下面用 SO-101 规划的 20,000 步作起点；Lumos 40,000 步不是本任务的固定答案，之后按验证曲线决定是否延长。

```bash
export N_EPISODES="$("$PY" -c 'import json,os; print(json.load(open(os.environ["DS_ROOT"]+"/meta/info.json"))["total_episodes"])')"
export EVAL_SPLIT=0 EVAL_STEPS=0
if (( N_EPISODES >= 20 )); then EVAL_SPLIT=0.13; EVAL_STEPS=2000; fi
export STEPS=20000
export RUN="$OUT_BASE/act_${TASK_SLUG}_${DATASET_VERSION}_$(date +%Y%m%d_%H%M%S)"
if test -e "$RUN" || ! test -f "$ROUND_ROOT/DATASET_SEALED.md"; then
  echo '运行目录已存在或数据未封版'; exit 1
fi
set -o pipefail
CUDA_VISIBLE_DEVICES="$GPU" "$TRAIN" \
  --dataset.repo_id="$REPO_ID" --dataset.root="$DS_ROOT" \
  --dataset.eval_split="$EVAL_SPLIT" \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --policy.chunk_size=50 --policy.n_action_steps=50 \
  --batch_size=4 --num_workers=4 --steps="$STEPS" \
  --eval_steps="$EVAL_STEPS" --env_eval_freq=0 --save_freq=2000 \
  --wandb.enable=false --output_dir="$RUN" \
  --job_name="act_${TASK_SLUG}_${DATASET_VERSION}" \
  2>&1 | tee "$HOME/soarm101_dorm/logs/train/$(basename "$RUN").log"
test -f "$RUN/checkpoints/last/pretrained_model/config.json"
```

中断后只从**本次 SO-101**运行的 checkpoint 恢复，先检查数据仍封版，保持原 batch、策略和 GPU 数量：

```bash
test -f "$ROUND_ROOT/DATASET_SEALED.md" && \
  test -f "$RUN/checkpoints/last/pretrained_model/train_config.json" || \
  { echo '封版或续训配置缺失'; exit 1; }
set -o pipefail
CUDA_VISIBLE_DEVICES="$GPU" "$TRAIN" \
  --config_path="$RUN/checkpoints/last/pretrained_model" --resume=true \
  2>&1 | tee -a "$HOME/soarm101_dorm/logs/train/$(basename "$RUN").log"
```

训练完成以 `End of training`、退出码 0 和最终 checkpoint 为准。离线 loss 不等于真机闭环成功率；实机评估仍需另行验收。

## 5. 仅供已有旧数据或换采集软件时使用

- 若手头**已经有旧视频数据集**，它不能与新图像数据在同一 task/version 中续录。可以在服务器另行测试 PyAV，或用 `scripts/lerobot/convert_video_dataset_to_images.py` 在采集机产生**新的版本/目录**。这不是新数据的日常步骤。
- 若将来换成其他软件，得到每集 `data.json + 图片`，那不是 LeRobot v3 数据集。先取得真实字段定义，核对六电机名称/单位、绝对或增量动作、相机名、时间戳/FPS 和 episode 边界，再写 SO-101 专用转换。Station Lite 的 14 维、三相机脚本不能直接复用。
- 服务器环境和训练数据仍未现场读回；以上是**已按本地采集代码和服务器固定 LeRobot 源码适配的可执行方案**，不是已完成训练的记录。

参考：`SOARM101_dorm_数据与训练隔离规划与操作手册_V1.0.md`、`README_纯指令操作教程.md`、`Station_Lite_ACT_GPU挂死案例分析与恢复_V1.0.md`；服务器固定提交的 [LeRobot 数据集读取](https://github.com/huggingface/lerobot/blob/3f2c29ef7e44b1ddccbcda3b6a63939e53639e9e/src/lerobot/datasets/lerobot_dataset.py)及[训练配置](https://github.com/huggingface/lerobot/blob/3f2c29ef7e44b1ddccbcda3b6a63939e53639e9e/src/lerobot/configs/train.py)。
