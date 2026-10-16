import React, { useEffect, useRef, useSyncExternalStore } from "react";

// Tiny external store so every <Voice> instance feeds the same window.
let state = { lines: [], mode: "idle", open: false, live: false, seq: 0 };
const subs = new Set();
const set = (p) => { state = { ...state, ...p }; subs.forEach((f) => f()); };
const useStore = () => useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => state);

export const transcript = {
  start: () => set({ lines: [], mode: "listening", open: true, live: true }),
  end: () => set({ live: false, mode: "idle" }),
  mode: (mode) => set({ mode }),
  add: ({ role, message }) => {
    if (!message) return;
    const seq = state.seq + 1;
    set({ lines: [...state.lines, { id: seq, role, text: message }], seq, open: true });
  },
  open: () => set({ open: true }),
  close: () => set({ open: false }),
};

// callbacks to spread into startSession({...})
export const transcriptHandlers = {
  onConnect: transcript.start,
  onDisconnect: transcript.end,
  onMessage: (m) => transcript.add({ role: m.role || (m.source === "ai" ? "agent" : "user"), message: m.message }),
  onModeChange: ({ mode }) => transcript.mode(mode === "speaking" ? "speaking" : "listening"),
};

export function TranscriptWindow() {
  const { lines, mode, open, live } = useStore();
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines, open]);
  if (!open) {
    return lines.length ? <button className="tr-fab ghost" onClick={transcript.open}>💬 บทสนทนา ({lines.length})</button> : null;
  }
  const status = !live ? "จบสายแล้ว" : mode === "speaking" ? "เอเจนต์กำลังพูด…" : "กำลังฟังคุณ…";
  return (
    <aside className="tr-win" role="log" aria-live="polite">
      <div className="tr-head">
        <b>💬 บทสนทนาสด</b>
        <span className={`tr-st ${live ? mode : ""}`}>{live && <i />}{status}</span>
        <button className="tr-x" onClick={transcript.close} aria-label="ซ่อน">×</button>
      </div>
      <div className="tr-body" ref={box}>
        {lines.length === 0 && <p className="note">รอการสนทนา…</p>}
        {lines.map((l) => (
          <div key={l.id} className={`tr-b ${l.role === "user" ? "me" : "ai"}`}>
            <span className="tr-who">{l.role === "user" ? "คุณ" : "เอเจนต์ (AI)"}</span>
            {l.text}
          </div>
        ))}
      </div>
    </aside>
  );
}
