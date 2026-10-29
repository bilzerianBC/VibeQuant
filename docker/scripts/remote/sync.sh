#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

remote_dir_quoted="$(remote_shell_quote "${REMOTE_PROJECT_DIR}")"
remote_exec "mkdir -p -- ${remote_dir_quoted}"

RSYNC_SSH="ssh -p ${REMOTE_SSH_PORT} -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=6 -o StrictHostKeyChecking=accept-new"

rsync \
  --archive \
  --compress \
  --itemize-changes \
  --exclude-from="${DOCKER_DIR}/.remoteignore" \
  --rsh="${RSYNC_SSH}" \
  "${REPO_ROOT}/" \
  "${REMOTE_SSH_HOST}:${REMOTE_PROJECT_DIR}/"

printf 'Source synchronized to %s:%s (no remote deletion performed).\n' \
  "${REMOTE_SSH_HOST}" "${REMOTE_PROJECT_DIR}"
