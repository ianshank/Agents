#!/usr/bin/env python3
"""Tests for scripts/agent_confidence.py — agent identity + confidence proxy (F-042, ADR 0023)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import agent_confidence as ac
import pytest
import yaml
from check_protected_changes import ConfigError
from hypothesis import given
from hypothesis import strategies as st

_ROOT = Path(ac.__file__).resolve().parent.parent

_IDENTITY = {
    "schema_version": "1.0.0",
    "agents": [
        {"agent_version": "claude-code", "branch_prefixes": ["claude/"], "author_logins": []},
        {
            "agent_version": "devin",
            "branch_prefixes": ["devin/"],
            "author_logins": ["devin-ai-integration[bot]"],
        },
    ],
}

_PROXY = {
    "schema_version": "1.0.0",
    "proxy": {
        "base": 1.5,
        "w_size": 2.0,
        "w_files": 1.0,
        "w_tests": 1.0,
        "w_protected": 2.0,
        "size_scale": 400.0,
        "size_cap": 3.0,
        "files_scale": 20.0,
        "files_cap": 3.0,
        "clamp_lo": 0.02,
        "clamp_hi": 0.98,
    },
    "test_globs": ["tests/**", "**/test_*.py"],
}


def _write(tmp_path: Path, name: str, doc: object) -> str:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(p)


def _proxy_cfg(tmp_path: Path, **overrides: object) -> ac.ProxyConfig:
    doc = copy.deepcopy(_PROXY)
    doc["proxy"].update(overrides)  # type: ignore[attr-defined]
    return ac.ProxyConfig.load(_write(tmp_path, "proxy.yaml", doc))


# --- identity: load + validation --------------------------------------------
def test_identity_load_valid(tmp_path):
    ident = ac.AgentIdentity.load(_write(tmp_path, "id.yaml", _IDENTITY))
    assert ident.agents[0] == ac.AgentRule("claude-code", ("claude/",), ())
    assert ident.agents[1].author_logins == ("devin-ai-integration[bot]",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d.pop("agents"),
        lambda d: d.update(schema_version="9.0.0"),
        lambda d: d.update(agents="nope"),
        lambda d: d.update(agents=[]),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": ["x/"]}]),  # missing key
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": ["x/"], "author_logins": [], "z": 1}]),
        lambda d: d.update(agents=[{"agent_version": "", "branch_prefixes": ["x/"], "author_logins": []}]),
        lambda d: d.update(
            agents=[
                {"agent_version": "dup", "branch_prefixes": ["a/"], "author_logins": []},
                {"agent_version": "dup", "branch_prefixes": ["b/"], "author_logins": []},
            ]
        ),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": [123], "author_logins": []}]),
        lambda d: d.update(agents=[{"agent_version": "x", "branch_prefixes": [], "author_logins": []}]),
    ],
)
def test_identity_load_rejects_invalid(tmp_path, mutate):
    doc = copy.deepcopy(_IDENTITY)
    mutate(doc)
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(_write(tmp_path, "id.yaml", doc))


def test_identity_load_unreadable(tmp_path):
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(str(tmp_path / "missing.yaml"))


def test_identity_load_not_mapping(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        ac.AgentIdentity.load(str(p))


# --- identity: resolve ------------------------------------------------------
@pytest.mark.parametrize(
    "head_ref,login,expected",
    [
        ("claude/foo-bar", "ianshank", "claude-code"),  # prefix wins, login ignored
        ("devin/x", "", "devin"),
        ("", "devin-ai-integration[bot]", "devin"),  # login match when no ref
        ("feat/x", "ianshank", None),  # human
        ("fix/y", "", None),
        ("", "", None),
    ],
)
def test_identity_resolve(tmp_path, head_ref, login, expected):
    ident = ac.AgentIdentity.load(_write(tmp_path, "id.yaml", _IDENTITY))
    assert ident.resolve(head_ref, login) == expected


# --- proxy: load + validation -----------------------------------------------
def test_proxy_load_valid(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    assert cfg.base == 1.5
    assert cfg.test_globs == ("tests/**", "**/test_*.py")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(schema_version="2.0.0"),
        lambda d: d.update(proxy="nope"),
        lambda d: d["proxy"].pop("base"),
        lambda d: d["proxy"].update(surprise=1),
        lambda d: d["proxy"].update(base="not-a-number"),
        lambda d: d["proxy"].update(size_scale=0),
        lambda d: d["proxy"].update(files_scale=-1),
        lambda d: d["proxy"].update(clamp_lo=0.0),  # must be > 0
        lambda d: d["proxy"].update(clamp_lo=0.9, clamp_hi=0.9),  # lo < hi
        lambda d: d["proxy"].update(clamp_hi=1.0),  # must be < 1
        lambda d: d.update(test_globs=[]),
        lambda d: d.update(test_globs=[123]),
    ],
)
def test_proxy_load_rejects_invalid(tmp_path, mutate):
    doc = copy.deepcopy(_PROXY)
    mutate(doc)
    with pytest.raises(ConfigError):
        ac.ProxyConfig.load(_write(tmp_path, "proxy.yaml", doc))


# --- proxy: compute_confidence ----------------------------------------------
def test_confidence_deterministic(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    a = ac.compute_confidence(["src/a.py", "tests/test_a.py"], 120, cfg)
    b = ac.compute_confidence(["src/a.py", "tests/test_a.py"], 120, cfg)
    assert a == b


def test_confidence_strictly_inside_unit_interval(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    for files, lines in [(["a.py"], 1), ([f"s/{i}.py" for i in range(40)], 9000), (["tests/test_x.py"], 30)]:
        c = ac.compute_confidence(files, lines, cfg)
        assert 0.0 < c < 1.0
        assert cfg.clamp_lo <= c <= cfg.clamp_hi


def test_confidence_varies_with_inputs(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    small = ac.compute_confidence(["src/a.py"], 20, cfg)
    big = ac.compute_confidence([f"src/{i}.py" for i in range(30)], 4000, cfg)
    assert small != big


def test_confidence_monotonic_in_size(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    small = ac.compute_confidence(["src/a.py"], 10, cfg)
    large = ac.compute_confidence(["src/a.py"], 2500, cfg)
    assert large < small


def test_confidence_tests_raise_it(tmp_path):
    """Adding a test must raise the score -- against the REAL protected-path classifier.

    This test previously monkeypatched ``matched_protected`` to False, with the comment
    "many test dirs (tests/**) are also protected paths in this repo, so hold
    touches_protected fixed to compare cleanly". That patch is exactly what hid F-061: it
    proved a counterfactual (what the score WOULD do if tests were not protected) while the
    real composed behaviour was the opposite -- adding a test halved the score. The patch is
    deleted on purpose; a test that passes only by switching off the condition that would
    falsify it is not evidence.
    """
    cfg = _proxy_cfg(tmp_path)
    files = ["pkg/a.py", "tests/test_a.py"]
    with_tests = ac.compute_confidence(files, 100, cfg, added=["tests/test_a.py"])
    without = ac.compute_confidence(["pkg/a.py", "pkg/b.py"], 100, cfg)
    assert with_tests > without


def test_modifying_an_existing_test_still_carries_the_protected_penalty(tmp_path):
    """The Goodhart hole stays shut: weakening an eval-defining test is not rewarded.

    Withholding *added* tests from the protected signal must not withhold *modified* ones --
    otherwise "modify only an eval-defining test" becomes the highest-confidence class in
    the system, which is precisely the failure scripts/fix_loop.py exists to name.
    """
    cfg = _proxy_cfg(tmp_path)
    files = ["tests/test_gating.py"]
    modified = ac.compute_confidence(files, 50, cfg, added=[])
    legacy = ac.compute_confidence(files, 50, cfg)
    assert modified == legacy, "a modified test must score exactly as it did before F-061"

    added_instead = ac.compute_confidence(files, 50, cfg, added=["tests/test_gating.py"])
    assert added_instead > modified, "adding that same file must score strictly higher"


def test_added_set_unknown_is_bit_identical_to_legacy(tmp_path):
    """``added=None`` is the backwards-compatibility contract, not merely a default.

    Every stored record and every caller that cannot distinguish additions from
    modifications must keep its exact pre-F-061 value.
    """
    cfg = _proxy_cfg(tmp_path)
    for files, lines in (
        (["src/a.py", "tests/test_a.py"], 100),
        (["tests/test_gating.py"], 50),
        (["src/a.py", "src/b.py"], 100),
        (["config/x.yaml"], 5),
        ([], 0),
    ):
        assert ac.compute_confidence(files, lines, cfg, added=None) == ac.compute_confidence(files, lines, cfg)


def test_added_non_test_file_does_not_dodge_the_protected_penalty(tmp_path):
    """Only added *tests* are withheld. A newly added protected non-test still counts."""
    cfg = _proxy_cfg(tmp_path)
    files = ["config/agent-confidence.yaml"]
    assert ac.compute_confidence(files, 20, cfg, added=list(files)) == ac.compute_confidence(files, 20, cfg)


# The committed config carries four test globs; the shared fixture carries only two, so a
# fixture-only test never exercises `**/tests/**` or `**/*_test.py`. Withholding only moves the
# score when the path is ALSO eval-protected: `src/pkg/test_a.py` matches a test glob but no
# protected pattern, so its score is correctly unchanged.
@pytest.mark.parametrize(
    ("test_path", "protected"),
    [
        ("tests/test_a.py", True),
        ("agent-core/tests/test_a.py", True),
        ("flow-corpus/tests/thing_test.py", True),
        ("src/pkg/test_a.py", False),
        ("src/pkg/a_test.py", False),
    ],
)
def test_added_test_withheld_for_every_committed_glob(tmp_path, test_path, protected):
    """Every glob in the committed config -- not just the two the fixture carries."""
    doc = copy.deepcopy(_PROXY)
    doc["test_globs"] = ["tests/**", "**/tests/**", "**/test_*.py", "**/*_test.py"]
    cfg = ac.ProxyConfig.load(_write(tmp_path, "proxy.yaml", doc))
    files = ["src/pkg/a.py", test_path]
    with_added = ac.compute_confidence(files, 100, cfg, added=[test_path])
    legacy = ac.compute_confidence(files, 100, cfg)
    if protected:
        assert with_added > legacy, f"{test_path} is protected; withholding it must raise the score"
    else:
        assert with_added == legacy, f"{test_path} is not protected; withholding it is a no-op"


# `tests/conftest.py` is deliberate: it is eval-protected but matches NO raw test glob in the
# fixture, so these cases can only pass if the path is normalised BEFORE classification. An
# earlier version of this test used `tests/test_a.py`, which matches `**/test_*.py` raw --
# so it passed via the glob and never exercised normalisation at all.
@pytest.mark.parametrize("spelling", ["./tests/conftest.py", "tests\\conftest.py", "/tests/conftest.py"])
def test_added_paths_are_normalised_before_classification(tmp_path, spelling):
    """A non-canonical spelling of an added test must still be withheld."""
    cfg = _proxy_cfg(tmp_path)
    files = ["pkg/a.py", "tests/conftest.py"]
    canonical = ac.compute_confidence(files, 100, cfg, added=["tests/conftest.py"])
    assert ac.compute_confidence(files, 100, cfg, added=[spelling]) == canonical


@pytest.mark.parametrize("spelling", ["./tests/conftest.py", "tests\\conftest.py"])
def test_non_canonical_spellings_in_files_are_normalised_too(tmp_path, spelling):
    """The *files* side is normalised as well -- otherwise the set lookup misses."""
    cfg = _proxy_cfg(tmp_path)
    canonical = ac.compute_confidence(["pkg/a.py", "tests/conftest.py"], 100, cfg, added=["tests/conftest.py"])
    assert ac.compute_confidence(["pkg/a.py", spelling], 100, cfg, added=["tests/conftest.py"]) == canonical


def test_added_paths_absent_from_files_are_a_no_op(tmp_path):
    """`added` entries not present in `files` must not change the outcome."""
    cfg = _proxy_cfg(tmp_path)
    files = ["pkg/a.py", "src/eval_harness/gating/x.py"]
    assert ac.compute_confidence(files, 50, cfg, added=["tests/unrelated_test.py"]) == (
        ac.compute_confidence(files, 50, cfg)
    )


def test_empty_files_with_non_empty_added(tmp_path):
    """Degenerate but reachable: no changed files, a non-empty added list."""
    cfg = _proxy_cfg(tmp_path)
    c = ac.compute_confidence([], 0, cfg, added=["tests/test_a.py"])
    assert cfg.clamp_lo <= c <= cfg.clamp_hi


def test_committed_config_acceptance_numbers(tmp_path):
    """Pins the three acceptance rows against the REAL committed weights.

    A regression in either direction -- adding tests stops being rewarded, or modifying one
    stops being penalised -- fails here with the actual numbers in the message.
    """
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    add_test = ac.compute_confidence(["src/a.py", "tests/test_a.py"], 100, cfg, added=["tests/test_a.py"])
    no_test = ac.compute_confidence(["src/a.py", "src/b.py"], 100, cfg)
    modify_test = ac.compute_confidence(["tests/test_gating.py"], 50, cfg, added=[])

    assert add_test > no_test, f"adding a test must beat not adding one ({add_test} vs {no_test})"
    assert modify_test < no_test, f"modifying an eval test must stay penalised ({modify_test})"


def test_confidence_protected_lowers_it(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path)
    monkeypatch.setattr(ac, "matched_protected", lambda files: [])
    clean = ac.compute_confidence(["x/a.py"], 100, cfg)
    monkeypatch.setattr(ac, "matched_protected", lambda files: list(files))
    protected = ac.compute_confidence(["x/a.py"], 100, cfg)
    assert protected < clean


def test_confidence_large_change_clamps_to_floor(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path)
    monkeypatch.setattr(ac, "matched_protected", lambda files: list(files))
    c = ac.compute_confidence([f"s/{i}.py" for i in range(50)], 9000, cfg)
    assert c == cfg.clamp_lo


def test_confidence_clamps_to_ceiling(tmp_path, monkeypatch):
    cfg = _proxy_cfg(tmp_path, base=12.0)  # forces sigmoid ~ 1.0
    monkeypatch.setattr(ac, "matched_protected", lambda files: [])
    c = ac.compute_confidence(["tests/test_a.py"], 1, cfg)
    assert c == cfg.clamp_hi


def test_confidence_empty_change(tmp_path):
    cfg = _proxy_cfg(tmp_path)
    c = ac.compute_confidence([], 0, cfg)
    assert 0.0 < c < 1.0


# --- committed configs are valid + wired ------------------------------------
def test_repo_configs_load_and_resolve_claude():
    ident = ac.AgentIdentity.load(str(_ROOT / "config" / "agent-authors.yaml"))
    assert ident.resolve("claude/agent-calibration-gap", "ianshank") == "claude-code"
    assert ident.resolve("fix/whatever", "ianshank") is None
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    assert 0.0 < ac.compute_confidence(["agent-core/x.py"], 200, cfg) < 1.0


# --- CLI --------------------------------------------------------------------
def test_cli_agent_path(tmp_path, capsys):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    rc = ac.main(
        [
            "--files",
            "src/a.py",
            "--lines-changed",
            "80",
            "--head-ref",
            "claude/x",
            "--identity-config",
            idp,
            "--proxy-config",
            pp,
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["agent"] is True
    assert out["agent_version"] == "claude-code"
    assert 0.0 < out["confidence"] < 1.0


def test_cli_human_path(tmp_path, capsys):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    rc = ac.main(["--files", "src/a.py", "--head-ref", "feat/x", "--identity-config", idp, "--proxy-config", pp])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"agent": False, "agent_version": None, "confidence": None}


def test_cli_files_from_and_output(tmp_path):
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    files_z = tmp_path / "files.z"
    files_z.write_bytes(b"agent-core/a.py\x00tests/test_a.py\x00")
    out = tmp_path / "out.json"
    rc = ac.main(
        [
            "--files-from",
            str(files_z),
            "--lines-changed",
            "60",
            "--head-ref",
            "claude/y",
            "--identity-config",
            idp,
            "--proxy-config",
            pp,
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["agent"] is True and payload["agent_version"] == "claude-code"


def test_cli_config_error_exits_2(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("agents: []\nschema_version: '1.0.0'\n", encoding="utf-8")
    rc = ac.main(["--head-ref", "claude/x", "--identity-config", str(bad)])
    assert rc == 2


def test_confidence_extreme_config_no_overflow(tmp_path):
    # Output contract under extreme (mis)configured base: result stays within [clamp_lo, clamp_hi]
    # and never OverflowErrors. The lower z-clamp is the load-bearing guard (base=-1e9 -> exp(+big)
    # would overflow without it); base=+1e9 merely underflows exp(-big) to 0 (upper clamp is
    # defensive symmetry, so removing it leaves the output unchanged — tested via the contract).
    hi = _proxy_cfg(tmp_path, base=1e9)
    assert ac.compute_confidence(["a.py"], 10, hi) == hi.clamp_hi
    lo = _proxy_cfg(tmp_path, base=-1e9)
    assert ac.compute_confidence(["a.py"], 10, lo) == lo.clamp_lo


def test_cli_agent_empty_files_is_config_error(tmp_path):
    # An agent change that resolves no files -> exit 2 (undeterminable file set), not a bogus seed.
    idp = _write(tmp_path, "id.yaml", _IDENTITY)
    pp = _write(tmp_path, "proxy.yaml", _PROXY)
    rc = ac.main(["--head-ref", "claude/x", "--identity-config", idp, "--proxy-config", pp])
    assert rc == 2


# --- property-based invariants ------------------------------------------------
# These must hold at ANY weights, so a future retune cannot quietly break them. Example
# counts come from the dev/ci Hypothesis profiles registered in tests/conftest.py -- never
# hard-coded here.

_PATH = st.sampled_from(
    [
        "src/a.py",
        "src/b.py",
        "pkg/mod.py",
        "tests/test_a.py",
        "tests/test_b.py",
        "agent-core/tests/test_c.py",
        "config/x.yaml",
        "features.yaml",
        "docs/readme.md",
    ]
)
_FILES = st.lists(_PATH, min_size=0, max_size=12, unique=True)


@given(files=_FILES, lines=st.integers(min_value=0, max_value=100_000))
def test_property_output_always_within_clamp_bounds(files, lines):
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    for added in (None, [], list(files)):
        c = ac.compute_confidence(files, lines, cfg, added=added)
        assert cfg.clamp_lo <= c <= cfg.clamp_hi
        assert 0.0 < c < 1.0


@given(files=_FILES, lines=st.integers(min_value=0, max_value=100_000))
def test_property_added_none_equals_legacy(files, lines):
    """The backwards-compatibility contract, over arbitrary inputs."""
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    assert ac.compute_confidence(files, lines, cfg, added=None) == ac.compute_confidence(files, lines, cfg)


@given(
    files=_FILES,
    small=st.integers(min_value=0, max_value=500),
    delta=st.integers(min_value=1, max_value=50_000),
)
def test_property_monotonic_decreasing_in_size(files, small, delta):
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    a = ac.compute_confidence(files, small, cfg)
    b = ac.compute_confidence(files, small + delta, cfg)
    assert b <= a


@given(files=_FILES)
def test_property_declaring_additions_never_lowers_the_score(files):
    """Withholding added tests can only remove a penalty, never add one.

    This is the invariant that stops a future refactor from turning the F-061 fix into a
    penalty by some other route: knowing MORE about a change must never score it worse.
    """
    cfg = ac.ProxyConfig.load(str(_ROOT / "config" / "agent-confidence.yaml"))
    unknown = ac.compute_confidence(files, 100, cfg, added=None)
    all_added = ac.compute_confidence(files, 100, cfg, added=list(files))
    assert all_added >= unknown


def test_added_from_error_names_its_own_flag(tmp_path, caplog):
    """A bad --added-from must not send an operator to --files-from.

    `read_nul_delimited` hardcoded the flag name in its message; both options share it, so a
    diagnostic-only input failed with the wrong option named. The flag is now a parameter.
    """
    files_z = tmp_path / "f.z"
    files_z.write_bytes(b"src/a.py\0")
    rc = ac.main(
        [
            "--files-from",
            str(files_z),
            "--added-from",
            str(tmp_path / "missing.z"),
            "--lines-changed",
            "10",
            "--head-ref",
            "claude/x",
            "--identity-config",
            str(_ROOT / "config" / "agent-authors.yaml"),
            "--proxy-config",
            str(_ROOT / "config" / "agent-confidence.yaml"),
        ]
    )
    assert rc == ac.EXIT_CONFIG
    assert any("--added-from" in r.message for r in caplog.records), caplog.text
    assert not any("--files-from" in r.message for r in caplog.records), caplog.text
