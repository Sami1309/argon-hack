import Clip from "../components/Clip.jsx";
import { media, pct } from "../lib.js";

const STEPS = [
  { pill: "The twin", eyebrow: "The digital twin",
    head: "Every program is tested in a MuJoCo twin of the cell first.",
    sub: "ABB robot models, the cell layout from CAD and the legacy targets, and both controllers’ I/O." },
  { pill: "Copy the code", eyebrow: "Option 1 · copy the code",
    head: "Copying the code fails: every target lands metres away.",
    sub: "The IRB controller used world base frames. The GoFa doesn’t. Same robtargets, different places." },
  { pill: "Argon’s port", eyebrow: "Option 2 · Argon’s single pass",
    head: "Argon’s port gets the geometry right…",
    sub: "One pass. The normal cycle delivers, and targets are within 1 mm of the engineer’s port." },
  { pill: "The catch", eyebrow: "The catch",
    head: "…and still ships the 15-year-old bug.",
    sub: "Inject the missed grasp seen on the real shift. The robot ‘places’ a tray it never picked up, then drops the parts on the bare belt." },
];
export const TWIN_STEPS = STEPS.map((s) => s.pill);

export default function Twin({ b, step }) {
  const t = b.twin, s = STEPS[step];
  const board = Object.fromEntries(b.proof.scoreboard.map((r) => [r.key, r]));
  const trials = b.single_pass_trials;
  const side = [
    <>
      <div className="chips"><span className="chip">robots: <strong>ABB URDF → MJCF</strong></span><span className="chip">reach checked vs datasheets</span>
        <span className="chip">RAPID interpreter: <strong>both tasks, live I/O</strong></span></div>
      <div className="muted" style={{ fontSize: 13.5, marginTop: 14 }}>Each scenario runs the full RAPID program: motion, grippers, conveyor, sensors, ERROR handlers.</div>
      <div style={{ marginTop: 14 }}><span className="label-tag">{b.meta.labels.geometry}</span></div>
    </>,
    <>
      <div className="big-stat num">{t.verbatim.unreachable}/{t.verbatim.moves}</div><div className="stat-label">moves unreachable on the GoFa</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>{(t.verbatim.target_err.mean_mm / 1000).toFixed(1)} m</div><div className="stat-label">mean target error vs the engineer’s port (max {(t.verbatim.target_err.max_mm / 1000).toFixed(1)} m)</div>
      <div className="legend" style={{ marginTop: 18 }}><span><i className="sw" style={{ background: "rgba(255,64,56,.6)", borderRadius: "50%" }} />where the copied targets land</span><span><i className="sw" style={{ background: "#d9e5f2", borderRadius: "50%" }} />where they should be</span></div>
    </>,
    <>
      <div className="big-stat num">{board.single?.target_err?.mean_mm ?? "–"} mm</div><div className="stat-label">mean target error vs. the engineer’s port ({board.single?.target_err?.n} targets)</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>✓</div><div className="stat-label">normal cycle delivered</div>
      <div className="muted" style={{ fontSize: 13, marginTop: 18 }}>{trials.length} single passes: {trials.map((x) => pct(x.cpr)).join(", ")}.{trials.some((x) => !x.nominal) ? " The 0% one has a frame sign error. The loop starts there." : ""}</div>
    </>,
    <>
      <div className="big-stat num">{pct(board.single?.cpr)}</div><div className="stat-label">Cell Pass Rate: only the normal cycle passes</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>{board.single?.fault_pass}/{board.single?.faults}</div><div className="stat-label">faults handled, same as legacy and the engineer’s port</div>
      <div style={{ marginTop: 18 }}><span className="label-tag">{b.meta.labels.sim_fault}</span></div>
    </>,
  ][step];
  const clip = [null, t.verbatim_ghosts, t.single_nominal, t.single_silent][step];
  return (
    <div className="beat">
      <div className="beat-head"><div><div className="eyebrow">03 · Twin · {s.eyebrow}</div><h2 className="headline">{s.head}</h2><div className="subline">{s.sub}</div></div></div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 18, minHeight: 0 }}>
        {step === 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, minHeight: 0, alignContent: "center" }}>
            <div className="clip cover" style={{ aspectRatio: "16/10" }}><img src={media(t.reference_images?.[0])} alt="RobotStudio reference station" style={{ objectFit: "cover" }} /><div className="tags"><span className="label-tag">reference · RobotStudio station (GoFa version)</span></div></div>
            <Clip src={t.single_nominal} controls={false} className="cover" style={{ aspectRatio: "16/10" }} tags={["the twin · MuJoCo · same cell, same robots"]} rate={1.5} />
          </div>
        ) : (
          <Clip key={clip} src={clip} events={clip?.replace(".mp4", ".events.json")} rate={step === 2 ? 1.6 : 1}
                tags={[["", "verbatim legacy RAPID @ GoFa", "Argon single pass @ GoFa · normal cycle", "Argon single pass @ GoFa · R1 misses the tray once"][step]].concat(step === 3 ? [b.meta.labels.sim_fault] : [])} />
        )}
        <div className="panel"><div className="panel-body">{side}</div></div>
      </div>
    </div>
  );
}
