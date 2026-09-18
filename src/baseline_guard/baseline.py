"""The recorded baseline: metrics per slice, plus when they were recorded."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

Metrics = dict[str, dict[str, float]]


@dataclass(frozen=True)
class Baseline:
    """A frozen set of per-slice metrics.

    ``recorded_at`` is what makes a stale baseline visible. A baseline nobody
    has re-frozen for months stops measuring the change under review and starts
    measuring its own age, and the gate should say so out loud.
    """

    metrics: Metrics
    recorded_at: date | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def slices(self) -> list[str]:
        return sorted(self.metrics)

    def age_days(self, today: date | None = None) -> int | None:
        if self.recorded_at is None:
            return None
        return ((today or datetime.now(timezone.utc).date()) - self.recorded_at).days

    def to_dict(self) -> dict:
        payload: dict = {"metrics": self.metrics}
        if self.recorded_at is not None:
            payload["recorded_at"] = self.recorded_at.isoformat()
        if self.note:
            payload["note"] = self.note
        payload.update(self.extra)
        return payload

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def from_dict(cls, data: dict) -> "Baseline":
        if "metrics" not in data:
            raise ValueError("baseline file has no 'metrics' key")
        recorded = data.get("recorded_at")
        known = {"metrics", "recorded_at", "note"}
        return cls(
            metrics=_coerce_metrics(data["metrics"]),
            recorded_at=date.fromisoformat(recorded) if recorded else None,
            note=data.get("note", ""),
            extra={k: v for k, v in data.items() if k not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "Baseline":
        return cls.from_dict(json.loads(Path(path).read_text()))

    @classmethod
    def record(
        cls, metrics: Metrics, *, note: str = "", today: date | None = None
    ) -> "Baseline":
        return cls(
            metrics=_coerce_metrics(metrics),
            recorded_at=today or datetime.now(timezone.utc).date(),
            note=note,
        )


def _coerce_metrics(raw: dict) -> Metrics:
    """Accept ints and numeric strings, reject anything that is not a number,
    so a malformed results file fails here rather than comparing as a string."""
    out: Metrics = {}
    for slice_name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(
                f"slice {slice_name!r}: expected a mapping of metric to number, "
                f"got {type(body).__name__}"
            )
        values: dict[str, float] = {}
        for metric, value in body.items():
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"slice {slice_name!r}, metric {metric!r}: not a number")
            try:
                values[metric] = float(value)
            except ValueError as exc:
                raise ValueError(
                    f"slice {slice_name!r}, metric {metric!r}: not a number ({value!r})"
                ) from exc
        out[slice_name] = values
    return out
