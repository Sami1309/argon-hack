"""Port loop (Loop 2/3): Argon single-pass port, then critique -> one patch -> rerun -> keep/revert.

    python loop/run_loop.py --iters 6                       # single pass + loop, writes runs/loop_<ts>/...
    python loop/run_loop.py --start runs/loop_X/iter00      # loop only, from a cached single-pass program
    python loop/run_loop.py --single-pass-only --trials 3   # repeatability of the single pass

Keep rule (training suite only): Cell Pass Rate rises; or it ties and the normal cycle gets further (I/O progress vs the
legacy reference); or both tie and the violation count falls. The nominal cycle time may grow by at most 10%. The held-out suite is scored for every kept and tried program but is never shown to
Argon and never used in the decision.
"""
import argparse, concurrent.futures as cf, difflib, json, pathlib, re, shutil, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client, sensor, stage1  # noqa: E402
from simulation.cell import gofa_cell  # noqa: E402
from simulation.rapid.interp import parse, RapidSyntaxError  # noqa: E402
from simulation.scenarios import SUITE, HELD_OUT, legacy_programs, run_scenario, run_suite  # noqa: E402
from simulation.render import Renderer  # noqa: E402
import imageio  # noqa: E402

MAX_PATCH_LINES = 40
CYCLE_TIME_SLACK = 1.10

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
- Tools (tooldata) and all I/O signal names stay the same; the cell I/O is shared between the two controllers."""

GUIDE = """RULES FOR PATCHES:
- Return exactly ONE patch: the full text of ONE routine (PROC ... ENDPROC) for ONE task. It replaces the routine of the
  same name, or is added if new. At most 40 changed lines. Keep everything else unchanged.
- The program must stay valid RAPID for RobotWare 7. Supported: MoveJ/MoveL/MoveAbsJ, Offs, SetDO/PulseDO/WaitDI
  (\\MaxTime, \\TimeFlag), WaitTime, WaitUntil, IF/TEST/WHILE/FOR, routine-local VAR declarations at the top of a routine,
  ERROR handlers with RETRY/TRYNEXT/RAISE/RETURN, ERRNO, ERR_WAIT_MAXTIME, ErrWrite, TPWrite, Stop, EXIT.
- A missed grasp must never be ignored: either recover (re-approach and re-grip, then continue) or stop safely with an
  alarm (ErrWrite) without continuing as if the part were held.
