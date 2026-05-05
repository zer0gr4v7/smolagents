"""High-level entry point: ``OpenClawOrchestrator`` ties everything together.

Responsibilities:

* Build the persistent memory store from config.
* Build the model factory from config (mock / litellm / openai / hf).
* Construct the ten niche agents and the daily optimizer.
* Expose ``run_day()`` / ``run(days=N)`` / ``run_until_converged()``.
* Render the learned formula and a daily report.
"""

from __future__ import annotations

import os
from typing import Callable

from smolagents.models import Model

from .agents import NicheAgent, build_niche_agent
from .config import ModelConfig, OpenClawConfig
from .market import MarketProvider, SyntheticMarket
from .mock_model import MockNicheModel
from .niches import Niche
from .optimizer import DailyOptimizer, DayReport
from .persistent_memory import PersistentMemory
from .revenue import RevenueFormula


__all__ = ["OpenClawOrchestrator", "build_model_factory"]


def build_model_factory(model_cfg: ModelConfig) -> Callable[[Niche], Model]:
    """Translate a ``ModelConfig`` into a per-niche model factory.

    Real model classes are imported lazily so a ``mock`` config never pulls in
    optional deps like ``litellm`` or ``openai``.
    """
    if model_cfg.type == "mock":
        return lambda niche: MockNicheModel(slug=niche.slug)

    api_key = os.getenv(model_cfg.api_key_env) if model_cfg.api_key_env else None

    if model_cfg.type == "litellm":
        from smolagents.models import LiteLLMModel

        def _factory(niche: Niche) -> Model:
            return LiteLLMModel(
                model_id=model_cfg.model_id,
                api_key=api_key,
                api_base=model_cfg.api_base,
                **model_cfg.extra,
            )
        return _factory

    if model_cfg.type == "openai":
        from smolagents.models import OpenAIModel

        def _factory(niche: Niche) -> Model:
            return OpenAIModel(
                model_id=model_cfg.model_id,
                api_key=api_key,
                api_base=model_cfg.api_base,
                **model_cfg.extra,
            )
        return _factory

    if model_cfg.type == "inference_client":
        from smolagents.models import InferenceClientModel

        def _factory(niche: Niche) -> Model:
            return InferenceClientModel(
                model_id=model_cfg.model_id,
                token=api_key,
                provider=model_cfg.provider,
                **model_cfg.extra,
            )
        return _factory

    raise ValueError(f"Unknown model type: {model_cfg.type!r}")


class OpenClawOrchestrator:
    """Top-level revenue-engine controller.

    The orchestrator is intentionally cheap to construct: tests build it with
    an in-memory database and a fixed seed, run a few days, and assert on the
    learned formula. Production callers point ``memory_path`` at a real file
    and let it grow over weeks.
    """

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        memory: PersistentMemory | None = None,
        market: MarketProvider | None = None,
    ):
        self.config = config or OpenClawConfig()
        self.memory = memory or PersistentMemory(self.config.memory_path)
        self._owns_memory = memory is None
        self.market = market or SyntheticMarket(seed=self.config.seed)

        model_factory = build_model_factory(self.config.model)
        self.fleet: list[NicheAgent] = [
            build_niche_agent(
                niche,
                model=model_factory(niche),
                max_steps=self.config.max_steps_per_day,
            )
            for niche in self.config.niches
        ]
        self.formula = RevenueFormula()
        self.optimizer = DailyOptimizer(
            fleet=self.fleet,
            memory=self.memory,
            formula=self.formula,
            market=self.market,
        )

    # ---- driving the loop ------------------------------------------------

    def run_day(self) -> DayReport:
        return self.optimizer.run_day()

    def run(self, days: int) -> list[DayReport]:
        return self.optimizer.run(days)

    def run_until_converged(self, max_days: int = 200, window: int = 7) -> list[DayReport]:
        return self.optimizer.run_until_converged(max_days=max_days, window=window)

    # ---- inspection ------------------------------------------------------

    @property
    def day(self) -> int:
        return self.optimizer.day

    def latest_report(self) -> str:
        per_niche = []
        latest_day = 0
        total = 0.0
        for na in self.fleet:
            obs = self.memory.latest_observation(na.slug)
            if obs:
                rev = obs.metrics.get("revenue", 0.0)
                per_niche.append(f"  {na.slug:>20s}: ${rev:>10,.2f}")
                latest_day = max(latest_day, obs.day)
                total += rev
        if not per_niche:
            return "No days run yet."
        if self.formula.history:
            step = self.formula.history[-1]["step"]
        else:
            step = self.formula.step_size
        return (
            f"Day {latest_day} | total ${total:,.2f} | "
            f"step={step:.4f} | lift={self.formula.total_lift():.3f}\n"
            + "\n".join(per_niche)
        )

    def render_formula(self) -> str:
        return self.formula.describe_portfolio([na.niche for na in self.fleet])

    # ---- lifecycle -------------------------------------------------------

    def close(self) -> None:
        if self._owns_memory:
            self.memory.close()

    def __enter__(self) -> "OpenClawOrchestrator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
