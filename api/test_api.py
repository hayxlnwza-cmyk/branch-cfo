import pytest
from fastapi.testclient import TestClient

from api.main import app, reset

c = TestClient(app)


@pytest.fixture
def isolate_ledger(tmp_path, monkeypatch):
    """Tests must never write ledger files into the repo or make git commits."""
    from engine import ledger as L
    monkeypatch.setattr(L, "LEDGER_DIR", tmp_path / "ledger")
    monkeypatch.setattr(L, "ROOT", tmp_path)
    monkeypatch.setattr(L, "commit", lambda f, m: dict(via="test"))
    import api.main as M
    monkeypatch.setattr(M.ledger, "commit", lambda f, m: dict(via="test"))


def setup_function(_):
    reset()


def test_state_and_forecast():
    s = c.get("/api/state").json()
    assert s["synthetic"] is True and len(s["history"]) == 24
    f = c.get("/api/forecast").json()
    assert 0.6 < f["p_survive"] < 0.9 and len(f["fan"]["p50"]) == 12


def test_parse_second_branch_lowers_survival():
    r = c.post("/api/parse", json={"text": "ถ้าเปิดสาขาสอง"}).json()
    assert r["delta_p"] < -0.1 and r["source"] == "rules"


def test_raise_price_rule_has_assumption():
    r = c.post("/api/parse", json={"text": "ถ้าขึ้นราคา 8%"}).json()
    assert r["patch"]["assumptions"]


def test_collection_call_moves_probability_up():
    r = c.post("/api/collections/outcome", json={"customer_id": "c1", "promised_month": 1, "confidence": 0.9}).json()
    assert r["p_survive_after"] > r["p_survive_before"]


def test_debt_report_worst_is_informal():
    assert c.get("/api/debt").json()["worst"] == "informal"


def test_unknown_customer_404():
    assert c.post("/api/collections/outcome", json={"customer_id": "zzz"}).status_code == 404


def test_merge_writes_ledger_and_git_commit(tmp_path, monkeypatch):
    import subprocess

    from engine import ledger

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    monkeypatch.setattr(ledger, "LEDGER_DIR", tmp_path / "ledger")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    r = c.post("/api/parse", json={"text": "ถ้าขึ้นราคา 8%"}).json()
    p_branch = r["branch"]["p_survive"]
    m = c.post("/api/merge", json={"branch_id": r["branch_id"], "reason": "test"}).json()
    assert (tmp_path / m["file"]).exists() and m["git"].get("commit")
    # after merge the base IS the branch (same seed/paths -> identical survival)
    assert abs(c.get("/api/forecast").json()["p_survive"] - p_branch) < 1e-9
    exp = c.get("/api/lender_export").json()
    assert exp["ledger"] and len(exp["export_sha256"]) == 64
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "ledger: merge" in log


def test_health_and_config(monkeypatch):
    assert c.get("/api/health").json()["ok"] is True
    monkeypatch.setenv("ELEVENLABS_ADVISOR_AGENT_ID", "agent_x")
    cfg = c.get("/api/config").json()
    assert cfg["advisor_agent_id"] == "agent_x" and cfg["collector_agent_id"] == ""


def test_ledger_commit_via_github_api(tmp_path, monkeypatch):
    import io, json as _json
    from engine import ledger

    f = tmp_path / "ledger" / "x.json"
    f.parent.mkdir()
    f.write_text("{}")
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPO", "o/r")
    seen = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake(req, timeout=0):
        seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers["Authorization"], _json.loads(req.data)
        return R(_json.dumps({"commit": {"sha": "abcdef123", "html_url": "c"}, "content": {"html_url": "u"}}).encode())

    monkeypatch.setattr(ledger.urllib.request, "urlopen", fake)
    out = ledger.commit("ledger/x.json", "msg")
    assert out["via"] == "github_api" and out["commit"] == "abcdef1"
    assert seen["url"].endswith("/repos/o/r/contents/ledger/x.json") and seen["auth"] == "Bearer t"
    assert seen["body"]["branch"] == "main" and seen["body"]["content"]


