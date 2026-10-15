"""Collection-call guardrails, enforced in code (not only in the agent prompt).

Every decision returns a Thai reason so the UI/judges can see *why* a call was allowed or blocked.
Defaults are a CONFIGURABLE starting point taken from our reading of Thai debt-collection rules
(weekday 08:00-20:00, weekend/holiday 08:00-18:00). They are NOT legally verified:
have a qualified person check them before real use (Policy.verified_by_lawyer stays False until then).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

TH = timezone(timedelta(hours=7))  # Thailand has no DST -> fixed offset, no tzdata dependency

DAY_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


@dataclass(frozen=True)
class Policy:
    weekday_window: tuple = (8, 20)       # [start, end) hour, Asia/Bangkok
    weekend_window: tuple = (8, 18)       # Sat/Sun and listed holidays
    max_calls_per_day: int = 1
    max_calls_per_7d: int = 2
    holidays: frozenset = field(default_factory=frozenset)  # 'YYYY-MM-DD'
    verified_by_lawyer: bool = False


def policy_from_env() -> Policy:
    hol = frozenset(h.strip() for h in os.getenv("GUARD_HOLIDAYS", "").split(",") if h.strip())
    return Policy(max_calls_per_day=int(os.getenv("GUARD_MAX_PER_DAY", "1")),
                  max_calls_per_7d=int(os.getenv("GUARD_MAX_PER_7D", "2")), holidays=hol)


def new_state() -> dict:
    return dict(stop={}, calls=[], log=[])


def now_th() -> datetime:
    return datetime.now(TH)


def _window(policy: Policy, now: datetime) -> tuple:
    off_day = now.weekday() >= 5 or now.strftime("%Y-%m-%d") in policy.holidays
    return policy.weekend_window if off_day else policy.weekday_window


def check_call(policy: Policy, state: dict, customer_id: str, known_ids: set, now: datetime | None = None) -> dict:
    """Pure check. Order matters: who -> consent to stop -> hours -> frequency."""
    now = (now or now_th()).astimezone(TH)
    base = dict(customer_id=customer_id, checked_at=now.isoformat(timespec="minutes"))

    def deny(code, reason):
        return dict(base, allowed=False, code=code, reason_th=reason)

    if customer_id not in known_ids:
        return deny("unknown_debtor", "ไม่ใช่ลูกหนี้ในระบบ จึงไม่โทร (ไม่โทรหาบุคคลที่สาม)")
    if customer_id in state["stop"]:
        s = state["stop"][customer_id]
        return deny("stopped", f"ลูกหนี้ขอให้หยุดติดต่อเมื่อ {s['at'][:16].replace('T', ' ')} จึงห้ามโทรอีก")
    lo, hi = _window(policy, now)
    if not (lo <= now.hour < hi):
        return deny("outside_hours", f"นอกเวลาที่อนุญาต วัน{DAY_TH[now.weekday()]}โทรได้ {lo:02d}:00-{hi:02d}:00 "
                                     f"(ตอนนี้ {now:%H:%M})")
    recent = [datetime.fromisoformat(c["at"]) for c in state["calls"] if c["customer_id"] == customer_id]
    today = [t for t in recent if t.astimezone(TH).date() == now.date()]
    if len(today) >= policy.max_calls_per_day:
        return deny("daily_limit", f"วันนี้โทรครบ {policy.max_calls_per_day} สายแล้ว")
    week = [t for t in recent if now - t < timedelta(days=7)]
    if len(week) >= policy.max_calls_per_7d:
        return deny("weekly_limit", f"7 วันที่ผ่านมาโทรครบ {policy.max_calls_per_7d} สายแล้ว")
    return dict(base, allowed=True, code="ok", reason_th="อยู่ในเวลาและโควตาที่อนุญาต")


def audit(state: dict, event: str, decision: dict, **extra) -> dict:
    row = dict(event=event, at=now_th().isoformat(timespec="seconds"), **{k: decision.get(k) for k in
               ("customer_id", "allowed", "code", "reason_th")}, **extra)
    state["log"].append(row)
    del state["log"][:-200]
    return row


def start_call(policy: Policy, state: dict, customer_id: str, known_ids: set,
               now: datetime | None = None, demo_override: bool = False) -> dict:
    """Check, then (if allowed) count the call against the quota. demo_override only lifts hours/quota blocks
    on synthetic data and is always reported, never silent."""
    d = check_call(policy, state, customer_id, known_ids, now)
    if not d["allowed"] and demo_override and d["code"] in ("outside_hours", "daily_limit", "weekly_limit"):
        d = dict(d, allowed=True, demo_override=True, would_block_code=d["code"],
                 reason_th=f"[โหมดเดโม ข้อมูลสังเคราะห์] ปกติจะถูกบล็อก: {d['reason_th']}")
    if d["allowed"]:
        state["calls"].append(dict(customer_id=customer_id, at=(now or now_th()).astimezone(TH).isoformat()))
    audit(state, "start_call", d)
    return d


def request_stop(state: dict, customer_id: str, reason: str = "", now: datetime | None = None) -> dict:
    at = (now or now_th()).astimezone(TH).isoformat(timespec="seconds")
    state["stop"][customer_id] = dict(at=at, reason=reason)
    d = dict(customer_id=customer_id, allowed=False, code="stopped", reason_th="บันทึกคำขอให้หยุดติดต่อถาวรแล้ว")
    audit(state, "stop_contact", d, note=reason)
    return dict(d, at=at)


def snapshot(policy: Policy, state: dict, known_ids: list, now: datetime | None = None) -> dict:
    ids = set(known_ids)
    return dict(
        policy=dict(asdict(policy), holidays=sorted(policy.holidays)),
        rules_th=[
            "AI แจ้งตัวว่าเป็น AI และบอกวัตถุประสงค์ (ยอดค้างชำระ) ทุกสาย",
            "ห้ามข่มขู่ ประจาน หรือกดดัน เจ้าของอนุมัติสคริปต์ก่อนโทร",
            f"โทรได้เฉพาะวันธรรมดา {policy.weekday_window[0]:02d}:00-{policy.weekday_window[1]:02d}:00 "
            f"และวันหยุด {policy.weekend_window[0]:02d}:00-{policy.weekend_window[1]:02d}:00",
            f"จำกัด {policy.max_calls_per_day} สายต่อวัน และ {policy.max_calls_per_7d} สายต่อ 7 วัน ต่อลูกหนี้",
            "ลูกหนี้ขอให้หยุด = หยุดถาวรโดยระบบ ไม่ใช่แค่คำสั่งใน prompt",
            "โทรเฉพาะลูกหนี้ในระบบ ไม่โทรหาบุคคลที่สาม และไม่เปิดเผยหนี้กับผู้อื่น",
        ],
        status=[check_call(policy, state, i, ids, now) for i in known_ids],
        stopped=state["stop"], log=state["log"][-20:],
        legal_note_th="ค่าเริ่มต้นจากความเข้าใจของทีม ยังไม่ผ่านผู้รู้ด้านกฎหมาย ต้องตรวจก่อนใช้จริง",
    )
