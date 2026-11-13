#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
scripts_dir="$repo_root/scripts/lerobot"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local expected="$1"
  local file="$2"
  grep -F -- "$expected" "$file" >/dev/null || fail "missing [$expected] in $file"
}

assert_not_contains() {
  local unexpected="$1"
  local file="$2"
  if grep -F -- "$unexpected" "$file" >/dev/null; then
    fail "unexpected [$unexpected] in $file"
  fi
}

assert_fails_with() {
  local expected="$1"
  local output_file="$2"
  shift 2
  if "$@" >"$output_file" 2>&1; then
    fail "command unexpectedly succeeded: $*"
  fi
  assert_contains "$expected" "$output_file"
}

config_file="$temp_root/fms688.env"
cat >"$config_file" <<EOF
FMS688_DATA="$temp_root/fms688_data"
DATASET_NAMESPACE="fms688"
TASK_SLUG="move_blue_cube"
TASK_DESCRIPTION="Move the blue cube to the registered target area."
DATASET_VERSION="v001"
ROUND_ID="r01"
EPISODES_THIS_ROUND="5"
EPISODE_MAX_TIME_S="300"
RESET_MAX_TIME_S="120"
FPS="30"
FOLLOWER_PORT="/dev/ttyACM0"
LEADER_PORT="/dev/ttyACM1"
FOLLOWER_ID="so101_follower_laptop_01"
LEADER_ID="so101_leader_laptop_01"
TOP_CAMERA="/dev/video0"
WRIST_CAMERA="/dev/video1"
TOP_WIDTH="640"
TOP_HEIGHT="480"
WRIST_WIDTH="640"
WRIST_HEIGHT="480"
NUM_WORKERS="4"
SAVE_FREQ="20000"
EVAL_STEPS="0"
EOF

dataset_root="$temp_root/fms688_data/datasets/move_blue_cube/v001"
round_root="$temp_root/fms688_data/rounds/move_blue_cube/v001"
bash "$scripts_dir/init_round.sh" --config "$config_file" --round r01 > /dev/null
mkdir -p "$dataset_root/meta" "$dataset_root/data/chunk-000"
printf '{"codebase_version":"v3.0","robot_type":"so101_follower","total_episodes":5}\n' >"$dataset_root/meta/info.json"
printf 'parquet-placeholder\n' >"$dataset_root/data/chunk-000/episode_000000.parquet"
printf 'quality=fail\nstatus=closed\n' >>"$round_root/r01/ROUND.md"

fake_bin="$temp_root/fake-bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_SSH_LOG"
if [[ "${FAKE_SSH_FAIL:-false}" == "true" ]]; then
  exit 255
fi
joined="$*"
if [[ "$joined" == *"__FMS688_REMOTE_HOME__"* ]]; then
  printf '__FMS688_REMOTE_HOME__=/home/server\n'
elif [[ "$joined" == *"__FMS688_SEAL_STATE__"* ]]; then
  printf '__FMS688_SEAL_STATE__=%s\n' "${FAKE_REMOTE_SEALED:-absent}"
elif [[ "$joined" == *"__FMS688_VERIFY__"* ]]; then
  printf 'DATASET_FILES=%s\n' "$FAKE_REMOTE_DATASET_FILES"
  printf 'DATASET_BYTES=%s\n' "$FAKE_REMOTE_DATASET_BYTES"
  printf 'ROUND_FILES=%s\n' "$FAKE_REMOTE_ROUND_FILES"
  printf 'ROUND_BYTES=%s\n' "$FAKE_REMOTE_ROUND_BYTES"
  printf 'META_OK=%s\n' "${FAKE_REMOTE_META_OK:-1}"
fi
EOF
cat >"$fake_bin/rsync" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_RSYNC_LOG"
if [[ "${FAKE_RSYNC_FAIL:-false}" == "true" ]]; then
  exit 23
fi
EOF
chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

export PATH="$fake_bin:$PATH"
export SSH_BIN="$fake_bin/ssh"
export RSYNC_BIN="$fake_bin/rsync"
export FAKE_SSH_LOG="$temp_root/ssh.log"
export FAKE_RSYNC_LOG="$temp_root/rsync.log"

assert_fails_with 'latest quality must be pass' "$temp_root/quality_fail.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --dry-run

printf 'quality=pass\nstatus=closed\n' >>"$round_root/r01/ROUND.md"
printf 'quality=fail\n' >>"$round_root/r01/ROUND.md"
assert_fails_with 'latest quality must be pass' "$temp_root/latest_quality_fail.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --dry-run
printf 'quality=pass\nstatus=closed\n' >>"$round_root/r01/ROUND.md"

