"""Commission one RAPID program on the twin: training suite, held-out suite, seeded Monte Carlo, optional proof clip.

Runs unchanged in a Managed Agent sandbox (against a clone of the public repo at a pinned commit) and locally (against
`git archive` of the same commit), so the two results can be compared number for number.

    python tools/commission.py --repo <checkout> --program <dir with R1/R2_{CalibData,Module1}.mod> --cell gofa \
        --mc 200 --p 0.06 --out <dir> [--clip]
"""
import argparse, json, pathlib, sys, time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--program", required=True)
    ap.add_argument("--cell", choices=["irb", "gofa"], required=True)
    ap.add_argument("--mc", type=int, default=200)
    ap.add_argument("--p", type=float, default=0.06)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--clip", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, a.repo)
    from simulation.cell import irb_cell, gofa_cell
    from simulation.scenarios import SUITE, HELD_OUT, run_suite, run_scenario, monte_carlo

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    P = pathlib.Path(a.program)
    prog = {r: [(P / f"{r}_{f}").read_text() for f in ("CalibData.mod", "Module1.mod")] for r in ("R1", "R2")}
    cell = irb_cell if a.cell == "irb" else gofa_cell
    t = time.time()
    s = run_suite(prog, cell, verbose=False)
    h = run_suite(prog, cell, suite=HELD_OUT, verbose=False)
    t_suites = time.time() - t
    t = time.time()
    mc = monte_carlo(prog, cell, a.p, n=a.mc, seed0=0, workers=a.workers)
    t_mc = time.time() - t
    brief = lambda rows: [dict(id=r["id"], passed=bool(r["passed"]), why=r["why"]) for r in rows]
    res = dict(cell=a.cell, cpr=s["cpr"], heldout=h["cpr"], nominal=bool(s["nominal"][0]), fault_pass=s["fault_pass"],
               violations=s["violations"], rows=brief(s["rows"]), heldout_rows=brief(h["rows"]), monte_carlo=mc,
               timing_s=dict(suites=round(t_suites, 1), monte_carlo=round(t_mc, 1)), clip_path=None, clip_error=None)
    if a.clip:
        try:
            import imageio
            from simulation.render import Renderer
            sc = next(x for x in SUITE if x["id"] == "r1_tray_miss_once")
            w, _, r = run_scenario(prog, cell, sc)
            ev = next((e for e in w.events if e["kind"] == "attach" and e.get("to") == "R1"), None)
            t0 = max(0.0, (ev["t"] if ev else 0.0) - 3.0)
            rr = Renderer(w)
            frames = [rr.frame(snap, "r1_close") for snap in w.snapshots[::3] if t0 <= snap["t"] <= t0 + 12.0]
            rr.close()
            clip = out / "proof_r1_tray_miss_once.mp4"
            imageio.mimwrite(clip, frames, fps=5, quality=7, macro_block_size=1)
            res["clip_path"] = str(clip)
        except Exception as e:  # recorded honestly, never faked
            res["clip_error"] = f"{type(e).__name__}: {e}"[:600]
    (out / "results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "heldout_rows")}))


if __name__ == "__main__":
    main()
