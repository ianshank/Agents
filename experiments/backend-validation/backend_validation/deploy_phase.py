"""P1 deploy phase: stand up the stacks, capture ops-burden metrics, or BLOCK.

Kept separate from ``phases.py`` (which owns P0/P2) purely for the 500-line file budget;
it shares the ``PhaseResult``/``PhaseIO`` vocabulary and the same BLOCKED discipline.
"""

from __future__ import annotations

import http.client
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlparse

from backend_validation.deploy import DeployError, deploy_stack, down_stack
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
from backend_validation.settings import Settings

logger = get_logger(__name__)


def http_health_check(base_url: str, *, timeout: float = 5.0) -> bool:
    """A proxy-free loopback GET that treats any HTTP response as 'the app answered'."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.request("GET", parsed.path or "/")
        response = connection.getresponse()
        connection.close()
        return response.status < 500
    except (TimeoutError, OSError, http.client.HTTPException):
        return False


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
    try:
        written = metrics_file.write()
    except MetricsError as exc:
        return PhaseResult("deploy", STATUS_FAIL, f"effort metrics invalid: {exc}")
    return PhaseResult(
        "deploy",
        STATUS_OK,
        f"{len(backend_ids)} stack(s) healthy; ops-burden metrics recorded",
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
    failed = [
        backend_id for backend_id in backend_ids if not down_stack(settings.backend(backend_id), subtree_root, runner)
    ]
    if failed:
        return PhaseResult("down", STATUS_FAIL, f"teardown failed for: {', '.join(failed)}")
    return PhaseResult("down", STATUS_OK, f"tore down {len(backend_ids)} stack(s)")
