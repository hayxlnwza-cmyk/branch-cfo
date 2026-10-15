"""Deterministic guardrail lint for agent prompts (runs in CI). Fails if safety rules are missing."""
import json, pathlib, sys

root = pathlib.Path(__file__).resolve().parent.parent / "agents" / "agent_configs"
RULES = {
    "branch_cfo_advisor.json": ["เป็น AI", "ห้ามคำนวณหรือเดาเอง", "merge_branch", "ไม่ใช่คำแนะนำลงทุน"],
    "branch_cfo_collector.json": ["เป็น AI", "ห้ามข่มขู่", "ห้ามพูดถึงการดำเนินคดี", "record_promise", "ห้ามโทรซ้ำ"],
}
bad = 0
for fn, needles in RULES.items():
    cfg = json.loads((root / fn).read_text())
    prompt = cfg["conversation_config"]["agent"]["prompt"]["prompt"]
    for n in needles:
        if n not in prompt:
            print(f"FAIL {fn}: missing '{n}'"); bad += 1
    if cfg["conversation_config"]["agent"]["language"] != "th":
        print(f"FAIL {fn}: language != th"); bad += 1
print("agent lint:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
