"""The daily observe-and-tweak loop.

For each niche the optimizer:

1. Picks the next *lever* to perturb (round-robin through the niche's lever
   list, with the ``+/-`` direction inferred from the prior tweak's outcome).
2. Builds the perturbed weight vector and asks the market provider what
   revenue results from the new effective parameters.
3. Compares with the unperturbed (baseline) revenue from the *same* day so
   the comparison isolates the lever's effect from market noise.
4. Keeps the better weights, records the observation + tweak in persistent
   memory, and shrinks the step size on accept.

Run for enough days and the per-niche weight vector stabilizes. The
:class:`~smolagents.openclaw.revenue.RevenueFormula` then prints the closed
form with the learned coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agents import NicheAgent
from .market import MarketProvider, SyntheticMarket
from .persistent_memory import PersistentMemory
from .revenue import NicheParams, RevenueFormula


__all__ = ["DailyOptimizer", "DayReport"]


@dataclass
class DayReport:
    day: int
    per_niche_revenue: dict[str, float]
    accepted_tweaks: int
    rejected_tweaks: int
    total_revenue: float

    def __str__(self) -> str:
        return (
            f"day={self.day} total=${self.total_revenue:,.2f} "
            f"accepted={self.accepted_tweaks} rejected={self.rejected_tweaks}"
        )


@dataclass
class _LeverState:
    """Per-(niche, lever) state for the round-robin search."""

    direction: int = 1  # +1 or -1
    consecutive_rejects: int = 0


@dataclass
class DailyOptimizer:
    """Coordinator for one run of the observe-and-tweak loop."""

    fleet: list[NicheAgent]
    memory: PersistentMemory
    formula: RevenueFormula = field(default_factory=RevenueFormula)
    market: MarketProvider = field(default_factory=SyntheticMarket)
    _lever_state: dict[tuple[str, str], _LeverState] = field(default_factory=dict)
    _lever_cursor: dict[str, int] = field(default_factory=dict)
    _day: int = 0

    def __post_init__(self) -> None:
        # Restore optimizer state if the memory has it.
        saved_weights = self.memory.get_state("__formula__", "weights")
        if saved_weights:
            self.formula.weights = saved_weights
        saved_step = self.memory.get_state("__formula__", "step_size")
        if saved_step:
            self.formula.step_size = saved_step
        saved_day = self.memory.get_state("__formula__", "day")
        if saved_day:
            self._day = saved_day
        for niche_agent in self.fleet:
            niche_agent.hydrate(self.memory)
            self._lever_cursor.setdefault(niche_agent.slug, 0)
            self.formula.ensure_niche(niche_agent.niche)

    # ---- internals -------------------------------------------------------

    def _next_lever(self, niche_agent: NicheAgent) -> str:
        levers = niche_agent.niche.levers
        idx = self._lever_cursor[niche_agent.slug] % len(levers)
        self._lever_cursor[niche_agent.slug] = idx + 1
        return levers[idx]

    def _state(self, slug: str, lever: str) -> _LeverState:
        key = (slug, lever)
        if key not in self._lever_state:
            self._lever_state[key] = _LeverState()
        return self._lever_state[key]

    def _revenue_for(self, niche_agent: NicheAgent, weights: dict[str, float], day: int) -> float:
        """Apply ``weights`` to the live params and ask the market for revenue."""
        backup = self.formula.weights[niche_agent.slug]
        self.formula.weights[niche_agent.slug] = weights
        try:
            scaled = self.formula.apply(niche_agent.niche, niche_agent.params)
            obs = self.market.observe(niche_agent.niche, scaled, day)
        finally:
            self.formula.weights[niche_agent.slug] = backup
        return obs["revenue"]

    # ---- public API ------------------------------------------------------

    def step_niche(self, niche_agent: NicheAgent, day: int) -> tuple[float, bool]:
        """Run one observe+tweak cycle for a single niche.

        Returns ``(revenue, accepted)``.
        """
        slug = niche_agent.slug
        niche = niche_agent.niche

        baseline_weights = dict(self.formula.weights[slug])
        baseline_rev = self._revenue_for(niche_agent, baseline_weights, day)

        lever = self._next_lever(niche_agent)
        state = self._state(slug, lever)
        candidate = self.formula.propose(niche, lever, state.direction)
        candidate_rev = self._revenue_for(niche_agent, candidate, day)

        accepted = candidate_rev > baseline_rev
        if accepted:
            self.formula.accept(niche, candidate)
            kept_rev = candidate_rev
            state.consecutive_rejects = 0
        else:
            kept_rev = baseline_rev
            state.consecutive_rejects += 1
            # Two strikes -> flip direction so the next visit explores the
            # other side of the current weight.
            if state.consecutive_rejects >= 2:
                state.direction *= -1
                state.consecutive_rejects = 0

        # Persist the *kept* metrics so notes/dashboards reflect what we shipped.
        kept_params = self.formula.apply(niche, niche_agent.params)
        kept_obs = self.market.observe(niche, kept_params, day)
        kept_obs["lever_tested"] = lever  # type: ignore[assignment]
        kept_obs["accepted"] = float(accepted)
        self.memory.record_observation(slug, day, kept_obs)
        self.memory.record_tweak(
            slug,
            day,
            lever=lever,
            direction=state.direction,
            accepted=accepted,
            delta_revenue=candidate_rev - baseline_rev,
        )
        if accepted:
            self.memory.add_note(
                slug,
                day,
                f"day {day}: accepted {lever:>10s} {'+' if state.direction > 0 else '-'} -> "
                f"+${candidate_rev - baseline_rev:,.2f}",
            )
        niche_agent.persist(self.memory)
        return kept_rev, accepted

    def run_day(self) -> DayReport:
        """Advance the simulation by one day across the entire fleet."""
        self._day += 1
        per_niche: dict[str, float] = {}
        accepted = 0
        for na in self.fleet:
            rev, ok = self.step_niche(na, self._day)
            per_niche[na.slug] = rev
            if ok:
                accepted += 1
        rejected = len(self.fleet) - accepted
        if accepted > 0:
            self.formula.decay_step()
        total = sum(per_niche.values())
        self.formula.record(self._day, total)
        # Snapshot optimizer state so a crashed run can resume.
        self.memory.set_state("__formula__", "weights", self.formula.weights)
        self.memory.set_state("__formula__", "step_size", self.formula.step_size)
        self.memory.set_state("__formula__", "day", self._day)
        return DayReport(
            day=self._day,
            per_niche_revenue=per_niche,
            accepted_tweaks=accepted,
            rejected_tweaks=rejected,
            total_revenue=total,
        )

    def run(self, days: int) -> list[DayReport]:
        return [self.run_day() for _ in range(days)]

    def run_until_converged(self, max_days: int = 200, window: int = 7) -> list[DayReport]:
        reports: list[DayReport] = []
        for _ in range(max_days):
            reports.append(self.run_day())
            if len(reports) >= window and self.formula.converged(window=window):
                break
        return reports

    @property
    def day(self) -> int:
        return self._day
