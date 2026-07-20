"""Phase orchestration: P0 preflight and P2 L1 probes, with BLOCKED/HALT semantics.

Fail-safe-to-escalate (spec invariant 5): every precondition failure produces a BLOCKED
report file naming what a human must do — never a silent skip, never a synthesized
result. An unexpected negative-control pass HALTs the run (the probe layer or the matrix
is wrong; both demand a human).
"""

from __future__ import annotations

import json
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

from backend_validation import probes as probes_pkg
from backend_validation.clients import MissingCredentialsError, ProbeClient, build_client
from backend_validation.controls import HaltRequiredError, evaluate_expected_fail, halt_if_passed
from backend_validation.logging_util import get_logger
from backend_validation.observables import Observable, ObservableLog
from backend_validation.registry import (
    CellDecl,
    ProbesSpec,
    RegistryError,
    cross_validate,
    load_probes_spec,
    registered_probe_ids,
)
from backend_validation.repetition import k_for
from backend_validation.rubric import RubricError, RubricRules, load_rubric, verify_signoff
from backend_validation.runner import ProbeContext, run_probe, utc_now_iso
from backend_validation.settings import Settings

logger = get_logger(__name__)

STATUS_OK = "OK"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_HALT = "HALT"

EXIT_BY_STATUS = {STATUS_OK: 0, STATUS_FAIL: 1, STATUS_BLOCKED: 3, STATUS_HALT: 4}


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    status: str
    reason: str
    artifacts: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return EXIT_BY_STATUS[self.status]


@dataclass
class PhaseIO:
    """Injectable environment edges so every phase is unit-testable offline."""

    runner_run: Callable[[list[str]], tuple[bool, str]]  # (ok, detail) for a command probe
    disk_free_gb: Callable[[Path], float]
    port_is_free: Callable[[int], bool]
    client_factory: Callable[..., ProbeClient]
    now_fn: Callable[[], str] = utc_now_iso


def default_phase_io(command_runner: object | None = None) -> PhaseIO:
    """Production wiring; tests build their own PhaseIO with fakes."""
    from backend_validation.procrun import CommandRunner, SubprocessRunner

    runner: CommandRunner = command_runner if command_runner is not None else SubprocessRunner()  # type: ignore[assignment]

    def _run(argv: list[str]) -> tuple[bool, str]:
        result = runner.run(argv, timeout=30)
        detail = (result.stdout or result.stderr).strip().splitlines()
        return result.ok, detail[0] if detail else ""

    def _disk_free_gb(path: Path) -> float:
        usage = shutil.disk_usage(path)
        return usage.free / 1_000_000_000

    def _port_is_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    return PhaseIO(
        runner_run=_run,
        disk_free_gb=_disk_free_gb,
        port_is_free=_port_is_free,
        client_factory=build_client,
    )


def write_blocked_report(
    artifacts_dir: Path,
    run_id: str,
    phase: str,
    reasons: list[str],
    human_next_steps: str,
    *,
    now_fn: Callable[[], str] = utc_now_iso,
) -> Path:
    """The single alternative to a silent skip: what failed, evidence, what a human does."""
    target = artifacts_dir / run_id / "blocked_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# BLOCKED — {phase}",
        "",
        f"- generated_utc: {now_fn()}",
        f"- run_id: {run_id}",
        "",
        "## Failed preconditions",
        *[f"- {reason}" for reason in reasons],
        "",
        "## What a human must do",
        human_next_steps,
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


