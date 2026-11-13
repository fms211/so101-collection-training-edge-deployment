#!/usr/bin/env bash
set -euo pipefail
scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT
config="$temp_root/config.env"
sed "s|FMS688_DATA=\"\$HOME/fms688_data\"|FMS688_DATA=\"$temp_root/data\"|" "$scripts_dir/fms688.env.example" > "$config"

output="$(printf '0\n' | bash "$scripts_dir/interactive_collection.sh" --config "$config")"
[[ "$output" == *'SO-101 采集助手'* && "$output" == *'开始跟随'* && "$output" == *'开始采集'* ]] || { printf 'menu missing\n' >&2; exit 1; }
[[ ! -e "$temp_root/data" ]] || { printf 'exit must not create data\n' >&2; exit 1; }

output="$(printf '2\n0\n' | bash "$scripts_dir/interactive_collection.sh" --config "$config" 2>&1)"
[[ "$output" == *'需要交互式终端'* ]] || { printf 'non-TTY teleoperation must be rejected\n' >&2; exit 1; }
output="$(printf '3\n0\n' | bash "$scripts_dir/interactive_collection.sh" --config "$config" 2>&1)"
[[ "$output" == *'需要交互式终端'* ]] || { printf 'non-TTY recording must be rejected\n' >&2; exit 1; }
output="$(printf '8\n0\n' | bash "$scripts_dir/interactive_collection.sh" --config "$config" 2>&1)"
[[ "$output" == *'需要交互式终端'* ]] || { printf 'non-TTY servo inspection must be rejected\n' >&2; exit 1; }
[[ ! -e "$temp_root/data" ]] || { printf 'rejected operation must not create data\n' >&2; exit 1; }
mkdir -p "$temp_root/data"
printf 'incident\n' > "$temp_root/data/PHYSICAL_SAFETY_HOLD.md"
printf '3\n0\n' | script -q -e -c "bash '$scripts_dir/interactive_collection.sh' --config '$config'" /dev/null > "$temp_root/hold.out"
grep -F 'PHYSICAL_SAFETY_HOLD' "$temp_root/hold.out" >/dev/null || { printf 'menu did not report active safety hold\n' >&2; exit 1; }
[[ ! -d "$temp_root/data/rounds" ]] || { printf 'safety hold must not create rounds\n' >&2; exit 1; }
printf 'PASS: interactive menu exits safely and rejects non-TTY motion\n'
