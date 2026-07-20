"""Unit tests for egress classification and dual-scored air-gap verdicts (spec P4)."""

from __future__ import annotations

from backend_validation.airgap import (
    EgressObservation,
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


def test_classify_dns_queries_keeps_only_external_domains() -> None:
    domains = classify_dns_queries(_WITNESS)
    # single-label service names (postgres, clickhouse) and *.internal are stack-local.
    assert domains == ("telemetry.langfuse.com", "us.i.posthog.com")


def test_classify_empty_log_is_zero_egress() -> None:
    assert classify_dns_queries("") == ()


def test_observe_egress_with_iptables_is_not_degraded() -> None:
    observation = observe_egress(_WITNESS, iptables_available=True, iptables_hits=2)
    assert observation.mechanism == "dns-witness+iptables"
    assert not observation.degraded
    assert "telemetry.langfuse.com" in observation.attempted_domains
    assert "iptables egress hits: 2" in observation.notes


def test_observe_egress_without_iptables_records_degradation() -> None:
    observation = observe_egress("", iptables_available=False)
    assert observation.mechanism == "dns-witness" and observation.degraded
    assert "iptables not available" in observation.notes


def test_observe_egress_merges_container_log_hosts() -> None:
    logs = "ERROR failed to connect to segment.io within timeout"
    observation = observe_egress("", iptables_available=False, container_logs=logs)
    assert "segment.io" in observation.attempted_domains


def test_dual_score_confirms_airgap_only_when_optout_is_clean() -> None:
    def observe(label: str, _env: dict[str, str]) -> EgressObservation:
        domains = ("telemetry.example.com",) if label == "as-shipped" else ()
        return EgressObservation(mechanism="dns-witness", attempted_domains=domains, degraded=True)

    verdict = dual_score("langfuse", {"TELEMETRY_ENABLED": "true"}, {"TELEMETRY_ENABLED": "false"}, observe)
    assert verdict.leaks_as_shipped is True
    assert verdict.air_gapped_confirmed is True  # opt-out run was clean
    assert len(verdict.runs) == 2


def test_dual_score_denies_airgap_when_optout_still_leaks() -> None:
    def observe(_label: str, _env: dict[str, str]) -> EgressObservation:
        return EgressObservation(mechanism="dns-witness", attempted_domains=("still.leaking.com",), degraded=False)

    verdict = dual_score("opik", {}, {}, observe)
    assert verdict.air_gapped_confirmed is False and verdict.leaks_as_shipped is True
