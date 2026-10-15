"""Verifiable financial history for lenders (สูตร 3.8).

FCF_5% = 5th percentile (across paths) of average monthly pre-debt free cash flow
PMT_max = alpha * FCF_5%        L_max = PMT_max * (1-(1+i)^-n)/i
Capacity for NEW debt subtracts today's debt service.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from . import ENGINE_VERSION
from . import forecast as fc
from .debt import annuity_factor


def export(params: dict, ledger_entries: list[dict], n_paths=5000, T=12, seed=42,
           alpha=0.5, apr=0.18, n=36) -> dict:
    noise = fc.draw_noise(n_paths, T, len(params.get("collections", [])), seed)
    sim = fc.simulate(params, noise)
    fcf = (sim["R"] * (1 - params["v"]) - sim["F"]).mean(axis=1)  # pre-debt, per path
    fcf5 = float(np.percentile(fcf, 5))
    D_now = float(sim["D"][0])
    pmt_max = alpha * fcf5
    i = apr / 12
    af = annuity_factor(i, n)
    payload = dict(
        engine_version=ENGINE_VERSION, seed=seed, n_paths=n_paths, horizon=T,
        fcf_p5=fcf5, fcf_p50=float(np.percentile(fcf, 50)), existing_debt_service=D_now,
        alpha=alpha, assumed_apr=apr, assumed_n=n,
        pmt_max_total=pmt_max, l_max_total=max(pmt_max, 0) * af,
        pmt_max_new=max(pmt_max - D_now, 0), l_max_new=max(pmt_max - D_now, 0) * af,
        ledger=[dict(file=e["file"], sha256=e["sha256"]) for e in ledger_entries],
    )
    payload["export_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload
