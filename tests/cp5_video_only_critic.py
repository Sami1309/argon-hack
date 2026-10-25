"""CP5: does Argon diagnose twin failures from PIXELS alone? (no overlay text, no trace, no suite table)

8 clips of the single-pass program on the GoFa twin: the 4 missed-grasp scenarios + the same 4 grips succeeding
(controls). Clip start offsets are randomized. Scored against the twin's ground-truth events.
"""
import json, pathlib, sys, concurrent.futures as cf
import numpy as np
import imageio

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client  # noqa: E402
from simulation.cell import gofa_cell  # noqa: E402
from simulation.scenarios import SUITE, run_scenario  # noqa: E402
from simulation.render import Renderer  # noqa: E402

CELL = ("Digital twin of a two-robot sorting cell (white ABB GoFa cobots). Robot 1 (left work table) vacuum-picks a brown tray "
        "and puts it on the black conveyor, then vacuum-picks small coloured tiles from a white holder plate onto the tray. "
        "Robot 2 (right work table) grips the tray at the conveyor end with two fingers and places it into an open cardboard box, "
        "then vacuum-picks a grey plate and places it on the box.")
Q = ("Watch the clip. Did a pick (grasp) fail in this clip - i.e. the robot lifts away without the object? If yes: when (clip "
     "seconds), which object, and what does the robot do afterwards (does it continue as if holding it?). Answer only from what you see.")
SCHEMA = {"type": "object", "properties": {
    "grasp_failed": {"type": "boolean"}, "failure_time_s": {"type": "number"}, "object": {"type": "string"},
    "afterwards": {"type": "string"}, "evidence": {"type": "string"}},
    "required": ["grasp_failed", "failure_time_s", "object", "afterwards", "evidence"]}
STEPS = {"r1_tray_miss_once": ("R1", "TRAY", "r1_close"), "r1_part_miss_once": ("R1", "AP3", "r1_close"),
         "r2_tray_miss_once": ("R2", "TRAY", "r2_close"), "r2_holder_miss_once": ("R2", "BH", "r2_close")}


def clip(prog, sc_id, faulty, out, rng):
    robot, obj, cam = STEPS[sc_id]
    sc = next(s for s in SUITE if s["id"] == (sc_id if faulty else "nominal"))
    w, _, _ = run_scenario(prog, gofa_cell, sc)
    ev = next(e for e in w.events if e["kind"] == "attach" and e["obj"] == obj and e["to"] == robot)
    t0 = max(0.0, ev["t"] - rng.uniform(1.5, 4.5)); t1 = t0 + 8.0
    rr = Renderer(w)
    frames = [rr.frame(s, cam) for s in w.snapshots[::3] if t0 <= s["t"] <= t1]  # no overlay text
    rr.close()
    imageio.mimwrite(out, frames, fps=5, quality=7, macro_block_size=1)
    return dict(id=f"{sc_id}{'' if faulty else '__control'}", faulty=faulty, object=obj, true_t=round(ev["t"] - t0, 2), path=out)


def ask(c, run_dir):
    parts = [dict(kind="text", data=CELL, source="cell description"),
             dict(kind="video", data=pathlib.Path(c["path"]).read_bytes(), source=f"twin render, no overlays: {pathlib.Path(c['path']).name}"),
             dict(kind="text", data=Q, source="question")]
    out, meta = argon_client.call(parts, label=c["id"], run_dir=run_dir, schema=SCHEMA, thinking="low")
    return c, out, meta


if __name__ == "__main__":
    run_dir = pathlib.Path(sys.argv[1]); out_dir = ROOT / "runs/cp5"; out_dir.mkdir(parents=True, exist_ok=True)
    prog = {r: [(run_dir / "iter00" / f"{r}_{f}").read_text() for f in ("CalibData.mod", "Module1.mod")] for r in ("R1", "R2")}
    rng = np.random.default_rng(7)
    clips = [clip(prog, sid, faulty, out_dir / f"{sid}_{'fault' if faulty else 'control'}.mp4", rng)
             for sid in STEPS for faulty in (True, False)]
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: ask(c, out_dir), clips))
    rows, correct = [], 0
    for c, o, m in results:
        ok = o["grasp_failed"] == c["faulty"]
        terr = abs(o["failure_time_s"] - c["true_t"]) if c["faulty"] and o["grasp_failed"] else None
        correct += ok
        rows.append(dict(clip=c["id"], truth="missed grasp" if c["faulty"] else "grasp ok", argon=o["grasp_failed"], correct=ok,
                         true_t=c["true_t"], argon_t=o["failure_time_s"], t_err=terr, object=o["object"], afterwards=o["afterwards"],
                         latency_s=m["latency_s"]))
        print(f"{'OK ' if ok else 'BAD'} {c['id']:34s} truth={'FAIL' if c['faulty'] else 'ok  '} argon={'FAIL' if o['grasp_failed'] else 'ok  '}"
              f" t_true={c['true_t']:4.1f} t_argon={o['failure_time_s']:4.1f}  obj={o['object'][:22]:22s} | {o['afterwards'][:70]}")
    print(f"\nvideo-only accuracy: {correct}/{len(rows)}")
    (out_dir / "results.json").write_text(json.dumps(rows, indent=1))
