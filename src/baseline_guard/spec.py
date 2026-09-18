"""What counts as a regression, per metric."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["lower", "higher"]


@dataclass(frozen=True)
class MetricSpec:
    """How one metric is allowed to move.

    ``limit`` is the per-slice budget: the amount a single slice may move in
    the wrong direction before the gate fails. ``aggregate_limit`` is the same
    budget for the mean across slices, and is usually tighter — an average that
    holds while one slice falls apart is the failure this tool exists to catch.
    """

    direction: Direction = "lower"
    limit: float | None = None
    aggregate_limit: float | None = None
    relative: bool = False

    def __post_init__(self) -> None:
        if self.direction not in ("lower", "higher"):
            raise ValueError(f"direction must be 'lower' or 'higher', got {self.direction!r}")
        for name in ("limit", "aggregate_limit"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")
        if self.limit is None and self.aggregate_limit is None:
            raise ValueError("a metric spec needs at least one of limit, aggregate_limit")

    def regression(self, baseline_value: float, current_value: float) -> float:
        """How far the metric moved in the wrong direction. Negative is an
        improvement, so a gate only ever fires on a positive number."""
        delta = current_value - baseline_value
        moved_wrong_way = delta if self.direction == "lower" else -delta
        if not self.relative:
            return moved_wrong_way
        denominator = abs(baseline_value)
        if denominator == 0:
            # A baseline of zero has no meaningful percentage; fall back to the
            # absolute move rather than dividing by zero or silently passing.
            return moved_wrong_way
        return moved_wrong_way / denominator

    def unit(self) -> str:
        return "%" if self.relative else ""


def spec_from_dict(raw: dict) -> dict[str, MetricSpec]:
    """Build a spec from parsed TOML/JSON, rejecting unknown keys rather than
    ignoring a typo that would silently disable a gate."""
    known = {"direction", "limit", "aggregate_limit", "relative"}
    specs: dict[str, MetricSpec] = {}
    for metric, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"metric {metric!r}: expected a table, got {type(body).__name__}")
        unknown = set(body) - known
        if unknown:
            raise ValueError(
                f"metric {metric!r}: unknown key(s) {sorted(unknown)}; "
                f"allowed: {sorted(known)}"
            )
        specs[metric] = MetricSpec(**body)
    if not specs:
        raise ValueError("the spec defines no metrics")
    return specs
