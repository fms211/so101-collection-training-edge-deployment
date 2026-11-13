#!/usr/bin/env bash
set -u
[[ $# -eq 3 && -t 0 ]] || { printf '需要交互终端及配置、轮次、日志路径。\n' >&2; exit 1; }
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config="$1"; round="$2"; log_file="$3"
printf '本窗口用于 HOLD 初始化和查看录制日志。\n随后在新弹出的控制窗口输入 s/n/r/q 并按回车。\n复位阶段仍会跟随；q 不是急停，异常立即断电。\n日志：%s\n' "$log_file"
printf -v command 'bash %q --config %q --round %q --confirm-physical' "$script_dir/record_round.sh" "$config" "$round"
script -q -f -e -c "$command" "$log_file"
status=$?
printf '\n录制进程退出码：%s。请回主菜单选择 4 校验已保存数据。\n日志：%s\n' "$status" "$log_file"
read -r -p '按回车关闭本窗口: ' _ || true
exit "$status"
