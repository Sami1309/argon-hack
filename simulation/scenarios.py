"""Scenario suite + evaluation for Twin A (the port loop's Cell Pass Rate).

Fault scenarios mirror the failure modes Stage 1 mined from the real footage (missed grasp, displaced part),
applied to each open-loop grip in the cell. All fault injection is simulation-only.
"""
import json, pathlib
import numpy as np

from simulation.cell import World, irb_cell, gofa_cell, run_cell

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGACY = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Solution_IRB_1200/Rapid"
ORACLE = ROOT / "derived/oracle.json"
DELIVER_TOL_MM = 10.0

SUITE = [
    dict(id="nominal", kind="nominal"),
    dict(id="r1_tray_miss_once", kind="once", faults={"R1_TAB": "once"}, robot="R1"),
    dict(id="r1_tray_miss_always", kind="always", faults={"R1_TAB": "always"}, robot="R1"),
    dict(id="r1_part_miss_once", kind="once", faults={"R1_PART": "once"}, robot="R1"),
    dict(id="r1_part_miss_always", kind="always", faults={"R1_PART": "always"}, robot="R1"),
    dict(id="r1_part_displaced_20mm", kind="always", displace=("AP3", (20.0, 0.0, 0.0)), robot="R1"),
    dict(id="r2_tray_miss_once", kind="once", faults={"R2_TTAB": "once"}, robot="R2"),
    dict(id="r2_tray_miss_always", kind="always", faults={"R2_TTAB": "always"}, robot="R2"),
    dict(id="r2_holder_miss_once", kind="once", faults={"R2_BH": "once"}, robot="R2"),
    dict(id="r2_holder_miss_always", kind="always", faults={"R2_BH": "always"}, robot="R2"),
]

# Held-out robustness suite: NEVER shown to Argon and never used in the keep/revert decision. Scored per iteration
# only to show whether the loop's patches generalise beyond the scenarios it optimised on.
HELD_OUT = [
    dict(id="r1_second_part_miss", kind="once", faults={"R1_PART": [1]}, robot="R1"),
    dict(id="r1_tray_miss_twice", kind="safe", faults={"R1_TAB": [0, 1]}, robot="R1"),
    dict(id="r2_tray_displaced_20mm", kind="always", tray_shift=(0.0, 20.0, 0.0), robot="R2"),
    dict(id="late_grip_sensor_0.4s", kind="nominal", sensor_delay=0.4),
    dict(id="both_robots_miss_once", kind="once", faults={"R1_PART": "once", "R2_BH": "once"}, robot="R1"),
]
GRIP_KINDS = ("R1_TAB", "R1_PART", "R2_TTAB", "R2_BH")


def legacy_programs():
    return {r: [(LEGACY / t / f).read_text() for f in ("CalibData.mod", "Module1.mod")] for r, t in (("R1", "T_ROB1"), ("R2", "T_ROB2"))}


def make_oracle():
    """Behavioural oracle: final object poses when the legacy program runs on the IRB cell (nominal)."""
    w = World(irb_cell()); ends = run_cell(w, legacy_programs())
    viol = [e for e in w.events if e["kind"] == "violation"]
    assert all(v == "Stop" for v in ends.values()) and not viol, (ends, viol)
    moved = {k: o.pos.round(2).tolist() for k, o in w.objs.items()
             if np.linalg.norm(o.pos - World(irb_cell()).objs[k].pos) > 1.0}
    io = [(e["task"], e["signal"], e["value"]) for e in w.events if e["kind"] == "io"]
    ORACLE.parent.mkdir(exist_ok=True)
    ORACLE.write_text(json.dumps(dict(destinations=moved, io_order=io, cycle_time_s=round(w.now, 2)), indent=1))
    return json.loads(ORACLE.read_text())


def oracle():
    return json.loads(ORACLE.read_text()) if ORACLE.exists() else make_oracle()


def run_scenario(programs, rigs_fn, sc, t_max=150.0, record_every=2):
    w = World(rigs_fn(), faults=sc.get("faults"), displace=sc.get("displace"), t_max=t_max,
              sensor_delay=sc.get("sensor_delay", 0.0), tray_shift=sc.get("tray_shift"), seed=sc.get("seed"))
    ends = run_cell(w, programs, record_every=record_every)
    return w, ends, evaluate(w, ends, sc)


def _lcs(a, b):
    m = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b, 1):
            cur = m[j]; m[j] = prev + 1 if x == y else max(m[j], m[j - 1]); prev = cur
    return m[-1]


def cycle_progress(w):
    """How far through the reference cycle the run got: per-task longest common subsequence of I/O events vs the
    oracle (legacy program on the IRB cell), as a fraction of the oracle's I/O events."""
    ref = oracle()["io_order"]
    got = [(e["task"], e["signal"], e["value"]) for e in w.events if e["kind"] == "io"]
    tasks = sorted({t for t, _, _ in ref})
    hit = sum(_lcs([x for x in got if x[0] == t], [tuple(x) for x in ref if x[0] == t]) for t in tasks)
    return round(hit / len(ref), 3)