drifted_description_config="$temp_root/drifted-description.env"
sed 's/^TASK_DESCRIPTION=.*/TASK_DESCRIPTION="Changed after collection."/' "$config_file" > "$drifted_description_config"
rm -f "$FAKE_SSH_LOG" "$FAKE_RSYNC_LOG"
assert_fails_with 'round manifest task_description mismatch' "$temp_root/sync_description_drift.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$drifted_description_config" \
    --server so101-train \
    --round r01 \
    --dry-run
[[ ! -e "$FAKE_SSH_LOG" ]] || fail 'identity failure must not contact SSH server'
[[ ! -e "$FAKE_RSYNC_LOG" ]] || fail 'identity failure must not start rsync'

bash "$scripts_dir/sync_dataset_to_server.sh" \
  --config "$config_file" \
  --server so101-train \
  --round r01 \
  --dry-run >"$temp_root/dry_run.out"
assert_contains 'Remote dataset: so101-train:~/fms688_data/datasets/move_blue_cube/v001/' "$temp_root/dry_run.out"
assert_contains 'Dry-run only' "$temp_root/dry_run.out"
[[ ! -e "$FAKE_SSH_LOG" ]] || fail 'dry-run must not contact SSH server'
[[ ! -e "$FAKE_RSYNC_LOG" ]] || fail 'dry-run must not start rsync'
assert_not_contains '--delete' "$temp_root/dry_run.out"
assert_not_contains '/runs/' "$temp_root/dry_run.out"
assert_not_contains '/cache/' "$temp_root/dry_run.out"
assert_not_contains '/calibrations/' "$temp_root/dry_run.out"

assert_fails_with 'safe SSH alias' "$temp_root/bad_server.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server 'bad;server' \
    --round r01 \
    --dry-run

bad_config="$temp_root/bad.env"
sed 's/TASK_SLUG="move_blue_cube"/TASK_SLUG="..\/escape"/' "$config_file" >"$bad_config"
assert_fails_with 'TASK_SLUG' "$temp_root/bad_path.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$bad_config" \
    --server so101-train \
    --round r01 \
    --dry-run

dataset_files="$(find "$dataset_root" -type f | wc -l | tr -d ' ')"
dataset_bytes="$(find "$dataset_root" -type f -printf '%s\n' | awk '{sum += $1} END {print sum + 0}')"
round_files="$(find "$round_root/r01" -type f | wc -l | tr -d ' ')"
round_bytes="$(find "$round_root/r01" -type f -printf '%s\n' | awk '{sum += $1} END {print sum + 0}')"
export FAKE_REMOTE_DATASET_FILES="$dataset_files"
export FAKE_REMOTE_DATASET_BYTES="$dataset_bytes"
export FAKE_REMOTE_ROUND_FILES="$round_files"
export FAKE_REMOTE_ROUND_BYTES="$round_bytes"
export FAKE_REMOTE_META_OK=1

bash "$scripts_dir/sync_dataset_to_server.sh" \
  --config "$config_file" \
  --server so101-train \
  --round r01 \
  --confirm-sync >"$temp_root/success.out"
assert_contains 'SYNC VERIFIED' "$temp_root/success.out"
assert_contains "$dataset_root/" "$FAKE_RSYNC_LOG"
assert_contains "$round_root/r01/" "$FAKE_RSYNC_LOG"
assert_contains 'so101-train:/home/server/fms688_data/datasets/move_blue_cube/v001/' "$FAKE_RSYNC_LOG"
assert_not_contains '--delete' "$FAKE_RSYNC_LOG"
assert_not_contains '/runs/' "$FAKE_RSYNC_LOG"
assert_not_contains '/cache/' "$FAKE_RSYNC_LOG"
assert_not_contains '/calibrations/' "$FAKE_RSYNC_LOG"

rm -f "$FAKE_SSH_LOG" "$FAKE_RSYNC_LOG"
export FAKE_SSH_FAIL=true
assert_fails_with 'SSH connection failed' "$temp_root/ssh_fail.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --confirm-sync
unset FAKE_SSH_FAIL

rm -f "$FAKE_SSH_LOG" "$FAKE_RSYNC_LOG"
export FAKE_REMOTE_SEALED=sealed
assert_fails_with 'server dataset version is sealed' "$temp_root/sealed_remote.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --confirm-sync
unset FAKE_REMOTE_SEALED

rm -f "$FAKE_SSH_LOG" "$FAKE_RSYNC_LOG"
export FAKE_RSYNC_FAIL=true
assert_fails_with 'rsync failed' "$temp_root/rsync_fail.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --confirm-sync
unset FAKE_RSYNC_FAIL

rm -f "$FAKE_SSH_LOG" "$FAKE_RSYNC_LOG"
export FAKE_REMOTE_DATASET_FILES="$((dataset_files + 1))"
assert_fails_with 'verification mismatch' "$temp_root/mismatch.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r01 \
    --confirm-sync
