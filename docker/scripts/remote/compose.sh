#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

if (( $# == 0 )); then
  printf 'Usage: %s <docker compose arguments...>\n' "$0" >&2
  exit 2
fi

docker_dir_quoted="$(remote_shell_quote "${REMOTE_DOCKER_DIR}")"
project_quoted="$(remote_shell_quote "${REMOTE_COMPOSE_PROJECT}")"
remote_command="cd ${docker_dir_quoted} && docker compose --project-name ${project_quoted}"

for argument in "$@"; do
  remote_command+=" $(remote_shell_quote "${argument}")"
done

remote_exec "${remote_command}"
