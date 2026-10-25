import { useEffect, useRef } from "react";
import { tokens } from "../lib.js";

const Line = ({ text }) => <span className="t">{tokens(text).map(([k, s], i) => (k ? <span key={i} className={`tk-${k}`}>{s}</span> : s))}</span>;

/* Source view: lines [from..to] (1-based) with lit lines; scrolls the first lit line into view. */
export function Source({ lines, from = 1, to, lit = [], dimOutside = [] }) {
  const ref = useRef(null);
  const end = Math.min(to || lines.length, lines.length);
  useEffect(() => { ref.current?.querySelector(".lit")?.scrollIntoView({ block: "center" }); }, [lines, from, lit.join()]);
  const out = [];
  for (let n = Math.max(1, from); n <= end; n++) {
    const dim = dimOutside.length === 2 && (n < dimOutside[0] || n > dimOutside[1]);
    out.push(<div key={n} className={`ln ${lit.includes(n) ? "lit" : ""} ${dim ? "dim" : ""}`}><span className="n">{n}</span><span className="op" /><Line text={lines[n - 1].replace(/\t/g, "    ")} /></div>);
  }
  return <div className="code" ref={ref}>{out}</div>;
}

/* Diff of one routine: +/- lines; unchanged runs longer than 2*ctx collapse to a fold marker. */
export function Diff({ diff, ctx = 2 }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.querySelector(".add,.del")?.scrollIntoView({ block: "start" }); }, [diff]);
  if (!diff?.length) return <div className="faint" style={{ padding: 16 }}>no change</div>;
  const keep = diff.map((d, i) => d.op !== " " || diff.slice(Math.max(0, i - ctx), i + ctx + 1).some((x) => x.op !== " "));
  const rows = [];
  let n = 0;
  diff.forEach((d, i) => {
    if (d.op !== "+") n += 1;
    if (!keep[i]) { if (rows.length && rows[rows.length - 1].fold) rows[rows.length - 1].count++; else rows.push({ fold: true, count: 1 }); return; }
    rows.push({ ...d, n: d.op === "+" ? "" : n });
  });
  return (
    <div className="code" ref={ref}>
      {rows.map((r, i) => r.fold
        ? <div key={i} className="ln"><span className="n" /><span className="op">⋯</span><span className="t faint">{r.count} unchanged lines</span></div>
        : <div key={i} className={`ln ${r.op === "+" ? "add" : r.op === "-" ? "del" : ""}`}><span className="n">{r.n}</span><span className="op">{r.op === " " ? "" : r.op}</span><Line text={r.text} /></div>)}
    </div>
  );
}
