#!/usr/bin/env bash
set -euo pipefail

# Verify the host-side prerequisites for an SO-101 collection session. This
# script does not open a serial port, power motors, move either arm, or create
# a dataset.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${script_dir}/lib.sh"

config_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_file="${2:-}"; shift 2 ;;
    --help)
      printf 'Usage: preflight_collection.sh --config <fms688.env>\n'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

load_config "$config_file"

failures=0

pass() {
  printf 'PASS: %s\n' "$*"
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  failures=$((failures + 1))
}

is_placeholder() {
  [[ "$1" == *'<'* || "$1" == *'>'* ]]
}

require_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "command available: $command_name"
  else
    fail "command unavailable: $command_name; activate the LeRobot environment first"
  fi
}

require_group() {
  local group_name="$1"
  if id -nG | tr ' ' '\n' | grep -Fx "$group_name" >/dev/null; then
    pass "user belongs to group: $group_name"
  else
    fail "user is not in group: $group_name; run sudo usermod -aG dialout,video \"\$USER\" and log in again"
  fi
}

require_serial_port() {
  local name="$1"
  local device_path="$2"
  if is_placeholder "$device_path"; then
    fail "$name still has a placeholder: $device_path"
  elif [[ ! -c "$device_path" ]]; then
    fail "$name is not a character device: $device_path"
  elif [[ ! -r "$device_path" || ! -w "$device_path" ]]; then
    fail "$name is not readable and writable: $device_path"
  else
    pass "$name is accessible: $device_path"
  fi
}

require_camera() {
  local name="$1"
  local device_path="$2"
  local width="$3"
  local height="$4"
  local fourcc="$5"
  local format_listing

  if is_placeholder "$device_path"; then
    fail "$name still has a placeholder: $device_path"
    return
  fi
  if [[ ! -c "$device_path" ]]; then
    fail "$name is not a character device: $device_path"
    return
  fi
  if [[ ! -r "$device_path" || ! -w "$device_path" ]]; then
    fail "$name is not readable and writable: $device_path"
    return
  fi
  if ! format_listing="$(v4l2-ctl --device="$device_path" --list-formats-ext 2>/dev/null)"; then
    fail "$name cannot list capture formats: $device_path"
    return
  fi
  if ! grep -F "Size: Discrete ${width}x${height}" <<<"$format_listing" >/dev/null; then
    fail "$name does not advertise ${width}x${height}: $device_path"
    return
  fi
  if [[ -n "$fourcc" ]] && ! awk -v fourcc="$fourcc" -v size="Size: Discrete ${width}x${height}" '
    /^\t*\[[0-9]+\]:/ {
      format_matches = index($0, sprintf("%c%s%c", 39, fourcc, 39)) > 0
      next
    }
    format_matches && index($0, size) { found = 1 }
    END { exit !found }
  ' <<<"$format_listing"; then
    fail "$name does not advertise ${fourcc} at ${width}x${height}: $device_path"
    return
  fi
  if [[ -n "$fourcc" ]]; then
    pass "$name is accessible and supports ${fourcc} at ${width}x${height}: $device_path"
  else
    pass "$name is accessible and supports ${width}x${height}: $device_path"
  fi
}

printf 'Collection preflight: no motor commands or dataset writes will run.\n'
printf '进度 [预检步骤] 0%% (0/5)：检查命令；完成比例不等于检查通过。\n'
require_command lerobot-record
require_command lerobot-find-port
require_command lerobot-find-cameras
require_command v4l2-ctl
printf '进度 [预检步骤] 20%% (1/5)：检查账户权限。\n'
require_group dialout
require_group video

printf '进度 [预检步骤] 40%% (2/5)：检查数据目录和串口。\n'
if [[ -d "$FMS688_DATA" && -w "$FMS688_DATA" ]]; then
  pass "data root is writable: $FMS688_DATA"
else
  fail "data root is not a writable directory: $FMS688_DATA"
fi

require_serial_port FOLLOWER_PORT "$FOLLOWER_PORT"
require_serial_port LEADER_PORT "$LEADER_PORT"
if [[ "$FOLLOWER_PORT" == "$LEADER_PORT" ]]; then
  fail 'FOLLOWER_PORT and LEADER_PORT must be different devices'
fi

printf '进度 [预检步骤] 60%% (3/5)：检查相机设备与格式。\n'
require_camera TOP_CAMERA "$TOP_CAMERA" "$TOP_WIDTH" "$TOP_HEIGHT" "$TOP_FOURCC"
require_camera WRIST_CAMERA "$WRIST_CAMERA" "$WRIST_WIDTH" "$WRIST_HEIGHT" "$WRIST_FOURCC"
if [[ "$TOP_CAMERA" == "$WRIST_CAMERA" ]]; then
  fail 'TOP_CAMERA and WRIST_CAMERA must be different capture devices'
fi

if (( failures > 0 )); then
  printf 'PRE-FLIGHT FAILED: %d issue(s) need correction before collection.\n' "$failures" >&2
  exit 1
fi

printf '进度 [预检步骤] 80%% (4/5)：读取硬件配置并进行双相机帧率检查。\n'
python3 "${script_dir}/collection.py" hardware
printf '进度 [预检步骤] 100%% (5/5)。\n'
printf 'PRE-FLIGHT PASSED: host is ready for the next collection step.\n'
