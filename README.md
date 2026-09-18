# baseline-guard

[![ci](https://github.com/kulykivska/baseline-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/kulykivska/baseline-guard/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Fail a build when a model regressed on **any slice**, not just on average.

A model that got better on average and fell apart on one segment is a model that got worse. An aggregate metric cannot see that, and an aggregate gate waves it through — which is how a regression reaches production with a green CI run behind it.

`baseline-guard` freezes per-slice metrics into a file, compares each run against it, and exits non-zero when any slice moves past its budget.

```bash
pip install git+https://github.com/kulykivska/baseline-guard
```

No dependencies beyond the standard library.

## Usage

```bash
baseline-guard save results.json --baseline baseline.json --note "after the damper change"
baseline-guard check results.json --baseline baseline.json --spec spec.toml --max-age-days 30
```

`results.json` is whatever your evaluation already produces, as `{slice: {metric: value}}`:

```json
{
  "australian-gp-2026": {"mae": 1.46, "podium_hits": 3},
  "chinese-gp-2026":    {"mae": 3.10, "podium_hits": 2},
  "japanese-gp-2026":   {"mae": 0.71, "podium_hits": 3}
}
```

`spec.toml` says how far each metric may move:

```toml
[metrics.mae]
direction = "lower"        # lower is better
limit = 0.4                # per-slice budget
aggregate_limit = 0.2      # tighter budget for the mean across slices

[metrics.podium_hits]
direction = "higher"
limit = 1
```

Real output from `demo/`:

```
[pass] australian-gp-2026 / mae: 1.46 -> 1.46 (+0, budget 0.4)
[pass] australian-gp-2026 / podium_hits: 3 -> 3 (+0, budget 1)
[FAIL] chinese-gp-2026 / mae: 2.6 -> 3.1 (+0.5, budget 0.4)
[pass] chinese-gp-2026 / podium_hits: 2 -> 2 (+0, budget 1)
[pass] japanese-gp-2026 / mae: 0.71 -> 0.71 (+0, budget 0.4)
[pass] japanese-gp-2026 / podium_hits: 3 -> 3 (+0, budget 1)
[pass] <all slices> / mae: 1.59 -> 1.757 (+0.1667, budget 0.2)
[warn] the baseline is 27 days old (limit 14); re-freeze it before trusting this
       comparison, or it measures its own age rather than this change
```

Exit code 1, because one race regressed by 0.5 against a budget of 0.4. Note that the aggregate passed: average MAE moved 1.59 → 1.76, inside its 0.2 budget. An aggregate-only gate would have shipped this.

## In Python

```python
from baseline_guard import Baseline, MetricSpec, check

report = check(
    current_metrics,
    Baseline.load("baseline.json"),
    {"mae": MetricSpec(direction="lower", limit=0.4, aggregate_limit=0.2)},
    max_age_days=30,
)
report.raise_for_status()   # RegressionError naming every slice that failed
```

## The opinions it holds

**A baseline is never overwritten by accident.** `save` refuses to clobber an existing file without `--force`. Re-freezing the baseline is the one action that makes a regression disappear, so it should take a deliberate keystroke, not a default.

**A stale baseline measures its own age.** Each baseline records the date it was frozen. Past `--max-age-days` you get a warning, because a comparison against numbers from three months ago is telling you about three months of drift, not about this change.

**A slice that vanished is a failure, not a pass.** If your run stops covering a segment, the gate fails rather than silently comparing fewer things. Shrinking the evaluation is the easiest way to get a green run.

**A new slice is reported, not failed.** There is nothing to compare it against yet, so it prints as a note and does not block.

**The aggregate is computed over shared slices only.** Otherwise the mean moves because the slice set moved and you spend an afternoon debugging the model instead of the harness.

**A typo in the spec is an error.** An unknown key raises instead of being ignored, because a silently disabled gate is worse than no gate.

## Why not just a pytest assertion

You can write `assert mae < 2.5` and many teams should. It stops being enough when the threshold has to be per-slice, when "how much worse is allowed" differs from "how good is acceptable", and when you want the failure to name every segment that moved rather than the first one. This is that assertion, for a table of metrics, with the bookkeeping already done.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## License

MIT
