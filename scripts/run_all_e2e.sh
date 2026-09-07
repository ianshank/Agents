#!/usr/bin/env bash
# run_all_e2e.sh - POSIX mirror of scripts/run_all_e2e.ps1.
#
# Runs every e2e / user-journey test across the monorepo and emits one aggregated
# pass/fail report under artifacts/e2e-report/. Same five tiers, same step names,
# same report layout as the PowerShell driver (see docs/e2e-runbook.md):
#   A  Package pytest suites (offline)          - always
#   B  Functionality gates via validate.py      - always
#   C  User-journey / CLI e2e (offline)         - always
#   D  Live integrations (credential-gated)     - only with --tiers live|all
#   E  Enterprise live integration suite        - only with --include-enterprise
#
# The step inventory must stay name-for-name identical to the .ps1: the e2e-matrix
# engine parses the .ps1 for the declared set and hard-fails a run whose report
# contains a step the parser cannot see (tests/_e2e_matrix.py policy_problems).
# tests/test_e2e_driver_parity.py asserts the two drivers declare the same steps.
#
# Usage:
#   bash scripts/run_all_e2e.sh --tiers offline
#   bash scripts/run_all_e2e.sh --tiers all --hypothesis-profile ci
#   bash scripts/run_all_e2e.sh --tiers offline --fail-fast
set -euo pipefail

TIERS=all
FAILFAST=0
HYP_PROFILE=dev
ENTERPRISE=0

usage() {
    echo "usage: $0 [--tiers offline|live|all] [--fail-fast] [--hypothesis-profile dev|ci] [--include-enterprise]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --tiers) TIERS="${2:?}"; shift 2 ;;
        --fail-fast) FAILFAST=1; shift ;;
        --hypothesis-profile) HYP_PROFILE="${2:?}"; shift 2 ;;
        --include-enterprise) ENTERPRISE=1; shift ;;
        *) usage ;;
    esac
done
case "$TIERS" in offline | live | all) ;; *) usage ;; esac
case "$HYP_PROFILE" in dev | ci) ;; *) usage ;; esac

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The .ps1 requires a provisioned .venv; this driver falls back to the ambient
# python3 so CI (which pip-installs into the runner's interpreter) needs no venv.
PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# Exit code a credential-gated step returns to mean "not configured -> SKIP".
# 78 is EX_CONFIG from sysexits(3); 2 cannot be used because python exits 2 for a
# missing file and argparse exits 2 for a bad flag. Single source of truth is
# SKIP_EXIT_CODE in scripts/smokes/_smoke_lib.py; tests/test_smoke_lib.py asserts
# the .ps1 mirror agrees, and tests/test_e2e_driver_parity.py asserts this one does.
SKIP_EXIT_CODE=78

# timeout(1) returns 124 on expiry; mirrors the .ps1's $script:TimeoutExit.
TIMEOUT_EXIT=124
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [ -z "$TIMEOUT_BIN" ]; then
    echo "run_all_e2e: coreutils timeout(1) not found (on macOS: brew install coreutils)" >&2
    exit 2
fi

REPORT="$REPO_ROOT/artifacts/e2e-report"
FIXTURES="$REPORT/fixtures"
rm -rf "$REPORT"
mkdir -p "$FIXTURES"

# PYTHONPATH, first entry first:
#  - e2e_shims: sitecustomize.py neutralizes the hanging platform._wmi_query on
#    locked-down Windows hosts (a no-op elsewhere; one code path across drivers).
#  - sibling packages: made importable here. Order matters (behavioral_regression
#    imports agent_core/flow_corpus at module load); claude-foundation exposes
#    foundation_tools under tools/.
export PYTHONPATH="$REPO_ROOT/scripts/e2e_shims:$REPO_ROOT/flow-protocol:$REPO_ROOT/flow-corpus:$REPO_ROOT/behavioral-regression:$REPO_ROOT/claude-foundation/tools:$REPO_ROOT/agent-core"
export HYPOTHESIS_PROFILE="$HYP_PROFILE"
export OUT_DIR="$REPORT"
export PYTHONUTF8=1

