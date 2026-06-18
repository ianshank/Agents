"""Prompt-injection sanitizer — standalone ingestion utility.

Run this BEFORE constructing CycleState. The sanitizer processes raw input
text; it never touches CycleState.unresolved (those are opaque claim IDs).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import ConfigError, SanitizerConfig
from .logging_util import debug_span, get_logger
from .protocols import ClaimId


@dataclass(frozen=True)
class Finding:
    category: str
    rule_id: str
    match: str
    severity: float  # = config.weights[category] at detection time


@dataclass(frozen=True)
class SanitizationResult:
    original: str
    sanitized: str
    findings: tuple[Finding, ...]  # stable (category, rule_id, match.start) order
    risk_score: float
    blocked: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError("risk_score must be in [0, 1]")


@runtime_checkable
class Sanitizer(Protocol):
    def sanitize(self, text: str) -> SanitizationResult: ...


@dataclass(frozen=True)
class SanitizationRule:
    rule_id: str
    category: str
    pattern: re.Pattern[str]  # compiled IGNORECASE


# DEFAULT_RULES data table — patterns are DATA, not logic
DEFAULT_RULES: tuple[SanitizationRule, ...] = (
    # instruction_override
    SanitizationRule(
        "io-01",
        "instruction_override",
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    ),
    SanitizationRule(
        "io-02",
        "instruction_override",
        re.compile(r"disregard\s+(all\s+)?instructions?", re.IGNORECASE),
    ),
    SanitizationRule(
        "io-03",
        "instruction_override",
        re.compile(r"forget\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    ),
    SanitizationRule(
        "io-04",
        "instruction_override",
        re.compile(r"override\s+(your\s+)?instructions?", re.IGNORECASE),
    ),
    # role_hijack
    SanitizationRule(
        "rh-01",
        "role_hijack",
        re.compile(r"you\s+are\s+now\s+\w", re.IGNORECASE),
    ),
    SanitizationRule(
        "rh-02",
        "role_hijack",
        re.compile(r"act\s+as\s+(a\s+|an\s+)?\w", re.IGNORECASE),
    ),
    SanitizationRule(
        "rh-03",
        "role_hijack",
        re.compile(r"pretend\s+(to\s+be|you\s+are)", re.IGNORECASE),
    ),
    SanitizationRule(
        "rh-04",
        "role_hijack",
        re.compile(r"roleplay\s+as", re.IGNORECASE),
    ),
    # delimiter_injection
    SanitizationRule(
        "di-01",
        "delimiter_injection",
        re.compile(r"<\|system\|>", re.IGNORECASE),
    ),
    SanitizationRule(
        "di-02",
        "delimiter_injection",
        re.compile(r"\[SYSTEM\]", re.IGNORECASE),
    ),
    SanitizationRule(
        "di-03",
        "delimiter_injection",
        re.compile(r"---+\s*SYSTEM\s*---+", re.IGNORECASE),
    ),
    SanitizationRule(
        "di-04",
        "delimiter_injection",
        re.compile(r"#+\s*SYSTEM\s*#+", re.IGNORECASE),
    ),
    # exfiltration
    SanitizationRule(
        "ex-01",
        "exfiltration",
        re.compile(
            r"(output|print|display|dump)\s+(all|the)\s+(system|config|secret|key)",
            re.IGNORECASE,
        ),
    ),
    SanitizationRule(
        "ex-02",
        "exfiltration",
        re.compile(r"reveal\s+(your\s+)?(prompt|instructions?|system)", re.IGNORECASE),
    ),
    SanitizationRule(
        "ex-03",
        "exfiltration",
        re.compile(r"(send|transmit|exfiltrate)\s+(data|information)\s+to", re.IGNORECASE),
    ),
    # prompt_leak
    SanitizationRule(
        "pl-01",
        "prompt_leak",
        re.compile(r"repeat\s+(everything|the|your)\s+(above|instructions?|prompt)", re.IGNORECASE),
    ),
    SanitizationRule(
        "pl-02",
        "prompt_leak",
        re.compile(r"what\s+(are|were)\s+your\s+(original\s+)?instructions?", re.IGNORECASE),
    ),
    SanitizationRule(
        "pl-03",
        "prompt_leak",
        re.compile(r"show\s+(me\s+)?(your\s+)?(original\s+)?system\s+prompt", re.IGNORECASE),
    ),
)


class RuleSanitizer:
    """Regex-rule-based sanitizer implementing the Sanitizer Protocol."""

    def __init__(
        self,
        config: SanitizerConfig,
        rules: Sequence[SanitizationRule] = DEFAULT_RULES,
    ) -> None:
        # validate unique rule_ids — shadowed rules are a security footgun
        seen_ids: set[str] = set()
        for rule in rules:
            if rule.rule_id in seen_ids:
                raise ConfigError(f"duplicate rule_id: {rule.rule_id!r}")
            seen_ids.add(rule.rule_id)
        self._config = config
        self._rules: list[SanitizationRule] = list(rules)
        self._log = get_logger("agent_core.sanitize")

    def register_rule(self, rule: SanitizationRule) -> RuleSanitizer:
        """Add a rule (open/closed); raises ConfigError on duplicate rule_id."""
        for existing in self._rules:
            if existing.rule_id == rule.rule_id:
                raise ConfigError(f"duplicate rule_id: {rule.rule_id!r}")
        self._rules.append(rule)
        return self

    def sanitize(self, text: str) -> SanitizationResult:
        cfg = self._config
        weights = cfg.weights
        enabled = set(cfg.enabled_categories) if cfg.enabled_categories else None
        # (category, rule_id, start, finding)
        raw_findings: list[tuple[str, str, int, Finding]] = []

        for rule in self._rules:
            if enabled is not None and rule.category not in enabled:
                continue
            severity = weights.get(rule.category, 0.0)
            for m in rule.pattern.finditer(text):
                raw_findings.append(
                    (
                        rule.category,
                        rule.rule_id,
                        m.start(),
                        Finding(
                            category=rule.category,
                            rule_id=rule.rule_id,
                            match=m.group(),
                            severity=severity,
                        ),
                    )
                )

        # stable order: (category, rule_id, match start position)
        raw_findings.sort(key=lambda t: (t[0], t[1], t[2]))
        findings = tuple(f for *_, f in raw_findings)

        # aggregate risk score per config
        if not findings:
            risk_score = 0.0
        elif cfg.risk_aggregation == "max":
            risk_score = max(f.severity for f in findings)
        else:  # weighted_sum, clamped to [0, 1]
            risk_score = min(1.0, sum(f.severity for f in findings))

        blocked = risk_score >= cfg.risk_block_threshold

        # replace each match with default_redaction (left-to-right, non-overlapping)
        # rebuild from original to avoid offset drift
        active_rules = [
            rule for rule in self._rules if (enabled is None or rule.category in enabled)
        ]
        if active_rules:
            pattern_union = re.compile(
                "|".join(rule.pattern.pattern for rule in active_rules),
                re.IGNORECASE,
            )
            sanitized = pattern_union.sub(cfg.default_redaction, text)
        else:
            sanitized = text

        if blocked:
            with debug_span(self._log, "sanitize.blocked", risk=f"{risk_score:.3f}"):
                pass

        return SanitizationResult(
            original=text,
            sanitized=sanitized,
            findings=findings,
            risk_score=risk_score,
            blocked=blocked,
        )


def build_sanitized_claims(
    raw_inputs: Sequence[str],
    sanitizer: Sanitizer,
    config: SanitizerConfig,
) -> tuple[tuple[ClaimId, ...], tuple[SanitizationResult, ...]]:
    """Sanitize raw inputs; drop blocked ones; map survivors to ClaimIds.

    Returns (claim_ids, all_results). claim_ids are the original input indices
    as strings (stable, opaque). Caller uses them to build CycleState.unresolved.
    Never mutates existing CycleState.
    """
    results: list[SanitizationResult] = [sanitizer.sanitize(inp) for inp in raw_inputs]
    claim_ids: list[ClaimId] = [str(i) for i, r in enumerate(results) if not r.blocked]
    return tuple(claim_ids), tuple(results)
