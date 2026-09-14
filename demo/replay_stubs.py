"""Literal and callable observation stubs for counterfactual demo replay."""

#: Not a callable — used to prove override resolution fails closed.
NOT_CALLABLE = "not a stub"


def search_v2(_recorded: object) -> str:
    """Stale retrieval stub: current policy replaced by a superseded Q3 document."""
    return "STALE: Q3 travel policy superseded 2025-01-01"


def search_count(_recorded: object) -> int:
    """Non-str callable return is stringified by the replay target."""
    return 7