# ---------------------------------------------------------------------------
# .env loader (BOM-safe). .env holds live endpoints/keys; it must NOT leak into
# the offline tiers -- SDK-optional tests assert failsafe behaviour when no
# endpoint is configured. Parsed now, applied only just before Tier D.
# ---------------------------------------------------------------------------
declare -A DOTENV=()
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#"$'\xef\xbb\xbf'"}" # strip a leading UTF-8 BOM
        t="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$t" in '' | \#*) continue ;; esac
        case "$t" in *=*) ;; *) continue ;; esac
        k="$(echo "${t%%=*}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        v="$(echo "${t#*=}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
        [ -n "$k" ] && DOTENV["$k"]="$v"
    done < .env
fi

enable_live_env() {
    local k
    for k in "${!DOTENV[@]}"; do
        export "$k=${DOTENV[$k]}"
    done
}

# ---------------------------------------------------------------------------
# Result tracking. Each result is one TAB-separated line in $RESULTS_TSV;
# write_summary renders summary.json + summary.md from it via the driver python
# (so JSON escaping is never hand-rolled in bash).
# ---------------------------------------------------------------------------
RESULTS_TSV="$REPORT/.results.tsv"
: >"$RESULTS_TSV"
COUNT_PASS=0
COUNT_FAIL=0
COUNT_SKIP=0

safe_name() { local n="$1"; echo "${n//[^A-Za-z0-9_.-]/_}"; }

# Millisecond clock. EPOCHREALTIME (bash >= 5) is subprocess-free and genuinely
# sub-second; `date +%s%3N` is GNU-only, and macOS ships neither, so the fallback
# reports whole seconds rather than inventing precision it does not have. The
# duration column is advisory — no gate reads it.
now_ms() {
    if [ -n "${EPOCHREALTIME:-}" ]; then
        local secs="${EPOCHREALTIME%%[.,]*}" frac="${EPOCHREALTIME#*[.,]}"
        frac="${frac}000"
        echo "$((10#$secs * 1000 + 10#${frac:0:3}))"
    else
        date +%s000
    fi
}

write_summary() {
    "$PY" - "$RESULTS_TSV" "$REPORT" "$TIERS" "$HYP_PROFILE" <<'PYEOF'
import json
import sys

tsv, report, tiers, profile = sys.argv[1:5]
rows = []
with open(tsv, encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        tier, name, status, detail, ms = line.split("\t")
        rows.append(
            {
                "tier": tier,
                "name": name,
                "status": status,
                "detail": detail,
                "duration_ms": int(ms),
            }
        )
counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
for r in rows:
    if r["status"] in counts:
        counts[r["status"]] += 1
with open(f"{report}/summary.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(rows, fh, indent=2)
    fh.write("\n")
lines = [
    "# E2E run summary",
    "",
    f"Tiers: `{tiers}`  |  HypothesisProfile: `{profile}`  |  "
    f"PASS {counts['PASS']} / FAIL {counts['FAIL']} / SKIP {counts['SKIP']}",
    "",
    "| Tier | Step | Status | Detail | ms |",
    "|------|------|--------|--------|----|",
]
for r in rows:
    lines.append(f"| {r['tier']} | {r['name']} | {r['status']} | {r['detail']} | {r['duration_ms']} |")
with open(f"{report}/summary.md", "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\n== Summary ==\nPASS {counts['PASS']}  FAIL {counts['FAIL']}  SKIP {counts['SKIP']}")
print(f"Report: {report}/summary.md")
PYEOF
}

add_result() { # tier name status detail [ms]
    local tier="$1" name="$2" status="$3" detail="${4:-}" ms="${5:-0}"
    printf '%s\t%s\t%s\t%s\t%s\n' "$tier" "$name" "$status" "$detail" "$ms" >>"$RESULTS_TSV"
    case "$status" in
        PASS) COUNT_PASS=$((COUNT_PASS + 1)) ;;
        FAIL) COUNT_FAIL=$((COUNT_FAIL + 1)) ;;
        SKIP) COUNT_SKIP=$((COUNT_SKIP + 1)) ;;
    esac
    printf '  [%-4s] %-38s %s\n' "$status" "$name" "$detail"
    if [ "$status" = FAIL ] && [ "$FAILFAST" = 1 ]; then
        write_summary
        echo "FailFast: $name failed" >&2
        exit 1
    fi
}

# Run a python step under a hard timeout; returns the exit code (124 = timeout).
run_py() { # name timeout_sec workdir -- args...
    local name="$1" tmo="$2" wd="$3"
    shift 3
    [ "${1:-}" = "--" ] && shift
    local log
    log="$REPORT/$(safe_name "$name").log"
    local rc=0
    (cd "$wd" && "$TIMEOUT_BIN" "$tmo" "$PY" "$@" >"$log" 2>&1) || rc=$?
    return "$rc"
}

