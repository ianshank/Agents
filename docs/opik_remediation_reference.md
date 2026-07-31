# Opik Integration & Remediation Reference (2026 Architecture)

## Overview
This reference document outlines the architectural design, API contracts, configuration schema, and telemetry patterns for the `opik` integration within the `eval_harness` package.

The design strictly follows the **SDK-optional seam pattern** used by `LangfuseClient`, `PhoenixScoreClient`, and `BrainTrustClient`.

---

## 1. Component Architecture

```
                                +-------------------+
                                |   EvalConfig      |
                                |  (opik: block)    |
                                +---------+---------+
                                          |
                                          v
                                +-------------------+
                                |    EvalEngine     |
                                +----+----+----+----+
                                     |    |    |
            +------------------------+    |    +-----------------------+
            |                             v                            |
            v                   +-------------------+                  v
 +-------------------+          |    OpikClient     |        +-------------------+
 |   DatasetSource   | <------- | (SDK / Null Seam) | ------>|     OpikSink      |
 +-------------------+          +---------+---------+        +-------------------+
                                          |
                                          v
                                +-------------------+
                                |    Opik Cloud     |
                                +-------------------+
```

---

## 2. API Seam Contract: `OpikClient`

```python
class OpikClient(ABC):
    @abstractmethod
    def log_score(
        self,
        *,
        run_id: str,
        item_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None: ...

    @abstractmethod
    def log_item(
        self,
        *,
        run_id: str,
        item_id: str,
        input: Any,
        output: Any,
        expected: Any = None,
        scores: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def get_dataset_items(self, dataset_name: str) -> list[dict]: ...

    @abstractmethod
    def flush(self) -> None: ...
```

---

## 3. Config Schema: `OpikConfig`

Added to `src/eval_harness/config/models.py`:

```yaml
schema_version: "1.0"
run:
  name: "demo-eval"
opik:
  enabled: true
  project_name: "eval-harness"
  workspace: "ian-cruickshank"
  track_targets: true
```

---

## 4. Windows & SSL Bypass Protocol
Opik's HTTP transport (`httpx`) on Windows enterprise networks requires an `HttpxClientHook` to disable strict SSL verification safely:

```python
from opik.hooks.httpx_client_hook import add_httpx_client_hook, HttpxClientHook

add_httpx_client_hook(
    HttpxClientHook(client_modifier=None, client_init_arguments={"verify": False})
)
```

---

## 5. Sink Definition
Registered as `opik` in `sinks/__init__.py`:

```python
@SINKS.register("opik")
class OpikSink(ResultSink):
    def __init__(
        self,
        enabled: bool = True,
        project_name: str = "eval-harness",
        min_value_to_log: float | None = None,
    ):
        ...
```
