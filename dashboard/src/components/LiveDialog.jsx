export default function LiveDialog({ onStart, onClose, busy }) {
  return (
    <div className="scrim" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="eyebrow">Run it live</div>
        <div style={{ fontSize: 22, fontWeight: 650 }}>Real Argon calls, real twin runs, nothing replayed.</div>
        <div className="muted" style={{ marginTop: 6, fontSize: 14 }}>If a call fails or times out, the dashboard falls back to the recorded run and says so.</div>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "loop", start: "buggy" })}>
          <div className="t">Live loop from the 0% port · ~2.5 min</div>
          <div className="d">Starts from the cached single pass that shipped a frame sign error. Argon has to find it from the clip, then the grip bugs.</div>
        </button>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "loop", start: "clean" })}>
          <div className="t">Live loop from the 10% port · ~1.5 min</div>
          <div className="d">Starts from the clean single pass: geometry right, open-loop grips.</div>
        </button>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "full", start: "buggy" })}>
          <div className="t">Full pipeline · ~6 min</div>
          <div className="d">Stage 1 on the 19-minute shift (~755K tokens) → sensor proposal → your approval → single-pass port → loop.</div>
        </button>
        <div style={{ textAlign: "right", marginTop: 14 }}><button className="icon-btn" onClick={onClose}>Cancel <kbd>Esc</kbd></button></div>
      </div>
    </div>
  );
}