junit_test_count() { # xmlpath -> stdout count (-1 on missing/unparseable)
    "$PY" - "$1" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

try:
    tree = ET.parse(sys.argv[1])
except (OSError, ET.ParseError):
    print(-1)
    raise SystemExit(0)
# Match by local name: a junit namespace prefix must not hide the suites.
total = 0
for el in tree.iter():
    if el.tag.split("}")[-1] == "testsuite":
        total += int(el.get("tests", "0"))
print(total)
PYEOF
}

# A pytest step: run, then assert junit reports > 0 tests (guards vacuous coverage).
invoke_pytest_step() { # tier name junit timeout_sec workdir -- pyargs...
    local tier="$1" name="$2" junit="$3" tmo="$4" wd="$5"
    shift 5
    [ "${1:-}" = "--" ] && shift
    local start n
    local rc=0
    start="$(now_ms)"
    # `|| rc=$?`, not `|| true; rc=$?`: the latter reads the status of `true`, so rc is
    # always 0 and every failing step reports PASS. run_py above uses this same idiom.
    run_py "$name" "$tmo" "$wd" -- "$@" || rc=$?
    local ms=$(($(now_ms) - start))
    if [ "$rc" -eq "$TIMEOUT_EXIT" ]; then
        add_result "$tier" "$name" FAIL "TIMEOUT after ${tmo}s" "$ms"
        return
    fi
    n="$(junit_test_count "$junit")"
    if [ "$rc" -eq 0 ] && [ "$n" -gt 0 ]; then
        add_result "$tier" "$name" PASS "$n tests" "$ms"
    elif [ "$rc" -eq 0 ]; then
        add_result "$tier" "$name" FAIL "exit 0 but $n tests collected (see log)" "$ms"
    else
        add_result "$tier" "$name" FAIL "exit $rc (see $(safe_name "$name").log)" "$ms"
    fi
}

# A plain command step: exit 0 (or a pass code) = PASS, a skip code = SKIP, else FAIL.
invoke_cmd_step() { # tier name pass_codes skip_codes pass_detail timeout_sec workdir -- pyargs...
    local tier="$1" name="$2" pass_codes="$3" skip_codes="$4" detail="$5" tmo="$6" wd="$7"
    shift 7
    [ "${1:-}" = "--" ] && shift
    local start
    local rc=0
    start="$(now_ms)"
    run_py "$name" "$tmo" "$wd" -- "$@" || rc=$?
    local ms=$(($(now_ms) - start))
    if [ "$rc" -eq "$TIMEOUT_EXIT" ]; then
        add_result "$tier" "$name" FAIL "TIMEOUT after ${tmo}s" "$ms"
        return
    fi
    local c
    for c in 0 $pass_codes; do
        if [ "$rc" -eq "$c" ]; then
            local d="$detail"
            [ "$rc" -ne 0 ] && d="${detail:+$detail }exit $rc"
            add_result "$tier" "$name" PASS "$d" "$ms"
            return
        fi
    done
    for c in $skip_codes; do
        if [ "$rc" -eq "$c" ]; then
            add_result "$tier" "$name" SKIP "exit $rc" "$ms"
            return
        fi
    done
    add_result "$tier" "$name" FAIL "exit $rc (see $(safe_name "$name").log)" "$ms"
}

test_env_set() { # name...
    local n
    for n in "$@"; do
        if [ -z "${!n:-}" ]; then
            return 1
        fi
    done
    return 0
}

# Third anti-vacuous-pass guard: a step whose script is missing is a harness
# defect, not a test outcome. Records FAIL and returns 1 rather than exiting, so
# the run continues and the summary still gets written.
test_step_script() { # tier name relpath
    if [ -f "$REPO_ROOT/$3" ]; then
        return 0
    fi
    add_result "$1" "$2" FAIL "step script missing: $3"
    return 1
}

# ---------------------------------------------------------------------------
# Pre-flight import guard (mandatory)
# ---------------------------------------------------------------------------
echo
echo "== Pre-flight =="
rc=0
run_py preflight-imports 120 "$REPO_ROOT" -- -c \
    'import flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness' || rc=$?
