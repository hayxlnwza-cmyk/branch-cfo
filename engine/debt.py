"""Debt Doctor (สูตร 3.5): true APR behind flat-rate and informal loans."""
from __future__ import annotations

# Legal reference points. VERIFY with a qualified person before quoting on stage.
CAP_NON_FI = 0.15      # non-financial-institution lenders: >15%/yr interest void (principal still owed)
CAP_PICO_UNSECURED = 0.36  # pico-finance unsecured (as reported by media)


def annuity_factor(i: float, n: int) -> float:
    return n if i == 0 else (1 - (1 + i) ** (-n)) / i


def solve_monthly_rate(P: float, pmt: float, n: int, tol: float = 1e-12) -> float:
    """Solve P = pmt * (1-(1+i)^-n)/i for i by bisection (monotone in i)."""
    if pmt * n <= P:
        return 0.0
    lo, hi = 0.0, 1.0
    while P < pmt * annuity_factor(hi, n):
        hi *= 2
    for _ in range(200):
        mid = (lo + hi) / 2
        if pmt * annuity_factor(mid, n) > P:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def flat_to_apr(P: float, flat_monthly: float, n: int) -> dict:
    pmt = P * (1 + flat_monthly * n) / n
    i = solve_monthly_rate(P, pmt, n)
    return dict(pmt=pmt, i_month=i, apr_nominal=12 * i, eir=(1 + i) ** 12 - 1,
                total_interest=pmt * n - P)


def monthly_rate_to_apr(r_month: float) -> dict:
    return dict(i_month=r_month, apr_nominal=12 * r_month, eir=(1 + r_month) ** 12 - 1)


def pmt_amortizing(P: float, apr: float, n: int) -> float:
    i = apr / 12
    return P / annuity_factor(i, n)


def diagnose(debt: dict, refi_apr: float = 0.20, refi_n: int = 24) -> dict:
    """debt: {id,name,kind: bank|flat|informal, principal, ...} -> APR, flags, refinance saving."""
    kind = debt["kind"]
    P = float(debt["principal"])
    if kind == "flat":
        r = flat_to_apr(P, debt["flat_monthly"], int(debt["n"]))
        cur_pmt, n_left = r["pmt"], int(debt["n"])
        total_cost = r["total_interest"]
    elif kind == "informal":
        r = monthly_rate_to_apr(debt["rate_monthly"])
        cur_pmt = P * debt["rate_monthly"]  # interest-only, principal never falls
        n_left = int(debt.get("horizon", refi_n))
        total_cost = cur_pmt * n_left
        r["pmt"] = cur_pmt
    else:  # bank amortising loan with stated APR
        r = dict(i_month=debt["apr"] / 12, apr_nominal=debt["apr"], eir=(1 + debt["apr"] / 12) ** 12 - 1,
                 pmt=debt["pmt"])
        cur_pmt, n_left = debt["pmt"], int(debt["n"])
        total_cost = cur_pmt * n_left - P
    flags = []
    if r["eir"] > CAP_PICO_UNSECURED:
        flags.append("EXCEEDS_36_PCT")
    if kind == "informal" and r["apr_nominal"] > CAP_NON_FI:
        flags.append("EXCEEDS_15_PCT_NON_FI_CAP")
    new_pmt = pmt_amortizing(P, refi_apr, refi_n)
    refi_total_cost = new_pmt * refi_n - P
    return dict(
        id=debt["id"], name=debt.get("name", debt["id"]), kind=kind, principal=P, **r,
        flags=flags, total_cost_current=total_cost,
        refinance=dict(apr=refi_apr, n=refi_n, pmt=new_pmt, total_cost=refi_total_cost,
                       monthly_cash_change=cur_pmt - new_pmt,
                       total_saving=total_cost - refi_total_cost
                       if kind == "informal" and n_left == refi_n else None),
    )


def report(debts: list[dict], **kw) -> dict:
    items = sorted((diagnose(d, **kw) for d in debts), key=lambda x: -x["eir"])
    return dict(items=items, worst=items[0]["id"] if items else None,
                note="Legal caps are reference values; verify before relying on them.")
