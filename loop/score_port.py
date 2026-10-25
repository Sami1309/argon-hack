"""Held-out score: compare a ported T_ROB1 Module1.mod to the human GoFa port. ONLY this script reads the answer key."""
import sys, re, json, pathlib, numpy as np
ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Solution_CRB_15000_GoFa/Rapid/Controller1/T_ROB1/Module1.mod"
RT = re.compile(r"robtarget\s+(\w+)\s*:=\s*\[\[([^\]]+)\],\[([^\]]+)\],\[([^\]]+)\]")
def targets(src):
    return {m[1]: (np.array(m[2].split(","), float), np.array(m[3].split(","), float), m[4].replace(" ", "")) for m in RT.finditer(src)}
def num(src, name):
    m = re.search(rf"{name}\s*:=\s*(-?[\d.]+)", src); return float(m[1]) if m else None
cand, key = pathlib.Path(sys.argv[1]).read_text(), KEY.read_text()
C, K = targets(cand), targets(key)
rows, errs = [], []
for n in K:
    if n not in C: rows.append(f"  {n:18s} MISSING"); continue
    e = float(np.linalg.norm(C[n][0] - K[n][0])); errs.append(e)
    qd = min(np.linalg.norm(C[n][1] - K[n][1]), np.linalg.norm(C[n][1] + K[n][1]))
    rows.append(f"  {n:18s} pos_err={e:9.2f} mm  quat_match={qd < 1e-3}  conf cand={C[n][2]} key={K[n][2]}")
print("\n".join(rows))
print(f"mean pos err (common targets): {np.mean(errs):.2f} mm" if errs else "no common targets")
def has_movej(src, tgt): return bool(re.search(rf"MoveJ\s+Offs\({tgt},[^;]*,200\)", src))
checks = {
  "HOME added": "Target_HOME" in cand,
  "tAB_offset_x/y swapped (87.5 / 300)": (num(cand, r"tAB_offset_x"), num(cand, r"tAB_offset_y")) == (87.5, 300.00021478) or (num(cand, r"tAB_offset_x"), num(cand, r"tAB_offset_y")) == (87.5, 300.0),
  "conveyor offset moved to X": bool(re.search(r"Offs\(Target_CONV_PR,\s*(0\s*\+\s*)?offset_C_\w+\s*,\s*0\s*,", cand)),
  "MoveJ approach Target_TAB+200": has_movej(cand, "Target_TAB"),
  "MoveJ approach Target_INIT_AP1+200": has_movej(cand, "Target_INIT_AP1"),
  "MoveJ approach Target_CONV_PR+200": has_movej(cand, "Target_CONV_PR"),
}
for k, v in checks.items(): print(f"  [{'x' if v else ' '}] {k}")
print(f"structural matches: {sum(checks.values())}/{len(checks)}")
