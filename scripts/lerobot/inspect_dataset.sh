#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

config_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --help)
      printf 'Usage: inspect_dataset.sh --config <fms688.env>\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
round_root="${FMS688_DATA}/rounds/${TASK_SLUG}/${DATASET_VERSION}"

printf 'DATASET_ID=%s\n' "$DATASET_ID"
printf 'DATASET_ROOT=%s\n' "$DATASET_ROOT"
printf 'TRAIN_DATASET_ROOT=%s\n' "$DATASET_ROOT"
printf 'TRAIN_OUTPUT_ROOT=%s\n' "$TRAIN_OUTPUT_ROOT"
printf 'ROUND_ROOT=%s\n' "$round_root"
if [[ -f "$DATASET_QUARANTINE" ]]; then
  printf 'DATASET_QUARANTINE=present\n'
  printf 'DATASET_QUARANTINE_FILE=%s\n' "$DATASET_QUARANTINE"
else
  printf 'DATASET_QUARANTINE=absent\n'
fi

if [[ -d "$DATASET_ROOT" ]]; then
  printf 'MASTER_DATASET_SIZE='
  du -sh "$DATASET_ROOT" | awk '{print $1}'
else
  printf 'MASTER_DATASET_SIZE=not_created\n'
fi

printf 'ROUND_MANIFESTS:\n'
find "$round_root" -name ROUND.md -print 2>/dev/null | sort || true
