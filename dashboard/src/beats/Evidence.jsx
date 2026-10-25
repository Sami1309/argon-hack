import { useEffect, useMemo, useRef, useState } from "react";
import Clip from "../components/Clip.jsx";
import { Source } from "../components/Code.jsx";
import { getJSON, int, mmss } from "../lib.js";

function Trace({ tr, u, thr }) {
  if (!tr) return <div className="faint" style={{ fontSize: 12 }}>loading telemetry…</div>;
  const W = 1000, H = 120, n = tr.obs.length;
  const px = (i) => (i / Math.max(n - 1, 1)) * W, py = (v) => H - 8 - v * (H - 16);
  const line = (a) => a.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join("");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 110, display: "block" }}>
      <line x1={0} x2={W} y1={py(thr)} y2={py(thr)} stroke="var(--critical)" strokeDasharray="6 5" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <path d={line(tr.act)} fill="none" stroke="var(--text-3)" strokeWidth={1.5} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
      <path d={line(tr.obs)} fill="none" stroke="var(--blue)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      {u != null && <line x1={u * W} x2={u * W} y1={0} y2={H} stroke="#fff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}

function Footage({ ev, setSeekRef }) {
  const [t, setT] = useState(0);
  const [seek, setSeek] = useState(null);
  const [traces, setTraces] = useState(null);
  useEffect(() => { getJSON("/bundle/traces.json").then(setTraces).catch(() => {}); }, []);
  useEffect(() => { setSeekRef.current = (tt) => setSeek({ t: tt }); }, []);
  const eps = ev.episodes;
  const cur = eps.find((e) => t >= e.t0 && t < e.t1) || eps[0];
  const thr = ev.sensor?.proposal?.telemetry_rule?.closed_on_nothing_min ?? 0.85;
  const tr = traces?.episodes?.[cur.seg];
  const u = tr ? Math.min(1, (t - cur.t0) / Math.max(cur.t1 - cur.t0, 0.1)) : null;
  const flag = ev.flags.find((f) => f.seg === cur.seg);
  return (
    <div className="panel" style={{ display: "grid", gridTemplateRows: "1fr auto", minHeight: 0 }}>
      <Clip src={ev.shift} autoPlay loop seekTo={seek} onTime={setT} style={{ borderRadius: "10px 10px 0 0", minHeight: 0 }}
            tags={["real footage · teleoperated Franka · a different cell", `episode ${cur.seg + 1} of 218 · ${mmss(t)}`]}
            rightTags={flag ? [`Argon: ${flag.type.replaceAll("_", " ")}`] : []} />
      <div style={{ padding: "12px 16px 14px", display: "grid", gap: 10 }}>
        <div className="strip">
          {eps.map((e) => (
            <div key={e.seg} title={`episode ${e.seg + 1}: ${e.label}${e.argon ? ` · Argon: ${e.argon}` : ""}`}
                 className={`tile ${e.argon && !e.argon.includes("re_grasp") ? "argon" : ""} ${e.argon?.includes("re_grasp") ? "regrasp" : ""} ${e.label !== "success" ? "labelled" : ""} ${e.seg === cur.seg ? "current" : ""}`}
                 onClick={() => setSeek({ t: e.t0 + 0.05 })} />
          ))}
        </div>
        <div className="legend">
          <span><i className="sw" style={{ background: "#2a3038" }} />success</span>
          <span><i className="sw" style={{ background: "var(--critical)" }} />Argon flagged a failure</span>
          <span><i className="sw" style={{ boxShadow: "inset 0 0 0 1.5px #fff" }} />dataset label says failure</span>
          <span><i className="sw" style={{ background: "var(--warn)" }} />hidden re-grasp (labelled a success)</span>
        </div>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 2 }}>
            <span className="muted">Gripper, episode {cur.seg + 1}: <span style={{ color: "var(--blue)" }}>━ measured</span> <span className="faint">┅ commanded</span></span>
            <span style={{ color: "var(--critical-text)" }}>┅ closed on nothing ≥ {thr}</span>
          </div>
          <Trace tr={tr} u={u} thr={thr} />
        </div>
      </div>
    </div>
  );
}

function Tokens({ tk, src }) {
  const parts = [["Video · 18:57 shift at 3 fps", tk.video, "var(--blue)"], ["Telemetry · 218 episodes at 5 Hz", tk.telemetry, "var(--aqua)"], ["Legacy RAPID + PLC code", tk.code, "var(--yellow)"]];
  return (
    <div className="panel">
      <div className="panel-head"><span className="panel-title">One Argon call, one context</span><span className="faint num" style={{ fontSize: 12 }}>{src.latency_s} s</span></div>
      <div className="panel-body">
        <div className="big-stat num">{int(tk.total)}<span style={{ fontSize: 18, color: "var(--text-2)", fontWeight: 500 }}> tokens</span></div>
        <div className="tokenbar" style={{ marginTop: 14 }}>{parts.map(([l, v, c]) => <div key={l} title={`${l}: ${int(v)}`} style={{ flex: v, background: c }} />)}</div>
        <div style={{ display: "grid", gap: 4, marginTop: 10 }}>
          {parts.map(([l, v, c]) => <div key={l} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}><span><i className="sw" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: c, marginRight: 8 }} />{l}</span><span className="num muted">{int(v)}</span></div>)}
        </div>
      </div>
    </div>
  );
}

