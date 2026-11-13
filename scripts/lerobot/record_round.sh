#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

build_camera_config() {
  local device_path="$1"
  local width="$2"
  local height="$3"
  local fourcc="$4"
  local config="{type: opencv, index_or_path: ${device_path}, width: ${width}, height: ${height}, fps: ${FPS}"

  if [[ -n "$fourcc" ]]; then
    config+=", fourcc: \"${fourcc}\""
  fi
  printf '%s}' "$config"
}

config_file=""
round_override=""
dry_run=true
confirm_physical=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --round) round_override="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --confirm-physical) dry_run=false; confirm_physical=true; shift ;;
    --help)
      printf 'Usage: record_round.sh --config <fms688.env> --round r01 [--dry-run|--confirm-physical]\n'
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
require_round_manifest

if [[ "$ROUND_ID" != "r01" ]]; then
  require_master_dataset
fi

resume_value="$(round_resume_value)"
top_camera_config="$(build_camera_config "$TOP_CAMERA" "$TOP_WIDTH" "$TOP_HEIGHT" "$TOP_FOURCC")"
wrist_camera_config="$(build_camera_config "$WRIST_CAMERA" "$WRIST_WIDTH" "$WRIST_HEIGHT" "$WRIST_FOURCC")"
robot_cameras="{top: ${top_camera_config}, wrist: ${wrist_camera_config}}"

record_args=(
  python3 "${script_dir}/record_sent_action.py"
  --robot.type=so101_follower
  --robot.port="$FOLLOWER_PORT"
  --robot.id="$FOLLOWER_ID"
  --robot.calibration_dir="${CALIBRATION_ROOT}/robots/so_follower"
  --robot.max_relative_target="${MAX_RELATIVE_TARGET:-1.0}"
  --robot.cameras="$robot_cameras"
  --teleop.type=so101_leader
  --teleop.port="$LEADER_PORT"
  --teleop.id="$LEADER_ID"
  --teleop.calibration_dir="${CALIBRATION_ROOT}/teleoperators/so_leader"
  --dataset.repo_id="$DATASET_ID"
  --dataset.root="$DATASET_ROOT"
  --dataset.push_to_hub=False
  --dataset.no_stamp=true
  --dataset.video=false
  --dataset.num_episodes="$EPISODES_THIS_ROUND"
  --dataset.episode_time_s="$EPISODE_MAX_TIME_S"
  --dataset.reset_time_s="$RESET_MAX_TIME_S"
  --dataset.fps="$FPS"
  --dataset.single_task="$TASK_DESCRIPTION"
  --display_data=true
)
if [[ "$resume_value" == "true" ]]; then
  record_args+=(--resume=true)
fi

printf 'Round: %s\n' "$ROUND_ID"
printf 'Master dataset: %s\n' "$DATASET_ROOT"
printf 'Round manifest: %s\n' "${ROUND_DIR}/ROUND.md"
printf 'Keyboard controls: n=next phase; r=discard and re-record; q=quit (may save the current buffer; not an emergency stop).\n'
printf 'Manual-first limits: episode=%ss, reset=%ss (timeouts remain a last-resort automatic switch).\n' "$EPISODE_MAX_TIME_S" "$RESET_MAX_TIME_S"
printf 'Command: '
print_command "${record_args[@]}"

if [[ "$dry_run" == true ]]; then
  printf 'Dry-run only. Add --confirm-physical after checking power, cameras, ports, and ROUND.md.\n'
  exit 0
fi

[[ "$confirm_physical" == true ]] || die "physical recording requires --confirm-physical"
[[ -t 0 ]] || die "physical recording requires an interactive TTY for keyboard controls; do not run in nohup, a pipe, or CI"
[[ ! -e "$FMS688_DATA/PHYSICAL_SAFETY_HOLD.md" ]] || die "PHYSICAL_SAFETY_HOLD: resolve the recorded incident before physical operation"
command -v lerobot-record >/dev/null || die "lerobot-record not found; activate LeRobot environment first"
python3 "${script_dir}/record_sent_action.py" --check-adapter
bash "${script_dir}/preflight_collection.sh" --config "$config_file"
exec python3 "${script_dir}/collection.py" run -- "${record_args[@]}"
