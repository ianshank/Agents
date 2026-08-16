"""Unit tests for egress classification and dual-scored air-gap verdicts (spec P4)."""

from __future__ import annotations

from backend_validation.airgap import (
    CANARY_DOMAIN,
    AirgapRun,
    AirgapVerdict,
    EgressObservation,
    _witness_is_live,
    classify_dns_queries,
    dual_score,
    observe_egress,
)

_WITNESS = """
15:00:01.001 query: postgres IN A + (172.18.0.2)
15:00:02.101 query: telemetry.langfuse.com IN A + (172.18.0.2)
15:00:03.201 query: clickhouse IN AAAA + (172.18.0.2)
15:00:04.301 query: us.i.posthog.com IN A + (172.18.0.2)
15:00:05.401 query: minio.internal IN A + (172.18.0.2)
"""

# A witness that saw ONLY in-network baseline queries — proof it was live, so an absence
# of external domains is meaningful (usable), not a dead sidecar.
_WITNESS_LIVE_CLEAN = "15:00:01 query: postgres IN A + (172.18.0.2)\n15:00:02 query: clickhouse IN A + (172.18.0.2)\n"


def _obs(
    *, domains: tuple[str, ...] = (), egress_detected: bool = False, usable: bool = True, degraded: bool = False
) -> EgressObservation:
    return EgressObservation(
        mechanism="dns-witness",
        attempted_domains=domains,
        degraded=degraded,
        egress_detected=egress_detected or bool(domains),
        usable=usable,
    )


def test_classify_dns_queries_keeps_only_external_domains() -> None:
    domains = classify_dns_queries(_WITNESS)
    assert domains == ("telemetry.langfuse.com", "us.i.posthog.com")


def test_classify_empty_log_is_zero_egress() -> None:
    assert classify_dns_queries("") == ()


def test_observe_egress_with_iptables_is_authoritative_and_usable() -> None:
    observation = observe_egress(_WITNESS, iptables_available=True, iptables_hits=2)
    assert observation.mechanism == "dns-witness+iptables"
    assert not observation.degraded and observation.usable
    assert observation.egress_detected  # domains present
    assert "telemetry.langfuse.com" in observation.attempted_domains
    assert "iptables egress hits: 2" in observation.notes


def test_iptables_hits_alone_count_as_egress() -> None:
    # Finding 1: a stack that egresses to a hardcoded IP makes no DNS query — iptables hits
    # must still register as egress even with an empty witness log.
    observation = observe_egress("", iptables_available=True, iptables_hits=5)
    assert observation.attempted_domains == ()  # no domains seen
    assert observation.egress_detected is True  # ...but iptables caught 5 packets
    assert observation.usable is True


def test_iptables_zero_hits_is_a_trustworthy_zero() -> None:
    observation = observe_egress(_WITNESS_LIVE_CLEAN, iptables_available=True, iptables_hits=0)
    assert observation.egress_detected is False and observation.usable is True


def test_iptables_available_but_hits_unknown_falls_back_to_witness() -> None:
    # Gemini review (high): iptables_available=True with an unknown (None) hit count is NOT an
    # authoritative trustworthy-zero — it must fall back to the DNS witness. A dead witness
    # there is unusable (fail-safe: never a false air-gap confirm); a live one still supports it.
    dead = observe_egress("", iptables_available=True, iptables_hits=None)
    assert dead.usable is False and dead.degraded is True and dead.mechanism == "dns-witness"
    assert dead.egress_detected is False
    live = observe_egress(_WITNESS_LIVE_CLEAN, iptables_available=True, iptables_hits=None)
    assert live.usable is True and live.egress_detected is False


def test_empty_witness_without_iptables_is_unusable() -> None:
    # Finding 4: a dead/empty witness with no iptables backstop cannot confirm zero egress.
    observation = observe_egress("", iptables_available=False)
    assert observation.mechanism == "dns-witness" and observation.degraded
    assert observation.usable is False  # cannot support an air-gap claim
    assert "WITNESS SAW NO QUERIES" in observation.notes


def test_live_witness_without_iptables_is_usable() -> None:
    observation = observe_egress(_WITNESS_LIVE_CLEAN, iptables_available=False)
    assert observation.degraded and observation.usable is True  # witness proved it was live
    assert observation.egress_detected is False


def test_observe_egress_merges_container_log_hosts_and_is_usable() -> None:
    logs = "ERROR failed to connect to segment.io within timeout"
    observation = observe_egress("", iptables_available=False, container_logs=logs)
    assert "segment.io" in observation.attempted_domains
    assert observation.egress_detected is True and observation.usable is True


def test_dual_score_confirms_airgap_only_when_optout_is_usable_and_clean() -> None:
    def observe(label: str, _env: dict[str, str]) -> EgressObservation:
        if label == "as-shipped":
            return _obs(domains=("telemetry.example.com",))
        return _obs(usable=True, degraded=True)  # opt-out: usable + no egress

    verdict = dual_score("langfuse", {"TELEMETRY_ENABLED": "true"}, {"TELEMETRY_ENABLED": "false"}, observe)
    assert verdict.leaks_as_shipped is True
    assert verdict.air_gapped_confirmed is True and verdict.unconfirmed is False
    assert len(verdict.runs) == 2


