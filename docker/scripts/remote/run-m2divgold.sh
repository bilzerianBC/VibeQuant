#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/sync.sh"
"${SCRIPT_DIR}/compose.sh" run --rm m2divgold

printf 'M2/黄金数据已写入远端卷 %s_vibequant-data。用 pull-data.sh 拉回本机。\n' "${REMOTE_COMPOSE_PROJECT:-vibequant}"
