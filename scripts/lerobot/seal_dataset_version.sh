#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

config_file=""
action="dry-run"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --dry-run) action="dry-run"; shift ;;
    --confirm-seal) action="seal"; shift ;;
    --confirm-unseal) action="unseal"; shift ;;
    --help)
      printf 'Usage: seal_dataset_version.sh --config <fms688.env> [--dry-run|--confirm-seal|--confirm-unseal]\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
round_root="${FMS688_DATA}/rounds/${TASK_SLUG}/${DATASET_VERSION}"
require_dataset_not_quarantined

if [[ "$action" == "unseal" ]]; then
  [[ -f "$DATASET_SEAL" ]] || die "dataset version is not sealed: $DATASET_SEAL"
  rm -f -- "$DATASET_SEAL"
  printf 'UNSEALED: %s. Any resumed formal run is now invalid until the version is sealed again.\n' "$DATASET_SEAL"
  exit 0
fi

require_master_dataset
info_json="${DATASET_ROOT}/meta/info.json"
[[ -f "$info_json" ]] || die "LeRobot metadata not found: $info_json"
python3 - "$info_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    json.load(handle)
PY

mapfile -d '' manifests < <(find "$round_root" -mindepth 2 -maxdepth 2 -type f -name ROUND.md -print0 2>/dev/null | sort -z)
(( ${#manifests[@]} > 0 )) || die "no round manifests found below: $round_root"
for manifest in "${manifests[@]}"; do
  require_round_qa_passed "$manifest" copied-source
done

read -r dataset_files dataset_bytes < <(python3 - "$DATASET_ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
files = [path for path in root.rglob("*") if path.is_file()]
print(len(files), sum(path.stat().st_size for path in files))
PY
)

printf 'Dataset: %s\n' "$DATASET_ROOT"
printf 'Seal record: %s\n' "$DATASET_SEAL"
printf 'Qualified rounds: %s\n' "${#manifests[@]}"
printf 'Dataset snapshot: files=%s bytes=%s\n' "$dataset_files" "$dataset_bytes"
if [[ "$action" == "dry-run" ]]; then
  printf 'Dry-run only. Use --confirm-seal on the 5090 server after the final synchronized round.\n'
  exit 0
fi

[[ ! -e "$DATASET_SEAL" ]] || die "dataset version is already sealed: $DATASET_SEAL"
mkdir -p "$round_root"
seal_tmp="$(mktemp "${DATASET_SEAL}.tmp.XXXXXX")"
trap 'rm -f "$seal_tmp"' EXIT
{
  printf 'status=sealed\n'
  printf 'dataset_id=%s\n' "$DATASET_ID"
  printf 'dataset_root=%s\n' "$DATASET_ROOT"
  printf 'sealed_at=%s\n' "$(date -Iseconds)"
  printf 'round_count=%s\n' "${#manifests[@]}"
  printf 'dataset_files=%s\n' "$dataset_files"
  printf 'dataset_bytes=%s\n' "$dataset_bytes"
  printf 'rule=formal training may start; append requires explicit unseal and a new run\n'
} >"$seal_tmp"
mv -- "$seal_tmp" "$DATASET_SEAL"
trap - EXIT
printf 'SEALED: %s\n' "$DATASET_SEAL"
