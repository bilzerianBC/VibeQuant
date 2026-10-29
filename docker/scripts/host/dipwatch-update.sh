#!/usr/bin/env bash
set -Eeuo pipefail
DOCKER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${DOCKER_DIR}"
docker compose --project-name "${REMOTE_COMPOSE_PROJECT:-vibequant}" --profile dipwatch up -d mihomo
# Keep the last job container for exit-status inspection. Do not delete old containers.
docker compose --project-name "${REMOTE_COMPOSE_PROJECT:-vibequant}" run --name "vibequant-dipwatch-$(date -u +%Y%m%dT%H%M%SZ)" usstock-dip-watch
