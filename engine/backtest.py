"""Backtest (สูตร 3.7): hide the last H months, forecast, compare with what happened.

Predictive law of revenue h months ahead:
  ln R_{n+h} ~ N( ln(R0 (1+g)^h s_m) - sigma^2/2 , sigma^2 )
Metrics: coverage of the central 80% interval (target ~0.80), MAPE of the median,
pinball loss (q=.1,.5,.9), and a seasonal-naive baseline for context.
Parameter uncertainty is included (OLS prediction variance, Student-t tails).
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np

from . import forecast as fc

_N = NormalDist()
QS = (0.1, 0.5, 0.9)


def _t_quantile(q, nu):
    """Student-t quantile via Cornish-Fisher expansion (no scipy needed; fine for nu >= 4)."""
    z = _N.inv_cdf(q)
    return z + (z**3 + z) / (4 * nu) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * nu**2)


def _quantiles(fit, h):
    """Predictive quantiles including parameter uncertainty (OLS prediction variance + t tails)."""
    m = fit["season"][(fit["last_month"] - 1 + h) % 12]
    se_level = np.hypot(fit["lnR0_se"], h * fit["g_se"] / (1 + fit["g"]))
    scale = float(np.sqrt(fit["sigma"] ** 2 + se_level**2))
    mu = np.log(fit["R0"] * (1 + fit["g"]) ** h * m) - fit["sigma"] ** 2 / 2
    return {q: float(np.exp(mu + scale * _t_quantile(q, fit["dof"]))) for q in QS}


def _pinball(y, qv):
    return float(np.mean([max(q * (y - v), (q - 1) * (y - v)) for q, v in qv.items()]))


def rolling_backtest(history, first_month: int, H: int = 3, min_train: int = 15) -> dict:
    hist = np.asarray(history, float)
    rows = []
    for k in range(min_train, len(hist)):
        fit = fc.fit_revenue(hist[:k], first_month)
        for h in range(1, min(H, len(hist) - k) + 1):
            y = hist[k + h - 1]
            qv = _quantiles(fit, h)
            snaive = hist[k + h - 1 - 12] if k + h - 1 - 12 >= 0 else np.nan
            rows.append(dict(origin=k, h=h, y=float(y), q10=qv[0.1], q50=qv[0.5], q90=qv[0.9],
                             covered=bool(qv[0.1] <= y <= qv[0.9]),
                             ape=abs(y - qv[0.5]) / y, pinball=_pinball(y, qv),
                             ape_snaive=abs(y - snaive) / y if not np.isnan(snaive) else None))
    sn = [r["ape_snaive"] for r in rows if r["ape_snaive"] is not None]
    return dict(
        n_points=len(rows), coverage_80=float(np.mean([r["covered"] for r in rows])),
        mape_median=float(np.mean([r["ape"] for r in rows])),
        mape_seasonal_naive=float(np.mean(sn)) if sn else None,
        pinball=float(np.mean([r["pinball"] for r in rows])), rows=rows,
        note="Synthetic data: generated from the same model family, so this checks the estimator and "
             "calibration, NOT real-world accuracy. Re-run on a real client's history.",
    )


def simulate_history(true, n_months, first_month, rng):
    t = np.arange(-(n_months - 1), 1)
    m = (first_month - 1 + np.arange(n_months)) % 12
    eps = np.exp(-true["sigma"] ** 2 / 2 + true["sigma"] * rng.standard_normal(n_months))
    return true["R0"] * (1 + true["g"]) ** t * np.asarray(true["season"])[m] * eps


def calibration_study(true: dict, n_series: int = 300, n_months: int = 24, train: int = 18,
                      first_month: int = 11, seed: int = 7) -> dict:
    """Many synthetic histories from known truth -> pooled out-of-sample coverage of the 80% band
    (the honest answer to 'is the band really 80%?')."""
    rng = np.random.default_rng(seed)
    cov, g_err, sg = [], [], []
    for _ in range(n_series):
        hist = simulate_history(true, n_months, first_month, rng)
        fit = fc.fit_revenue(hist[:train], first_month)
        g_err.append(fit["g"] - true["g"]); sg.append(fit["sigma"])
        for h in range(1, n_months - train + 1):
            q = _quantiles(fit, h)
            cov.append(q[0.1] <= hist[train + h - 1] <= q[0.9])
    return dict(n_series=n_series, n_points=len(cov), coverage_80=float(np.mean(cov)),
                g_bias=float(np.mean(g_err)), sigma_mean=float(np.mean(sg)), sigma_true=true["sigma"])