- The nominal cycle time may grow by at most 10%.
- Cite what you saw: failure_time_s is the clip time of the FIRST frame where the failure is visible; every
  observation gives its clip time in seconds."""

PORT_SCHEMA = {"type": "object", "properties": {
    "R1_module1": {"type": "string"}, "R2_module1": {"type": "string"},
    "changes": {"type": "array", "items": {"type": "string"}}},
    "required": ["R1_module1", "R2_module1", "changes"]}

CRITIQUE_SCHEMA = {"type": "object", "properties": {
    "failure_time_s": {"type": "number"},
    "observations": {"type": "array", "items": {"type": "object", "properties": {
        "clip_time_s": {"type": "number"}, "what": {"type": "string"}}, "required": ["clip_time_s", "what"]}},
    "root_cause": {"type": "string"},
    "patch": {"type": "object", "properties": {
        "task": {"type": "string", "enum": ["R1", "R2"]}, "routine": {"type": "string"},
        "new_routine": {"type": "string"}, "rationale": {"type": "string"}},
        "required": ["task", "routine", "new_routine", "rationale"]},
    "expected_effect": {"type": "string"}},
    "required": ["failure_time_s", "observations", "root_cause", "patch", "expected_effect"]}

FAIL_KINDS = ("violation", "wait_timeout", "alarm")


def numbered(src):
    return "\n".join(f"{i:4d} {l}" for i, l in enumerate(src.splitlines(), 1))


def legacy_text():
    p = legacy_programs()
    return "\n\n".join(f"=== legacy T_ROB{r[1]} {name} ===\n{src}" for r, srcs in p.items() for name, src in zip(("CalibData.mod", "Module1.mod"), srcs))


def program_text(prog):
    return "\n\n".join(f"=== CURRENT {r} {name} (line-numbered) ===\n{numbered(src)}"
                       for r, srcs in prog.items() for name, src in zip(("CalibData.mod", "Module1.mod"), srcs))


def load_prog(d):
    d = pathlib.Path(d)
    return {r: [(d / f"{r}_{f}").read_text() for f in ("CalibData.mod", "Module1.mod")] for r in ("R1", "R2")}


def save_prog(prog, d):
    d.mkdir(parents=True, exist_ok=True)
    for r, (cal, mod) in prog.items():
        (d / f"{r}_CalibData.mod").write_text(cal); (d / f"{r}_Module1.mod").write_text(mod)


# ---------------------------------------------------------------- iteration 0: single-pass port (no sensor, no Stage 1)
def single_pass(run_dir, thinking="medium", label="iter00_single_pass"):
    prompt = (f"{CELL_FACTS}\n\nTASK: Port both legacy RAPID tasks to the two GoFa robots so the cell performs the same "
              f"sorting cycle. CalibData.mod (tooldata) stays unchanged. Return the full ported Module1.mod for R1 (from T_ROB1) "
              f"and R2 (from T_ROB2), and a list of changes.\n\n{legacy_text()}")
    out, meta = argon_client.call([dict(kind="text", data=prompt, source="legacy RAPID (D1) + cell facts")],
                                  label=label, run_dir=run_dir, schema=PORT_SCHEMA, thinking=thinking)
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
    """Returns (new_prog, changed_lines, old_routine) or raises ValueError with a message Argon will see."""
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
    return out, changed, old


def routine_diff(old, new):
    """Line diff of a patched routine that ignores re-indentation: [{op: ' '|'+'|'-', text}]."""
    a, b = (old or "").strip("\n").splitlines(), (new or "").strip("\n").splitlines()
    sm = difflib.SequenceMatcher(a=[x.strip() for x in a], b=[x.strip() for x in b], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal": out += [dict(op=" ", text=t) for t in b[j1:j2]]
        else: out += [dict(op="-", text=t) for t in a[i1:i2]] + [dict(op="+", text=t) for t in b[j1:j2]]
    return out


# ---------------------------------------------------------------- evaluation + evidence
def evaluate(prog):
    """Training suite (decides keep/revert) and held-out suite (reported only)."""
    s = run_suite(prog, gofa_cell, verbose=False)
    h = run_suite(prog, gofa_cell, suite=HELD_OUT, verbose=False)
    s["heldout"] = h["cpr"]; s["heldout_rows"] = h["rows"]
    nom = next(r for r in s["rows"] if r["id"] == "nominal")
    s["cycle_time"] = nom["sim_time"] if nom["passed"] else None
    return s


def better(new, old):
    if new["cpr"] < old["cpr"]: return False, "Cell Pass Rate fell"
    if old["cycle_time"] and new["cycle_time"] and new["cycle_time"] > old["cycle_time"] * CYCLE_TIME_SLACK:
        return False, f"nominal cycle {old['cycle_time']}s -> {new['cycle_time']}s (> +10%)"
    if new["cpr"] > old["cpr"]: return True, "Cell Pass Rate rose"
    if new["progress"] > old["progress"] + 1e-3: return True, "same Cell Pass Rate, the normal cycle gets further"
    if new["progress"] < old["progress"] - 1e-3: return False, "the normal cycle gets less far"
    if new["violations"] < old["violations"]: return True, "same Cell Pass Rate, fewer violations"
    return False, "no improvement"


def suite_table(s):
    lines = ["scenario | result | why | violations (type, task, line)"]
    for r in s["rows"]:
        lines.append(f"{r['id']} | {'PASS' if r['passed'] else 'FAIL'} | {r['why']} | {r['violations'][:4]}")
    lines.append(f"Cell Pass Rate = {s['cpr']:.0%} ({sum(r['passed'] for r in s['rows'])}/{len(s['rows'])}); normal-cycle progress = "
                 f"{s['progress']:.0%}; total violations = {s['violations']}"
                 + (f"; nominal cycle {s['cycle_time']}s" if s.get("cycle_time") else ""))
    return "\n".join(lines)


def rows_brief(rows):
    return [dict(id=r["id"], passed=r["passed"], why=r["why"]) for r in rows]


def showcase(prog, s, run_dir, label):
    """Render the first failing scenario around its first failure (8 s, 5 fps, no burned-in text: Argon sees pixels)."""
    failing = [r for r in s["rows"] if not r["passed"]]
    if not failing: return None
    sc = next(x for x in SUITE if x["id"] == failing[0]["id"])
    w, ends, res = run_scenario(prog, gofa_cell, sc)
    evs = [e for e in w.events if e["kind"] in FAIL_KINDS or (e["kind"] == "attach" and not e.get("ok"))]
    t_fail = evs[0]["t"] if evs else max(0.0, w.now - 8)
    t0, t1 = max(0.0, t_fail - 2.0), t_fail + 6.0
    robot = sc.get("robot") or (evs[0]["task"][2:] if evs and evs[0].get("task") else "R1")
    cam = {"R1": "r1_close", "R2": "r2_close"}.get(robot, "station")
    rr = Renderer(w)
    frames = [rr.frame(snap, cam) for snap in w.snapshots[::3] if t0 <= snap["t"] <= t1]
    rr.close()
    mp4 = pathlib.Path(run_dir) / f"{label}_{sc['id']}.mp4"
    imageio.mimwrite(mp4, frames, fps=5, quality=7, macro_block_size=8)
    trace = [e for e in w.events if e["kind"] in ("attach", "detach", "violation", "alarm", "wait_timeout", "task_end", "io")
             and t0 - 2 <= e["t"] <= t1 + 30][:40]
    return dict(scenario=sc["id"], camera=cam, clip=mp4, clip_t0=round(t0, 3), clip_t1=round(t1, 3),
                truth_t=round(t_fail - t0, 2), truth_event=evs[0] if evs else None, trace=trace, result=res)


def critique(prog, s, ev, history, run_dir, label, thinking, context=None):
    context = context or {}
    stable = (f"{CELL_FACTS}\n{context.get('sensor_facts') or sensor.facts()}\n\n{context.get('stage1_text') or stage1.summary_text()}\n\nSCENARIO SUITE (digital twin, sim-only faults "
              f"mirroring the Stage 1 findings): " + "; ".join(f"{x['id']}" for x in SUITE)
              + ". nominal/once: every part must reach its destination with 0 violations. always/displaced: safe stop with alarm, "
              f"never continue as if holding.\n\n{GUIDE}\n\n{legacy_text()}")
    tail = (f"{program_text(prog)}\n\nTWIN RESULTS FOR THE CURRENT PROGRAM:\n{suite_table(s)}\n\n"
            f"SHOWCASE CLIP: scenario {ev['scenario']}, camera {ev['camera']}, clip starts at sim time {ev['clip_t0']:.1f}s "
            f"(clip_time_s = sim time - {ev['clip_t0']:.1f}). Twin trace excerpt (sim time):\n" + "\n".join(json.dumps(e) for e in ev["trace"])
            + f"\n\nHISTORY:\n" + ("\n".join(history[-6:]) or "none")
            + "\n\nWatch the clip, give failure_time_s, explain the failure citing clip times, then return ONE patch that raises "
              "the Cell Pass Rate.")
    parts = [dict(kind="text", data=stable, source="cell facts + approved sensor + Stage 1 (derived/stage1.json) + suite + rules + legacy RAPID"),
             dict(kind="video", data=ev["clip"].read_bytes(), source=f"twin render, no overlays: {ev['clip'].name}"),
             dict(kind="text", data=tail, source="current program + twin results + trace + history")]
    return argon_client.call(parts, label=label, run_dir=run_dir, schema=CRITIQUE_SCHEMA, thinking=thinking)


# ---------------------------------------------------------------- the loop
def run(run_dir, iters=6, thinking="medium", port_thinking="medium", start=None, emit=print, context=None):
    """emit(dict) receives every step (the dashboard's live mode streams these). Returns the metrics list.
    context: optional {stage1_text, sensor_facts} from a live Stage 1 + approval; defaults to the recorded ones."""
    if not (context or {}).get("sensor_facts") and not sensor.approved():
        raise SystemExit("the grip sensor is not approved yet: python loop/sensor.py --approve")
    run_dir = pathlib.Path(run_dir).resolve(); run_dir.mkdir(parents=True, exist_ok=True)
    t_run = time.time()
    if start:
        prog = load_prog(start); save_prog(prog, run_dir / "iter00")
        for f in pathlib.Path(start).parent.glob("iter00_single_pass.*.json"): shutil.copy(f, run_dir / f.name)
        emit(dict(ev="single_pass", cached=True, source=str(start)))
    elif (run_dir / "iter00" / "R1_Module1.mod").exists():
        prog = load_prog(run_dir / "iter00"); emit(dict(ev="single_pass", cached=True, source=str(run_dir / "iter00")))
    else:
        emit(dict(ev="single_pass_start"))
        prog, changes, meta = single_pass(run_dir, port_thinking)
        save_prog(prog, run_dir / "iter00")
        emit(dict(ev="single_pass", cached=False, latency_s=meta["latency_s"], changes=changes))
    s = evaluate(prog)
    (run_dir / "iter00" / "suite.json").write_text(json.dumps(s, indent=1, default=str))
    metrics = [dict(iter=0, cpr=s["cpr"], heldout=s["heldout"], progress=s["progress"], fault_pass=s["fault_pass"], violations=s["violations"],
                    cycle_time=s["cycle_time"], kept=True, note="single-pass port", rows=rows_brief(s["rows"]),
                    heldout_rows=rows_brief(s["heldout_rows"]))]
    emit(dict(ev="iteration", **metrics[-1]))
    history, fails = [], 0
    for k in range(1, iters + 1):
        if s["cpr"] == 1.0: emit(dict(ev="done", reason="Cell Pass Rate 100%")); break
        d = run_dir / f"iter{k:02d}"; d.mkdir(exist_ok=True)
        ev = showcase(prog, s, d, f"iter{k:02d}")
        emit(dict(ev="watching", iter=k, scenario=ev["scenario"], clip=str(ev["clip"].relative_to(ROOT))))
        out, meta = critique(prog, s, ev, history, d, f"iter{k:02d}_critique", thinking, context)
        p = out["patch"]
        emit(dict(ev="patch", iter=k, task=p["task"], routine=p["routine"], failure_time_s=out["failure_time_s"],
                  root_cause=out["root_cause"], latency_s=meta["latency_s"]))
        old = ""
        try:
            cand, nchg, old = apply_patch(prog, p)
            cs = evaluate(cand)
            keep, why = better(cs, s)
            reason = (f"{why}: CPR {s['cpr']:.0%}->{cs['cpr']:.0%}, cycle progress {s['progress']:.0%}->{cs['progress']:.0%}, "
                      f"violations {s['violations']}->{cs['violations']}, held-out {s['heldout']:.0%}->{cs['heldout']:.0%}")
            save_prog(cand, d / "candidate")
        except ValueError as e:
            keep, reason, cs, nchg = False, f"patch rejected: {e}", None, 0
        decision = "KEPT" if keep else "REVERTED"
        history.append(f"iter {k}: patched {p['task']}.{p['routine']} ({nchg} lines) -> {decision}: {reason.split(', held-out')[0]}")
        (d / "decision.json").write_text(json.dumps(dict(
            decision=decision, reason=reason, patch=p, old_routine=old, scenario=ev["scenario"], camera=ev["camera"],
            clip=ev["clip"].name, clip_t0=ev["clip_t0"], clip_t1=ev["clip_t1"], truth_t=ev["truth_t"], truth_event=ev["truth_event"],
            failure_time_s=out["failure_time_s"], observations=out["observations"], root_cause=out["root_cause"],
            expected_effect=out["expected_effect"], changed_lines=nchg,
            tried=None if cs is None else dict(cpr=cs["cpr"], heldout=cs["heldout"], progress=cs["progress"], violations=cs["violations"],
                                               cycle_time=cs["cycle_time"], rows=rows_brief(cs["rows"]),
                                               heldout_rows=rows_brief(cs["heldout_rows"]))), indent=1, default=str))
        if keep:
            prog, s, fails = cand, cs, 0
            save_prog(prog, d)
        else:
            fails += 1
        metrics.append(dict(iter=k, cpr=s["cpr"], heldout=s["heldout"], progress=s["progress"], fault_pass=s["fault_pass"], violations=s["violations"],
                            cycle_time=s["cycle_time"], kept=keep, decision=decision, reason=reason,
                            tried=None if cs is None else cs["cpr"], tried_heldout=None if cs is None else cs["heldout"],
                            note=f"{p['task']}.{p['routine']}", scenario=ev["scenario"], latency_s=meta["latency_s"],
                            tokens=meta["usage"].get("total_token_count"), pin_error_s=round(abs(out["failure_time_s"] - ev["truth_t"]), 2),
                            rows=rows_brief(s["rows"]), heldout_rows=rows_brief(s["heldout_rows"])))
        (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
        emit(dict(ev="iteration", **metrics[-1]))
        if fails >= 3: emit(dict(ev="done", reason="3 consecutive rejections")); break
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (run_dir / "run.json").write_text(json.dumps(dict(wall_s=round(time.time() - t_run, 1), thinking=thinking, start=str(start) if start else None,
                                                      iterations=len(metrics) - 1, final_cpr=s["cpr"], final_heldout=s["heldout"]), indent=1))
    return metrics


def single_pass_trials(n, thinking):
    """n independent single passes (parallel), each scored on both suites -> runs/single_pass_<ts>/."""
    out = ROOT / f"runs/single_pass_{time.strftime('%Y%m%d_%H%M%S')}"
    def one(i):
        d = out / f"trial{i}"
        prog, changes, meta = single_pass(d, thinking, label="iter00_single_pass")
        save_prog(prog, d / "iter00")
        s = evaluate(prog)
        return dict(trial=i, cpr=s["cpr"], heldout=s["heldout"], nominal=s["nominal"][0], violations=s["violations"],
                    latency_s=meta["latency_s"], dir=str((d / "iter00").relative_to(ROOT)), changes=len(changes))
    with cf.ThreadPoolExecutor(n) as ex:
        rows = list(ex.map(one, range(n)))
    (out / "trials.json").write_text(json.dumps(rows, indent=1))
    for r in rows: print(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--port-thinking", default="medium")
    ap.add_argument("--start", help="iter00 dir of a cached single-pass program")
    ap.add_argument("--resume", help="existing run dir (re-uses its iter00)")
    ap.add_argument("--out", help="run dir to create")
    ap.add_argument("--single-pass-only", action="store_true")
    ap.add_argument("--trials", type=int, default=3)
    a = ap.parse_args()
    if a.single_pass_only: return single_pass_trials(a.trials, a.port_thinking)
    run_dir = pathlib.Path(a.resume or a.out or ROOT / f"runs/loop_{time.strftime('%Y%m%d_%H%M%S')}")
    log = lambda e: print(time.strftime("%H:%M:%S"), json.dumps({k: v for k, v in e.items() if k not in ("rows", "heldout_rows")}, default=str)[:400], flush=True)
    m = run(run_dir, a.iters, a.thinking, a.port_thinking, start=a.start, emit=log)
    print("CPR by iteration:", [f"{x['cpr']:.0%}" for x in m], " held-out:", [f"{x['heldout']:.0%}" for x in m], "->", run_dir)


if __name__ == "__main__":
    main()
