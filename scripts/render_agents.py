"""Render agents/_templates/tools.json -> agents/tool_configs/*.json with API_BASE (public URL of the API,
e.g. a cloudflared/ngrok tunnel during the hackathon).  Usage: API_BASE=https://xxx.trycloudflare.com python scripts/render_agents.py"""
import json, os, pathlib

root = pathlib.Path(__file__).resolve().parent.parent / "agents"
base = os.environ.get("API_BASE", "").rstrip("/")
if not base:
    raise SystemExit("set API_BASE (public https URL of the FastAPI server)")
out = root / "tool_configs"
out.mkdir(exist_ok=True)
for t in json.loads((root / "_templates" / "tools.json").read_text()):
    t["api_schema"]["url"] = t["api_schema"]["url"].replace("{{API_BASE}}", base)
    (out / f"{t['name']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2))
    print("wrote", out / f"{t['name']}.json")
