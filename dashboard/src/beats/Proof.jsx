import { useRef, useState } from "react";
import Clip from "../components/Clip.jsx";
import { int, media, pct, sec } from "../lib.js";

function Board({ b }) {
  const cols = b.proof.scoreboard;
  const mc = (r, p, k) => r.mc?.[p]?.[k];
  const rows = [
    ["Cell Pass Rate", "10 training scenarios", (r) => pct(r.cpr)],
    ["Held-out scenarios", "never shown to Argon", (r) => `${r.heldout_pass}/${r.heldout_n}`],
    ["Faults handled", "of 9 injected", (r) => `${r.fault_pass}/${r.faults}`],
    ["Good boxes · safe stops", `${int(b.proof.mc_meta.n || 1000)}-cycle shift sim, 6% miss per grasp`, (r) => (mc(r, "0.06", "good") == null ? "–" : `${int(mc(r, "0.06", "good"))} · ${int(mc(r, "0.06", "safe_stop"))}`)],
    ["Bad boxes shipped as good", "silent failures, same shift", (r) => int(mc(r, "0.06", "silent_bad"))],
    ["Target error vs engineer’s port", "mean / max", (r) => (r.target_err?.mean_mm == null ? "—" : r.key === "verbatim" ? `${(r.target_err.mean_mm / 1000).toFixed(1)} / ${(r.target_err.max_mm / 1000).toFixed(1)} m` : `${r.target_err.mean_mm} / ${r.target_err.max_mm} mm`)],
  ];
  return (
    <table className="board">
      <thead><tr><th />{cols.map((c) => <th key={c.key} className={c.key === "looped" ? "hl" : ""}>{c.name}</th>)}</tr></thead>
      <tbody>{rows.map(([n, sub, f]) => (
        <tr key={n}><td className="rowname">{n} {sub && <span className="sub" style={{ marginLeft: 8 }}>{sub}</span>}</td>
          {cols.map((c) => <td key={c.key} className={`v ${c.key === "looped" ? "hl" : ""}`} style={{ fontWeight: c.key === "looped" ? 650 : 400 }}>{f(c)}</td>)}</tr>
      ))}</tbody>
    </table>
  );
}

function Agents({ b }) {
  const a = b.agents;
  if (!a) return <div className="faint">No managed-agent run in this bundle.</div>;
  const max = Math.max(...a.agents.map((x) => x.duration_s || 0), 1);
  const summary = (x) => {
    const o = x.output || {};
    if (x.role === "log-verifier") {
      const c = o.confusion || o.confusion_matrix || {};
      const mg = c.missed_grasp || {}, su = c.success || c.successes || {};
      return mg.flagged != null ? `missed grasps ${mg.flagged}/${mg.total} · successes ${su.flagged}/${su.total}` : "confusion matrix on 218 logs";
    }
    return o.cpr != null ? `CPR ${pct(o.cpr)} · held-out ${pct(o.heldout)}` : x.status;
  };
  return (
    <div>
      {a.agents.map((x) => (
        <div key={x.label || x.role} className="lane">
          <div><div style={{ fontWeight: 600 }}>{x.label || x.role}</div><div className="faint mono" style={{ fontSize: 11 }}>{x.role} · {x.environment_id ? `env ${String(x.environment_id).slice(0, 8)}` : ""}</div></div>
          <div><div className="bar"><div style={{ width: `${(100 * (x.duration_s || 0)) / max}%` }} /></div><div className="muted" style={{ fontSize: 12.5, marginTop: 5 }}>{summary(x)}</div>
            {typeof x.output?.verdict === "string" && <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.4, color: "var(--text)" }}>“{x.output.verdict.split(/(?<=\.)\s/)[0].slice(0, 230)}”</div>}</div>
          <div style={{ textAlign: "right" }}><div className="num">{sec(x.duration_s, 0)}</div>
            <span className={`badge ${x.matches_local ? "good" : "warn"}`} style={{ marginTop: 4 }}>{x.matches_local ? "✓ matches local" : "≠ local"}</span></div>
        </div>
      ))}
      <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>Parallel fan-out, {sec(a.fanout_wall_s, 0)} wall. Custom managed agents on gemini-4-argon, one remote sandbox each, built from public sources. The engineer’s port never leaves this machine.</div>
    </div>
  );
}

export default function Proof({ b, step }) {
  const p = b.proof;
  const [nonce, setNonce] = useState(0);
  const hRef = useRef(null), lRef = useRef(null);
  const sync = (t) => { if (hRef.current && Math.abs(hRef.current.currentTime - t) > 0.25) hRef.current.currentTime = t; };
  return (
    <div className="beat">
      <div className="beat-head">
        <div>
          <div className="eyebrow">05 · Proof</div>
          <h2 className="headline">{step === 0 ? "Same fault. The engineer’s port fails silently. Argon’s re-grips." : "Re-checked independently. Ready for Monday."}</h2>
          <div className="subline">{step === 0 ? "R1 misses the tray once. Same twin, same fault." : "Four managed agents rebuilt the twin in their own sandboxes and re-ran every check."}</div>
        </div>
        {step === 0 && <button className="icon-btn" onClick={() => setNonce((n) => n + 1)}>↺ Replay both</button>}
      </div>
      {step === 0 ? (
        <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 18, minHeight: 0 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, minHeight: 0 }}>
            <Clip key={`h${nonce}`} videoRef={hRef} src={p.split?.human} events={p.split?.human_events} tags={["Engineer’s port (held out)"]} rightTags={["R1 misses the tray once"]} />
            <Clip key={`l${nonce}`} videoRef={lRef} src={p.split?.looped} events={p.split?.looped_events} onTime={sync} tags={["Argon looped"]} rightTags={[b.meta.labels.sim_fault]} />
          </div>
          <div className="panel"><div className="panel-body flush"><Board b={b} /></div></div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr", gap: 18, minHeight: 0 }}>
          <div className="panel">
            <div className="panel-head"><span className="panel-title">Managed agents · parallel fan-out</span><span className="label-tag">gemini-4-argon · remote sandboxes</span></div>
            <div className="panel-body"><Agents b={b} /></div>
          </div>
          <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 18, minHeight: 0 }}>
            <Clip src={p.safe_stop?.clip} events={p.safe_stop?.events} tags={["Argon looped · the part never grips"]} rightTags={["safe stop with alarm"]} />
            <div className="panel">
              <div className="panel-head"><span className="panel-title">Hand-off</span><span className="badge good">✓ ready for Monday</span></div>
              <div className="panel-body" style={{ display: "grid", gap: 8 }}>
                {b.handoff.files.filter(Boolean).map((f) => <a key={f} href={media(f)} download className="chip" style={{ textDecoration: "none" }}>⤓ <strong>{f.split("/").pop()}</strong></a>)}
                <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "grid", gap: 4 }} className="muted">{b.handoff.notes.map((n) => <li key={n} style={{ fontSize: 12.5 }}>{n}</li>)}</ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
