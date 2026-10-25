import { useCallback, useEffect, useRef, useState } from "react";
import Problem from "./beats/Problem.jsx";
import Evidence from "./beats/Evidence.jsx";
import Twin, { TWIN_STEPS } from "./beats/Twin.jsx";
import Loop from "./beats/Loop.jsx";
import Proof from "./beats/Proof.jsx";
import Inspector from "./components/Inspector.jsx";
import LiveDialog from "./components/LiveDialog.jsx";
import { getJSON, pct } from "./lib.js";

const BEATS = [
  { key: "problem", label: "Problem", steps: () => ["The cell"] },
  { key: "evidence", label: "Evidence", steps: () => ["The shift", "The fix"] },
  { key: "twin", label: "Twin", steps: () => TWIN_STEPS },
  { key: "loop", label: "Loop", steps: (b, run) => run.iterations.map((x) => `#${x.iter}`) },
  { key: "proof", label: "Proof", steps: () => ["Same fault", "Hand-off"] },
];

function reduceLive(s, e) {
  const run = s.run || { iterations: [] };
  const its = [...run.iterations];
  const k = e.iter;
  switch (e.ev) {
    case "stage": return { ...s, stage: e.stage, status: e.status, approved: s.approved || e.status === "approved", [`stage_${e.stage}`]: e };
    case "iteration": {
      const base = { ...e, kind: k === 0 ? "single_pass" : "patch" };
      if (k > 0 && e.decision) {
        const d = e.decision;
        Object.assign(base, { argon_clip: d.clip_url, observations: d.observations, root_cause: d.root_cause, failure_time_s: d.failure_time_s,
          truth_t: d.truth_t, patch: { task: d.patch.task, routine: d.patch.routine }, diff: d.diff, changed_lines: d.changed_lines, scenario: d.scenario });
      }
      const at = its.findIndex((x) => x.iter === k);
      if (at >= 0) its[at] = base; else its.push(base);
      return { ...s, run: { ...run, iterations: its } };
    }
    case "watching": its.push({ iter: k, pending: true, status: "watching", scenario: e.scenario, argon_clip: e.clip_url }); return { ...s, run: { ...run, iterations: its } };
    case "patch": {
      const at = its.findIndex((x) => x.iter === k);
      if (at >= 0) its[at] = { ...its[at], status: "patched", root_cause: e.root_cause, failure_time_s: e.failure_time_s, patch: { task: e.task, routine: e.routine }, latency_s: e.latency_s };
      return { ...s, run: { ...run, iterations: its } };
    }
    case "done": return { ...s, doneReason: e.reason };
    case "finished": return { ...s, finished: true };
    case "error": return { ...s, error: e.message, finished: true };
    default: return s;
  }
}

