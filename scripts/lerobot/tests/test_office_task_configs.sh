#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
scripts_dir="$repo_root/scripts/lerobot"
task_configs_dir="$scripts_dir/task-configs"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file $1"
}

assert_contains() {
  local expected="$1"
  local file="$2"
  grep -F -- "$expected" "$file" >/dev/null || fail "missing [$expected] in $file"
}

check_task_config() {
  local filename="$1"
  local expected_slug="$2"
  local expected_description="$3"
  local expected_episodes="$4"
  local source_config="$task_configs_dir/$filename"
  local staged_config="$temp_root/$filename"
  local output_file="$temp_root/${expected_slug}.out"
  local manifest="$temp_root/fms688_data/rounds/$expected_slug/v001/r01/ROUND.md"

  assert_file "$source_config"
  sed "s|^FMS688_DATA=.*|FMS688_DATA=\"$temp_root/fms688_data\"|" "$source_config" > "$staged_config"

  (
    # shellcheck source=/dev/null
    source "$staged_config"
    [[ "$TASK_SLUG" == "$expected_slug" ]] || fail "unexpected TASK_SLUG in $filename"
    [[ "$TASK_DESCRIPTION" == "$expected_description" ]] || fail "unexpected TASK_DESCRIPTION in $filename"
    [[ "$DATASET_VERSION" == "v001" ]] || fail "unexpected DATASET_VERSION in $filename"
    [[ "$ROUND_ID" == "r01" ]] || fail "unexpected ROUND_ID in $filename"
    [[ "$EPISODES_THIS_ROUND" == "$expected_episodes" ]] || fail "unexpected EPISODES_THIS_ROUND in $filename"
    [[ "$FPS" == "30" ]] || fail "unexpected FPS in $filename"
    [[ "$TOP_WIDTH" == "640" && "$TOP_HEIGHT" == "480" ]] || fail "unexpected top-camera size in $filename"
    [[ "$WRIST_WIDTH" == "640" && "$WRIST_HEIGHT" == "480" ]] || fail "unexpected wrist-camera size in $filename"
  )

  bash "$scripts_dir/init_round.sh" --config "$staged_config" --round r01 > /dev/null
  bash "$scripts_dir/record_round.sh" --config "$staged_config" --round r01 --dry-run > "$output_file"
  assert_contains "task=$expected_slug" "$manifest"
  assert_contains "task_description=$expected_description" "$manifest"
  assert_contains "$temp_root/fms688_data/datasets/$expected_slug/v001" "$output_file"
}

check_task_config \
  "office-sort.env.example" \
  "sort_office_items" \
  "Sort the specified office item into its registered category zone." \
  "7"

check_task_config \
  "office-usb-transfer.env.example" \
  "transfer_usb_a_to_preinsert" \
  "Pick up the USB-A connector from the U-shaped holder and place it in the pre-insertion cradle." \
  "5"

check_task_config \
  "office-usb-insert.env.example" \
  "insert_usb_a_unpowered" \
  "Pick up the USB-A connector from the U-shaped holder and insert it into the fixed unpowered USB-A adapter." \
  "5"

printf 'PASS: office task configs preserve independent task identities, paths, and r01 collection counts.\n'
