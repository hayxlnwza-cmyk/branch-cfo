"""Natural language -> branch patch. Rules handle the common Thai what-if sentences (several can be combined in one
sentence); an LLM is only a fallback. Either way the text only produces PARAMETERS; the engine computes numbers."""
from __future__ import annotations

import json
import os
import re
import urllib.request

ALLOWED = {"name", "reason", "cash_delta", "g_delta", "sigma_delta", "v_delta", "add_fixed", "add_revenue",
           "debts", "collection_updates", "assumptions"}
SCHEMA_HELP = """Return ONLY a JSON object (no prose) with optional keys:
name, reason (Thai), cash_delta (baht, capex negative), g_delta, sigma_delta, v_delta (fractions),
add_fixed [{amount,start,end?}], add_revenue [{share,start,ramp}] (share of main revenue),
debts [{pmt,start,n}], assumptions [strings]. Months are 1..12 from next month. Never output forecasts."""

EXAMPLES_TH = ("เปิดสาขาสอง · ขึ้นราคา 8% · ลดราคา 10% · กู้ 200000 · จ้างพนักงานเพิ่ม 2 คน · ลดพนักงาน 1 คน · "
               "ค่าเช่าเพิ่ม 5000 · ลดต้นทุนวัตถุดิบ 5% · ยอดขายลด 15% · ซื้อเครื่อง 150000 · "
               "ยิงแอด 10000 ต่อเดือน · เจ้าของใส่เงินเพิ่ม 100000 · ปิดหนี้นอกระบบ")

