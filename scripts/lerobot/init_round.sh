#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

config_file=""
round_override=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --round) round_override="${2:-}"; shift 2 ;;
    --help)
      printf 'Usage: init_round.sh --config <fms688.env> --round r01\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
if [[ -n "$round_override" ]]; then
  ROUND_ID="$round_override"
  [[ "$ROUND_ID" =~ ^r[0-9][0-9]+$ ]] || die "--round must look like r01, r02, or r03"
  derive_paths
fi
require_dataset_writable

resume_value="$(round_resume_value)"
mkdir -p "$(dirname "$DATASET_ROOT")" "$ROUND_DIR" "$TRAIN_OUTPUT_ROOT"
manifest="${ROUND_DIR}/ROUND.md"
[[ ! -e "$manifest" ]] || die "round already exists: $manifest"
python3 "${script_dir}/collection.py" init

printf 'round=%s\ntask=%s\ntask_description=%s\nversion=%s\ndataset_id=%s\ndataset_root=%s\nresume=%s\nstatus=ready\n' \
  "$ROUND_ID" "$TASK_SLUG" "$TASK_DESCRIPTION" "$DATASET_VERSION" "$DATASET_ID" "$DATASET_ROOT" "$resume_value" \
  > "$manifest"


printf 'Created round manifest: %s\n' "$manifest"
printf 'Master dataset: %s\n' "$DATASET_ROOT"
printf 'Training output root: %s\n' "$TRAIN_OUTPUT_ROOT"