if [ "$rc" -ne 0 ]; then
    add_result PRE preflight-imports FAIL 'sibling imports failed - aborting (see preflight-imports.log)'
    write_summary
    echo "Pre-flight import guard failed; PYTHONPATH is wrong or a package is missing." >&2
    exit 1
fi
add_result PRE preflight-imports PASS \
    'flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness'

# ===========================================================================
# TIER A - Package test suites (offline, always)
# ===========================================================================
echo
echo "== Tier A: package suites =="
invoke_pytest_step A suite:root "$REPORT/root.xml" 1800 "$REPO_ROOT" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/root.xml" -p no:cacheprovider
invoke_pytest_step A suite:agent-core "$REPORT/agent-core.xml" 900 "$REPO_ROOT/agent-core" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/agent-core.xml" -p no:cacheprovider
invoke_pytest_step A suite:behavioral-regression "$REPORT/behavioral-regression.xml" 900 "$REPO_ROOT/behavioral-regression" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/behavioral-regression.xml" -p no:cacheprovider
invoke_pytest_step A suite:flow-corpus "$REPORT/flow-corpus.xml" 900 "$REPO_ROOT/flow-corpus" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/flow-corpus.xml" -p no:cacheprovider
invoke_pytest_step A suite:flow-protocol "$REPORT/flow-protocol.xml" 900 "$REPO_ROOT/flow-protocol" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/flow-protocol.xml" -p no:cacheprovider
invoke_pytest_step A suite:claude-foundation "$REPORT/claude-foundation.xml" 900 "$REPO_ROOT/claude-foundation" -- \
    -m pytest --cov --cov-report=term-missing "--junitxml=$REPORT/claude-foundation.xml" -p no:cacheprovider
# Operational-scripts coverage gate (F-031) - reuses tests/ with a scripts coverage config.
invoke_pytest_step A suite:scripts-gate "$REPORT/scripts.xml" 900 "$REPO_ROOT" -- \
    -m pytest tests --cov=scripts --cov-config=scripts/.coveragerc --cov-report=term-missing \
    "--junitxml=$REPORT/scripts.xml" -p no:cacheprovider

# ===========================================================================
# TIER B - Functionality gates (offline, always)
# ===========================================================================
echo
echo "== Tier B: functionality gates (features.yaml) =="
# validate.py runs every done+fast feature's validation_command (all done features
# are tier fast); deferred features (e.g. F-036) are skipped by design.
invoke_cmd_step B features:validate.py "" "" "" 1800 "$REPO_ROOT" -- scripts/validate.py -v
# Matrix-completeness freshness gate (F-053): docs/matrix-coverage.md must match a
# live regeneration. A plain CLI, not pytest -- the junit ">0 tests" assertion
# would false-FAIL it.
invoke_cmd_step B matrix:coverage-check "" "" "" 600 "$REPO_ROOT" -- tests/test_matrix_coverage.py --check

# ===========================================================================
# TIER C - User-journey / CLI e2e (offline, always)
# ===========================================================================
echo
echo "== Tier C: user-journey / CLI e2e =="

# C1: skill + hook end-to-end tests (addopts neutralized so per-package coverage
# gates / strict-config don't collide when run from the repo root).
invoke_pytest_step C e2e:skills+hooks "$REPORT/e2e_journeys.xml" 900 "$REPO_ROOT" -- \
    -m pytest \
    skills/architecture-drift-guard/tests/test_end_to_end.py \
    skills/eval-corpus-forge/tests/test_end_to_end.py \
    skills/project-setup/tests/test_gen_makefile.py \
    skills/project-setup/tests/test_workspace.py \
    skills/quality-gate/tests/test_gen_gate.py \
    skills/deploy/tests/test_gen_deploy.py \
    claude-foundation/tests/test_hooks_e2e.py \
    -o addopts= --import-mode=importlib -p no:cacheprovider "--junitxml=$REPORT/e2e_journeys.xml"

