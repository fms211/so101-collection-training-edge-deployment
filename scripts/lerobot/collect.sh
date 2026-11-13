#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/lib.sh"
config_file="${SO101_CONFIG:-${script_dir}/fms688.env}"
if [[ "${1:-}" == --config ]]; then
  config_file="$2"
  shift 2
fi
load_config "$config_file"
case "${1:-help}" in
  help|--help|-h) exec python3 "${script_dir}/collection.py" --help ;;
  init) shift; exec bash "${script_dir}/init_round.sh" --config "$config_file" "$@" ;;
  record) shift; exec bash "${script_dir}/record_round.sh" --config "$config_file" "$@" ;;
  preflight) exec bash "${script_dir}/preflight_collection.sh" --config "$config_file" ;;
  *) exec python3 "${script_dir}/collection.py" "$@" ;;
esac
