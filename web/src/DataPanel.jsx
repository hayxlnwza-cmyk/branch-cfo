import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
const KIND = { bank: "สินเชื่อธนาคาร (ดอกเบี้ยต่อปี)", flat: "ผ่อนแบบ flat", informal: "กู้นอกระบบ (ดอกต่อเดือน)" };

const toForm = (f) => ({
  ...f,
  historyText: (f.history || []).join("\n"),
  var_pct: +(f.var_ratio * 100).toFixed(2),
  debts: (f.debts || []).map((d) => ({ ...d, apr_pct: d.apr != null ? +(d.apr * 100).toFixed(3) : "", flat_pct: d.flat_monthly != null ? +(d.flat_monthly * 100).toFixed(3) : "", rate_pct: d.rate_monthly != null ? +(d.rate_monthly * 100).toFixed(3) : "" })),
  receivables: (f.receivables || []).map((c) => ({ ...c, prob_pct: +(c.prob * 100).toFixed(0) })),
});
const fromForm = (f) => ({
  business_name: f.business_name, start_year: Number(f.start_year), first_month: Number(f.first_month),
  history: f.historyText.split(/[\s,;]+/).filter(Boolean).map((x) => Number(x.replace(/,/g, ""))),
  cash0: Number(f.cash0), fixed_monthly: Number(f.fixed_monthly), var_ratio: Number(f.var_pct) / 100, min_cash: Number(f.min_cash || 0),
  debts: f.debts.map((d) => ({ name: d.name, kind: d.kind, principal: Number(d.principal), n: d.n === "" ? undefined : Number(d.n),
    ...(d.kind === "bank" ? { apr: Number(d.apr_pct) / 100 } : d.kind === "flat" ? { flat_monthly: Number(d.flat_pct) / 100 } : { rate_monthly: Number(d.rate_pct) / 100 }) })),
  receivables: f.receivables.map((c) => ({ name: c.name, amount: Number(c.amount), month: Number(c.month), prob: Number(c.prob_pct) / 100 })),
});

