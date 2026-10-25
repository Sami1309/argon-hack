import Clip from "../components/Clip.jsx";

export default function Problem({ b }) {
  const p = b.persona;
  return (
    <div className="beat" style={{ padding: 0, gridTemplateRows: "1fr" }}>
      <div style={{ position: "relative", minHeight: 0 }}>
        <Clip src={b.twin.hero_legacy} poster={b.twin.hero_legacy?.replace(".mp4", ".jpg")} controls={false} className="cover" style={{ position: "absolute", inset: 0, borderRadius: 0 }}
              rightTags={["legacy RAPID · ABB IRB 1200 × 2 · digital twin"]} />
        <div className="fade-bottom" />
        <div style={{ position: "absolute", left: 56, right: 56, bottom: 52 }}>
          <div className="eyebrow">01 · The problem</div>
          <h1 className="hero-title">This cell has to run on new cobots by Monday.</h1>
          <div className="hero-sub">
            A {p.role.toLowerCase()} must replace two ABB IRB 1200s running 15-year-old RAPID with ABB GoFa cobots. The old program has
            never run anywhere but this cell, and the line can’t stop for weeks of commissioning.
          </div>
          <div className="chips" style={{ marginTop: 22 }}>
            <span className="chip">Argon gets <strong>19 min of shift footage</strong></span>
            <span className="chip"><strong>218 robot logs</strong></span>
            <span className="chip"><strong>the legacy RAPID + PLC code</strong></span>
            <span className="chip">and returns a <strong>commissioned GoFa program</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}
