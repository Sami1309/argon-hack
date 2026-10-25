"""CP2: kinematic acid test for T_ROB1 (no interpreter yet).

Enumerates the Cartesian poses of the production cycle from each program's own RAPID (INIT_PARAM values,
main's PP_TP_AB call, PROC Move statements), then runs them on a robot model:
  MoveJ  -> IK solution with the programmed confdata if one exists (else closest to current joints)
  MoveL  -> 2 mm straight-line tracking from the current joints
Reports unreachable poses, confdata mismatches, MoveL failures and the singularity margin.
The human GoFa port is read here only as a TEST of the twin (never shown to Argon).
"""
import json, pathlib, re, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.kinematics import Robot, quat_mul, quat_conj, quat_to_mat  # noqa: E402
from simulation.rapid.parse import parse_module, evaluate, split_args  # noqa: E402

AK = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key"
LEGACY = AK / "Solution_IRB_1200/Rapid/T_ROB1"
HUMAN = AK / "Solution_CRB_15000_GoFa/Rapid/Controller1/T_ROB1"
SINGLE = ROOT / "runs/smoke/port_baseline"
IRB_BASE = (np.array([-2943.42, -3356.18, 0.0]), np.array([0.707107, 0, 0, 0.707107]))  # MOC.cfg ROB_1
IRB2_BASE = (np.array([306.514, -3249.93, 0.0]), np.array([0.707107, 0, 0, 0.707107]))  # MOC.cfg ROB_2
IDENTITY = (np.zeros(3), np.array([1.0, 0, 0, 0]))
LEGACY2 = AK / "Solution_IRB_1200/Rapid/T_ROB2"


def target_check(mod, robot_name, base):
    """Each production Move target (with the tool named in that statement): reachable? programmed conf available?"""
    bp, bq = base
    rows, robots = [], {}
    for proc, (_, body) in mod.procs.items():
        if proc == "Path_Targets_Test": continue
        for line, s in body:
            m = re.match(r"(MoveL|MoveJ)\s+(.*);", s)
            if not m: continue
            args = split_args(m[2]); tool = re.match(r"(\w+)", args[3])[1]
            o = re.match(r"Offs\((\w+),(.*)\)$", args[0])
            name, off = (o[1], np.array([float(x) for x in split_args(o[2])])) if o else (args[0], np.zeros(3))
            rt, t = mod.robtargets[name], mod.tools[tool]
            robot = robots.setdefault(tool, Robot(robot_name, t.trans, t.rot))
            p = quat_to_mat(bq).T @ (rt.trans + off - bp) / 1000.0
            sols = robot.ik_all(p, quat_to_mat(quat_mul(quat_conj(bq), rt.rot)), n_seeds=32)
            confs = {robot.confdata(q) for q in sols}
            rows.append(dict(at=f"{proc}:{line}", target=f"{name}+{off.tolist()}", tool=tool, reachable=bool(sols),
                             programmed=rt.conf, exact=rt.conf in confs, tolerated=any(Robot.conf_ok(c, rt.conf) for c in confs)))
    return rows


def load(module1, calib):
    mod = parse_module(module1.read_text())
    mod.tools.update(parse_module(calib.read_text()).tools)
    return mod


def cycle(mod, obj_type):
    """Ordered motion list for one production cycle of T_ROB1."""
    env = {"r_str.objec_type": float(obj_type)}
    for _, s in mod.procs["INIT_PARAM"][1]:
        m = re.match(r"([\w.]+)\s*:=\s*(.+);", s)
        if m:
            try: env[m[1]] = evaluate(m[2], env)
            except (KeyError, SyntaxError): pass
    call = next(s for _, s in mod.procs["main"][1] if s.startswith("PP_TP_AB"))
    call_args = split_args(call[len("PP_TP_AB"):].rstrip(";"))
    home = ("MoveAbsJ", np.radians([0, 0, 0, 0, 90, 0]), None)
    seq = [home] + moves(mod, "PP_TAB_CONV", env)
    for counter in (0, 1):
        env["r_str.tAB_actual_counter"] = float(counter)
        params = mod.procs["PP_TP_AB"][0]
        local = dict(env, **{p: evaluate(a, env) for p, a in zip(params, call_args)})
        seq += moves(mod, "PP_TP_AB", local)
    return seq + [home]


def moves(mod, proc, env):
    out = []
    for line, s in mod.procs[proc][1]:
        m = re.match(r"(MoveL|MoveJ)\s+(.*);", s)
        if not m: continue
        tgt = split_args(m[2])[0]
        o = re.match(r"Offs\((.*)\)$", tgt)
        if o:
            name, *d = split_args(o[1]); off = np.array([evaluate(x, env) for x in d])
        else:
            name, off = tgt, np.zeros(3)
        rt = mod.robtargets[name]
        out.append((m[1], (rt.trans + off, rt.rot, rt.conf), f"{proc}:{line} {name}+{off.round(1).tolist()}"))
    return out


