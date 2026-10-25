export const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
export const int = (v) => (v == null ? "–" : Number(v).toLocaleString("en-US"));
export const sec = (v, d = 1) => (v == null ? "–" : `${Number(v).toFixed(d)} s`);
export const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
export const media = (p) => (!p ? null : p.startsWith("/") ? p : `/bundle/${p}`);

// short, human label for a loop iteration (from what Argon patched and why)
export function itLabel(it) {
  if (!it) return "";
  if (it.kind === "single_pass" || it.iter === 0) return "single-pass port";
  const p = it.patch || {};
  const rc = (it.root_cause || "").toLowerCase();
  const what = /uframe|wobj|frame/.test(rc) ? "frame fix"
    : /holder|\bbh\b/.test(rc) && p.task === "R2" ? "holder grip check"
    : /tray/.test(rc) ? "tray grip check"
    : /part|obj/.test(rc) ? "part grip check"
    : /grip/.test(rc) ? "grip check" : p.routine || "patch";
  return `${p.task || ""} ${what}`.trim();
}

export const SCEN = {
  nominal: "normal cycle",
  r1_tray_miss_once: "R1 misses tray once",
  r1_tray_miss_always: "R1 tray never grips",
  r1_part_miss_once: "R1 misses part once",
  r1_part_miss_always: "R1 part never grips",
  r1_part_displaced_20mm: "R1 part 20 mm off",
  r2_tray_miss_once: "R2 misses tray once",
  r2_tray_miss_always: "R2 tray never grips",
  r2_holder_miss_once: "R2 misses holder once",
  r2_holder_miss_always: "R2 holder never grips",
  r1_second_part_miss: "R1 misses 2nd part",
  r1_tray_miss_twice: "R1 misses tray twice",
  r2_tray_displaced_20mm: "tray lands 20 mm off",
  "late_grip_sensor_0.4s": "grip sensor 0.4 s late",
  both_robots_miss_once: "both robots miss once",
};
export const scen = (id) => SCEN[id] || id;

// RAPID tokenizer for light highlighting
const KW = new Set("PROC ENDPROC FUNC ENDFUNC TRAP ENDTRAP IF THEN ELSE ELSEIF ENDIF WHILE DO ENDWHILE FOR FROM TO ENDFOR TEST CASE DEFAULT ENDTEST ERROR RETRY TRYNEXT RAISE RETURN EXIT VAR PERS CONST LOCAL TASK MODULE ENDMODULE AND OR NOT TRUE FALSE".split(" "));
const INS = new Set("MoveL MoveJ MoveAbsJ MoveC PulseDO SetDO Set Reset WaitDI WaitDO WaitTime WaitUntil ErrWrite TPWrite Stop Offs ConfJ ConfL SingArea".split(" "));
const RE = /(!.*$)|("(?:[^"\\]|\\.)*")|(\b[A-Za-z_]\w*\b)|(-?\b\d+(?:\.\d+)?(?:E[+-]?\d+)?\b)|(\s+|.)/g;
export function tokens(line) {
  const out = [];
  let m;
  RE.lastIndex = 0;
  while ((m = RE.exec(line))) {
    if (m[1]) out.push(["cm", m[1]]);
    else if (m[2]) out.push(["str", m[2]]);
    else if (m[3]) out.push([KW.has(m[3]) ? "kw" : INS.has(m[3]) ? "ins" : /^(DI|DO)_/.test(m[3]) ? "sig" : "", m[3]]);
    else if (m[4]) out.push(["num", m[4]]);
    else out.push(["", m[5]]);
    if (m[0] === "") RE.lastIndex++;
  }
  return out;
}

export async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
