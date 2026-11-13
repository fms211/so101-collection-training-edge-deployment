#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 兼容旧 ACT 恢复入口：把 --run-id 转为 ACT 专属的 --resume-run-id。
forward_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      forward_args+=(--resume-run-id "${2:-}")
      shift 2
      ;;
    --help)
      printf 'Usage: resume_train.sh --config <fms688.env> --run-id <existing-act-run-id> [--dry-run|--confirm-train]\n'
      exit 0
      ;;
    *)
      forward_args+=("$1")
      shift
      ;;
  esac
done
exec "${script_dir}/strategies-训练策略脚本/act/train_act.sh" "${forward_args[@]}"