# C1b: backend-validation experiment offline suite. Runs from the subtree so its
# own pyproject drives config. Isolated/temporary experiment, not a package/skill.
BV_DIR="$REPO_ROOT/experiments/backend-validation"
if [ -f "$BV_DIR/pyproject.toml" ]; then
    rc=0
    (cd "$BV_DIR" && PYTHONPATH="$BV_DIR:$PYTHONPATH" "$TIMEOUT_BIN" 900 "$PY" \
        -m pytest tests --cov=backend_validation --cov-branch \
        --cov-report=term-missing --cov-fail-under=95 \
        "--junitxml=$REPORT/backend-validation.xml" -p no:cacheprovider \
        >"$REPORT/e2e_backend-validation.log" 2>&1) || rc=$?
    n="$(junit_test_count "$REPORT/backend-validation.xml")"
    if [ "$rc" -eq 0 ] && [ "$n" -gt 0 ]; then
        add_result C e2e:backend-validation PASS "$n tests"
    elif [ "$rc" -eq 0 ]; then
        add_result C e2e:backend-validation FAIL "exit 0 but $n tests collected (see log)"
    else
        add_result C e2e:backend-validation FAIL "exit $rc (see e2e_backend-validation.log)"
    fi
fi

# C2: eval-harness CLI journeys (offline)
invoke_cmd_step C 'cli:eval-harness list-plugins' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli list-plugins
invoke_cmd_step C 'cli:eval-harness run' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli run --config config/eval.example.yaml --offline
# Override a harmless field so the --set plumbing is exercised without shrinking
# the (2-item) dataset to zero rows (sample_rate=0.1 would sample 0 -> gate fails).
invoke_cmd_step C 'cli:eval-harness run --set' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli run --config config/eval.example.yaml --set run.seed=123 --offline

# C3: generate offline compare/campaign fixtures (config/ is a protected path, so
# these live in the report dir, not the repo).
COMPARE_YAML="$FIXTURES/compare.yaml"
cat >"$COMPARE_YAML" <<'YAML'
schema_version: "1.0"
run: { name: e2e-compare, seed: 7 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "reset password" }, expected: "reset" }
      - { id: q2, inputs: { question: "cancel plan" }, expected: "cancel" }
target: { type: echo, params: { output_key: question } }
scorers:
  - type: contains
    params: { name: mentions_reset, substring: "reset" }
judge:
  type: mock
  params: { default_score: 0.9 }
comparison:
  models:
    - { name: echo_a, target: { type: echo, params: { output_key: question } } }
    - { name: echo_b, target: { type: echo, params: { output_key: expected } } }
YAML
invoke_cmd_step C 'cli:eval-harness compare' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli compare --config "$COMPARE_YAML" --offline \
    --html "$REPORT/compare.html" --json "$REPORT/compare.json"

CAMPAIGN_YAML="$FIXTURES/campaign.yaml"
cat >"$CAMPAIGN_YAML" <<'YAML'
schema_version: "1.0"
run: { name: e2e-campaign, seed: 7 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "reset password" }, expected: "reset" }
      - { id: q2, inputs: { question: "cancel plan" }, expected: "cancel" }
target: { type: echo, params: { output_key: question } }
scorers:
  - type: contains
    params: { name: mentions_reset, substring: "reset" }
judge:
  type: mock
  params: { default_score: 0.9 }
ab_campaign:
  campaign_id: e2e-campaign
  arm_a: { name: a, target: { type: echo, params: { output_key: question } } }
  arm_b: { name: b, target: { type: echo, params: { output_key: expected } } }
  score: mentions_reset
  min_sample: 1
YAML
CAMPAIGN_STORE="$REPORT/campaign_store.jsonl"
invoke_cmd_step C 'cli:eval-harness campaign record' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli campaign --config "$CAMPAIGN_YAML" --store "$CAMPAIGN_STORE" --mode record --offline
invoke_cmd_step C 'cli:eval-harness campaign analyze' "" "" "" 600 "$REPO_ROOT" -- \
    -m eval_harness.cli campaign --config "$CAMPAIGN_YAML" --store "$CAMPAIGN_STORE" --mode analyze --offline \
    --json "$REPORT/campaign_analyze.json"

# C4: behavioral-regression CLI journey (deterministic, offline)
BR_JSON="$REPORT/br.json"
invoke_cmd_step C 'cli:bregress' "" "" "" 600 "$REPO_ROOT" -- \
    -m behavioral_regression --seed 7 --out "$BR_JSON" --html "$REPORT/br.html"
if [ -f "$BR_JSON" ]; then
    if ! "$PY" -m json.tool "$BR_JSON" >/dev/null 2>&1; then
        add_result C 'cli:bregress json-valid' FAIL 'br.json is not valid JSON'
    fi
fi

