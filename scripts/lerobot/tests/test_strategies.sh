#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
scripts_dir="$repo_root/scripts/lerobot"
strategy_root="$scripts_dir/strategies-训练策略脚本"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file $1"
}

assert_contains() {
  local expected="$1"
  local file="$2"
  grep -F -- "$expected" "$file" >/dev/null || fail "missing [$expected] in $file"
}

assert_not_contains() {
  local unexpected="$1"
  local file="$2"
  if grep -F -- "$unexpected" "$file" >/dev/null; then
    fail "unexpected [$unexpected] in $file"
  fi
}

for path in \
  "$strategy_root/act/act.env" \
  "$strategy_root/act/train_act.sh" \
  "$strategy_root/smolvla/smolvla.env" \
  "$strategy_root/smolvla/train_smolvla.sh" \
  "$strategy_root/vqbet/vqbet.env" \
  "$strategy_root/vqbet/train_vqbet.sh"; do
  assert_file "$path"
done
[[ ! -f "$strategy_root/diffusion/diffusion.env" ]] || fail "deprecated diffusion config still exists"
[[ ! -f "$strategy_root/diffusion/train_diffusion.sh" ]] || fail "deprecated diffusion trainer still exists"

config_file="$temp_root/fms688.env"
cat > "$config_file" <<EOF
FMS688_DATA="$temp_root/fms688_data"
DATASET_NAMESPACE="fms688"
TASK_SLUG="move_blue_cube"
TASK_DESCRIPTION="Move the blue cube to the registered target area."
DATASET_VERSION="v001"
ROUND_ID="r01"
EPISODES_THIS_ROUND="5"
EPISODE_MAX_TIME_S="300"
RESET_MAX_TIME_S="120"
FPS="30"
FOLLOWER_PORT="/dev/ttyACM0"
LEADER_PORT="/dev/ttyACM1"
FOLLOWER_ID="so101_follower_rack_01"
LEADER_ID="so101_leader_rack_01"
TOP_CAMERA="/dev/video0"
WRIST_CAMERA="/dev/video1"
TOP_WIDTH="640"
TOP_HEIGHT="480"
WRIST_WIDTH="640"
WRIST_HEIGHT="480"
NUM_WORKERS="4"
SAVE_FREQ="20000"
EVAL_STEPS="0"
EOF
mkdir -p "$temp_root/fms688_data/datasets/move_blue_cube/v001"

quarantine_dir="$temp_root/fms688_data/rounds/move_blue_cube/v001"
quarantine_marker="$quarantine_dir/DATASET_QUARANTINED.md"
mkdir -p "$quarantine_dir"
printf 'status=quarantined\n' > "$quarantine_marker"
for policy in act smolvla vqbet; do
  if bash "$strategy_root/$policy/train_${policy}.sh" --config "$config_file" --profile smoke --mode single --dry-run > "$temp_root/quarantined-${policy}.out" 2>&1; then
    fail "$policy training must reject a quarantined dataset version"
  fi
  assert_contains 'ERROR: dataset version is quarantined' "$temp_root/quarantined-${policy}.out"
done
rm -f "$quarantine_marker"

bash "$strategy_root/act/train_act.sh" --config "$config_file" --profile smoke --mode single --dry-run > "$temp_root/act.out"
assert_contains '--policy.type=act' "$temp_root/act.out"
assert_contains "$temp_root/fms688_data/runs/act/move_blue_cube/v001" "$temp_root/act.out"
assert_contains '--policy.kl_weight=' "$temp_root/act.out"

if bash "$strategy_root/act/train_act.sh" --config "$config_file" --profile formal --mode single --dry-run > "$temp_root/unsealed_formal.out" 2>&1; then
  fail 'formal training must reject an unsealed dataset version'
fi
assert_contains 'dataset version is not sealed' "$temp_root/unsealed_formal.out"
seal_dir="$temp_root/fms688_data/rounds/move_blue_cube/v001"
mkdir -p "$seal_dir"
printf 'status=sealed\ndataset_id=fms688/so101_move_blue_cube_v001\n' > "$seal_dir/DATASET_SEALED.md"

