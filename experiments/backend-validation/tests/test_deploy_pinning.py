"""Unit tests for the M2 pinning reach: Dockerfile FROM lines + air-gap overlays.

`tests/test_deploy.py` owns the compose-file pinning suite; THIS file owns everything the
peer review added on top — `_FROM_LINE`/`pin_dockerfile` and the pin-digests CLI walking
overlays + the prober Dockerfile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation import cli
from backend_validation.deploy import _FROM_LINE, DeployError, pin_compose_file, pin_dockerfile
from backend_validation.procrun import CompletedCommand, SubprocessRunner

_DIGEST = "sha256:" + "c" * 64
_MANIFEST = f'{{"Descriptor": {{"digest": "{_DIGEST}"}}}}'
_PINNED_REF = "python:3.11-slim@sha256:" + "a" * 64


class ManifestRunner:
    """Every `docker manifest inspect` resolves to the canned digest; records argv."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
        self.calls.append(list(argv))
        return CompletedCommand(tuple(argv), 0, stdout=_MANIFEST)


# ------------------------------------------------------------------- _FROM_LINE
def test_from_line_matches_the_shapes_that_matter() -> None:
    match = _FROM_LINE.match("FROM python:3.11-slim@TODO_PIN")
    assert match and match.group("ref") == "python:3.11-slim@TODO_PIN"
    lowered = _FROM_LINE.match("from ubuntu:24.04")
    assert lowered and lowered.group("ref") == "ubuntu:24.04"
    staged = _FROM_LINE.match("FROM golang:1.22 AS builder")
    assert staged and staged.group("ref") == "golang:1.22" and staged.group("suffix") == " AS builder"
    platformed = _FROM_LINE.match("FROM --platform=linux/amd64 alpine:3.20")
    assert platformed and platformed.group("ref") == "alpine:3.20"
    assert _FROM_LINE.match("COPY . .") is None
    assert _FROM_LINE.match("# FROM commented out") is None


# ---------------------------------------------------------------- pin_dockerfile
def _dockerfile(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Dockerfile"
    path.write_text(body, encoding="utf-8")
    return path


def test_pin_dockerfile_rewrites_only_unpinned_from_lines(tmp_path: Path) -> None:
    path = _dockerfile(
        tmp_path,
        f"# comment survives\nFROM python:3.11-slim@TODO_PIN\nFROM {_PINNED_REF}\nCOPY pyproject.toml .\n",
    )
    runner = ManifestRunner()
    pinned = pin_dockerfile(path, runner)
    assert pinned == [("python:3.11-slim", _DIGEST)]  # only the TODO line resolved
    body = path.read_text(encoding="utf-8")
    assert f"FROM python:3.11-slim@{_DIGEST}\n" in body
    assert _PINNED_REF in body  # already-pinned line untouched
    assert "# comment survives" in body and "COPY pyproject.toml ." in body


def test_pin_dockerfile_preserves_multistage_as_suffix(tmp_path: Path) -> None:
    path = _dockerfile(tmp_path, "FROM golang:1.22 AS builder\n")
    pinned = pin_dockerfile(path, ManifestRunner())
    assert pinned == [("golang:1.22", _DIGEST)]
    assert path.read_text(encoding="utf-8") == f"FROM golang:1.22@{_DIGEST} AS builder\n"


def test_pin_dockerfile_no_op_when_everything_is_pinned(tmp_path: Path) -> None:
    body = f"FROM {_PINNED_REF}\n"
    path = _dockerfile(tmp_path, body)
    runner = ManifestRunner()
    assert pin_dockerfile(path, runner) == []
    assert path.read_text(encoding="utf-8") == body  # not rewritten
    assert runner.calls == []  # registry never consulted


def test_pin_dockerfile_propagates_registry_failure(tmp_path: Path) -> None:
    path = _dockerfile(tmp_path, "FROM python:3.11-slim@TODO_PIN\n")

    class NoRegistry:
        def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), 1, stderr="no route to registry")

    with pytest.raises(DeployError, match="manifest inspect failed"):
        pin_dockerfile(path, NoRegistry())


# ------------------------------------------------------------- overlay pinning
_OVERLAY_WITH_RESET = """networks:
  bv-internal:
    internal: true
services:
  web:
    ports: !reset []
  bv-dns-witness:
    image: coredns/coredns:1.12.1@TODO_PIN
"""


def test_pin_compose_file_pins_overlay_and_preserves_reset_tag(tmp_path: Path) -> None:
    # pin_compose_file is line-based BY DESIGN: an overlay's `!reset` tag (which
    # yaml.safe_load cannot even parse) passes through untouched while images pin.
    path = tmp_path / "compose.airgap.yaml"
    path.write_text(_OVERLAY_WITH_RESET, encoding="utf-8")
    pinned = pin_compose_file(path, ManifestRunner())
    assert pinned == [("coredns/coredns:1.12.1", _DIGEST)]
    body = path.read_text(encoding="utf-8")
    assert f"coredns/coredns:1.12.1@{_DIGEST}" in body
    assert "ports: !reset []" in body


