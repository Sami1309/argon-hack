import { useEffect, useState } from "react";
import Clip from "../components/Clip.jsx";
import Chart from "../components/Chart.jsx";
import Matrix from "../components/Matrix.jsx";
import { Diff } from "../components/Code.jsx";
import { int, itLabel, pct, scen, sec } from "../lib.js";

const runName = (key, run) => {
  const it0 = run.iterations[0];
  return key === "primary" ? `Run D · starts at ${pct(it0?.cpr)}` : `Run ${key.toUpperCase()} · starts at ${pct(it0?.cpr)}`;
};

function Decision({ it }) {
  if (it.kind === "single_pass" || it.iter === 0) {
    return (
      <div className="panel" style={{ minHeight: 0 }}>
        <div className="panel-head"><span className="panel-title">Iteration 0 · Argon single-pass port</span><span className="badge neutral">{pct(it.cpr)} · held-out {pct(it.heldout)}</span></div>
        <div className="panel-body">
          <div className="muted" style={{ fontSize: 13.5, marginBottom: 10 }}>One call over the legacy RAPID and the cell facts{it.latency_s ? ` (${sec(it.latency_s, 0)})` : ""}. No Stage 1 findings, no sensor: a plain port. Argon’s own change notes:</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 13.5 }}>{(it.changes || []).map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      </div>
    );
  }
  if (it.pending) {
    return (
      <div className="panel"><div className="panel-body">
        <div className="thinking"><div className="spinner" />{it.status === "watching" ? `Argon is watching ${scen(it.scenario)}…` : "Patched: re-running both suites…"}</div>
        {it.root_cause && <div style={{ marginTop: 14, fontSize: 15 }}>{it.root_cause}</div>}
      </div></div>
    );
  }
  const kept = it.kept;
  const [why, nums] = (it.reason || "").split(/:\s(.+)/);
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-head">
        <span className="panel-title">Iteration {it.iter} · patch {it.patch?.task}.{it.patch?.routine}{it.changed_lines ? ` · ${it.changed_lines} lines` : ""}</span>
        <span className={`badge ${kept ? "good" : "warn"}`}>{kept ? "✓ KEPT" : "↺ REVERTED"}</span>
      </div>
      <div className="panel-body" style={{ display: "grid", gridTemplateRows: "auto auto minmax(0, 1fr)", gap: 10, minHeight: 0, overflow: "hidden" }}>
        <div style={{ fontSize: 15, lineHeight: 1.4 }}>{it.root_cause}</div>
        <div className="chips">
          <span className="chip"><strong>{why}</strong></span>
          {nums && nums.split(", ").slice(0, 2).map((n) => <span key={n} className="chip num">{n}</span>)}
          {it.latency_s != null && <span className="chip num">Argon {sec(it.latency_s)}</span>}
          {it.tokens != null && <span className="chip num">{int(it.tokens)} tokens</span>}
          {it.mc && <span className="chip num" title="Monte Carlo: seeded cycles, every grip misses with p = 6%">shift sim: <strong>{Math.round((1000 * it.mc.good) / it.mc.cycles)}</strong> good boxes / 1,000</span>}
        </div>
        <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "auto", minHeight: 0, background: "var(--bg)" }}><Diff diff={it.diff} /></div>
      </div>
    </div>
  );
}

