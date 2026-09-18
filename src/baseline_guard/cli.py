"""baseline-guard command line: check a run, or freeze a new baseline."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from .baseline import Baseline
from .compare import check
from .spec import spec_from_dict


def _load_metrics(path: Path) -> dict:
    data = json.loads(path.read_text())
    # Accept both a bare {slice: {metric: value}} file and a baseline-shaped
    # one, so a saved baseline can be replayed as a run.
    return data["metrics"] if isinstance(data, dict) and "metrics" in data else data


def _load_spec(path: Path) -> dict:
    if path.suffix == ".toml":
        raw = tomllib.loads(path.read_text())
        return spec_from_dict(raw.get("metrics", raw))
    return spec_from_dict(json.loads(path.read_text()))


def _cmd_check(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(
            f"no baseline at {baseline_path}. Freeze one with:\n"
            f"  baseline-guard save {args.results} --baseline {baseline_path}",
            file=sys.stderr,
        )
        return 2

    report = check(
        _load_metrics(Path(args.results)),
        Baseline.load(baseline_path),
        _load_spec(Path(args.spec)),
        max_age_days=args.max_age_days,
    )
    print(report)
    if report.ok:
        print("\nOK: nothing regressed past its budget.")
        return 0
    print(f"\nBLOCKED: {len(report.failures)} regression(s), "
          f"{len(report.missing_slices)} missing slice(s).", file=sys.stderr)
    return 1


def _cmd_save(args: argparse.Namespace) -> int:
    path = Path(args.baseline)
    if path.exists() and not args.force:
        print(
            f"{path} already exists. A baseline is never overwritten by accident — "
            f"pass --force once you have confirmed the new numbers.",
            file=sys.stderr,
        )
        return 2
    Baseline.record(_load_metrics(Path(args.results)), note=args.note).save(path)
    print(f"baseline frozen -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="baseline-guard",
        description="Fail a build when a model regressed on any slice.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="compare a run against the baseline")
    c.add_argument("results", help="JSON file of {slice: {metric: value}}")
    c.add_argument("--baseline", default="baseline.json")
    c.add_argument("--spec", required=True, help="TOML or JSON spec of per-metric budgets")
    c.add_argument("--max-age-days", type=int, default=None,
                   help="warn when the baseline is older than this")
    c.set_defaults(func=_cmd_check)

    s = sub.add_parser("save", help="freeze a new baseline")
    s.add_argument("results", help="JSON file of {slice: {metric: value}}")
    s.add_argument("--baseline", default="baseline.json")
    s.add_argument("--note", default="", help="why this baseline was re-frozen")
    s.add_argument("--force", action="store_true", help="overwrite an existing baseline")
    s.set_defaults(func=_cmd_save)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
