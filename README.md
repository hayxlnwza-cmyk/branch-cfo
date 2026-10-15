# Branch CFO — AI CFO ให้ SME ที่ทำนายอนาคต ลงมือแทน และพิสูจน์ได้
U-Hackathon 2026 · แทร็ก AI · ข้อมูลทั้งหมดในรีโปเป็น **ข้อมูลตัวอย่างสังเคราะห์** (ไม่ใช่ธุรกิจจริง) · เป็นเครื่องมือวางแผน ไม่ใช่คำแนะนำลงทุน

ตัวเลขทุกตัวมาจาก `engine/` (numpy, seed ซ้ำได้) ไม่ใช่ LLM — LLM/เสียงแปลคำพูดเป็นพารามิเตอร์และอธิบายผลเท่านั้น

## รัน
```bash
pip install -r requirements.txt
python -m pytest -q engine/tests api          # 20 เทสต์
python data/make_seed.py                      # (ทางเลือก) สร้าง data/seed.json ใหม่ — deterministic
uvicorn api.main:app --port 8000              # API (+ เสิร์ฟ web/dist ถ้ามี)

cd web && npm install && npm run dev          # UI ที่ :5173 (proxy /api → :8000)
# หรือ npm run build แล้วเปิด http://localhost:8000
```
ตัวแปรสภาพแวดล้อม (ทั้งหมดเป็น optional — ไม่มีก็รันเดโมได้):
| ตัวแปร | ใช้ทำอะไร |
|---|---|
| `VITE_ELEVENLABS_ADVISOR_AGENT_ID`, `VITE_ELEVENLABS_COLLECTOR_AGENT_ID` (web/.env) | เปิดปุ่มคุยเสียง/โทรตามเงิน ถ้าไม่ตั้ง UI ใช้ช่องพิมพ์ + ปุ่ม "จำลองผลสาย" แทน |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | ให้ LLM แปลประโยค "ถ้า..." ที่ rule ไม่รู้จัก (ผ่าน whitelist + ขอบเขตค่า) |
| `GITHUB_TOKEN`, `GITHUB_REPO` | หลัง merge จะ `git push` ledger ขึ้น GitHub ทันที (ไม่ตั้ง = commit ในเครื่องอย่างเดียว) |
| `ELEVENLABS_API_KEY`, `API_BASE` | deploy เอเจนต์ด้วย CLI (`.github/workflows/deploy-agent.yml`) |

## ต่อ ElevenLabs
1. เปิด tunnel ให้ API เข้าถึงได้จากภายนอก (`cloudflared tunnel --url http://localhost:8000` หรือ ngrok)
2. `API_BASE=https://<tunnel> python scripts/render_agents.py` → สร้าง `agents/tool_configs/*.json`
3. ใส่ `voice_id` ที่พูดไทยได้ใน `agents/agent_configs/*.json` (ตอนนี้เป็น placeholder)
4. `cd agents && elevenlabs agents push --dry-run && elevenlabs agents push` แล้วนำ agent id ไปใส่ `web/.env`
> ⚠️ รูปแบบ config ของ `first_message` / `tool_ids` / webhook tool ผมเขียนตามความรู้ทั่วไป — หน้าเอกสาร CLI ที่ดึงมาไม่ได้ระบุส่วนนี้ ให้ใช้ `push --dry-run` ตรวจ และปรับตามที่ CLI รายงาน **ยังไม่เคยทดสอบกับบัญชีจริง**

## เดโม 4 นาที กับตัวเลขที่รันจริง (seed 42, 5,000 เส้นทาง, ขอบฟ้า 12 เดือน)
| ฉาก | สิ่งที่พูด/ทำ | ผลที่ engine ให้ |
|---|---|---|
| 1 | ปัญหา: SME เจ๊งเพราะเงินสดขาด ไม่ใช่เพราะขาดทุน | ฐาน **77.0%** รอด, เงินสดต่ำสุด p5 = −151k฿, ต่ำสุดบ่อยสุดเดือน 10 |
| 2 | "ถ้าเปิดสาขาสอง" | **52.0%** (ΔP = −24.9 จุด, 95% CI [−26.1, −23.7]) |
| 3 | Debt Doctor | นอกระบบ 10%/เดือน = APR 120%, EIR 213.8% เกินเพดาน 15%/ปี; ผ่อน flat 0.9%/เดือน = APR 19.4%; รีไฟแนนซ์นอกระบบ 100k เป็น 20%/24 ด. ลดค่างวด 4,910฿/เดือน |
| 4 | โทรตามเงิน c4→เดือน 2, c1→เดือน 1, c2→เดือน 2 (conf 0.85) | โอกาสรอดฐาน 77.0% → 86.0% → 90.9% → **93.4%**; กิ่งสาขาสองกลับมา **80.4%** |
| 5 | กด Merge | `ledger/<ts>-merge-<ชื่อ>.json` + git commit (+ push ถ้าตั้ง token); ส่งออกประวัติให้ผู้ให้สินเชื่อ: FCF p5 ≈ 13.8k฿/เดือน, วงเงินใหม่หลังหักหนี้เดิม = 0 (ตามจริงสำหรับธุรกิจที่ตึงตัว — จุดขายของ Debt Doctor) |

Backtest (บนจอ): coverage ช่วง 80% จริง **75.7%** (400 ชุดจำลอง, 2,400 จุด; เป้า 80%), rolling บนประวัติ 24 ด. 92% (n=24 น้อย), MAPE มัธยฐาน 6.1% เทียบ seasonal-naive 7.9% — **ข้อมูลสังเคราะห์จากโมเดลตระกูลเดียวกัน** วัดได้แค่ estimator/calibration ไม่ใช่ความแม่นยำโลกจริง

## โครงรีโป
`engine/` สูตรทั้งหมด + `tests/` · `api/` FastAPI + tool endpoints ของเอเจนต์เสียง · `web/` React · `agents/` ElevenLabs agents-as-code · `data/` seed สังเคราะห์ · `ledger/` หลักฐานการตัดสินใจ · `.github/workflows/` backtest (gate), agent-tests (lint guardrail), deploy-agent · `docs/FORMULAS.md` สูตรและสมมติฐาน

## ยังไม่ได้ทำ / ข้อจำกัดที่ต้องรู้ก่อนขึ้นเวที
- เสียง (ElevenLabs) **ยังไม่ได้ทดสอบ** — ไม่มี API key/เอเจนต์จริงในเซสชันสร้าง ต้องทดสอบเสียงไทย ความหน่วง และ tool-calling ก่อนเป็นอย่างแรก
- OCR สลิป/สมุดบัญชียังไม่ทำ (เดโมใช้ข้อมูลที่ป้อนไว้ตามสเปก)
- `agent-tests.yml` เป็น lint guardrail ของพรอมต์ (deterministic) ยังไม่ได้จำลองบทสนทนากับเอเจนต์จริง
- เพดานดอกเบี้ย 15% / 36% เป็นค่าอ้างอิงจากสื่อ ต้องให้ผู้รู้ตรวจก่อนพูดบนเวที และตรวจกฎหมายทวงถามหนี้/PDPA
- โมเดลรายรับเป็น log-normal + ฤดูกาล 2 ฮาร์โมนิก + พารามิเตอร์ไม่แน่นอนแบบ OLS (ไม่รวม covariance ระหว่าง level/slope) ไม่ใช่ธุรกิจทุกประเภท
- สถานะเซิร์ฟเวอร์อยู่ในหน่วยความจำ (ผู้ใช้ 1 session) พอสำหรับเดโม
