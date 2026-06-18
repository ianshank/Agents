"""Per-domain recalibration management.

TemperatureScaler: 1-parameter temperature scaling calibrator.
CalibratorRegistry: fit-per-domain, then freeze → read-only concurrent predict.
make_calibrator: factory keyed by name from RecalibrationConfig.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from .calibration import Calibrator, IsotonicCalibrator, _check_pairs
from .config import ConfigError, RecalibrationConfig
from .logging_util import debug_span, get_logger

_GR = (math.sqrt(5) + 1) / 2  # golden ratio constant for golden-section search


class TemperatureScaler:
    """1-parameter temperature scaling: predict(p) = sigmoid(logit(clamp(p, eps)) / T).

    T is found by golden-section search minimising mean NLL on the fit data.
    All search parameters come from RecalibrationConfig — no literals in logic.
    """

    def __init__(self, config: RecalibrationConfig) -> None:
        self._config = config
        self._T: float | None = None  # None = not fitted

    def fit(self, probs: Sequence[float], outcomes: Sequence[int]) -> TemperatureScaler:
        _check_pairs(probs, outcomes)
        cfg = self._config
        eps = cfg.clamp_eps

        def _clamp(p: float) -> float:
            return max(eps, min(1.0 - eps, p))

        def _logit(p: float) -> float:
            q = _clamp(p)
            return math.log(q / (1.0 - q))

        def _sigmoid(x: float) -> float:
            # Numerically stable: avoid overflow for large |x|.
            if x >= 0:
                return 1.0 / (1.0 + math.exp(-x))
            ex = math.exp(x)
            return ex / (1.0 + ex)

        logits = [_logit(p) for p in probs]
        ys = list(outcomes)

        # Single-class: calibration undefined → identity (T=1)
        if len(set(ys)) < 2:
            self._T = 1.0
            return self

        def _nll(t_val: float) -> float:
            total = 0.0
            for lgt, y in zip(logits, ys, strict=False):
                p_hat = _sigmoid(lgt / t_val)
                p_hat = max(eps, min(1.0 - eps, p_hat))
                total -= y * math.log(p_hat) + (1 - y) * math.log(1.0 - p_hat)
            return total / len(logits)

        # Golden-section search over [lo, hi] for minimum NLL.
        # Each iteration reuses one of the two previously-evaluated points, so only
        # one new _nll() call per iteration instead of two (O(dataset) each).
        a, b = cfg.temperature_search_lo, cfg.temperature_search_hi
        c = b - (b - a) / _GR
        d = a + (b - a) / _GR
        fc, fd = _nll(c), _nll(d)
        for _ in range(cfg.temperature_max_iter):
            if fc < fd:
                b = d
                d, fd = c, fc
                c = b - (b - a) / _GR
                fc = _nll(c)
            else:
                a = c
                c, fc = d, fd
                d = a + (b - a) / _GR
                fd = _nll(d)
            if abs(b - a) < cfg.temperature_tol:
                break
        self._T = (a + b) / 2.0
        return self

    def predict(self, prob: float) -> float:
        if self._T is None:
            raise RuntimeError("TemperatureScaler.predict called before fit")
        cfg = self._config
        eps = cfg.clamp_eps
        p = max(eps, min(1.0 - eps, prob))
        logit = math.log(p / (1.0 - p))
        x = logit / self._T
        # Numerically stable sigmoid to avoid overflow for large |x|.
        if x >= 0:
            return 1.0 / (1.0 + math.exp(-x))
        ex = math.exp(x)
        return ex / (1.0 + ex)


def _make_isotonic(cfg: RecalibrationConfig) -> Calibrator:
    return IsotonicCalibrator()


def _make_temperature(cfg: RecalibrationConfig) -> Calibrator:
    return TemperatureScaler(cfg)


CALIBRATOR_FACTORIES: dict[str, Callable[[RecalibrationConfig], Calibrator]] = {
    "isotonic": _make_isotonic,
    "temperature": _make_temperature,
}


def make_calibrator(name: str, config: RecalibrationConfig) -> Calibrator:
    """Instantiate a calibrator by name, passing config for parameterisation."""
    try:
        return CALIBRATOR_FACTORIES[name](config)
    except KeyError as exc:
        raise ConfigError(f"unknown calibrator: {name!r}") from exc


class CalibratorRegistry:
    """Fit one calibrator per domain; freeze → read-only concurrent predict.

    After freeze(), predict() needs no lock because _calibrators is never written.
    Unseen domains use the global fallback calibrator (fitted on all training data)
    or raise per fallback_policy.
    """

    def __init__(self, config: RecalibrationConfig) -> None:
        self._config = config
        self._frozen = False
        self._calibrators: dict[str, Calibrator] = {}
        # per-domain data stored keyed by domain so re-fit overwrites, not appends
        self._domain_data: dict[str, tuple[list[float], list[int]]] = {}
        self._log = get_logger("agent_core.recalibration")

    def fit(self, domain: str, probs: Sequence[float], outcomes: Sequence[int]) -> None:
        """Fit a calibrator for `domain`. Raises RuntimeError if already frozen."""
        if self._frozen:
            raise RuntimeError("CalibratorRegistry is frozen; fit() is not allowed after freeze()")
        if domain == "__global__":
            raise ConfigError("'__global__' is a reserved domain name")
        with debug_span(self._log, "recalibration.fit", domain=domain, n=len(probs)):
            cal = make_calibrator(self._config.default_calibrator, self._config)
            cal = cal.fit(list(probs), list(outcomes))
            self._calibrators[domain] = cal
            # overwrite (not extend) so repeated fit for same domain doesn't duplicate data
            self._domain_data[domain] = (list(probs), list(outcomes))

    def freeze(self) -> CalibratorRegistry:
        """Fit global fallback on all seen data, then lock registry against further fit()."""
        if self._frozen:
            return self  # idempotent — safe to call multiple times
        all_probs = [p for ps, _ in self._domain_data.values() for p in ps]
        all_outcomes = [o for _, os in self._domain_data.values() for o in os]
        if all_probs:
            global_cal = make_calibrator(self._config.default_calibrator, self._config)
            global_cal = global_cal.fit(all_probs, all_outcomes)
            self._calibrators["__global__"] = global_cal
        self._domain_data.clear()  # release training data; fitted calibrators are enough
        self._frozen = True
        return self

    def predict(self, domain: str, prob: float) -> float:
        """Predict for `domain`. Uses global fallback or raises per fallback_policy."""
        if not self._frozen:
            raise RuntimeError("CalibratorRegistry.predict() must be called after freeze()")
        if domain in self._calibrators:
            return self._calibrators[domain].predict(prob)
        # unseen domain
        if self._config.fallback_policy == "global":
            global_cal = self._calibrators.get("__global__")
            if global_cal is None:  # pragma: no cover  # registry not fitted before freeze
                return prob  # nothing fitted — identity
            with debug_span(self._log, "recalibration.fallback", domain=domain):
                pass
            return global_cal.predict(prob)
        raise KeyError(f"unknown domain {domain!r} and fallback_policy='error'")
