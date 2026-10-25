import { useEffect, useState } from "react";
import Clip from "../components/Clip.jsx";
import Chart from "../components/Chart.jsx";
import Matrix from "../components/Matrix.jsx";
import { Diff } from "../components/Code.jsx";
import { int, itLabel, pct, scen, sec } from "../lib.js";

const runName = (key, run) => `Run ${key === "primary" ? "D" : key.toUpperCase()} · from ${pct(run.iterations[0]?.cpr)}`;
const TOTAL = 15;
const scored = (it) => (it.rows?.length || 0) + (it.heldout_rows?.length || 0);

function pendingText(it) {
  if (it.iter === 0) return it.status === "porting" ? "Argon is porting the legacy RAPID to the GoFa" : "Scoring the port on 15 scenarios";
  if (it.status === "watching") return `Argon is analysing the failure: ${scen(it.scenario)}`;
  return "Scoring the patch on 15 scenarios";
}

function Waiting({ it }) {
  return (
    <div className="clip" style={{ flexDirection: "column", gap: 14, background: "var(--surface)", border: "1px solid var(--line)" }}>
      <div className="spinner" style={{ width: 34, height: 34, borderWidth: 3 }} />
      <div style={{ fontSize: 18, fontWeight: 600 }}>{pendingText(it)}</div>
      {it.status !== "porting" && <div className="muted num">{scored(it)} / {TOTAL} scenarios run</div>}
    </div>
  );
}

function Decision({ it }) {
  if (it.pending) {
    return (
      <div className="panel"><div className="panel-body" style={{ display: "grid", gap: 12 }}>
        <div className="thinking"><div className="spinner" />{pendingText(it)}{it.status !== "porting" && it.status !== "watching" ? ` · ${scored(it)}/${TOTAL}` : "…"}</div>
        {it.patch?.routine && <div className="chips"><span className="chip">patch <strong>{it.patch.task}.{it.patch.routine}</strong></span>{it.latency_s != null && <span className="chip num">Argon {sec(it.latency_s)}</span>}</div>}
        {it.root_cause && <div style={{ fontSize: 15, lineHeight: 1.4 }}>{it.root_cause}</div>}
        {it.status === "watching" && (
          <div className="kv" style={{ marginTop: 4 }}>
            <span className="k">Video</span><span>the clip on the left: 8 s, 5 fps, no labels</span>
            <span className="k">Code</span><span>current RAPID for both robots, line-numbered, and the legacy program</span>
            <span className="k">Results</span><span>pass / fail and violations for the 10 training scenarios, the twin’s event trace</span>
            <span className="k">Context</span><span>cell facts, Stage 1 findings, the approved DI_GRIP_OK sensor, earlier iterations</span>
            <span className="k">Not sent</span><span>the held-out suite and the engineer’s port</span>
          </div>
        )}
      </div></div>
    );
  }
  if (it.kind === "single_pass" || it.iter === 0) {
    return (
      <div className="panel" style={{ minHeight: 0 }}>
        <div className="panel-head"><span className="panel-title">Iteration 0 · single-pass port</span><span className="badge neutral">{pct(it.cpr)} · held-out {pct(it.heldout)}</span></div>
        <div className="panel-body">
          <div className="muted" style={{ fontSize: 13.5, marginBottom: 10 }}>Legacy RAPID + cell facts only. No Stage 1 findings, no sensor.{it.latency_s ? ` ${sec(it.latency_s, 0)}.` : ""} Argon’s change notes:</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 13.5 }}>{(it.changes || []).map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      </div>
    );
  }
  const [why, nums] = (it.reason || "").split(/:\s(.+)/);
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-head">
        <span className="panel-title">Iteration {it.iter} · {it.patch?.task}.{it.patch?.routine}{it.changed_lines ? ` · ${it.changed_lines} lines` : ""}</span>
        <span className={`badge ${it.kept ? "good" : "warn"}`}>{it.kept ? "✓ KEPT" : "↺ REVERTED"}</span>
      </div>
      <div className="panel-body" style={{ display: "grid", gridTemplateRows: "auto auto minmax(0, 1fr)", gap: 10, minHeight: 0, overflow: "hidden" }}>
        <div style={{ fontSize: 15, lineHeight: 1.4 }}>{it.root_cause}</div>
        <div className="chips">
          {why && <span className="chip"><strong>{why}</strong></span>}
          {nums && nums.split(", ").slice(0, 2).map((n) => <span key={n} className="chip num">{n}</span>)}
          {it.latency_s != null && <span className="chip num">Argon {sec(it.latency_s)}</span>}
          {it.tokens != null && <span className="chip num">{int(it.tokens)} tokens</span>}
          {it.mc && <span className="chip num" title="Monte Carlo: seeded cycles, every grip misses with p = 6%">shift sim: <strong>{Math.round((1000 * it.mc.good) / it.mc.cycles)}</strong> good / 1,000</span>}
        </div>
        <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "auto", minHeight: 0, background: "var(--bg)" }}><Diff diff={it.diff} /></div>
      </div>
    </div>
  );
}

