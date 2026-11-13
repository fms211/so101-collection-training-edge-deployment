#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

load_config() {
  local config_file="$1"
  [[ -n "$config_file" ]] || die "missing --config"
  [[ -f "$config_file" ]] || die "config file not found: $config_file"
  # These are optional so existing local configurations keep their current
  # auto-detected format behavior. When set, recording validates a fourcc.
  unset TOP_FOURCC WRIST_FOURCC HF_REPO_ID CALIBRATION_ROOT MIN_FREE_GB MAX_RELATIVE_TARGET
  # shellcheck source=/dev/null
  source "$config_file"
  TOP_FOURCC="${TOP_FOURCC:-}"
  WRIST_FOURCC="${WRIST_FOURCC:-}"
  HF_REPO_ID="${HF_REPO_ID:-}"
  CALIBRATION_ROOT="${CALIBRATION_ROOT:-${FMS688_DATA}/calibration}"
  MIN_FREE_GB="${MIN_FREE_GB:-10}"
  MAX_RELATIVE_TARGET="${MAX_RELATIVE_TARGET:-1.0}"
  require_config_values
  derive_paths
  export FMS688_DATA DATASET_ID DATASET_ROOT ROUND_DIR DATASET_SEAL DATASET_QUARANTINE
  export DATASET_NAMESPACE HF_REPO_ID
  export TASK_SLUG TASK_DESCRIPTION DATASET_VERSION ROUND_ID EPISODES_THIS_ROUND FPS
  export FOLLOWER_PORT LEADER_PORT FOLLOWER_ID LEADER_ID TOP_CAMERA WRIST_CAMERA
  export TOP_WIDTH TOP_HEIGHT WRIST_WIDTH WRIST_HEIGHT TOP_FOURCC WRIST_FOURCC
  export CALIBRATION_ROOT MIN_FREE_GB MAX_RELATIVE_TARGET
  if [[ -n "${HF_DATASETS_CACHE:-}" ]]; then
    export HF_DATASETS_CACHE
  fi
}

