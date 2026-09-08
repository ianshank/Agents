#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi
exec "$PYTHON" "${REPO_ROOT}/scripts/verify_tier_a.py"
