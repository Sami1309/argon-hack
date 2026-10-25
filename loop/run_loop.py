"""Port loop (Loop 2/3): Argon single-pass port, then critique -> one patch -> rerun -> keep/revert.

    python loop/run_loop.py --iters 6            # writes runs/loop_<ts>/...
Keep rule: Cell Pass Rate rises, or stays equal while the violation count falls. Otherwise revert.
"""
import argparse, json, pathlib, re, sys, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client  # noqa: E402
from simulation.cell import gofa_cell  # noqa: E402
from simulation.rapid.interp import parse, RapidSyntaxError  # noqa: E402
from simulation.scenarios import SUITE, legacy_programs, run_scenario, run_suite  # noqa: E402
from simulation.render import Renderer, overlay_lines  # noqa: E402
import imageio  # noqa: E402

MAX_PATCH_LINES = 40

CELL_FACTS = """CELL (two-robot sorting line, RobotStudio station by R. Parak, MIT):
- Robot 1 (task T_ROB1) picks a tray (vacuum gripper smc_gripper, DO_ATT_TAB) from its table and places it on the conveyor
  (DO_DET_TAB), then moves two parts of the selected colour from the parts holder onto the tray (OBJECT_MANIP -> DO_ATT_xPn /
  DO_DET_xPn), attaches them to the tray (DO_ATT_ABn) and runs the conveyor (DO_ENABLE_CONV) until DI_CONV_IN_POS.
- Robot 2 (task T_ROB2) waits for DI_CONV_IN_POS, grips the tray with servo fingers (DO_SG_P, DO_ATT_TTAB), puts it in the
  box, then places the box holder with its vacuum tool (DO_ATT_BH / DO_DET_BH).
- Legacy robots: two ABB IRB 1200-5/0.9 on ONE IRC5 controller (RobotWare 6). MOC.cfg base frames (world, mm):
  ROB_1 at (-2943.42, -3356.18, 0), ROB_2 at (306.514, -3249.93, 0), both rotated +90 deg about world Z.
  Because base frames are configured, legacy robtargets with wobj0 are WORLD coordinates.
- New robots: two ABB GoFa CRB 15000-5/0.95 (RobotWare 7, one OmniCore controller each), bolted onto the SAME mounting
  points and orientations as the IRBs. The GoFa controllers have NO world/base frame configured: wobj0 = robot base frame.
- Tools (tooldata) and all I/O signal names stay the same; the cell I/O is shared between the two controllers.
- Sensor available on the new cobots: DI_GRIP_OK (per robot) = 1 while the gripper holds a part. It is a PROPOSED
  hardware addition (not in the original cell)."""

GUIDE = """RULES FOR PATCHES:
- Return exactly ONE patch: the full text of ONE routine (PROC ... ENDPROC) for ONE task. It replaces the routine of the
  same name, or is added if new. At most 40 changed lines. Keep everything else unchanged.
- The program must stay valid RAPID for RobotWare 7. Supported: MoveJ/MoveL/MoveAbsJ, Offs, SetDO/PulseDO/WaitDI
  (\\MaxTime, \\TimeFlag), WaitTime, WaitUntil, IF/TEST/WHILE/FOR, routine-local VAR declarations at the top of a routine,
  ERROR handlers with RETRY/TRYNEXT/RAISE/RETURN, ERRNO, ERR_WAIT_MAXTIME, ErrWrite, TPWrite, Stop, EXIT.
- A missed grasp must never be ignored: either recover (re-approach and re-grip, then continue) or stop safely with an
  alarm (ErrWrite) without continuing as if the part were held.
- Cite what you saw: every observation must give the clip time in seconds."""

PORT_SCHEMA = {"type": "object", "properties": {
    "R1_module1": {"type": "string"}, "R2_module1": {"type": "string"},
    "changes": {"type": "array", "items": {"type": "string"}}},
    "required": ["R1_module1", "R2_module1", "changes"]}

