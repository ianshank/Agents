"""Fixture replay: envelope round-trip, archive confinement, target modes, CLI, slices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval_harness.cli import build_parser
from eval_harness.cli import main as cli_main
from eval_harness.core._paths import DATA_ROOT_ENV, OUTPUT_ROOT_ENV
from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    RunContext,
    ScoreResult,
    TargetOutput,
    TrajectoryStep,
)
from eval_harness.plugins import SCORERS, TARGETS, bootstrap
from eval_harness.replay.archive import ReplayArchive
from eval_harness.replay.cli import (
    items_from_envelopes,
    parse_overrides,
    parse_overrides_mapping,
    parse_tag_filter,
    run_replay,
)
from eval_harness.replay.envelope import (
    ReplayConfig,
    ReplayEnvelope,
    ReplayError,
    canonical_hash,
    envelope_from_dict,
    envelope_to_dict,
    state_snapshot_from_dict,
    trajectory_from_dict,
)
from eval_harness.replay.report import (
    failing_steps,
    first_failing_step,
    format_pass_rate,
    render_html,
    render_text,
)
from eval_harness.replay.slice import global_pass_rate, pass_rate_delta, pass_rates_by_tag, tags_of
from eval_harness.replay.target import ReplayTarget, apply_counterfactual
from tests._trajectory_helpers import call, final, observation, tool_call, tool_error, trajectory


def _envelope(**kwargs: object) -> ReplayEnvelope:
    defaults: dict[str, object] = {
        "envelope_id": "e1",
        "recorded_run_id": "r1",
        "item_id": "i1",
        "recorded_at": "2026-09-14T00:00:00+00:00",
        "environment": "offline",
        "agent_version": "v1",
        "input_hash": canonical_hash({"q": "x"}),
        "output_hash": canonical_hash("ok"),
        "trajectory": trajectory(tool_call("search", {"q": "x"}), observation("hit", name="search"), final("ok")),
        "output": "ok",
        "tags": {"freshness": "normal"},
    }
    defaults.update(kwargs)
    return ReplayEnvelope(**defaults)  # type: ignore[arg-type]


def test_envelope_round_trip_is_strict() -> None:
    original = _envelope()
    restored = envelope_from_dict(envelope_to_dict(original))
    assert restored == original


def test_envelope_unknown_key_raises() -> None:
    payload = envelope_to_dict(_envelope())
    payload["otel_span"] = "nope"
    with pytest.raises(ReplayError, match="unknown keys"):
        envelope_from_dict(payload)


def test_canonical_hash_is_stable_across_equal_payloads() -> None:
    left = canonical_hash({"a": 1, "b": [2, 3]})
    right = canonical_hash({"b": [2, 3], "a": 1})
    assert left == right
    assert left != hex(id({"a": 1}))


def test_archive_write_refuses_output_root_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setenv(OUTPUT_ROOT_ENV, str(root))
    with pytest.raises(ValueError, match=r"\.\."):
        ReplayArchive(root / ".." / "escape.jsonl", for_write=True)


def test_archive_append_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "env.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    loaded = ReplayArchive(path).load()
    assert len(loaded) == 1
    assert loaded[0].item_id == "i1"


def test_corrupt_jsonl_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="corrupt JSONL"):
        ReplayArchive(path).load()


def test_first_failing_step_is_the_earliest_tool_error() -> None:
    traj = trajectory(tool_call("search"), observation("x", name="search"), tool_error("fetch", "stale"), final("ok"))
    step = first_failing_step(traj, item_id="i")
    assert step is not None
    assert step.index == 2
    assert step.tool_name == "fetch"


def test_first_failing_step_none_without_tool_error() -> None:
    assert first_failing_step(trajectory(final("ok"))) is None


def test_exact_replay_is_idempotent() -> None:
    bootstrap()
    env = _envelope()
    target = ReplayTarget(envelopes=[env], mode="exact")
    item = EvalItem(
        id="i1",
        inputs={},
        expected={"tool_calls": [{"name": "search", "arguments": {"q": "x"}}]},
    )
    first = target.run(item)
    second = target.run(item)
    assert first.trajectory == second.trajectory == env.trajectory
    scorer = SCORERS.create("trajectory_in_order", {})
    ctx = RunContext(config=None)
    assert scorer.score(item, first, ctx).passed is True
    assert scorer.score(item, second, ctx).passed is True


def test_counterfactual_changes_only_tagged_search_observation() -> None:
    sensitive = _envelope(item_id="s", tags={"freshness": "sensitive"})
    normal = _envelope(item_id="n", tags={"freshness": "normal"})
    target = ReplayTarget(
        envelopes=[sensitive, normal],
        mode="counterfactual",
        overrides={"search": "error:stale_index"},
        override_tag_key="freshness",
        override_tag_value="sensitive",
    )
    out_s = target.run(EvalItem(id="s", inputs={}))
    out_n = target.run(EvalItem(id="n", inputs={}))
    assert out_s.trajectory is not None
    assert any(step.kind == "tool_error" for step in out_s.trajectory.steps)
    assert out_n.trajectory == normal.trajectory


def test_missing_envelope_degrades_to_error() -> None:
    out = ReplayTarget(envelopes=[], mode="exact").run(EvalItem(id="missing", inputs={}))
    assert out.error is not None
    assert out.trajectory is None


def test_invalid_mode_raises() -> None:
    with pytest.raises(ReplayError, match="invalid replay mode"):
        ReplayTarget(envelopes=[], mode="shadow")


def test_from_span_skips_overrides_before_index() -> None:
    env = _envelope()
    target = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "error:late"},
        from_span="99",
    )
    out = target.run(EvalItem(id="i1", inputs={}))
    assert out.trajectory == env.trajectory


def test_slice_hides_a_tag_regression() -> None:
    bootstrap()
    sensitive = _envelope(item_id="s", tags={"freshness": "sensitive"})
    normal = _envelope(item_id="n", tags={"freshness": "normal"})
    target = ReplayTarget(
        envelopes=[sensitive, normal],
        mode="counterfactual",
        overrides={"search": "error:stale"},
        override_tag_value="sensitive",
    )
    items = items_from_envelopes([sensitive, normal])
    ctx = RunContext(config=None)
    scorer = SCORERS.create("trajectory_recovery", {})
    results = []
    for item in items:
        output = target.run(item)
        results.append(ItemResult(item=item, output=output, scores=[scorer.score(item, output, ctx)]))
    passed, n, rate = global_pass_rate(results)
    assert n == 2
    assert rate == 0.5
    slices = {row.tag_value: row.pass_rate for row in pass_rates_by_tag(results, "freshness")}
    assert slices["sensitive"] == 0.0
    assert slices["normal"] == 1.0
    assert passed == 1


def test_parse_overrides_and_cli_help() -> None:
    assert parse_overrides(["tool.search=stale"]) == {"search": "stale"}
    parser = build_parser()
    args = parser.parse_args(["replay", "--archive", "demo/replay/baseline.jsonl", "--mode", "exact", "--offline"])
    assert args.command == "replay"
    assert args.mode == "exact"
    with pytest.raises(SystemExit) as exc:
        cli_main(["replay", "--help"])
    assert exc.value.code == 0


def test_cli_replay_exact_on_temp_archive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "baseline.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    html = tmp_path / "replay.html"
    args = build_parser().parse_args(
        ["replay", "--archive", str(path), "--mode", "exact", "--html", str(html), "--offline"]
    )
    assert run_replay(args) == 0
    captured = capsys.readouterr()
    assert "pass_rate=" in captured.out
    assert html.is_file()
    assert "first tool_error" in html.read_text(encoding="utf-8")


def test_registered_replay_target_name() -> None:
    bootstrap()
    assert "replay" in TARGETS.names()


def test_trajectory_from_dict_rejects_bad_kind() -> None:
    with pytest.raises(ReplayError, match="unknown step kind"):
        trajectory_from_dict({"schema_version": "1.0.0", "steps": [{"kind": "span"}]})


def test_archive_read_refuses_data_root_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV, str(root))
    with pytest.raises(ValueError, match=r"\.\."):
        ReplayArchive(root / ".." / "escape.jsonl")


def test_archive_last_item_id_wins(tmp_path: Path) -> None:
    path = tmp_path / "dup.jsonl"
    first = _envelope(item_id="same", output="one")
    second = _envelope(item_id="same", envelope_id="e2", output="two")
    ReplayArchive(path, for_write=True).append([first, second])
    assert ReplayArchive(path).by_item_id()["same"].output == "two"


def test_archive_append_requires_write_mode(tmp_path: Path) -> None:
    path = tmp_path / "env.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    with pytest.raises(ReplayError, match="cannot append"):
        ReplayArchive(path).append([_envelope()])


def test_optional_envelope_fields_round_trip() -> None:
    from eval_harness.core.types import StateSnapshot

    original = _envelope(
        prompt_version="p1",
        model_id="mock",
        model_parameters_hash="abc",
        dependency_snapshot_id="dep",
        state_before=StateSnapshot(data={"k": "v"}),
        state_after=StateSnapshot(data={"k": "after"}),
        payload_refs={"blob": "ref://x"},
    )
    restored = envelope_from_dict(envelope_to_dict(original))
    assert restored == original


def test_envelope_missing_required_key_raises() -> None:
    payload = envelope_to_dict(_envelope())
    del payload["item_id"]
    with pytest.raises(ReplayError, match="missing required key"):
        envelope_from_dict(payload)


def test_replay_config_rejects_negative_digits() -> None:
    with pytest.raises(ReplayError, match="pass_rate_digits"):
        ReplayConfig(pass_rate_digits=-1)


def test_from_span_by_tool_name() -> None:
    env = _envelope()
    target = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "error:late"},
        from_span="search",
    )
    out = target.run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    assert any(step.kind == "tool_error" for step in out.trajectory.steps)


def test_unknown_from_span_is_a_scored_error() -> None:
    env = _envelope()
    target = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "error:late"},
        from_span="missing-span",
    )
    out = target.run(EvalItem(id="i1", inputs={}))
    assert out.error is not None
    assert out.trajectory == env.trajectory


def test_callable_override_uses_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST", "demo")
    env = _envelope()
    target = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "demo.replay_stubs:search_v2"},
    )
    out = target.run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    obs = [step.content for step in out.trajectory.steps if step.kind == "tool_observation"]
    assert obs and str(obs[0]).startswith("STALE:")


def test_pass_rate_delta_and_format() -> None:
    left = pass_rates_by_tag([], "freshness")
    right = pass_rates_by_tag([], "freshness")
    assert pass_rate_delta(left, right) == ()
    assert format_pass_rate(None) == "n/a"
    assert format_pass_rate(0.5, digits=2) == "0.50"


def test_cli_json_and_bad_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "baseline.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    json_out = tmp_path / "summary.json"
    args = build_parser().parse_args(
        ["replay", "--archive", str(path), "--mode", "exact", "--json", str(json_out), "--offline"]
    )
    assert run_replay(args) == 0
    payload = json_out.read_text(encoding="utf-8")
    assert "pass_rate" in payload
    bad = build_parser().parse_args(["replay", "--archive", str(path), "--override", "nope", "--offline"])
    assert run_replay(bad) == 2
    captured = capsys.readouterr()
    assert "ERROR" in captured.err


def test_parse_tag_filter_and_empty_override() -> None:
    assert parse_tag_filter(None) == (None, "")
    with pytest.raises(ReplayError, match="tag=value"):
        parse_tag_filter("freshness")
    with pytest.raises(ReplayError, match="empty"):
        parse_overrides(["tool.=x"])


def test_demo_baseline_is_committed() -> None:
    baseline = Path(__file__).resolve().parent.parent / "demo" / "replay" / "baseline.jsonl"
    assert baseline.is_file()
    assert "replay-00" in baseline.read_text(encoding="utf-8")


def test_demo_baseline_regenerates_byte_identically(tmp_path: Path) -> None:
    from demo.replay_fixtures import write_baseline

    committed = Path(__file__).resolve().parent.parent / "demo" / "replay" / "baseline.jsonl"
    generated = write_baseline(tmp_path / "baseline.jsonl")
    assert generated.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")


def test_replay_config_rejects_invalid_mode() -> None:
    with pytest.raises(ReplayError, match="invalid replay mode"):
        ReplayConfig(mode="shadow")  # type: ignore[arg-type]


def test_envelope_constructor_rejects_unknown_schema_version() -> None:
    with pytest.raises(ReplayError, match="unsupported envelope schema_version"):
        _envelope(schema_version="9.9.9")


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("nope", "envelope must be a mapping"),
        ({"schema_version": "2.0.0", "envelope_id": "e"}, "unsupported envelope schema_version"),
        (
            {
                "envelope_id": 1,
                "recorded_run_id": "r",
                "item_id": "i",
                "recorded_at": "t",
                "environment": "e",
                "agent_version": "v",
                "input_hash": "h",
                "output_hash": "h",
                "trajectory": {"schema_version": "1.0.0", "steps": []},
            },
            "must be a string",
        ),
        (
            {
                **envelope_to_dict(_envelope()),
                "output_metadata": [],
            },
            "output_metadata must be a mapping",
        ),
        ({**envelope_to_dict(_envelope()), "tags": ["x"]}, "tags must be a mapping"),
        ({**envelope_to_dict(_envelope()), "tags": {1: "x"}}, "keys and values must be strings"),
    ],
)
def test_envelope_from_dict_rejects_malformed_payloads(payload: object, match: str) -> None:
    with pytest.raises(ReplayError, match=match):
        envelope_from_dict(payload)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("nope", "trajectory payload must be a mapping"),
        ({"schema_version": "0.0.1", "steps": []}, "unsupported trajectory schema_version"),
        ({"schema_version": "1.0.0", "steps": {}}, "trajectory.steps must be a list"),
        ({"schema_version": "1.0.0", "steps": ["x"]}, "trajectory step must be a mapping"),
        (
            {"schema_version": "1.0.0", "steps": [{"kind": "final", "extra": 1}]},
            "unknown keys",
        ),
        (
            {"schema_version": "1.0.0", "steps": [{"kind": "final", "timestamp_ms": 1.5}]},
            "timestamp_ms must be an int",
        ),
        (
            {"schema_version": "1.0.0", "steps": [{"kind": "final", "metadata": []}]},
            "step metadata must be a mapping",
        ),
        (
            {
                "schema_version": "1.0.0",
                "steps": [{"kind": "tool_call", "tool_call": "search"}],
            },
            "tool_call must be a mapping",
        ),
        (
            {
                "schema_version": "1.0.0",
                "steps": [{"kind": "tool_call", "tool_call": {"name": ""}}],
            },
            "non-empty string",
        ),
        (
            {
                "schema_version": "1.0.0",
                "steps": [{"kind": "tool_call", "tool_call": {"name": "s", "arguments": []}}],
            },
            "arguments must be a mapping",
        ),
        (
            {
                "schema_version": "1.0.0",
                "steps": [{"kind": "tool_call", "tool_call": {"name": "s", "call_id": 1}}],
            },
            "call_id must be a string",
        ),
        (
            {
                "schema_version": "1.0.0",
                "steps": [{"kind": "tool_call", "tool_call": {"name": "s", "span": "x"}}],
            },
            "unknown keys",
        ),
    ],
)
def test_trajectory_from_dict_rejects_malformed_payloads(payload: object, match: str) -> None:
    with pytest.raises(ReplayError, match=match):
        trajectory_from_dict(payload)


def test_trajectory_from_dict_accepts_call_id() -> None:
    restored = trajectory_from_dict(
        {
            "schema_version": "1.0.0",
            "steps": [{"kind": "tool_call", "tool_call": {"name": "s", "call_id": "c1"}}],
        }
    )
    assert restored.steps[0].tool_call is not None
    assert restored.steps[0].tool_call.call_id == "c1"


def test_state_snapshot_from_dict_rejects_malformed_payloads() -> None:
    with pytest.raises(ReplayError, match="state snapshot must be a mapping"):
        state_snapshot_from_dict("x")
    with pytest.raises(ReplayError, match="unknown keys"):
        state_snapshot_from_dict({"data": {}, "extra": 1})
    with pytest.raises(ReplayError, match="data must be a mapping"):
        state_snapshot_from_dict({"data": []})
    assert state_snapshot_from_dict(None) is None


def test_archive_skips_blank_lines_and_wraps_invalid_envelopes(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    good = json.dumps(envelope_to_dict(_envelope()), sort_keys=True)
    path.write_text(f"\n{good}\n\n{{}}\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="invalid envelope"):
        ReplayArchive(path).load()
    blank_only = tmp_path / "blank.jsonl"
    blank_only.write_text(f"\n{good}\n\n", encoding="utf-8")
    loaded = ReplayArchive(blank_only).load()
    assert len(loaded) == 1


def test_archive_directory_read_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "not-a-file.jsonl"
    path.mkdir()
    with pytest.raises(ReplayError, match="could not read"):
        ReplayArchive(path).load()


def test_replay_target_loads_archive_and_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "env.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    target = ReplayTarget(archive=str(path), mode="exact")
    assert target.is_deterministic() is True
    out = target.run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    assert out.error is None


def test_replay_target_without_archive_is_a_scored_error() -> None:
    out = ReplayTarget(mode="exact").run(EvalItem(id="x", inputs={}))
    assert out.error is not None
    assert "archive" in out.error


def test_empty_override_tool_name_on_target_raises() -> None:
    with pytest.raises(ReplayError, match="override tool name is empty"):
        ReplayTarget(envelopes=[_envelope()], overrides={"tool.": "x"})


def test_literal_override_without_colon_replaces_observation() -> None:
    env = _envelope()
    out = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "NEW_OBS"},
    ).run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    obs = [step.content for step in out.trajectory.steps if step.kind == "tool_observation"]
    assert obs == ["NEW_OBS"]


def test_from_span_by_metadata_span_id() -> None:
    search = call("search", {"q": "x"})
    env = _envelope(
        trajectory=trajectory(
            TrajectoryStep(kind="tool_call", tool_call=search, metadata={"span_id": "s1"}),
            TrajectoryStep(kind="tool_observation", tool_call=search, content="hit"),
            final("ok"),
        )
    )
    out = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "error:late"},
        from_span="s1",
    ).run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    assert any(step.kind == "tool_error" for step in out.trajectory.steps)


def test_apply_counterfactual_skips_non_observation_steps() -> None:
    search = call("search", {"q": "x"})
    traj = trajectory(
        TrajectoryStep(kind="tool_call", tool_call=search),
        TrajectoryStep(kind="tool_observation", tool_call=search, content="hit"),
        final("ok"),
    )
    rebuilt = apply_counterfactual(traj, {"search": "error:x"})
    assert rebuilt.steps[0].kind == "tool_call"
    assert rebuilt.steps[1].kind == "tool_error"


def test_unmatched_override_leaves_recorded_observations() -> None:
    env = _envelope()
    out = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"fetch": "error:x"},
    ).run(EvalItem(id="i1", inputs={}))
    assert out.trajectory == env.trajectory


def test_envelope_omits_none_output() -> None:
    original = _envelope(output=None)
    payload = envelope_to_dict(original)
    assert "output" not in payload
    assert envelope_from_dict(payload).output is None


def test_non_callable_override_is_a_scored_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST", "demo")
    env = _envelope()
    out = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "demo.replay_stubs:NOT_CALLABLE"},
    ).run(EvalItem(id="i1", inputs={}))
    assert out.error is not None
    assert "not callable" in out.error


def test_callable_override_stringifies_non_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST", "demo")
    env = _envelope()
    out = ReplayTarget(
        envelopes=[env],
        mode="counterfactual",
        overrides={"search": "demo.replay_stubs:search_count"},
    ).run(EvalItem(id="i1", inputs={}))
    assert out.trajectory is not None
    obs = [step.content for step in out.trajectory.steps if step.kind == "tool_observation"]
    assert obs == ["7"]


def test_parse_overrides_mapping_and_empty_override_when() -> None:
    assert parse_overrides_mapping({"tool.search": "v"}) == {"search": "v"}
    assert parse_tag_filter("freshness=sensitive") == ("freshness", "sensitive")
    with pytest.raises(ReplayError, match="tag key is empty"):
        parse_tag_filter("=sensitive")


def test_cli_reports_archive_and_override_when_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = build_parser().parse_args(["replay", "--archive", str(tmp_path / "missing.jsonl"), "--offline"])
    assert run_replay(missing) == 2
    bad_when = build_parser().parse_args(
        ["replay", "--archive", str(tmp_path / "missing.jsonl"), "--override-when", "=x", "--offline"]
    )
    assert run_replay(bad_when) == 2
    captured = capsys.readouterr()
    assert "ERROR" in captured.err


def test_cli_main_dispatches_replay(tmp_path: Path) -> None:
    path = tmp_path / "baseline.jsonl"
    ReplayArchive(path, for_write=True).append([_envelope()])
    assert cli_main(["replay", "--archive", str(path), "--mode", "exact", "--offline"]) == 0


def _scored(
    item_id: str,
    tags: Any,
    *,
    passed: bool | None,
    score_name: str = "trajectory_recovery",
    trajectory: Any = None,
    error: str | None = None,
) -> ItemResult:
    item = EvalItem(id=item_id, inputs={}, metadata={"replay_tags": tags})
    output = TargetOutput(output="ok", error=error, trajectory=trajectory)
    scores = [ScoreResult(name=score_name, value=1.0, passed=passed)]
    return ItemResult(item=item, output=output, scores=scores)


def test_slice_skips_missing_verdicts_and_non_mapping_tags() -> None:
    skipped = _scored("a", {"freshness": "normal"}, passed=None)
    other = _scored("b", {"freshness": "normal"}, passed=True, score_name="other")
    bad_tags = _scored("c", "not-a-map", passed=True)
    assert pass_rates_by_tag([skipped, other], "freshness") == ()
    assert tags_of(bad_tags) == {}
    untagged = pass_rates_by_tag([bad_tags], "freshness")
    assert len(untagged) == 1
    assert untagged[0].tag_value == ""
    passed, n, rate = global_pass_rate([skipped, other, bad_tags])
    assert (passed, n, rate) == (1, 1, 1.0)


def test_pass_rate_delta_on_real_rows() -> None:
    baseline = pass_rates_by_tag([_scored("s", {"freshness": "sensitive"}, passed=True)], "freshness")
    candidate = pass_rates_by_tag([_scored("s", {"freshness": "sensitive"}, passed=False)], "freshness")
    extra = pass_rates_by_tag([_scored("n", {"freshness": "normal"}, passed=True)], "freshness")
    dropped = pass_rate_delta(baseline, candidate)
    assert dropped[0].delta == -1.0
    unmatched = pass_rate_delta(baseline, extra)
    assert all(row.delta is None for row in unmatched)


def test_report_renders_failing_steps_without_tool_name() -> None:
    traj = trajectory(TrajectoryStep(kind="tool_error", content="boom"), final("ok"))
    result = _scored("i", {"freshness": "sensitive"}, passed=False, trajectory=traj)
    no_traj = _scored("j", {}, passed=True, error="missing", trajectory=None)
    text = render_text([result, no_traj])
    assert "first_failing_step:" in text
    assert "<unknown>" in text
    html = render_html([result, no_traj])
    assert "tool_error" in html
    assert "(no trajectory)" in html
    found = failing_steps([result, no_traj])
    assert len(found) == 1
    assert found[0].tool_name is None


def test_step_path_includes_tool_error_without_call() -> None:
    traj = trajectory(TrajectoryStep(kind="tool_error", content="boom"), final("ok"))
    html = render_html([_scored("i", {}, passed=False, trajectory=traj)])
    assert "tool_error(tool)" in html
    empty = render_html([_scored("e", {}, passed=True, trajectory=trajectory(TrajectoryStep(kind="model_decision")))])
    assert "(no tools)" in empty
