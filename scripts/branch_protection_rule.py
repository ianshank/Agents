"""Classic branch-protection rule payload (ADR 0037).

Check-context *names* are never literals here: callers pass the derived
enablement set. Operator tunables (admin bypass, review count, force-push)
live on ``ProtectionRuleConfig`` so call sites do not restated numeric defaults.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

ApplyRunner = Callable[[Sequence[str], str], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ProtectionRuleConfig:
    """Classic-rule knobs. Documented defaults are the single-maintainer posture."""

    #: Require the PR branch to be up to date with the base. ADR 0037 does not.
    require_up_to_date: bool = False
    #: ``True`` is GitHub's "Do not allow bypassing the above settings".
    #: Default ``False``: a flake with one maintainer and no review path is an
    #: outage. Record whichever way this is set (ADR 0037 forbids leaving it implicit).
    enforce_admins: bool = False
    #: Zero approvals: require a pull request without the CODEOWNERS deadlock.
    required_approving_review_count: int = 0
    require_code_owner_reviews: bool = False
    dismiss_stale_reviews: bool = False
    allow_force_pushes: bool = False
    allow_deletions: bool = False
    required_conversation_resolution: bool = False
    required_linear_history: bool = False
    block_creations: bool = False
    lock_branch: bool = False
    allow_fork_syncing: bool = False


@dataclass(frozen=True)
class ProtectionApplyConfig:
    """How to talk to GitHub. Timeouts belong here, not at the ``run`` call site."""

    branch: str = "main"
    gh_command: str = "gh"
    timeout_s: float = 30.0
    protection_api: str = "repos/{owner}/{repo}/branches/{branch}/protection"


def build_protection_payload(
    contexts: Sequence[str],
    cfg: ProtectionRuleConfig | None = None,
) -> dict[str, Any]:
    """PUT body for ``/branches/{branch}/protection``. Empty context set is an error."""
    conf = cfg or ProtectionRuleConfig()
    ordered = tuple(sorted({str(name) for name in contexts if str(name).strip()}))
    if not ordered:
        raise ValueError("required-check set is empty")
    return {
        "required_status_checks": {
            "strict": conf.require_up_to_date,
            "contexts": list(ordered),
            "checks": [{"context": name} for name in ordered],
        },
        "enforce_admins": conf.enforce_admins,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": conf.dismiss_stale_reviews,
            "require_code_owner_reviews": conf.require_code_owner_reviews,
            "required_approving_review_count": conf.required_approving_review_count,
        },
        "restrictions": None,
        "required_linear_history": conf.required_linear_history,
        "allow_force_pushes": conf.allow_force_pushes,
        "allow_deletions": conf.allow_deletions,
        "block_creations": conf.block_creations,
        "required_conversation_resolution": conf.required_conversation_resolution,
        "lock_branch": conf.lock_branch,
        "allow_fork_syncing": conf.allow_fork_syncing,
    }


def payload_json(payload: Mapping[str, Any]) -> str:
    """Stable serialisation for ``gh api --input`` and golden tests."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _default_apply_runner(cfg: ProtectionApplyConfig) -> ApplyRunner:
    def run(args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [cfg.gh_command, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=cfg.timeout_s,
            check=False,
        )

    return run


def apply_protection_rule(
    owner: str,
    repo: str,
    payload: Mapping[str, Any],
    *,
    cfg: ProtectionApplyConfig | None = None,
    runner: ApplyRunner | None = None,
) -> tuple[bool, str | None]:
    """PUT the classic rule. ``(False, err)`` on HTTP/tool failure — never raises for 403.

    An agent token without admin cannot enable protection; the caller must treat
    a false return as "not enabled", not as success.
    """
    conf = cfg or ProtectionApplyConfig()
    run = runner or _default_apply_runner(conf)
    api = conf.protection_api.format(owner=owner, repo=repo, branch=conf.branch)
    checks = payload.get("required_status_checks")
    n_checks = 0
    if isinstance(checks, Mapping):
        ctx = checks.get("contexts")
        n_checks = len(ctx) if isinstance(ctx, list) else 0
    logger.info(
        "Applying classic branch protection on %s/%s:%s (%s required checks, enforce_admins=%s)",
        owner,
        repo,
        conf.branch,
        n_checks,
        payload.get("enforce_admins"),
    )
    stdin = payload_json(payload)
    try:
        proc = run(["api", "--method", "PUT", api, "--input", "-"], stdin)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("branch-protection apply failed: %s", exc)
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"{conf.gh_command} api exited {proc.returncode}"
        logger.error("branch-protection apply refused: %s", err)
        return False, err
    logger.info("branch-protection apply accepted for %s/%s:%s", owner, repo, conf.branch)
    return True, None