def evaluate(w, ends, sc):
    orc = oracle()["destinations"]
    viol = [e for e in w.events if e["kind"] == "violation"]
    silent = [v for v in viol if v["type"] == "silent_failure"]
    hard = [v for v in viol if v["type"] != "silent_failure"]
    misplaced = {k: round(float(np.linalg.norm(w.objs[k].pos - np.array(p))), 1) for k, p in orc.items()
                 if np.linalg.norm(w.objs[k].pos - np.array(p)) > DELIVER_TOL_MM}
    delivered = not misplaced
    clean_end = all(v == "Stop" for v in ends.values())
    res = dict(id=sc["id"], kind=sc["kind"], delivered=delivered, misplaced=misplaced, ends=ends,
               violations=[(v["type"], v["task"], v.get("line")) for v in viol], n_violations=len(viol),
               alarms=[e["text"] for e in w.events if e["kind"] == "alarm"], sim_time=round(w.now, 1), progress=cycle_progress(w))
    if sc["kind"] in ("nominal", "once"):
        res["passed"] = delivered and clean_end and not viol
        res["why"] = "delivered" if res["passed"] else ("not delivered" if not delivered else "violations" if viol else f"ended {ends}")
    elif sc["kind"] == "safe":  # repeated fault: recovering or stopping safely are both acceptable, silence is not
        task = f"T_{sc['robot']}"
        faulted_end = ends.get(task, "timeout")
        alarmed = bool(res["alarms"]) or faulted_end.startswith("unhandled error")
        recovered = delivered and clean_end and not viol
        res["passed"] = recovered or (not silent and not hard and faulted_end != "timeout" and alarmed)
        res["why"] = ("recovered and delivered" if recovered else "safe stop with alarm" if res["passed"] else
                      "silent failure: program continued as if holding the part" if silent else
                      "violations" if hard else "no alarm / no stop")
    else:  # persistent fault: a safe stop is the correct outcome
        task = f"T_{sc['robot']}"
        faulted_end = ends.get(task, "timeout")
        alarmed = bool(res["alarms"]) or faulted_end.startswith("unhandled error")
        res["passed"] = not silent and not hard and faulted_end != "timeout" and alarmed
        res["why"] = ("safe stop with alarm" if res["passed"] else
                      "silent failure: program continued as if holding the part" if silent else
                      "violations" if hard else "no alarm / no stop")
    return res


def run_suite(programs, rigs_fn, suite=SUITE, verbose=True, on_row=None):
    rows = []
    for sc in suite:
        _, _, r = run_scenario(programs, rigs_fn, sc)
        rows.append(r)
        if on_row: on_row(r)
        if verbose: print(f"  {'PASS' if r['passed'] else 'fail'}  {sc['id']:24s} {r['why']}")
    cpr = sum(r["passed"] for r in rows) / len(rows)
    return dict(cpr=cpr, nominal=[r["passed"] for r in rows if r["kind"] == "nominal"],
                progress=next((r["progress"] for r in rows if r["kind"] == "nominal"), None),
                fault_pass=sum(r["passed"] for r in rows if r["kind"] != "nominal"),
                violations=sum(r["n_violations"] for r in rows), rows=rows)


def _mc_one(args):
    programs, rigs_fn, p, seed = args
    sc = dict(id=f"mc_{seed}", kind="nominal", faults={k: ("prob", p) for k in GRIP_KINDS}, seed=seed)
    w, ends, r = run_scenario(programs, rigs_fn, sc)
    silent = any(v[0] == "silent_failure" for v in r["violations"])
    hard = any(v[0] != "silent_failure" for v in r["violations"]) or "timeout" in ends.values()
    alarmed = bool(r["alarms"]) or any(str(e).startswith("unhandled error") for e in ends.values())
    misses = sum(1 for e in w.events if e["kind"] == "attach" and not e["ok"] and e.get("reason") == "injected missed grasp")
    # good box | bad box the program believes is good | stop with an operator alarm | controller fault (unreachable, timeout)
    outcome = ("good" if r["passed"] else "silent_bad" if silent or (not r["delivered"] and not alarmed and not hard)
               else "safe_stop" if alarmed else "fault_stop")
    return dict(seed=seed, outcome=outcome, misses=misses, sim_time=r["sim_time"])


def monte_carlo(programs, rigs_fn, p, n=1000, seed0=0, workers=None):
    """n seeded cycles with an independent per-grasp miss probability p at every grip. Returns counts + throughput."""
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_mc_one, [(programs, rigs_fn, p, seed0 + i) for i in range(n)], chunksize=8))
    cnt = {k: sum(r["outcome"] == k for r in rows) for k in ("good", "silent_bad", "safe_stop", "fault_stop")}
    hours = sum(r["sim_time"] for r in rows) / 3600.0
    good_t = [r["sim_time"] for r in rows if r["outcome"] == "good"]
    return dict(p_miss=p, cycles=n, **cnt, cycles_with_miss=sum(r["misses"] > 0 for r in rows),
                good_per_hour=round(cnt["good"] / hours, 1) if hours else 0.0,
                mean_good_cycle_s=round(float(np.mean(good_t)), 2) if good_t else None)


VARIANTS = {
    "legacy@IRB": (legacy_programs, irb_cell),
    "legacy@GoFa (verbatim)": (legacy_programs, gofa_cell),
}