# C5: agent-core merge_gate_ci CLI journey (throwaway store)
# Exit contract: 0=AUTO_MERGE, 10=ESCALATE, 20=REJECT are all valid gate
# decisions (only 1/2 are errors). The journey verifies the CLI decides.
MG_STORE="$REPORT/merge_gate_store.jsonl"
invoke_cmd_step C 'cli:merge_gate_ci' "10 20" "" "decision" 600 "$REPO_ROOT" -- \
    -m agent_core.merge_gate_ci --store "$MG_STORE" --domain human --raw-confidence 0.9 --mech-pass

# C5b: agent-confidence seed path (F-042) — classify an agent change, then compose
# its seed context. Paths need not exist (classification is by path pattern + head
# ref); config is read from the repo root. Both must exit 0.
AC_JSON="$REPORT/agent_confidence.json"
invoke_cmd_step C 'cli:agent_confidence (agent lane)' "" "" "" 600 "$REPO_ROOT" -- \
    scripts/agent_confidence.py --files src/eval_harness/x.py tests/test_x.py \
    --lines-changed 40 --head-ref claude/e2e-journey --output "$AC_JSON"
AGENT_SEED_JSON="$REPORT/agent_seed_context.json"
invoke_cmd_step C 'cli:merge_gate_context (--confidence)' "" "" "" 600 "$REPO_ROOT" -- \
    scripts/merge_gate_context.py --files src/eval_harness/x.py tests/test_x.py \
    --confidence 0.5 --output "$AGENT_SEED_JSON"

# C5c: agent-core read-only reporting CLIs over a seeded throwaway store. These
# never write to the store and never influence a gate decision, so unlike C5 they
# must exit 0. The store is built by the audit-sampler CLI so the journey also
# covers the propensity round-trip (select --with-propensity -> record
# --selection-propensity).
REPORT_STORE="$REPORT/report_store.jsonl"
invoke_cmd_step C 'cli:merge_seed (report store)' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.merge_seed --store "$REPORT_STORE" --change-id e2e0001 \
    --domain agent-core --raw-confidence 0.7
invoke_cmd_step C 'cli:audit_sampler select --with-propensity' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.audit_sampler --store "$REPORT_STORE" select \
    --base-rate 1.0 --per-domain-floor 0 --with-propensity
invoke_cmd_step C 'cli:audit_sampler record --selection-propensity' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.audit_sampler --store "$REPORT_STORE" record \
    --change-id e2e0001 --correct --selection-propensity 1.0
# Both estimators must render. `ppi++` is report-only: it never changes a gate
# decision, and falls back to Wilson (saying so) whenever the proxy cannot support it.
invoke_cmd_step C 'cli:calibration_report (wilson)' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.calibration_report --store "$REPORT_STORE" --domain-filter all
invoke_cmd_step C 'cli:calibration_report (--estimator ppi++)' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.calibration_report --store "$REPORT_STORE" --domain-filter all --estimator ppi++
PROXY_JSON="$REPORT/proxy_eval.json"
invoke_cmd_step C 'cli:proxy_eval (json)' "" "" "" 600 "$REPO_ROOT" -- \
    -m agent_core.proxy_eval --store "$REPORT_STORE" --domain-filter all --format json --output "$PROXY_JSON"
# Records an outcome in ALL three cases. A missing artifact used to record nothing,
# so the journey could pass while never validating the JSON it exists to produce.
if [ -f "$PROXY_JSON" ]; then
    if "$PY" -m json.tool "$PROXY_JSON" >/dev/null 2>&1; then
        add_result C 'cli:proxy_eval json-valid' PASS
    else
        add_result C 'cli:proxy_eval json-valid' FAIL 'proxy_eval.json is not valid JSON'
    fi
else
    add_result C 'cli:proxy_eval json-valid' FAIL 'proxy_eval did not write proxy_eval.json'
fi

# C6: skill-marketplace CLI journeys
invoke_cmd_step C 'cli:skill_marketplace list' "" "" "" 600 "$REPO_ROOT" -- \
    scripts/skill_marketplace.py list
invoke_cmd_step C 'cli:skill_marketplace verify' "" "" "" 600 "$REPO_ROOT" -- \
    scripts/skill_marketplace.py verify

