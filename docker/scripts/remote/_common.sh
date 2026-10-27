#!/usr/bin/env bash
set -Eeuo pipefail

REMOTE_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# scripts 位于 docker/scripts/remote/ 下：上两级 = docker/，上三级 = 仓库根
DOCKER_DIR="$(cd -- "${REMOTE_SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd -- "${DOCKER_DIR}/.." && pwd)"
REMOTE_CONFIG_FILE="${VIBEQUANT_REMOTE_CONFIG:-${DOCKER_DIR}/.env.remote}"

if [[ ! -f "${REMOTE_CONFIG_FILE}" ]]; then
  printf 'Missing remote config: %s\n' "${REMOTE_CONFIG_FILE}" >&2
  printf 'Copy .env.remote.example to .env.remote and fill in SSH metadata.\n' >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${REMOTE_CONFIG_FILE}"
set +a

: "${REMOTE_SSH_HOST:?REMOTE_SSH_HOST is required}"
: "${REMOTE_SSH_PORT:?REMOTE_SSH_PORT is required}"
: "${REMOTE_PROJECT_DIR:?REMOTE_PROJECT_DIR is required}"
: "${REMOTE_COMPOSE_PROJECT:?REMOTE_COMPOSE_PROJECT is required}"

if [[ ! "${REMOTE_SSH_HOST}" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.:-]+$ ]]; then
  printf 'Unsafe REMOTE_SSH_HOST value.\n' >&2
  exit 2
fi
if [[ ! "${REMOTE_SSH_PORT}" =~ ^[0-9]+$ ]]; then
  printf 'REMOTE_SSH_PORT must be numeric.\n' >&2
  exit 2
fi
if [[ ! "${REMOTE_PROJECT_DIR}" =~ ^/home/[A-Za-z0-9._/-]+$ ]]; then
  printf 'REMOTE_PROJECT_DIR must be an absolute path below /home.\n' >&2
  exit 2
fi
if [[ ! "${REMOTE_COMPOSE_PROJECT}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  printf 'REMOTE_COMPOSE_PROJECT contains unsupported characters.\n' >&2
  exit 2
fi

REMOTE_DOCKER_DIR="${REMOTE_PROJECT_DIR}/docker"

SSH_BASE=(
  ssh
  -p "${REMOTE_SSH_PORT}"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
)

remote_shell_quote() {
  printf '%q' "$1"
}

remote_exec() {
  "${SSH_BASE[@]}" "${REMOTE_SSH_HOST}" "$1"
}
