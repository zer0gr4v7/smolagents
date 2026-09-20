from pathlib import Path

import pytest

from smolagents.openclaw import (
    DEFAULT_NICHES,
    OpenClawConfig,
    OpenClawOrchestrator,
    PersistentMemory,
)
from smolagents.openclaw.market import MarketProvider
from smolagents.openclaw.niches import Niche
from smolagents.openclaw.revenue import NicheParams


class _ConstantMarket(MarketProvider):
    """Returns a fixed revenue regardless of params - lets us assert that
    the optimizer rejects every tweak (no improvement is possible)."""

    def observe(self, niche: Niche, params: NicheParams, day: int) -> dict[str, float]:
        return {"traffic": 1, "clicks": 1, "conversions": 1, "revenue": 100.0, "epc": 100.0, "rpm": 100.0}


class _UpwardMarket(MarketProvider):
    """Revenue strictly increases with weight magnitude - every tweak that
    pushes weights up is accepted."""

    def observe(self, niche: Niche, params: NicheParams, day: int) -> dict[str, float]:
        magnitude = params.traffic * params.ctr * params.cr * (params.aov + 1) * (params.commission + 1)
        return {
            "traffic": params.traffic,
            "clicks": params.traffic * params.ctr,
            "conversions": params.traffic * params.ctr * params.cr,
            "revenue": magnitude,
            "epc": 0.0,
            "rpm": 0.0,
        }


def test_run_day_advances_day_counter_and_records_observation():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg) as oc:
        assert oc.day == 0
        report = oc.run_day()
        assert oc.day == 1
        assert report.day == 1
        assert len(report.per_niche_revenue) == 10
        # Each niche has a recorded observation for day 1.
        for niche in DEFAULT_NICHES:
            obs = oc.memory.latest_observation(niche.slug)
            assert obs is not None and obs.day == 1


def test_run_n_days_returns_report_per_day():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg) as oc:
        reports = oc.run(days=4)
        assert [r.day for r in reports] == [1, 2, 3, 4]


def test_constant_market_rejects_all_tweaks():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg, market=_ConstantMarket()) as oc:
        oc.run(days=3)
        # No accept means weights stay at 1.0 across the board.
        for slug, weights in oc.formula.weights.items():
            for v in weights.values():
                assert v == pytest.approx(1.0)


def test_upward_market_grows_lift_over_baseline():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg, market=_UpwardMarket()) as oc:
        oc.run(days=20)
        assert oc.formula.total_lift() > 1.10


def test_state_persists_across_orchestrator_restart(tmp_path: Path):
    db = tmp_path / "oc.db"
    cfg = OpenClawConfig(memory_path=str(db))
    with OpenClawOrchestrator(cfg) as oc:
        oc.run(days=5)
        weights_before = {k: dict(v) for k, v in oc.formula.weights.items()}
        day_before = oc.day
        lift_before = oc.formula.total_lift()
    with OpenClawOrchestrator(cfg) as oc2:
        assert oc2.day == day_before
        assert oc2.formula.total_lift() == pytest.approx(lift_before)
        assert oc2.formula.weights == weights_before


def test_render_formula_lists_all_ten_niches():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg) as oc:
        oc.run_day()
        text = oc.render_formula()
        for niche in DEFAULT_NICHES:
            assert f"R_{niche.slug}" in text


def test_run_until_converged_terminates_with_stable_market():
    cfg = OpenClawConfig()
    with OpenClawOrchestrator(cfg, market=_ConstantMarket()) as oc:
        reports = oc.run_until_converged(max_days=30, window=5)
        # Constant market means immediate convergence (after window days).
        assert len(reports) <= 30
        assert oc.formula.converged(window=5)


def test_orchestrator_uses_external_memory_without_owning_it():
    mem = PersistentMemory(":memory:")
    cfg = OpenClawConfig()
    oc = OpenClawOrchestrator(cfg, memory=mem)
    oc.run_day()
    oc.close()
    # External memory must still be usable after orchestrator closes.
    assert mem.latest_observation("outdoor_gear") is not None
    mem.close()