require_config_values() {
  local required=(
    FMS688_DATA DATASET_NAMESPACE TASK_SLUG TASK_DESCRIPTION DATASET_VERSION ROUND_ID
    EPISODES_THIS_ROUND EPISODE_MAX_TIME_S RESET_MAX_TIME_S FPS
    FOLLOWER_PORT LEADER_PORT FOLLOWER_ID LEADER_ID
    TOP_CAMERA WRIST_CAMERA TOP_WIDTH TOP_HEIGHT WRIST_WIDTH WRIST_HEIGHT
    NUM_WORKERS SAVE_FREQ EVAL_STEPS
  )
  local name
  for name in "${required[@]}"; do
    [[ -n "${!name:-}" ]] || die "missing required config value: $name"
  done
  [[ "$TASK_DESCRIPTION" =~ [^[:space:]] ]] || die "TASK_DESCRIPTION must contain a non-whitespace character"
  [[ "$TASK_DESCRIPTION" != *$'\n'* && "$TASK_DESCRIPTION" != *$'\r'* ]] || die "TASK_DESCRIPTION must be a single line"
  [[ "$DATASET_NAMESPACE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "DATASET_NAMESPACE contains unsafe characters"
  [[ "$TASK_SLUG" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "TASK_SLUG must use lowercase letters, numbers, underscores, or hyphens"
  [[ "$ROUND_ID" =~ ^r[0-9][0-9]+$ ]] || die "ROUND_ID must look like r01, r02, or r03"
  [[ "$DATASET_VERSION" =~ ^v[0-9][0-9][0-9]+$ || "$DATASET_VERSION" =~ ^[0-9]{8}_[a-z0-9][a-z0-9_-]*$ ]] || die "DATASET_VERSION must be a legacy v001 or YYYYMMDD_task name"
  [[ "$EPISODES_THIS_ROUND" =~ ^[1-9][0-9]*$ ]] || die "EPISODES_THIS_ROUND must be a positive integer"
  [[ -z "$HF_REPO_ID" || "$HF_REPO_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "HF_REPO_ID must be owner/dataset"
  [[ -z "$TOP_FOURCC" || "$TOP_FOURCC" =~ ^[[:alnum:]]{4}$ ]] || die "TOP_FOURCC must be empty or a 4-character alphanumeric code such as MJPG"
  [[ -z "$WRIST_FOURCC" || "$WRIST_FOURCC" =~ ^[[:alnum:]]{4}$ ]] || die "WRIST_FOURCC must be empty or a 4-character alphanumeric code such as MJPG"
  [[ "$MAX_RELATIVE_TARGET" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "MAX_RELATIVE_TARGET must be a positive number such as 1.0"
}

derive_paths() {
  DATASET_ID="${DATASET_NAMESPACE}/so101_${TASK_SLUG}_${DATASET_VERSION}"
  if [[ "$DATASET_VERSION" =~ ^[0-9]{8}_ ]]; then
    DATASET_ID="${DATASET_NAMESPACE}/so101_${DATASET_VERSION}"
  fi
  DATASET_ID="${HF_REPO_ID:-$DATASET_ID}"
  DATASET_ROOT="${FMS688_DATA}/datasets/${TASK_SLUG}/${DATASET_VERSION}"
  ROUND_DIR="${FMS688_DATA}/rounds/${TASK_SLUG}/${DATASET_VERSION}/${ROUND_ID}"
  DATASET_SEAL="${FMS688_DATA}/rounds/${TASK_SLUG}/${DATASET_VERSION}/DATASET_SEALED.md"
  DATASET_QUARANTINE="${FMS688_DATA}/rounds/${TASK_SLUG}/${DATASET_VERSION}/DATASET_QUARANTINED.md"
  TRAIN_OUTPUT_ROOT="${FMS688_DATA}/runs"
}

round_resume_value() {
  if [[ "$ROUND_ID" == "r01" ]]; then
    printf 'false\n'
  else
    printf 'true\n'
  fi
}

print_command() {
  local item
  for item in "$@"; do
    printf '%q ' "$item"
  done
  printf '\n'
}

require_round_manifest() {
  local manifest="${ROUND_DIR}/ROUND.md"
  [[ -f "$manifest" ]] || die "run init_round.sh before record_round.sh: $manifest"
  require_manifest_dataset_identity "$manifest"
  require_manifest_value "$manifest" round "$ROUND_ID"
  require_manifest_value "$manifest" resume "$(round_resume_value)"
}

last_manifest_value() {
  local manifest="$1"
  local key="$2"
  sed -n "s/^${key}=//p" "$manifest" | tail -n 1 | tr -d '\r'
}

require_manifest_value() {
  local manifest="$1"
  local key="$2"
  local expected="$3"
  local actual
  actual="$(last_manifest_value "$manifest" "$key")"
  [[ "$actual" == "$expected" ]] || die "round manifest ${key} mismatch: expected [$expected], got [${actual:-<missing>}] in $manifest"
}

require_manifest_dataset_identity() {
  local manifest="$1"
  require_manifest_value "$manifest" task "$TASK_SLUG"
  require_manifest_value "$manifest" task_description "$TASK_DESCRIPTION"
  require_manifest_value "$manifest" version "$DATASET_VERSION"
  require_manifest_value "$manifest" dataset_id "$DATASET_ID"
  require_manifest_value "$manifest" dataset_root "$DATASET_ROOT"
}

require_round_qa_passed() {
  local manifest="$1"
  [[ -f "$manifest" ]] || die "round manifest not found: $manifest"
  if [[ "${2:-}" == "copied-source" ]]; then
    # ROUND.md was written on the collector and keeps its absolute source path.
    # The server's synchronized copy has a different HOME but the same task/version.
    require_manifest_value "$manifest" task "$TASK_SLUG"
    require_manifest_value "$manifest" task_description "$TASK_DESCRIPTION"
    require_manifest_value "$manifest" version "$DATASET_VERSION"
    require_manifest_value "$manifest" dataset_id "$DATASET_ID"
    local source_root
    source_root="$(last_manifest_value "$manifest" dataset_root)"
    [[ "$source_root" == "$DATASET_ROOT" || "$source_root" == /*/datasets/"$TASK_SLUG"/"$DATASET_VERSION" ]] || \
      die "round manifest dataset_root mismatch: expected local root or collector datasets/${TASK_SLUG}/${DATASET_VERSION}, got [$source_root] in $manifest"
  else
    require_manifest_dataset_identity "$manifest"
  fi
  [[ "$(last_manifest_value "$manifest" quality)" == "pass" ]] || die "latest quality must be pass before synchronization or sealing: $manifest"
  [[ "$(last_manifest_value "$manifest" status)" == "closed" ]] || die "latest status must be closed before synchronization or sealing: $manifest"
}

require_master_dataset() {
  [[ -d "$DATASET_ROOT" ]] || die "master dataset directory not found: $DATASET_ROOT"
}

require_dataset_not_quarantined() {
  [[ ! -e "$DATASET_QUARANTINE" ]] || die "dataset version is quarantined: $DATASET_QUARANTINE"
}

require_dataset_writable() {
  require_dataset_not_quarantined
  [[ ! -e "$DATASET_SEAL" ]] || die "dataset version is sealed: $DATASET_SEAL"
}

require_dataset_seal() {
  [[ -f "$DATASET_SEAL" ]] || die "dataset version is not sealed: $DATASET_SEAL"
  grep -Fx 'status=sealed' "$DATASET_SEAL" >/dev/null || die "invalid dataset seal status: $DATASET_SEAL"
  grep -Fx "dataset_id=${DATASET_ID}" "$DATASET_SEAL" >/dev/null || die "dataset seal identity mismatch: $DATASET_SEAL"
}
