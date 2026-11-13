#!/usr/bin/env bash
set -euo pipefail

strategy_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts_dir="$(cd "${strategy_dir}/../.." && pwd)"
# shellcheck source=../../lib.sh
source "${scripts_dir}/lib.sh"
# shellcheck source=vqbet.env
source "${strategy_dir}/vqbet.env"

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
      printf 'Usage: train_vqbet.sh --config <fms688.env> [--mode single|four-gpu] [--profile smoke|formal] [--resume-run-id <vqbet-run-id>] [--dry-run|--confirm-train]\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
require_dataset_not_quarantined
[[ "$POLICY_NAME" == "vqbet" ]] || die "policy mismatch in ${strategy_dir}/vqbet.env"
policy_output_root="${FMS688_DATA}/runs/vqbet/${TASK_SLUG}/${DATASET_VERSION}"

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
  grep -Fx 'policy=vqbet' "$context" >/dev/null || die "policy mismatch in ${context}"
  grep -Fx "task=${TASK_SLUG}" "$context" >/dev/null || die "task mismatch in ${context}"
  grep -Fx "version=${DATASET_VERSION}" "$context" >/dev/null || die "version mismatch in ${context}"
  if grep -Fx 'profile=formal' "$context" >/dev/null; then
    require_dataset_seal
  fi
  [[ -f "$config_path" ]] || die "checkpoint config not found: ${config_path}"
  local args=(lerobot-train --config_path="$config_path" --resume=true)
  printf 'POLICY=vqbet\nRUN_ID=%s\nCHECKPOINT_CONFIG=%s\nCommand: ' "$resume_run_id" "$config_path"
  print_command "${args[@]}"
  [[ "$dry_run" == true ]] && exit 0
  [[ "$confirm_train" == true ]] || die "resume requires --confirm-train"
  exec "${args[@]}"
}

[[ -n "$resume_run_id" ]] && resume_run
require_master_dataset
case "$mode:$profile" in
  single:smoke)
    batch_size="$VQBET_SMOKE_BATCH_SIZE"; steps="$VQBET_SMOKE_STEPS"; vqvae_steps="$VQBET_SMOKE_VQVAE_TRAINING_STEPS"; run_id="vqbet_${TASK_SLUG}_${DATASET_VERSION}_single_gpu_smoke"
    ;;
  single:formal)
    batch_size="$VQBET_FORMAL_BATCH_SIZE"; steps="$VQBET_FORMAL_STEPS"; vqvae_steps="$VQBET_FORMAL_VQVAE_TRAINING_STEPS"; run_id="vqbet_${TASK_SLUG}_${DATASET_VERSION}_single_gpu_formal"
    ;;
  four-gpu:formal)
    batch_size="$VQBET_FOUR_GPU_BATCH_SIZE"; steps="$VQBET_FOUR_GPU_STEPS"; vqvae_steps="$VQBET_FOUR_GPU_VQVAE_TRAINING_STEPS"; run_id="vqbet_${TASK_SLUG}_${DATASET_VERSION}_four_gpu_formal"
    ;;
  four-gpu:smoke) die "four-gpu VQ-BeT requires --profile formal" ;;
  *) die "profile must be smoke or formal; mode must be single or four-gpu" ;;
esac
[[ "$profile" != "formal" ]] || require_dataset_seal
[[ "$vqvae_steps" -lt "$steps" ]] || die "VQ-BeT total steps must exceed VQ-VAE training steps"

