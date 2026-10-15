"""Weekly LINE summary for SME owners. Numbers come from the engine only; this module just words them.

Send path: LINE Messaging API push (needs LINE_CHANNEL_TOKEN + LINE_USER_ID). Without them we return the
text as a preview so the demo can show the exact message without any account.
"""
from __future__ import annotations

import copy
import json
import os
import urllib.request

from . import debt as dbt
from . import forecast as fc


FLAG_TH = {"EXCEEDS_36_PCT": "เกินเพดานอ้างอิง 36% ต่อปี",
           "EXCEEDS_15_PCT_NON_FI_CAP": "เกินเพดานอ้างอิง 15% ต่อปี (เจ้าหนี้นอกสถาบันการเงิน)"}


def _baht(x: float) -> str:
    return f"{x:,.0f}".replace("-", "−")


def collection_gains(params: dict, n_paths: int, T: int, seed: int, base_p: float,
                     month: int = 2, conf: float = 0.85) -> list:
    """What-if per debtor: survival gain if they pay in `month` with confidence `conf` (same seed = paired)."""
    out = []
    for c in params["collections"]:
        p2 = copy.deepcopy(params)
        d = next(x for x in p2["collections"] if x["id"] == c["id"])
        d["tau"], d["q"] = month, conf
        gain = fc.run(p2, n_paths, T, seed)["p_survive"] - base_p
        out.append(dict(id=c["id"], name=c["name"], amount=c["amount"], gain=gain, month=month))
    return sorted(out, key=lambda r: -r["gain"])


def build(params: dict, debts: list, business_name: str, synthetic: bool,
          n_paths=5000, T=12, seed=42) -> dict:
    base = fc.run(params, n_paths, T, seed)
    p = base["p_survive"]
    gains = collection_gains(params, n_paths, T, seed, p)
    rep = dbt.report(debts)
    worst = max(rep["items"], key=lambda i: i["eir"])
    top = gains[0] if gains else None
    lines = [f"สรุปประจำสัปดาห์ · {business_name}" + (" (ข้อมูลสังเคราะห์)" if synthetic else ""),
             "",
             f"โอกาสรอด 12 เดือน: {p:.1%}",
             f"เงินสดต่ำสุดที่เป็นไปได้ (กรณีแย่ 5%): {_baht(base['min_cash_pct']['p5'])} ฿ "
             f"ราวเดือนที่ {base['trough_month_mode']}"]
    if top and top["gain"] > 0:
        lines += ["", f"ควรตามก่อน: {top['name']} ยอด {_baht(top['amount'])} ฿",
                  f"ถ้าได้รับในเดือนที่ {top['month']} โอกาสรอดเป็น {p + top['gain']:.1%} "
                  f"(+{top['gain'] * 100:.1f} จุด)"]
    lines += ["", f"หนี้ที่แพงที่สุด: {worst['name']} ดอกเบี้ยจริง {worst['eir'] * 100:.1f}% ต่อปี"]
    if worst.get("flags"):
        lines.append("ธง: " + ", ".join(FLAG_TH.get(f, f) for f in worst["flags"]) + " (ค่าอ้างอิง ต้องตรวจกฎหมาย)")
    lines += ["", "เป็นเครื่องมือวางแผน ไม่ใช่คำแนะนำลงทุน ตัวเลขมาจากการจำลอง 5,000 แบบ"]
    return dict(text="\n".join(lines), p_survive=p, top_debtor=top, worst_debt=worst["name"])


def push(text: str, token: str, user_id: str, timeout: int = 15) -> dict:
    body = json.dumps(dict(to=user_id, messages=[dict(type="text", text=text[:4900])])).encode()
    req = urllib.request.Request("https://api.line.me/v2/bot/message/push", body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(sent=True, status=r.status)
    except Exception as e:
        return dict(sent=False, error=str(e)[:200])


def send_weekly(msg: dict) -> dict:
    tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
    if not (tok and uid):
        return dict(sent=False, reason_th="ยังไม่ได้ตั้ง LINE_CHANNEL_TOKEN / LINE_USER_ID จึงแสดงตัวอย่างข้อความเท่านั้น")
    return push(msg["text"], tok, uid)
