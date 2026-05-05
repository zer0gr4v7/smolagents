"""``openclaw`` command-line interface.

Subcommands:
    init           Write a starter ``openclaw.yaml`` next to the current dir.
    run-day        Advance the simulation by one day, print the report.
    run            Run for N days (``--days 30``), print final report + formula.
    converge       Run until the trailing-window revenue plateaus, print formula.
    formula        Print the currently-learned revenue formula.
    status         Show the latest day's per-niche revenue.

All subcommands accept ``--config PATH`` (default: ``./openclaw.yaml`` if it
exists, else the curated defaults) and ``--db PATH`` (overrides the memory
path from the config).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import OpenClawConfig, load_config
from .orchestrator import OpenClawOrchestrator


__all__ = ["main"]


_STARTER_YAML = """# OpenClaw affiliate-revenue engine config.
# Defaults to the curated 10-niche portfolio with the offline mock model so it
# runs without API keys. Swap `model.type` to litellm/openai/inference_client
# to use a real LLM.

memory_path: ./openclaw.db
seed: 1337
max_steps_per_day: 4

model:
  type: mock
  # model_id: gpt-4o-mini
  # api_key_env: OPENAI_API_KEY

# Uncomment to override one or more curated niches, or to add a new one.
# niches:
#   - slug: outdoor_gear
#     base_traffic: 2200
"""


def _load(args: argparse.Namespace) -> OpenClawConfig:
    if args.config:
        cfg = load_config(args.config)
    elif Path("openclaw.yaml").exists():
        cfg = load_config("openclaw.yaml")
    else:
        cfg = OpenClawConfig()
    if args.db:
        cfg.memory_path = args.db
    return cfg


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path or "openclaw.yaml")
    if target.exists() and not args.force:
        print(f"refusing to overwrite existing {target}; pass --force to replace", file=sys.stderr)
        return 1
    target.write_text(_STARTER_YAML, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def _cmd_run_day(args: argparse.Namespace) -> int:
    cfg = _load(args)
    with OpenClawOrchestrator(cfg) as oc:
        report = oc.run_day()
        print(report)
        print(oc.latest_report())
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = _load(args)
    with OpenClawOrchestrator(cfg) as oc:
        reports = oc.run(args.days)
        for r in reports:
            print(r)
        print()
        print(oc.latest_report())
        print()
        print(oc.render_formula())
    return 0


def _cmd_converge(args: argparse.Namespace) -> int:
    cfg = _load(args)
    with OpenClawOrchestrator(cfg) as oc:
        reports = oc.run_until_converged(max_days=args.max_days, window=args.window)
        print(f"converged after {len(reports)} days")
        print(oc.latest_report())
        print()
        print(oc.render_formula())
    return 0


def _cmd_formula(args: argparse.Namespace) -> int:
    cfg = _load(args)
    with OpenClawOrchestrator(cfg) as oc:
        print(oc.render_formula())
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = _load(args)
    with OpenClawOrchestrator(cfg) as oc:
        print(oc.latest_report())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclaw", description="Affiliate-revenue engine on smolagents.")
    parser.add_argument("--config", help="Path to openclaw.yaml (default: ./openclaw.yaml if present)")
    parser.add_argument("--db", help="Override memory_path from the config")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Write a starter openclaw.yaml")
    p_init.add_argument("path", nargs="?", default=None)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_run_day = sub.add_parser("run-day", help="Advance one simulated day")
    p_run_day.set_defaults(func=_cmd_run_day)

    p_run = sub.add_parser("run", help="Run for N days")
    p_run.add_argument("--days", type=int, default=30)
    p_run.set_defaults(func=_cmd_run)

    p_conv = sub.add_parser("converge", help="Run until revenue plateaus")
    p_conv.add_argument("--max-days", type=int, default=200)
    p_conv.add_argument("--window", type=int, default=7)
    p_conv.set_defaults(func=_cmd_converge)

    p_form = sub.add_parser("formula", help="Print the learned formula")
    p_form.set_defaults(func=_cmd_formula)

    p_stat = sub.add_parser("status", help="Show latest report")
    p_stat.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