def run(robot, seq, base):
    """Execute the motion list; returns per-move records and a summary."""
    bp, bq = base
    q = None
    recs, summ = [], dict(moves=0, unreachable=0, config_mismatch=0, movel_fail=0, axis_travel_gt180=0, min_sv=np.inf)
    for kind, tgt, label in seq:
        if kind == "MoveAbsJ":
            q = np.array(tgt); recs.append(dict(kind=kind, label="home", ok=True)); continue
        summ["moves"] += 1
        p_w, r_w, conf = tgt
        p = quat_to_mat(bq).T @ (p_w - bp) / 1000.0           # wobj -> robot base, metres
        R = quat_to_mat(quat_mul(quat_conj(bq), r_w))
        sols = robot.ik_all(p, R, n_seeds=32)
        confs = [robot.confdata(s) for s in sols]
        rec = dict(kind=kind, label=label, n_solutions=len(sols), programmed_conf=list(conf),
                   solution_confs=sorted(set(confs)), conf_available=conf in confs)
        if not sols:
            summ["unreachable"] += 1; rec["ok"] = False; recs.append(rec); continue
        if kind == "MoveJ":
            ok_sols = [s for s, c in zip(sols, confs) if Robot.conf_ok(c, conf)]
            exact = [s for s, c in zip(sols, confs) if c == conf]
            q = min(exact or ok_sols or sols, key=lambda s: np.abs(s - q).max())
        else:
            q_prev = q
            nq, rep = robot.track_line(q, p, R)
            rec["movel"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rep.items() if k != "samples"}
            if nq is None:
                summ["movel_fail"] += 1; rec["ok"] = False; recs.append(rec)
                q = min(sols, key=lambda s: np.abs(s - q).max()); continue
            q = nq; summ["min_sv"] = min(summ["min_sv"], rep["min_sv"])
            travel = np.degrees(np.abs(q - q_prev))[[0, 3, 5]]
            rec["axis146_travel_deg"] = travel.round(1).tolist()
            if travel.max() > 180:
                summ["axis_travel_gt180"] += 1  # ABB: keep axes 1/4/6 under 180 deg per linear move
        rec["reached_conf"] = list(robot.confdata(q))
        rec["config_match"] = Robot.conf_ok(rec["reached_conf"], conf)
        summ["config_mismatch"] += not rec["config_match"]
        rec["ok"] = True; recs.append(rec)
    return recs, summ


VARIANTS = [  # name, module dir/file, calib, robot, base frame for wobj0
    ("legacy  @ IRB 1200", LEGACY / "Module1.mod", LEGACY / "CalibData.mod", "irb1200_5_90", IRB_BASE),
    ("legacy  @ GoFa (verbatim)", LEGACY / "Module1.mod", LEGACY / "CalibData.mod", "crb15000_5_95", IDENTITY),
    ("single-pass Argon @ GoFa", SINGLE / "Module1.mod", LEGACY / "CalibData.mod", "crb15000_5_95", IDENTITY),
    ("human port @ GoFa", HUMAN / "Module1.mod", HUMAN / "CalibData.mod", "crb15000_5_95", IDENTITY),
]

if __name__ == "__main__":
    out = ROOT / "runs/cp2"; out.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, mod_f, cal_f, robot_name, base in VARIANTS:
        mod = load(mod_f, cal_f)
        tool = mod.tools["smc_gripper"]
        robot = Robot(robot_name, tool.trans, tool.rot)
        all_recs, tot = [], dict(moves=0, unreachable=0, config_mismatch=0, movel_fail=0, axis_travel_gt180=0, min_sv=np.inf)
        for obj_type in (1, 2, 3):
            recs, s = run(robot, cycle(mod, obj_type), base)
            all_recs.append(recs)
            for k in ("moves", "unreachable", "config_mismatch", "movel_fail", "axis_travel_gt180"): tot[k] += s[k]
            tot["min_sv"] = min(tot["min_sv"], s["min_sv"])
        report[name] = dict(summary=tot, type3=all_recs[2])
        print(f"{name:28s} moves={tot['moves']:3d} unreachable={tot['unreachable']:3d} "
              f"config_viol={tot['config_mismatch']:3d} movel_fail={tot['movel_fail']:3d} "
              f"axis_travel>180={tot['axis_travel_gt180']:2d} min_sv={tot['min_sv']:.4f}")
    mod2 = load(LEGACY2 / "Module1.mod", LEGACY2 / "CalibData.mod")
    rows = target_check(mod2, "irb1200_5_90", IRB2_BASE)
    report["legacy T_ROB2 @ IRB ROB_2"] = rows
    print(f"legacy T_ROB2 @ IRB ROB_2: reachable {sum(r['reachable'] for r in rows)}/{len(rows)}, "
          f"programmed conf exact {sum(r['exact'] for r in rows)}/{len(rows)}, tolerated {sum(r['tolerated'] for r in rows)}/{len(rows)}")
    for r in rows: print(f"   {r['at']:16s} {r['target'][:34]:34s} {r['tool']:9s} prog={r['programmed']} exact={r['exact']}")
    (out / "report.json").write_text(json.dumps(report, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    print("details ->", out / "report.json")


def test_kinematic_acid():
    """Gate: twin accepts what really ran, rejects the verbatim copy."""
    res = {}
    for name, mod_f, cal_f, robot_name, base in VARIANTS:
        mod = load(mod_f, cal_f); tool = mod.tools["smc_gripper"]
        robot = Robot(robot_name, tool.trans, tool.rot)
        _, res[name] = run(robot, cycle(mod, 3), base)
    clean = lambda s: s["unreachable"] == s["config_mismatch"] == s["movel_fail"] == s["axis_travel_gt180"] == 0
    assert clean(res["legacy  @ IRB 1200"])
    assert res["legacy  @ GoFa (verbatim)"]["unreachable"] == res["legacy  @ GoFa (verbatim)"]["moves"]
    assert clean(res["human port @ GoFa"])
    rows = target_check(load(LEGACY2 / "Module1.mod", LEGACY2 / "CalibData.mod"), "irb1200_5_90", IRB2_BASE)
    assert all(r["reachable"] and r["tolerated"] for r in rows)
