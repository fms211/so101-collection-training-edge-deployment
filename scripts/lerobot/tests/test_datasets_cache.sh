#!/usr/bin/env bash
set -euo pipefail
scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
sed "s|FMS688_DATA=\"\$HOME/fms688_data\"|FMS688_DATA=\"$tmp/data\"|" "$scripts_dir/fms688.env.example" > "$tmp/config.env"
source "$scripts_dir/lib.sh"
load_config "$tmp/config.env"
[[ "$HF_DATASETS_CACHE" == "$tmp/data/cache/hf_datasets" ]]
[[ "$(bash -c 'printf %s "$HF_DATASETS_CACHE"')" == "$tmp/data/cache/hf_datasets" ]]
printf 'PASS: dataset cache follows configured data root and reaches child processes\n'
