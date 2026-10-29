#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
docker_dir_quoted="$(remote_shell_quote "${REMOTE_DOCKER_DIR}")"
# Existing node config and env are never overwritten. Never print their contents.
remote_exec "cd ${docker_dir_quoted} && umask 077 && mkdir -p mihomo/runtime && { test -e mihomo/config.yaml || cp mihomo/config.example.yaml mihomo/config.yaml; } && { test -e .env.dipwatch || cp .env.dipwatch.example .env.dipwatch; } && chmod 600 mihomo/config.yaml .env.dipwatch && chmod 700 mihomo/runtime"
printf 'Prepared project-local Mihomo config and runtime directory; existing configuration preserved.\n'
