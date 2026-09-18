from __future__ import annotations

import json
from datetime import date

import pytest

from baseline_guard import (
    AGGREGATE,
    Baseline,
    MetricSpec,
    RegressionError,
    check,
    spec_from_dict,
)
from baseline_guard.cli import main

MAE = {"mae": MetricSpec(direction="lower", limit=0.4)}


def _baseline(**slices: float) -> Baseline:
    return Baseline.record(
        {name: {"mae": value} for name, value in slices.items()}, today=date(2026, 1, 1)
    )


class TestPerSliceGate:
    def test_a_run_inside_the_budget_passes(self) -> None:
        report = check({"r1": {"mae": 2.3}}, _baseline(r1=2.0), MAE)
        assert report.ok, str(report)

    def test_a_single_slice_over_budget_fails(self) -> None:
        report = check({"r1": {"mae": 2.5}}, _baseline(r1=2.0), MAE)
        assert not report.ok
        assert [m.slice_name for m in report.failures] == ["r1"]

    def test_the_budget_boundary_is_inclusive(self) -> None:
        report = check({"r1": {"mae": 2.4}}, _baseline(r1=2.0), MAE)
        assert report.ok, str(report)

    def test_an_improvement_never_fails(self) -> None:
        report = check({"r1": {"mae": 0.1}}, _baseline(r1=2.0), MAE)
        assert report.ok
        assert report.movements[0].improved

    def test_a_good_average_does_not_rescue_a_broken_slice(self) -> None:
        """The reason this tool exists: one slice falling apart while the mean
        improves is exactly what an aggregate-only gate waves through."""
        report = check(
            {"r1": {"mae": 3.0}, "r2": {"mae": 0.5}, "r3": {"mae": 0.5}},
            _baseline(r1=2.0, r2=2.0, r3=2.0),
            MAE,
        )
        assert not report.ok
        assert [m.slice_name for m in report.failures] == ["r1"]


class TestDirection:
    def test_higher_is_better_fails_on_a_drop(self) -> None:
        spec = {"accuracy": MetricSpec(direction="higher", limit=0.02)}
        base = Baseline.record({"r1": {"accuracy": 0.90}}, today=date(2026, 1, 1))
        assert not check({"r1": {"accuracy": 0.80}}, base, spec).ok
        assert check({"r1": {"accuracy": 0.95}}, base, spec).ok

    def test_relative_limits_scale_with_the_baseline(self) -> None:
        spec = {"mae": MetricSpec(direction="lower", limit=0.10, relative=True)}
        # +5% passes, +20% does not, on the same absolute move at two scales.
        assert check({"r1": {"mae": 10.5}}, _baseline(r1=10.0), spec).ok
        assert not check({"r1": {"mae": 12.0}}, _baseline(r1=10.0), spec).ok

    def test_a_zero_baseline_falls_back_to_the_absolute_move(self) -> None:
        spec = {"mae": MetricSpec(direction="lower", limit=0.4, relative=True)}
        assert not check({"r1": {"mae": 1.0}}, _baseline(r1=0.0), spec).ok


class TestSliceSetChanges:
    def test_a_new_slice_is_reported_not_failed(self) -> None:
        report = check({"r1": {"mae": 2.0}, "r2": {"mae": 9.9}}, _baseline(r1=2.0), MAE)
        assert report.ok, str(report)
        assert report.new_slices == ["r2"]

    def test_a_vanished_slice_fails(self) -> None:
        """A run that quietly stopped covering part of the data must not pass
        by no longer being measured."""
        report = check({"r1": {"mae": 2.0}}, _baseline(r1=2.0, r2=2.0), MAE)
        assert not report.ok
        assert report.missing_slices == ["r2"]

    def test_a_metric_missing_from_one_side_is_warned_not_compared(self) -> None:
        base = Baseline.record({"r1": {"mae": 2.0}}, today=date(2026, 1, 1))
        report = check({"r1": {"rmse": 2.0}}, base, MAE)
        assert report.movements == []
        assert any("not compared" in w for w in report.warnings)


class TestAggregate:
    def test_the_aggregate_budget_can_fail_on_its_own(self) -> None:
        spec = {"mae": MetricSpec(direction="lower", limit=0.4, aggregate_limit=0.1)}
        report = check(
            {"r1": {"mae": 2.3}, "r2": {"mae": 2.3}}, _baseline(r1=2.0, r2=2.0), spec
        )
        assert not report.ok
        assert [m.slice_name for m in report.failures] == [AGGREGATE]

    def test_the_aggregate_uses_only_shared_slices(self) -> None:
        """Otherwise the mean moves because the slice set moved, not the model."""
        spec = {"mae": MetricSpec(direction="lower", limit=5.0, aggregate_limit=0.1)}
        report = check(
            {"r1": {"mae": 2.0}, "brand_new": {"mae": 50.0}}, _baseline(r1=2.0), spec
        )
        agg = [m for m in report.movements if m.slice_name == AGGREGATE]
        assert agg and agg[0].current == 2.0


