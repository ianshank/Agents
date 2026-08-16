"""P1 deploy phase: stand up the stacks, capture ops-burden metrics, or BLOCK.

Kept separate from ``phases.py`` (which owns P0/P2) purely for the 500-line file budget;
it shares the ``PhaseResult``/``PhaseIO`` vocabulary and the same BLOCKED discipline.
"""

from __future__ import annotations

import http.client
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from backend_validation.airgap_phase import airgap_project_name
from backend_validation.deploy import (
    DeployError,
    DeployOutcome,
    compose_argv,
    deploy_stack,
    down_stack,
    project_name,
)
from backend_validation.logging_util import get_logger
from backend_validation.metrics import EffortMetricsFile, MetricsError, metrics_from_outcome
from backend_validation.phases import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_OK,
    PhaseResult,
    write_blocked_report,
)
from backend_validation.procrun import CommandRunner, SubprocessRunner
from backend_validation.settings import BackendSpec, Settings

logger = get_logger(__name__)

# The judge stack's compose project; its spec lives on settings.judge (not a backend).
JUDGE_ID = "judge"
# The single service in deploy/judge/compose.yaml; the post-health model pull execs here.
_JUDGE_OLLAMA_SERVICE = "ollama"
# The shared EXTERNAL network every compose file attaches (server-side evaluators inside
# backend containers dial the judge over it). `external: true` means compose refuses to
# `up` while it is absent and never removes it on `down` — both ends live here.
JUDGE_NETWORK = "bv-judge-net"


def ensure_judge_network(runner: CommandRunner) -> None:
    """Idempotently create ``bv-judge-net`` BEFORE any stack comes up.

    All three compose files declare it ``external: true``, so an ``up`` without it fails
    hard. "Already exists" is success; any other create failure raises ``DeployError``
    (-> BLOCKED) rather than letting every subsequent ``up`` fail with a worse message.
    """
    result = runner.run(["docker", "network", "create", JUDGE_NETWORK], timeout=60)
    if result.ok or "already exists" in (result.stderr or "").lower():
        return
    raise DeployError(
        f"cannot create the shared judge network {JUDGE_NETWORK}: {(result.stderr or result.stdout).strip()[:200]}"
    )