export default function DataPanel({ synthetic, onApplied }) {
  const [f, setF] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  useEffect(() => { api.data().then((r) => setF(toForm(r.form))).catch((e) => setMsg({ bad: true, t: String(e.message || e) })); }, [synthetic]);
  if (!f) return null;
  const set = (k, v) => setF({ ...f, [k]: v });
  const setRow = (key, i, k, v) => setF({ ...f, [key]: f[key].map((r, j) => (j === i ? { ...r, [k]: v } : r)) });
  const addDebt = () => setF({ ...f, debts: [...f.debts, { name: "", kind: "bank", principal: "", n: 12, apr_pct: "", flat_pct: "", rate_pct: "" }] });
  const addRec = () => setF({ ...f, receivables: [...f.receivables, { name: "", amount: "", month: 3, prob_pct: 60 }] });
  const nHist = f.historyText.split(/[\s,;]+/).filter(Boolean).length;

  const apply = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.saveData(fromForm(f));
      setMsg({ t: `✓ ใช้ข้อมูลนี้แล้ว (โมเดลเรียนรู้จาก ${r.fit.n_obs} เดือน: โต ${(r.fit.g_monthly * 100).toFixed(2)}%/เดือน, ความผันผวน σ=${(r.fit.sigma * 100).toFixed(1)}%)${r.saved_on_server ? "" : " · บันทึกบนเซิร์ฟเวอร์ไม่ได้"}`, warns: r.warnings });
      onApplied();
    } catch (e) { setMsg({ bad: true, t: String(e.message || e) }); }
    setBusy(false);
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(fromForm(f), null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "branch-cfo-data.json"; a.click();
  };
  const upload = (file) => {
    const r = new FileReader();
    r.onload = () => { try { setF(toForm(JSON.parse(r.result))); setMsg({ t: "นำเข้าไฟล์แล้ว ตรวจตัวเลขแล้วกด “ใช้ข้อมูลนี้”" }); } catch { setMsg({ bad: true, t: "ไฟล์ไม่ใช่ JSON ที่ถูกต้อง" }); } };
    r.readAsText(file);
  };
  const demo = async () => { if (!window.confirm("กลับไปใช้ข้อมูลตัวอย่าง? (ข้อมูลที่กรอกบนเซิร์ฟเวอร์จะถูกลบ)")) return; await api.demoData(); setMsg({ t: "กลับเป็นข้อมูลตัวอย่างแล้ว" }); onApplied(); };

  return (
    <details className="card wide datapanel" open={!synthetic ? false : undefined}>
      <summary><b>⚙ ใส่ข้อมูลจริงของธุรกิจคุณ</b> <span className="muted">{synthetic ? "(ตอนนี้ใช้ข้อมูลตัวอย่าง กดเพื่อเปิดฟอร์ม)" : "(ใช้ข้อมูลจริงอยู่ กดเพื่อแก้ไข)"}</span></summary>
      <p className="note">กรอกตัวเลขจากบัญชี/สลิป/สมุดรายรับ แล้วกด “ใช้ข้อมูลนี้” ระบบจะเรียนรู้แนวโน้มและฤดูกาลจากยอดขายย้อนหลัง แล้วคำนวณทุกหน้าใหม่ ข้อมูลเก็บบนเซิร์ฟเวอร์ชั่วคราว (หายเมื่อ Render รีสตาร์ท) ควร “ดาวน์โหลดไฟล์ข้อมูล” เก็บไว้ ห้ามใส่ข้อมูลส่วนบุคคลของลูกหนี้เกินความจำเป็น (PDPA)</p>

      <h3>1) ข้อมูลทั่วไป</h3>
      <div className="fgrid">
        <label>ชื่อธุรกิจ<input value={f.business_name} onChange={(e) => set("business_name", e.target.value)} /></label>
        <label>เงินสดคงเหลือตอนนี้ (บาท)<input type="number" value={f.cash0} onChange={(e) => set("cash0", e.target.value)} /></label>
        <label>ค่าใช้จ่ายคงที่ต่อเดือน (เช่น ค่าเช่า เงินเดือน ค่าไฟ ไม่รวมค่างวดหนี้)<input type="number" value={f.fixed_monthly} onChange={(e) => set("fixed_monthly", e.target.value)} /></label>
        <label>ต้นทุนผันแปร (% ของยอดขาย เช่น วัตถุดิบ)<input type="number" step="0.1" value={f.var_pct} onChange={(e) => set("var_pct", e.target.value)} /></label>
        <label>เงินสดขั้นต่ำที่ยอมให้เหลือ (บาท) ต่ำกว่านี้นับว่า “ไม่รอด”<input type="number" value={f.min_cash} onChange={(e) => set("min_cash", e.target.value)} /></label>
      </div>

      <h3>2) ยอดขายรายเดือนย้อนหลัง <span className="muted">(เก่า→ใหม่ อย่างน้อย 12 เดือน ยิ่งมากยิ่งแม่น · ตอนนี้มี {nHist} เดือน)</span></h3>
      <div className="fgrid">
        <label>เดือนแรกของข้อมูล<select value={f.first_month} onChange={(e) => set("first_month", e.target.value)}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></label>
        <label>ปี (ค.ศ.)<input type="number" value={f.start_year} onChange={(e) => set("start_year", e.target.value)} /></label>
      </div>
      <textarea rows={6} value={f.historyText} onChange={(e) => set("historyText", e.target.value)} placeholder={"วางตัวเลขยอดขายแต่ละเดือน บรรทัดละเดือน (คัดลอกคอลัมน์จาก Excel มาวางได้)\n520000\n610000\n..."} />

      <h3>3) หนี้ที่มี</h3>
      {f.debts.length > 0 && (
        <table className="ed">
          <thead><tr><th>ชื่อ</th><th>ประเภท</th><th>เงินต้น</th><th>ดอกเบี้ย (%)</th><th>งวด/เดือนที่เหลือ</th><th /></tr></thead>
          <tbody>
            {f.debts.map((d, i) => (
              <tr key={i}>
                <td><input value={d.name} onChange={(e) => setRow("debts", i, "name", e.target.value)} /></td>
                <td><select value={d.kind} onChange={(e) => setRow("debts", i, "kind", e.target.value)}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></td>
                <td><input type="number" value={d.principal} onChange={(e) => setRow("debts", i, "principal", e.target.value)} /></td>
                <td>
                  {d.kind === "bank" && <input type="number" step="0.01" title="ต่อปี" placeholder="ต่อปี" value={d.apr_pct} onChange={(e) => setRow("debts", i, "apr_pct", e.target.value)} />}
                  {d.kind === "flat" && <input type="number" step="0.01" title="flat ต่อเดือน" placeholder="flat ต่อเดือน" value={d.flat_pct} onChange={(e) => setRow("debts", i, "flat_pct", e.target.value)} />}
                  {d.kind === "informal" && <input type="number" step="0.01" title="ต่อเดือน" placeholder="ต่อเดือน" value={d.rate_pct} onChange={(e) => setRow("debts", i, "rate_pct", e.target.value)} />}
                </td>
                <td><input type="number" value={d.n} onChange={(e) => setRow("debts", i, "n", e.target.value)} /></td>
                <td><button className="ghost" onClick={() => setF({ ...f, debts: f.debts.filter((_, j) => j !== i) })}>ลบ</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button className="ghost" onClick={addDebt}>+ เพิ่มหนี้</button>
      <p className="note">ธนาคาร: ใส่ดอกเบี้ย % ต่อปี · flat: ใส่ % ต่อเดือนของเงินต้น (เช่น 0.9) · นอกระบบ: ใส่ % ต่อเดือน (เช่น 10) ระบบจะแปลงเป็นดอกเบี้ยที่แท้จริง (EIR) ให้</p>

      <h3>4) ลูกหนี้ที่ค้างชำระ</h3>
      {f.receivables.length > 0 && (
        <table className="ed">
          <thead><tr><th>ชื่อลูกหนี้</th><th>ยอดค้าง (บาท)</th><th>คาดว่าได้เดือนที่ (1-12)</th><th>โอกาสได้ (%)</th><th /></tr></thead>
          <tbody>
            {f.receivables.map((c, i) => (
              <tr key={i}>
                <td><input value={c.name} onChange={(e) => setRow("receivables", i, "name", e.target.value)} /></td>
                <td><input type="number" value={c.amount} onChange={(e) => setRow("receivables", i, "amount", e.target.value)} /></td>
                <td><input type="number" min="1" max="12" value={c.month} onChange={(e) => setRow("receivables", i, "month", e.target.value)} /></td>
                <td><input type="number" min="0" max="100" value={c.prob_pct} onChange={(e) => setRow("receivables", i, "prob_pct", e.target.value)} /></td>
                <td><button className="ghost" onClick={() => setF({ ...f, receivables: f.receivables.filter((_, j) => j !== i) })}>ลบ</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button className="ghost" onClick={addRec}>+ เพิ่มลูกหนี้</button>

      <div className="frow">
        <button onClick={apply} disabled={busy}>{busy ? "กำลังคำนวณ…" : "ใช้ข้อมูลนี้"}</button>
        <button className="ghost" onClick={download}>ดาวน์โหลดไฟล์ข้อมูล</button>
        <button className="ghost" onClick={() => fileRef.current?.click()}>นำเข้าไฟล์</button>
        <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files[0] && upload(e.target.files[0])} />
        {!synthetic && <button className="ghost" onClick={demo}>กลับไปข้อมูลตัวอย่าง</button>}
      </div>
      {msg && <div className={msg.bad ? "err" : "commit"}>{msg.t}{msg.warns?.map((w, i) => <div key={i} className="note">⚠ {w}</div>)}</div>}
    </details>
  );
}
