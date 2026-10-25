import { useEffect, useRef, useState } from "react";
import { itLabel, pct } from "../lib.js";

function useSize() {
  const ref = useRef(null);
  const [s, setS] = useState({ w: 600, h: 260 });
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setS({ w: e.contentRect.width, h: e.contentRect.height }));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, s];
}

const stepPath = (pts) => pts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `H${p[0]}V${p[1]}`)).join("");

/* Cell Pass Rate per iteration: training suite (decides keep/revert) and held-out suite (never shown to Argon),
   repeat runs as thin grey lines, reference programs as dashed lines, reverted tries as hollow dots. One y-axis (%). */
export default function Chart({ its, repeats = [], refs = [], current, onSelect, nMax }) {
  const [ref, { w, h }] = useSize();
  const [hover, setHover] = useState(null);
  const m = { l: 44, r: 128, t: 52, b: 30 };
  const N = Math.max(nMax || 0, its.length - 1, ...repeats.map((r) => r.iterations.length - 1), 1);
  const x = (i) => m.l + ((w - m.l - m.r) * i) / N;
  const y = (v) => m.t + (h - m.t - m.b) * (1 - v);
  const shown = its.filter((it) => it.cpr != null);
  const train = shown.map((it) => [x(it.iter), y(it.cpr)]);
  const held = shown.filter((it) => it.heldout != null).map((it) => [x(it.iter), y(it.heldout)]);
  const last = shown[shown.length - 1];
  const hv = hover != null ? its.find((it) => it.iter === hover) : null;
  return (
    <div ref={ref} style={{ position: "relative", width: "100%", height: "100%", minHeight: 200 }}>
      <svg className="chart" width={w} height={h} onMouseLeave={() => setHover(null)}
           onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.round(((e.clientX - r.left - m.l) / (w - m.l - m.r)) * N); setHover(i >= 0 && i < its.length ? i : null); }}
           onClick={() => hover != null && onSelect?.(hover)}>
        <g>
          <circle cx={6} cy={12} r={4.5} fill="var(--blue)" /><text x={16} y={16}>Training suite (10) · decides keep / revert</text>
          <rect x={1.5} y={27.5} width={9} height={9} rx={1.5} fill="var(--orange)" /><text x={16} y={36}>Held-out (5) · never shown to Argon</text>
          {repeats.length > 0 && <><line x1={Math.max(300, w * 0.55)} x2={Math.max(300, w * 0.55) + 14} y1={12} y2={12} stroke="var(--repeat)" strokeWidth={2} />
            <text x={Math.max(300, w * 0.55) + 20} y={16}>other runs ({repeats.length})</text></>}
        </g>
        {[0, 0.5, 1].map((v) => (
          <g key={v}><line className="grid" x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} /><text x={m.l - 8} y={y(v) + 4} textAnchor="end">{pct(v)}</text></g>
        ))}
        {Array.from({ length: N + 1 }, (_, i) => <text key={i} x={x(i)} y={h - 8} textAnchor="middle" className="num">{i}</text>)}
        {current != null && <rect x={x(current) - 14} y={m.t - 6} width={28} height={h - m.t - m.b + 12} rx={6} fill="var(--surface-3)" opacity={0.7} />}
        {refs.map((r) => (
          <g key={r.label}><line className="ref" x1={m.l} x2={w - m.r} y1={y(r.y)} y2={y(r.y)} />
            <text x={w - m.r + 8} y={y(r.y) + 4} style={{ fill: "var(--text-3)", fontSize: 11.5 }}>{r.label}</text></g>
        ))}
        {repeats.map((r) => (
          <path key={r.key} d={stepPath(r.iterations.filter((i) => i.cpr != null).map((it) => [x(it.iter), y(it.cpr)]))} fill="none" stroke="var(--repeat)" strokeWidth={1.25} />
        ))}
        <path d={stepPath(held)} fill="none" stroke="var(--orange)" strokeWidth={2} />
        <path d={stepPath(train)} fill="none" stroke="var(--blue)" strokeWidth={2} />
        {shown.map((it) => it.kept === false && it.tried != null && (
          <circle key={`t${it.iter}`} cx={x(it.iter)} cy={y(it.tried)} r={5} fill="var(--surface)" stroke="var(--blue)" strokeWidth={1.75} strokeDasharray="2 2" />
        ))}
        {held.map(([px, py], i) => <rect key={`h${i}`} x={px - 4.5} y={py - 4.5} width={9} height={9} rx={1.5} fill="var(--orange)" stroke="var(--surface)" strokeWidth={2} />)}
        {shown.map((it) => <circle key={`c${it.iter}`} cx={x(it.iter)} cy={y(it.cpr)} r={it.kept === false ? 3.5 : 5} fill="var(--blue)" stroke="var(--surface)" strokeWidth={2} />)}
        {last && <text x={x(last.iter) + 12} y={y(last.cpr) + 4} style={{ fill: "var(--text)", fontWeight: 650 }}>{pct(last.cpr)}</text>}
        {hv && <line x1={x(hv.iter)} x2={x(hv.iter)} y1={m.t} y2={h - m.b} stroke="var(--text-3)" strokeDasharray="2 3" />}
      </svg>
      {hv && hv.cpr != null && (
        <div className="tip" style={{ left: Math.min(x(hv.iter) + 14, w - 250), top: 30 }}>
          <div style={{ fontWeight: 650, marginBottom: 4 }}>Iteration {hv.iter} · {itLabel(hv)}</div>
          <div>Training <b>{pct(hv.cpr)}</b> · held-out <b>{pct(hv.heldout)}</b></div>
          {hv.progress != null && <div className="muted">normal-cycle progress {pct(hv.progress)}</div>}
          {hv.decision && <div className="muted">{hv.decision}{hv.tried != null && hv.kept === false ? ` (tried ${pct(hv.tried)})` : ""}</div>}
        </div>
      )}
    </div>
  );
}
