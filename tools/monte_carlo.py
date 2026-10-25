"""Monte Carlo shift: seeded cycles with an independent per-grasp miss probability at every grip.

    python tools/monte_carlo.py --run runs/loop_final_d --single runs/single_pass_X/trial1/iter00 -> runs/mc_<ts>/mc.json
p = 6% is the missed-grasp rate Stage 1 measured on real teleoperated footage (a different cell); 1% is a mature cell.
Per iteration of the loop run (kept programs) a smaller n shows the good-box rate climbing with the Cell Pass Rate.
"""
import argparse, functools, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop.run_loop import load_prog  # noqa: E402
from loop.score import human_port_programs, human_port_bases  # noqa: E402
from simulation.cell import irb_cell, gofa_cell  # noqa: E402
from simulation.scenarios import legacy_programs, monte_carlo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True); ap.add_argument("--single", required=True)
    ap.add_argument("--n", type=int, default=1000); ap.add_argument("--n-iter", type=int, default=300)
    a = ap.parse_args()
    run = pathlib.Path(a.run)
    metrics = json.loads((run / "metrics.json").read_text())
    final = max(m["iter"] for m in metrics if m["kept"])
    out = ROOT / f"runs/mc_{time.strftime('%Y%m%d_%H%M%S')}"; out.mkdir(parents=True)
    res = dict(run=str(run), single=a.single, n=a.n, n_iter=a.n_iter, per_iteration=[], programs={})
    log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)
    prog = None
    for m in metrics:  # the program in force after each iteration
        d = run / f"iter{m['iter']:02d}"
        if m["kept"]: prog = load_prog(d)
        r = monte_carlo(prog, gofa_cell, 0.06, n=a.n_iter, seed0=10_000)
        res["per_iteration"].append(dict(iter=m["iter"], **r)); log("iter", m["iter"], r)
        (out / "mc.json").write_text(json.dumps(res, indent=1))
    cols = {"legacy @ IRB 1200": (legacy_programs(), irb_cell),
            "verbatim copy @ GoFa": (legacy_programs(), gofa_cell),
            "Argon single pass": (load_prog(a.single), gofa_cell),
            "Argon looped": (load_prog(run / f"iter{final:02d}"), gofa_cell),
            "human port (held out)": (human_port_programs(), functools.partial(gofa_cell, human_port_bases()))}
    for p in (0.06, 0.01):
        for name, (pg, fn) in cols.items():
            r = monte_carlo(pg, fn, p, n=a.n, seed0=0)
            res["programs"].setdefault(name, {})[f"{p:g}"] = r; log(name, p, r)
            (out / "mc.json").write_text(json.dumps(res, indent=1))
    log("->", out / "mc.json")


if __name__ == "__main__":
    main()
