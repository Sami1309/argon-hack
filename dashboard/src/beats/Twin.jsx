import Clip from "../components/Clip.jsx";
import { media, pct } from "../lib.js";

const STEPS = [
  { pill: "The twin", eyebrow: "The digital twin",
    head: "Argon commissions in a MuJoCo twin of the cell before anything touches the floor.",
    sub: "ABB’s own robot models (IRB 1200 and GoFa CRB 15000), the cell from the CAD bounding boxes and the legacy targets, and the two controllers’ I/O as smart components." },
  { pill: "Copy the code", eyebrow: "Option 1 · copy the code",
    head: "Copying the code fails: every target lands metres away.",
    sub: "The IRB controller had world base frames configured; the GoFa has none. The same robtargets now mean a different place." },
  { pill: "Argon’s port", eyebrow: "Option 2 · Argon’s single pass",
    head: "Argon’s port gets the geometry right…",
    sub: "One pass over the legacy RAPID and the cell facts. The normal cycle delivers, with targets within a millimetre of the engineer’s own port." },
  { pill: "The catch", eyebrow: "The catch",
    head: "…and still ships the 15-year-old bug.",
    sub: "Inject the failure Stage 1 saw on the real shift. The port carries on as if it held the tray: it ‘places’ nothing on the belt and drops the parts on bare conveyor." },
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
      <div className="muted" style={{ fontSize: 13.5, marginTop: 14 }}>Every scenario is a full run of the real RAPID program on this twin: motion, grippers, conveyor, sensors and ERROR handlers.</div>
      <div style={{ marginTop: 14 }}><span className="label-tag">{b.meta.labels.geometry}</span></div>
    </>,
    <>
      <div className="big-stat num">{t.verbatim.unreachable}/{t.verbatim.moves}</div><div className="stat-label">moves unreachable on the GoFa</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>{(t.verbatim.target_err.mean_mm / 1000).toFixed(1)} m</div><div className="stat-label">mean target error vs the engineer’s port (max {(t.verbatim.target_err.max_mm / 1000).toFixed(1)} m)</div>
      <div className="legend" style={{ marginTop: 18 }}><span><i className="sw" style={{ background: "rgba(255,64,56,.6)", borderRadius: "50%" }} />where the copied targets land</span><span><i className="sw" style={{ background: "#d9e5f2", borderRadius: "50%" }} />where they should be</span></div>
    </>,
    <>
      <div className="big-stat num">{board.single?.target_err?.mean_mm ?? "–"} mm</div><div className="stat-label">mean target error vs the engineer’s port, measured in the twin ({board.single?.target_err?.n} targets)</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>✓</div><div className="stat-label">normal cycle delivered: tray, two parts and the holder in the box</div>
      <div className="muted" style={{ fontSize: 13, marginTop: 18 }}>Repeatability: {trials.length} independent single passes scored {trials.map((x) => pct(x.cpr)).join(", ")}. {trials.some((x) => !x.nominal) ? "One shipped a frame sign error — the loop beat starts from that one." : ""}</div>
    </>,
    <>
      <div className="big-stat num">{pct(board.single?.cpr)}</div><div className="stat-label">Cell Pass Rate: only the normal cycle passes</div>
      <div className="big-stat num" style={{ marginTop: 18 }}>{board.single?.fault_pass}/{board.single?.faults}</div><div className="stat-label">fault scenarios handled; the same as the legacy program and the engineer’s port</div>
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
