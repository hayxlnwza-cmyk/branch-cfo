"""Natural language -> branch patch. The LLM (or rules) only produces PARAMETERS; engine computes numbers."""
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


def validate(patch: dict) -> dict:
    out = {k: v for k, v in patch.items() if k in ALLOWED}
    for k, lo, hi in (("cash_delta", -5e7, 5e7), ("g_delta", -0.2, 0.2), ("sigma_delta", -0.2, 0.3),
                      ("v_delta", -0.5, 0.5)):
        if k in out:
            out[k] = max(lo, min(hi, float(out[k])))
    for key, fields in (("add_fixed", ("amount", "start", "end")), ("add_revenue", ("share", "start", "ramp")),
                        ("debts", ("pmt", "start", "n"))):
        if key in out:
            out[key] = [{f: float(i[f]) if f in ("amount", "share", "pmt") else int(i[f])
                         for f in fields if f in i} for i in out[key]][:5]
    return out


def rule_based(text: str, params: dict, seed_branches: dict) -> dict | None:
    t = text.lower()
    if any(w in t for w in ("สาขาสอง", "สาขาที่สอง", "สาขาใหม่", "second branch", "new branch", "เปิดสาขา")):
        return {**seed_branches["second-branch"], "reason": text}
    m = re.search(r"ขึ้นราคา\s*(\d+(?:\.\d+)?)\s*%|raise (?:prices?|price) (?:by )?(\d+(?:\.\d+)?)\s*%", t)
    if m:
        p = float(m.group(1) or m.group(2)) / 100
        e = 0.5  # assumed price elasticity of volume
        mult = (1 + p) * (1 - e * p)
        v = params["v"]
        return dict(name=f"ขึ้นราคา {p*100:.0f}%", reason=text,
                    add_revenue=[dict(share=mult - 1, start=1, ramp=1)],
                    v_delta=v * (1 - e * p) / mult - v,
                    assumptions=[f"สมมติความยืดหยุ่นของปริมาณต่อราคา = -{e} (ปรับได้)"])
    m = re.search(r"กู้\s*(\d[\d,]*)", t)
    if m:
        amt = float(m.group(1).replace(",", ""))
        n = 24
        i = 0.18 / 12
        pmt = amt * i / (1 - (1 + i) ** -n)
        return dict(name=f"กู้เพิ่ม {amt:,.0f}", reason=text, cash_delta=amt,
                    debts=[dict(pmt=pmt, start=1, n=n)],
                    assumptions=["สมมติดอกเบี้ย 18% ต่อปี 24 งวด"])
    return None


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


def parse(text: str, params: dict, seed_branches: dict) -> dict:
    patch = rule_based(text, params, seed_branches)
    source = "rules"
    if patch is None:
        patch, source = llm_patch(text, params), "llm"
    if patch is None:
        raise ValueError("แปลงคำพูดเป็นสมมติฐานไม่ได้ ลองระบุเช่น 'เปิดสาขาสอง' หรือ 'ขึ้นราคา 8%'")
    return dict(patch=validate(patch), source=source)