# ---------------------------------------------------------------- guardrails + LINE
def test_guard_blocks_outside_hours_when_time_given():
    r = c.post("/api/guard/start_call", json={"customer_id": "c1", "at": "2026-10-15T22:00:00+07:00"}).json()
    assert r["allowed"] is False and r["code"] == "outside_hours"
    ok = c.post("/api/guard/start_call", json={"customer_id": "c2", "at": "2026-10-15T10:00:00+07:00"}).json()
    assert ok["allowed"] is True
    g = c.get("/api/guardrails").json()
    assert len(g["rules_th"]) >= 5 and g["policy"]["verified_by_lawyer"] is False and g["log"]


def test_guard_demo_override_follows_env(monkeypatch):
    from engine import guardrails as gd
    from datetime import datetime
    monkeypatch.setattr(gd, "now_th", lambda: datetime(2026, 10, 15, 22, 0, tzinfo=gd.TH))
    on = c.post("/api/guard/start_call", json={"customer_id": "c1"}).json()
    assert on["allowed"] and on["demo_override"]
    reset()
    monkeypatch.setenv("GUARD_DEMO", "0")
    off = c.post("/api/guard/start_call", json={"customer_id": "c1"}).json()
    assert off["allowed"] is False and off["code"] == "outside_hours"


def test_third_party_answer_is_not_recorded():
    before = c.get("/api/forecast").json()["p_survive"]
    r = c.post("/api/tools/record_promise", json={"customer_id": "c1", "promised_month": 1, "spoke_to_debtor": False}).json()
    assert r["recorded"] is False and r["code"] == "third_party"
    assert c.get("/api/forecast").json()["p_survive"] == before


def test_stop_contact_blocks_calls_and_promises(tmp_path, monkeypatch):
    import subprocess
    from engine import ledger
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    monkeypatch.setattr(ledger, "LEDGER_DIR", tmp_path / "ledger")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    r = c.post("/api/tools/stop_contact", json={"customer_id": "c1", "reason": "ขอให้หยุดโทร"}).json()
    assert r["recorded"] and (tmp_path / r["file"]).exists()
    d = c.post("/api/guard/start_call", json={"customer_id": "c1", "at": "2026-10-15T10:00:00+07:00"}).json()
    assert d["allowed"] is False and d["code"] == "stopped"
    p = c.post("/api/tools/record_promise", json={"customer_id": "c1", "promised_month": 1}).json()
    assert p["recorded"] is False and p["code"] == "stopped"


def test_line_preview_uses_engine_numbers_and_never_sends_without_token(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)
    monkeypatch.delenv("LINE_USER_ID", raising=False)
    f = c.get("/api/forecast").json()["p_survive"]
    pv = c.get("/api/line/preview").json()
    assert f"{f:.1%}" in pv["text"] and "213.8%" in pv["text"] and pv["configured"] is False
    r = c.post("/api/line/weekly").json()
    assert r["sent"] is False and "LINE_CHANNEL_TOKEN" in r["reason_th"]


