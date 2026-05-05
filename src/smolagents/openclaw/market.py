"""Synthetic affiliate-marketing market used for offline training.

OpenClaw needs *some* environment to query each simulated day. In production
that's a real analytics pipeline (GA4, partner APIs, ...) plugged in via
``OpenClawConfig.metrics_provider``. For tests, examples, and the default
``run-day`` loop we use this deterministic-with-noise simulator.

The simulator is intentionally non-trivial: each lever has a different
elasticity (e.g. CTR scales sub-linearly past a saturation point, AOV faces
diminishing returns), so naive "push every lever to infinity" strategies don't
win - the optimizer has to find a balance, which is the whole point.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .niches import Niche
from .revenue import NicheParams, compute_revenue


__all__ = ["SyntheticMarket", "MarketProvider"]


class MarketProvider:
    """Protocol for anything that can answer "what revenue did niche X earn today"."""

    def observe(self, niche: Niche, params: NicheParams, day: int) -> dict[str, float]:
        raise NotImplementedError


@dataclass
class _Saturation:
    """Diminishing-returns shaping for a single lever.

    Past ``soft_cap`` the lever's effective value is dampened by a logistic
    so that pushing it further yields ever-smaller real-world gains.
    """

    soft_cap: float
    sharpness: float = 1.0

    def shape(self, x: float) -> float:
        if x <= self.soft_cap:
            return x
        excess = x - self.soft_cap
        return self.soft_cap + math.tanh(excess * self.sharpness / self.soft_cap) * self.soft_cap


class SyntheticMarket(MarketProvider):
    """Deterministic-with-seed market simulator.

    The simulator applies per-lever saturations on top of the closed-form
    revenue to produce *realized* metrics. Volatility is drawn from a Gaussian
    seeded by ``(day, niche.slug)`` so two runs with the same seed are
    bit-identical - critical for reproducible CI.
    """

    def __init__(self, seed: int = 1337):
        self.seed = seed
        self._saturations = {
            "traffic": _Saturation(soft_cap=5000.0),
            "ctr": _Saturation(soft_cap=0.10),
            "cr": _Saturation(soft_cap=0.05),
            "aov": _Saturation(soft_cap=400.0),
            "commission": _Saturation(soft_cap=0.30),
        }

    def _shape(self, params: NicheParams) -> NicheParams:
        return NicheParams(
            traffic=self._saturations["traffic"].shape(params.traffic),
            ctr=self._saturations["ctr"].shape(params.ctr),
            cr=self._saturations["cr"].shape(params.cr),
            aov=self._saturations["aov"].shape(params.aov),
            commission=self._saturations["commission"].shape(params.commission)
            if params.commission < 1.0
            else params.commission,
            refund=params.refund,
            ltv_multiplier=params.ltv_multiplier,
        )

    def _noise(self, niche: Niche, day: int) -> float:
        rng = random.Random(f"{self.seed}|{day}|{niche.slug}")
        # Centered around 1.0; clamp to [0.5, 1.5] so a single bad day can't
        # drown out the lever-search signal entirely.
        n = rng.gauss(1.0, niche.volatility)
        return min(max(n, 0.5), 1.5)

    def observe(self, niche: Niche, params: NicheParams, day: int) -> dict[str, float]:
        shaped = self._shape(params)
        rev = compute_revenue(niche, shaped) * self._noise(niche, day)
        clicks = shaped.traffic * shaped.ctr
        conversions = clicks * shaped.cr
        return {
            "traffic": shaped.traffic,
            "clicks": clicks,
            "conversions": conversions,
            "revenue": rev,
            "epc": (rev / clicks) if clicks > 0 else 0.0,
            "rpm": (rev / shaped.traffic * 1000.0) if shaped.traffic > 0 else 0.0,
        }