export default function App() {
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  const [beat, setBeat] = useState(() => Number(new URLSearchParams(location.hash.slice(1)).get("beat") || 0));
  const [step, setStep] = useState(() => Number(new URLSearchParams(location.hash.slice(1)).get("step") || 0));
  const [runKey, setRunKey] = useState("primary");
  const [inspector, setInspector] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [live, setLive] = useState(null);
  const [banner, setBanner] = useState(null);
  const [tick, setTick] = useState(0);
  const esRef = useRef(null);

  useEffect(() => { getJSON("/bundle/bundle.json").then(setB).catch((e) => setErr(String(e))); }, []);
  useEffect(() => { history.replaceState(null, "", `#beat=${beat}&step=${step}`); }, [beat, step]);
  useEffect(() => {
    const h = () => { const q = new URLSearchParams(location.hash.slice(1)); setBeat(Number(q.get("beat") || 0)); setStep(Number(q.get("step") || 0)); };
    window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => { if (!live || live.finished) return; const h = setInterval(() => setTick((x) => x + 1), 1000); return () => clearInterval(h); }, [live?.id, live?.finished]);

  const run = live?.run || (b && (b.runs[runKey] || b.runs.primary));
  const nSteps = b ? BEATS[beat].steps(b, run || { iterations: [] }).length : 1;
  const go = useCallback((d) => {
    if (!b) return;
    const n = BEATS[beat].steps(b, run).length;
    if (d > 0) { if (step + 1 < n) setStep(step + 1); else if (beat + 1 < BEATS.length) { setBeat(beat + 1); setStep(0); } }
    else if (step > 0) setStep(step - 1);
    else if (beat > 0) { const pb = beat - 1; setBeat(pb); setStep(BEATS[pb].steps(b, run).length - 1); }
  }, [b, beat, step, run]);

  const startLive = async (opts) => {
    setDialog(false);
    try {
      const r = await fetch("/api/live/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts) });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const { id } = await r.json();
      setLive({ id, mode: opts.mode, start: opts.start, startedAt: Date.now(), run: opts.mode === "loop" ? { iterations: [] } : null });
      setBanner(null);
      if (opts.mode === "loop") { setBeat(3); setStep(0); } else { setBeat(1); setStep(1); }
      esRef.current?.close();
      const es = new EventSource(`/api/live/stream/${id}`);
      es.onmessage = (m) => { const e = JSON.parse(m.data); setLive((s) => (s && s.id === id ? reduceLive(s, e) : s)); };
      es.addEventListener("end", () => es.close());
      es.onerror = () => { es.close(); };
      esRef.current = es;
    } catch (e) {
      setBanner(`Live run could not start (${e.message}). Showing the recorded run (Replay).`);
    }
  };
  useEffect(() => {
    if (live?.error) { setBanner(`Live run failed: ${live.error.slice(0, 160)}. Showing the recorded run (Replay).`); setLive(null); }
  }, [live?.error]);
  useEffect(() => { if (live?.stage === "loop" && live.mode === "full" && beat !== 3) { setBeat(3); setStep(0); } }, [live?.stage]);
  const approve = () => live && fetch(`/api/live/approve/${live.id}`, { method: "POST" });

  useEffect(() => {
    const h = (e) => {
      if (e.target.tagName === "INPUT") return;
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(-1); }
      else if (e.key === "i" || e.key === "I") setInspector((x) => !x);
      else if (e.key === "l" || e.key === "L") setDialog(true);
      else if (e.key === "Escape") { setDialog(false); setInspector(false); }
      else if (/^[1-5]$/.test(e.key)) { setBeat(Number(e.key) - 1); setStep(0); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [go]);

  if (err) return <div style={{ padding: 40 }}>Could not load the demo bundle: {err}. Run <code>python tools/build_demo.py …</code> and <code>python dashboard/server.py</code>.</div>;
  if (!b) return <div style={{ padding: 40 }} className="muted">Loading the demo bundle…</div>;
  const elapsed = live ? Math.round((Date.now() - live.startedAt) / 1000) : 0;
  const liveLast = live?.run?.iterations?.filter((x) => !x.pending).slice(-1)[0];
  const props = { b, step: Math.min(step, nSteps - 1) };
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#181c22" /><path d="M8 23 L16 8 L24 23" stroke="#3987e5" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" /><circle cx="16" cy="19" r="2.4" fill="#e8ebef" /></svg>
          <span className="brand-name">Argon Cell Port</span>
          <span className="persona">· {b.persona.role}: IRB 1200 → GoFa, {b.persona.deadline}</span>
        </div>
        <nav className="beats">
          {BEATS.map((x, k) => (
            <button key={x.key} className={`beat-tab ${k === beat ? "active" : k < beat ? "done" : ""}`} onClick={() => { setBeat(k); setStep(0); }}>
              <span className="dot" />{x.label}
            </button>
          ))}
        </nav>
        <div className="top-right">
          {nSteps > 1 && beat !== 3 && <div className="steps">{BEATS[beat].steps(b, run).map((s, k) => <button key={s} className={`step-pill ${k === step ? "active" : k < step ? "done" : ""}`} onClick={() => setStep(k)}>{s}</button>)}</div>}
          <span className={`mode ${live ? "live" : ""}`}>{live ? "LIVE" : "REPLAY"}</span>
          <button className="icon-btn" onClick={() => setDialog(true)} title="Run live">Live <kbd>L</kbd></button>
          <button className="icon-btn" onClick={() => setInspector((x) => !x)} title="Inspector">Inspect <kbd>I</kbd></button>
        </div>
      </header>
      <main className="stage">
        {beat === 0 && <Problem {...props} />}
        {beat === 1 && <Evidence {...props} live={live && { stage: live.stage, status: live.status, approved: live.approved }} onApprove={approve} />}
        {beat === 2 && <Twin {...props} />}
        {beat === 3 && <Loop b={b} step={step} setStep={setStep} live={live?.run ? live : null} runKey={runKey} setRunKey={setRunKey} />}
        {beat === 4 && <Proof {...props} />}
      </main>
      {inspector && <Inspector b={b} onClose={() => setInspector(false)} />}
      {dialog && <LiveDialog onStart={startLive} onClose={() => setDialog(false)} />}
      {live && (
        <div className="banner">
          <span className="mode live">LIVE</span>
          <span className="num">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</span>
          <span>{live.finished ? `Finished${liveLast ? `: ${pct(liveLast.cpr)} after ${liveLast.iter} iterations` : ""}`
            : live.stage === "stage1" ? "Stage 1: Argon is reading the shift, the logs and the code…"
            : live.stage === "sensor" ? (live.status === "awaiting_approval" ? "Argon proposes a grip sensor: approve it on the Evidence beat" : "Argon is proposing a sensor…")
            : liveLast ? `Iteration ${liveLast.iter}: ${pct(liveLast.cpr)} (held-out ${pct(liveLast.heldout)})` : "Starting the loop…"}</span>
          {live.stage === "sensor" && live.status === "awaiting_approval" && <button className="icon-btn" onClick={() => { setBeat(1); setStep(1); }}>Go to approval</button>}
          <button className="icon-btn" onClick={() => { esRef.current?.close(); setLive(null); }}>Back to replay</button>
        </div>
      )}
      {banner && !live && <div className="banner"><span className="badge warn">Replay</span>{banner}<button className="icon-btn" onClick={() => setBanner(null)}>OK</button></div>}
    </div>
  );
}
