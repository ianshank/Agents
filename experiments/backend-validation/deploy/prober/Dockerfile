# In-network prober for the air-gapped L3 re-run (P4): published ports die on
# `internal: true` networks, so the L1 suite re-runs from THIS container inside the stack
# network, writing evidence to a bind mount of the experiment's own artifacts/ directory
# (the one permitted bind mount — still inside the subtree, zero-writes preserved).
# Build while ONLINE during P1; run offline during P4. Base image digest-pinned like
# every other image (TODO_PIN -> `make pin-digests`).
FROM python:3.11-slim@TODO_PIN

WORKDIR /experiment
COPY pyproject.toml README.md config.yaml PROBES.yaml RUBRIC.md ./
COPY schemas/ schemas/
COPY backend_validation/ backend_validation/

RUN pip install --no-cache-dir ".[langfuse,opik]"

ENTRYPOINT ["python", "-m", "backend_validation.cli"]
