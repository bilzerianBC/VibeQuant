#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
python_code='from pathlib import Path; import secrets; p=Path(".env.web"); p.write_text("DIPWATCH_EDIT_PASSWORD="+secrets.token_urlsafe(24)+"\n") if not p.exists() else None; p.chmod(0o600); print("Website editing configuration prepared; existing password preserved")'
remote_exec "cd $(remote_shell_quote "${REMOTE_DOCKER_DIR}") && umask 077 && python3 -c $(remote_shell_quote "${python_code}")"
