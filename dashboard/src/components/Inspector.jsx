import { useState } from "react";
import { Source } from "./Code.jsx";
import { int, sec } from "../lib.js";

export default function Inspector({ b, onClose }) {
  const [tab, setTab] = useState("calls");
  const total = b.calls.reduce((a, c) => a + (c.usage?.total_token_count || 0), 0);
  return (
    <div className="drawer">
      <div className="panel-head" style={{ padding: "14px 18px" }}>
        <div className="seg">{[["calls", `Argon calls (${b.calls.length})`], ["inputs", "Inputs"], ["bundle", "Provenance"]].map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>
        <button className="icon-btn" onClick={onClose}>Close <kbd>I</kbd></button>
      </div>
      <div className="panel-body" style={{ flex: 1 }}>
        {tab === "calls" && (
          <>
            <div className="muted" style={{ fontSize: 13, marginBottom: 12 }}>Every Argon call behind this demo: what went in (by source), tokens by modality, latency. {int(total)} tokens in total. Each call passed the answer-key quarantine (no engineer’s-port paths or target literals).</div>
            {b.calls.map((c, i) => {
              const mods = c.usage?.prompt_tokens_details || [];
              return (
                <div key={i} className="call">
                  <div className="row"><strong>{c.label}</strong><span className="num muted">{sec(c.latency_s)} · {int(c.usage?.total_token_count)} tok</span></div>
                  <div className="muted" style={{ fontSize: 12.5 }}>{c.what}{c.run ? ` · ${c.run}` : ""}{c.thinking ? ` · thinking ${c.thinking}` : ""}</div>
                  <div className="chips" style={{ marginTop: 6 }}>{mods.map((m) => <span key={m.modality} className="chip num">{m.modality.toLowerCase()} {int(m.token_count)}</span>)}</div>
                  <div style={{ marginTop: 6, fontSize: 12 }} className="faint">{(c.parts || []).map((p) => `${p.kind}: ${p.source}`).join(" · ")}</div>
                </div>
              );
            })}
          </>
        )}
        {tab === "inputs" && (
          <>
            <div className="panel-title" style={{ marginBottom: 8 }}>Cell facts given to Argon</div>
            <pre className="code" style={{ whiteSpace: "pre-wrap", fontSize: 12, color: "var(--text-2)" }}>{b.cell_facts}</pre>
            <div className="panel-title" style={{ margin: "16px 0 8px" }}>Legacy RAPID · T_ROB1/Module1.mod</div>
            <Source lines={b.evidence.code.R1.lines} lit={b.evidence.code.R1.lit} />
          </>
        )}
        {tab === "bundle" && (
          <div className="kv">
            <span className="k">Built</span><span>{b.meta.built_at} · git {b.meta.git}</span>
            <span className="k">Primary run</span><span className="mono">{b.meta.primary_run}</span>
            <span className="k">Monte Carlo</span><span className="mono">{b.meta.mc}</span>
            <span className="k">Model</span><span className="mono">{b.meta.model}</span>
            <span className="k">Labels</span><span>{Object.values(b.meta.labels).join(" · ")}</span>
            <span className="k">Manifest</span><span><a href="/bundle/manifest.json" target="_blank" rel="noreferrer">manifest.json</a> (every asset: producer, sha256, measured / reference)</span>
          </div>
        )}
      </div>
    </div>
  );
}
