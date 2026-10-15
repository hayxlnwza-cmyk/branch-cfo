import math
import numpy as np
import pytest

from engine import branch as br, backtest as bt, debt as dbt, forecast as fc, lender_export as lx


def det_params(**kw):
    p = dict(R0=100.0, g=0.0, season=[1.0] * 12, sigma=1e-9, last_month=12, v=0.4, F=30.0,
             cash0=50.0, min_cash=0.0, debts=[dict(id="d", pmt=10.0, start=1, n=3)],
             add_fixed=[], add_revenue=[], collections=[])
    p.update(kw)
    return p


# ---- 3.1 recursion, hand-checked --------------------------------------------------------
def test_cash_recursion_deterministic():
    p = det_params()
    sim = fc.simulate(p, fc.draw_noise(4, 6, 0, 1))
    # months 1-3: 100*0.6 - 30 - 10 = +20 ; months 4-6: +30
    assert sim["C"][0].round(6).tolist() == [70, 90, 110, 140, 170, 200]


def test_collection_bernoulli_and_tau():
    p = det_params(collections=[dict(id="c", amount=100.0, tau=2, q=0.3)], cash0=0.0)
    sim = fc.simulate(p, fc.draw_noise(20000, 3, 1, 5))
    jump = sim["C"][:, 1] - sim["C"][:, 0] - 20.0
    assert abs((jump > 1).mean() - 0.3) < 0.01
    assert np.allclose(sim["C"][:, 0], 20.0)  # nothing before tau


def test_seed_reproducible_and_survival_monotone_in_cash():
    p = det_params(sigma=0.2, F=55.0)
    a = fc.run(p, 3000, 12, 1)["p_survive"]
    assert a == fc.run(p, 3000, 12, 1)["p_survive"]
    hi = fc.run(det_params(sigma=0.2, F=55.0, cash0=150.0), 3000, 12, 1)["p_survive"]
    assert hi >= a


# ---- 3.2 fit recovers truth --------------------------------------------------------------
def test_fit_recovers_parameters():
    rng = np.random.default_rng(0)
    amp = [1 + 0.2 * math.cos(2 * math.pi * (m - 12) / 12) for m in range(1, 13)]
    true = dict(R0=500_000, g=0.01, sigma=0.05, season=[a / (sum(amp) / 12) for a in amp])
    h = bt.simulate_history(true, 120, 1, rng)
    f = fc.fit_revenue(h, 1)
    assert abs(f["g"] - 0.01) < 0.002
    assert abs(f["sigma"] - 0.05) < 0.008
    assert abs(f["R0"] / 500_000 - 1) < 0.05
    assert abs(np.mean(f["season"]) - 1) < 1e-9


def test_revenue_mean_matches_model():
    p = det_params(sigma=0.25, g=0.02, R0=100.0, F=0, v=0, debts=[], cash0=0)
    sim = fc.simulate(p, fc.draw_noise(200_000, 6, 0, 3))
    expect = 100.0 * 1.02 ** np.arange(1, 7)
    assert np.allclose(sim["R"].mean(axis=0), expect, rtol=0.01)  # E[eps]=1


# ---- 3.4 branch / CRN ---------------------------------------------------------------------
def test_empty_patch_has_exactly_zero_delta():
    p = det_params(sigma=0.2, F=55.0)
    c = br.compare(p, {}, 2000, 12, 9)
    assert c["delta_p"] == 0.0 and c["delta_p_se"] == 0.0


def test_extra_fixed_cost_lowers_survival():
    p = det_params(sigma=0.2, F=50.0)
    c = br.compare(p, dict(add_fixed=[dict(amount=15.0, start=1)]), 4000, 12, 9)
    assert c["delta_p"] < 0 and c["delta_p_ci95"][1] < 0


def test_patch_does_not_mutate_base():
    p = det_params()
    snap = repr(p)
    br.apply_patch(p, dict(cash_delta=-10, add_fixed=[dict(amount=1)], debts=[dict(pmt=1, n=2)]))
    assert repr(p) == snap


# ---- 3.5 debt ------------------------------------------------------------------------------
def test_flat_to_apr_identity_and_known_value():
    r = dbt.flat_to_apr(100_000, 0.006, 12)
    assert r["pmt"] == pytest.approx(100_000 * 1.072 / 12)
    assert r["pmt"] * dbt.annuity_factor(r["i_month"], 12) == pytest.approx(100_000, rel=1e-9)
    assert 0.0100 < r["i_month"] < 0.0112 and r["eir"] > r["apr_nominal"]


def test_informal_ten_percent_month():
    r = dbt.monthly_rate_to_apr(0.10)
    assert r["apr_nominal"] == pytest.approx(1.2) and r["eir"] == pytest.approx(1.1**12 - 1)


def test_diagnose_flags_and_ordering():
    items = dbt.report([
        dict(id="a", kind="informal", principal=100_000, rate_monthly=0.10, horizon=12),
        dict(id="b", kind="bank", principal=500_000, apr=0.12, n=30, pmt=dbt.pmt_amortizing(500_000, 0.12, 30)),
    ])["items"]
    assert items[0]["id"] == "a" and "EXCEEDS_15_PCT_NON_FI_CAP" in items[0]["flags"]
    assert items[1]["flags"] == []


# ---- 3.7 / 3.8 ----------------------------------------------------------------------------
def test_calibration_in_sane_band():
    amp = [1 + 0.2 * math.cos(2 * math.pi * (m - 12) / 12) for m in range(1, 13)]
    true = dict(R0=500_000, g=0.004, sigma=0.10, season=[a / (sum(amp) / 12) for a in amp])
    r = bt.calibration_study(true, n_series=150, train=18)
    assert 0.65 <= r["coverage_80"] <= 0.92


def test_lender_export_is_conservative_and_hash_stable():
    p = det_params(sigma=0.1, F=50.0)
    a = lx.export(p, [], 2000, 12, 3)
    assert a["fcf_p5"] <= a["fcf_p50"]
    assert a == lx.export(p, [], 2000, 12, 3)