CRITIQUE_SCHEMA = {"type": "object", "properties": {
    "observations": {"type": "array", "items": {"type": "object", "properties": {
        "clip_time_s": {"type": "number"}, "what": {"type": "string"}}, "required": ["clip_time_s", "what"]}},
    "root_cause": {"type": "string"},
    "patch": {"type": "object", "properties": {
        "task": {"type": "string", "enum": ["R1", "R2"]}, "routine": {"type": "string"},
        "new_routine": {"type": "string"}, "rationale": {"type": "string"}},
        "required": ["task", "routine", "new_routine", "rationale"]},
    "expected_effect": {"type": "string"}},
    "required": ["observations", "root_cause", "patch", "expected_effect"]}


def numbered(src):
    return "\n".join(f"{i:4d} {l}" for i, l in enumerate(src.splitlines(), 1))


def legacy_text():
    p = legacy_programs()
    return "\n\n".join(f"=== legacy T_ROB{r[1]} {name} ===\n{src}" for r, srcs in p.items() for name, src in zip(("CalibData.mod", "Module1.mod"), srcs))


def program_text(prog):
    return "\n\n".join(f"=== CURRENT {r} {name} (line-numbered) ===\n{numbered(src)}"
                       for r, srcs in prog.items() for name, src in zip(("CalibData.mod", "Module1.mod"), srcs))


# ---------------------------------------------------------------- iteration 0: single-pass port
def single_pass(run_dir, thinking="medium"):
    prompt = (f"{CELL_FACTS}\n\nTASK: Port both legacy RAPID tasks to the two GoFa robots so the cell performs the same "
              f"sorting cycle. CalibData.mod (tooldata) stays unchanged. Return the full ported Module1.mod for R1 (from T_ROB1) "
              f"and R2 (from T_ROB2), and a list of changes.\n\n{legacy_text()}")
    out, meta = argon_client.call([dict(kind="text", data=prompt, source="legacy RAPID (D1) + cell facts")],
                                  label="iter00_single_pass", run_dir=run_dir, schema=PORT_SCHEMA, thinking=thinking)
    calib = {r: srcs[0] for r, srcs in legacy_programs().items()}
    prog = {"R1": [calib["R1"], out["R1_module1"]], "R2": [calib["R2"], out["R2_module1"]]}
    return prog, out["changes"], meta


# ---------------------------------------------------------------- patches
def find_routine(src, name):
    m = re.search(rf"^[ \t]*(?:LOCAL\s+)?(PROC|FUNC\s+\w+|TRAP)\s+{re.escape(name)}\b", src, re.M)
    if not m: return None
    end = re.compile(r"^[ \t]*END(PROC|FUNC|TRAP)\b", re.M).search(src, m.end())
    return m.start(), src.index("\n", end.start()) + 1 if "\n" in src[end.start():] else len(src)


def apply_patch(prog, patch):
    """Returns (new_prog, changed_lines) or raises ValueError with a message Argon will see."""
    task, name, new = patch["task"], patch["routine"].strip(), patch["new_routine"].strip("\n") + "\n"
    if not re.match(rf"\s*(?:LOCAL\s+)?(PROC|FUNC\s+\w+|TRAP)\s+{re.escape(name)}\b", new):
        raise ValueError(f"new_routine must start with 'PROC {name}' (or FUNC/TRAP)")
    src = prog[task][1]
    span = find_routine(src, name)
    if span: new_src = src[:span[0]] + new + src[span[1]:]; old = src[span[0]:span[1]]
    else:
        k = src.rindex("ENDMODULE"); new_src = src[:k] + new + "\n" + src[k:]; old = ""
    a, b = [l.strip() for l in old.splitlines()], [l.strip() for l in new.splitlines()]
    changed = len(set(b) - set(a)) + len(set(a) - set(b))
    if changed > MAX_PATCH_LINES: raise ValueError(f"patch changes {changed} lines (limit {MAX_PATCH_LINES})")
    try: parse(new_src)
    except RapidSyntaxError as e: raise ValueError(f"RAPID syntax error after patch: {e}")
    out = {k: list(v) for k, v in prog.items()}; out[task] = [prog[task][0], new_src]
    return out, changed