class TestStaleBaseline:
    def test_an_old_baseline_warns_without_failing(self) -> None:
        report = check(
            {"r1": {"mae": 2.0}}, _baseline(r1=2.0), MAE,
            max_age_days=30, today=date(2026, 6, 1),
        )
        assert report.ok
        assert any("measures its own age" in w for w in report.warnings)

    def test_a_fresh_baseline_is_quiet(self) -> None:
        report = check(
            {"r1": {"mae": 2.0}}, _baseline(r1=2.0), MAE,
            max_age_days=30, today=date(2026, 1, 10),
        )
        assert not report.warnings

    def test_a_baseline_without_a_date_says_so(self) -> None:
        base = Baseline(metrics={"r1": {"mae": 2.0}})
        report = check({"r1": {"mae": 2.0}}, base, MAE, max_age_days=30)
        assert any("recorded_at" in w for w in report.warnings)


class TestReport:
    def test_raise_for_status_names_the_slice(self) -> None:
        report = check({"r1": {"mae": 5.0}}, _baseline(r1=2.0), MAE)
        with pytest.raises(RegressionError, match="r1"):
            report.raise_for_status()

    def test_raise_for_status_is_quiet_when_clean(self) -> None:
        check({"r1": {"mae": 2.0}}, _baseline(r1=2.0), MAE).raise_for_status()

    def test_a_movement_renders_both_numbers_and_the_budget(self) -> None:
        line = str(check({"r1": {"mae": 2.5}}, _baseline(r1=2.0), MAE).movements[0])
        assert "FAIL" in line and "2" in line and "budget" in line


class TestSpecValidation:
    def test_an_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown key"):
            spec_from_dict({"mae": {"direction": "lower", "limt": 0.4}})

    def test_a_spec_with_no_budget_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one of"):
            spec_from_dict({"mae": {"direction": "lower"}})

    def test_a_bad_direction_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            spec_from_dict({"mae": {"direction": "down", "limit": 0.4}})

    def test_a_negative_budget_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            spec_from_dict({"mae": {"limit": -1.0}})

    def test_an_empty_spec_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no metrics"):
            spec_from_dict({})


class TestBaselineIO:
    def test_round_trip_keeps_the_date_and_note(self, tmp_path) -> None:
        path = tmp_path / "baseline.json"
        Baseline.record({"r1": {"mae": 2.0}}, note="after the damper", today=date(2026, 3, 1)).save(path)
        loaded = Baseline.load(path)
        assert loaded.recorded_at == date(2026, 3, 1)
        assert loaded.note == "after the damper"
        assert loaded.metrics == {"r1": {"mae": 2.0}}

    def test_a_non_numeric_metric_is_rejected_on_load(self, tmp_path) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps({"metrics": {"r1": {"mae": "not a number"}}}))
        with pytest.raises(ValueError, match="not a number"):
            Baseline.load(path)

    def test_a_file_without_metrics_is_rejected(self, tmp_path) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps({"r1": {"mae": 2.0}}))
        with pytest.raises(ValueError, match="no 'metrics' key"):
            Baseline.load(path)


class TestCli:
    def _write(self, tmp_path, results, spec_toml="[metrics.mae]\ndirection='lower'\nlimit=0.4\n"):
        (tmp_path / "results.json").write_text(json.dumps(results))
        (tmp_path / "spec.toml").write_text(spec_toml)
        return tmp_path / "results.json", tmp_path / "spec.toml"

    def test_save_then_check_passes(self, tmp_path) -> None:
        results, spec = self._write(tmp_path, {"r1": {"mae": 2.0}})
        base = tmp_path / "baseline.json"
        assert main(["save", str(results), "--baseline", str(base)]) == 0
        assert main(["check", str(results), "--baseline", str(base), "--spec", str(spec)]) == 0

    def test_check_without_a_baseline_explains_how_to_make_one(self, tmp_path, capsys) -> None:
        results, spec = self._write(tmp_path, {"r1": {"mae": 2.0}})
        code = main(["check", str(results), "--baseline", str(tmp_path / "nope.json"), "--spec", str(spec)])
        assert code == 2
        assert "baseline-guard save" in capsys.readouterr().err

    def test_save_refuses_to_overwrite_without_force(self, tmp_path, capsys) -> None:
        results, _ = self._write(tmp_path, {"r1": {"mae": 2.0}})
        base = tmp_path / "baseline.json"
        assert main(["save", str(results), "--baseline", str(base)]) == 0
        assert main(["save", str(results), "--baseline", str(base)]) == 2
        assert "never overwritten by accident" in capsys.readouterr().err

    def test_check_exits_1_on_a_regression(self, tmp_path) -> None:
        results, spec = self._write(tmp_path, {"r1": {"mae": 2.0}})
        base = tmp_path / "baseline.json"
        main(["save", str(results), "--baseline", str(base)])
        (tmp_path / "worse.json").write_text(json.dumps({"r1": {"mae": 9.0}}))
        code = main(["check", str(tmp_path / "worse.json"), "--baseline", str(base), "--spec", str(spec)])
        assert code == 1

    def test_a_saved_baseline_can_be_replayed_as_a_run(self, tmp_path) -> None:
        results, spec = self._write(tmp_path, {"r1": {"mae": 2.0}})
        base = tmp_path / "baseline.json"
        main(["save", str(results), "--baseline", str(base)])
        assert main(["check", str(base), "--baseline", str(base), "--spec", str(spec)]) == 0
