"""Generate the SYNTHETIC demo business (restaurant, 24 months). Not real data. Deterministic (seed 2026)."""
import json, math, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import forecast as fc, backtest as bt, debt as dbt  # noqa: E402

FIRST_MONTH = 11  # history = Nov 2024 .. Oct 2026
TRUE = dict(R0=520_000.0, g=0.004, sigma=0.10)
amp = [1 + 0.22 * math.cos(2 * math.pi * (m - 12) / 12) for m in range(1, 13)]  # peak Dec (tourist season)
TRUE["season"] = [a / (sum(amp) / 12) for a in amp]

BANK = dict(id="bank", name="สินเชื่อธนาคาร (SME)", kind="bank", principal=520_000, apr=0.12, n=30)
BANK["pmt"] = dbt.pmt_amortizing(BANK["principal"], BANK["apr"], BANK["n"])
FLAT = dict(id="flat", name="ผ่อนเครื่องครัวแบบ flat", kind="flat", principal=180_000, flat_monthly=0.009, n=12)
INFORMAL = dict(id="informal", name="กู้นอกระบบ 10%/เดือน", kind="informal", principal=100_000, rate_monthly=0.10, horizon=12)
FLAT_PMT = FLAT["principal"] * (1 + FLAT["flat_monthly"] * FLAT["n"]) / FLAT["n"]

CASH0, V, F = 170_000.0, 0.40, 271_000.0

def build():
    rng = np.random.default_rng(2026)
    hist = bt.simulate_history(TRUE, 24, FIRST_MONTH, rng)
    fit = fc.fit_revenue(hist, FIRST_MONTH)
    params = dict(
        **{k: fit[k] for k in ("R0", "g", "season", "sigma", "last_month", "g_se", "lnR0_se")},
        v=V, F=F, cash0=CASH0, min_cash=0.0,
        debts=[dict(id="bank", pmt=BANK["pmt"], start=1, n=BANK["n"]),
               dict(id="flat", pmt=FLAT_PMT, start=1, n=FLAT["n"]),
               dict(id="informal", pmt=INFORMAL["principal"] * INFORMAL["rate_monthly"], start=1, n=12)],
        add_fixed=[], add_revenue=[],
        collections=[
            dict(id="c1", name="บริษัท เอ็มพรีเมียร์ (จัดเลี้ยง)", amount=85_000, tau=6, q=0.40),
            dict(id="c2", name="คุณสมศรี (ออกงานแต่ง)", amount=60_000, tau=8, q=0.40),
            dict(id="c3", name="โรงแรมริมน้ำ (วัตถุดิบ)", amount=45_000, tau=5, q=0.40),
            dict(id="c4", name="บริษัท ไทยเฟรช (ล็อตใหญ่)", amount=120_000, tau=9, q=0.40),
        ],
    )
    branches = {
        "second-branch": dict(
            name="เปิดสาขาสอง", reason="ถ้าเปิดสาขาสอง",
            cash_delta=-80_000,                                  # capex net of loan proceeds
            add_fixed=[dict(amount=70_000, start=2)],             # rent + staff, from month 2
            add_revenue=[dict(share=0.40, start=2, ramp=6)],      # 40% of main branch revenue after 6-month ramp
            debts=[dict(id="branch-loan", pmt=10_000, start=1, n=36)],
        ),
        "raise-prices": dict(name="ขึ้นราคา 8%", reason="ถ้าขึ้นราคา 8%", v_delta=-0.045, g_delta=-0.004),
    }
    return dict(
        synthetic=True,
        notice="ข้อมูลตัวอย่างสังเคราะห์เพื่อเดโม ไม่ใช่ธุรกิจจริง / SYNTHETIC DEMO DATA",
        business=dict(name="ร้านอาหารตัวอย่าง", first_month=FIRST_MONTH, history_start="2024-11"),
        history=[round(float(x), 2) for x in hist],
        true_params=TRUE, fit=fit, params=params, debts=[BANK, FLAT, INFORMAL], branches=branches,
    )

if __name__ == "__main__":
    out = build()
    (ROOT / "data" / "seed.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    from engine import branch as br
    base = fc.run(out["params"], 10000, 12, 42)
    cmp = br.compare(out["params"], out["branches"]["second-branch"], 10000, 12, 42)
    print("fit g=%.4f sigma=%.3f R0=%.0f" % (out["fit"]["g"], out["fit"]["sigma"], out["fit"]["R0"]))
    print("base P=%.3f  branch P=%.3f  dP=%.3f +-%.3f" % (base["p_survive"], cmp["branch"]["p_survive"], cmp["delta_p"], cmp["delta_p_se"]))
    print("base min p5/50/95", base["min_cash_pct"], "trough", base["trough_month_mode"])
