"""FastAPI wrapper around the engine. Run from repo root:  uvicorn api.main:app --port 8000"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import ENGINE_VERSION, backtest as bt, branch as br, debt as dbt, forecast as fc
from engine import guardrails as gd, ledger, lender_export, line_summary
from . import nlpatch

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "data" / "seed.json").read_text())
N_PATHS, T, SEED_RNG = 5000, 12, 42

app = FastAPI(title="Branch CFO", version=ENGINE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_lock = threading.Lock()
S: dict = {}


def reset():
    S.clear()
    S.update(params=copy.deepcopy(SEED["params"]), branches=copy.deepcopy(SEED["branches"]),
             version=0, bt_cache=None, calls=[], guard=gd.new_state())


reset()


def bump():
    S["version"] += 1


def _demo_override() -> bool:
    """Hours/quota blocks may be lifted ONLY on synthetic demo data, and the decision says so explicitly."""
    return bool(SEED.get("synthetic")) and os.getenv("GUARD_DEMO", "1") != "0"


def _debtor_ids() -> list:
    return [c["id"] for c in S["params"]["collections"]]


def _branch(bid: str) -> dict:
    if bid not in S["branches"]:
        raise HTTPException(404, f"no branch '{bid}'")
    return S["branches"][bid]


# ------------------------------------------------------------------ read
@app.get("/api/state")
def state():
    p = S["params"]
    return dict(
        synthetic=SEED["synthetic"], notice=SEED["notice"], version=S["version"], engine=ENGINE_VERSION,
        business=SEED["business"], history=SEED["history"],
        fit={k: SEED["fit"][k] for k in ("g", "sigma", "R0", "season", "n_obs")},
        assumptions=dict(v=p["v"], F=p["F"], cash0=p["cash0"], min_cash=p["min_cash"], horizon=T, n_paths=N_PATHS, seed=SEED_RNG),
        debts=SEED["debts"], collections=p["collections"],
        branches={k: dict(name=v.get("name", k), reason=v.get("reason", "")) for k, v in S["branches"].items()},
        ledger=ledger.list_entries(), calls=S["calls"][-10:],
    )


@app.get("/api/health")
def health():
    return dict(ok=True, engine=ENGINE_VERSION)


@app.get("/api/config")
def config():
    """Runtime config for the web app (agent IDs are public identifiers; set them as env vars on the host)."""
    return dict(advisor_agent_id=os.getenv("ELEVENLABS_ADVISOR_AGENT_ID", ""),
                collector_agent_id=os.getenv("ELEVENLABS_COLLECTOR_AGENT_ID", ""))


@app.get("/api/version")
def version():
    return dict(version=S["version"])


@app.get("/api/forecast")
def forecast(branch: str | None = None):
    p = br.apply_patch(S["params"], _branch(branch)) if branch else S["params"]
    return fc.run(p, N_PATHS, T, SEED_RNG)


class CompareReq(BaseModel):
    branch_id: str | None = None
    patch: dict | None = None
    name: str | None = None


@app.post("/api/compare")
def compare(req: CompareReq):
    patch = _branch(req.branch_id) if req.branch_id else nlpatch.validate(req.patch or {})
    if not req.branch_id:
        bid = (req.name or patch.get("name") or f"branch-{len(S['branches'])+1}").strip()
        S["branches"][bid] = patch
        req.branch_id = bid
        bump()
    out = br.compare(S["params"], patch, N_PATHS, T, SEED_RNG)
    out["branch_id"] = req.branch_id
    return out


class ParseReq(BaseModel):
    text: str


@app.post("/api/parse")
def parse(req: ParseReq):
    try:
        res = nlpatch.parse(req.text, S["params"], SEED["branches"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    patch = res["patch"]
    bid = patch.get("name", "branch")
    S["branches"][bid] = patch
    bump()
    out = br.compare(S["params"], patch, N_PATHS, T, SEED_RNG)
    out.update(branch_id=bid, source=res["source"])
    return out


@app.get("/api/debt")
def debt():
    return dbt.report(SEED["debts"])


@app.get("/api/backtest")
def backtest():
    if S["bt_cache"] is None:
        roll = bt.rolling_backtest(SEED["history"], SEED["business"]["first_month"], H=3, min_train=15)
        cal = bt.calibration_study(SEED["true_params"], n_series=400, train=18)
        S["bt_cache"] = dict(rolling=roll, calibration=cal, target_coverage=0.80)
    return S["bt_cache"]


@app.get("/api/lender_export")
def lender():
    return lender_export.export(S["params"], ledger.list_entries(), N_PATHS, T, SEED_RNG)


# ------------------------------------------------------------------ write
class OutcomeReq(BaseModel):
    customer_id: str
    promised_month: int | None = None   # months from now (1..12); None = refused / no commitment
    confidence: float | None = None     # agent's estimate that promise is kept; default 0.75
    note: str | None = None
    spoke_to_debtor: bool = True        # False = someone else answered -> nothing is recorded or disclosed


@app.post("/api/collections/outcome")
def collection_outcome(req: OutcomeReq):
    """Voice agent result -> collection assumptions (3.6) -> survival moves live."""
    with _lock:
        c = next((x for x in S["params"]["collections"] if x["id"] == req.customer_id), None)
        if c is None:
            raise HTTPException(404, "unknown customer")
        if not req.spoke_to_debtor:
            d = dict(customer_id=c["id"], allowed=False, code="third_party",
                     reason_th="ผู้รับสายไม่ใช่ลูกหนี้ ไม่บันทึกผลและไม่เปิดเผยเรื่องหนี้")
            gd.audit(S["guard"], "record_blocked", d)
            return dict(recorded=False, code=d["code"], reason_th=d["reason_th"])
        if c["id"] in S["guard"]["stop"]:
            d = dict(customer_id=c["id"], allowed=False, code="stopped", reason_th="ลูกหนี้ขอให้หยุดติดต่อแล้ว")
            gd.audit(S["guard"], "record_blocked", d)
            return dict(recorded=False, code=d["code"], reason_th=d["reason_th"])
        before = fc.run(S["params"], N_PATHS, T, SEED_RNG)["p_survive"]
        old = dict(tau=c["tau"], q=c["q"])
        if req.promised_month is not None:
            c["tau"] = max(1, min(T, int(req.promised_month)))
            c["q"] = float(req.confidence if req.confidence is not None else 0.75)
        else:
            c["q"] = max(0.05, c["q"] * 0.7)  # refused: lower the belief
        after = fc.run(S["params"], N_PATHS, T, SEED_RNG)["p_survive"]
        S["calls"].append(dict(customer_id=c["id"], name=c["name"], old=old, new=dict(tau=c["tau"], q=c["q"]),
                               p_before=before, p_after=after, note=req.note))
        bump()
    return dict(recorded=True, customer=c["name"], old=old, new=dict(tau=c["tau"], q=c["q"]),
                p_survive_before=before, p_survive_after=after)


class MergeReq(BaseModel):
    branch_id: str
    reason: str = ""


@app.post("/api/merge")
def merge(req: MergeReq):
    with _lock:
        patch = _branch(req.branch_id)
        cmp = br.compare(S["params"], patch, N_PATHS, T, SEED_RNG)
        res = dict(delta_p=cmp["delta_p"], p_base=cmp["base"]["p_survive"], p_branch=cmp["branch"]["p_survive"],
                   min_cash_p5=cmp["branch"]["min_cash_pct"]["p5"], trough_month=cmp["branch"]["trough_month_mode"])
        entry = ledger.write_entry("merge", patch.get("name", req.branch_id), S["params"], patch, res,
                                   req.reason or patch.get("reason", ""), SEED_RNG, N_PATHS, T)
        S["params"] = br.apply_patch(S["params"], patch)
        S["branches"].pop(req.branch_id, None)
        git = ledger.commit(entry["file"], f"ledger: merge '{patch.get('name', req.branch_id)}' "
                                           f"(P {res['p_base']:.0%} -> {res['p_branch']:.0%})")
        bump()
    return dict(file=entry["file"], sha256=entry["sha256"], git=git, result=res)


@app.post("/api/reset")
def reset_api():
    reset()
    return dict(ok=True)


# ------------------------------------------------------------------ guardrails (enforced in code)
@app.get("/api/guardrails")
def guardrails():
    """Rules, per-debtor 'may we call now?' status, stop list and audit log (for the safety panel)."""
    return dict(gd.snapshot(gd.policy_from_env(), S["guard"], _debtor_ids()), demo_override=_demo_override())


class StartCallReq(BaseModel):
    customer_id: str
    at: str | None = None   # ISO time, only to demonstrate/test the hour rule (e.g. "2026-10-15T22:00:00+07:00")


@app.post("/api/guard/start_call")
def guard_start_call(req: StartCallReq):
    """The web app calls this BEFORE opening a voice session. Refused = the call button must not start a call."""
    with _lock:
        now = datetime.fromisoformat(req.at) if req.at else None
        if now is not None and now.tzinfo is None:
            now = now.replace(tzinfo=gd.TH)
        d = gd.start_call(gd.policy_from_env(), S["guard"], req.customer_id, set(_debtor_ids()), now,
                          demo_override=_demo_override() and req.at is None)
        bump()
    return d


class StopReq(BaseModel):
    customer_id: str
    reason: str = ""


@app.post("/api/tools/stop_contact")
def tool_stop_contact(req: StopReq):
    """Agent tool: debtor asked us to stop calling. Permanent, logged in the evidence ledger."""
    with _lock:
        c = next((x for x in S["params"]["collections"] if x["id"] == req.customer_id), None)
        if c is None:
            raise HTTPException(404, "unknown customer")
        d = gd.request_stop(S["guard"], c["id"], req.reason)
        res = dict(customer_id=c["id"], stopped_at=d["at"])
        entry = ledger.write_entry("stop-contact", c["name"], S["params"], {}, res,
                                   req.reason or "ลูกหนี้ขอให้หยุดติดต่อ", SEED_RNG, N_PATHS, T)
        git = ledger.commit(entry["file"], f"ledger: stop-contact '{c['name']}'")
        bump()
    return dict(recorded=True, code="stopped", reason_th=d["reason_th"], file=entry["file"], git=git)


# ------------------------------------------------------------------ LINE weekly summary
def _line_msg() -> dict:
    return line_summary.build(S["params"], SEED["debts"], SEED["business"].get("name", "ร้านของคุณ"),
                              bool(SEED.get("synthetic")), N_PATHS, T, SEED_RNG)


@app.get("/api/line/preview")
def line_preview():
    """Exact text that would be pushed to LINE (works with no LINE account)."""
    m = _line_msg()
    return dict(text=m["text"], configured=bool(os.getenv("LINE_CHANNEL_TOKEN") and os.getenv("LINE_USER_ID")))


@app.post("/api/line/weekly")
def line_weekly():
    m = _line_msg()
    return dict(text=m["text"], **line_summary.send_weekly(m))


# ------------------------------------------------------------------ compact tools for the voice agent (server tools)
class ToolForecast(BaseModel):
    pass


@app.post("/api/tools/get_forecast")
def tool_get_forecast(_: ToolForecast | None = None):
    r = fc.run(S["params"], N_PATHS, T, SEED_RNG)
    return dict(p_survive=round(r["p_survive"], 3), min_cash_p5=round(r["min_cash_pct"]["p5"]),
                min_cash_p50=round(r["min_cash_pct"]["p50"]), trough_month=r["trough_month_mode"])


class ToolBranch(BaseModel):
    request_text: str


@app.post("/api/tools/create_branch")
def tool_create_branch(req: ToolBranch):
    o = parse(ParseReq(text=req.request_text))
    return dict(branch_id=o["branch_id"], p_base=round(o["base"]["p_survive"], 3),
                p_branch=round(o["branch"]["p_survive"], 3), delta_p=round(o["delta_p"], 3),
                min_cash_p5_branch=round(o["branch"]["min_cash_pct"]["p5"]),
                trough_month=o["branch"]["trough_month_mode"])


class ToolMerge(BaseModel):
    branch_id: str
    reason: str = ""


@app.post("/api/tools/merge_branch")
def tool_merge(req: ToolMerge):
    return merge(MergeReq(branch_id=req.branch_id, reason=req.reason))


@app.get("/api/tools/get_debt_report")
def tool_debt():
    r = dbt.report(SEED["debts"])
    return dict(items=[dict(name=i["name"], apr_pct=round(i["apr_nominal"] * 100, 1),
                            eir_pct=round(i["eir"] * 100, 1), flags=i["flags"],
                            refinance_monthly_saving=round(i["refinance"]["monthly_cash_change"]))
                       for i in r["items"]])


@app.post("/api/tools/record_promise")
def tool_record_promise(req: OutcomeReq):
    return collection_outcome(req)


@app.get("/api/tools/list_debtors")
def tool_debtors():
    return dict(debtors=[dict(id=c["id"], name=c["name"], amount=c["amount"]) for c in S["params"]["collections"]])


# ------------------------------------------------------------------ static web (after `npm run build`)
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
