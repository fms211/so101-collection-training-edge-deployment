#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
scripts_dir="$repo_root/scripts/lerobot"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT

config_file="$temp_root/fms688.env"
cat > "$config_file" <<EOF
FMS688_DATA="$temp_root/fms688_data"
DATASET_NAMESPACE="fms688"
TASK_SLUG="sort_office_items"
TASK_DESCRIPTION="Sort the specified office item into its registered category zone."
DATASET_VERSION="v001"
ROUND_ID="r01"
EPISODES_THIS_ROUND="5"
EPISODE_MAX_TIME_S="300"
RESET_MAX_TIME_S="120"
FPS="30"
FOLLOWER_PORT="/dev/ttyACM0"
LEADER_PORT="/dev/ttyACM1"
FOLLOWER_ID="so101_follower_rack_01"
LEADER_ID="so101_leader_rack_01"
TOP_CAMERA="/dev/video0"
TOP_FOURCC="MJPG"
WRIST_CAMERA="/dev/video1"
WRIST_FOURCC="MJPG"
TOP_WIDTH="640"
TOP_HEIGHT="480"
WRIST_WIDTH="640"
WRIST_HEIGHT="480"
NUM_WORKERS="4"
SAVE_FREQ="20000"
EVAL_STEPS="0"
EOF

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

missing_description_config="$temp_root/missing-description.env"
grep -v '^TASK_DESCRIPTION=' "$config_file" > "$missing_description_config"
if bash "$scripts_dir/init_round.sh" --config "$missing_description_config" --round r90 > "$temp_root/missing-description.out" 2>&1; then
  fail 'config without TASK_DESCRIPTION must be rejected'
fi
assert_contains 'ERROR: missing required config value: TASK_DESCRIPTION' "$temp_root/missing-description.out"

multiline_description_config="$temp_root/multiline-description.env"
while IFS= read -r line; do
  if [[ "$line" == TASK_DESCRIPTION=* ]]; then
    printf 'TASK_DESCRIPTION="Line one\nLine two"\n'
  else
    printf '%s\n' "$line"
  fi
done < "$config_file" > "$multiline_description_config"
if bash "$scripts_dir/init_round.sh" --config "$multiline_description_config" --round r91 > "$temp_root/multiline-description.out" 2>&1; then
  fail 'multiline TASK_DESCRIPTION must be rejected'
fi
assert_contains 'ERROR: TASK_DESCRIPTION must be a single line' "$temp_root/multiline-description.out"

whitespace_description_config="$temp_root/whitespace-description.env"
while IFS= read -r line; do
  if [[ "$line" == TASK_DESCRIPTION=* ]]; then
    printf 'TASK_DESCRIPTION="   "\n'
  else
    printf '%s\n' "$line"
  fi
done < "$config_file" > "$whitespace_description_config"
if bash "$scripts_dir/init_round.sh" --config "$whitespace_description_config" --round r92 > "$temp_root/whitespace-description.out" 2>&1; then
  fail 'whitespace-only TASK_DESCRIPTION must be rejected'
fi
assert_contains 'ERROR: TASK_DESCRIPTION must contain a non-whitespace character' "$temp_root/whitespace-description.out"

bash "$scripts_dir/init_round.sh" --config "$config_file" --round r01
round_one="$temp_root/fms688_data/rounds/sort_office_items/v001/r01/ROUND.md"
assert_file "$round_one"
assert_contains 'round=r01' "$round_one"
assert_contains 'task=sort_office_items' "$round_one"
assert_contains 'resume=false' "$round_one"
assert_contains 'task_description=Sort the specified office item into its registered category zone.' "$round_one"
assert_contains 'version=v001' "$round_one"
assert_contains 'dataset_id=fms688/so101_sort_office_items_v001' "$round_one"
assert_contains "dataset_root=$temp_root/fms688_data/datasets/sort_office_items/v001" "$round_one"

drifted_description_config="$temp_root/drifted-description.env"
sed 's/^TASK_DESCRIPTION=.*/TASK_DESCRIPTION="Changed after manifest creation."/' "$config_file" > "$drifted_description_config"
if bash "$scripts_dir/record_round.sh" --config "$drifted_description_config" --round r01 --dry-run > "$temp_root/drifted-description.out" 2>&1; then
  fail 'recording must reject a task description that differs from ROUND.md'
fi
assert_contains 'ERROR: round manifest task_description mismatch' "$temp_root/drifted-description.out"

bash "$scripts_dir/record_round.sh" --config "$config_file" --round r01 --dry-run > "$temp_root/r01.out"
assert_contains '--dataset.root=' "$temp_root/r01.out"
assert_contains "$temp_root/fms688_data/datasets/sort_office_items/v001" "$temp_root/r01.out"
assert_contains 'Keyboard controls: n=next phase; r=discard and re-record; q=quit (may save the current buffer; not an emergency stop).' "$temp_root/r01.out"
assert_contains '--dataset.episode_time_s=300' "$temp_root/r01.out"
assert_contains '--dataset.single_task=Sort\ the\ specified\ office\ item\ into\ its\ registered\ category\ zone.' "$temp_root/r01.out"
assert_contains 'fourcc:\ \"MJPG\"' "$temp_root/r01.out"
assert_contains '--robot.max_relative_target=1.0' "$temp_root/r01.out"

