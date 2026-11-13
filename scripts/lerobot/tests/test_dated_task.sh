#!/usr/bin/env bash
set -euo pipefail
scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
config="$tmp/config.env"
sed -e "s|FMS688_DATA=\"\$HOME/fms688_data\"|FMS688_DATA=\"$tmp/data\"|" \
    -e 's/TASK_SLUG="move_blue_cube"/TASK_SLUG="pick_to_container"/' \
    -e 's/DATASET_VERSION="v001"/DATASET_VERSION="20261111_pick_to_container"/' \
    -e 's/EPISODES_THIS_ROUND="5"/EPISODES_THIS_ROUND="40"/' \
    "$scripts_dir/fms688.env.example" > "$config"
bash "$scripts_dir/init_round.sh" --config "$config" --round r01 > "$tmp/init.out"
bash "$scripts_dir/record_round.sh" --config "$config" --round r01 --dry-run > "$tmp/record.out"
grep -F "datasets/pick_to_container/20261111_pick_to_container" "$tmp/record.out" >/dev/null
grep -F 'fms688/so101_20261111_pick_to_container' "$tmp/record.out" >/dev/null
grep -F 'dataset.num_episodes=40' "$tmp/record.out" >/dev/null
[[ ! -e "$tmp/data/datasets/pick_to_container/20261111_pick_to_container" ]]
mkdir -p "$tmp/data/datasets/pick_to_container/20261111_pick_to_container/meta"
printf '{}\n' > "$tmp/data/datasets/pick_to_container/20261111_pick_to_container/meta/info.json"
printf 'quality=pass\nstatus=closed\n' >> "$tmp/data/rounds/pick_to_container/20261111_pick_to_container/r01/ROUND.md"
bash "$scripts_dir/sync_dataset_to_server.sh" --config "$config" --server test-server --round r01 --dry-run > "$tmp/sync.out"
grep -F '~/fms688_data/datasets/pick_to_container/20261111_pick_to_container/' "$tmp/sync.out" >/dev/null
bash "$scripts_dir/seal_dataset_version.sh" --config "$config" --dry-run > "$tmp/seal.out"
grep -F 'Qualified rounds: 1' "$tmp/seal.out" >/dev/null
printf 'PASS: dated task manifest and record preview\n'