def http_health_check(base_url: str, *, timeout: float = 5.0) -> bool:
    """A proxy-free loopback GET that treats any HTTP response as 'the app answered'."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Use a TLS connection for https endpoints; plaintext HTTPConnection to a TLS port
    # would always fail the health check even against a healthy stack.
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    try:
        connection = connection_class(host, port, timeout=timeout)
        connection.request("GET", parsed.path or "/")
        response = connection.getresponse()
        connection.close()
        return response.status < 500
    except (TimeoutError, OSError, http.client.HTTPException):
        return False


def _judge_spec(settings: Settings) -> BackendSpec:
    """The judge stack shaped as a BackendSpec so ``deploy_stack``'s whole flow (digest
    gate, mount containment, ``up -d --wait``, health polling) is reused verbatim.

    ``id="judge"`` yields project ``bv-judge``; health is the app answering on
    ``judge.base_url`` (Ollama returns a non-5xx for ``/v1`` once it is serving).
    """
    return BackendSpec(
        id=JUDGE_ID,
        display_name="Local judge (Ollama)",
        base_url=settings.judge.base_url,
        compose_file=settings.judge.compose_file,
        sdk_extra="",
    )


def deploy_judge(
    settings: Settings,
    subtree_root: Path,
    runner: CommandRunner,
    *,
    env: Mapping[str, str],
    health_check: Callable[[str], bool],
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> DeployOutcome:
    """Deploy the judge stack, then pull the pinned model into its named volume (M6a).

    Judge-class cells on EVERY backend dial this stack, so a healthy-but-empty Ollama
    would turn every judge probe into a false negative — the pull is part of the deploy,
    its wall-clock folded into the setup metric (spec R9), and a failed pull raises
    ``DeployError`` (-> BLOCKED) rather than leaving a silently modelless judge.
    """
    outcome = deploy_stack(
        _judge_spec(settings),
        settings,
        subtree_root,
        runner,
        env=env,
        health_check=health_check,
        clock=clock,
        sleeper=sleeper,
    )
    compose_path = subtree_root / settings.judge.compose_file
    pull_started = clock()
    pull = runner.run(
        compose_argv(
            compose_path, JUDGE_ID, "exec", "-T", _JUDGE_OLLAMA_SERVICE, "ollama", "pull", settings.judge.model
        ),
        env=dict(env),
        timeout=3600,
    )
    if not pull.ok:
        raise DeployError(
            f"judge model pull failed (`ollama pull {settings.judge.model}` rc={pull.returncode}, "
            f"timed_out={pull.timed_out}): {(pull.stderr or pull.stdout).strip()[:400]}"
        )
    return replace(outcome, setup_wall_clock_seconds=outcome.setup_wall_clock_seconds + (clock() - pull_started))


def run_deploy(
    subtree_root: Path,
    settings: Settings,
    *,
    env: Mapping[str, str],
    run_id: str,
    only_backend: str | None = None,
    runner: CommandRunner | None = None,
    health_check: Callable[[str], bool] = http_health_check,
    clock: Callable[[], float] = time.perf_counter,
    sleeper: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], str],
    stats_samples: int = 3,
    stats_interval_seconds: float = 2.0,
) -> PhaseResult:
    runner = runner if runner is not None else SubprocessRunner()
    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    reports_dir = settings.resolve_dir("reports_dir", subtree_root)
    backend_ids = [spec.id for spec in settings.backends]
    if only_backend is not None:
        backend_ids = [backend_id for backend_id in backend_ids if backend_id == only_backend]
        if not backend_ids:
            return PhaseResult("deploy", STATUS_FAIL, f"backend {only_backend!r} is not configured")

    try:
        ensure_judge_network(runner)
    except DeployError as exc:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "deploy (P1) — shared judge network",
            [str(exc)],
            "Docker refused to create the shared bv-judge-net network every stack attaches; "
            "check the daemon/network state and re-run `make deploy`.",
            now_fn=now_fn,
        )
        return PhaseResult("deploy", STATUS_BLOCKED, str(exc), artifacts=(str(report),))

    metrics_file = EffortMetricsFile(
        path=reports_dir / "effort_metrics.json",
        schema_path=subtree_root / "schemas" / "effort_metrics.schema.json",
    )
    for backend_id in backend_ids:
        spec = settings.backend(backend_id)
        try:
            outcome = deploy_stack(
                spec,
                settings,
                subtree_root,
                runner,
                env=env,
                health_check=health_check,
                clock=clock,
                sleeper=sleeper,
            )
            metrics_file.record(
                metrics_from_outcome(
                    outcome,
                    runner,
                    started_utc=now_fn(),
                    stats_samples=stats_samples,
                    stats_interval_seconds=stats_interval_seconds,
                    sleeper=sleeper,
                )
            )
        except DeployError as exc:
            report = write_blocked_report(
                artifacts_dir,
                run_id,
                f"deploy (P1) — {backend_id}",
                [str(exc)],
                "Resolve the deployment finding above (pin digests with `make pin-digests`, set "
                "missing .env.local secrets, or free resources) and re-run `make deploy`.",
                now_fn=now_fn,
            )
            return PhaseResult("deploy", STATUS_BLOCKED, str(exc), artifacts=(str(report),))
    # The judge is a shared fixture (judge-class cells on every backend dial it), so it
    # deploys regardless of --backend filtering, with the same digest gate and metrics.
    try:
        judge_outcome = deploy_judge(
            settings,
            subtree_root,
            runner,
            env=env,
            health_check=health_check,
            clock=clock,
            sleeper=sleeper,
        )
        metrics_file.record(
            metrics_from_outcome(
                judge_outcome,
                runner,
                started_utc=now_fn(),
                stats_samples=stats_samples,
                stats_interval_seconds=stats_interval_seconds,
                sleeper=sleeper,
            )
        )
    except DeployError as exc:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "deploy (P1) — judge",
            [str(exc)],
            "Resolve the judge-stack finding above (pin digests with `make pin-digests`, or check the "
            "Ollama model name/network for the pull) and re-run `make deploy` — judge-class cells on "
            "every backend need this stack.",
            now_fn=now_fn,
        )
        return PhaseResult("deploy", STATUS_BLOCKED, str(exc), artifacts=(str(report),))
    try:
        written = metrics_file.write()
    except MetricsError as exc:
        return PhaseResult("deploy", STATUS_FAIL, f"effort metrics invalid: {exc}")
    return PhaseResult(
        "deploy",
        STATUS_OK,
        f"{len(backend_ids)} backend stack(s) + judge healthy; ops-burden metrics recorded",
        artifacts=(str(written),),
    )


def run_down(
    subtree_root: Path,
    settings: Settings,
    *,
    runner: CommandRunner | None = None,
    only_backend: str | None = None,
) -> PhaseResult:
    runner = runner if runner is not None else SubprocessRunner()
    backend_ids = [spec.id for spec in settings.backends]
    if only_backend is not None:
        backend_ids = [backend_id for backend_id in backend_ids if backend_id == only_backend]
    specs = [settings.backend(backend_id) for backend_id in backend_ids]
    if only_backend is None:
        # The judge deploys with the full fleet (run_deploy), so a full `down` tears it
        # down too; a --backend-scoped down leaves the shared judge alone.
        specs.append(_judge_spec(settings))
    failed = [spec.id for spec in specs if not down_stack(spec, subtree_root, runner)]
    # Best-effort removal of the shared judge network (external: compose never removes
    # it). Failure is expected and ignored when containers are still attached after a
    # failed teardown, a --backend-scoped down, or when the network never existed.
    runner.run(["docker", "network", "rm", JUDGE_NETWORK], timeout=60)
    if failed:
        return PhaseResult("down", STATUS_FAIL, f"teardown failed for: {', '.join(failed)}")
    return PhaseResult("down", STATUS_OK, f"tore down {len(specs)} stack(s)")


def run_status(
    subtree_root: Path,  # unused today; kept for phase-signature symmetry across run_* entrypoints
    settings: Settings,
    *,
    runner: CommandRunner | None = None,
) -> PhaseResult:
    """Read-only container inventory across every experiment compose project.

    Purely informational (no evidence produced, no blocked_report.md): an empty project
    is a normal answer, not a failure — but a missing/dead docker is still BLOCKED (exit
    3), never an argparse error or a fake `0 containers` reading.
    """
    runner = runner if runner is not None else SubprocessRunner()
    probe = runner.run(["docker", "--version"], timeout=30)
    if not probe.ok:
        detail = (probe.stderr or probe.stdout).strip().splitlines()
        return PhaseResult(
            "status", STATUS_BLOCKED, f"docker is not available: {detail[0] if detail else 'command failed'}"
        )
    projects = [project_name(spec.id) for spec in settings.backends]
    projects.append(project_name(JUDGE_ID))
    projects.extend(airgap_project_name(spec.id) for spec in settings.backends)
    counts: list[str] = []
    for project in projects:
        listing = runner.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Names}}\t{{.Status}}",
            ],
            timeout=60,
        )
        if not listing.ok:
            return PhaseResult(
                "status",
                STATUS_BLOCKED,
                f"docker ps failed for {project}: {(listing.stderr or listing.stdout).strip()[:200]}",
            )
        running = [line for line in listing.stdout.splitlines() if line.strip()]
        counts.append(f"{project}: {len(running)} container(s)")
    return PhaseResult("status", STATUS_OK, "; ".join(counts))
