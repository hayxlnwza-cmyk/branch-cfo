import React, { useCallback, useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversationControls, useConversationStatus } from "@elevenlabs/react";
import { api } from "./api.js";
import FanChart from "./FanChart.jsx";

const baht = (v) => Math.round(v).toLocaleString("th-TH");
const pct = (v, d = 0) => `${(v * 100).toFixed(d)}%`;
const ADVISOR = import.meta.env.VITE_ELEVENLABS_ADVISOR_AGENT_ID;
const COLLECTOR = import.meta.env.VITE_ELEVENLABS_COLLECTOR_AGENT_ID;

export default function App() {
  return (
    <ConversationProvider connectionType="webrtc">
      <Dashboard />
    </ConversationProvider>
  );
}

function Dashboard() {
  const [st, setSt] = useState(null);
  const [base, setBase] = useState(null);
  const [debt, setDebt] = useState(null);
  const [bt, setBt] = useState(null);
  const [lender, setLender] = useState(null);
  const [cmp, setCmp] = useState(null);
  const [branchFc, setBranchFc] = useState(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [cfg, setCfg] = useState({});
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(null);
  const ver = useRef(-1);
  const prevP = useRef(null);

  const refresh = useCallback(async () => {
    const [s, f] = await Promise.all([api.state(), api.forecast()]);
    ver.current = s.version;
    setSt(s);
    if (prevP.current != null && Math.abs(prevP.current - f.p_survive) > 0.001) {
      setFlash(f.p_survive > prevP.current ? "up" : "down");
      setTimeout(() => setFlash(null), 1800);
    }
    prevP.current = f.p_survive;
    setBase(f);
    setDebt(await api.debt());
    if (cmp?.branch_id && s.branches[cmp.branch_id]) {
      const c = await api.compare(cmp.branch_id);
      setCmp(c);
      setBranchFc(c.branch);
    } else if (cmp) { setCmp(null); setBranchFc(null); }
  }, [cmp?.branch_id]);

  useEffect(() => { api.config().then(setCfg).catch(() => {}); }, []);
  useEffect(() => { refresh().catch((e) => setErr(String(e))); api.backtest().then(setBt).catch(() => {}); }, []);
  useEffect(() => {  // live: voice agent tools mutate server state -> version bumps -> refetch
    const id = setInterval(async () => {
      try { const v = await api.version(); if (v.version !== ver.current) refresh(); } catch {}
    }, 1200);
    return () => clearInterval(id);
  }, [refresh]);

  const ask = async (q) => {
    if (!q.trim()) return;
    setBusy(true); setErr("");
    try { const c = await api.parse(q); setCmp(c); setBranchFc(c.branch); setText(""); await refresh(); }
    catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };
  const merge = async () => {
    const reason = prompt("เหตุผลที่ตัดสินใจ merge (จะถูกบันทึกลง ledger):", cmp.patch.reason || "");
    if (reason == null) return;
    setBusy(true);
    try { const r = await api.merge(cmp.branch_id, reason); setCmp(null); setBranchFc(null); setLender(null); await refresh();
      const g = r.git || {};
      setFlash("commit:" + [r.file, g.error ? "err" : g.via === "github_api" ? "github" : "local", g.error || g.commit || "", g.commit_url || ""].join("|"));
      setTimeout(() => setFlash(null), 30000); }
    catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };

  if (!st || !base) return <div className="boot">{err || "กำลังโหลด…"}</div>;
  const a = st.assumptions;

  return (
    <div className="app">
      <header>
        <div>
          <h1>Branch <span>CFO</span></h1>
          <p className="sub">AI CFO ที่ทำนายอนาคต ลงมือแทน และพิสูจน์ได้</p>
        </div>
        <div className="badges">
          <span className="badge warn">ข้อมูลตัวอย่างสังเคราะห์</span>
          <span className="badge">engine v{st.engine}</span>
          <span className="badge">{a.n_paths.toLocaleString()} เส้นทาง · seed {a.seed}</span>
          <button className="ghost" onClick={async () => { await api.reset(); setCmp(null); setBranchFc(null); setLender(null); refresh(); }}>รีเซ็ตเดโม</button>
        </div>
      </header>

      <section className="hero">
        <div className={`survive ${flash === "up" ? "up" : flash === "down" ? "down" : ""}`}>
          <div className="lbl">โอกาสรอด 12 เดือน (ฐาน)</div>
          <div className="big">{pct(base.p_survive)}</div>
          {cmp && (
            <div className="delta">
              → สาขา “{cmp.patch.name}” <b>{pct(cmp.branch.p_survive)}</b>
              <span className={cmp.delta_p < 0 ? "neg" : "pos"}> ({cmp.delta_p > 0 ? "+" : ""}{(cmp.delta_p * 100).toFixed(1)} จุด ± {(1.96 * cmp.delta_p_se * 100).toFixed(1)})</span>
            </div>
          )}
          <div className="meta">
            เงินสดต่ำสุด p5/p50/p95: {baht(base.min_cash_pct.p5)} / {baht(base.min_cash_pct.p50)} / {baht(base.min_cash_pct.p95)} ฿ · ต่ำสุดบ่อยสุดเดือนที่ {base.trough_month_mode}
          </div>
        </div>
        <div className="chartcard">
          <FanChart base={base} branch={branchFc} cash0={a.cash0} />
          <div className="legend">
            <i className="k1" /> ช่วง 5–95% <i className="k2" /> 25–75% <i className="k3" /> มัธยฐาน
            {branchFc && (<><i className="k4" /> กิ่ง “{cmp.patch.name}”</>)}
          </div>
        </div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>แตกกิ่ง “ถ้า…”</h2>
          <form onSubmit={(e) => { e.preventDefault(); ask(text); }} className="askrow">
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="เช่น ถ้าเปิดสาขาสอง / ถ้าขึ้นราคา 8% / กู้ 200000" />
            <button disabled={busy}>รัน</button>
          </form>
          <div className="chips">
            {["ถ้าเปิดสาขาสอง", "ถ้าขึ้นราคา 8%", "ถ้ากู้ 200000"].map((q) => (<button key={q} className="chip" onClick={() => ask(q)}>{q}</button>))}
          </div>
          <Voice agentId={cfg.advisor_agent_id || ADVISOR} label="คุยกับที่ปรึกษา (เสียง)" />
          {err && <div className="err">{err}</div>}
          {cmp && (
            <div className="diff">
              <h3>diff ของอนาคต</h3>
              <table>
                <thead><tr><th></th><th>ฐาน</th><th>กิ่ง</th></tr></thead>
                <tbody>
                  <tr><td>โอกาสรอด</td><td>{pct(cmp.base.p_survive, 1)}</td><td>{pct(cmp.branch.p_survive, 1)}</td></tr>
                  <tr><td>เงินสดต่ำสุด p5</td><td>{baht(cmp.base.min_cash_pct.p5)}</td><td>{baht(cmp.branch.min_cash_pct.p5)}</td></tr>
                  <tr><td>เงินสดต่ำสุด p50</td><td>{baht(cmp.base.min_cash_pct.p50)}</td><td>{baht(cmp.branch.min_cash_pct.p50)}</td></tr>
                  <tr><td>เดือนต่ำสุด</td><td>{cmp.base.trough_month_mode}</td><td>{cmp.branch.trough_month_mode}</td></tr>
                </tbody>
              </table>
              <p className="note">เลขสุ่มชุดเดียวกันทั้งฐานและกิ่ง (common random numbers) · 95% CI ของ ΔP = [{(cmp.delta_p_ci95[0] * 100).toFixed(1)}, {(cmp.delta_p_ci95[1] * 100).toFixed(1)}] จุด</p>
              {cmp.patch.assumptions?.map((s, i) => <p className="note" key={i}>สมมติ: {s}</p>)}
              <button className="primary" onClick={merge} disabled={busy}>Merge → commit ลง GitHub</button>
            </div>
          )}
          {flash?.startsWith?.("commit:") && (() => {
            const [file, kind, info, url] = flash.slice(7).split("|");
            return (
              <div className="commit">
                ✓ บันทึกหลักฐานแล้ว <code>{file}</code>
                <div>
                  {kind === "github" && <>ขึ้น GitHub แล้ว: <a href={url} target="_blank" rel="noreferrer">commit {info}</a></>}
                  {kind === "local" && "บันทึกในเซิร์ฟเวอร์เท่านั้น ยังไม่ขึ้น GitHub (ยังไม่ได้ตั้ง GITHUB_TOKEN / GITHUB_REPO)"}
                  {kind === "err" && <>✗ ขึ้น GitHub ไม่สำเร็จ: <code>{info}</code></>}
                </div>
              </div>
            );
          })()}
        </div>

        <div className="card">
          <h2>Debt Doctor</h2>
          <table className="debt">
            <thead><tr><th>หนี้</th><th>APR</th><th>EIR</th><th>ค่างวด</th><th>รีไฟแนนซ์ (20%/24ด.)</th></tr></thead>
            <tbody>
              {debt?.items.map((d) => (
                <tr key={d.id} className={d.flags.length ? "bad" : ""}>
                  <td>{d.name}{d.flags.includes("EXCEEDS_15_PCT_NON_FI_CAP") && <em> เกินเพดาน 15%/ปี (เจ้าหนี้นอกสถาบัน)</em>}</td>
                  <td>{pct(d.apr_nominal, 1)}</td><td>{pct(d.eir, 1)}</td><td>{baht(d.pmt)}</td>
                  <td>{d.refinance.monthly_cash_change > 0 ? `ลด ${baht(d.refinance.monthly_cash_change)}/ด.` : `เพิ่ม ${baht(-d.refinance.monthly_cash_change)}/ด.`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">APR จริงแก้จาก P = PMT·(1−(1+i)^−n)/i · {debt?.note}</p>
        </div>

        <Collections st={st} base={base} refresh={refresh} collectorId={cfg.collector_agent_id || COLLECTOR} />

        <div className="card">
          <h2>Backtest: แม่นแค่ไหน</h2>
          {bt ? (
            <>
              <div className="kpis">
                <div><b>{pct(bt.calibration.coverage_80, 1)}</b><span>coverage ช่วง 80% (เป้า 80%) · {bt.calibration.n_points} จุด / {bt.calibration.n_series} ชุดจำลอง</span></div>
                <div><b>{pct(bt.rolling.coverage_80, 0)}</b><span>rolling บนประวัติ 24 ด. · n={bt.rolling.n_points}</span></div>
                <div><b>{pct(bt.rolling.mape_median, 1)}</b><span>MAPE มัธยฐาน (seasonal-naive {pct(bt.rolling.mape_seasonal_naive, 1)})</span></div>
              </div>
              <p className="note">{bt.rolling.note}</p>
            </>
          ) : <p className="note">กำลังคำนวณ…</p>}
        </div>

        <div className="card wide">
          <h2>หลักฐาน (ledger) และข้อมูลสำหรับผู้ให้สินเชื่อ</h2>
          <div className="ledgerrow">
            <ul className="ledger">
              {st.ledger.length === 0 && <li className="muted">ยังไม่มีการ merge</li>}
              {st.ledger.slice(-6).map((e) => (<li key={e.file}><code>{e.file}</code> <span>{e.sha256.slice(0, 10)}</span></li>))}
            </ul>
            <div>
              <button onClick={async () => setLender(await api.lender())}>ส่งออกประวัติที่ตรวจสอบได้</button>
              {lender && (
                <table className="lend">
                  <tbody>
                    <tr><td>FCF (ก่อนหนี้) p5 / p50 ต่อเดือน</td><td>{baht(lender.fcf_p5)} / {baht(lender.fcf_p50)}</td></tr>
                    <tr><td>ค่างวดหนี้ปัจจุบัน</td><td>{baht(lender.existing_debt_service)}</td></tr>
                    <tr><td>PMT สูงสุดรวม (α={lender.alpha} × FCF p5)</td><td>{baht(lender.pmt_max_total)}</td></tr>
                    <tr><td>วงเงินรวมที่รองรับ (18%/{lender.assumed_n} ด.)</td><td>{baht(lender.l_max_total)}</td></tr>
                    <tr><td>วงเงินใหม่ หลังหักหนี้เดิม</td><td><b>{baht(lender.l_max_new)}</b></td></tr>
                    <tr><td>hash ส่งออก</td><td><code>{lender.export_sha256.slice(0, 16)}…</code></td></tr>
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </section>
      <footer>{st.notice} · เป็นเครื่องมือวางแผน ไม่ใช่คำแนะนำลงทุน · ตัวเลขทั้งหมดมาจาก engine ไม่ใช่ LLM</footer>
    </div>
  );
}

function Collections({ st, base, refresh, collectorId }) {
  const [promise, setPromise] = useState({});
  const [msg, setMsg] = useState("");
  const [log, setLog] = useState([]);
  const sim = async (c) => {
    const m = promise[c.id] ?? 1;
    const r = await api.outcome({ customer_id: c.id, promised_month: Number(m), confidence: 0.85 });
    setMsg(`${r.customer}: สัญญาจ่ายเดือนที่ ${r.new.tau} → โอกาสรอด ${pct(r.p_survive_before, 1)} → ${pct(r.p_survive_after, 1)}`);
    refresh();
  };
  return (
    <div className="card">
      <h2>ลงมือ: โทรตามเงิน</h2>
      <table className="coll">
        <thead><tr><th>ลูกหนี้</th><th>ยอดค้าง</th><th>คาดรับ</th><th>โอกาสได้</th><th></th></tr></thead>
        <tbody>
          {st.collections.map((c) => (
            <tr key={c.id}>
              <td>{c.name}</td><td>{baht(c.amount)}</td><td>เดือนที่ {c.tau}</td><td>{pct(c.q)}</td>
              <td className="act">
                <CollectCall c={c} agentId={collectorId} />
                <select value={promise[c.id] ?? 1} onChange={(e) => setPromise({ ...promise, [c.id]: e.target.value })}>
                  {[1, 2, 3, 4].map((m) => <option key={m} value={m}>สัญญาเดือน {m}</option>)}
                </select>
                <button className="ghost" onClick={() => sim(c)}>จำลองผลสาย</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {msg && <div className="commit">{msg}</div>}
      {st.calls.length > 0 && (<ul className="ledger">{st.calls.slice(-4).map((c, i) => (<li key={i}>{c.name}: {pct(c.p_before, 1)} → <b>{pct(c.p_after, 1)}</b></li>))}</ul>)}
      <p className="note">เอเจนต์เปิดเผยว่าเป็น AI ทุกสาย · เจ้าของอนุมัติสคริปต์ · ผลสายป้อนกลับ q, τ ตามสูตร 3.6 แล้วจำลองใหม่</p>
    </div>
  );
}

function CollectCall({ c, agentId }) {
  return <Voice agentId={agentId} compact label="โทร (web call)" dynamicVariables={{ customer_id: c.id, customer_name: c.name, amount: String(c.amount) }} />;
}

function Voice({ agentId, label, compact, dynamicVariables }) {
  const { startSession, endSession } = useConversationControls();
  const { status } = useConversationStatus();
  const [e, setE] = useState("");
  const on = status === "connected" || status === "connecting";
  if (!agentId) return compact ? null : <p className="note">ยังไม่ได้ตั้ง VITE_ELEVENLABS_*_AGENT_ID → ใช้ช่องพิมพ์แทนเสียง (โหมดสำรอง)</p>;
  return (
    <>
      <button className={on ? "live" : "ghost"} onClick={() => {
        if (on) return endSession();
        setE("");
        startSession({ agentId, dynamicVariables, onError: (m) => setE(String(m)) });
      }}>{on ? "● วางสาย" : `🎙 ${label}`}</button>
      {e && <span className="err">{e}</span>}
    </>
  );
}
