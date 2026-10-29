#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

# Read-only connectivity preflight, before copying or building anything.
remote_exec "true"
"${SCRIPT_DIR}/sync.sh"
"${SCRIPT_DIR}/compose.sh" build m2divgold
"${SCRIPT_DIR}/compose.sh" run --rm usstock-dip-watch python publish.py
# Keep an existing frontend container; start it only if absent/stopped.
"${SCRIPT_DIR}/compose.sh" up -d --no-recreate front
"${SCRIPT_DIR}/compose.sh" exec -T front python -c '
import json
from urllib.request import urlopen
base = "http://127.0.0.1:8000/usstockdipwatch/"
with urlopen(base, timeout=10) as response:
    page = response.read().decode("utf-8")
    assert response.status == 200 and "回撤观察" in page
with urlopen(base + "data.json", timeout=10) as response:
    data = json.load(response)
    assert isinstance(data.get("assets"), list)
with urlopen(base + "reminders.json", timeout=10) as response:
    assert isinstance(json.load(response).get("reminders"), list)
print("Internal HTTP verification passed: page, data.json, reminders.json")
'
"${SCRIPT_DIR}/compose.sh" ps front
printf '\nWeb deployment completed. Open /usstockdipwatch/ under the existing portal URL.\n'
printf 'Market collection, daily schedules, and phone reminders remain disabled.\n'
