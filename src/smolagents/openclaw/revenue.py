"""Affiliate-marketing revenue formula and parameter learning.

The portfolio revenue is the sum across niches of:

    R_n = T_n * CTR_n * CR_n * V_n * (1 - refund_n) * LTV_n

where ``V_n`` is value-per-conversion (AOV * commission for rate-based niches,
or the flat CPA bounty for finance-style niches), and ``LTV_n`` is a
recurring-revenue multiplier (1.0 for one-shot niches).

The :class:`RevenueFormula` learns multiplicative *lever weights* per niche by
running coordinate-wise hill-climbing on the observed daily revenue. After
enough days the weights converge and ``describe()`` emits a closed-form
expression with the learned coefficients.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .niches import Niche


__all__ = ["NicheParams", "RevenueFormula", "compute_revenue"]


@dataclass
class NicheParams:
    """Live, tweakable parameters for a single niche.

    These start at the niche baseline values and the optimizer mutates them
    each day. Bounds are enforced so the search stays in physically plausible
    ranges (e.g. CTR can never exceed 100%).
    """

    traffic: float
    ctr: float
    cr: float
    aov: float
    commission: float
    refund: float
    ltv_multiplier: float = 1.0

    @classmethod
    def from_niche(cls, niche: Niche) -> "NicheParams":
        return cls(
            traffic=niche.base_traffic,
            ctr=niche.base_ctr,
            cr=niche.base_cr,
            aov=niche.base_aov,
            commission=niche.base_commission,
            refund=niche.refund_rate,
            ltv_multiplier=6.0 if niche.recurring else 1.0,
        )

    def clamp(self) -> "NicheParams":
        """Project parameters back into valid ranges in-place. Returns self."""
        self.traffic = max(0.0, self.traffic)
        self.ctr = min(max(self.ctr, 0.0), 1.0)
        self.cr = min(max(self.cr, 0.0), 1.0)
        self.aov = max(0.0, self.aov)
        self.commission = max(0.0, self.commission)
        self.refund = min(max(self.refund, 0.0), 1.0)
        self.ltv_multiplier = max(1.0, self.ltv_multiplier)
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "traffic": self.traffic,
            "ctr": self.ctr,
            "cr": self.cr,
            "aov": self.aov,
            "commission": self.commission,
            "refund": self.refund,
            "ltv_multiplier": self.ltv_multiplier,
        }


def compute_revenue(niche: Niche, params: NicheParams) -> float:
    """Closed-form daily revenue contribution from a single niche."""
    conversions = params.traffic * params.ctr * params.cr
    if niche.base_aov == 0.0:
        # CPA model: commission field is a flat USD bounty per conversion.
        value_per_conv = params.commission
    else:
        value_per_conv = params.aov * params.commission
    gross = conversions * value_per_conv * params.ltv_multiplier
    return gross * (1.0 - params.refund)


@dataclass
class RevenueFormula:
    """Coordinate-wise hill-climber over per-niche multiplicative lever weights.

    The optimizer maintains a weight vector ``w`` per niche (one weight per
    lever in ``Niche.levers``) and a step size. Each day it picks one lever,
    proposes ``w' = w * (1 +/- step)``, asks the simulator (or a real metrics
    callback) for the resulting revenue, and keeps the better of the two. The
    step shrinks geometrically so the search converges.

    The "formula" is the product of the niche baseline expression and the
    learned weights. ``describe()`` renders it.
    """

    weights: dict[str, dict[str, float]] = field(default_factory=dict)
    step_size: float = 0.10
    step_decay: float = 0.97
    history: list[dict[str, float]] = field(default_factory=list)
    min_step: float = 0.005

    def ensure_niche(self, niche: Niche) -> None:
        if niche.slug not in self.weights:
            self.weights[niche.slug] = {lever: 1.0 for lever in niche.levers}

    def apply(self, niche: Niche, params: NicheParams) -> NicheParams:
        """Return a new ``NicheParams`` with this formula's weights applied."""
        self.ensure_niche(niche)
        w = self.weights[niche.slug]
        scaled = NicheParams(
            traffic=params.traffic * w.get("traffic", 1.0),
            ctr=params.ctr * w.get("ctr", 1.0),
            cr=params.cr * w.get("cr", 1.0),
            aov=params.aov * w.get("aov", 1.0),
            commission=params.commission * w.get("commission", 1.0),
            refund=params.refund,
            ltv_multiplier=params.ltv_multiplier,
        )
        return scaled.clamp()

    def propose(
        self, niche: Niche, lever: str, direction: int
    ) -> dict[str, float]:
        """Return a candidate weight dict perturbed along ``lever``."""
        self.ensure_niche(niche)
        candidate = dict(self.weights[niche.slug])
        factor = 1.0 + direction * self.step_size
        candidate[lever] = max(0.05, candidate[lever] * factor)
        return candidate

    def accept(self, niche: Niche, weights: dict[str, float]) -> None:
        self.weights[niche.slug] = weights

    def decay_step(self) -> None:
        self.step_size = max(self.min_step, self.step_size * self.step_decay)

    def record(self, day: int, revenue: float) -> None:
        self.history.append({"day": day, "revenue": revenue, "step": self.step_size})

    def converged(self, window: int = 5, tol: float = 0.005) -> bool:
        """True once the trailing-window relative range falls below ``tol``."""
        if len(self.history) < window:
            return False
        tail = [h["revenue"] for h in self.history[-window:]]
        lo, hi = min(tail), max(tail)
        if hi == 0:
            return True
        return (hi - lo) / hi < tol

    def describe(self, niche: Niche) -> str:
        """Render the learned closed-form expression for one niche."""
        self.ensure_niche(niche)
        w = self.weights[niche.slug]
        if niche.base_aov == 0.0:
            value_term = f"{w['commission']:.3f}*c"
        else:
            value_term = f"{w['aov']:.3f}*A * {w['commission']:.3f}*c"
        ltv = "L" if niche.recurring else "1"
        return (
            f"R_{niche.slug} = {w.get('traffic', 1.0):.3f}*T * "
            f"{w.get('ctr', 1.0):.3f}*ctr * {w.get('cr', 1.0):.3f}*cr * "
            f"({value_term}) * {ltv} * (1-r)"
        )

    def describe_portfolio(self, niches: list[Niche]) -> str:
        body = "\n  + ".join(self.describe(n) for n in niches)
        return "Revenue =\n  + " + body

    def total_lift(self) -> float:
        """Geometric mean lift across all niche/lever weights vs baseline.

        A value > 1.0 means the formula has learned to amplify the baseline.
        """
        all_w: list[float] = []
        for d in self.weights.values():
            all_w.extend(d.values())
        if not all_w:
            return 1.0
        return math.exp(sum(math.log(max(w, 1e-9)) for w in all_w) / len(all_w))