# ===========================================================================
# TIER D - Live integrations (credential-gated)
# ===========================================================================
if [ "$TIERS" = live ] || [ "$TIERS" = all ]; then
    echo
    echo "== Tier D: live integrations (credential-gated) =="
    enable_live_env # only now inject .env creds/endpoints (kept out of Tiers A-C)

    # Langfuse smoke (script exits 78/EX_CONFIG when creds missing -> SKIP). The
    # smokes live in scripts/smokes/ (tracked) so a missing file cannot masquerade
    # as SKIP: a missing script exits 2, which is not the skip code.
    if ! test_step_script D live:langfuse-smoke scripts/smokes/langfuse_smoke.py; then
        :
    elif test_env_set LANGFUSE_SECRET_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_BASE_URL; then
        invoke_cmd_step D live:langfuse-smoke "" "$SKIP_EXIT_CODE" "" 600 "$REPO_ROOT" -- \
            scripts/smokes/langfuse_smoke.py
    else
        add_result D live:langfuse-smoke SKIP 'LANGFUSE_* not set'
    fi

    # Phoenix smoke (needs a running collector)
    if ! test_step_script D live:phoenix-smoke scripts/smokes/phoenix_smoke.py; then
        :
    elif test_env_set PHOENIX_COLLECTOR_ENDPOINT; then
        invoke_cmd_step D live:phoenix-smoke "" "$SKIP_EXIT_CODE" "" 600 "$REPO_ROOT" -- \
            scripts/smokes/phoenix_smoke.py
    else
        add_result D live:phoenix-smoke SKIP 'PHOENIX_COLLECTOR_ENDPOINT not set'
    fi

    # Local OpenAI-compatible model (LM Studio / Ollama / any /v1 server). When set,
    # the live journeys use a REAL model target instead of the `echo` stand-in.
    # base_url is deliberately NOT passed in the fixture: ModelTarget leaves it None
    # and the openai SDK reads OPENAI_BASE_URL from the environment, keeping the
    # endpoint out of committed YAML.
    if [ -n "${LOCAL_MODEL_ID:-}" ]; then
        LIVE_TARGET="{ type: model, params: { provider: openai, model: \"$LOCAL_MODEL_ID\" } }"
        # A real judge too: `mock` returned a constant 0.9 regardless of the output.
        LIVE_JUDGE="{ type: openai, params: { model: \"$LOCAL_MODEL_ID\" } }"
        echo "  live target/judge: model/$LOCAL_MODEL_ID (real round-trip)"
    else
        LIVE_TARGET='{ type: echo, params: { output_key: question } }'
        LIVE_JUDGE='{ type: mock, params: { default_score: 0.9 } }'
        echo "  live target/judge: echo+mock (set LOCAL_MODEL_ID for a real round-trip)"
    fi

    # Live judge journeys. The judge constructor's model keyword is not uniform:
    # OpenAI/Anthropic take `model`, Bedrock takes `model_id` — keeping the keyword
    # next to the model it applies to is what stops that recurring mismatch.
    if test_env_set OPENAI_API_KEY; then
        cat >"$FIXTURES/live_openai.yaml" <<YAML
schema_version: "1.0"
run: { name: live-openai, seed: 7, sample_rate: 1.0 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "Reply with the single word: ok" }, expected: "ok" }
target: $LIVE_TARGET
scorers:
  - type: llm_judge
    params: { name: helpfulness }
judge:
  type: openai
  params: { model: "${OPENAI_JUDGE_MODEL:-gpt-4o-mini}" }
sinks:
  - { type: console, params: { verbose: false } }
gate: { rules: [] }
YAML
        invoke_cmd_step D live:judge-openai "" "" "" 600 "$REPO_ROOT" -- \
            -m eval_harness.cli run --config "$FIXTURES/live_openai.yaml"
    else
        add_result D live:judge-openai SKIP 'OPENAI_API_KEY not set'
    fi
    if test_env_set ANTHROPIC_API_KEY; then
        cat >"$FIXTURES/live_anthropic.yaml" <<YAML
schema_version: "1.0"
run: { name: live-anthropic, seed: 7, sample_rate: 1.0 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "Reply with the single word: ok" }, expected: "ok" }
target: $LIVE_TARGET
scorers:
  - type: llm_judge
    params: { name: helpfulness }
judge:
  type: anthropic
  params: { model: "${ANTHROPIC_JUDGE_MODEL:-claude-haiku-4-5-20251001}" }
sinks:
  - { type: console, params: { verbose: false } }
