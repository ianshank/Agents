#!/usr/bin/env bash
# Install smoke test — deterministic and offline.
#
# 1. The official validator must accept the plugin.
# 2. Every hook script must execute standalone with the documented stdin
#    contract (the exact way the harness invokes them at install time).
#
# Run from the plugin root: bash tests/smoke/install_smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"

echo "== claude plugin validate =="
if command -v claude >/dev/null 2>&1; then
    (cd "$ROOT" && claude plugin validate .)
else
    echo "claude CLI not on PATH — skipping official validation (CI installs it)"
fi

echo "== hook stdin contract =="
deny_out="$(printf '%s' '{"tool_name":"Read","tool_input":{"file_path":"/x/.env"}}' \
    | "$PY" "$ROOT/hooks/pre_tool_guard.py")"
echo "$deny_out" | "$PY" -c '
import json, sys
out = json.load(sys.stdin)["hookSpecificOutput"]
assert out["permissionDecision"] == "deny", out
print("pre-tool-guard: deny contract OK")
'

printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"/nonexistent"}}' \
    | "$PY" "$ROOT/hooks/post_edit_verify.py" >/dev/null
echo "post-edit-verify: fail-open contract OK"

printf '%s' '{"tool_name":"Read","tool_input":{},"session_id":"smoke"}' \
    | "$PY" "$ROOT/hooks/session_logger.py" >/dev/null
echo "session-logger: no-op contract OK"

echo "== own validator + scanner =="
(cd "$ROOT" && "$PY" -m foundation_tools.validate --root . && "$PY" -m foundation_tools.scan --root .)

echo "install-smoke: OK"
