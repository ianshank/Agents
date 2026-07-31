"""Tests for the merge-gate CI entrypoint."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core import merge_gate_ci
from agent_core.merge_gate import ChangeContext, GateDecision, GatePolicyConfig
from agent_core.merge_gate_ci import main, run
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore, _fold
from agent_core.protocols import FixedClock

CFG = GatePolicyConfig()


def _healthy_store(path) -> OutcomeStore:
    store = OutcomeStore(path)
    for i in range(1000):
        high = i % 2 == 0
        store.append(
            OutcomeRecord(
                change_id=f"c{i}",
                domain="core",
                raw_confidence=0.96 if high else 0.04,
                merged_at="2026-01-01T00:00:00+00:00",
                label=high,
                label_source=LabelSource.HUMAN_AUDIT.value,
                labeled_at="2026-01-02T00:00:00+00:00",
            )
        )
    return store


def _ctx(**kw: object) -> ChangeContext:
    base: dict[str, Any] = dict(
        mech_pass=True, touches_protected=False, raw_confidence=0.96, domain="core"
    )
    base.update(kw)
    return ChangeContext(**base)


def test_run_cold_start_escalates(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    d, why = run(_ctx(domain="unknown"), store, CFG)
    assert d == GateDecision.ESCALATE
    assert "cold start" in why


def test_run_reject_on_mech_fail(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, _ = run(_ctx(mech_pass=False), store, CFG)
    assert d == GateDecision.REJECT


def test_run_protected_escalates(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, _ = run(_ctx(touches_protected=True), store, CFG)
    assert d == GateDecision.ESCALATE


def test_run_auto_merge_on_healthy_high_confidence(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, why = run(_ctx(), store, CFG)
    assert d == GateDecision.AUTO_MERGE
    assert "tau=" in why


def test_run_bin_conflation_avoided(tmp_path):
    # A lone audit in a different high bin (0.85) must not piggyback on the
    # well-populated 0.96 bin: grouping by bin index keeps it thin -> ESCALATE.
    #
    # The change_id is pinned to fold 0 deliberately. With a fold-1 id this test passed
    # for the wrong reason: the lone record landed in the HELD-OUT fold, made the domain
    # untrustworthy, and escalated at the health layer -- never reaching the Wilson floor
    # it exists to exercise. Fold 0 puts it in the calibrator but not in the health
    # measurement, so the escalation must come from the thin operating bin.
    store = _healthy_store(tmp_path / "s.jsonl")
    assert _fold("lone0") == 0, "this test requires the lone record in the FIT fold"
    store.append(
        OutcomeRecord(
            change_id="lone0",
            domain="core",
            raw_confidence=0.85,
            merged_at="2026-01-01T00:00:00+00:00",
            label=True,
            label_source=LabelSource.HUMAN_AUDIT.value,
            labeled_at="2026-01-02T00:00:00+00:00",
        )
    )
    d, why = run(_ctx(raw_confidence=0.85), store, CFG)
    assert d == GateDecision.ESCALATE
    # Prove it reached the Wilson floor rather than short-circuiting at health.
    assert "healthy=True" in why and "bin=1/1" in why


def test_main_exit_codes_via_argv(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    assert (
        main(["--store", store_path, "--mech-pass", "--raw-confidence", "0.96", "--domain", "core"])
        == 0
    )
    assert main(["--store", store_path, "--no-mech-pass", "--domain", "core"]) == 20
    assert main(["--store", store_path, "--mech-pass", "--domain", "unknown"]) == 10


def test_main_with_context_file_and_audit_log(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    ctx_file = tmp_path / "ctx.json"
    ctx_file.write_text(
        json.dumps(
            {
                "mech_pass": True,
                "touches_protected": False,
                "raw_confidence": 0.96,
                "domain": "core",
            }
        ),
        encoding="utf-8",
    )
    audit = tmp_path / "audit.jsonl"
    rc = main(["--store", store_path, "--context", str(ctx_file), "--audit-log", str(audit)])
    assert rc == 0
    line = json.loads(audit.read_text(encoding="utf-8").strip())
    assert line["decision"] == "auto_merge" and line["domain"] == "core"


def test_main_internal_error_returns_one(tmp_path):
    # --context points at a missing file -> read raises -> caught -> exit 1.
    rc = main(["--store", str(tmp_path / "s.jsonl"), "--context", str(tmp_path / "missing.json")])
    assert rc == 1


def test_append_audit_uses_injected_clock(tmp_path):
    """Direct unit test of the private _append_audit DI seam: a broken
    `clock or SystemClock()` fallback would go undetected via main() alone, since
    no existing test asserts anything about the written `ts` field."""
    fixed = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    audit = tmp_path / "audit.jsonl"
    ctx = _ctx()
    merge_gate_ci._append_audit(
        str(audit), ctx, GateDecision.AUTO_MERGE, "why", clock=FixedClock(fixed)
    )

    line = json.loads(audit.read_text(encoding="utf-8").strip())
    assert line["ts"] == fixed.isoformat()
    assert line["decision"] == "auto_merge"


def test_main_missing_store_is_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_exit_table_covers_all_decisions():
    assert set(merge_gate_ci.EXIT) == set(GateDecision)


def test_seed_store_seeds_pending_on_auto_merge(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    seed_path = tmp_path / "seed.jsonl"
    rc = main(
        [
            "--store",
            store_path,
            "--mech-pass",
            "--raw-confidence",
            "0.96",
            "--domain",
            "core",
            "--seed-store",
            str(seed_path),
            "--change-id",
            "pr-42",
            "--merged-at",
            "2026-06-30T00:00:00+00:00",
        ]
    )
    assert rc == 0
    seeded = OutcomeStore(seed_path).all()
    assert len(seeded) == 1
    assert seeded[0].change_id == "pr-42"
    assert seeded[0].label is None  # pending


def test_seed_store_no_seed_on_escalate(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    seed_path = tmp_path / "seed.jsonl"
    # unknown domain -> cold-start ESCALATE -> nothing seeded
    rc = main(
        [
            "--store",
            store_path,
            "--mech-pass",
            "--domain",
            "unknown",
            "--seed-store",
            str(seed_path),
            "--change-id",
            "pr-99",
        ]
    )
    assert rc == 10
    assert not seed_path.exists()


def test_seed_store_ignored_without_change_id(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    seed_path = tmp_path / "seed.jsonl"
    # --seed-store but no --change-id -> seam not triggered, decision unaffected
    rc = main(
        [
            "--store",
            store_path,
            "--mech-pass",
            "--raw-confidence",
            "0.96",
            "--domain",
            "core",
            "--seed-store",
            str(seed_path),
        ]
    )
    assert rc == 0
    assert not seed_path.exists()


@pytest.mark.parametrize(
    "bad", ["nan", "inf", "1.5", "-0.2"], ids=["nan", "inf", "above-1", "below-0"]
)
def test_main_rejects_out_of_contract_confidence_as_usage_error(tmp_path, bad, capsys):
    """Bad input exits 2 (usage), not 0 (AUTO_MERGE) and not 1 (internal error).

    Exit 0 is the dangerous outcome here: CI treats it as "proceed to merge".
    """
    rc = main(
        [
            "--store",
            str(tmp_path / "s.jsonl"),
            "--mech-pass",
            "--raw-confidence",
            bad,
            "--domain",
            "core",
        ]
    )
    assert rc == 2
    assert "invalid input" in capsys.readouterr().err


def test_main_rejects_out_of_contract_confidence_from_context_file(tmp_path, capsys):
    ctx_file = tmp_path / "ctx.json"
    ctx_file.write_text(
        json.dumps(
            {
                "mech_pass": True,
                "touches_protected": False,
                "raw_confidence": float("nan"),
                "domain": "core",
            }
        ),
        encoding="utf-8",
    )
    rc = main(["--store", str(tmp_path / "s.jsonl"), "--context", str(ctx_file)])
    assert rc == 2
    assert "invalid input" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ('{"mech_pass": true, "touches_protected": false, "domain": "core"}', "missing field"),
        (
            '{"mech_pass": true, "touches_protected": false, '
            '"raw_confidence": null, "domain": "core"}',
            "null where a value belongs",
        ),
        ("{not json at all", "malformed JSON"),
    ],
    ids=["missing-key", "null-value", "malformed-json"],
)
def test_main_malformed_context_is_a_usage_error(tmp_path, payload, why, capsys):
    """Every way a caller can hand over a bad context maps to exit 2, not exit 1.

    KeyError (missing field) and TypeError (null) are as much "your input is wrong" as a
    ValueError is; reporting them as internal faults sent CI chasing a gate bug instead.
    """
    ctx_file = tmp_path / "ctx.json"
    ctx_file.write_text(payload, encoding="utf-8")
    rc = main(["--store", str(tmp_path / "s.jsonl"), "--context", str(ctx_file)])
    assert rc == 2, why
    assert "invalid input" in capsys.readouterr().err


def test_main_unreadable_context_path_stays_an_internal_error(tmp_path):
    """A missing --context file is the environment failing, not a bad caller value."""
    rc = main(["--store", str(tmp_path / "s.jsonl"), "--context", str(tmp_path / "nope.json")])
    assert rc == 1


# --- gate-policy CLI seam ----------------------------------------------------
def _ctx_file(tmp_path, **over: Any) -> str:
    payload = {
        "mech_pass": True,
        "touches_protected": False,
        "raw_confidence": 0.96,
        "domain": "core",
    }
    payload.update(over)
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--risk-target", "1.0"),
        ("--min-calibration-n", "0"),
        ("--min-auroc", "0.5"),
        ("--n-bins", "1"),
        ("--wilson-z", "nan"),
        ("--wilson-floor", "0.0"),
    ],
)
def test_main_rejects_out_of_range_policy_as_usage_error(tmp_path, capsys, flag, value) -> None:
    """An out-of-range policy is exit 2 (usage), never 1 (internal), never 0 (merge).

    The construction sits inside main()'s outer `except Exception -> return 1`, so a
    ConfigError raised there would be reported as an internal fault -- contradicting the
    module docstring's exit contract and telling CI "the gate broke" instead of "fix your
    inputs". argparse's type=float also accepts "nan"/"inf" happily; the config's isfinite
    guards are the only thing that stops them.
    """
    store = _healthy_store(tmp_path / "s.jsonl")
    rc = main(["--store", str(store.path), "--context", _ctx_file(tmp_path), flag, value])
    assert rc == 2
    assert "merge-gate invalid policy" in capsys.readouterr().err


def test_policy_flags_reach_the_decision(tmp_path) -> None:
    """Proves the flags are THREADED, not merely parsed.

    A test that only asserts exit 2 on bad input would pass even if _policy_from_args
    built a config that main() then dropped on the floor.
    """
    store = _healthy_store(tmp_path / "s.jsonl")
    argv = ["--store", str(store.path), "--context", _ctx_file(tmp_path)]
    assert main(argv) == 0  # AUTO_MERGE at the documented defaults
    assert main([*argv, "--min-calibration-n", "100000"]) == 10  # ESCALATE: floor unreachable


def test_no_protected_auto_merge_flag(tmp_path) -> None:
    """The one tunable deliberately withheld from operators.

    ADR 0005 makes never-auto-merging protected paths a design invariant, not a knob.
    The field stays reachable in-process (the suite exercises it) but a CI job must not
    be able to switch off the protected-path layer from a workflow file.
    """
    store = _healthy_store(tmp_path / "s.jsonl")
    with pytest.raises(SystemExit) as exc:
        main(
            ["--store", str(store.path), "--context", _ctx_file(tmp_path), "--protected-auto-merge"]
        )
    assert exc.value.code == 2


def test_protected_auto_merge_is_logged_when_enabled(tmp_path, caplog) -> None:
    """If it is ever set in-process, the audit trail must show the layer was disabled."""
    store = _healthy_store(tmp_path / "s.jsonl")
    ctx = ChangeContext(mech_pass=True, touches_protected=False, raw_confidence=0.96, domain="core")
    with caplog.at_level("WARNING"):
        run(ctx, store, GatePolicyConfig(protected_auto_merge=True))
    assert "protected_auto_merge is ENABLED" in caplog.text