run_dir="${policy_output_root}/${run_id}"
train_args=(
  --dataset.repo_id="$DATASET_ID"
  --dataset.root="$DATASET_ROOT"
  --policy.type=vqbet
  --policy.device=cuda
  --policy.push_to_hub=false
  --policy.n_obs_steps="$VQBET_N_OBS_STEPS"
  --policy.n_action_pred_token="$VQBET_N_ACTION_PRED_TOKEN"
  --policy.action_chunk_size="$VQBET_ACTION_CHUNK_SIZE"
  --policy.n_vqvae_training_steps="$vqvae_steps"
  --policy.vqvae_n_embed="$VQBET_VQVAE_N_EMBED"
  --policy.vqvae_embedding_dim="$VQBET_VQVAE_EMBEDDING_DIM"
  --policy.vqvae_enc_hidden_dim="$VQBET_VQVAE_ENC_HIDDEN_DIM"
  --policy.gpt_block_size="$VQBET_GPT_BLOCK_SIZE"
  --policy.gpt_input_dim="$VQBET_GPT_INPUT_DIM"
  --policy.gpt_output_dim="$VQBET_GPT_OUTPUT_DIM"
  --policy.gpt_n_layer="$VQBET_GPT_N_LAYER"
  --policy.gpt_n_head="$VQBET_GPT_N_HEAD"
  --policy.gpt_hidden_dim="$VQBET_GPT_HIDDEN_DIM"
  --policy.dropout="$VQBET_DROPOUT"
  --policy.offset_loss_weight="$VQBET_OFFSET_LOSS_WEIGHT"
  --policy.primary_code_loss_weight="$VQBET_PRIMARY_CODE_LOSS_WEIGHT"
  --policy.secondary_code_loss_weight="$VQBET_SECONDARY_CODE_LOSS_WEIGHT"
  --policy.optimizer_lr="$VQBET_OPTIMIZER_LR"
  --policy.optimizer_weight_decay="$VQBET_OPTIMIZER_WEIGHT_DECAY"
  --policy.optimizer_vqvae_lr="$VQBET_OPTIMIZER_VQVAE_LR"
  --policy.optimizer_vqvae_weight_decay="$VQBET_OPTIMIZER_VQVAE_WEIGHT_DECAY"
  --policy.scheduler_warmup_steps="$VQBET_SCHEDULER_WARMUP_STEPS"
  --output_dir="$run_dir"
  --job_name="$run_id"
  --batch_size="$batch_size"
  --steps="$steps"
  --num_workers="$NUM_WORKERS"
  --save_freq="$SAVE_FREQ"
  --eval_steps="$EVAL_STEPS"
  --wandb.enable=false
)
if [[ "$mode" == "single" ]]; then
  launch_args=(env CUDA_VISIBLE_DEVICES=0 lerobot-train "${train_args[@]}")
else
  launch_args=(env CUDA_VISIBLE_DEVICES=0,1,2,3 accelerate launch --multi_gpu --num_processes=4 --mixed_precision=bf16 lerobot-train "${train_args[@]}")
fi
printf 'POLICY=vqbet\nTRAIN_DATASET_ROOT=%s\nRUN_DIR=%s\nCommand: ' "$DATASET_ROOT" "$run_dir"
print_command "${launch_args[@]}"
[[ "$dry_run" == true ]] && exit 0
[[ "$confirm_train" == true ]] || die "training requires --confirm-train"
[[ ! -e "$run_dir" ]] || die "run directory already exists: ${run_dir}"
command -v lerobot-train >/dev/null || die "lerobot-train not found; activate LeRobot environment first"
[[ "$mode" == "single" ]] || command -v accelerate >/dev/null || die "accelerate not found; activate LeRobot training environment first"
mkdir -p "$run_dir"
printf 'policy=vqbet\ntask=%s\nversion=%s\ndataset_id=%s\ndataset_root=%s\nmode=%s\nprofile=%s\nbatch_size=%s\nsteps=%s\nn_vqvae_training_steps=%s\nstrategy_config=%s\n' \
  "$TASK_SLUG" "$DATASET_VERSION" "$DATASET_ID" "$DATASET_ROOT" "$mode" "$profile" "$batch_size" "$steps" "$vqvae_steps" "${strategy_dir}/vqbet.env" > "${run_dir}/RUN_CONTEXT.txt"
exec "${launch_args[@]}"
