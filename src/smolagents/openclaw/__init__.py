"""OpenClaw: an affiliate-revenue engine running on smolagents.

OpenClaw stitches together ten niche-specific :class:`smolagents.CodeAgent`
instances behind a daily *observe-and-tweak* optimizer, all backed by a
SQLite :class:`PersistentMemory` so the system retains state across runs.
The end goal is the closed-form revenue formula learned by
:class:`RevenueFormula`.

Quick start::

    from smolagents.openclaw import OpenClawOrchestrator

    with OpenClawOrchestrator() as oc:        # offline defaults: mock model + 10 niches
        oc.run(days=30)
        print(oc.render_formula())

See :mod:`smolagents.openclaw.cli` for the ``openclaw`` command-line entry point.
"""

from .agents import NicheAgent, build_niche_agent
from .config import ModelConfig, OpenClawConfig, load_config
from .market import MarketProvider, SyntheticMarket
from .mock_model import MockNicheModel
from .niches import DEFAULT_NICHES, Niche, niche_by_slug
from .optimizer import DailyOptimizer, DayReport
from .orchestrator import OpenClawOrchestrator, build_model_factory
from .persistent_memory import Observation, PersistentMemory, Tweak
from .revenue import NicheParams, RevenueFormula, compute_revenue


__all__ = [
    "DEFAULT_NICHES",
    "DailyOptimizer",
    "DayReport",
    "MarketProvider",
    "MockNicheModel",
    "ModelConfig",
    "Niche",
    "NicheAgent",
    "NicheParams",
    "Observation",
    "OpenClawConfig",
    "OpenClawOrchestrator",
    "PersistentMemory",
    "RevenueFormula",
    "SyntheticMarket",
    "Tweak",
    "build_model_factory",
    "build_niche_agent",
    "compute_revenue",
    "load_config",
    "niche_by_slug",
]