# --------------------------------------------------------------------- P0 preflight
def _structural_validation(subtree_root: Path) -> tuple[ProbesSpec, RubricRules]:
    schema = json.loads((subtree_root / "schemas" / "probes.schema.json").read_text(encoding="utf-8"))
    raw = yaml.safe_load((subtree_root / "PROBES.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(raw, schema)
    spec = load_probes_spec(subtree_root / "PROBES.yaml")
    rules = load_rubric(subtree_root / "RUBRIC.md")
    probes_pkg.load_all()
    problems = cross_validate(spec, registered_probe_ids(), layers=("l1",))
    if problems:
        raise RegistryError("probe-id cross-validation failed: " + "; ".join(problems))
    return spec, rules


def _environment_reasons(settings: Settings, subtree_root: Path, io: PhaseIO) -> list[str]:
    reasons: list[str] = []
    docker_ok, docker_detail = io.runner_run(["docker", "--version"])
    if not docker_ok:
        reasons.append(f"docker is not available: {docker_detail or 'command failed'}")
    compose_ok, compose_detail = io.runner_run(["docker", "compose", "version"])
    if not compose_ok:
        reasons.append(f"docker compose v2 is not available: {compose_detail or 'command failed'}")
    free_gb = io.disk_free_gb(subtree_root)
    if free_gb < settings.min_free_gb:
        reasons.append(f"free disk {free_gb:.1f} GB is below the configured minimum {settings.min_free_gb} GB")
    for port in settings.required_ports:
        if not io.port_is_free(port):
            reasons.append(f"required port {port} is already bound on 127.0.0.1")
    return reasons


def run_preflight(
    subtree_root: Path,
    settings: Settings,
    io: PhaseIO,
    *,
    schema_only: bool = False,
    run_id: str = "preflight",
) -> PhaseResult:
    try:
        spec, rules = _structural_validation(subtree_root)
    except (RegistryError, RubricError, jsonschema.ValidationError, OSError) as exc:
        return PhaseResult("preflight", STATUS_FAIL, f"TCB artifacts failed structural validation: {exc}")
    if schema_only:
        return PhaseResult("preflight", STATUS_OK, "structural validation passed (sign-off not checked)")

    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    reasons: list[str] = []
    signoff = verify_signoff(subtree_root, spec.signoff, rules)
    reasons.extend(signoff.reasons)
    unresolved = spec.unresolved_claims()
    if unresolved:
        cells = ", ".join(f"{cell}/{backend}" for cell, backend in unresolved[:5])
        reasons.append(f"{len(unresolved)} claimed marks still CLAIM_TBD (e.g. {cells}) — transcribe from the matrix")
    reasons.extend(_environment_reasons(settings, subtree_root, io))
    if reasons:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "preflight (P0)",
            reasons,
            "Complete the sign-off procedure at the bottom of RUBRIC.md (correct CLAIM_TBD marks, "
            "set signed_off in both TCB files, write SIGNOFF), and fix any environment findings. "
            "Agents never perform the sign-off.",
            now_fn=io.now_fn,
        )
        return PhaseResult("preflight", STATUS_BLOCKED, reasons[0], artifacts=(str(report),))
    return PhaseResult("preflight", STATUS_OK, "TCB signed and environment ready")


# ------------------------------------------------------------------------- P2 L1
def _run_cell_probe(
    cell: CellDecl,
    probe_id: str,
    backend_id: str,
    settings: Settings,
    client: ProbeClient,
    log: ObservableLog,
    io: PhaseIO,
    run_id: str,
) -> list[Observable]:
    collected: list[Observable] = []
    for rep_index in range(k_for(cell.repetition)):
        ctx = ProbeContext(
            backend_id=backend_id,
            run_marker=f"{run_id}-{probe_id.replace('.', '-')}-r{rep_index}",
            rep_index=rep_index,
            judge=settings.judge,
            control_endpoint=settings.control_endpoint,
        )
        collected.extend(
            run_probe(probe_id, cell.id, client, ctx, settings.timeouts, settings.retries, log=log, now_fn=io.now_fn)
        )
    return collected


def _run_synthetic_controls(
    spec: ProbesSpec,
    backend_id: str,
    settings: Settings,
    client: ProbeClient,
    log: ObservableLog,
    io: PhaseIO,
    run_id: str,
) -> None:
    for control in spec.controls.synthetic:
        if backend_id not in control.applies_to:
            continue
        ctx = ProbeContext(
            backend_id=backend_id,
            run_marker=f"{run_id}-control-r0",
            judge=settings.judge,
            control_endpoint=settings.control_endpoint,
        )
        observables = run_probe(
            control.probe_id,
            "controls.synthetic",
            client,
            ctx,
            settings.timeouts,
            settings.retries,
            log=log,
            now_fn=io.now_fn,
        )
        outcome = evaluate_expected_fail(control.probe_id, backend_id, control.expected_observables, observables)
        halt_if_passed(outcome)


def run_l1(
    subtree_root: Path,
    settings: Settings,
    io: PhaseIO,
    *,
    run_id: str,
    only_backend: str | None = None,
) -> PhaseResult:
    try:
        spec, _rules = _structural_validation(subtree_root)
    except (RegistryError, RubricError, jsonschema.ValidationError, OSError) as exc:
        return PhaseResult("l1", STATUS_FAIL, f"TCB artifacts failed structural validation: {exc}")
    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    log = ObservableLog(artifacts_dir / run_id / "observables.jsonl")
    backend_ids = [spec_backend.id for spec_backend in settings.backends]
    if only_backend is not None:
        backend_ids = [backend_id for backend_id in backend_ids if backend_id == only_backend]
        if not backend_ids:
            return PhaseResult("l1", STATUS_FAIL, f"backend {only_backend!r} is not configured")
    total = 0
    try:
        for backend_id in backend_ids:
            total += _run_backend_l1(spec, backend_id, settings, log, io, run_id)
    except MissingCredentialsError as exc:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "l1 (P2)",
            [str(exc)],
            "Export the named credential env vars (copy .env.example to .env.local and fill it).",
            now_fn=io.now_fn,
        )
        return PhaseResult("l1", STATUS_BLOCKED, str(exc), artifacts=(str(report),))
    except HaltRequiredError as exc:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "l1 (P2) — negative controls",
            [str(exc)],
            "Either the matrix claim for this cell is wrong (a finding!) or the probe layer is "
            "broken. Review the observables JSONL next to this report before ANY further runs.",
            now_fn=io.now_fn,
        )
        return PhaseResult("l1", STATUS_HALT, str(exc), artifacts=(str(report), str(log.path)))
    return PhaseResult(
        "l1",
        STATUS_OK,
        f"{total} observables recorded across {len(backend_ids)} backend(s)",
        artifacts=(str(log.path),),
    )