def test_line_push_request_shape(monkeypatch):
    import io, json as _json
    from engine import line_summary as ls
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "tok")
    monkeypatch.setenv("LINE_USER_ID", "U123")
    seen = {}

    class R(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake(req, timeout=0):
        seen.update(url=req.full_url, auth=req.headers["Authorization"], body=_json.loads(req.data))
        return R(b"{}")

    monkeypatch.setattr(ls.urllib.request, "urlopen", fake)
    r = c.post("/api/line/weekly").json()
    assert r["sent"] is True and seen["url"].endswith("/v2/bot/message/push")
    assert seen["auth"] == "Bearer tok" and seen["body"]["to"] == "U123"
    assert seen["body"]["messages"][0]["type"] == "text"


def test_thai_branch_name_gives_ascii_ledger_file_and_url(tmp_path, monkeypatch):
    """Regression: Thai names broke the GitHub contents API call ('ascii' codec can't encode...)."""
    import io, json as _json
    from engine import ledger

    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    monkeypatch.setattr(ledger, "LEDGER_DIR", tmp_path / "ledger")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPO", "o/r")
    seen = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake(req, timeout=0):
        req.full_url.encode("ascii")          # what http.client does; raised before the fix
        seen["url"] = req.full_url
        return R(_json.dumps({"commit": {"sha": "abcdef123", "html_url": "u"}, "content": {"html_url": "c"}}).encode())

    monkeypatch.setattr(ledger.urllib.request, "urlopen", fake)
    r = c.post("/api/parse", json={"text": "ถ้าขึ้นราคา 8%"}).json()
    m = c.post("/api/merge", json={"branch_id": r["branch_id"], "reason": "ทดสอบ"}).json()
    assert m["file"].isascii() and m["git"].get("commit") == "abcdef1", m
    assert seen["url"].isascii()


# ---- what-if parsing, live events, real data -------------------------------------------------
import pytest


@pytest.mark.parametrize("text", ["ขึ้นราคา 10 เปอร์เซ็นต์", "ลดราคา 10%", "กู้ สองแสน", "จ้างพนักงานเพิ่ม 2 คน",
                                  "ค่าเช่าเพิ่ม 5000", "ลดต้นทุนวัตถุดิบ 5%", "ยอดขายลด 15%", "ซื้อเครื่อง 150000",
                                  "ยิงแอด 10000 ต่อเดือน", "เจ้าของใส่เงินเพิ่ม 100000", "ปิดหนี้นอกระบบ",
                                  "ขึ้นราคา 5% และจ้างคนเพิ่ม 2 คน"])
def test_parse_many_phrases(text):
    r = c.post("/api/parse", json={"text": text})
    assert r.status_code == 200, text
    assert 0 <= r.json()["branch"]["p_survive"] <= 1


def test_greeting_is_helpful_422():
    r = c.post("/api/parse", json={"text": "สวัสดี"})
    assert r.status_code == 422 and "เช่น" in r.json()["detail"]


@pytest.mark.parametrize("text", ["ถ้าขึ้นราคา", "ถ้าจ้างพนักงานเพิ่ม", "ถ้ากู้เงินมาลงทุน", "ถ้าน้ำท่วมร้าน", "ถ้าคู่แข่งมาเปิดข้างๆ",
                                  "ถ้าค่าเช่าขึ้น", "ถ้าวัตถุดิบแพงขึ้น", "ถ้าทำโปรโมชั่น", "ถ้าฤดูท่องเที่ยวแย่",
                                  "ถ้าผมไปเที่ยวญี่ปุ่นหนึ่งเดือน", "what if we sell more coffee"])
def test_whatif_without_numbers_still_answers(text):
    r = c.post("/api/parse", json={"text": text})
    assert r.status_code == 200, text
    j = r.json()
    assert 0 <= j["branch"]["p_survive"] <= 1 and j["patch"]["assumptions"]


def test_voice_tool_never_returns_error():
    for t in ["ถ้าน้ำท่วม", "ฮัลโหล", ""]:
        r = c.post("/api/tools/create_branch", json={"request_text": t})
        assert r.status_code == 200, t


def test_voice_tools_emit_events_and_merge_by_loose_name(isolate_ledger):
    o = c.post("/api/tools/create_branch", json={"request_text": "ขึ้นราคา 8 เปอร์เซ็นต์"}).json()
    assert o["branch_id"]
    c.get("/api/tools/get_debt_report")
    ev = c.get("/api/state").json()["events"]
    assert [e["tool"] for e in ev][-2:] == ["create_branch", "get_debt_report"]
    m = c.post("/api/tools/merge_branch", json={"branch_id": "ขึ้นราคา", "reason": "test"})
    assert m.status_code == 200 and m.json()["merged"].startswith("ขึ้นราคา")
    assert c.get("/api/state").json()["events"][-1]["tool"] == "merge_branch"


def test_real_data_roundtrip_and_validation(tmp_path, monkeypatch):
    import api.main as m
    monkeypatch.setattr(m, "USER_FILE", tmp_path / "u.json")
    form = c.get("/api/data").json()["form"]
    form["business_name"] = "ร้านทดสอบ"
    assert c.post("/api/data", json=form).status_code == 200
    s = c.get("/api/state").json()
    assert s["synthetic"] is False and s["business"]["name"] == "ร้านทดสอบ"
    bad = dict(form, history=[1, 2, 3])
    assert c.post("/api/data", json=bad).status_code == 422
    assert c.post("/api/parse", json={"text": "เปิดสาขาสอง"}).status_code == 200
    c.post("/api/data/demo")
    assert c.get("/api/state").json()["synthetic"] is True
