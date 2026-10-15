import React from "react";

const W = 760, H = 320, M = { l: 64, r: 16, t: 16, b: 30 };

export default function FanChart({ base, branch, cash0 }) {
  const sets = [base, branch].filter(Boolean);
  const all = sets.flatMap((s) => [...s.fan.p5, ...s.fan.p95]).concat([cash0, 0]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const T = base.fan.p50.length;
  const x = (t) => M.l + (t / T) * (W - M.l - M.r);
  const y = (v) => M.t + (1 - (v - lo) / (hi - lo || 1)) * (H - M.t - M.b);
  const line = (arr) => [cash0, ...arr].map((v, t) => `${t ? "L" : "M"}${x(t)},${y(v)}`).join(" ");
  const band = (a, b) =>
    [cash0, ...a].map((v, t) => `${t ? "L" : "M"}${x(t)},${y(v)}`).join(" ") +
    [...[cash0, ...b].map((v, t) => [t, v])].reverse().map(([t, v]) => `L${x(t)},${y(v)}`).join(" ") + "Z";
  const raw = (hi - lo) / 4, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  const tickVals = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) tickVals.push(v);
  const fmt = (v) => (Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="fan" role="img" aria-label="พยากรณ์เงินสด 12 เดือนแบบช่วงความน่าจะเป็น">
      {tickVals.map((v, i) => {
        return (
          <g key={i}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={M.l - 8} y={y(v) + 4} className="tick" textAnchor="end">{fmt(v)}</text>
          </g>
        );
      })}
      {[...Array(T + 1)].map((_, t) => (
        <text key={t} x={x(t)} y={H - 8} className="tick" textAnchor="middle">{t === 0 ? "ตอนนี้" : `ด.${t}`}</text>
      ))}
      <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} className="zero" />
      <text x={W - M.r} y={y(0) - 5} className="zerolbl" textAnchor="end">เงินสด = 0 (ขาดมือ)</text>
      <path d={band(base.fan.p5, base.fan.p95)} className="band-outer" />
      <path d={band(base.fan.p25, base.fan.p75)} className="band-inner" />
      <path d={line(base.fan.p50)} className="median" />
      {branch && (
        <>
          <path d={band(branch.fan.p5, branch.fan.p95)} className="band-branch" />
          <path d={line(branch.fan.p50)} className="median-branch" />
        </>
      )}
    </svg>
  );
}
