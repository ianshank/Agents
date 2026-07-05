#!/usr/bin/env python3
"""Seed a Langfuse dataset with E2E test items.

Idempotent: if the dataset already exists, this script logs a message and exits.
All configuration via environment variables — no hardcoded values.

Usage:
    python scripts/seed_langfuse_dataset.py [--dataset-name NAME]
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Default dataset name — overridable via CLI arg or env var
_DEFAULT_DATASET = os.environ.get("E2E_DATASET_NAME", "eval-harness-e2e-test")

# Test items — minimal but realistic for E2E validation
_TEST_ITEMS: list[dict[str, Any]] = [
    {
        "input": {"question": "What is 2+2?"},
        "expected_output": "4",
        "metadata": {"category": "math", "difficulty": "easy"},
    },
    {
        "input": {"question": "What is the capital of France?"},
        "expected_output": "Paris",
        "metadata": {"category": "geography", "difficulty": "easy"},
    },
    {
        "input": {
            "question": (
                "If all roses are flowers and some flowers fade quickly, "
                "can we conclude all roses fade quickly?"
            ),
        },
        "expected_output": "No, this is a logical fallacy (undistributed middle).",
        "metadata": {"category": "reasoning", "difficulty": "medium"},
    },
]


def seed_dataset(dataset_name: str) -> None:
    """Create dataset in Langfuse and populate with test items."""
    try:
        Langfuse = getattr(importlib.import_module("langfuse"), "Langfuse")
    except ImportError:
        logger.error("langfuse package not installed. Run: pip install 'langfuse-eval-harness[langfuse]'")
        sys.exit(1)

    # Credentials from env vars (Langfuse SDK reads these automatically)
    for var in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY"):
        if not os.environ.get(var):
            logger.error("Required env var %s is not set.", var)
            sys.exit(1)

    lf = Langfuse()

    # Check if dataset already exists
    try:
        existing = lf.get_dataset(dataset_name)
        if existing and existing.items:
            logger.info(
                "Dataset '%s' already exists with %d items. Skipping seed.",
                dataset_name,
                len(existing.items),
            )
            return
    except Exception:
        logger.info("Dataset '%s' not found, creating...", dataset_name)

    # Create dataset
    lf.create_dataset(
        name=dataset_name,
        description="E2E test dataset for langfuse-eval-harness (auto-created, safe to delete)",
        metadata={"source": "scripts/seed_langfuse_dataset.py"},
    )

    # Add items
    for item_data in _TEST_ITEMS:
        lf.create_dataset_item(
            dataset_name=dataset_name,
            input=item_data["input"],
            expected_output=item_data["expected_output"],
            metadata=item_data.get("metadata", {}),
        )
        input_dict: dict[str, str] = item_data["input"]
        logger.info("Added item: %s", input_dict.get("question", "")[:60])

    lf.flush()
    logger.info("Seeded dataset '%s' with %d items.", dataset_name, len(_TEST_ITEMS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Langfuse dataset for E2E tests")
    parser.add_argument(
        "--dataset-name",
        default=_DEFAULT_DATASET,
        help=f"Dataset name (default: {_DEFAULT_DATASET})",
    )
    args = parser.parse_args()
    seed_dataset(args.dataset_name)


if __name__ == "__main__":
    main()