# ---------------------------------------------------------------- evaluation + evidence
def evaluate(prog):
    s = run_suite(prog, gofa_cell, verbose=False)
    return s


def suite_table(s):
    lines = ["scenario | result | why | violations (type, task, line)"]
    for r in s["rows"]:
        lines.append(f"{r['id']} | {'PASS' if r['passed'] else 'FAIL'} | {r['why']} | {r['violations'][:4]}")
    lines.append(f"Cell Pass Rate = {s['cpr']:.0%} ({sum(r['passed'] for r in s['rows'])}/{len(s['rows'])}); total violations = {s['violations']}")
    return "\n".join(lines)


def showcase(prog, s, run_dir, label):
    """Render the first failing scenario around its first failure event (8 s clip, 5 fps)."""
    failing = [r for r in s["rows"] if not r["passed"]]
    if not failing: return None
    sc = next(x for x in SUITE if x["id"] == failing[0]["id"])
    w, ends, res = run_scenario(prog, gofa_cell, sc)
    evs = [e for e in w.events if e["kind"] in ("violation", "wait_timeout", "alarm") or (e["kind"] == "attach" and not e.get("ok"))]
    t_fail = evs[0]["t"] if evs else max(0.0, w.now - 8)
    t0, t1 = max(0.0, t_fail - 2.0), t_fail + 6.0
    robot = sc.get("robot") or (evs[0]["task"][2:] if evs and evs[0].get("task") else "R1")
    cam = {"R1": "r1_close", "R2": "r2_close"}.get(robot, "station")
    rr = Renderer(w)
    frames = [rr.frame(snap, cam, overlay_lines(w, snap, f"{sc['id']} (sim-only fault)")) for snap in w.snapshots[::3] if t0 <= snap["t"] <= t1]
    rr.close()
    mp4 = pathlib.Path(run_dir) / f"{label}_{sc['id']}.mp4"
    imageio.mimwrite(mp4, frames, fps=5, quality=7, macro_block_size=8)
    trace = [e for e in w.events if e["kind"] in ("attach", "detach", "violation", "alarm", "wait_timeout", "task_end", "io")
             and t0 - 2 <= e["t"] <= t1 + 30][:40]
    return dict(scenario=sc["id"], clip=mp4, clip_t0=t0, trace=trace, result=res)


def critique(prog, s, ev, history, run_dir, label, thinking):
    stable = (f"{CELL_FACTS}\n\nSTAGE 1 (Argon mined 19 min of real cobot footage + logs): the most common observed failure "
              f"is the MISSED GRASP (gripper closes on nothing); contact displacement also occurs. The legacy program grips open-loop "
              f"(pulse + WaitTime, no confirmation).\n\nSCENARIO SUITE (digital twin, sim-only faults): "
              + "; ".join(f"{x['id']}" for x in SUITE)
              + ". nominal/once: every part must reach its destination with 0 violations. always/displaced: safe stop with alarm, "
              f"never continue as if holding.\n\n{GUIDE}\n\n{legacy_text()}")
    tail = (f"{program_text(prog)}\n\nTWIN RESULTS FOR THE CURRENT PROGRAM:\n{suite_table(s)}\n\n"
            f"SHOWCASE CLIP: scenario {ev['scenario']}, clip starts at sim time {ev['clip_t0']:.1f}s (clip_time_s = sim time - "
            f"{ev['clip_t0']:.1f}). Twin trace excerpt (sim time):\n" + "\n".join(json.dumps(e) for e in ev["trace"])
            + f"\n\nHISTORY:\n" + ("\n".join(history[-6:]) or "none")
            + "\n\nWatch the clip, explain the failure citing clip times, then return ONE patch that raises the Cell Pass Rate.")
    parts = [dict(kind="text", data=stable, source="cell facts + Stage1 summary + suite + rules + legacy RAPID"),
             dict(kind="video", data=ev["clip"].read_bytes(), source=f"twin render {ev['clip'].name}"),
             dict(kind="text", data=tail, source="current program + twin results + trace + history")]
    return argon_client.call(parts, label=label, run_dir=run_dir, schema=CRITIQUE_SCHEMA, thinking=thinking)


