#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

config_file=""
server_alias=""
round_override=""
dry_run=true
confirm_sync=false
SSH_BIN="${SSH_BIN:-ssh}"
RSYNC_BIN="${RSYNC_BIN:-rsync}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --server) server_alias="${2:-}"; shift 2 ;;
    --round) round_override="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --confirm-sync) dry_run=false; confirm_sync=true; shift ;;
    --help)
      printf 'Usage: sync_dataset_to_server.sh --config <fms688.env> --server <ssh-alias> --round r01 [--dry-run|--confirm-sync]\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"
[[ -n "$server_alias" ]] || die "missing --server SSH alias"
[[ "$server_alias" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "--server must be a safe SSH alias from ~/.ssh/config"
if [[ -n "$round_override" ]]; then
  ROUND_ID="$round_override"
  [[ "$ROUND_ID" =~ ^r[0-9][0-9]+$ ]] || die "--round must look like r01, r02, or r03"
  derive_paths
fi
require_dataset_not_quarantined

manifest="${ROUND_DIR}/ROUND.md"
require_round_manifest
require_round_qa_passed "$manifest"
require_master_dataset
info_json="${DATASET_ROOT}/meta/info.json"
[[ -f "$info_json" ]] || die "LeRobot metadata not found: $info_json"
python3 - "$info_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    json.load(handle)
PY

remote_dataset_display="${server_alias}:~/fms688_data/datasets/${TASK_SLUG}/${DATASET_VERSION}/"
remote_round_display="${server_alias}:~/fms688_data/rounds/${TASK_SLUG}/${DATASET_VERSION}/${ROUND_ID}/"
dry_dataset_args=(
  "$RSYNC_BIN"
  --archive
  --partial
  --human-readable
  --info=progress2
  --
  "${DATASET_ROOT}/"
  "$remote_dataset_display"
)
dry_round_args=(
  "$RSYNC_BIN"
  --archive
  --partial
  --human-readable
  --info=progress2
  --
  "${ROUND_DIR}/"
  "$remote_round_display"
)

printf 'Dataset owner: this laptop (the server copy is training-only)\n'
printf 'Round: %s\n' "$ROUND_ID"
printf 'Local dataset: %s/\n' "$DATASET_ROOT"
printf 'Local round: %s/\n' "$ROUND_DIR"
printf 'Remote dataset: %s\n' "$remote_dataset_display"
printf 'Remote round: %s\n' "$remote_round_display"
printf 'Dataset command: '
print_command "${dry_dataset_args[@]}"
printf 'Round command: '
print_command "${dry_round_args[@]}"

if [[ "$dry_run" == true ]]; then
  printf 'Dry-run only. No SSH connection or file transfer was attempted. Use --confirm-sync after the round passes QA.\n'
  exit 0
fi

[[ "$confirm_sync" == true ]] || die "synchronization requires --confirm-sync"
command -v "$SSH_BIN" >/dev/null || die "SSH client not found: $SSH_BIN"
command -v "$RSYNC_BIN" >/dev/null || die "rsync not found: $RSYNC_BIN"

resolve_command='printf "__FMS688_REMOTE_HOME__=%s\n" "$HOME"'
if ! remote_home_output="$($SSH_BIN -o BatchMode=yes -o ConnectTimeout=10 "$server_alias" "$resolve_command")"; then
  die "SSH connection failed for alias: $server_alias"
fi
remote_home="$(printf '%s\n' "$remote_home_output" | sed -n 's/^__FMS688_REMOTE_HOME__=//p' | tail -n 1)"
[[ "$remote_home" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "remote HOME is not a safe absolute path: $remote_home"
[[ "$remote_home" != "/" && "$remote_home" != *".."* ]] || die "refusing unsafe remote HOME: $remote_home"

remote_root="${remote_home%/}/fms688_data"
remote_dataset_root="${remote_root}/datasets/${TASK_SLUG}/${DATASET_VERSION}"
remote_round_dir="${remote_root}/rounds/${TASK_SLUG}/${DATASET_VERSION}/${ROUND_ID}"
remote_seal="${remote_root}/rounds/${TASK_SLUG}/${DATASET_VERSION}/DATASET_SEALED.md"
[[ "$remote_dataset_root" == "$remote_root"/datasets/* ]] || die "remote dataset path escaped fms688_data"
[[ "$remote_round_dir" == "$remote_root"/rounds/* ]] || die "remote round path escaped fms688_data"

seal_command="if test -e '$remote_seal'; then printf '__FMS688_SEAL_STATE__=sealed\\n'; else printf '__FMS688_SEAL_STATE__=absent\\n'; fi"
if ! seal_output="$($SSH_BIN -o BatchMode=yes "$server_alias" "$seal_command")"; then
  die "SSH connection failed while checking the server dataset seal"
fi
if grep -F '__FMS688_SEAL_STATE__=sealed' <<<"$seal_output" >/dev/null; then
  die "server dataset version is sealed; unseal it on the server before appending another round"
fi

mkdir_command="mkdir -p -- '$remote_dataset_root' '$remote_round_dir'"
if ! $SSH_BIN -o BatchMode=yes "$server_alias" "$mkdir_command"; then
  die "SSH connection failed while creating server destination directories"
fi

dataset_sync_args=(
  "$RSYNC_BIN"
  --archive
  --partial
  --human-readable
  --info=progress2
  --
  "${DATASET_ROOT}/"
  "${server_alias}:${remote_dataset_root}/"
)
round_sync_args=(
  "$RSYNC_BIN"
  --archive
  --partial
  --human-readable
  --info=progress2
  --
  "${ROUND_DIR}/"
  "${server_alias}:${remote_round_dir}/"
)

if ! "${dataset_sync_args[@]}"; then
  die "dataset rsync failed; fix the network and rerun the same command"
fi
if ! "${round_sync_args[@]}"; then
  die "round rsync failed; fix the network and rerun the same command"
fi

tree_stats() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
files = [path for path in root.rglob("*") if path.is_file()]
print(len(files), sum(path.stat().st_size for path in files))
PY
}

read -r local_dataset_files local_dataset_bytes < <(tree_stats "$DATASET_ROOT")
read -r local_round_files local_round_bytes < <(tree_stats "$ROUND_DIR")
verify_command="printf '__FMS688_VERIFY__\\n'; dataset_files=\$(find '$remote_dataset_root' -type f | wc -l); dataset_bytes=\$(find '$remote_dataset_root' -type f -printf '%s\\n' | awk '{sum += \$1} END {print sum + 0}'); round_files=\$(find '$remote_round_dir' -type f | wc -l); round_bytes=\$(find '$remote_round_dir' -type f -printf '%s\\n' | awk '{sum += \$1} END {print sum + 0}'); if python3 -c \"import json; json.load(open('$remote_dataset_root/meta/info.json', encoding='utf-8'))\"; then meta_ok=1; else meta_ok=0; fi; printf 'DATASET_FILES=%s\\nDATASET_BYTES=%s\\nROUND_FILES=%s\\nROUND_BYTES=%s\\nMETA_OK=%s\\n' \"\$dataset_files\" \"\$dataset_bytes\" \"\$round_files\" \"\$round_bytes\" \"\$meta_ok\""
if ! verify_output="$($SSH_BIN -o BatchMode=yes "$server_alias" "$verify_command")"; then
  die "SSH connection failed during post-transfer verification"
fi

read_metric() {
  local name="$1"
  printf '%s\n' "$verify_output" | sed -n "s/^${name}=//p" | tail -n 1
}

remote_dataset_files="$(read_metric DATASET_FILES)"
remote_dataset_bytes="$(read_metric DATASET_BYTES)"
remote_round_files="$(read_metric ROUND_FILES)"
remote_round_bytes="$(read_metric ROUND_BYTES)"
remote_meta_ok="$(read_metric META_OK)"

if [[ "$local_dataset_files" != "$remote_dataset_files" \
  || "$local_dataset_bytes" != "$remote_dataset_bytes" \
  || "$local_round_files" != "$remote_round_files" \
  || "$local_round_bytes" != "$remote_round_bytes" \
  || "$remote_meta_ok" != "1" ]]; then
  printf 'Local dataset: files=%s bytes=%s\n' "$local_dataset_files" "$local_dataset_bytes" >&2
  printf 'Remote dataset: files=%s bytes=%s meta_ok=%s\n' "$remote_dataset_files" "$remote_dataset_bytes" "$remote_meta_ok" >&2
  printf 'Local round: files=%s bytes=%s\n' "$local_round_files" "$local_round_bytes" >&2
  printf 'Remote round: files=%s bytes=%s\n' "$remote_round_files" "$remote_round_bytes" >&2
  die "post-transfer verification mismatch; do not start training"
fi

printf 'SYNC VERIFIED: %s/%s %s is complete on %s.\n' "$TASK_SLUG" "$DATASET_VERSION" "$ROUND_ID" "$server_alias"
printf 'Server training input: %s\n' "$remote_dataset_root"
