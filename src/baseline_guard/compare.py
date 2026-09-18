"""Compare a run against a baseline and decide whether it may ship."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import fmean

from .baseline import Baseline, Metrics, _coerce_metrics
from .spec import MetricSpec

AGGREGATE = "<all slices>"


class RegressionError(RuntimeError):
    """Raised when a run regressed past its budget."""


@dataclass(frozen=True)
class Movement:
    """One metric on one slice, or on the aggregate."""

    slice_name: str
    metric: str
    baseline: float
    current: float
    regression: float
    limit: float
    relative: bool

    @property
    def failed(self) -> bool:
        return self.regression > self.limit

    @property
    def improved(self) -> bool:
        return self.regression < 0

    def __str__(self) -> str:
        scale, unit = (100.0, "%") if self.relative else (1.0, "")
        verdict = "FAIL" if self.failed else "pass"
        moved = self.regression * scale
        moved = 0.0 if moved == 0 else moved  # keep an unchanged metric off "-0"
        return (
            f"[{verdict}] {self.slice_name} / {self.metric}: "
            f"{self.baseline:.4g} -> {self.current:.4g} "
            f"({moved:+.4g}{unit}, budget {self.limit * scale:.4g}{unit})"
        )


@dataclass
class GateReport:
    movements: list[Movement] = field(default_factory=list)
    new_slices: list[str] = field(default_factory=list)
    missing_slices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[Movement]:
        return [m for m in self.movements if m.failed]

    @property
    def ok(self) -> bool:
        # A slice that vanished is a failure: a run that quietly stopped
        # covering part of the data would otherwise pass by not being measured.
        return not self.failures and not self.missing_slices

    def raise_for_status(self) -> None:
        if self.ok:
            return
        lines = [str(m) for m in self.failures]
        lines += [f"[FAIL] {name}: in the baseline but missing from this run"
                  for name in self.missing_slices]
        raise RegressionError("the run regressed past its budget:\n" + "\n".join(f"  {l}" for l in lines))

    def __str__(self) -> str:
        lines = [str(m) for m in self.movements]
        lines += [f"[FAIL] {name}: in the baseline but missing from this run"
                  for name in self.missing_slices]
        lines += [f"[note] {name}: new slice, not in the baseline" for name in self.new_slices]
        lines += [f"[warn] {text}" for text in self.warnings]
        return "\n".join(lines)


def check(
    current: Metrics,
    baseline: Baseline,
    spec: dict[str, MetricSpec],
    *,
    max_age_days: int | None = None,
    today: date | None = None,
) -> GateReport:
    """Compare ``current`` against ``baseline`` under ``spec``.

    Slices absent from the baseline are reported as new rather than failed:
    there is nothing to compare them against yet. Slices present in the
    baseline but absent from the run fail, because a shrinking run is how a
    gate gets passed by accident.
    """
    current = _coerce_metrics(current)
    report = GateReport()

    report.new_slices = sorted(set(current) - set(baseline.metrics))
    report.missing_slices = sorted(set(baseline.metrics) - set(current))

    age = baseline.age_days(today)
    if max_age_days is not None and age is not None and age > max_age_days:
        report.warnings.append(
            f"the baseline is {age} days old (limit {max_age_days}); re-freeze it before "
            f"trusting this comparison, or it measures its own age rather than this change"
        )
    if baseline.recorded_at is None:
        report.warnings.append("the baseline has no recorded_at, so its age cannot be checked")

    for slice_name in sorted(set(current) & set(baseline.metrics)):
        for metric, metric_spec in spec.items():
            if metric_spec.limit is None:
                continue
            base_value = baseline.metrics[slice_name].get(metric)
            new_value = current[slice_name].get(metric)
            if base_value is None or new_value is None:
                report.warnings.append(
                    f"{slice_name} / {metric}: missing from "
                    f"{'the baseline' if base_value is None else 'this run'}, not compared"
                )
                continue
            report.movements.append(
                Movement(
                    slice_name=slice_name,
                    metric=metric,
                    baseline=base_value,
                    current=new_value,
                    regression=metric_spec.regression(base_value, new_value),
                    limit=metric_spec.limit,
                    relative=metric_spec.relative,
                )
            )

    report.movements.extend(_aggregate_movements(current, baseline, spec))
    return report


def _aggregate_movements(
    current: Metrics, baseline: Baseline, spec: dict[str, MetricSpec]
) -> list[Movement]:
    """The mean across the slices both runs share. Comparing over anything
    else would let the aggregate move because the slice set moved."""
    shared = sorted(set(current) & set(baseline.metrics))
    movements: list[Movement] = []
    for metric, metric_spec in spec.items():
        if metric_spec.aggregate_limit is None:
            continue
        pairs = [
            (baseline.metrics[s][metric], current[s][metric])
            for s in shared
            if metric in baseline.metrics[s] and metric in current[s]
        ]
        if not pairs:
            continue
        base_mean = fmean(p[0] for p in pairs)
        new_mean = fmean(p[1] for p in pairs)
        movements.append(
            Movement(
                slice_name=AGGREGATE,
                metric=metric,
                baseline=base_mean,
                current=new_mean,
                regression=metric_spec.regression(base_mean, new_mean),
                limit=metric_spec.aggregate_limit,
                relative=metric_spec.relative,
            )
        )
    return movements
