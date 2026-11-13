#!/bin/bash
set -euo pipefail
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate so101-act-gpu
export FOLLOWER_PORT=/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B91028773-if00
export FOLLOWER_ID=fms_follower_arm
export CALIBRATION_ROOT="$HOME/.cache/huggingface/lerobot/calibration"
STEP="${STEP:-060000}"
if [[ ! "$STEP" =~ ^[0-9]{6}$ ]]; then
  echo "错误：STEP 必须是六位数字，例如 040000。" >&2
  exit 1
fi
MODEL_DIR="/mnt/so101-deploy/output/act_pick_to_container_60k_20261112_165946/checkpoints/$STEP/pretrained_model"
if [[ ! -f "$MODEL_DIR/config.json" || ! -f "$MODEL_DIR/model.safetensors" ]]; then
  echo "错误：找不到完整模型目录 $MODEL_DIR" >&2
  exit 1
fi
echo "使用 checkpoint 步数：$STEP；模型路径：$MODEL_DIR"
echo "ACT 不限时实机测试（限幅 5.0）：按 Ctrl+C 停止；请手放电源开关旁，异常立即断电。"
echo "即将加载模型，等待 HOLD 提示后托稳从臂并输入 HOLD。"
so101-gpu-python "$HOME/so101-deploy/scripts/guarded_rollout.py" --collection "$HOME/so101-deploy/scripts/collection.py" --confirm-physical \
 --strategy.type=base --inference.type=sync \
 --policy.path="$MODEL_DIR" \
 --device=cuda --robot.type=so101_follower --robot.port="$FOLLOWER_PORT" --robot.id="$FOLLOWER_ID" \
 --robot.calibration_dir="$CALIBRATION_ROOT/robots/so_follower" --robot.max_relative_target=5.0 \
 --robot.cameras="{top: {type: opencv, index_or_path: /dev/v4l/by-id/usb-SN0002_1080P_USB_Camera_46435000_P030C00_SN0002-video-index0, width: 1280, height: 720, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: /dev/v4l/by-id/usb-LRCP_H-720P_LRCP_H-720P_SN0001-video-index0, width: 1280, height: 720, fps: 30, fourcc: MJPG}}" \
 --task="Pick up small objects and place them in the container." --fps=10 --duration=0 --return_to_initial_position=false