export FAKE_REMOTE_DATASET_FILES="$dataset_files"

python3 - "$round_root/r01/SESSION.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
s = json.loads(p.read_text())
s['status'] = 'closed'
p.write_text(json.dumps(s))
PY
bash "$scripts_dir/init_round.sh" --config "$config_file" --round r02 > /dev/null
printf 'quality=pass\nstatus=closed\n' >>"$round_root/r02/ROUND.md"
bash "$scripts_dir/sync_dataset_to_server.sh" \
  --config "$config_file" \
  --server so101-train \
  --round r02 \
  --dry-run >"$temp_root/r02.out"
assert_contains 'Remote dataset: so101-train:~/fms688_data/datasets/move_blue_cube/v001/' "$temp_root/r02.out"
assert_contains 'Remote round: so101-train:~/fms688_data/rounds/move_blue_cube/v001/r02/' "$temp_root/r02.out"

quarantine_marker="$round_root/DATASET_QUARANTINED.md"
printf 'status=quarantined\n' > "$quarantine_marker"
assert_fails_with 'dataset version is quarantined' "$temp_root/quarantined_sync.out" \
  bash "$scripts_dir/sync_dataset_to_server.sh" \
    --config "$config_file" \
    --server so101-train \
    --round r02 \
    --dry-run
assert_fails_with 'dataset version is quarantined' "$temp_root/quarantined_seal.out" \
  bash "$scripts_dir/seal_dataset_version.sh" \
    --config "$config_file" \
    --dry-run
rm -f "$quarantine_marker"

assert_fails_with 'round manifest task_description mismatch' "$temp_root/seal_description_drift.out" \
  bash "$scripts_dir/seal_dataset_version.sh" \
    --config "$drifted_description_config" \
    --dry-run

bash "$scripts_dir/seal_dataset_version.sh" \
  --config "$config_file" \
  --dry-run >"$temp_root/seal_dry.out"
assert_contains 'DATASET_SEALED.md' "$temp_root/seal_dry.out"
bash "$scripts_dir/seal_dataset_version.sh" \
  --config "$config_file" \
  --confirm-seal >"$temp_root/seal.out"
seal_file="$round_root/DATASET_SEALED.md"
[[ -f "$seal_file" ]] || fail "seal file not created: $seal_file"
assert_contains 'dataset_id=fms688/so101_move_blue_cube_v001' "$seal_file"
assert_contains 'status=sealed' "$seal_file"

printf 'status=quarantined\n' > "$quarantine_marker"
assert_fails_with 'dataset version is quarantined' "$temp_root/quarantined_unseal.out" \
  bash "$scripts_dir/seal_dataset_version.sh" \
    --config "$config_file" \
    --confirm-unseal
[[ -f "$seal_file" ]] || fail 'quarantined unseal must preserve the seal file'
rm -f "$quarantine_marker"

bash "$scripts_dir/seal_dataset_version.sh" \
  --config "$config_file" \
  --confirm-unseal >"$temp_root/unseal.out"
[[ ! -e "$seal_file" ]] || fail "seal file not removed: $seal_file"

# A copied ROUND.md retains the collector's absolute dataset_root. Sealing the
# verified server copy must accept that source path without accepting another task.
server_data="$temp_root/server/fms688_data"
server_config="$temp_root/server.env"
mkdir -p "$server_data/datasets/move_blue_cube" "$server_data/rounds/move_blue_cube"
cp -a "$dataset_root" "$server_data/datasets/move_blue_cube/v001"
cp -a "$round_root" "$server_data/rounds/move_blue_cube/v001"
sed "s@^FMS688_DATA=.*@FMS688_DATA=\"$server_data\"@" "$config_file" > "$server_config"
server_manifest="$server_data/rounds/move_blue_cube/v001/r01/ROUND.md"
sed -i 's@^dataset_root=.*@dataset_root=/tmp/unrelated/datasets/other_task/v001@' "$server_manifest"
assert_fails_with 'round manifest dataset_root mismatch' "$temp_root/server_bad_source.out" \
  bash "$scripts_dir/seal_dataset_version.sh" --config "$server_config" --dry-run
sed -i "s@^dataset_root=.*@dataset_root=$dataset_root@" "$server_manifest"
bash "$scripts_dir/seal_dataset_version.sh" --config "$server_config" --confirm-seal > "$temp_root/server_seal.out"
assert_contains 'status=sealed' "$server_data/rounds/move_blue_cube/v001/DATASET_SEALED.md"

printf 'PASS: laptop collection sync is gated by round QA, verifies the server copy, and seals formal training input.\n'
