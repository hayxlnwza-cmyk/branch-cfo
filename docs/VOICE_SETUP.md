# ตั้งเสียง ElevenLabs (ทำตอน 20:00 ใช้เวลา ~40 นาที)
> ชื่อเมนูใน dashboard ของ ElevenLabs เปลี่ยนบ่อย ถ้าชื่อไม่ตรงให้หาเมนูที่ใกล้เคียง · ยังไม่เคยทดสอบกับบัญชีจริง ต้องเทสต์ด้วยหู

ก่อนเริ่ม: เปิด `https://branch-cfo.onrender.com` ค้างไว้ (Render ฟรีหลับ → webhook ของเอเจนต์จะ timeout ถ้าเซิร์ฟเวอร์หลับ)

## A. เอเจนต์ที่ปรึกษา (Advisor)
1. elevenlabs.io → **Agents** → สร้างเอเจนต์ใหม่ (blank) ชื่อ `Branch CFO Advisor`
2. **Language = Thai**
3. **System prompt**: ก๊อปจากไฟล์ (รันใน Terminal แล้ว Cmd+V):
   `python3 -c "import json;print(json.load(open('agents/agent_configs/branch_cfo_advisor.json'))['conversation_config']['agent']['prompt']['prompt'])" | pbcopy`
4. **First message**: `python3 -c "import json;print(json.load(open('agents/agent_configs/branch_cfo_advisor.json'))['conversation_config']['agent']['first_message'])" | pbcopy`
5. **Voice**: เลือกเสียงที่รองรับภาษาไทย (กรอง Thai ใน Voice library) แล้ว**ฟังเทสต์ประโยคตัวเลข** เช่น "โอกาสรอดลดจาก 77 เปอร์เซ็นต์เหลือ 52 เปอร์เซ็นต์" โมเดล TTS ต้องรองรับไทยจริง ให้ลองรุ่นที่ dashboard ระบุว่ารองรับไทย (เช่น v3 / multilingual) ถ้ารุ่น flash ออกเสียงเพี้ยนให้เปลี่ยนรุ่น
6. **Tools → Add tool → Webhook (server tool)** เพิ่ม 4 อัน (ชื่อต้องตรง):

| ชื่อ | Method | URL | Body (JSON) |
|---|---|---|---|
| get_forecast | POST | `https://branch-cfo.onrender.com/api/tools/get_forecast` | ไม่มี |
| create_branch | POST | `.../api/tools/create_branch` | `request_text` (string, required) |
| merge_branch | POST | `.../api/tools/merge_branch` | `branch_id` (string, required), `reason` (string) |
| get_debt_report | GET | `.../api/tools/get_debt_report` | ไม่มี |

   คำอธิบายของแต่ละ tool ก๊อปจาก `agents/_templates/tools.json` (field `description`)
7. กด **Test AI agent** พูดว่า "ตอนนี้โอกาสรอดเท่าไหร่" → ต้องตอบ ~77% แล้วลอง "ถ้าเปิดสาขาสอง" → ~52%
8. คัดลอก **Agent ID** (ขึ้นต้น `agent_`)

## B. เอเจนต์โทรตามเงิน (Collector)
1. สร้างเอเจนต์ใหม่ `Branch CFO Collector` ภาษาไทย เลือกเสียงเดียวกันหรือเสียงอื่น
2. System prompt / First message จาก `agents/agent_configs/branch_cfo_collector.json` (วิธีเดียวกับข้อ A.3–A.4)
3. **Dynamic variables** ประกาศ 4 ตัว: `business_name`, `customer_name`, `amount`, `customer_id` (เว็บส่งค่าให้เองตอนกดโทร)
4. เพิ่ม webhook tool `record_promise` (POST `.../api/tools/record_promise`) body: `customer_id` (string, required), `promised_month` (integer), `confidence` (number), `note` (string), `spoke_to_debtor` (boolean)
5. ทดสอบใน dashboard: ใส่ค่า dynamic variables เช่น `customer_id=c1`, พูดเป็นลูกหนี้ "ขอจ่ายเดือนหน้าครับ" → หน้าเว็บ (เปิดค้าง) ต้องเห็นโอกาสรอดขยับขึ้นเอง
6. คัดลอก Agent ID ตัวที่สอง

