import React from "react";

const baht = (v) => Math.round(v).toLocaleString("th-TH");
const pct = (v, d = 0) => `${(v * 100).toFixed(d)}%`;

export function EventBody({ e }) {
  const d = e.data || {};
  switch (e.tool) {
    case "get_forecast":
      return (<p>โอกาสรอด <b>{pct(d.p_survive, 1)}</b> · เงินสดต่ำสุด p5 {baht(d.min_cash_p5)} ฿ · p50 {baht(d.min_cash_p50)} ฿ · ต่ำสุดบ่อยสุดเดือนที่ {d.trough_month}</p>);
    case "create_branch":
      return (<>
        <p>โอกาสรอด {pct(d.p_base, 1)} → <b>{pct(d.p_branch, 1)}</b> <span className={d.delta_p < 0 ? "neg" : "pos"}>({d.delta_p > 0 ? "+" : ""}{(d.delta_p * 100).toFixed(1)} จุด)</span> · เงินสดต่ำสุด p5 {baht(d.min_cash_p5_branch)} ฿</p>
        {d.assumptions?.map((a, i) => <p className="note" key={i}>สมมติ: {a}</p>)}
      </>);
    case "merge_branch": {
      const g = d.git || {};
      return (<>
        <p>โอกาสรอด {pct(d.p_base, 1)} → <b>{pct(d.p_branch, 1)}</b> · บันทึก <code>{d.file}</code></p>
        <p className="note">
          {g.error ? <>✗ ขึ้น GitHub ไม่สำเร็จ: {g.error}</> : g.via === "github_api" ? <>ขึ้น GitHub แล้ว: <a href={g.commit_url} target="_blank" rel="noreferrer">commit {g.commit}</a></> : "บันทึกในเซิร์ฟเวอร์ (ยังไม่ได้ตั้ง GITHUB_TOKEN)"}
        </p>
      </>);
    }
    case "get_debt_report":
      return (
        <table>
          <thead><tr><th>หนี้</th><th>APR</th><th>EIR</th><th>ค่างวด</th><th>รีไฟแนนซ์</th></tr></thead>
          <tbody>
            {d.items?.map((i) => (
              <tr key={i.name} className={i.flags?.length ? "bad" : ""}>
                <td>{i.name}{i.flags?.includes("EXCEEDS_15_PCT_NON_FI_CAP") && <em>เกินเพดาน 15%/ปี</em>}</td>
                <td>{i.apr_pct}%</td><td>{i.eir_pct}%</td><td>{baht(i.monthly_payment)}</td>
                <td>{i.refinance_monthly_saving > 0 ? `ลด ${baht(i.refinance_monthly_saving)}/ด.` : `เพิ่ม ${baht(-i.refinance_monthly_saving)}/ด.`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case "list_debtors":
      return (
        <table>
          <thead><tr><th>ลูกหนี้</th><th>ยอดค้าง</th><th>คาดรับ</th><th>โอกาสได้</th></tr></thead>
          <tbody>{d.debtors?.map((c) => (<tr key={c.id}><td>{c.name}</td><td>{baht(c.amount)}</td><td>เดือนที่ {c.expected_month}</td><td>{pct(c.prob)}</td></tr>))}</tbody>
        </table>
      );
    case "record_promise":
      return d.recorded ? (
        <p>{d.customer}: สัญญาจ่ายเดือนที่ <b>{d.new?.tau}</b> (ความมั่นใจ {pct(d.new?.q ?? 0)}) → โอกาสรอด {pct(d.p_survive_before, 1)} → <b>{pct(d.p_survive_after, 1)}</b></p>
      ) : (<p className="neg">ไม่บันทึก: {d.reason_th}</p>);
    case "stop_contact":
      return (<p>หยุดติดต่อถาวรแล้ว · บันทึกหลักฐาน <code>{d.file}</code></p>);
    default:
      return <p className="note">{JSON.stringify(d).slice(0, 200)}</p>;
  }
}

const ICON = { get_forecast: "📈", create_branch: "🌿", merge_branch: "✅", get_debt_report: "🩺", list_debtors: "📒", record_promise: "📞", stop_contact: "⛔" };

export function ActivityPanel({ events, freshId }) {
  if (!events?.length) return null;
  const list = [...events].reverse().slice(0, 6);
  return (
    <section className="card wide activity">
      <h2>กิจกรรมสดจากเอเจนต์เสียง</h2>
      {list.map((e) => (
        <div className={`evt ${e.id === freshId ? "fresh" : ""}`} key={e.id}>
          <div className="evh"><span>{ICON[e.tool] || "•"} {e.title}</span><span className="muted">{e.at}</span></div>
          <EventBody e={e} />
        </div>
      ))}
    </section>
  );
}

export function Toast({ e, onClose }) {
  if (!e) return null;
  return (
    <div className="toast" onClick={onClose}>
      <div className="evh"><b>{ICON[e.tool] || "•"} {e.title}</b><span className="muted">แตะเพื่อปิด</span></div>
      <EventBody e={e} />
    </div>
  );
}
