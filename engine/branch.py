"""Branching (สูตร 3.4, 3.6): a branch is a JSON patch on the base parameters.

Base and branch share the same random numbers (common random numbers), so
Delta P = P_branch - P_base is not polluted by sampling noise; we also report a paired s.e.

Patch schema (all keys optional):
  name, reason
  cash_delta: float                     one-off cash at t=0 (capex < 0, loan proceeds > 0)
  g_delta, sigma_delta, v_delta: float
  add_fixed:   [{amount, start, end?}]  extra fixed cost / month
  add_revenue: [{share, start, ramp}]   extra revenue = share * main revenue, linear ramp-up over `ramp` months
  debts:       [{pmt, start, n}]        new debt service
  collection_updates: [{id, tau, q}]    update overdue-receivable assumptions (3.6)
"""
from __future__ import annotations

import copy

from . import forecast as fc


def apply_patch(params: dict, patch: dict | None) -> dict:
    p = copy.deepcopy(params)
    if not patch:
        return p
    p["cash0"] += float(patch.get("cash_delta", 0.0))
    p["g"] += float(patch.get("g_delta", 0.0))
    p["sigma"] = max(1e-6, p["sigma"] + float(patch.get("sigma_delta", 0.0)))
    p["v"] = min(0.99, max(0.0, p["v"] + float(patch.get("v_delta", 0.0))))
    p.setdefault("add_fixed", []).extend(copy.deepcopy(patch.get("add_fixed", [])))
    p.setdefault("add_revenue", []).extend(copy.deepcopy(patch.get("add_revenue", [])))
    p.setdefault("debts", []).extend(copy.deepcopy(patch.get("debts", [])))
    upd = {u["id"]: u for u in patch.get("collection_updates", [])}
    for c in p.get("collections", []):
        if c["id"] in upd:
            c["tau"] = int(upd[c["id"]].get("tau", c["tau"]))
            c["q"] = float(upd[c["id"]].get("q", c["q"]))
    return p


def compare(base: dict, patch: dict, n_paths: int = 5000, T: int = 12, seed: int = 42) -> dict:
    import numpy as np

    noise = fc.draw_noise(n_paths, T, len(base.get("collections", [])), seed)
    sb = fc.simulate(base, noise)
    br = apply_patch(base, patch)
    sr = fc.simulate(br, noise)
    mc = base.get("min_cash", 0.0)
    a, b = fc.summarize(sb["C"], mc), fc.summarize(sr["C"], mc)
    d = (sr["C"].min(1) >= mc).astype(float) - (sb["C"].min(1) >= mc).astype(float)
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    dP = float(d.mean())
    return dict(
        base=a, branch=b, delta_p=dP, delta_p_se=se,
        delta_p_ci95=[dP - 1.96 * se, dP + 1.96 * se],
        delta_min_cash_p50=b["min_cash_pct"]["p50"] - a["min_cash_pct"]["p50"],
        patch=patch, n_paths=n_paths, seed=seed,
    )
