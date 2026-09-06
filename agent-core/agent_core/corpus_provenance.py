"""Human-vs-synthetic provenance for a :class:`~agent_core.golden.GoldenSet`.

Phase 7 of the eval-evidence-integrity plan: a gating config must not underwrite
itself with a synthetic corpus. Provenance lives on :attr:`GoldenItem.meta` so
the golden JSONL schema stays additive (unknown meta keys already round-trip).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError
from .golden import GoldenSet
from .logging_util import configure_from_config, debug_span, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CorpusProvenanceConfig:
    """Tunables for the human-label requirement. No literals at call sites."""

    meta_key: str = "provenance"
    human_value: str = "human"
    synthetic_value: str = "synthetic"
    min_items: int = 50  # Phase 7 first-corpus size; a floor, not a target to pad to

    def __post_init__(self) -> None:
        if not self.meta_key.strip():
            raise ConfigError("corpus_provenance.meta_key must be non-empty")
        if not self.human_value.strip() or not self.synthetic_value.strip():
            raise ConfigError("corpus_provenance human/synthetic values must be non-empty")
        if self.human_value == self.synthetic_value:
            raise ConfigError("corpus_provenance human_value and synthetic_value must differ")
        if self.min_items < 1:
            raise ConfigError(f"corpus_provenance.min_items must be >= 1 (got {self.min_items!r})")


def item_provenance(meta: dict[str, str], cfg: CorpusProvenanceConfig | None = None) -> str:
    """Return the provenance token, or empty when unset (treated as unknown)."""
    key = (cfg or CorpusProvenanceConfig()).meta_key
    return str(meta.get(key, "")).strip()


def corpus_problems(gs: GoldenSet, cfg: CorpusProvenanceConfig | None = None) -> tuple[str, ...]:
    """Human-readable problems; empty means the corpus may underwrite a gate."""
    conf = cfg or CorpusProvenanceConfig()
    problems: list[str] = []
    if len(gs.items) < conf.min_items:
        problems.append(
            f"corpus has {len(gs.items)} item(s); need >= {conf.min_items} human-labeled rows"
        )
    synthetic = 0
    missing = 0
    for item in gs.items:
        token = item_provenance(item.meta, conf)
        if token == conf.synthetic_value:
            synthetic += 1
        elif token != conf.human_value:
            missing += 1
    if synthetic:
        problems.append(
            f"{synthetic} item(s) marked {conf.meta_key}={conf.synthetic_value!r} -- "
            "synthetic rows cannot underwrite a gate"
        )
    if missing:
        problems.append(
            f"{missing} item(s) missing {conf.meta_key}={conf.human_value!r} "
            "(unknown provenance is not human provenance)"
        )
    return tuple(problems)


def require_human_corpus(gs: GoldenSet, cfg: CorpusProvenanceConfig | None = None) -> None:
    """Raise :class:`ConfigError` unless every item is human-labeled at the floor."""
    problems = corpus_problems(gs, cfg)
    if problems:
        raise ConfigError("; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assert a GoldenSet JSONL is human-labeled.")
    ap.add_argument("--jsonl", required=True, help="GoldenSet JSONL path")
    ap.add_argument(
        "--min-items",
        type=int,
        default=CorpusProvenanceConfig.min_items,
        help="floor on corpus size (default: CorpusProvenanceConfig.min_items)",
    )
    ap.add_argument(
        "--meta-key",
        default=CorpusProvenanceConfig.meta_key,
        help="GoldenItem.meta key holding provenance",
    )
    args = ap.parse_args(argv)
    configure_from_config()
    cfg = CorpusProvenanceConfig(meta_key=args.meta_key, min_items=args.min_items)
    path = Path(args.jsonl)
    with debug_span(logger, "corpus_provenance.check", path=path.as_posix()):
        try:
            gs = GoldenSet.from_jsonl(path.read_text(encoding="utf-8"))
            require_human_corpus(gs, cfg)
        except (OSError, ValueError, ConfigError) as exc:
            logger.error("corpus-provenance: %s", exc)
            print(f"corpus-provenance FAIL: {exc}", file=sys.stderr)
            return 2
    logger.info("corpus-provenance PASS items=%d", len(gs.items))
    print(f"corpus-provenance PASS items={len(gs.items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
