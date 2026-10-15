"""Real business data in, same structure as the synthetic seed out.

The editable 'form' is what the web app shows and what an exported file contains:
  business_name, start_year, first_month (1-12, month of history[0]), history [monthly revenue, oldest first],
  cash0, fixed_monthly, var_ratio (0-1), min_cash,
  debts [{name, kind: bank|flat|informal, principal, apr?, flat_monthly?, rate_monthly?, n?, pmt?}],
  receivables [{name, amount, month 1-12, prob 0-1}]
"""
from __future__ import annotations

import time

from engine import debt as dbt, forecast as fc

MIN_HISTORY = 12


class DataError(ValueError):
    pass


def _num(x, name, lo=None, hi=None, req=True, default=0.0):
    if x is None or x == "":
        if req:
            raise DataError(f"กรุณากรอก {name}")
        return default
    try:
        v = float(str(x).replace(",", ""))
    except Exception:
        raise DataError(f"{name} ต้องเป็นตัวเลข")
    if lo is not None and v < lo:
        raise DataError(f"{name} ต้องไม่น้อยกว่า {lo:g}")
    if hi is not None and v > hi:
        raise DataError(f"{name} ต้องไม่เกิน {hi:g}")
    return v


def build(form: dict) -> tuple[dict, list]:
    """Validate form -> (seed-like dict, warnings[th])."""
    warns: list[str] = []
    name = str(form.get("business_name") or "ธุรกิจของฉัน").strip()[:80]
    fm = int(_num(form.get("first_month"), "เดือนแรกของข้อมูล", 1, 12))
    year = int(_num(form.get("start_year"), "ปีของเดือนแรก", 1990, 2100, req=False, default=time.localtime().tm_year - 2))
    hist_raw = form.get("history") or []
    hist = [_num(h, "ยอดขายรายเดือน", 1) for h in hist_raw]
    if len(hist) < MIN_HISTORY:
        raise DataError(f"ต้องมียอดขายรายเดือนอย่างน้อย {MIN_HISTORY} เดือน (มี {len(hist)})")
    if len(hist) > 120:
        raise DataError("ยอดขายรายเดือนมากสุด 120 เดือน")
    if len(hist) < 24:
        warns.append(f"มีข้อมูล {len(hist)} เดือน (<24) ฤดูกาลและแนวโน้มจะไม่แน่นอนมาก ผลพยากรณ์ช่วงกว้างขึ้น")
    cash0 = _num(form.get("cash0"), "เงินสดคงเหลือตอนนี้")
    F = _num(form.get("fixed_monthly"), "ค่าใช้จ่ายคงที่ต่อเดือน", 0)
    v = _num(form.get("var_ratio"), "สัดส่วนต้นทุนผันแปรต่อยอดขาย (0-1)", 0, 0.95)
    min_cash = _num(form.get("min_cash"), "เงินสดขั้นต่ำที่ยอมให้เหลือ", req=False, default=0.0)

    fit = fc.fit_revenue(hist, fm)
    pdebts, ddebts = [], []
    for i, d in enumerate(form.get("debts") or [], 1):
        kind = d.get("kind")
        if kind not in ("bank", "flat", "informal"):
            raise DataError(f"หนี้ข้อ {i}: ประเภทต้องเป็น bank / flat / informal")
        dn = str(d.get("name") or f"หนี้ {i}")[:60]
        P = _num(d.get("principal"), f"หนี้ข้อ {i}: เงินต้น", 1)
        did = f"d{i}"
        if kind == "bank":
            apr = _num(d.get("apr"), f"หนี้ข้อ {i}: ดอกเบี้ยต่อปี (เศษส่วน เช่น 0.12)", 0, 1)
            n = int(_num(d.get("n"), f"หนี้ข้อ {i}: จำนวนงวดที่เหลือ", 1, 360))
            pmt = _num(d.get("pmt"), f"หนี้ข้อ {i}: ค่างวด", 0, req=False, default=0.0) or dbt.pmt_amortizing(P, apr, n)
            dd = dict(id=did, name=dn, kind=kind, principal=P, apr=apr, n=n, pmt=pmt)
            pd = dict(id=did, pmt=pmt, start=1, n=n)
        elif kind == "flat":
            fl = _num(d.get("flat_monthly"), f"หนี้ข้อ {i}: ดอกเบี้ยแบบ flat ต่อเดือน (เศษส่วน เช่น 0.009)", 0, 0.5)
            n = int(_num(d.get("n"), f"หนี้ข้อ {i}: จำนวนงวด", 1, 360))
            dd = dict(id=did, name=dn, kind=kind, principal=P, flat_monthly=fl, n=n)
            pd = dict(id=did, pmt=P * (1 + fl * n) / n, start=1, n=n)
        else:
            rm = _num(d.get("rate_monthly"), f"หนี้ข้อ {i}: ดอกเบี้ยต่อเดือน (เศษส่วน เช่น 0.10)", 0, 1)
            hz = int(_num(d.get("n"), f"หนี้ข้อ {i}: ระยะเวลาที่ต้องจ่าย (เดือน)", 1, 120, req=False, default=12))
            dd = dict(id=did, name=dn, kind=kind, principal=P, rate_monthly=rm, horizon=hz)
            pd = dict(id=did, pmt=P * rm, start=1, n=hz)
        ddebts.append(dd)
        pdebts.append(pd)
    colls = []
    for i, c in enumerate(form.get("receivables") or [], 1):
        colls.append(dict(id=f"c{i}", name=str(c.get("name") or f"ลูกหนี้ {i}")[:60],
                          amount=_num(c.get("amount"), f"ลูกหนี้ข้อ {i}: ยอดค้าง", 1),
                          tau=int(_num(c.get("month"), f"ลูกหนี้ข้อ {i}: เดือนที่คาดว่าจะได้รับ (1-12)", 1, 12)),
                          q=_num(c.get("prob"), f"ลูกหนี้ข้อ {i}: โอกาสได้รับ (0-1)", 0, 1)))
    if F + sum(p["pmt"] for p in pdebts) > fit["R0"] * (1 - v) * 3:
        warns.append("ค่าใช้จ่ายคงที่+ค่างวดสูงกว่ากำไรขั้นต้นมาก ตรวจตัวเลขอีกครั้ง")
    params = dict(**{k: fit[k] for k in ("R0", "g", "season", "sigma", "last_month", "g_se", "lnR0_se")},
                  v=v, F=F, cash0=cash0, min_cash=min_cash, debts=pdebts, add_fixed=[], add_revenue=[],
                  collections=colls)
    seed = dict(synthetic=False,
                notice="ข้อมูลธุรกิจจริงที่ผู้ใช้กรอก — ผลเป็นการประมาณจากข้อมูลที่ให้ ไม่ใช่คำแนะนำลงทุน/กฎหมาย",
                business=dict(name=name, first_month=fm, history_start=f"{year}-{fm:02d}"),
                history=[round(h, 2) for h in hist], true_params=dict(R0=fit["R0"], g=fit["g"], sigma=fit["sigma"], season=fit["season"]),
                fit=fit, params=params, debts=ddebts, branches={})
    return seed, warns


