"""Literal and callable observation stubs for counterfactual demo replay."""


class NotCallable:
    """Module-defined non-callable; override resolution must fail closed."""


NOT_CALLABLE = NotCallable()


def search_v2(_recorded: object) -> str:
    """Stale retrieval stub: current policy replaced by a superseded Q3 document."""
    return "STALE: Q3 travel policy superseded 2025-01-01"


def search_count(_recorded: object) -> int:
    """Non-str callable return is stringified by the replay target."""
    return 7
