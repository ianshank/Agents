"""P4 air-gap: re-run L1 egress-blocked, dual-scored as-shipped vs telemetry opt-out.

The matrix's ``Air-Gapped: Yes`` claim is only confirmed if a stack, on an ``internal:
true`` network, makes ZERO external calls after the documented telemetry opt-out (spec
R8/P4). Published ports die with internal networks, so the L1 suite re-runs from an
in-network prober container; a DNS-witness sidecar logs every attempted lookup. Every
degradation (no iptables, witness-only) is RECORDED, never silently assumed away.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from backend_validation.logging_util import get_logger

logger = get_logger(__name__)

# Hostnames that are part of the local stack — a lookup for these is NOT egress.
_INTERNAL_SUFFIXES = (".internal", ".local", "localhost")
_QUERY_LINE = re.compile(r"query:\s+(?P<domain>[A-Za-z0-9._-]+)\s+IN\s+", re.IGNORECASE)


@dataclass(frozen=True)
class EgressObservation:
    """What egress-observation mechanism was available, and what it saw.

    ``egress_detected`` and ``usable`` are the two facts the verdict actually keys off:
    a "zero egress" claim requires POSITIVE evidence that nothing left (``not
    egress_detected``) AND that the observation was capable of seeing it (``usable``).
    A dead/empty DNS witness with no iptables backstop is NOT usable — absence of
    observed egress there is absence of evidence, not evidence of absence.
    """

    mechanism: str  # "dns-witness" | "dns-witness+iptables"
    attempted_domains: tuple[str, ...]
    degraded: bool
    egress_detected: bool  # external domains seen OR iptables recorded >0 egress packets
    usable: bool  # can this observation support a trustworthy "zero egress" claim?
    notes: str = ""


def classify_dns_queries(witness_log: str) -> tuple[str, ...]:
    """Extract external (non-stack) domains from a coredns/dnsmasq query log."""
    domains: set[str] = set()
    for match in _QUERY_LINE.finditer(witness_log):
        domain = match.group("domain").rstrip(".").lower()
        if not domain or domain.endswith(_INTERNAL_SUFFIXES) or _is_service_name(domain):
            continue
        domains.add(domain)
    return tuple(sorted(domains))


def _is_service_name(domain: str) -> bool:
    """A bare single-label name (e.g. 'postgres', 'clickhouse') is an in-network service."""
    return "." not in domain


def _witness_is_live(witness_log: str) -> bool:
    """True if the witness logged ANY DNS query (internal or external).

    A live witness that saw only in-network baseline lookups (postgres, clickhouse) proves
    it was capturing, so an absence of EXTERNAL queries is meaningful. A witness log with no
    query lines at all is indistinguishable from a sidecar that never attached — it cannot
    support an air-gap confirmation.
    """
    return _QUERY_LINE.search(witness_log) is not None


def observe_egress(
    witness_log: str,
    *,
    iptables_available: bool,
    iptables_hits: int | None = None,
    container_logs: str = "",
) -> EgressObservation:
    """Combine the DNS witness (primary) with optional iptables counters and log scraping.

    The iptables hit count now feeds the verdict directly (an egress to a hardcoded IP makes
    no DNS query, so DNS-witness alone would miss it), and the DNS-witness-only path is only
    ``usable`` when the witness proved it was live.
    """
    domains = classify_dns_queries(witness_log)
    log_domains = _domains_from_container_logs(container_logs)
    all_domains = tuple(sorted(set(domains) | set(log_domains)))
    iptables_egress = bool(iptables_available and (iptables_hits or 0) > 0)
    egress_detected = bool(all_domains) or iptables_egress
    if iptables_available:
        # iptables is authoritative: it counts every packet, so even a zero here is a
        # trustworthy zero regardless of the DNS witness.
        mechanism = "dns-witness+iptables"
        degraded = False
        usable = True
        notes = f"iptables egress hits: {iptables_hits if iptables_hits is not None else 'unknown'}"
    else:
        mechanism = "dns-witness"
        degraded = True
        usable = _witness_is_live(witness_log) or bool(log_domains)
        witness_note = "" if usable else " — WITNESS SAW NO QUERIES (cannot confirm air-gap)"
        notes = "iptables unavailable; egress inferred from DNS witness + container logs" + witness_note
    return EgressObservation(
        mechanism=mechanism,
        attempted_domains=all_domains,
        degraded=degraded,
        egress_detected=egress_detected,
        usable=usable,
        notes=notes,
    )


_LOG_HOST = re.compile(
    r"(?:connect to|connection to|reaching|host[:=])\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.IGNORECASE
)


def _domains_from_container_logs(container_logs: str) -> set[str]:
    domains: set[str] = set()
    for match in _LOG_HOST.finditer(container_logs):
        domain = match.group(1).rstrip(".").lower()
        if not domain.endswith(_INTERNAL_SUFFIXES) and not _is_service_name(domain):
            domains.add(domain)
    return domains


@dataclass
class AirgapRun:
    """One air-gapped re-run under a specific telemetry configuration."""

    backend: str
    config_label: str  # "as-shipped" | "opt-out"
    env: dict[str, str]
    observation: EgressObservation | None = None

    @property
    def zero_egress(self) -> bool:
        # Confirmed zero egress requires a USABLE observation that detected NO egress —
        # not merely the absence of observed domains from an observation that could not see.
        obs = self.observation
        return obs is not None and obs.usable and not obs.egress_detected

    @property
    def egress_detected(self) -> bool:
        return self.observation is not None and self.observation.egress_detected

    @property
    def observation_usable(self) -> bool:
        return self.observation is not None and self.observation.usable


@dataclass
class AirgapVerdict:
    """The dual-scored verdict for one backend (spec P4)."""

    backend: str
    as_shipped: AirgapRun
    opt_out: AirgapRun
    runs: list[AirgapRun] = field(default_factory=list)

    @property
    def air_gapped_confirmed(self) -> bool:
        # The matrix's Yes is confirmed ONLY when the opt-out run POSITIVELY shows zero
        # egress from a usable observation. An unusable observation confirms nothing.
        return self.opt_out.zero_egress

    @property
    def leaks_as_shipped(self) -> bool:
        # A leak is a POSITIVE detection, not merely "not confirmed zero" — so an unusable
        # observation is `unconfirmed`, never a false leak claim.
        return self.as_shipped.egress_detected

    @property
    def unconfirmed(self) -> bool:
        """The opt-out observation could not support a verdict either way (spec fail-safe:
        this should route to a human / BLOCK, never silently read as confirmed)."""
        return not self.opt_out.observation_usable


def dual_score(
    backend_id: str,
    as_shipped_env: Mapping[str, str],
    opt_out_env: Mapping[str, str],
    observe: Callable[[str, dict[str, str]], EgressObservation],
) -> AirgapVerdict:
    """Run the (already-collected) observation function for both env configurations.

    ``observe`` is injected: in production it recreates the stack on the internal network
    with the given env, runs the prober, and returns the egress observation. Kept as a
    seam so the dual-scoring logic is unit-testable without docker.
    """
    as_shipped = AirgapRun(backend_id, "as-shipped", dict(as_shipped_env))
    as_shipped.observation = observe("as-shipped", dict(as_shipped_env))
    opt_out = AirgapRun(backend_id, "opt-out", dict(opt_out_env))
    opt_out.observation = observe("opt-out", dict(opt_out_env))
    logger.info(
        "airgap[%s]: as-shipped leaks=%s, opt-out zero-egress=%s",
        backend_id,
        not as_shipped.zero_egress,
        opt_out.zero_egress,
    )
    return AirgapVerdict(backend=backend_id, as_shipped=as_shipped, opt_out=opt_out, runs=[as_shipped, opt_out])
