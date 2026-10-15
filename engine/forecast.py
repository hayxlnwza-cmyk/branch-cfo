"""Branch CFO engine: cash-flow Monte Carlo (สูตร 3.1-3.3).

C_{t+1} = C_t + R_t - v R_t - F_t - D_t
R_t     = R0 (1+g)^t s_{m(t)} eps_t,   ln eps ~ N(-sigma^2/2, sigma^2)
P_surv  = Pr(min_{1<=t<=T} C_t >= min_cash)

Pure functions, numpy-vectorised, reproducible by seed. No LLM touches numbers.
"""
from __future__ import annotations

import numpy as np

HARMONICS = 2  # seasonal shape = 2 Fourier harmonics (6 params total, stable on 18-24 months)


# ---------------------------------------------------------------- fitting (3.2)
def _design(tau, months, K=HARMONICS):
    tau = np.asarray(tau, float)
    months = np.asarray(months)
    ang = 2 * np.pi * (months - 1) / 12
    cols = [np.ones_like(tau), tau]
    for k in range(1, K + 1):
        cols += [np.cos(k * ang), np.sin(k * ang)]
    return np.column_stack(cols)


def fit_revenue(history, first_month: int, K: int = HARMONICS) -> dict:
    """Estimate g, seasonal index s (mean 1), sigma, level R0 at t=0 (= last observed month).

    ln R_tau = a + b*tau + f(month) + e,  e ~ N(0, sigma^2)   (tau = 0 at last obs)
    g = exp(b)-1;  s = exp(f)/mean(exp(f));  R0 = exp(a + ln mean(exp f) + sigma^2/2)
    so that E[R_t] = R0 (1+g)^t s_m  exactly as in the model.
    """
    y = np.log(np.asarray(history, float))
    n = len(y)
    months = ((first_month - 1 + np.arange(n)) % 12) + 1
    tau = np.arange(n) - (n - 1)
    X = _design(tau, months, K)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    p = X.shape[1]
    sigma = float(np.sqrt(resid @ resid / max(n - p, 1)))
    g = float(np.exp(beta[1]) - 1)
    f = _design(np.zeros(12), np.arange(1, 13), K)[:, 2:] @ beta[2:]
    e = np.exp(f)
    c = float(np.log(e.mean()))
    season = (e / e.mean()).tolist()
    R0 = float(np.exp(beta[0] + c + sigma**2 / 2))
    last_month = int(months[-1])
    # parameter uncertainty (OLS): slope s.e. and level s.e. at t=0 (cross-covariance ignored)
    XtXi = np.linalg.inv(X.T @ X)
    x0 = _design([0.0], [last_month], K)[0]
    g_se = float(sigma * np.sqrt(XtXi[1, 1]) * (1 + g))
    lnR0_se = float(sigma * np.sqrt(x0 @ XtXi @ x0))
    return dict(R0=R0, g=g, season=season, sigma=sigma, last_month=last_month, n_obs=n,
                g_se=g_se, lnR0_se=lnR0_se, dof=max(n - p, 1), K=K)


# ---------------------------------------------------------------- simulation (3.1, 3.3)
def draw_noise(n_paths: int, T: int, n_debtors: int, seed: int):
    """Common random numbers: reuse the SAME (z,u) for base and every branch (3.4)."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, T))
    u = rng.random((n_paths, max(n_debtors, 1)))
    w = rng.standard_normal((n_paths, 2))  # parameter-uncertainty draws (growth, level)
    return z, u, w


def _series_from_items(items, T, default_n=None):
    t = np.arange(1, T + 1)
    out = np.zeros(T)
    for it in items:
        start = int(it.get("start", 1))
        if "n" in it and it["n"] is not None:
            end = start + int(it["n"]) - 1
        else:
            end = int(it.get("end", T))
        out[(t >= start) & (t <= end)] += float(it.get("pmt", it.get("amount", 0.0)))
    return out


def simulate(params: dict, noise) -> dict:
    z, u, w = noise
    N, T = z.shape
    t = np.arange(1, T + 1)
    season = np.asarray(params["season"])[(params["last_month"] - 1 + t) % 12]
    sig = params["sigma"]
    eps = np.exp(-sig**2 / 2 + sig * z)
    g_i = params["g"] + params.get("g_se", 0.0) * w[:, :1]            # (N,1) growth uncertainty
    lse = params.get("lnR0_se", 0.0)
    R0_i = params["R0"] * np.exp(lse * w[:, 1:2] - lse**2 / 2)        # (N,1) level uncertainty, mean-preserving
    R = R0_i * (1 + g_i) ** t * season * eps  # (N,T)

    # extra revenue streams proportional to the main process (e.g. second branch), with linear ramp
    for it in params.get("add_revenue", []):
        start, ramp, share = int(it.get("start", 1)), max(int(it.get("ramp", 1)), 1), float(it["share"])
        rt = np.clip((t - start + 1) / ramp, 0.0, 1.0) * (t >= start)
        R = R + share * rt * R
    v = params["v"]
    F = np.full(T, float(params["F"])) + _series_from_items(params.get("add_fixed", []), T)
    D = _series_from_items(params.get("debts", []), T)

    inflow_extra = np.zeros((N, T))
    for j, c in enumerate(params.get("collections", [])):
        tau = int(c["tau"])
        if 1 <= tau <= T:
            inflow_extra[:, tau - 1] += c["amount"] * (u[:, j] < c["q"])

    net = R * (1 - v) - F - D + inflow_extra
    C = params["cash0"] + np.cumsum(net, axis=1)
    return dict(C=C, R=R, F=F, D=D)


def summarize(C: np.ndarray, min_cash: float = 0.0) -> dict:
    N, T = C.shape
    minC = C.min(axis=1)
    arg = C.argmin(axis=1) + 1
    p_surv = float((minC >= min_cash).mean())
    qs = np.percentile(C, [5, 25, 50, 75, 95], axis=0)
    mode_month = int(np.bincount(arg, minlength=T + 1).argmax())
    return dict(
        p_survive=p_surv,
        min_cash_pct={"p5": float(np.percentile(minC, 5)), "p50": float(np.percentile(minC, 50)),
                      "p95": float(np.percentile(minC, 95))},
        trough_month_mode=mode_month,
        trough_month_median=float(np.median(arg)),
        fan={"p5": qs[0].tolist(), "p25": qs[1].tolist(), "p50": qs[2].tolist(),
             "p75": qs[3].tolist(), "p95": qs[4].tolist()},
        n_paths=int(N), horizon=int(T),
    )


def run(params: dict, n_paths: int = 5000, T: int = 12, seed: int = 42) -> dict:
    noise = draw_noise(n_paths, T, len(params.get("collections", [])), seed)
    sim = simulate(params, noise)
    return summarize(sim["C"], params.get("min_cash", 0.0))