# ------------------------------------------------------------- pin-digests CLI
def test_pin_digests_cli_covers_overlays_and_prober_dockerfile(
    tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "SUBTREE_ROOT", tmp_subtree)

    class ManifestSubprocess(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), 0, stdout=_MANIFEST)

    monkeypatch.setattr(cli, "SubprocessRunner", ManifestSubprocess)
    overlay = tmp_subtree / "deploy" / "langfuse" / "compose.airgap.yaml"
    overlay.write_text(_OVERLAY_WITH_RESET, encoding="utf-8")
    # The committed prober Dockerfile ships pinned; recreate the marker so the
    # Dockerfile branch has work to do.
    (tmp_subtree / "deploy" / "prober" / "Dockerfile").write_text("FROM python:3.11-slim@TODO_PIN\n", encoding="utf-8")
    code = cli.main(["pin-digests", "--config", str(tmp_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 0 and "backend-validation[pin-digests]: OK" in out
    # The overlay's witness image and the prober's FROM line were both reached (M2).
    assert f"coredns/coredns:1.12.1@{_DIGEST}" in overlay.read_text(encoding="utf-8")
    assert "!reset" in overlay.read_text(encoding="utf-8")
    dockerfile = (tmp_subtree / "deploy" / "prober" / "Dockerfile").read_text(encoding="utf-8")
    assert f"FROM python:3.11-slim@{_DIGEST}" in dockerfile
    assert "FROM python:3.11-slim@TODO_PIN" not in dockerfile  # (comments may still say TODO_PIN)
    assert f"pinned coredns/coredns:1.12.1 -> {_DIGEST}" in out
    assert f"pinned python:3.11-slim -> {_DIGEST}" in out


def test_pin_digests_cli_fails_when_only_the_dockerfile_needs_the_registry(
    tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Pre-pin every compose the handler walks so ONLY the prober Dockerfile still needs
    # the registry: an unreachable registry then fails from the Dockerfile branch.
    monkeypatch.setattr(cli, "SUBTREE_ROOT", tmp_subtree)
    for name in ("langfuse", "opik", "judge"):
        (tmp_subtree / "deploy" / name / "compose.yaml").write_text(
            f"services:\n  s:\n    image: img@sha256:{'a' * 64}\n", encoding="utf-8"
        )
        (tmp_subtree / "deploy" / name / "compose.airgap.yaml").unlink(missing_ok=True)
    (tmp_subtree / "deploy" / "prober" / "Dockerfile").write_text("FROM python:3.11-slim@TODO_PIN\n", encoding="utf-8")

    class NoRegistry(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=1, stderr="no route to registry")

    monkeypatch.setattr(cli, "SubprocessRunner", NoRegistry)
    code = cli.main(["pin-digests", "--config", str(tmp_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 1
    assert "backend-validation[pin-digests]: FAIL" in out and "manifest inspect failed" in out


def test_pin_digests_cli_skips_absent_overlays_and_dockerfile(
    tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No compose.airgap.yaml anywhere in the tmp tree and no prober Dockerfile: both
    # extensions contribute nothing and the command still succeeds (skip-if-absent,
    # never a crash on a pre-overlay tree).
    monkeypatch.setattr(cli, "SUBTREE_ROOT", tmp_subtree)
    (tmp_subtree / "deploy" / "prober" / "Dockerfile").unlink()

    class ManifestSubprocess(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), 0, stdout=_MANIFEST)

    monkeypatch.setattr(cli, "SubprocessRunner", ManifestSubprocess)
    code = cli.main(["pin-digests", "--config", str(tmp_subtree / "config.yaml")])
    assert code == 0
    assert "backend-validation[pin-digests]: OK" in capsys.readouterr().out


def test_pin_dockerfile_skips_multistage_stage_references(tmp_path: Path) -> None:
    # `FROM base` names the earlier stage — resolving it against a registry would fail
    # on a nonexistent image; only real image refs are pinned.
    path = _dockerfile(
        tmp_path,
        "FROM python:3.11-slim@TODO_PIN AS base\nFROM base AS runtime\nCOPY . .\n",
    )
    runner = ManifestRunner()
    pinned = pin_dockerfile(path, runner)
    assert pinned == [("python:3.11-slim", _DIGEST)]
    body = path.read_text(encoding="utf-8")
    assert f"FROM python:3.11-slim@{_DIGEST} AS base\n" in body
    assert "FROM base AS runtime\n" in body  # untouched


def test_pin_dockerfile_pins_a_stage_whose_alias_equals_its_image_name(tmp_path: Path) -> None:
    # `FROM alpine AS alpine`: the line's OWN alias must not satisfy the prior-stage
    # check, or a real registry image silently escapes pinning (CodeRabbit review;
    # dockerfile_pinned uses the same check-before-register order).
    path = _dockerfile(tmp_path, "FROM alpine AS alpine\nFROM alpine AS runtime\n")
    pinned = pin_dockerfile(path, ManifestRunner())
    assert pinned == [("alpine", _DIGEST)]  # first line resolved; second is a prior-stage ref
    body = path.read_text(encoding="utf-8")
    assert f"FROM alpine@{_DIGEST} AS alpine\n" in body
    assert "FROM alpine AS runtime\n" in body  # references the stage, untouched
