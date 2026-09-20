"""Niche and orchestrator agents - thin wrappers around smolagents.

Each :class:`NicheAgent` owns one of the ten affiliate verticals. It is a
real :class:`smolagents.CodeAgent` so users can inspect/replay it through the
standard smolagents tooling, but its decision logic is delegated to the
:class:`~smolagents.openclaw.optimizer.DailyOptimizer`. The agent's job is
narrative + persistence: read the optimizer's decision, record it to the
:class:`~smolagents.openclaw.persistent_memory.PersistentMemory`, and surface
a journal note that future days can read back.

The :class:`OpenClawOrchestrator` is the manager. It holds all ten niche
agents, the shared persistent memory, the optimizer, and the market provider,
and it exposes ``run_day()`` and ``run_until_converged()`` to the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smolagents.agents import CodeAgent
from smolagents.models import Model

from .mock_model import MockNicheModel
from .niches import DEFAULT_NICHES, Niche
from .persistent_memory import PersistentMemory
from .revenue import NicheParams


__all__ = ["NicheAgent", "build_niche_agent"]


@dataclass
class NicheAgent:
    """Bundle of (niche, smolagents CodeAgent, live params)."""

    niche: Niche
    agent: CodeAgent
    params: NicheParams = field(init=False)

    def __post_init__(self) -> None:
        self.params = NicheParams.from_niche(self.niche)

    @property
    def slug(self) -> str:
        return self.niche.slug

    def hydrate(self, memory: PersistentMemory) -> None:
        """Restore live params from the persistent store, if present.

        Called once on orchestrator start-up so a re-launched run picks up
        exactly where the last day left off.
        """
        saved = memory.get_state(self.slug, "params")
        if saved:
            self.params = NicheParams(**saved).clamp()

    def persist(self, memory: PersistentMemory) -> None:
        memory.set_state(self.slug, "params", self.params.as_dict())


def build_niche_agent(
    niche: Niche,
    model: Model | None = None,
    max_steps: int = 4,
) -> NicheAgent:
    """Construct a smolagents-backed agent for one niche.

    The agent is configured with ``name`` and ``description`` so it can be
    used as a *managed agent* under the orchestrator (smolagents convention).
    """
    code_agent = CodeAgent(
        tools=[],
        model=model or MockNicheModel(slug=niche.slug),
        max_steps=max_steps,
        name=niche.slug,
        description=(
            f"Affiliate-marketing operator for the '{niche.title}' vertical. "
            f"Programs: {', '.join(niche.affiliate_programs)}."
        ),
        verbosity_level=0,
    )
    return NicheAgent(niche=niche, agent=code_agent)


def build_default_fleet(model_factory=None) -> list[NicheAgent]:
    """Spin up one ``NicheAgent`` per default niche.

    Args:
        model_factory: Optional callable ``(niche) -> Model``. If omitted, every
            agent gets a per-slug :class:`MockNicheModel` so the fleet runs
            offline.
    """
    fleet: list[NicheAgent] = []
    for niche in DEFAULT_NICHES:
        model = model_factory(niche) if model_factory else None
        fleet.append(build_niche_agent(niche, model=model))
    return fleet
