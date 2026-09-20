"""End-to-end OpenClaw demo - no API keys required.

Run::

    python examples/openclaw/run_demo.py

It boots a 10-niche fleet on the offline synthetic market, runs the daily
observe-and-tweak loop until revenue plateaus, then prints the learned
closed-form revenue formula and the per-niche final state.
"""

from __future__ import annotations

from smolagents.openclaw import OpenClawConfig, OpenClawOrchestrator


def main() -> None:
    config = OpenClawConfig()  # defaults: in-memory DB, mock model, 10 default niches.
    with OpenClawOrchestrator(config) as oc:
        reports = oc.run_until_converged(max_days=120, window=7)
        print(f"\nconverged after {len(reports)} days\n")
        print(oc.latest_report())
        print()
        print(oc.render_formula())
        print()
        print(f"Total geometric lift over baseline: {oc.formula.total_lift():.3f}x")


if __name__ == "__main__":
    main()
