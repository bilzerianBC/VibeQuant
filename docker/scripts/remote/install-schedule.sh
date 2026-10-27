#!/usr/bin/env bash
set -Eeuo pipefail
# 安装宿主机上的每日定时任务（cron）：每天 08:00 拉数据 + 出图。
# 在 Mac 上跑一次即可，幂等（重复跑会覆盖旧规则，不会重复添加）。

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

"${SCRIPT_DIR}/sync.sh"

docker_dir_quoted="$(remote_shell_quote "${REMOTE_DOCKER_DIR}")"
update_script="${REMOTE_DOCKER_DIR}/scripts/host/daily-update.sh"
update_script_quoted="$(remote_shell_quote "${update_script}")"
log_file="${REMOTE_DOCKER_DIR}/logs/daily.log"
log_file_quoted="$(remote_shell_quote "${log_file}")"

# 可执行权限 + 日志目录
remote_exec "chmod +x ${update_script_quoted} && mkdir -p $(remote_shell_quote "${REMOTE_DOCKER_DIR}/logs")"

# cron 规则：每天 08:00（宿主机本地时间）
cron_line="0 8 * * * ${update_script} >> ${log_file} 2>&1"
cron_line_quoted="$(remote_shell_quote "${cron_line}")"

# 幂等写入：删掉旧的 daily-update.sh 行，再追加新行
remote_exec "( crontab -l 2>/dev/null | grep -v 'daily-update.sh' || true ; echo ${cron_line_quoted} ) | crontab -"

printf '已安装定时任务。当前 crontab：\n'
remote_exec "crontab -l"
printf '\n注意：cron 按宿主机本地时间触发。若 08:00 不是 Asia/Shanghai 的 8 点，先用 timedatectl 核对时区。\n'
