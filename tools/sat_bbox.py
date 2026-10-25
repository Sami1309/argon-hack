"""Bounding boxes of the ACIS SAT (v7 text) cell CAD files, from their `point` records -> derived/sat_bboxes.json (mm)."""
import json, pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
SAT = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Project_Materials/.sat"
NUM = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
out = {}
for f in sorted(SAT.glob("*.sat")):
    pts = [tuple(map(float, m.groups())) for m in re.finditer(rf"^point \$-?\d+ -?\d+ \$-?\d+ {NUM} {NUM} {NUM} #", f.read_text(), re.M)]
    lo = [min(p[i] for p in pts) for i in range(3)]; hi = [max(p[i] for p in pts) for i in range(3)]
    out[f.stem] = dict(points=len(pts), min=lo, max=hi, size=[h - l for h, l in zip(hi, lo)])
(ROOT / "derived").mkdir(exist_ok=True)
(ROOT / "derived/sat_bboxes.json").write_text(json.dumps(out, indent=1))
for k, v in out.items(): print(f"{k:10s} pts={v['points']:4d} size_mm={[round(x, 1) for x in v['size']]} min={[round(x, 1) for x in v['min']]}")
