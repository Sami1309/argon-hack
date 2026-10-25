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


def run_scenario(programs, rigs_fn, sc, t_max=150.0):
    w = World(rigs_fn(), faults=sc.get("faults"), displace=sc.get("displace"), t_max=t_max)
    ends = run_cell(w, programs)
    return w, ends, evaluate(w, ends, sc)


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
               alarms=[e["text"] for e in w.events if e["kind"] == "alarm"], sim_time=round(w.now, 1))
    if sc["kind"] in ("nominal", "once"):
        res["passed"] = delivered and clean_end and not viol
        res["why"] = "delivered" if res["passed"] else ("not delivered" if not delivered else "violations" if viol else f"ended {ends}")
    else:  # persistent fault: a safe stop is the correct outcome
        task = f"T_{sc['robot']}"
        faulted_end = ends.get(task, "timeout")
        alarmed = bool(res["alarms"]) or faulted_end.startswith("unhandled error")
        res["passed"] = not silent and not hard and faulted_end != "timeout" and alarmed
        res["why"] = ("safe stop with alarm" if res["passed"] else
                      "silent failure: program continued as if holding the part" if silent else
                      "violations" if hard else "no alarm / no stop")
    return res


def run_suite(programs, rigs_fn, suite=SUITE, verbose=True):
    rows = []
    for sc in suite:
        _, _, r = run_scenario(programs, rigs_fn, sc)
        rows.append(r)
        if verbose: print(f"  {'PASS' if r['passed'] else 'fail'}  {sc['id']:24s} {r['why']}")
    cpr = sum(r["passed"] for r in rows) / len(rows)
    return dict(cpr=cpr, nominal=[r["passed"] for r in rows if r["kind"] == "nominal"],
                fault_pass=sum(r["passed"] for r in rows if r["kind"] != "nominal"),
                violations=sum(r["n_violations"] for r in rows), rows=rows)


VARIANTS = {
    "legacy@IRB": (legacy_programs, irb_cell),
    "legacy@GoFa (verbatim)": (legacy_programs, gofa_cell),
}