## C. เอา ID ไปใส่เว็บ (ไม่ต้อง build ใหม่)
1. Render → บริการ `branch-cfo` → **Environment** → เพิ่ม
   - `ELEVENLABS_ADVISOR_AGENT_ID` = ID ข้อ A.8
   - `ELEVENLABS_COLLECTOR_AGENT_ID` = ID ข้อ B.6
2. Save → Render deploy ใหม่เอง → รีเฟรชเว็บ จะเห็นปุ่ม 🎙 (ที่ปรึกษา 1 ปุ่ม + โทรต่อลูกหนี้)
3. อนุญาตไมโครโฟนใน Chrome

## D. ให้ merge ขึ้น GitHub สด (ทางเลือก แต่ฉากสุดท้ายของเดโมต้องใช้)
1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate: เลือกรีโป `branch-cfo` → Permissions → **Contents: Read and write** → สร้างแล้วก๊อป
2. Render → Environment เพิ่ม `GITHUB_TOKEN` = token นั้น, `GITHUB_REPO` = `hayxlnwza-cmyk/branch-cfo`
3. กด Merge ในเว็บ → ไฟล์ `ledger/...json` ต้องโผล่ใน GitHub ภายในไม่กี่วินาที (ผลตอบกลับมีลิงก์ commit)
4. หลังเดโม ในเครื่อง `git pull` เพื่อดึง ledger ที่เว็บสร้าง

## ถ้าเสียงไม่ผ่าน
- ใช้ช่องพิมพ์ + ปุ่ม "จำลองผลสาย" ในเว็บ (ตัวเลขเดียวกันทุกอย่าง) และเปิดวิดีโอสำรองที่อัดไว้
- เช็ค Render → **Logs**: ต้องเห็น `POST /api/tools/...` เมื่อเอเจนต์เรียก tool ถ้าไม่เห็น = webhook URL ผิด หรือเซิร์ฟเวอร์หลับ

## E. Guardrail ในโค้ด (เพิ่มใหม่ตามคำแนะนำของครู)
- เพิ่ม webhook tool `stop_contact` (POST `.../api/tools/stop_contact`) body: `customer_id` (string, required), `reason` (string) แล้วใส่ใน tool ของ Collector ด้วย: ลูกหนี้ขอหยุด = ระบบห้ามโทรถาวรและเขียนหลักฐานลง ledger
- เว็บต้องเรียก `POST /api/guard/start_call` ก่อนเปิดสาย ถ้า `allowed:false` ห้ามเริ่มสาย แล้วแสดง `reason_th`
- `GET /api/guardrails` ให้กฎ สถานะลูกหนี้แต่ละราย รายชื่อที่ขอหยุด และ audit log สำหรับแผง "ขอบเขตความปลอดภัย"
- เดโมนอกเวลา 08:00-20:00: Render ตั้ง `GUARD_DEMO=1` ไว้แล้ว (ใช้ได้เฉพาะข้อมูลสังเคราะห์) ระบบจะอนุญาตแต่ติดป้าย "โหมดเดโม ปกติจะถูกบล็อก" ให้เห็นชัด ถ้าอยากโชว์การบล็อกจริงให้ส่ง `at` เช่น `2026-10-15T22:00:00+07:00`
- ช่วงเวลาและโควตาเป็นค่าเริ่มต้นจากความเข้าใจของทีม ยังไม่ผ่านผู้รู้ด้านกฎหมาย

## F. สรุปรายสัปดาห์ผ่าน LINE (ทางเลือก)
- ดูข้อความตัวอย่างได้เลยโดยไม่ต้องมีบัญชี: `GET /api/line/preview`
- ส่งจริง: สร้าง LINE Official Account + Messaging API ตั้ง `LINE_CHANNEL_TOKEN` และ `LINE_USER_ID` บน Render แล้วเรียก `POST /api/line/weekly`
