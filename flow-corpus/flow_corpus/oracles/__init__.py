"""Oracle layer: judges a FlowResult, validated against human audit before it gates."""

from __future__ import annotations

from .base import Oracle
from .kappa_gate import KappaReport, validate_oracle
from .property_oracle import PropertyOracle

__all__ = ["KappaReport", "Oracle", "PropertyOracle", "validate_oracle"]