def to_form(seed: dict) -> dict:
    """Current dataset -> editable form (works for both the synthetic seed and user data)."""
    b, p = seed["business"], seed["params"]
    debts = []
    for d in seed["debts"]:
        row = dict(name=d.get("name", d["id"]), kind=d["kind"], principal=d["principal"])
        if d["kind"] == "bank":
            row.update(apr=d["apr"], n=d["n"])
        elif d["kind"] == "flat":
            row.update(flat_monthly=d["flat_monthly"], n=d["n"])
        else:
            row.update(rate_monthly=d["rate_monthly"], n=d.get("horizon", 12))
        debts.append(row)
    return dict(business_name=b["name"], start_year=int(b.get("history_start", "2024-01")[:4]), first_month=b["first_month"],
                history=seed["history"], cash0=p["cash0"], fixed_monthly=p["F"], var_ratio=p["v"],
                min_cash=p.get("min_cash", 0.0), debts=debts,
                receivables=[dict(name=c["name"], amount=c["amount"], month=c["tau"], prob=c["q"]) for c in p["collections"]])


def second_branch_template(R0: float) -> dict:
    """'Open a second branch' scaled to the business size (demo numbers were calibrated at R0 ~ 520k)."""
    k = R0 / 520_000.0
    return dict(name="เปิดสาขาสอง", reason="ถ้าเปิดสาขาสอง", cash_delta=-80_000 * k,
                add_fixed=[dict(amount=70_000 * k, start=2)], add_revenue=[dict(share=0.40, start=2, ramp=6)],
                debts=[dict(id="branch-loan", pmt=10_000 * k, start=1, n=36)],
                assumptions=["สมมติลงทุนสุทธิ ≈ 0.15× รายได้/เดือน ค่าใช้จ่ายสาขา ≈ 0.13× รายได้/เดือน รายได้สาขาใหม่ = 40% ของสาขาแรกหลัง ramp 6 เดือน (ปรับได้)"])
