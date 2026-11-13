#!/usr/bin/env bash
set -euo pipefail

# 兼容旧入口：实际 ACT 实现已迁入 strategies-训练策略脚本/act/train_act.sh。
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${script_dir}/strategies-训练策略脚本/act/train_act.sh" "$@"

