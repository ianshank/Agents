"""The SDLC test-pass domain: the first cheap property-oracle suite.

Each instance presents a small set of candidate work products (the abstract
analogue of candidate patches), exactly one of which is ``correct`` (passes the
instance's tests). ``difficulty`` spans a range so a skilled agent's outcomes vary
across the population — giving the calibration metrics real spread to measure.

The suite is generated deterministically from a seed so the population is
reproducible and its size is *declared* (``CorpusConfig.declared_n_per_domain``),
not guessed. A snapshot is committed at ``flow-corpus/data/suites/sdlc.jsonl`` for
provenance; :func:`load_suite` / :func:`save_suite` round-trip it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from flow_corpus.config import CorpusConfig
from flow_corpus.suites.base import TaskInstance, TaskSuite

DOMAIN = "sdlc"
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "suites" / "sdlc.jsonl"
_SPACE_SIZE = 4  # candidates per instance: 1 correct + 3 wrong


def build_sdlc_suite(cfg: CorpusConfig, *, seed: int = 1729) -> TaskSuite:
    """Deterministically build a suite of ``cfg.declared_n_per_domain`` instances."""
    rng = random.Random(seed)
    instances: list[TaskInstance] = []
    n = cfg.declared_n_per_domain
    for i in range(n):
        # Difficulty sweeps [0, 0.8] so outcomes are neither all-pass nor all-fail.
        difficulty = round(0.8 * i / max(1, n - 1), 4)
        space = tuple(f"cand_{i}_{j}" for j in range(_SPACE_SIZE))
        correct_idx = rng.randrange(_SPACE_SIZE)
        instances.append(
            TaskInstance(
                instance_id=f"sdlc-{i:04d}",
                domain=DOMAIN,
                difficulty=difficulty,
                solution_space=space,
                correct=(space[correct_idx],),
            )
        )
    return TaskSuite(domain=DOMAIN, instances=tuple(instances))


def save_suite(suite: TaskSuite, path: Path | None = None) -> Path:
    """Persist a suite as deterministic JSONL (one instance per line, sorted keys)."""
    target = path or _DATA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [inst.model_dump_json() for inst in suite.instances]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def load_suite(path: Path | None = None) -> TaskSuite:
    """Load a committed JSONL suite snapshot."""
    source = path or _DATA_PATH
    text = source.read_text(encoding="utf-8")
    instances = tuple(
        TaskInstance.model_validate(json.loads(line)) for line in text.splitlines() if line.strip()
    )
    if not instances:
        raise ValueError(f"no valid task instances found in {source}")
    return TaskSuite(domain=instances[0].domain, instances=instances)
