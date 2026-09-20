"""The ten affiliate-marketing niches that the OpenClaw fleet monetizes.

The list is curated for: high diversity (so domain-level mistakes don't sink the
portfolio), an intentional mix of recurring vs one-shot commissions, and a
spread of average-order-values from low (apps) to high (finance/credit cards).

Each niche carries its own *baseline* economics and *volatility*; the daily
observe-and-tweak loop perturbs the live parameters and learns which levers
move revenue. See ``revenue.py`` for the formula those parameters feed into.
"""

from __future__ import annotations

from dataclasses import dataclass, field


__all__ = ["Niche", "DEFAULT_NICHES", "niche_by_slug"]


@dataclass(frozen=True)
class Niche:
    """A single affiliate-marketing vertical.

    Attributes:
        slug: Stable identifier used as the agent name and in the SQLite store.
        title: Human-readable display name.
        affiliate_programs: The programs we'd run against this niche IRL.
        base_traffic: Daily organic + paid sessions at parameter baseline.
        base_ctr: Click-through rate from page to merchant (0-1).
        base_cr: Conversion rate from click to purchase (0-1).
        base_aov: Average order value in USD.
        base_commission: Effective commission rate net of tier blends (0-1).
        refund_rate: Share of commissions clawed back (0-1).
        volatility: Multiplicative noise std-dev applied each simulated day.
        recurring: True for SaaS-style recurring commissions, False otherwise.
    """

    slug: str
    title: str
    affiliate_programs: tuple[str, ...]
    base_traffic: float
    base_ctr: float
    base_cr: float
    base_aov: float
    base_commission: float
    refund_rate: float = 0.03
    volatility: float = 0.15
    recurring: bool = False
    notes: str = ""
    levers: tuple[str, ...] = field(
        default=("traffic", "ctr", "cr", "aov", "commission"),
    )


DEFAULT_NICHES: tuple[Niche, ...] = (
    Niche(
        slug="outdoor_gear",
        title="Outdoor & Hiking Gear",
        affiliate_programs=("Amazon Associates", "REI Co-op", "Backcountry"),
        base_traffic=1800,
        base_ctr=0.045,
        base_cr=0.028,
        base_aov=140.0,
        base_commission=0.045,
        volatility=0.18,
        notes="High AOV; seasonal spikes around spring and Black Friday.",
    ),
    Niche(
        slug="home_office",
        title="Home Office & Productivity",
        affiliate_programs=("Amazon Associates", "Autonomous", "Fully"),
        base_traffic=2400,
        base_ctr=0.038,
        base_cr=0.022,
        base_aov=320.0,
        base_commission=0.04,
        volatility=0.12,
        notes="Standing desks, monitors, ergonomic chairs - high AOV one-shot.",
    ),
    Niche(
        slug="smart_home",
        title="Smart Home & IoT",
        affiliate_programs=("Amazon Associates", "Best Buy", "Wyze"),
        base_traffic=3200,
        base_ctr=0.052,
        base_cr=0.031,
        base_aov=85.0,
        base_commission=0.035,
        volatility=0.14,
        notes="Cheaper carts, but high cross-sell - bundles boost AOV.",
    ),
    Niche(
        slug="personal_finance",
        title="Personal Finance & Credit Cards",
        affiliate_programs=("CardRatings", "Bankrate", "Credible"),
        base_traffic=1500,
        base_ctr=0.062,
        base_cr=0.018,
        base_aov=0.0,  # CPA - no AOV, fixed bounty per approval
        base_commission=85.0,  # USD per approval
        refund_rate=0.08,
        volatility=0.22,
        notes="CPA bounty model; commission is a flat USD value, not a rate.",
    ),
    Niche(
        slug="web_hosting",
        title="Web Hosting & SaaS",
        affiliate_programs=("Cloudways", "Hostinger", "Bluehost"),
        base_traffic=900,
        base_ctr=0.071,
        base_cr=0.034,
        base_aov=58.0,
        base_commission=0.30,
        recurring=True,
        refund_rate=0.12,
        volatility=0.10,
        notes="Recurring monthly commissions - LTV multiplier matters.",
    ),
    Niche(
        slug="online_learning",
        title="Online Learning Platforms",
        affiliate_programs=("Coursera", "Skillshare", "Udemy"),
        base_traffic=2100,
        base_ctr=0.041,
        base_cr=0.024,
        base_aov=49.0,
        base_commission=0.25,
        recurring=True,
        volatility=0.16,
        notes="Subscription-based; cancellation rate proxied by refund_rate.",
    ),
    Niche(
        slug="pet_care",
        title="Pet Care & Supplies",
        affiliate_programs=("Chewy", "Petco", "Amazon Associates"),
        base_traffic=2700,
        base_ctr=0.049,
        base_cr=0.036,
        base_aov=64.0,
        base_commission=0.04,
        volatility=0.09,
        notes="Sticky audience, repeat purchases - lowest volatility.",
    ),
    Niche(
        slug="eco_products",
        title="Sustainable & Eco Products",
        affiliate_programs=("EarthHero", "Public Goods", "Grove Collaborative"),
        base_traffic=1100,
        base_ctr=0.044,
        base_cr=0.021,
        base_aov=72.0,
        base_commission=0.08,
        volatility=0.20,
        notes="Smaller market, higher commission to compensate.",
    ),
    Niche(
        slug="mobile_gaming",
        title="Mobile Apps & Gaming Peripherals",
        affiliate_programs=("Apple Services", "Razer", "Logitech G"),
        base_traffic=4200,
        base_ctr=0.029,
        base_cr=0.014,
        base_aov=42.0,
        base_commission=0.05,
        volatility=0.25,
        notes="Volume play - cheap traffic, low CR, viral spikes possible.",
    ),
    Niche(
        slug="fitness_wearables",
        title="Health & Fitness Wearables",
        affiliate_programs=("Garmin", "Whoop", "Oura"),
        base_traffic=1700,
        base_ctr=0.037,
        base_cr=0.019,
        base_aov=265.0,
        base_commission=0.06,
        volatility=0.19,
        notes="High-AOV gadgets; January peak from new-year resolutions.",
    ),
)


_BY_SLUG = {n.slug: n for n in DEFAULT_NICHES}


def niche_by_slug(slug: str) -> Niche:
    """Look up a default niche by slug. Raises KeyError if unknown."""
    return _BY_SLUG[slug]
