#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/sync.sh"
"${SCRIPT_DIR}/compose.sh" build

printf 'Ubuntu Docker image is ready.\n'