_GREETING = re.compile(r"(สวัสดี|หวัดดี|ขอบคุณ|ครับ|ค่ะ|โอเค|ok|hi|hello|ทดสอบ|test)+")
_TH_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_WORDS = {"หนึ่ง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9, "สิบ": 10}
_UNIT = {"ล้าน": 1e6, "แสน": 1e5, "หมื่น": 1e4, "พัน": 1e3, "ร้อย": 1e2, "k": 1e3, "m": 1e6}
PCT = r"(?:%|เปอร์เซ็นต์|เปอร์เซนต์|เปอร์เซ็น|เปอเซ็นต์|เปอเซ็น|percent|เปอร์)"
NUM = r"(\d[\d,]*(?:\.\d+)?)"
AMT = NUM + r"\s*(ล้าน|แสน|หมื่น|พัน|ร้อย|k|m)?"


def normalize(text: str) -> str:
    t = text.lower().translate(_TH_DIGITS)
    t = re.sub(r"(หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ)(?=\s*(?:ล้าน|แสน|หมื่น|พัน|ร้อย|" + PCT + r"|คน|เดือน|งวด|ปี|บาท))",
               lambda m: str(_WORDS[m.group(1)]), t)
    return t


def _amt(num: str, unit: str | None) -> float:
    return float(num.replace(",", "")) * _UNIT.get(unit or "", 1.0)


def _pct(s: str) -> float:
    return float(s) / 100.0


def _p(params: dict, key: str, default: float) -> float:
    try:
        return float(params[key])
    except Exception:
        return default


# ---- each rule: (text, params, ctx) -> (patch|None, remaining_text). A matched span is removed so rules don't overlap.
def _r_second_branch(t, params, ctx):
    pat = r"สาขาสอง|สาขาที่สอง|สาขาใหม่|เปิดสาขา|second branch|new branch"
    if re.search(pat, t):
        return dict(ctx["second_branch"], name=ctx["second_branch"].get("name", "เปิดสาขาสอง")), re.sub(pat, " ", t)
    return None, t


def _r_pay_informal(t, params, ctx):
    m = re.search(r"(?:ปิด|ล้าง|โปะ|จ่ายคืน|ชำระ)หนี้(?:นอกระบบ|ก้อนแพง)?", t)
    if not m:
        return None, t
    d = next((x for x in ctx.get("debts", []) if x.get("kind") == "informal"), None)
    if d is None:
        return None, t
    pmt = float(d["principal"]) * float(d["rate_monthly"])
    n = int(d.get("horizon", 12))
    return dict(name="ปิดหนี้นอกระบบ", cash_delta=-float(d["principal"]), debts=[dict(pmt=-pmt, start=1, n=n)],
                assumptions=[f"จ่ายต้น {d['principal']:,.0f} บาท ครั้งเดียว แล้วไม่ต้องจ่ายดอกเบี้ย {pmt:,.0f}/เดือน"]), t[:m.start()] + t[m.end():]


def _r_cost(t, params, ctx):
    v = _p(params, "v", 0.4)
    m = re.search(r"(?:ลด|ประหยัด)(?:ต้นทุน|ค่าวัตถุดิบ|วัตถุดิบ)(?:ผันแปร)?[^\d]{0,16}" + NUM + r"\s*" + PCT, t)
    sign = -1
    if not m:
        m = re.search(r"(?:ต้นทุน|วัตถุดิบ|ค่าวัตถุดิบ|ของ)(?:ผันแปร)?[^\d]{0,12}?(?:เพิ่ม|ขึ้น|แพงขึ้น|แพง)[^\d]{0,8}" + NUM + r"\s*" + PCT, t)
        sign = 1
    if not m:
        return None, t
    x = _pct(m.group(1))
    return dict(name=f"{'ลดต้นทุนผันแปร' if sign < 0 else 'ต้นทุนผันแปรเพิ่ม'} {x*100:g}%", v_delta=sign * v * x,
                assumptions=[f"ต้นทุนผันแปรต่อยอดขาย {v*100:.0f}% → {(v*(1+sign*x))*100:.1f}%"]), t[:m.start()] + t[m.end():]


def _r_price(t, params, ctx):
    m = re.search(r"(ขึ้น|เพิ่ม|ปรับขึ้น|ลด|ปรับลด|ลดลง)\s*ราคา[^\d]{0,8}" + NUM + r"\s*" + PCT, t)
    sign = None
    if m:
        sign = 1 if m.group(1) in ("ขึ้น", "เพิ่ม", "ปรับขึ้น") else -1
        val = m.group(2)
    else:
        m = re.search(r"ราคา[^\d]{0,4}(ขึ้น|เพิ่ม|ลด|ลดลง)[^\d]{0,8}" + NUM + r"\s*" + PCT, t) or \
            re.search(r"(?:raise|increase|cut|lower|reduce)\s*(?:prices?|price)?\s*(?:by)?\s*" + NUM + r"\s*" + PCT, t)
        if not m:
            return None, t
        if len(m.groups()) == 3:
            sign = 1 if m.group(1) in ("ขึ้น", "เพิ่ม") else -1
            val = m.group(2)
        else:
            sign = -1 if re.search(r"cut|lower|reduce", m.group(0)) else 1
            val = m.group(1)
    p = sign * _pct(val)
    e = 0.5  # assumed price elasticity of volume
    mult = (1 + p) * (1 - e * p)
    v = _p(params, "v", 0.4)
    nm = f"{'ขึ้น' if p > 0 else 'ลด'}ราคา {abs(p)*100:g}%"
    return dict(name=nm, add_revenue=[dict(share=mult - 1, start=1, ramp=1)], v_delta=v * (1 - e * p) / mult - v,
                assumptions=[f"สมมติความยืดหยุ่นของปริมาณต่อราคา = -{e} (ปรับได้)"]), t[:m.start()] + t[m.end():]


def _r_loan(t, params, ctx):
    m = re.search(r"(?:กู้|ขอสินเชื่อ|ยืมเงิน|สินเชื่อ)[^\d]{0,12}" + AMT, t)
    if not m:
        return None, t
    amt = _amt(m.group(1), m.group(2))
    rest = t[m.end():m.end() + 60]
    ir = re.search(r"ดอก(?:เบี้ย)?[^\d]{0,6}" + NUM + r"\s*" + PCT, rest)
    apr = _pct(ir.group(1)) if ir else 0.18
    n = 24
    mn = re.search(NUM + r"\s*(งวด|เดือน|ปี)", rest)
    if mn:
        n = int(float(mn.group(1)) * (12 if mn.group(2) == "ปี" else 1))
    n = max(1, min(120, n))
    i = apr / 12
    pmt = amt * i / (1 - (1 + i) ** -n) if i > 0 else amt / n
    return dict(name=f"กู้เพิ่ม {amt:,.0f}", cash_delta=amt, debts=[dict(pmt=pmt, start=1, n=n)],
                assumptions=[f"สมมติดอกเบี้ย {apr*100:g}% ต่อปี {n} งวด (ค่างวด {pmt:,.0f} บาท)"]), t[:m.start()] + t[m.end():]


def _r_staff(t, params, ctx):
    wage = 15000.0
    mw = re.search(r"เงินเดือน[^\d]{0,6}" + AMT, t)
    if mw:
        wage = _amt(mw.group(1), mw.group(2))
        t = t[:mw.start()] + t[mw.end():]
    m = re.search(r"(?:จ้าง|รับ|เพิ่ม|ขยาย)(?:พนักงาน|คนงาน|ลูกจ้าง|คน)?[^\d]{0,6}" + NUM + r"\s*คน", t)
    sign = 1
    if not m:
        m = re.search(r"(?:ปลด|ลด|เลิกจ้าง|ไล่)(?:พนักงาน|คนงาน|ลูกจ้าง|คน)?[^\d]{0,6}" + NUM + r"\s*คน", t)
        sign = -1
    if not m:
        return None, t
    k = float(m.group(1))
    return dict(name=f"{'จ้าง' if sign > 0 else 'ลด'}พนักงาน {k:g} คน", add_fixed=[dict(amount=sign * k * wage, start=1)],
                assumptions=[f"สมมติเงินเดือนรวมค่าใช้จ่าย {wage:,.0f} บาท/คน/เดือน และยังไม่คิดผลต่อยอดขาย"]), t[:m.start()] + t[m.end():]


def _r_fixed(t, params, ctx):
    F = _p(params, "F", 0.0)
    m = re.search(r"(ค่าเช่า|ค่าไฟ|ค่าน้ำ|ค่าใช้จ่ายประจำ|ค่าใช้จ่าย|ต้นทุนคงที่)[^\d%]{0,12}?(เพิ่ม|ขึ้น|ลด)(?:ขึ้น|ลง)?[^\d]{0,6}" + AMT + r"(\s*" + PCT + r")?", t)
    if not m:
        return None, t
    sign = -1 if m.group(2) == "ลด" else 1
    if m.group(5):
        amt = F * _pct(m.group(3))
        note = f"คิดเป็น {m.group(3)}% ของค่าใช้จ่ายคงที่ {F:,.0f} บาท/เดือน"
    else:
        amt = _amt(m.group(3), m.group(4))
        note = "ต่อเดือน ตั้งแต่เดือนหน้า"
    return dict(name=f"{m.group(1)}{'ลด' if sign < 0 else 'เพิ่ม'} {amt:,.0f}", add_fixed=[dict(amount=sign * amt, start=1)],
                assumptions=[note]), t[:m.start()] + t[m.end():]


def _r_revenue(t, params, ctx):
    m = re.search(r"(ยอดขาย|รายได้|ลูกค้า)[^\d]{0,6}?(เพิ่ม|ขึ้น|โต|ลด|ตก|หาย|ลดลง)(?:ขึ้น|ลง)?[^\d]{0,6}" + NUM + r"\s*" + PCT, t)
    if not m:
        return None, t
    sign = 1 if m.group(2) in ("เพิ่ม", "ขึ้น", "โต") else -1
    x = _pct(m.group(3))
    return dict(name=f"{m.group(1)}{'เพิ่ม' if sign > 0 else 'ลด'} {x*100:g}%", add_revenue=[dict(share=sign * x, start=1, ramp=1)],
                assumptions=["สมมติต้นทุนผันแปรเป็นสัดส่วนเดิมของยอดขาย"]), t[:m.start()] + t[m.end():]


def _r_marketing(t, params, ctx):
    m = re.search(r"(ยิงแอด|โฆษณา|การตลาด|โปรโมท|โปรโมชั่น|โปรโมชัน|ทำแอด)[^\d]{0,12}" + AMT + r"(\s*(?:ต่อเดือน|/เดือน|ทุกเดือน|รายเดือน))?", t)
    if not m:
        return None, t
    amt = _amt(m.group(2), m.group(3))
    if m.group(4):
        R0 = _p(params, "R0", 0.0)
        roi = 1.5
        share = roi * amt / R0 if R0 > 0 else 0.0
        return dict(name=f"{m.group(1)} {amt:,.0f}/เดือน", add_fixed=[dict(amount=amt, start=1)],
                    add_revenue=[dict(share=share, start=1, ramp=2)],
                    assumptions=[f"สมมติได้ยอดขายเพิ่ม {roi} เท่าของงบ (= {share*100:.1f}% ของรายได้) ค่านี้เดาเอง ควรปรับตามจริง"]), t[:m.start()] + t[m.end():]
    return dict(name=f"{m.group(1)} {amt:,.0f} (ครั้งเดียว)", cash_delta=-amt,
                assumptions=["ค่าใช้จ่ายครั้งเดียว ยังไม่คิดผลต่อยอดขาย"]), t[:m.start()] + t[m.end():]


def _r_inject(t, params, ctx):
    m = re.search(r"(?:เพิ่มทุน|ใส่เงิน|ลงเงิน|เติมเงิน|ได้เงิน|รับเงิน|ได้ทุน|หาทุน)[^\d]{0,12}" + AMT, t)
    if not m:
        return None, t
    amt = _amt(m.group(1), m.group(2))
    return dict(name=f"เงินเข้า {amt:,.0f}", cash_delta=amt, assumptions=["เงินก้อนเข้าครั้งเดียว ไม่มีภาระผ่อน"]), t[:m.start()] + t[m.end():]


def _r_capex(t, params, ctx):
    m = re.search(r"(?:ซื้อ|ลงทุน|ปรับปรุง|รีโนเวท|ซ่อม|ต่อเติม|ซื้อเครื่อง)[^\d]{0,16}" + AMT, t)
    if not m:
        return None, t
    amt = _amt(m.group(1), m.group(2))
    return dict(name=f"ลงทุน {amt:,.0f}", cash_delta=-amt, assumptions=["จ่ายสดครั้งเดียว ยังไม่คิดผลต่อยอดขาย/ต้นทุน"]), t[:m.start()] + t[m.end():]


# ---- fallback layer: the user should always get an answer. Missing numbers get a stated default (shown as an
# assumption on screen); an unrecognised sentence becomes a labelled +/-10% revenue sensitivity test.
def _defaults(t, params, ctx):
    """Intents with no number in the sentence -> default magnitude, always listed in `assumptions`."""
    R0, F, v = _p(params, "R0", 0.0), _p(params, "F", 0.0), _p(params, "v", 0.4)
    out = []
    def has(pat): return re.search(pat, t)
    if has(r"ปิด(?:ร้าน|สาขา|กิจการ)|หยุด(?:ขาย|กิจการ)|น้ำท่วม|ไฟไหม้|โควิด|ล็อกดาวน์|lockdown"):
        out.append(dict(name="ยอดขายหายหนัก", add_revenue=[dict(share=-0.5, start=1, ramp=1)],
                        assumptions=["ไม่ได้ระบุระยะเวลา/ขนาด สมมติยอดขายหาย 50% ตลอด 12 เดือน (เป็นกรณีเลวร้าย)"]))
    elif has(r"ขึ้นราคา|ปรับราคาขึ้น"):
        out.append(_r_price("ขึ้นราคา 5%", params, ctx)[0] | dict(name="ขึ้นราคา (สมมติ 5%)"))
    elif has(r"ลดราคา|โปรโมชั่น|โปรโมชัน|ลดแลกแจก|ส่วนลด"):
        out.append(_r_price("ลดราคา 10%", params, ctx)[0] | dict(name="ลดราคา/โปร (สมมติ 10%)"))
    if has(r"(?:จ้าง|รับ|เพิ่ม)(?:พนักงาน|คนงาน|ลูกจ้าง)"):
        out.append(dict(name="จ้างพนักงานเพิ่ม (สมมติ 1 คน)", add_fixed=[dict(amount=15000.0, start=1)],
                        assumptions=["ไม่ได้ระบุจำนวน สมมติ 1 คน เงินเดือน 15,000 บาท"]))
    elif has(r"(?:ปลด|ลด|เลิกจ้าง)(?:พนักงาน|คนงาน|ลูกจ้าง)"):
        out.append(dict(name="ลดพนักงาน (สมมติ 1 คน)", add_fixed=[dict(amount=-15000.0, start=1)],
                        assumptions=["ไม่ได้ระบุจำนวน สมมติ 1 คน เงินเดือน 15,000 บาท"]))
    if has(r"กู้|สินเชื่อ|ยืมเงิน"):
        amt = round(R0, -3) or 100000.0
        i, n = 0.18 / 12, 24
        pmt = amt * i / (1 - (1 + i) ** -n)
        out.append(dict(name=f"กู้เพิ่ม (สมมติ {amt:,.0f})", cash_delta=amt, debts=[dict(pmt=pmt, start=1, n=n)],
                        assumptions=[f"ไม่ได้ระบุวงเงิน สมมติเท่ายอดขาย 1 เดือน = {amt:,.0f} บาท ดอก 18%/ปี 24 งวด"]))
    if has(r"ลงทุน|ซื้อเครื่อง|ซื้ออุปกรณ์|รีโนเวท|ปรับปรุงร้าน|ซ่อม"):
        amt = round(R0, -3) or 100000.0
        out.append(dict(name=f"ลงทุน (สมมติ {amt:,.0f})", cash_delta=-amt,
                        assumptions=[f"ไม่ได้ระบุจำนวนเงิน สมมติเท่ายอดขาย 1 เดือน = {amt:,.0f} บาท จ่ายสดครั้งเดียว"]))
    if has(r"ยิงแอด|โฆษณา|การตลาด|โปรโมท|ทำแอด"):
        amt = round(0.05 * R0, -2) or 5000.0
        share = 1.5 * amt / R0 if R0 > 0 else 0.0
        out.append(dict(name=f"ทำการตลาด (สมมติ {amt:,.0f}/เดือน)", add_fixed=[dict(amount=amt, start=1)],
                        add_revenue=[dict(share=share, start=1, ramp=2)],
                        assumptions=[f"ไม่ได้ระบุงบ สมมติ 5% ของรายได้ = {amt:,.0f}/เดือน และได้ยอดขายคืน 1.5 เท่าของงบ (เดา)"]))
    if has(r"ค่าเช่า|ค่าไฟ|ค่าน้ำ|ค่าใช้จ่าย|ต้นทุนคงที่|ดอกเบี้ยขึ้น"):
        up = not has(r"ลด|ถูกลง|ประหยัด")
        amt = round(0.1 * F, -2) or 3000.0
        out.append(dict(name=f"ค่าใช้จ่ายคงที่{'เพิ่ม' if up else 'ลด'} (สมมติ 10%)", add_fixed=[dict(amount=amt if up else -amt, start=1)],
                        assumptions=[f"ไม่ได้ระบุจำนวน สมมติ 10% ของค่าใช้จ่ายคงที่ = {amt:,.0f} บาท/เดือน"]))
    if has(r"ต้นทุน|วัตถุดิบ|ของแพง"):
        down = has(r"ลด|ถูกลง|ประหยัด")
        out.append(dict(name=f"ต้นทุนผันแปร{'ลด' if down else 'เพิ่ม'} (สมมติ 5%)", v_delta=(-1 if down else 1) * v * 0.05,
                        assumptions=["ไม่ได้ระบุ % สมมติต้นทุนผันแปรเปลี่ยน 5% ของสัดส่วนเดิม"]))
    if has(r"ยอดขาย|รายได้|ลูกค้า|คู่แข่ง|เศรษฐกิจ|ฤดูกาล|หน้าฝน|หน้าหนาว|เทศกาล|ท่องเที่ยว"):
        neg = has(r"ลด|ตก|หาย|แย่|ซบเซา|ถดถอย|น้อยลง|คู่แข่ง|ไม่ดี|ฝืด")
        out.append(dict(name=f"ยอดขาย{'ลด' if neg else 'เพิ่ม'} (สมมติ 10%)", add_revenue=[dict(share=-0.1 if neg else 0.1, start=1, ramp=1)],
                        assumptions=["ไม่ได้ระบุ % สมมติยอดขายเปลี่ยน 10%"]))
    return out


def fallback_patch(text: str) -> dict:
    """Last resort: never fail. A plainly-labelled standard stress test, not a guess dressed up as the user's scenario."""
    t = normalize(text)
    up = bool(re.search(r"ดีขึ้น|โต|เพิ่ม|ปัง|บูม|ขายดี|รวย", t)) and not re.search(r"ลด|ตก|แย่|หาย|เจ๊ง|ล้ม", t)
    sh = 0.1 if up else -0.1
    return dict(name="ทดสอบความไว: ยอดขาย " + ("+10%" if up else "-10%"),
                add_revenue=[dict(share=sh, start=1, ramp=1)], reason=text,
                assumptions=["ระบบไม่พบการกระทำ/ตัวเลขที่เจาะจงในประโยคนี้ จึงทดสอบความไวมาตรฐาน (ยอดขายเปลี่ยน 10%) แทน",
                             "บอกเป็นการกระทำ+ตัวเลข เช่น “ขึ้นราคา 8%” เพื่อได้ผลที่ตรงกับสถานการณ์จริง"])


RULES = (_r_second_branch, _r_pay_informal, _r_cost, _r_price, _r_loan, _r_staff, _r_fixed, _r_revenue,
         _r_marketing, _r_inject, _r_capex)


def merge_patches(ps: list[dict]) -> dict:
    out: dict = {}
    for p in ps:
        for k, v in p.items():
            if k in ("cash_delta", "g_delta", "sigma_delta", "v_delta"):
                out[k] = out.get(k, 0.0) + float(v)
            elif k in ("add_fixed", "add_revenue", "debts", "assumptions", "collection_updates"):
                out.setdefault(k, []).extend(v)
            elif k == "name":
                out["name"] = (out["name"] + " + " + v) if "name" in out else v
    out["name"] = out.get("name", "branch")[:70]
    return out


def validate(patch: dict) -> dict:
    out = {k: v for k, v in patch.items() if k in ALLOWED}
    for k, lo, hi in (("cash_delta", -5e8, 5e8), ("g_delta", -0.2, 0.2), ("sigma_delta", -0.2, 0.3),
                      ("v_delta", -0.5, 0.5)):
        if k in out:
            out[k] = max(lo, min(hi, float(out[k])))
    for key, fields in (("add_fixed", ("amount", "start", "end")), ("add_revenue", ("share", "start", "ramp")),
                        ("debts", ("pmt", "start", "n"))):
        if key in out:
            out[key] = [{f: float(i[f]) if f in ("amount", "share", "pmt") else int(i[f])
                         for f in fields if f in i} for i in out[key]][:8]
    for i in out.get("add_revenue", []):
        i["share"] = max(-0.9, min(3.0, i["share"]))
    return out


def rule_based(text: str, params: dict, ctx: dict) -> dict | None:
    t = normalize(text)
    found = []
    for rule in RULES:
        p, t = rule(t, params, ctx)
        if p:
            found.append(p)
    if not found:
        found = _defaults(normalize(text), params, ctx)
    if not found:
        return None
    patch = merge_patches(found)
    patch["reason"] = text
    return patch


def llm_patch(text: str, params: dict) -> dict | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = json.dumps(dict(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), max_tokens=700,
        system=SCHEMA_HELP,
        messages=[dict(role="user", content=f"Business params: v={params['v']}, fixed={params['F']}, "
                                            f"cash={params['cash0']}.\nUser says: {text}")],
    )).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body, {
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = json.loads(r.read())["content"][0]["text"]
        return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    except Exception:
        return None


def parse(text: str, params: dict, ctx: dict) -> dict:
    """ctx: second_branch (patch template), debts (list of debt dicts)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("ยังไม่ได้พิมพ์สถานการณ์ ลองเช่น: " + EXAMPLES_TH)
    patch = rule_based(text, params, ctx)
    source = "rules"
    if patch is None:
        patch, source = llm_patch(text, params), "llm"
    if patch is None:
        if _GREETING.fullmatch(re.sub(r"[\s!?.]+", "", text.lower())) or len(text) < 3:
            raise ValueError("ยังไม่ใช่สถานการณ์ “ถ้า…” ลองพูดการกระทำ+ตัวเลข เช่น: " + EXAMPLES_TH)
        patch, source = fallback_patch(text), "fallback"
    return dict(patch=validate(patch), source=source)
