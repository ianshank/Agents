"""Tests for store_sync — pure merge core, config validation, and soak progress.

Decomposed to maintain module focus and size budgets; real-git tests are in
test_store_sync_git.py and concurrency/CLI tests are in test_store_sync_concurrency.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_core.audit_sampler import AuditConfig
from agent_core.config import ConfigError, SoakConfig
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from agent_core.store_sync import (
    EXIT_OK,
    UNPARSED_STATS_KEY,
    StoreSyncConfig,
    canonical_key,
    effective_soak_target,
    main,
    merge_records,
    read_store,
    read_store_lines,
    serialize_store,
    soak_progress,
    store_stats,
    write_store,
)


def _rec(
    change_id: str = "c1",
    domain: str = "human/agent-core",
    merged_at: str = "2026-01-01T00:00:00+00:00",
    label: bool | None = None,
    label_source: str | None = None,
    labeled_at: str | None = None,
) -> OutcomeRecord:
    return OutcomeRecord(
        change_id=change_id,
        domain=domain,
        raw_confidence=0.0,
        merged_at=merged_at,
        label=label,
        label_source=label_source,
        labeled_at=labeled_at,
    )


def _cfg(clone: Path, **kw: object) -> StoreSyncConfig:
    kw.setdefault("backoff_base_s", 0.0)
    return StoreSyncConfig(repo_dir=str(clone), **kw)  # type: ignore[arg-type]


# --- config validation ---------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"remote": ""},
        {"branch": ""},
        {"store_filename": ""},
        {"store_filename": "data/store.jsonl"},
        {"store_filename": "data\\store.jsonl"},
        {"git_timeout_s": 0},
        {"max_push_retries": 0},
        {"backoff_base_s": -1.0},
        {"commit_user_name": ""},
        {"commit_user_email": ""},
    ],
)
def test_config_validation_raises_config_error(kw):
    with pytest.raises(ConfigError):
        StoreSyncConfig(**kw)


# --- pure merge core -----------------------------------------------------------
def test_canonical_key_orders_pending_before_labels():
    pending = _rec()
    labeled = _rec(label=False, label_source="revert", labeled_at="2026-01-02T00:00:00+00:00")
    assert canonical_key(pending) < canonical_key(labeled)


def test_merge_records_dedupes_identical_lines_and_keeps_distinct_labels():
    pending = _rec()
    rev = _rec(label=False, label_source="revert", labeled_at="2026-01-02T00:00:00+00:00")
    merged = merge_records([pending, rev], [pending])
    assert merged == [pending, rev]


def test_serialize_store_byte_stable_under_shuffle():
    records = [
        _rec(change_id=c, labeled_at=la, label_source=ls, label=lb)
        for c, la, ls, lb in [
            ("c1", None, None, None),
            ("c2", "2026-01-03T00:00:00+00:00", "timeout_clean", True),
            ("c1", "2026-01-02T00:00:00+00:00", "revert", False),
        ]
    ]
    a = serialize_store(merge_records(records))
    b = serialize_store(merge_records(reversed(records)))
    assert a == b


def test_read_store_absent_file_is_empty(tmp_path):
    assert read_store(tmp_path / "nope.jsonl") == []


def test_write_store_atomic_and_propagates_failure(tmp_path):
    path = tmp_path / "s.jsonl"
    write_store(path, [_rec()])
    assert read_store(path) == [_rec()]
    with pytest.raises(OSError):
        write_store(tmp_path / "missing-dir" / "s.jsonl", [_rec()])


def test_stats_counts_per_domain_per_source_including_pending(tmp_path):
    path = tmp_path / "s.jsonl"
    write_store(
        path,
        [
            _rec(change_id="c1"),
            _rec(
                change_id="c1",
                label=False,
                label_source="revert",
                labeled_at="2026-01-02T00:00:00+00:00",
            ),
            _rec(change_id="c2", domain="human/docs"),
        ],
    )
    assert store_stats(read_store(path)) == {
        "human/agent-core": {"pending": 1, "revert": 1},
        "human/docs": {"pending": 1},
    }


def test_stats_reports_unparsed_lines(tmp_path):
    store = tmp_path / "s.jsonl"
    store.write_text(_rec().to_json() + "\n\n" + "{broken\n", encoding="utf-8")
    records, opaque = read_store_lines(store)
    stats = store_stats(records, opaque)
    assert stats[UNPARSED_STATS_KEY] == {"lines": 1}
    assert stats["human/agent-core"] == {"pending": 1}


# --- hypothesis: merge properties ------------------------------------------------
_records_strategy = st.lists(
    st.builds(
        _rec,
        change_id=st.sampled_from(["c1", "c2", "c3"]),
        domain=st.sampled_from(["human/a", "human/b"]),
        merged_at=st.sampled_from(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]),
        label=st.sampled_from([True, False]),
        label_source=st.sampled_from([s.value for s in LabelSource]),
        labeled_at=st.sampled_from(["2026-01-03T00:00:00+00:00", "2026-01-04T00:00:00+00:00"]),
    )
    | st.builds(
        _rec,
        change_id=st.sampled_from(["c1", "c2", "c3"]),
        domain=st.sampled_from(["human/a", "human/b"]),
        merged_at=st.sampled_from(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]),
    ),
    max_size=12,
)


@given(a=_records_strategy, b=_records_strategy)
def test_merge_idempotent_and_commutative(a, b):
    ab = serialize_store(merge_records(a, b))
    ba = serialize_store(merge_records(b, a))
    again = serialize_store(merge_records(merge_records(a, b), a))
    assert ab == ba == again


@given(records=_records_strategy, data=st.data())
def test_any_interleaving_yields_identical_store_and_resolved_view(tmp_path_factory, records, data):
    permutation = data.draw(st.permutations(records))
    cut = data.draw(st.integers(min_value=0, max_value=len(records)))
    merged_a = merge_records(records)
    merged_b = merge_records(list(permutation)[:cut], list(permutation)[cut:])
    assert serialize_store(merged_a) == serialize_store(merged_b)
    base = tmp_path_factory.mktemp("interleave")
    pa, pb = base / "a.jsonl", base / "b.jsonl"
    write_store(pa, merged_a)
    write_store(pb, merged_b)
    assert OutcomeStore(pa).resolved() == OutcomeStore(pb).resolved()


@given(a=_records_strategy, b=_records_strategy)
def test_human_audit_records_never_dropped_and_still_win(tmp_path_factory, a, b):
    merged = merge_records(a, b)
    human = [r for r in a + b if r.label_source == LabelSource.HUMAN_AUDIT.value]
    for rec in human:
        assert rec in merged
    path = tmp_path_factory.mktemp("human") / "s.jsonl"
    write_store(path, merged)
    resolved = OutcomeStore(path).resolved()
    for rec in human:
        assert resolved[rec.change_id].label_source == LabelSource.HUMAN_AUDIT.value


# --- F-040: soak progress (pure, read-only over already-parsed records) ----------
def test_soak_progress_empty_store_is_zeroed_and_velocity_none():
    p = soak_progress([], target=20)
    assert p["total"] == 0 and p["pending"] == 0 and p["labeled"] == 0
    assert p["human_audit"] == 0
    assert p["per_domain_cold_start"] == {}
    assert p["n_vs_target"] == {"n": 0, "target": 20, "shortfall": 20}
    assert p["velocity_per_day"] is None
    assert p["days_to_target"] is None


def test_soak_progress_single_record_cannot_establish_a_rate():
    # The current live state: exactly one pending record on merge-gate-data.
    p = soak_progress([_rec()], target=20)
    assert p["total"] == 1 and p["pending"] == 1 and p["labeled"] == 0
    assert p["velocity_per_day"] is None
    assert p["days_to_target"] is None
    assert p["n_vs_target"] == {"n": 1, "target": 20, "shortfall": 19}


def test_soak_progress_counts_labeled_pending_and_human_audit():
    recs = [
        _rec(change_id="c1"),
        _rec(
            change_id="c2",
            label=True,
            label_source="timeout_clean",
            labeled_at="2026-01-05T00:00:00+00:00",
        ),
        _rec(
            change_id="c3",
            label=False,
            label_source="human_audit",
            labeled_at="2026-01-06T00:00:00+00:00",
        ),
    ]
    p = soak_progress(recs, target=20)
    assert p["total"] == 3 and p["labeled"] == 2 and p["pending"] == 1
    assert p["human_audit"] == 1  # only HUMAN_AUDIT is called out (it alone feeds tau/health)


def test_soak_progress_velocity_and_days_to_target():
    # 5 records spanning 4 days -> 4/4 = 1.0 rec/day; shortfall 15 -> 15 days.
    days = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
    recs = [_rec(change_id=f"c{i}", merged_at=f"{d}T00:00:00+00:00") for i, d in enumerate(days)]
    p = soak_progress(recs, target=20)
    assert p["velocity_per_day"] == pytest.approx(1.0)
    assert p["days_to_target"] == pytest.approx(15.0)


def test_soak_progress_span_under_one_day_has_no_velocity():
    recs = [
        _rec(change_id="c1", merged_at="2026-01-01T00:00:00+00:00"),
        _rec(change_id="c2", merged_at="2026-01-01T06:00:00+00:00"),
    ]
    assert soak_progress(recs, target=20)["velocity_per_day"] is None


def test_soak_progress_ignores_unparseable_merged_at_for_velocity():
    # A bad stamp is dropped from the rate calc (not crashed on); it still counts in total.
    recs = [
        _rec(change_id="c1", merged_at="not-a-timestamp"),
        _rec(change_id="c2", merged_at="2026-01-01T00:00:00+00:00"),
    ]
    p = soak_progress(recs, target=20)
    assert p["velocity_per_day"] is None  # only one parseable stamp remains
    assert p["total"] == 2


def test_soak_progress_z_suffix_merged_at_is_parsed():
    # Regression: a bare datetime.fromisoformat rejects 'Z' before Python 3.11
    # (agent-core CI runs 3.10); _parse_ts must delegate to timeutil.parse_iso8601
    # rather than reintroduce this already-fixed gap on the same field.
    recs = [
        _rec(change_id="c1", merged_at="2026-01-01T00:00:00Z"),
        _rec(change_id="c2", merged_at="2026-01-03T00:00:00Z"),
    ]
    p = soak_progress(recs, target=20)
    assert p["velocity_per_day"] == pytest.approx(0.5)


def test_soak_progress_mixed_naive_and_aware_merged_at_does_not_crash():
    # Regression: sorting naive and timezone-aware datetimes together raises
    # TypeError. A bare datetime.fromisoformat parse of a naive stamp stays naive;
    # parse_iso8601 normalizes it to UTC so the sort in _velocity_per_day never sees
    # a mixed batch. merged_at is an unvalidated free-form string end-to-end
    # (OutcomeRecord.from_json does no normalization), so this input is realistic.
    recs = [
        _rec(change_id="c1", merged_at="2026-01-01T00:00:00+00:00"),  # aware
        _rec(change_id="c2", merged_at="2026-01-02T00:00:00"),  # naive
    ]
    p = soak_progress(recs, target=20)
    assert p["velocity_per_day"] == pytest.approx(1.0)


def test_soak_progress_cold_start_keyed_on_audit_floor_not_a_literal():
    audited = [
        _rec(
            change_id=f"c{i}",
            domain="human/x",
            label=True,
            label_source="human_audit",
            labeled_at="2026-01-02T00:00:00+00:00",
        )
        for i in range(3)
    ]
    assert soak_progress(audited, target=20, audit_floor=3)["per_domain_cold_start"] == {
        "human/x": False
    }
    assert soak_progress(audited, target=20, audit_floor=4)["per_domain_cold_start"] == {
        "human/x": True
    }


def test_soak_progress_default_audit_floor_is_the_audit_config_field():
    rec = [
        _rec(label=True, label_source="human_audit", labeled_at="2026-01-02T00:00:00+00:00"),
    ]
    # one audit, default floor (>1) -> still cold; provenance is the config, not a literal.
    assert soak_progress(rec, target=20)["per_domain_cold_start"] == {"human/agent-core": True}
    assert AuditConfig.per_domain_floor > 1


@given(records=_records_strategy, target=st.integers(min_value=0, max_value=50))
def test_soak_progress_never_mutates_its_input(records, target):
    before = [r.to_json() for r in records]
    n = len(records)
    soak_progress(records, target)
    assert [r.to_json() for r in records] == before
    assert len(records) == n


def test_cli_stats_soak_target_adds_reserved_block_default_unchanged(tmp_path, capsys):
    store = tmp_path / "s.jsonl"
    write_store(store, [_rec()])
    base = ["stats", "--store", str(store)]
    # Default output stays byte-identical to the pre-F-040 stats contract.
    assert main(base) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip()) == {"human/agent-core": {"pending": 1}}
    # --soak-target opts into the reserved _soak block; domain stats are preserved.
    assert main([*base, "--soak-target", "20"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out.strip())
    assert out["human/agent-core"] == {"pending": 1}
    assert out["_soak"]["n_vs_target"] == {"n": 1, "target": 20, "shortfall": 19}
    assert out["_soak"]["velocity_per_day"] is None


def test_cli_stats_audit_floor_overrides_the_config_default(tmp_path, capsys):
    # The live merge-gate-audit.yml workflow runs with a lower operational floor
    # (vars.MERGE_GATE_AUDIT_FLOOR, typically 3) than AuditConfig.per_domain_floor's
    # library default (30) — --audit-floor lets the CLI report match what audit
    # selection is actually enforcing instead of silently over-reporting cold-start.
    store = tmp_path / "s.jsonl"
    audited = [
        _rec(
            change_id=f"c{i}",
            domain="human/x",
            label=True,
            label_source="human_audit",
            labeled_at="2026-01-02T00:00:00+00:00",
        )
        for i in range(3)
    ]
    write_store(store, audited)
    base = ["stats", "--store", str(store), "--soak-target", "20"]
    # Default floor (AuditConfig.per_domain_floor, 30) still reports cold-start at 3 audits.
    assert main(base) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip())["_soak"]["per_domain_cold_start"] == {
        "human/x": True
    }
    # --audit-floor 3 matches the live workflow's floor: 3 audits clears it.
    assert main([*base, "--audit-floor", "3"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip())["_soak"]["per_domain_cold_start"] == {
        "human/x": False
    }


def test_cli_stats_soak_progress_uses_soak_config_default(tmp_path, capsys):
    store = tmp_path / "s.jsonl"
    write_store(store, [_rec()])
    assert effective_soak_target(None, True) == SoakConfig.target_per_domain
    assert effective_soak_target(20, True) == 20  # explicit target wins
    assert effective_soak_target(None, False) is None
    assert main(["stats", "--store", str(store), "--soak-progress"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out.strip())
    assert out["_soak"]["n_vs_target"]["target"] == SoakConfig.target_per_domain
    assert out["_soak"]["remaining_by_domain"]["human/agent-core"] == SoakConfig.target_per_domain
    assert out["_soak"]["human_audit_by_domain"]["human/agent-core"] == 0


def test_soak_progress_remaining_by_domain_counts_human_audit_only():
    recs = [
        _rec(change_id="c1", domain="d1"),
        _rec(
            change_id="c2",
            domain="d1",
            label=True,
            label_source="human_audit",
            labeled_at="2026-01-02T00:00:00+00:00",
        ),
        _rec(
            change_id="c3",
            domain="d2",
            label=True,
            label_source="timeout_clean",
            labeled_at="2026-01-02T00:00:00+00:00",
        ),
    ]
    p = soak_progress(recs, target=5)
    assert p["human_audit_by_domain"] == {"d1": 1, "d2": 0}
    assert p["remaining_by_domain"] == {"d1": 4, "d2": 5}