def _run_backend_l1(
    spec: ProbesSpec,
    backend_id: str,
    settings: Settings,
    log: ObservableLog,
    io: PhaseIO,
    run_id: str,
) -> int:
    backend_spec = settings.backend(backend_id)
    client = io.client_factory(backend_spec, judge=settings.judge, op_timeout=settings.timeouts.op_seconds)
    count = 0
    try:
        # Controls FIRST (spec P2 gate): a broken probe layer must halt before any
        # pass-expectation evidence is collected.
        _run_synthetic_controls(spec, backend_id, settings, client, log, io, run_id)
        for cell in spec.cells:
            for probe in cell.probes:
                if probe.expectation.get(backend_id) != "fail":
                    continue
                observables = _run_cell_probe(cell, probe.probe_id, backend_id, settings, client, log, io, run_id)
                outcome = evaluate_expected_fail(probe.probe_id, backend_id, probe.expected_observables, observables)
                halt_if_passed(outcome)
                count += len(observables)
        for cell in spec.cells:
            if cell.classification not in ("api-probeable", "config-probeable"):
                continue  # human-only/doc-only cells are never probed (spec R2)
            for probe in cell.probes:
                if probe.expectation.get(backend_id) != "pass":
                    continue
                count += len(_run_cell_probe(cell, probe.probe_id, backend_id, settings, client, log, io, run_id))
    finally:
        client.close()
    logger.info("l1[%s]: %d observables", backend_id, count)
    return count
