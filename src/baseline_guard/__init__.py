"""Fail a build when a model regressed on any slice, not just on average."""
from .baseline import Baseline
from .compare import AGGREGATE, GateReport, Movement, RegressionError, check
from .spec import MetricSpec, spec_from_dict

__version__ = "0.1.0"

__all__ = [
    "AGGREGATE",
    "Baseline",
    "GateReport",
    "MetricSpec",
    "Movement",
    "RegressionError",
    "check",
    "spec_from_dict",
]
