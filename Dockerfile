# Minimal, air-gapped evaluation runner image for Langfuse Eval Harness
FROM python:3.11-slim

LABEL maintainer="Ian Cruickshank <ianshank@gmail.com>"
LABEL description="Headless evaluation runner for Langfuse Eval Harness"

WORKDIR /app

# Install dependencies first for efficient layer caching
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Default unprivileged runtime user
RUN useradd -u 1000 -m appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["eval-harness"]
CMD ["--help"]