export default function Loop({ b, step, setStep, live, runKey, setRunKey }) {
  const isLive = Boolean(live);
  const run = isLive ? live.run || { iterations: [] } : b.runs[runKey] || b.runs.primary;
  const its = run.iterations.length ? run.iterations : [{ iter: 0, pending: true, status: live?.mode === "full" ? "porting" : "scoring", kind: "single_pass" }];
  const i = Math.max(0, Math.min(step, its.length - 1));
  const it = its[i];
  const [view, setView] = useState("argon");
  const [play, setPlay] = useState(false);
  useEffect(() => { setView("argon"); }, [i, runKey, isLive]);
  useEffect(() => {
    if (!play) return;
    const h = setInterval(() => setStep((s) => (s + 1 < its.length ? s + 1 : (setPlay(false), s))), 9000);
    return () => clearInterval(h);
  }, [play, its.length]);
  useEffect(() => {
    const h = (e) => { if (e.key === "p" || e.key === "P") setPlay((x) => !x); };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, []);
  const last = its[its.length - 1];
  useEffect(() => { if (isLive) setStep(its.length - 1); }, [isLive, its.length, last?.pending]);

  const next = its[i + 1];
  const clipIt = it.iter === 0 && !it.pending && next ? next : it;
  const clipSrc = view === "after" ? it.after_clip : view === "before" ? it.before_clip : clipIt?.argon_clip;
  const obsEvents = view === "argon" && clipIt?.observations ? clipIt.observations.map((o) => ({ t: o.clip_time_s, level: "info", text: `Argon: ${o.what}` })) : null;
  const pins = view === "argon" && clipIt?.failure_time_s != null
    ? [{ t: clipIt.failure_time_s, kind: "argon", title: `Argon: failure visible at ${clipIt.failure_time_s.toFixed(1)} s` }]
        .concat(clipIt.truth_t != null ? [{ t: clipIt.truth_t, kind: "truth", title: `twin ground truth ${clipIt.truth_t.toFixed(1)} s` }] : [])
    : [];
  const repeats = Object.entries(b.runs).filter(([k]) => isLive || k !== runKey).map(([k, r]) => ({ key: k, iterations: r.iterations }));
  const refs = [{ y: 0, label: "verbatim copy" }, { y: b.proof.reference_lines.legacy_irb, label: "legacy, human port" }];
  const select = (n) => setStep(its.findIndex((x) => x.iter === n));
  return (
    <div className="beat">
      <div className="beat-head">
        <div>
          <div className="eyebrow">04 · The loop · {isLive ? "live" : "replay"}</div>
          <h2 className="headline">Argon watches the failure, patches one routine, and keeps the patch only if the score rises.</h2>
          <div className="subline">Keep or revert is decided by code on 10 training scenarios. 5 held-out scenarios are scored but never shown to Argon.</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {!isLive && <div className="seg">{Object.entries(b.runs).map(([k, r]) => <button key={k} className={k === runKey ? "on" : ""} onClick={() => { setRunKey(k); setStep(0); }}>{runName(k, r)}</button>)}</div>}
          {!isLive && <button className="icon-btn" onClick={() => setPlay((p) => !p)}>{play ? "❚❚ Pause" : "▶ Play"} <kbd>P</kbd></button>}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.06fr 1fr", gridTemplateRows: "minmax(0, 1fr) auto", gap: 18, minHeight: 0 }}>
        <div style={{ display: "grid", gridTemplateRows: "minmax(0, 1fr) auto", gap: 12, minHeight: 0 }}>
          <div style={{ position: "relative", minHeight: 0, display: "grid" }}>
            {clipSrc ? (
              <Clip key={`${isLive ? "live" : runKey}-${i}-${view}-${clipSrc}`} src={clipSrc} events={view === "argon" ? obsEvents : clipSrc.replace(".mp4", ".events.json")}
                    pins={pins} captionMax={1} rate={view === "argon" ? 1 : 1.25}
                    tags={[view === "argon" ? "Argon’s input · 5 fps · no overlays" : view === "before" ? "before the patch" : "after the patch", scen(clipIt?.scenario)].filter(Boolean)}
                    rightTags={[isLive ? "LIVE" : "REPLAY", b.meta.labels.sim_fault]} />
            ) : <Waiting it={it} />}
            {clipSrc && it.pending && it.status === "watching" && (
              <div className="ev" style={{ position: "absolute", top: 52, left: 12, zIndex: 3 }}><div className="spinner" style={{ width: 14, height: 14 }} />Argon is watching this clip</div>
            )}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, minHeight: 32 }}>
            <div className="legend">
              <span><i className="sw" style={{ background: "var(--blue)", borderRadius: "50%" }} />Argon’s failure time{clipIt?.failure_time_s != null ? ` ${clipIt.failure_time_s.toFixed(1)} s` : ""}</span>
              <span><i className="sw" style={{ background: "#fff", width: 3 }} />twin ground truth{clipIt?.truth_t != null ? ` ${clipIt.truth_t.toFixed(1)} s` : ""}</span>
            </div>
            {it.after_clip && <div className="seg">{[["argon", "Argon’s input"], ["before", "Before"], ["after", "After"]].map(([k, l]) => <button key={k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{l}</button>)}</div>}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateRows: "minmax(300px, 0.95fr) minmax(0, 1fr)", gap: 18, minHeight: 0 }}>
          <div className="panel">
            <div className="panel-body" style={{ display: "grid", gridTemplateColumns: "1.25fr 1fr", gap: 18, height: "100%", overflow: "hidden" }}>
              <Chart its={its} repeats={repeats} refs={refs} current={it.iter} onSelect={select} nMax={isLive ? 6 : undefined} />
              <Matrix its={its} suite={b.suite} held={b.heldout_suite} current={it.iter} onSelect={select} />
            </div>
          </div>
          <Decision it={it} />
        </div>
        <div className="stepper" style={{ gridColumn: "1 / -1" }}>
          {its.map((x, k) => (
            <button key={k} className={`it-chip ${k === i ? "active" : ""} ${x.pending ? "pending" : ""}`} onClick={() => setStep(k)}>
              <div className="top"><span>#{x.iter}</span>{x.pending ? <div className="spinner" style={{ width: 12, height: 12 }} /> : x.iter > 0 && <span style={{ color: x.kept ? "var(--good-text)" : "var(--warn)" }}>{x.kept ? "kept" : "reverted"}</span>}</div>
              <div className="what">{x.pending ? (x.iter === 0 ? (x.status === "porting" ? "porting…" : "scoring…") : x.status === "watching" ? "Argon watching…" : `scoring ${scored(x)}/${TOTAL}…`) : itLabel(x)}</div>
              {!x.pending && <div className="cpr num">{pct(x.cpr)} <span className="faint" style={{ fontWeight: 400 }}>· held-out {pct(x.heldout)}</span></div>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
