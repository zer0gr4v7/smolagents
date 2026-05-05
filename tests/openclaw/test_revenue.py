import pytest

from smolagents.openclaw import (
    DEFAULT_NICHES,
    NicheParams,
    RevenueFormula,
    compute_revenue,
    niche_by_slug,
)


def test_default_niches_count_and_unique_slugs():
    slugs = [n.slug for n in DEFAULT_NICHES]
    assert len(DEFAULT_NICHES) == 10
    assert len(set(slugs)) == 10


def test_compute_revenue_rate_based():
    n = niche_by_slug("outdoor_gear")
    params = NicheParams.from_niche(n)
    rev = compute_revenue(n, params)
    expected = (
        params.traffic * params.ctr * params.cr
        * params.aov * params.commission
        * (1 - params.refund)
    )
    assert rev == pytest.approx(expected)


def test_compute_revenue_cpa_uses_flat_commission():
    """personal_finance has base_aov=0; commission becomes a flat USD bounty."""
    n = niche_by_slug("personal_finance")
    params = NicheParams.from_niche(n)
    rev = compute_revenue(n, params)
    expected = (
        params.traffic * params.ctr * params.cr
        * params.commission  # not aov*commission
        * (1 - params.refund)
    )
    assert rev == pytest.approx(expected)


def test_compute_revenue_recurring_applies_ltv():
    n = niche_by_slug("web_hosting")
    params = NicheParams.from_niche(n)
    assert params.ltv_multiplier > 1.0
    rev = compute_revenue(n, params)
    one_shot = NicheParams.from_niche(n)
    one_shot.ltv_multiplier = 1.0
    assert rev > compute_revenue(n, one_shot)


def test_clamp_keeps_params_in_range():
    p = NicheParams(traffic=-5, ctr=2.0, cr=-0.1, aov=-10, commission=-1, refund=2.0).clamp()
    assert p.traffic == 0
    assert p.ctr == 1.0
    assert p.cr == 0
    assert p.aov == 0
    assert p.commission == 0
    assert p.refund == 1.0


def test_formula_applies_weights_multiplicatively():
    n = niche_by_slug("pet_care")
    f = RevenueFormula()
    params = NicheParams.from_niche(n)
    f.ensure_niche(n)
    f.weights[n.slug]["traffic"] = 2.0
    scaled = f.apply(n, params)
    assert scaled.traffic == pytest.approx(params.traffic * 2.0)


def test_formula_propose_does_not_mutate_current_weights():
    n = niche_by_slug("smart_home")
    f = RevenueFormula(step_size=0.10)
    f.ensure_niche(n)
    before = dict(f.weights[n.slug])
    candidate = f.propose(n, "ctr", direction=1)
    assert candidate["ctr"] == pytest.approx(before["ctr"] * 1.10)
    assert f.weights[n.slug] == before  # unchanged until accept()


def test_formula_decay_floors_at_min_step():
    f = RevenueFormula(step_size=0.10, step_decay=0.5, min_step=0.05)
    for _ in range(10):
        f.decay_step()
    assert f.step_size == pytest.approx(0.05)


def test_describe_handles_cpa_and_recurring_niches():
    f = RevenueFormula()
    out = f.describe(niche_by_slug("personal_finance"))
    assert "*A" not in out  # no AOV term for CPA
    out = f.describe(niche_by_slug("web_hosting"))
    assert "* L *" in out  # recurring uses L


def test_converged_returns_false_when_oscillating():
    f = RevenueFormula()
    f.history = [{"day": i, "revenue": r, "step": 0.1} for i, r in enumerate([10, 50, 10, 50, 10])]
    assert not f.converged(window=5, tol=0.01)


def test_converged_returns_true_when_flat():
    f = RevenueFormula()
    f.history = [{"day": i, "revenue": 100.0 + i * 0.001, "step": 0.1} for i in range(7)]
    assert f.converged(window=5, tol=0.01)