gate: { rules: [] }
YAML
        invoke_cmd_step D live:judge-anthropic "" "" "" 600 "$REPO_ROOT" -- \
            -m eval_harness.cli run --config "$FIXTURES/live_anthropic.yaml"
    else
        add_result D live:judge-anthropic SKIP 'ANTHROPIC_API_KEY not set'
    fi
    if test_env_set AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; then
        cat >"$FIXTURES/live_bedrock.yaml" <<YAML
schema_version: "1.0"
run: { name: live-bedrock, seed: 7, sample_rate: 1.0 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "Reply with the single word: ok" }, expected: "ok" }
target: $LIVE_TARGET
scorers:
  - type: llm_judge
    params: { name: helpfulness }
judge:
  type: bedrock
  params: { model_id: "${BEDROCK_JUDGE_MODEL:-anthropic.claude-3-haiku-20240307-v1:0}" }
sinks:
  - { type: console, params: { verbose: false } }
gate: { rules: [] }
YAML
        invoke_cmd_step D live:judge-bedrock "" "" "" 600 "$REPO_ROOT" -- \
            -m eval_harness.cli run --config "$FIXTURES/live_bedrock.yaml"
    else
        add_result D live:judge-bedrock SKIP 'AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY not set'
    fi

    # Live Langfuse sink journey (writes scores to the backend)
    if test_env_set LANGFUSE_SECRET_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_BASE_URL; then
        cat >"$FIXTURES/live_langfuse_sink.yaml" <<YAML
schema_version: "1.0"
run: { name: live-langfuse-sink, seed: 7 }
dataset:
  type: inline
  params:
    items: [ { id: q1, inputs: { question: "reset password" }, expected: "reset" } ]
target: $LIVE_TARGET
scorers: [ { type: contains, params: { name: mentions_reset, substring: "reset" } } ]
judge: $LIVE_JUDGE
sinks:
  - { type: console, params: { verbose: false } }
  - { type: langfuse }
gate: { rules: [] }
YAML
        invoke_cmd_step D live:langfuse-sink "" "" "" 600 "$REPO_ROOT" -- \
            -m eval_harness.cli run --config "$FIXTURES/live_langfuse_sink.yaml"
    else
        add_result D live:langfuse-sink SKIP 'LANGFUSE_* not set'
    fi

    # Live Phoenix sink journey
    if test_env_set PHOENIX_COLLECTOR_ENDPOINT; then
        cat >"$FIXTURES/live_phoenix_sink.yaml" <<YAML
schema_version: "1.0"
run: { name: live-phoenix-sink, seed: 7 }
phoenix: { enabled: true, project_name: e2e-phoenix, tracing: true }
dataset:
  type: inline
  params:
    items: [ { id: q1, inputs: { question: "reset password" }, expected: "reset" } ]
target: $LIVE_TARGET
scorers: [ { type: contains, params: { name: mentions_reset, substring: "reset" } } ]
judge: $LIVE_JUDGE
sinks:
  - { type: console, params: { verbose: false } }
  - { type: phoenix, params: { enabled: true } }
gate: { rules: [] }
YAML
        invoke_cmd_step D live:phoenix-sink "" "" "" 600 "$REPO_ROOT" -- \
            -m eval_harness.cli run --config "$FIXTURES/live_phoenix_sink.yaml"
    else
        add_result D live:phoenix-sink SKIP 'PHOENIX_COLLECTOR_ENDPOINT not set'
    fi
fi

# ===========================================================================
# TIER E - Enterprise live integration suite (opt-in)
# ===========================================================================
if [ "$ENTERPRISE" = 1 ]; then
    echo
    echo "== Tier E: Enterprise live integration suite =="
    ENT_DIR="$REPO_ROOT/../Enterprise/files/langfuse-eval-harness/langfuse-eval-harness"
    if [ -d "$ENT_DIR/tests/integration" ]; then
        invoke_pytest_step E enterprise:integration "$REPORT/enterprise.xml" 900 "$ENT_DIR" -- \
            -m pytest tests/integration -m integration -o addopts= -p no:cacheprovider \
            "--junitxml=$REPORT/enterprise.xml"
    else
        add_result E enterprise:integration SKIP "not found at $ENT_DIR/tests/integration"
    fi
fi

# ===========================================================================
# Summary
# ===========================================================================
write_summary

if [ "$COUNT_FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
