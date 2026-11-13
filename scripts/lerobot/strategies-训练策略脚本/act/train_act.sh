#!/usr/bin/env bash
set -euo pipefail

strategy_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts_dir="$(cd "${strategy_dir}/../.." && pwd)"
# shellcheck source=../../lib.sh
source "${scripts_dir}/lib.sh"
# shellcheck source=act.env
source "${strategy_dir}/act.env"

config_file=""
mode="single"
profile="smoke"
resume_run_id=""
dry_run=true
confirm_train=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --mode) mode="${2:-}"; shift 2 ;;
    --profile) profile="${2:-}"; shift 2 ;;
    --resume-run-id) resume_run_id="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --confirm-train) dry_run=false; confirm_train=true; shift ;;
    --help)
      printf 'Usage: train_act.sh --config <fms688.env> [--mode single|four-gpu] [--profile smoke|formal] [--resume-run-id <act-run-id>] [--dry-run|--confirm-train]\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
require_dataset_not_quarantined
[[ "$POLICY_NAME" == "act" ]] || die "policy mismatch in ${strategy_dir}/act.env"
policy_output_root="${FMS688_DATA}/runs/act/${TASK_SLUG}/${DATASET_VERSION}"

resume_run() {
  local run_dir="${policy_output_root}/${resume_run_id}"
  if [[ ! -d "$run_dir" ]]; then
    shopt -s nullglob
    local foreign_runs=("${FMS688_DATA}/runs"/*/"${TASK_SLUG}"/"${DATASET_VERSION}"/"${resume_run_id}")
    shopt -u nullglob
    (( ${#foreign_runs[@]} == 0 )) || die "policy mismatch: run belongs to ${foreign_runs[0]}"
    die "checkpoint config not found: ${run_dir}"
  fi
  local context="${run_dir}/RUN_CONTEXT.txt"
  local config_path="${run_dir}/checkpoints/last/pretrained_model/train_config.json"
  [[ -f "$context" ]] || die "missing RUN_CONTEXT.txt: ${context}"
  grep -Fx 'policy=act' "$context" >/dev/null || die "policy mismatch in ${context}"
  grep -Fx "task=${TASK_SLUG}" "$context" >/dev/null || die "task mismatch in ${context}"
  grep -Fx "version=${DATASET_VERSION}" "$context" >/dev/null || die "version mismatch in ${context}"
  if grep -Fx 'profile=formal' "$context" >/dev/null; then
    require_dataset_seal
  fi
  [[ -f "$config_path" ]] || die "checkpoint config not found: ${config_path}"
  local args=(lerobot-train --config_path="$config_path" --resume=true)
  printf 'POLICY=act\nRUN_ID=%s\nCHECKPOINT_CONFIG=%s\nCommand: ' "$resume_run_id" "$config_path"
  print_command "${args[@]}"
  [[ "$dry_run" == true ]] && exit 0
  [[ "$confirm_train" == true ]] || die "resume requires --confirm-train"
  exec "${args[@]}"
}

[[ -n "$resume_run_id" ]] && resume_run
require_master_dataset
case "$mode:$profile" in
  single:smoke) batch_size="$ACT_SMOKE_BATCH_SIZE"; steps="$ACT_SMOKE_STEPS"; run_id="act_${TASK_SLUG}_${DATASET_VERSION}_single_gpu_smoke" ;;
  single:formal) batch_size="$ACT_FORMAL_BATCH_SIZE"; steps="$ACT_FORMAL_STEPS"; run_id="act_${TASK_SLUG}_${DATASET_VERSION}_single_gpu_v001" ;;
  four-gpu:formal) batch_size="$ACT_FOUR_GPU_BATCH_SIZE"; steps="$ACT_FOUR_GPU_STEPS"; run_id="act_${TASK_SLUG}_${DATASET_VERSION}_four_gpu_v001" ;;
  four-gpu:smoke) die "four-gpu ACT requires --profile formal" ;;
  *) die "profile must be smoke or formal; mode must be single or four-gpu" ;;
esac
[[ "$profile" != "formal" ]] || require_dataset_seal

run_dir="${policy_output_root}/${run_id}"
train_args=(
  --dataset.repo_id="$DATASET_ID"
  --dataset.root="$DATASET_ROOT"
  --policy.type=act
  --policy.device=cuda
  --policy.push_to_hub=false
  --policy.optimizer_lr="$ACT_OPTIMIZER_LR"
  --policy.optimizer_weight_decay="$ACT_OPTIMIZER_WEIGHT_DECAY"
  --policy.chunk_size="$ACT_CHUNK_SIZE"
  --policy.n_action_steps="$ACT_N_ACTION_STEPS"
  --policy.dropout="$ACT_DROPOUT"
  --policy.kl_weight="$ACT_KL_WEIGHT"
  --output_dir="$run_dir"
  --job_name="$run_id"
  --batch_size="$batch_size"
  --steps="$steps"
  --num_workers="$NUM_WORKERS"
  --save_freq="$SAVE_FREQ"
  --eval_steps="$EVAL_STEPS"
  --wandb.enable=false
)
if [[ -n "$ACT_TEMPORAL_ENSEMBLE_COEFF" ]]; then
  [[ "$ACT_N_ACTION_STEPS" -eq 1 ]] || die "ACT temporal ensemble requires ACT_N_ACTION_STEPS=1"
  train_args+=(--policy.temporal_ensemble_coeff="$ACT_TEMPORAL_ENSEMBLE_COEFF")
fi
if [[ "$ACT_N_ACTION_STEPS" -gt "$ACT_CHUNK_SIZE" ]]; then
  die "ACT_N_ACTION_STEPS must not exceed ACT_CHUNK_SIZE"
fi
if [[ "$mode" == "single" ]]; then
  launch_args=(env CUDA_VISIBLE_DEVICES=0 lerobot-train "${train_args[@]}")
else
  launch_args=(env CUDA_VISIBLE_DEVICES=0,1,2,3 accelerate launch --multi_gpu --num_processes=4 --mixed_precision=bf16 lerobot-train "${train_args[@]}")
fi
printf 'POLICY=act\nTRAIN_DATASET_ROOT=%s\nRUN_DIR=%s\nCommand: ' "$DATASET_ROOT" "$run_dir"
print_command "${launch_args[@]}"
[[ "$dry_run" == true ]] && exit 0
[[ "$confirm_train" == true ]] || die "training requires --confirm-train"
[[ ! -e "$run_dir" ]] || die "run directory already exists: ${run_dir}"
command -v lerobot-train >/dev/null || die "lerobot-train not found; activate LeRobot environment first"
[[ "$mode" == "single" ]] || command -v accelerate >/dev/null || die "accelerate not found; activate LeRobot training environment first"
mkdir -p "$run_dir"
printf 'policy=act\ntask=%s\nversion=%s\ndataset_id=%s\ndataset_root=%s\nmode=%s\nprofile=%s\nbatch_size=%s\nsteps=%s\nstrategy_config=%s\n' \
  "$TASK_SLUG" "$DATASET_VERSION" "$DATASET_ID" "$DATASET_ROOT" "$mode" "$profile" "$batch_size" "$steps" "${strategy_dir}/act.env" > "${run_dir}/RUN_CONTEXT.txt"
exec "${launch_args[@]}"
