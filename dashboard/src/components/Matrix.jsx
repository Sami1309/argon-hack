import { scen } from "../lib.js";

/* Scenario x iteration grid: filled = pass. Blue rows = training suite, orange rows = held-out (never shown to Argon).
   Shows exactly which scenario each kept patch flipped, and that held-out scenarios flip with them. */
export default function Matrix({ its, suite, held, current, onSelect, footer }) {
  const cols = its.length;
  const grid = { gridTemplateColumns: `minmax(120px, 170px) repeat(${cols}, minmax(14px, 1fr))` };
  const cell = (it, id, kind) => {
    const rows = kind === "train" ? it.rows : it.heldout_rows;
    const r = rows?.find((x) => x.id === id);
    return <div key={`${it.iter}-${id}`} className={`cell ${r?.passed ? "pass" : ""} ${kind}`} title={r ? `${scen(id)}: ${r.why}` : "pending"}
                style={{ opacity: r ? 1 : 0.25 }} onClick={() => onSelect?.(it.iter)} />;
  };
  return (
    <div className="matrix" style={grid}>
      <div className="rl faint" style={{ fontSize: 11 }}>scenario \ iteration</div>
      {its.map((it) => <div key={`h${it.iter}`} className={`hdr ${it.iter === current ? "col-cur" : ""}`}>{it.iter}</div>)}
      {suite.map((s) => [<div key={`l${s.id}`} className="rl">{scen(s.id)}</div>, ...its.map((it) => cell(it, s.id, "train"))])}
      <div className="sep" />
      {held.map((s) => [<div key={`l${s.id}`} className="rl" style={{ color: "var(--text-2)" }}>{scen(s.id)}</div>, ...its.map((it) => cell(it, s.id, "held"))])}
      {footer && <><div className="sep" />{footer}</>}
    </div>
  );
}