limited_config="$temp_root/limited.env"
sed 's/^FPS=.*/FPS="30"\nMAX_RELATIVE_TARGET="0.5"/' "$config_file" > "$limited_config"
bash "$scripts_dir/record_round.sh" --config "$limited_config" --round r01 --dry-run > "$temp_root/limited.out"
assert_contains '--robot.max_relative_target=0.5' "$temp_root/limited.out"

if grep -F -- 'Move the blue cube to the registered target area.' "$temp_root/r01.out" >/dev/null; then
  fail 'record dry-run must not use the hard-coded blue-cube task description'
fi

quarantine_marker="$temp_root/fms688_data/rounds/sort_office_items/v001/DATASET_QUARANTINED.md"
printf 'status=quarantined\n' > "$quarantine_marker"
if bash "$scripts_dir/init_round.sh" --config "$config_file" --round r03 > "$temp_root/quarantined-init.out" 2>&1; then
  fail 'round initialization must reject a quarantined dataset version'
fi
assert_contains 'ERROR: dataset version is quarantined' "$temp_root/quarantined-init.out"
[[ ! -e "$temp_root/fms688_data/rounds/sort_office_items/v001/r03/ROUND.md" ]] || fail 'quarantined init must not create a round manifest'
if bash "$scripts_dir/record_round.sh" --config "$config_file" --round r01 --dry-run > "$temp_root/quarantined-record.out" 2>&1; then
  fail 'recording must reject a quarantined dataset version'
fi
assert_contains 'ERROR: dataset version is quarantined' "$temp_root/quarantined-record.out"
bash "$scripts_dir/inspect_dataset.sh" --config "$config_file" > "$temp_root/quarantined-inspect.out"
assert_contains 'DATASET_QUARANTINE=present' "$temp_root/quarantined-inspect.out"
rm -f "$quarantine_marker"
if grep -F -- '--resume=true' "$temp_root/r01.out" >/dev/null; then
  fail 'r01 dry-run must not append resume=true'
fi

# Simulate a finalized, reviewed first round for the shell-only continuation test.
python3 - "$temp_root/fms688_data" <<'PY'
import json, pathlib, sys
base = pathlib.Path(sys.argv[1])
root = base/'datasets/sort_office_items/v001/meta'
root.mkdir(parents=True)
(root/'info.json').write_text(json.dumps({'total_episodes': 5}))
path = base/'rounds/sort_office_items/v001/r01/SESSION.json'
state = json.loads(path.read_text())
state['status'] = 'closed'
path.write_text(json.dumps(state))
PY
bash "$scripts_dir/init_round.sh" --config "$config_file" --round r02
round_two="$temp_root/fms688_data/rounds/sort_office_items/v001/r02/ROUND.md"
assert_file "$round_two"
assert_contains 'round=r02' "$round_two"
assert_contains 'resume=true' "$round_two"

bash "$scripts_dir/record_round.sh" --config "$config_file" --round r02 --dry-run > "$temp_root/r02.out"
assert_contains '--resume=true' "$temp_root/r02.out"
assert_contains "$temp_root/fms688_data/datasets/sort_office_items/v001" "$temp_root/r02.out"

bash "$scripts_dir/inspect_dataset.sh" --config "$config_file" > "$temp_root/inspect.out"
assert_contains 'TRAIN_DATASET_ROOT=' "$temp_root/inspect.out"
assert_contains "$temp_root/fms688_data/datasets/sort_office_items/v001" "$temp_root/inspect.out"
assert_contains 'DATASET_QUARANTINE=absent' "$temp_root/inspect.out"

bash "$scripts_dir/train_act.sh" --config "$config_file" --mode single --dry-run > "$temp_root/train.out"
assert_contains 'lerobot-train' "$temp_root/train.out"
assert_contains '--dataset.root=' "$temp_root/train.out"
assert_contains "$temp_root/fms688_data/runs/act/sort_office_items/v001" "$temp_root/train.out"

mkdir -p "$temp_root/fms688_data/rounds/sort_office_items/v001"
printf 'status=sealed\ndataset_id=fms688/so101_sort_office_items_v001\n' > "$temp_root/fms688_data/rounds/sort_office_items/v001/DATASET_SEALED.md"
bash "$scripts_dir/train_act.sh" --config "$config_file" --mode four-gpu --profile formal --dry-run > "$temp_root/four_gpu.out"
assert_contains 'accelerate' "$temp_root/four_gpu.out"
assert_contains '--num_processes=4' "$temp_root/four_gpu.out"
assert_contains "$temp_root/fms688_data/datasets/sort_office_items/v001" "$temp_root/four_gpu.out"

run_id='act_sort_office_items_v001_single_gpu_v001'
checkpoint_dir="$temp_root/fms688_data/runs/act/sort_office_items/v001/$run_id/checkpoints/last/pretrained_model"
mkdir -p "$checkpoint_dir"
touch "$checkpoint_dir/train_config.json"
printf 'policy=act\ntask=sort_office_items\nversion=v001\n' > "${checkpoint_dir%/checkpoints/last/pretrained_model}/RUN_CONTEXT.txt"
bash "$scripts_dir/resume_train.sh" --config "$config_file" --run-id "$run_id" --dry-run > "$temp_root/resume.out"
assert_contains '--resume=true' "$temp_root/resume.out"
assert_contains "$checkpoint_dir/train_config.json" "$temp_root/resume.out"

printf 'PASS: reusable LeRobot scripts preserve one master dataset across r01/r02 and train from it.\n'
