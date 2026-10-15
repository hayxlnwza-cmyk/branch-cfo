from fastapi.testclient import TestClient

from api.main import app, reset

c = TestClient(app)


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
