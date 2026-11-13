#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/lib.sh"
config="${SO101_CONFIG:-$script_dir/fms688.env}"
if [[ "${1:-}" == --config ]]; then
  config="${2:-}"
  shift 2
fi
[[ $# -eq 0 ]] || die 'usage: interactive_collection.sh [--config FILE]'
[[ -f "$config" ]] || die "config file not found: $config"
config="$(realpath "$config")"

# An activated collector environment is needed by the existing entry points.
if ! command -v lerobot-record >/dev/null 2>&1; then
  activation="$HOME/so101-lab/activate-lerobot.sh"
  [[ -f "$activation" ]] || die "LeRobot environment not found: $activation"
  source "$activation"
fi

confirm_motion() {
  if [[ ! -t 0 ]]; then
    printf '需要交互式终端才能操作机械臂。\n'
    return 1
  fi
  printf '请确认机械臂已固定、主从臂姿态已对齐、运动范围无人和障碍、手可及时断电；跟随开始时机械臂可能立即运动。\n'
  read -r -p '输入 YES 开始，其他输入取消: ' answer || return 1
  [[ "$answer" == YES ]]
}

physical_hold_clear() {
  if [[ -e "$FMS688_DATA/PHYSICAL_SAFETY_HOLD.md" ]]; then
    printf 'PHYSICAL_SAFETY_HOLD：上次硬件故障尚待排查，未启动；详见 %s/PHYSICAL_SAFETY_HOLD.md\n' "$FMS688_DATA"
    return 1
  fi
}

while true; do
  load_config "$config"
  printf '\nSO-101 采集助手\n任务: %s | 版本: %s | 轮次: %s | 目标: %s 条\n数据: %s\n' \
    "$TASK_SLUG" "$DATASET_VERSION" "$ROUND_ID" "$EPISODES_THIS_ROUND" "$DATASET_ROOT"
  printf '1 检查环境和设备\n2 开始跟随（双相机预览，不录制）\n3 开始采集 / 继续采集（选择日期任务）\n4 检查已保存数据\n5 回放一条数据\n6 完成质量审核并关闭轮次\n7 修改完整配置文件\n8 只读关节状态检查\n9 交互校准主臂或从臂\n10 列出串口和相机端口\n11 填写本轮质量审核\n12 Hugging Face 登录与账号检查\n13 审核后上传到 Hugging Face（公开）\n14 删除当前组轨迹或生成副本\n0 退出\n'
  read -r -p '选择: ' choice || break
  case "$choice" in
    0) break ;;
    1) bash "$script_dir/preflight_collection.sh" --config "$config" || printf '预检未通过，请先处理上述问题。\n' ;;
    2)
      if physical_hold_clear && confirm_motion; then
        printf '跟随将显示顶部和腕部相机；在此终端按 Ctrl+C 结束跟随，此模式不录制。\n'
        bash "$script_dir/collect.sh" --config "$config" teleop --with-cameras --confirm-physical || printf '跟随已结束或发生错误，请检查上方信息。\n'
      fi
      ;;
    3)
      physical_hold_clear || continue
      if ! python3 "$script_dir/configure_collection.py" "$config"; then
        continue
      fi
      load_config "$config"
      if physical_hold_clear && confirm_motion; then
        if bash "$script_dir/preflight_collection.sh" --config "$config"; then
          if [[ ! -e "$ROUND_DIR/ROUND.md" && ! -e "$ROUND_DIR/SESSION.json" ]]; then
            bash "$script_dir/init_round.sh" --config "$config" --round "$ROUND_ID" || { printf '初始化失败，未开始采集。\n'; continue; }
          fi
          if ! command -v gnome-terminal >/dev/null || ! command -v script >/dev/null; then
            printf '需要图形桌面、gnome-terminal 和 script；未启动录制。\n'
            continue
          fi
          mkdir -p "$FMS688_DATA/logs"
          log_file="$FMS688_DATA/logs/record-${TASK_SLUG}-${DATASET_VERSION}-${ROUND_ID}-$(date +%Y%m%d-%H%M%S)-$$.log"
          printf '采集将在新终端运行，日志：%s\n' "$log_file"
          gnome-terminal --wait --title='SO101 采集与保存记录' -- bash "$script_dir/record_terminal.sh" "$config" "$ROUND_ID" "$log_file" || printf '采集终端异常退出，请检查日志与已保存数据。\n'
          printf '采集终端已退出；请使用菜单 4 校验数据，日志：%s\n' "$log_file"
        else
          printf '预检未通过，未开始采集。\n'
        fi
      fi
      ;;
    4) bash "$script_dir/collect.sh" --config "$config" review || printf '数据检查失败，请保留现场文件并检查错误。\n' ;;
    5)
      read -r -p '输入 episode 编号（从 0 开始）: ' episode || continue
      if [[ "$episode" =~ ^[0-9]+$ ]]; then
        bash "$script_dir/collect.sh" --config "$config" view --episode "$episode" || printf '回放失败，请检查数据和显示环境。\n'
      else
        printf '编号必须是非负整数。\n'
      fi
      ;;
    6)
      printf '请先用菜单 4 检查数据，逐条回放并填写轮次目录中的 QA.csv。\n'
      bash "$script_dir/collect.sh" --config "$config" close || printf '轮次未关闭；请检查审核结果。\n'
      ;;
    7) "${EDITOR:-nano}" "$config" || printf '未能打开编辑器。\n' ;;
    8)
      if ! physical_hold_clear; then
        :
      elif [[ ! -t 0 ]]; then
        printf '需要交互式终端才能检查机械臂。\n'
      else
        printf '本检查只读电机寄存器，不改变力矩或位置；但接通电源可能导致运动，须先排除故障并做好现场防护。\n'
        read -r -p '确认现场安全且已了解风险，输入 YES 继续: ' answer || continue
        if [[ "$answer" == YES ]]; then
          bash "$script_dir/collect.sh" --config "$config" inspect-joints --confirm-physical || printf '只读检查失败，请查看上方错误。\n'
        fi
      fi
      ;;
    9)
      printf '校准前先排除舵机故障；会备份已有校准文件，按提示人工摆放中位和行程。\n'
      read -r -p '选择主臂 1、从臂 2，其他取消: ' arm_choice || continue
      case "$arm_choice" in 1) arm=leader ;; 2) arm=follower ;; *) continue ;; esac
      bash "$script_dir/collect.sh" --config "$config" calibrate-arm --arm "$arm" --confirm-physical || printf '校准未完成，请保留备份和上方错误。\n'
      ;;
    10) bash "$script_dir/collect.sh" --config "$config" devices || printf '设备列表未能完整读取。\n' ;;
    11)
      if [[ -f "$ROUND_DIR/QA.csv" ]]; then
        printf '逐条回放后填写 item、result=pass、privacy=pass；异常轨迹不要标为 pass。\n'
        "${EDITOR:-nano}" "$ROUND_DIR/QA.csv" || printf '未能打开审核文件。\n'
      else
        printf '请先执行菜单 4 生成 QA.csv。\n'
      fi
      ;;
    12)
      if [[ ! -t 0 ]]; then
        printf '登录需要交互式终端。\n'
      elif ! command -v hf >/dev/null 2>&1; then
        printf '找不到 hf 命令，请检查 LeRobot 环境。\n'
      else
        hf auth whoami || printf '尚未登录或账号检查失败。\n'
        read -r -p '需要登录或切换账号请输入 LOGIN，其他返回: ' answer || continue
        if [[ "$answer" == LOGIN ]]; then
          hf auth login && hf auth whoami || printf '登录或账号检查失败，请查看提示。\n'
        fi
      fi
      ;;
    13)
      if [[ ! -t 0 ]]; then
        printf '公开上传需要交互式终端。\n'
      else
        printf '将公开上传当前任务：%s，版本：%s，轮次：%s\n仓库：%s\n' "$TASK_SLUG" "$DATASET_VERSION" "$ROUND_ID" "$DATASET_ID"
        printf '请先完成菜单 4、5、11、6 的数据检查、逐条回放、质量与隐私审核和关组。\n'
        read -r -p '确认公开上传，输入 PUBLIC，其他取消: ' answer || continue
        if [[ "$answer" == PUBLIC ]]; then
          bash "$script_dir/collect.sh" --config "$config" upload --confirm-public || printf '未确认上传成功；请查看上方原因。\n'
        else
          printf '已取消上传。\n'
        fi
      fi
      ;;
    14) python3 "$script_dir/filter_episode.py" || printf '未生成完整副本，请检查上方信息。\n' ;;
    *) printf '无效选择。\n' ;;
  esac
done
