#!/usr/bin/env bash
# SessionStart hook — make a fresh checkout's toolchain match CI before any work starts.
#
# WHY THIS EXISTS. `pip install -e '.[dev]'` (CONTRIBUTING.md) installs neither the four
# sibling packages, nor `hypothesis`, nor the optional extras. Without them the gates report
# failures that are artifacts of the environment, not of the code. Three real examples, each
# of which cost investigation time before being traced to a missing package:
#
#   symptom                                          actual cause
#   -----------------------------------------------  ---------------------------------------
#   8 files "would be reformatted", incl. untouched   a newer ruff than the pinned 0.15.20
#     READMEs                                           (markdown formatting changed in 0.16)
#   config/__init__.py "Returning Any" mypy error     pydantic not installed
#   5 `untyped-decorator` errors in agent-core        hypothesis not installed, so @given is
#                                                       untyped
#   `make check-all` dies in claude-foundation with   claude-foundation was the one package
#     "No module named 'foundation_tools'", and         this hook did not install, and its
#     'Library stubs not installed for "yaml"'          declared types-PyYAML came with it
#
# Idempotent and safe to re-run. Never fails the session: a sandbox without network still
# gets a usable shell, just with the warning below.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT" || exit 0

log() { printf '\033[1m[session-start]\033[0m %s\n' "$1"; }

# Pinned in pyproject's [dev] extra. Read from there rather than duplicated here, so this
# hook cannot drift from the versions CI actually uses.
PINNED="$(python3 - <<'PY' 2>/dev/null || true
import pathlib, re
text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'dev\s*=\s*\[([^\]]*)\]', text, re.S)
if match:
    pins = re.findall(r'"((?:ruff|mypy)==[^"]+)"', match.group(1))
    print(" ".join(pins))
PY
)"

if [ -z "${SKIP_SESSION_BOOTSTRAP:-}" ]; then
  log "installing the pinned toolchain and every package the gates import"
  {
    # Order matters: the root package first, then siblings, so editable installs resolve.
    # Every package `make check-all` recurses into must be here — claude-foundation is a
    # target like any other, and omitting it made the sweep die before reaching it.
    # `[dev]` on claude-foundation pulls its declared types-PyYAML stubs.
    python3 -m pip install -q -e '.[dev,langfuse,openai,anthropic,archguard,parquet]' \
      && python3 -m pip install -q -e ./agent-core -e ./flow-protocol \
                                   -e ./flow-corpus -e ./behavioral-regression \
                                   -e './claude-foundation[dev]' \
      && python3 -m pip install -q hypothesis \
      && { [ -z "$PINNED" ] || python3 -m pip install -q $PINNED; }
  } || log "WARNING: bootstrap incomplete (offline?). Gate output may show environment artifacts, not real findings."
else
  log "SKIP_SESSION_BOOTSTRAP set — skipping dependency install"
fi

log "ready. Verify with: ./scripts/quality-gate.sh all && make check-all"
