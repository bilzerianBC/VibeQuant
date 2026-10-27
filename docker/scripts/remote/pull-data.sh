#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

IMAGE="${VIBEQUANT_IMAGE:-vibequant:dev}"
OUT_DIR="${REPO_ROOT}/docker/out"
mkdir -p "${OUT_DIR}"

vol_prefix="${REMOTE_COMPOSE_PROJECT}_"

pull_volume() {
  local volume="$1" outfile="$2"
  printf '拉取 %s%s -> %s\n' "${vol_prefix}" "${volume}" "${outfile}"
  remote_exec "docker run --rm -v '${vol_prefix}${volume}:/d:ro' '${IMAGE}' tar -C /d -cf - ." > "${outfile}"
}

pull_volume "vibequant-data" "${OUT_DIR}/m2divgold-data.tar"

printf '完成。解包示例: tar -xf %s/m2divgold-data.tar -C 目标目录\n' "${OUT_DIR}"