function Findings({ ev, seek, twinMiss }) {
  const missed = ev.flags.filter((f) => f.type.includes("missed_grasp"));
  const a = ev.agreement;
  return (
    <div className="panel">
      <div className="panel-head"><span className="panel-title">What Argon found</span><span className="badge bad">● {missed.length} of {ev.flags.length} flagged: missed grasp</span></div>
      <div className="panel-body">
        <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.35 }}>The gripper closes on nothing, and the arm carries on as if it held the block.</div>
        {missed.slice(0, 3).map((f) => (
          <div key={f.seg} className="quote" onClick={() => seek(f.t - 1.5)}><span className="when">{mmss(f.t)}</span>{f.evidence.replace(/^seg \d+:\s*/, "")}</div>
        ))}
        <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>
          Against the dataset’s labels (which Argon never saw): {a.both} of {a.dataset_failures} labelled failures found, plus {a.argon_only.length} the labels
          miss, including a hidden re-grasp in an episode labelled “success”.
        </div>
        <div className="panel-title" style={{ margin: "16px 0 8px" }}>The fault we inject is the fault we saw</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Clip src={ev.real_clip} controls={false} style={{ aspectRatio: "16/9" }} tags={["real · missed grasp"]} />
          <Clip src={twinMiss} controls={false} style={{ aspectRatio: "16/9" }} tags={["twin · injected miss"]} rate={1.5} />
        </div>
      </div>
    </div>
  );
}

function CodeCard({ ev }) {
  const c = ev.code.R1;
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-head"><span className="panel-title">Legacy RAPID · {c.file} · PROC PP_TAB_CONV</span><span className="badge warn">▲ open-loop grip</span></div>
      <div className="panel-body flush" style={{ padding: "8px 0" }}><Source lines={c.lines} from={c.focus[0] - 3} to={c.focus[1] + 4} lit={c.lit} /></div>
      <div className="code-note">Lines {c.lit[0]}–{c.lit[1]}: pulse the gripper, wait 0.25 s, move on. Nothing checks that the part is there. Same pattern at every grip in both tasks.</div>
    </div>
  );
}

function SensorCard({ ev, live, onApprove }) {
  const s = ev.sensor, p = s.proposal.proposal, v = s.verification.by_label;
  const [ok, setOk] = useState(false);
  const liveWaiting = live?.stage === "sensor" && live.status === "awaiting_approval";
  const approved = ok || live?.approved;
  const succ = v.success || { flagged: 0, total: 0 }, mg = v.missed_grasp || { flagged: 0, total: 0 };
  const other = Object.entries(v).filter(([k]) => k !== "success" && k !== "missed_grasp").reduce((a, [, x]) => [a[0] + x.flagged, a[1] + x.total], [0, 0]);
  return (
    <div className="panel">
      <div className="panel-head"><span className="panel-title">Argon’s proposal · the one decision for the engineer</span><span className="label-tag">proposed sensor</span></div>
      <div className="panel-body">
        <div style={{ fontSize: 17, fontWeight: 600 }}>Add a grip-confirmation input on each GoFa</div>
        <div className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>{p.meaning}</div>
        <div className="kv" style={{ marginTop: 12 }}>
          <span className="k">Hardware</span><span>{p.hardware.split(/[.;]/)[0]}.</span>
          <span className="k">Rule on logs</span><span className="mono" style={{ fontSize: 12 }}>{s.verification.rule}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 14 }}>
          <div><div className="big-stat num" style={{ fontSize: 30 }}>{mg.flagged}/{mg.total}</div><div className="stat-label">real missed grasps caught</div></div>
          <div><div className="big-stat num" style={{ fontSize: 30 }}>{other[0]}/{other[1]}</div><div className="stat-label">other failures flagged</div></div>
          <div><div className="big-stat num" style={{ fontSize: 30 }}>{succ.flagged}/{succ.total}</div><div className="stat-label">“successes” flagged: the hidden re-grasp</div></div>
        </div>
        <button className={`approve ${approved ? "done" : ""}`} disabled={approved}
                onClick={() => { if (liveWaiting) onApprove?.(); setOk(true); }}>
          {approved ? `✓ Approved · wired as ${s.approval?.wired_as || "DI_GRIP_OK"}` : liveWaiting ? "Approve DI_GRIP_OK (live run is waiting)" : "Approve DI_GRIP_OK"}
        </button>
      </div>
    </div>
  );
}

export default function Evidence({ b, step, live, onApprove }) {
  const ev = b.evidence;
  const seekRef = useRef(() => {});
  useEffect(() => {
    const f = ev.flags.find((x) => x.type === "missed_grasp");
    if (step === 1 && f) setTimeout(() => seekRef.current(f.t - 2.0), 50);
  }, [step]);
  return (
    <div className="beat">
      <div className="beat-head">
        <div>
          <div className="eyebrow">02 · Evidence</div>
          <h2 className="headline">{step === 0 ? "Argon watched the whole shift, read the logs and the code at once." : "Missed grasps are what fail, and the legacy code never checks the grip."}</h2>
          <div className="subline">{step === 0 ? `${int(ev.tokens.total)} tokens in one context: what the camera saw, what the gripper measured and what the program commanded.` : "Argon proposes the fix in hardware first; the rule behind it is checked on every real episode before anyone approves it."}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.35fr 1fr", gap: 18, minHeight: 0 }}>
        <Footage ev={ev} setSeekRef={seekRef} />
        <div style={{ display: "grid", gridTemplateRows: step === 0 ? "auto minmax(0, 1fr)" : "minmax(0, 1fr) auto", gap: 18, minHeight: 0 }}>
          {step === 0 ? <><Tokens tk={ev.tokens} src={ev.source} /><Findings ev={ev} twinMiss={b.twin.single_silent} seek={(t) => seekRef.current(t)} /></>
                      : <><CodeCard ev={ev} /><SensorCard ev={ev} live={live} onApprove={onApprove} /></>}
        </div>
      </div>
    </div>
  );
}
