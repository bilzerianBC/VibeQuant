#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
script="${REMOTE_DOCKER_DIR}/scripts/host/dipwatch-update.sh"
log="${REMOTE_DOCKER_DIR}/logs/dipwatch.log"
line="*/30 * * * * REMOTE_COMPOSE_PROJECT=${REMOTE_COMPOSE_PROJECT} /bin/bash ${script} >> ${log} 2>&1 # vibequant-dipwatch"
remote_exec "mkdir -p $(remote_shell_quote "${REMOTE_DOCKER_DIR}/logs") && { crontab -l 2>/dev/null | sed '/# vibequant-dipwatch$/d'; printf '%s\\n' $(remote_shell_quote "${line}"); } | crontab -"
printf 'Installed twice-hourly DipWatch job. Logs: %s\n' "${log}"