def save_prog(prog, d):
    d.mkdir(parents=True, exist_ok=True)
    for r, (cal, mod) in prog.items():
        (d / f"{r}_CalibData.mod").write_text(cal); (d / f"{r}_Module1.mod").write_text(mod)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--port-thinking", default="medium")
    ap.add_argument("--resume", help="run dir with iter00 program to start from")
    a = ap.parse_args()
    run_dir = pathlib.Path(a.resume) if a.resume else ROOT / f"runs/loop_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)

    if a.resume and (run_dir / "iter00").exists():
        prog = {r: [(run_dir / "iter00" / f"{r}_{f}").read_text() for f in ("CalibData.mod", "Module1.mod")] for r in ("R1", "R2")}
        log("resumed single-pass program")
    else:
        log("iteration 0: Argon single-pass port ...")
        prog, changes, meta = single_pass(run_dir, a.port_thinking)
        save_prog(prog, run_dir / "iter00")
        log(f"  single pass in {meta['latency_s']}s, {len(changes)} changes")
    s = evaluate(prog)
    metrics = [dict(iter=0, cpr=s["cpr"], fault_pass=s["fault_pass"], violations=s["violations"], kept=True, note="single-pass port")]
    log(f"iter 0: CPR={s['cpr']:.0%} violations={s['violations']}")
    (run_dir / "iter00" / "suite.json").write_text(json.dumps(s, indent=1, default=str))
    history, fails = [], 0
    for k in range(1, a.iters + 1):
        if s["cpr"] == 1.0: log("CPR 100% - done"); break
        d = run_dir / f"iter{k:02d}"; d.mkdir(exist_ok=True)
        ev = showcase(prog, s, d, f"iter{k:02d}")
        out, meta = critique(prog, s, ev, history, d, f"iter{k:02d}_critique", a.thinking)
        p = out["patch"]
        log(f"iter {k}: Argon ({meta['latency_s']}s) patch {p['task']}.{p['routine']} :: {p['rationale'][:120]}")
        try:
            cand, nchg = apply_patch(prog, p)
            cs = evaluate(cand)
            better = cs["cpr"] > s["cpr"] or (cs["cpr"] == s["cpr"] and cs["violations"] < s["violations"])
            reason = f"CPR {s['cpr']:.0%}->{cs['cpr']:.0%}, violations {s['violations']}->{cs['violations']}"
        except ValueError as e:
            better, reason, cs, nchg = False, f"patch rejected: {e}", s, 0
        decision = "KEPT" if better else "REVERTED"
        history.append(f"iter {k}: patched {p['task']}.{p['routine']} ({nchg} lines) -> {decision}: {reason}")
        log(f"   {decision}: {reason}")
        (d / "decision.json").write_text(json.dumps(dict(decision=decision, reason=reason, patch=p, scenario=ev["scenario"],
                                                         observations=out["observations"], root_cause=out["root_cause"]), indent=1))
        if better:
            prog, s = cand, cs; fails = 0
            save_prog(prog, d)
        else:
            fails += 1
        metrics.append(dict(iter=k, cpr=s["cpr"], fault_pass=s["fault_pass"], violations=s["violations"], kept=better,
                            tried=cs["cpr"], note=f"{p['task']}.{p['routine']}", latency_s=meta["latency_s"],
                            tokens=meta["usage"].get("total_token_count")))
        (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
        if fails >= 3: log("3 consecutive rejections - stop"); break
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
    log("CPR by iteration:", [f"{m['cpr']:.0%}" for m in metrics])
    return run_dir


if __name__ == "__main__":
    main()