export default function Loop({ b, step, setStep, live, runKey, setRunKey }) {
  const runs = live?.run ? { live: live.run } : b.runs;
  const key = live?.run ? "live" : runKey;
  const run = runs[key] || b.runs.primary;
  const its = run.iterations;
  const i = Math.min(step, its.length - 1);
  const it = its[i] || its[0];
  const [view, setView] = useState("argon");
  const [play, setPlay] = useState(false);
  useEffect(() => { setView("argon"); }, [i, key]);
  useEffect(() => {
    if (!play) return;
    const h = setInterval(() => setStep((s) => (s + 1 < its.length ? s + 1 : (setPlay(false), s))), 9000);
    return () => clearInterval(h);
  }, [play, its.length]);
  useEffect(() => {
    const h = (e) => { if (e.key === "p" || e.key === "P") setPlay((x) => !x); };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => { if (live?.run) setStep(its.length - 1); }, [live?.run && its.length, live?.run && its[its.length - 1]?.pending]);
  const next = its[i + 1];
  const clipIt = it.iter === 0 ? next : it;
  const clipSrc = view === "after" ? it.after_clip : view === "before" ? it.before_clip : clipIt?.argon_clip;
  const obsEvents = view === "argon" && clipIt?.observations ? clipIt.observations.map((o) => ({ t: o.clip_time_s, level: "info", text: `Argon: ${o.what}` })) : null;
  const pins = view === "argon" && clipIt?.failure_time_s != null
    ? [{ t: clipIt.failure_time_s, kind: "argon", title: `Argon: failure visible at ${clipIt.failure_time_s.toFixed(1)} s` }].concat(clipIt.truth_t != null ? [{ t: clipIt.truth_t, kind: "truth", title: `twin ground truth ${clipIt.truth_t.toFixed(1)} s` }] : [])
    : [];
  const repeats = Object.entries(b.runs).filter(([k]) => k !== key).map(([k, r]) => ({ key: k, iterations: r.iterations }));
  const refs = [{ y: 0, label: "verbatim copy" }, { y: b.proof.reference_lines.legacy_irb, label: "legacy, human port" }];
  return (
    <div className="beat">
      <div className="beat-head">
        <div>
          <div className="eyebrow">04 · The loop {live?.run ? "· live" : "· replay"}</div>
          <h2 className="headline">Argon watches the twin, patches one routine, and keeps it only if the score goes up.</h2>
          <div className="subline">Keep/revert is decided by code on the training suite. The held-out suite is scored every time and never shown to Argon.</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {!live?.run && <div className="seg">{Object.entries(b.runs).map(([k, r]) => <button key={k} className={k === key ? "on" : ""} onClick={() => { setRunKey(k); setStep(0); }}>{runName(k, r)}</button>)}</div>}
          <button className="icon-btn" onClick={() => setPlay((p) => !p)}>{play ? "❚❚ Pause" : "▶ Play"} <kbd>P</kbd></button>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.06fr 1fr", gridTemplateRows: "minmax(0, 1fr) auto", gap: 18, minHeight: 0 }}>
        <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 12, minHeight: 0 }}>
          <div style={{ position: "relative", minHeight: 0, display: "grid" }}>
            <Clip key={`${key}-${i}-${view}`} src={clipSrc} events={view === "argon" ? obsEvents : clipSrc?.replace(".mp4", ".events.json")} pins={pins} captionMax={1} rate={view === "argon" ? 1 : 1.25}
                  tags={[view === "argon" ? "what Argon saw · twin render · 5 fps · no overlays" : view === "before" ? "before the patch" : "after the patch", clipIt ? scen(clipIt.scenario) : ""].filter(Boolean)}
                  rightTags={[live?.run ? "LIVE" : "REPLAY", b.meta.labels.sim_fault]} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div className="legend">
              <span><i className="sw" style={{ background: "var(--blue)", borderRadius: "50%" }} />Argon’s failure pin{clipIt?.failure_time_s != null ? ` ${clipIt.failure_time_s.toFixed(1)} s` : ""}</span>
              <span><i className="sw" style={{ background: "#fff", width: 3 }} />twin ground truth{clipIt?.truth_t != null ? ` ${clipIt.truth_t.toFixed(1)} s` : ""}</span>
            </div>
            {it.after_clip && <div className="seg">{[["argon", "Argon’s view"], ["before", "Before"], ["after", "After the patch"]].map(([k, l]) => <button key={k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{l}</button>)}</div>}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateRows: "minmax(300px, 0.95fr) minmax(0, 1fr)", gap: 18, minHeight: 0 }}>
          <div className="panel">
            <div className="panel-body" style={{ display: "grid", gridTemplateColumns: "1.25fr 1fr", gap: 18, height: "100%", overflow: "hidden" }}>
              <Chart its={its} repeats={repeats} refs={refs} current={it.iter} onSelect={(n) => setStep(its.findIndex((x) => x.iter === n))} />
              <Matrix its={its} suite={b.suite} held={b.heldout_suite} current={it.iter} onSelect={(n) => setStep(its.findIndex((x) => x.iter === n))} />
            </div>
          </div>
          <Decision it={it} />
        </div>
        <div className="stepper" style={{ gridColumn: "1 / -1" }}>
          {its.map((x, k) => (
            <button key={k} className={`it-chip ${k === i ? "active" : ""} ${x.pending ? "pending" : ""}`} onClick={() => setStep(k)}>
              <div className="top"><span>#{x.iter}</span>{x.pending ? <div className="spinner" style={{ width: 12, height: 12 }} /> : x.iter > 0 && <span style={{ color: x.kept ? "var(--good-text)" : "var(--warn)" }}>{x.kept ? "kept" : "reverted"}</span>}</div>
              <div className="what">{x.pending ? (x.status === "watching" ? "Argon watching…" : "re-running suites…") : itLabel(x)}</div>
              {!x.pending && <div className="cpr num">{pct(x.cpr)} <span className="faint" style={{ fontWeight: 400 }}>· held-out {pct(x.heldout)}</span></div>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
