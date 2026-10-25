import { useEffect, useRef, useState } from "react";
import { getJSON, media } from "../lib.js";

/* A video with crisp event captions (from the render's events sidecar), labels, and pins on its timeline.
   pins: [{t, kind: "argon" | "truth" | "mark", color, title}] in clip seconds. */
export default function Clip({ src, events, tags = [], rightTags = [], pins = [], autoPlay = true, loop = true, rate = 1,
                               onTime, seekTo, poster, style, className = "", captionMax = 2, controls = true, videoRef }) {
  const ref = useRef(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [side, setSide] = useState(null);
  useEffect(() => {
    setSide(null);
    if (!events) return;
    if (typeof events === "string") getJSON(media(events)).then(setSide).catch(() => setSide(null));
    else setSide({ events });
  }, [events]);
  useEffect(() => { if (ref.current) ref.current.playbackRate = rate; }, [rate, src]);
  useEffect(() => { if (seekTo && ref.current && seekTo.t != null) { ref.current.currentTime = seekTo.t; ref.current.play?.().catch(() => {}); } }, [seekTo]);
  useEffect(() => { if (videoRef) videoRef.current = ref.current; });
  const evs = (side?.events || []).filter((e) => e.t <= t + 0.05 && t - e.t < 2.6).slice(-captionMax);
  const seek = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const u = Math.min(1, Math.max(0, (e.clientX - r.left - 14) / (r.width - 28)));
    if (ref.current && dur) ref.current.currentTime = u * dur;
  };
  return (
    <div className={`clip ${className}`} style={style}>
      {src ? (
        <video ref={ref} src={media(src)} poster={poster ? media(poster) : undefined} autoPlay={autoPlay} loop={loop} muted playsInline preload="auto"
               onTimeUpdate={(e) => { setT(e.target.currentTime); onTime?.(e.target.currentTime); }}
               onLoadedMetadata={(e) => { setDur(e.target.duration); e.target.playbackRate = rate; }} />
      ) : <div className="faint" style={{ padding: 40 }}>clip not rendered yet</div>}
      {tags.length > 0 && <div className="tags">{tags.map((x) => <span key={x} className="label-tag">{x}</span>)}</div>}
      {rightTags.length > 0 && <div className="tags right">{rightTags.map((x) => <span key={x} className="label-tag">{x}</span>)}</div>}
      <div className="caption">{evs.map((e, i) => <div key={`${e.t}-${i}`} className={`ev ${e.level}`}><i />{e.text}</div>)}</div>
      {controls && (
        <div className="timeline" onClick={seek}>
          <div className="track">
            <div className="fill" style={{ width: dur ? `${(100 * t) / dur}%` : 0 }} />
            {dur > 0 && pins.map((p, i) => (
              <div key={i} className={`pin ${p.kind || "mark"}`} title={p.title}
                   style={{ left: `${Math.min(100, (100 * p.t) / dur)}%`, background: p.color }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
