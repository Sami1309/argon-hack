export default function LiveDialog({ onStart, onClose, busy }) {
  return (
    <div className="scrim" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="eyebrow">Run it live</div>
        <div style={{ fontSize: 22, fontWeight: 650 }}>Real Argon calls and twin runs.</div>
        <div className="muted" style={{ marginTop: 6, fontSize: 14 }}>On failure the dashboard falls back to the recorded run.</div>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "loop", start: "buggy" })}>
          <div className="t">Loop from the 0% port · ~2.5 min</div>
          <div className="d">Cached single pass with a frame sign error. Argon fixes the frames, then the grips.</div>
        </button>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "loop", start: "clean" })}>
          <div className="t">Loop from the 10% port · ~1.5 min</div>
          <div className="d">Cached single pass with correct geometry and open-loop grips.</div>
        </button>
        <button className="choice" disabled={busy} onClick={() => onStart({ mode: "full", start: "buggy" })}>
          <div className="t">Full pipeline · ~6 min</div>
          <div className="d">Stage 1 on the shift (~755K tokens) → sensor proposal → your approval → single pass → loop.</div>
        </button>
        <div style={{ textAlign: "right", marginTop: 14 }}><button className="icon-btn" onClick={onClose}>Cancel <kbd>Esc</kbd></button></div>
      </div>
    </div>
  );
}