def test_dual_score_denies_airgap_when_optout_still_leaks() -> None:
    verdict = dual_score("opik", {}, {}, lambda _label, _env: _obs(domains=("still.leaking.com",)))
    assert verdict.air_gapped_confirmed is False and verdict.leaks_as_shipped is True
    assert verdict.unconfirmed is False  # a positive leak is a definite 'no', not unconfirmed


def test_dual_score_unconfirmed_when_optout_observation_unusable() -> None:
    # Finding 4 end-to-end: a dead-witness opt-out run must be unconfirmed, never confirmed.
    verdict = dual_score("opik", {}, {}, lambda _label, _env: _obs(usable=False, degraded=True))
    assert verdict.air_gapped_confirmed is False
    assert verdict.unconfirmed is True  # cannot make the call -> routes to a human


# ------------------------------------------------------- CoreDNS format + canary (B1)
_COREDNS_LOG = """
witness-1  | [INFO] 172.31.101.7:34567 - 12345 "A IN stats.comet.com. udp 45 false 512" NXDOMAIN qr,aa,rd 106 0.000123s
witness-1  | [INFO] 172.31.101.8:53001 - 12346 "AAAA IN postgres. udp 37 false 512" NXDOMAIN qr,aa,rd 98 0.000101s
witness-1  | [INFO] 172.31.101.9:41210 - 12347 "A IN bv-witness-canary.invalid. udp 54 false 512" NXDOMAIN qr,aa,rd 110 0.000099s
"""

_CANARY_ONLY_COREDNS = (
    '[INFO] 172.31.101.9:41210 - 7 "A IN bv-witness-canary.invalid. udp 54 false 512" NXDOMAIN qr,aa,rd 110 0.0001s\n'
)


def test_classify_parses_coredns_log_format() -> None:
    # CoreDNS quotes `<TYPE> IN <fqdn.>`; single-label service lookups stay internal.
    assert classify_dns_queries(_COREDNS_LOG) == ("stats.comet.com",)


def test_canary_domain_is_excluded_from_egress_but_proves_liveness() -> None:
    # B1: the harness's own canary query must never read as egress...
    assert classify_dns_queries(_CANARY_ONLY_COREDNS) == ()
    # ...yet its query line proves the witness was capturing.
    assert _witness_is_live(_CANARY_ONLY_COREDNS) is True
    assert _witness_is_live("") is False


def test_canary_only_witness_supports_zero_egress_verdict() -> None:
    # End-to-end B1 fix: a clean opt-out run whose ONLY witness line is the canary is a
    # USABLE zero-egress observation — before the canary it read as a dead witness.
    observation = observe_egress(_CANARY_ONLY_COREDNS, iptables_available=False)
    assert observation.usable is True and observation.egress_detected is False
    assert observation.attempted_domains == ()


def test_bind_style_canary_line_is_also_excluded() -> None:
    log = f"15:00:01 query: {CANARY_DOMAIN} IN A + (172.31.101.9)\n"
    assert classify_dns_queries(log) == ()
    assert _witness_is_live(log) is True


def test_container_log_canary_mention_is_not_egress() -> None:
    logs = f"prober | connect to {CANARY_DOMAIN} refused\nweb | connect to minio.internal timed out"
    observation = observe_egress("", iptables_available=False, container_logs=logs)
    assert observation.attempted_domains == ()  # neither the canary nor an internal host
    assert observation.egress_detected is False


# ------------------------------------------------------------- dict round-trips (P4)
def test_egress_observation_dict_round_trip() -> None:
    observation = observe_egress(_COREDNS_LOG, iptables_available=True, iptables_hits=3)
    rebuilt = EgressObservation.from_dict(observation.to_dict())
    assert rebuilt == observation


def test_airgap_run_dict_round_trip_with_and_without_observation() -> None:
    run = AirgapRun("langfuse", "opt-out", {"BV_LANGFUSE_TELEMETRY": "false"})
    assert AirgapRun.from_dict(run.to_dict()) == run  # observation=None survives
    run.observation = observe_egress("", iptables_available=True, iptables_hits=0)
    assert AirgapRun.from_dict(run.to_dict()) == run


def test_airgap_verdict_dict_round_trip_preserves_verdict_properties() -> None:
    def observe(label: str, _env: dict[str, str]) -> EgressObservation:
        if label == "as-shipped":
            return _obs(domains=("stats.comet.com",))
        return _obs(usable=True, degraded=True)

    verdict = dual_score("opik", {"BV_OPIK_USAGE_REPORT": "true"}, {"BV_OPIK_USAGE_REPORT": "false"}, observe)
    payload = verdict.to_dict()
    # The evidence file is self-describing: derived properties are serialized...
    assert payload["air_gapped_confirmed"] is True and payload["leaks_as_shipped"] is True
    rebuilt = AirgapVerdict.from_dict(payload)
    # ...but from_dict recomputes them from structure (never trusts the stored copies).
    assert rebuilt == verdict
    assert rebuilt.air_gapped_confirmed and rebuilt.leaks_as_shipped and not rebuilt.unconfirmed
