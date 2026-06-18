"""A trivial system-under-test for exercising the dynamic CallableTarget."""

from __future__ import annotations


def summarize(inputs: dict) -> str:
    return f"summary: {inputs.get('text', '')}"


def boom(inputs: dict) -> str:
    raise ValueError("kaboom")