bash "$strategy_root/act/train_act.sh" --config "$config_file" --profile formal --mode single --dry-run > "$temp_root/act_formal.out"
assert_contains '--steps=20000' "$temp_root/act_formal.out"
bash "$strategy_root/act/train_act.sh" --config "$config_file" --profile formal --mode four-gpu --dry-run > "$temp_root/act_four.out"
assert_contains '--num_processes=4' "$temp_root/act_four.out"

bash "$strategy_root/smolvla/train_smolvla.sh" --config "$config_file" --profile smoke --mode single --dry-run > "$temp_root/smolvla.out"
assert_contains '--policy.path=lerobot/smolvla_base' "$temp_root/smolvla.out"
assert_contains "$temp_root/fms688_data/runs/smolvla/move_blue_cube/v001" "$temp_root/smolvla.out"
assert_contains '--policy.freeze_vision_encoder=true' "$temp_root/smolvla.out"
assert_contains '--policy.train_expert_only=true' "$temp_root/smolvla.out"
assert_not_contains '--policy.kl_weight=' "$temp_root/smolvla.out"
assert_not_contains '--policy.n_vqvae_training_steps=' "$temp_root/smolvla.out"

bash "$strategy_root/smolvla/train_smolvla.sh" --config "$config_file" --profile formal --mode single --dry-run > "$temp_root/smolvla_formal.out"
assert_contains '--steps=20000' "$temp_root/smolvla_formal.out"
bash "$strategy_root/smolvla/train_smolvla.sh" --config "$config_file" --profile formal --mode four-gpu --dry-run > "$temp_root/smolvla_four.out"
assert_contains '--num_processes=4' "$temp_root/smolvla_four.out"
assert_contains '--steps=5000' "$temp_root/smolvla_four.out"

bash "$strategy_root/vqbet/train_vqbet.sh" --config "$config_file" --profile formal --mode single --dry-run > "$temp_root/vqbet.out"
assert_contains '--policy.type=vqbet' "$temp_root/vqbet.out"
assert_contains "$temp_root/fms688_data/runs/vqbet/move_blue_cube/v001" "$temp_root/vqbet.out"
assert_contains '--policy.n_vqvae_training_steps=20000' "$temp_root/vqbet.out"
assert_contains '--steps=40000' "$temp_root/vqbet.out"
assert_not_contains '--policy.kl_weight=' "$temp_root/vqbet.out"

bash "$strategy_root/vqbet/train_vqbet.sh" --config "$config_file" --profile smoke --mode single --dry-run > "$temp_root/vqbet_smoke.out"
assert_contains '--policy.n_vqvae_training_steps=100' "$temp_root/vqbet_smoke.out"
assert_contains '--steps=200' "$temp_root/vqbet_smoke.out"

bash "$strategy_root/vqbet/train_vqbet.sh" --config "$config_file" --profile formal --mode four-gpu --dry-run > "$temp_root/vqbet_four.out"
assert_contains '--num_processes=4' "$temp_root/vqbet_four.out"
assert_contains '--steps=40000' "$temp_root/vqbet_four.out"

bad_run="act_move_blue_cube_v001_single_gpu_smoke"
checkpoint_dir="$temp_root/fms688_data/runs/act/move_blue_cube/v001/$bad_run/checkpoints/last/pretrained_model"
mkdir -p "$checkpoint_dir"
touch "$checkpoint_dir/train_config.json"
printf 'policy=act\ntask=move_blue_cube\nversion=v001\n' > "${checkpoint_dir%/checkpoints/last/pretrained_model}/RUN_CONTEXT.txt"
if bash "$strategy_root/smolvla/train_smolvla.sh" --config "$config_file" --resume-run-id "$bad_run" --dry-run > "$temp_root/cross_policy.out" 2>&1; then
  fail 'SmolVLA resume must reject an ACT run directory'
fi
assert_contains 'policy mismatch' "$temp_root/cross_policy.out"

printf 'PASS: ACT, SmolVLA and VQ-BeT strategy pairs isolate parameters, output roots, and resume state.\n'
