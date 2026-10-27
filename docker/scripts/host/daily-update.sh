#!/usr/bin/env bash
set -Eeuo pipefail
# 宿主机上的每日更新：拉最新 M2/金价 → 重新出图 → 写进站点卷。
# 由 cron 每天 08:00 调用（安装见 docker/scripts/remote/install-schedule.sh）。
# 只新建一次性容器跑完即删，不重启任何常驻服务，网页全程在线。

DOCKER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${DOCKER_DIR}"

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') 开始每日更新 ====="

docker compose --project-name vibequant run --rm m2divgold python fetch_m2_gold.py
docker compose --project-name vibequant run --rm m2divgold python daily_ratio_chart.py

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') 完成 ====="
