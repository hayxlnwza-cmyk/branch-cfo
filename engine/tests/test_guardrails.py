from datetime import datetime

from engine import guardrails as g

P = g.Policy()
IDS = {"c1", "c2"}


def t(*a):
    return datetime(*a, tzinfo=g.TH)


def code(s, cid="c1", now=None, ids=IDS):
    return g.check_call(P, s, cid, ids, now)["code"]


def test_weekday_hours_edges():
    s = g.new_state()
    assert code(s, now=t(2026, 10, 15, 8, 0)) == "ok"
    assert code(s, now=t(2026, 10, 15, 19, 59)) == "ok"
    assert code(s, now=t(2026, 10, 15, 20, 0)) == "outside_hours"
    assert code(s, now=t(2026, 10, 15, 7, 59)) == "outside_hours"


def test_weekend_and_holiday_end_at_18():
    s = g.new_state()
    assert code(s, now=t(2026, 10, 17, 17, 59)) == "ok"        # Saturday
    assert code(s, now=t(2026, 10, 17, 18, 0)) == "outside_hours"
    hol = g.Policy(holidays=frozenset({"2026-10-23"}))           # a Friday
    assert g.check_call(hol, s, "c1", IDS, t(2026, 10, 23, 18, 30))["code"] == "outside_hours"


def test_third_party_never_called():
    assert code(g.new_state(), cid="stranger", now=t(2026, 10, 15, 10)) == "unknown_debtor"


def test_daily_and_weekly_quota():
    s = g.new_state()
    assert g.start_call(P, s, "c1", IDS, t(2026, 10, 12, 10))["allowed"]
    assert code(s, now=t(2026, 10, 12, 15)) == "daily_limit"
    assert g.start_call(P, s, "c1", IDS, t(2026, 10, 14, 10))["allowed"]
    assert code(s, now=t(2026, 10, 15, 10)) == "weekly_limit"      # 2 calls inside 7 days
    assert code(s, now=t(2026, 10, 20, 10)) == "ok"                # first call is now > 7 days old
    assert code(s, cid="c2", now=t(2026, 10, 15, 10)) == "ok"      # quota is per debtor


def test_stop_is_permanent_and_beats_everything():
    s = g.new_state()
    g.request_stop(s, "c1", "อย่าโทรมาอีก", t(2026, 10, 15, 10))
    assert code(s, now=t(2026, 12, 1, 10)) == "stopped"
    assert s["log"][-1]["event"] == "stop_contact"


def test_demo_override_is_explicit_and_limited():
    s = g.new_state()
    d = g.start_call(P, s, "c1", IDS, t(2026, 10, 15, 22), demo_override=True)
    assert d["allowed"] and d["demo_override"] and d["would_block_code"] == "outside_hours"
    assert "โหมดเดโม" in d["reason_th"]
    # override never lifts a stop request or the third-party rule
    g.request_stop(s, "c1", "", t(2026, 10, 15, 22))
    assert not g.start_call(P, s, "c1", IDS, t(2026, 10, 16, 10), demo_override=True)["allowed"]
    assert not g.start_call(P, s, "x", IDS, t(2026, 10, 16, 10), demo_override=True)["allowed"]
