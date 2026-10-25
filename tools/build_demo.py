"""Build demo_bundle/: everything the dashboard and the demo video show, from recorded runs. Nobody edits numbers by hand.

    python tools/build_demo.py --loop runs/loop_final_d --repeats runs/loop_final_a,runs/loop_final_b,runs/loop_final_c \
        --single runs/single_pass_20261025_152644 [--mc runs/mc_X] [--agents runs/agents_X] [--skip-render] [--force]

Output: demo_bundle/bundle.json (what the dashboard reads), traces.json (gripper traces of the 218 real episodes),
media/ (cinema clips + events sidecars, Argon's own clips, footage links) and manifest.json (every asset: producer,
sha256, kind = measured | precomputed | reference).
"""
import argparse, difflib, functools, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import stage1, sensor  # noqa: E402
from loop.run_loop import load_prog, routine_diff, CELL_FACTS  # noqa: E402
from loop.score import human_port_programs, human_port_bases, executed_target_error, target_error_vs_human, world_targets  # noqa: E402
from simulation.cell import irb_cell, gofa_cell  # noqa: E402
from simulation.scenarios import SUITE, HELD_OUT, legacy_programs, run_scenario, run_suite, oracle  # noqa: E402

B = ROOT / "demo_bundle"
MEDIA = B / "media"
ASSETS = []
RENDER = True   # False (--skip-render): reuse clips already on disk, never render
HD, SD = (1920, 1080), (1280, 720)
LABELS = dict(sim_fault="simulation-only fault", sensor="proposed sensor (DI_GRIP_OK), approved by the engineer",
              footage="footage: teleoperated Franka, a different cell", human="human port held out, scoring only",
              geometry="placeholder cell geometry (from CAD bounding boxes and legacy targets)")
log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()[:16]


def asset(p, producer, kind):
    if p is None: return None
    p = pathlib.Path(p)
    ASSETS.append(dict(path=str(p.relative_to(B)), producer=producer, kind=kind, bytes=p.stat().st_size if p.exists() else None,
                       sha256=sha(p) if p.exists() and p.stat().st_size < 400e6 else None,
                       created_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)) if p.exists() else None))
    return str(p.relative_to(B))


def rel(p): return str(pathlib.Path(p).relative_to(B))


# ---------------------------------------------------------------- cameras (MuJoCo free cameras, metres)
def cams():
    from simulation.render import free_camera as fc
    return {
        "orbit": lambda u: fc([-1.35, -3.0, 0.1], 4.7, 58 + 34 * u, -24),
        "orbit_wide": lambda u: fc([-1.35, -3.0, 0.05], 5.4, 48 + 30 * u, -28),
        "r1": lambda u: fc([-2.85, -3.0, 0.12], 2.35, 62 + 6 * u, -31),
        "r1_conv": lambda u: fc([-2.45, -3.0, 0.12], 2.9, 70 + 5 * u, -30),
        "r2": lambda u: fc([0.2, -2.95, 0.15], 2.35, 112 - 6 * u, -31),
        "ghosts": lambda u: fc([0.0, -4.7, 0.0], 9.2 - 1.0 * u, 72 + 14 * u, -46),
        "reference": lambda u: fc([-1.35, -2.95, 0.0], 5.6, 62, -33),
    }


def scenario(sid):
    return next(s for s in SUITE + HELD_OUT if s["id"] == sid)


def render_clip(name, prog, rigs_fn, sc_id, cam, t0=0.0, t1=None, size=SD, markers=True, force=False, still_at=None, trail=True):
    """Cinema clip of one scenario run (deterministic twin). Cached unless --force."""
    from simulation.render import cinema_clip, event_markers
    out = MEDIA / f"{name}.mp4"
    if out.exists() and not force and out.with_suffix(".events.json").exists():
        return out
    if not RENDER: return None
    w, ends, res = run_scenario(prog, rigs_fn, scenario(sc_id), record_every=1)
    t1 = min(w.now, t1) if t1 else w.now
    mk = event_markers(w, {k: np.array(v) for k, v in oracle()["destinations"].items()}) if markers else []
    t = time.time()
    cinema_clip(w, out, cams()[cam], t0=t0, t1=t1, markers=mk, width=size[0], height=size[1], still_at=still_at or (t0 + t1) / 2, trail=trail)
    side = json.loads(out.with_suffix(".events.json").read_text())
    side.update(scenario=sc_id, result=dict(passed=res["passed"], why=res["why"]), camera=cam)
    out.with_suffix(".events.json").write_text(json.dumps(side, indent=1))
    log(f"  rendered {out.name} ({t1 - t0:.0f}s of sim) in {time.time() - t:.0f}s")
    return out


def static_clip(name, rigs, markers, cam, seconds=6.0, size=SD, force=False):
    """A still cell (no program running) with markers and a moving camera."""
    import imageio
    from simulation.cell import World
    from simulation.render import Renderer
    out = MEDIA / f"{name}.mp4"
    if out.exists() and not force: return out
    if not RENDER: return None
    w = World(rigs); w.snapshot()
    rr = Renderer(w, look="cinema", markers=markers, width=size[0], height=size[1])
    wr = imageio.get_writer(out, fps=30, codec="libx264", quality=8, macro_block_size=8, pixelformat="yuv420p",
                            ffmpeg_params=["-movflags", "+faststart"])
    n = int(seconds * 30)
    for i in range(n):
        img = rr.frame(w.snapshots[0], cams()[cam](i / (n - 1)))
        wr.append_data(img)
        if i == n // 2: imageio.imwrite(out.with_suffix(".jpg"), img, quality=90)
    wr.close(); rr.close()
    return out


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------- beat 2: evidence
def token_split():
    """Split the unified call's text tokens into telemetry vs code (countTokens is free). Cached."""
    p = ROOT / "derived/token_split.json"
    if p.exists(): return json.loads(p.read_text())
    from loop import argon_client
    c = argon_client.client()
    tele = "=== TELEMETRY\n" + stage1.TELEMETRY.read_text()
    code = "=== LEGACY CODE\n" + "\n".join(f"=== {q.relative_to(ROOT)}\n{q.read_text(errors='replace')}" for q in sorted(stage1.LEGACY_CODE.rglob("*"))
                                           if q.suffix in {".mod", ".sys", ".cfg", ".c", ".h", ".var", ".typ"} and "CRB_15000" not in str(q) and "GoFa" not in str(q))
    out = dict(telemetry=c.models.count_tokens(model="gemini-4-argon", contents=tele).total_tokens,
               code=c.models.count_tokens(model="gemini-4-argon", contents=code).total_tokens)
    p.write_text(json.dumps(out, indent=1))
    return out


def evidence(skip_render, force):
    s1, sens = stage1.load(), sensor.load()
    rule_flags = {f["seg"] for f in sens["verification"]["flagged"]}
    segs = {s["segment_index"]: s for s in stage1.segments()}
    traces = {}
    for seg, s in segs.items():
        obs, act = stage1.gripper(s)
        traces[seg] = dict(obs=np.round(obs, 3).tolist(), act=np.round(act, 3).tolist())
    (B / "traces.json").write_text(json.dumps(dict(fps=stage1.FPS, episodes=traces), separators=(",", ":")))
    asset(B / "traces.json", "tools/build_demo.py (robot_logs/*.parquet)", "reference")
    eps = [dict(e, rule=e["seg"] in rule_flags) for e in s1["episodes"]]
    mods = s1["source"]["tokens_by_modality"]; split = token_split()
    text_total = mods.get("TEXT", 0)
    tele = round(text_total * split["telemetry"] / (split["telemetry"] + split["code"]))
    tokens = dict(total=s1["source"]["prompt_tokens"], video=mods.get("VIDEO", 0), telemetry=tele, code=text_total - tele)
    # footage: the shift itself (symlink) and the first real missed grasp Argon flagged
    shift = MEDIA / "shift.mp4"
    if not shift.exists(): os.symlink(stage1.SHIFT, shift)
    asset(shift, "inputs_v2/video/shift_v2.mp4 (symlink)", "reference")
    first = next(f for f in s1["flags"] if f["type"] == "missed_grasp")
    ep = next(e for e in eps if e["seg"] == first["seg"])
    real = MEDIA / "real_missed_grasp.mp4"
    if not real.exists() or force:
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{ep['t0']:.2f}", "-to", f"{ep['t1']:.2f}", "-i", str(stage1.SHIFT),
                        "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(real)], check=True)
    asset(real, "ffmpeg cut of shift_v2.mp4", "reference")
    legacy = legacy_programs()
    r1, r2 = legacy["R1"][1].splitlines(), legacy["R2"][1].splitlines()
    find = lambda lines, pat, after=0: next(i + 1 for i, l in enumerate(lines) if i >= after and pat in l)
    k = find(r1, "PulseDO DO_ATT_TAB;")
    hz = s1["legacy_hazard"]; a, b = (int(x) for x in re.findall(r"\d+", hz["lines"])[:2])
    p0 = find(r2, "PROC PP_TAB_CONV"); p1 = find(r2, "ENDPROC", p0)
    code = dict(R1=dict(file="T_ROB1/Module1.mod", lines=r1, focus=[k - 3, k + 3], lit=[k, k + 1], note="grip pulse, fixed wait, no check"),
                R2=dict(file="T_ROB2/Module1.mod", lines=r2, focus=[p0, p1], lit=[find(r2, "PulseDO DO_SG_P;", p0), find(r2, "PulseDO DO_ATT_TTAB;", p0)],
                        note=f"Argon cited {pathlib.Path(hz['file']).parts[-3]}/Module1.mod lines {hz['lines']} (PROC PP_TAB_CONV; "
                             f"the routine spans {p0}-{p1}, so the line numbers are off by {a - p0})"))
    twin_miss = None
    return dict(source=s1["source"], video_only=s1["video_only"], tokens=tokens, flags=s1["flags"], episodes=eps,
                agreement=s1["agreement"], counts=s1["counts"], disagreements=s1["disagreements"],
                hazard=dict(file=hz["file"].split("references/")[-1], lines=hz["lines"], why=hz["why"], guarded_rapid=hz["guarded_rapid"]),
                code=code, real_clip=rel(real), real_clip_seg=first["seg"], real_clip_evidence=first["evidence"],
                shift=rel(shift), hidden_regrasp=[f["seg"] for f in s1["flags"] if "re_grasp" in f["type"]],
                sensor=dict(proposal=sens["proposal"], verification=sens["verification"], approval=sens.get("approval", {}),
                            call=sens.get("call"))), twin_miss


# ---------------------------------------------------------------- beat 3: twin
def twin(single_dir, skip_render, force):
    single = load_prog(single_dir)
    legacy = legacy_programs()
    rigs = gofa_cell()
    ghosts, truth = [], []
    for r in ("R1", "R2"):
        tw = world_targets(legacy[r][1], rigs[r].base_pos, rigs[r].base_quat, False)
        tr = world_targets(legacy[r][1], rigs[r].base_pos, rigs[r].base_quat, True)
        for n in tw:
            if n == "Target_HOME": continue
            ghosts.append(dict(kind="ghost", pos=tw[n].tolist(), t_on=0.0, label=f"{r} {n} (verbatim)"))
            truth.append(dict(kind="dot", pos=tr[n].tolist(), t_on=0.0, label=f"{r} {n} (intended)"))
            truth.append(dict(kind="link", pos=dict(**{"from": tr[n].tolist(), "to": tw[n].tolist()}), t_on=0.0, label=""))
    cp2 = json.loads((ROOT / "runs/cp2/report.json").read_text())
    verb = next(v for k, v in cp2.items() if "verbatim" in k)["summary"]
    terr = target_error_vs_human(legacy, gofa_cell())
    out = dict(verbatim=dict(moves=verb["moves"], unreachable=verb["unreachable"], target_err=terr, n_ghosts=len(ghosts)),
               single=dict(target_err=executed_target_error(single, gofa_cell)),
               reference_images=[], labels=[LABELS["geometry"]])
    for f in ("3_1.png", "1_1.PNG"):
        src = ROOT / "third_party/rparak_station/images" / f
        if src.exists():
            from PIL import Image
            dst = MEDIA / f"reference_{f.split('.')[0]}.jpg"
            if not dst.exists():
                im = Image.open(src).convert("RGB"); im.thumbnail((1920, 1080)); im.save(dst, quality=88)
            out["reference_images"].append(asset(dst, "RobotStudio station screenshot (R. Parak, MIT)", "reference"))
    log("twin clips")
    out["hero_legacy"] = asset(render_clip("hero_legacy", legacy, irb_cell, "nominal", "orbit", size=HD, force=force, still_at=6.0),
                               "cinema: legacy RAPID @ IRB 1200, nominal", "measured")
    out["verbatim_ghosts"] = asset(static_clip("verbatim_ghosts", gofa_cell(), ghosts + truth, "ghosts", force=force),
                                   "cinema: verbatim targets read in the GoFa base frame", "measured")
    out["single_nominal"] = asset(render_clip("single_nominal", single, gofa_cell, "nominal", "orbit_wide", force=force, still_at=12.0),
                                  "cinema: Argon single pass @ GoFa, nominal", "measured")
    out["single_silent"] = asset(render_clip("single_silent", single, gofa_cell, "r1_tray_miss_once", "r1_conv", t0=1.0, t1=26.0,
                                             force=force, still_at=12.0), "cinema: Argon single pass, injected missed grasp", "measured")
    out["reference_render"] = asset(static_clip("twin_reference_angle", gofa_cell(), [], "reference", seconds=1.0, force=force),
                                    "cinema: twin from the reference angle", "measured")
    return out


# ---------------------------------------------------------------- beat 4: loop
def loop_run(run_dir, key, primary, single_root, mc, skip_render, force):
    run_dir = pathlib.Path(run_dir).resolve()
    metrics = json.loads((run_dir / "metrics.json").read_text())
    info = json.loads((run_dir / "run.json").read_text()) if (run_dir / "run.json").exists() else {}
    its = []
    sp = run_dir / "iter00_single_pass.response.json"
    spm = run_dir / "iter00_single_pass.manifest.json"
    its.append(dict(metrics[0], kind="single_pass", changes=json.loads(sp.read_text())["changes"] if sp.exists() else [],
                    latency_s=json.loads(spm.read_text())["latency_s"] if spm.exists() else None))
    prog = load_prog(run_dir / "iter00")
    mdir = MEDIA / f"loop_{key}"; mdir.mkdir(parents=True, exist_ok=True)
    for m in metrics[1:]:
        d = run_dir / f"iter{m['iter']:02d}"
        dec = json.loads((d / "decision.json").read_text())
        man = json.loads((d / f"iter{m['iter']:02d}_critique.manifest.json").read_text())
        clip = mdir / f"iter{m['iter']:02d}_argon.mp4"
        if not clip.exists() or force: shutil.copy(d / dec["clip"], clip)
        it = dict(m, kind="patch", scenario=dec["scenario"], camera=dec["camera"], argon_clip=asset(clip, f"{d.relative_to(ROOT)} (what Argon saw)", "measured"),
                  clip_t0=dec["clip_t0"], failure_time_s=dec["failure_time_s"], truth_t=dec["truth_t"], truth_event=dec.get("truth_event"),
                  observations=dec["observations"], root_cause=dec["root_cause"], expected_effect=dec["expected_effect"],
                  patch=dict(task=dec["patch"]["task"], routine=dec["patch"]["routine"], rationale=dec["patch"]["rationale"]),
                  diff=routine_diff(dec.get("old_routine"), dec["patch"]["new_routine"]), changed_lines=dec.get("changed_lines"),
                  tried_detail=dec.get("tried"), usage=man.get("usage", {}), parts=man.get("parts", []))
        if primary and dec["decision"] == "KEPT":
            cand = load_prog(d)
            robot = scenario(dec["scenario"]).get("robot") or "R1"
            cam = "r1" if robot == "R1" else "r2"
            t0 = max(0.0, dec["clip_t0"]); t1 = t0 + 16.0
            out = render_clip(f"loop_{key}/iter{m['iter']:02d}_after", cand, gofa_cell, dec["scenario"], cam, t0=t0, t1=t1, force=force,
                              still_at=t0 + dec["truth_t"] + 3.0)
            it["after_clip"] = asset(out, f"cinema: kept program after iteration {m['iter']} on {dec['scenario']}", "measured")
            it["after_events"] = rel(out.with_suffix(".events.json")) if out else None
            befo = render_clip(f"loop_{key}/iter{m['iter']:02d}_before", prog, gofa_cell, dec["scenario"], cam, t0=t0, t1=t1, force=force,
                               still_at=t0 + dec["truth_t"] + 3.0)
            it["before_clip"] = asset(befo, f"cinema: program before iteration {m['iter']} on {dec['scenario']}", "measured")
            it["before_events"] = rel(befo.with_suffix(".events.json")) if befo else None
        if dec["decision"] == "KEPT": prog = load_prog(d)
        its.append(it)
    if mc and mc.get("run") and pathlib.Path(mc["run"]).name == run_dir.name:
        per = {r["iter"]: r for r in mc["per_iteration"]}
        for it in its: it["mc"] = per.get(it["iter"])
    final = max(m["iter"] for m in metrics if m["kept"])
    return dict(key=key, dir=str(run_dir.relative_to(ROOT)), start=info.get("start"), wall_s=info.get("wall_s"),
                iterations=its, final_iter=final, final_cpr=metrics[-1]["cpr"], final_heldout=metrics[-1]["heldout"])


# ---------------------------------------------------------------- beat 5: proof
def proof(final_dir, single_dir, mc, skip_render, force):
    looped, single, legacy, human = load_prog(final_dir), load_prog(single_dir), legacy_programs(), human_port_programs()
    human_rigs = functools.partial(gofa_cell, human_port_bases())
    cols = [("verbatim", "Verbatim copy", legacy, gofa_cell), ("single", "Argon single pass", single, gofa_cell),
            ("looped", "Argon looped", looped, gofa_cell), ("human", "Engineer's port (held out)", human, human_rigs)]
    mc_names = {"verbatim": "verbatim copy @ GoFa", "single": "Argon single pass", "looped": "Argon looped", "human": "human port (held out)"}
    board = []
    for key, name, prog, fn in cols:
        s = run_suite(prog, fn, verbose=False); h = run_suite(prog, fn, suite=HELD_OUT, verbose=False)
        te = (target_error_vs_human(prog, fn()) if key == "verbatim" else executed_target_error(prog, fn)) if key != "human" else None
        board.append(dict(key=key, name=name, cpr=s["cpr"], nominal=bool(s["nominal"][0]), fault_pass=s["fault_pass"], faults=len(SUITE) - 1,
                          heldout=h["cpr"], heldout_pass=sum(r["passed"] for r in h["rows"]), heldout_n=len(HELD_OUT), violations=s["violations"],
                          rows=[dict(id=r["id"], passed=r["passed"], why=r["why"]) for r in s["rows"]],
                          heldout_rows=[dict(id=r["id"], passed=r["passed"], why=r["why"]) for r in h["rows"]],
                          target_err=te, mc=(mc or {}).get("programs", {}).get(mc_names[key])))
        log(f"  scoreboard {name}: CPR {s['cpr']:.0%} held-out {h['cpr']:.0%}")
    legacy_irb = run_suite(legacy, irb_cell, verbose=False)
    out = dict(scoreboard=board, reference_lines=dict(legacy_irb=legacy_irb["cpr"]),
               mc_meta=dict(n=(mc or {}).get("n"), p=[0.06, 0.01], note="per-grasp miss probability; 6% = Stage 1's rate on real teleoperated footage (a different cell)",
                            legacy_irb=(mc or {}).get("programs", {}).get("legacy @ IRB 1200")),
               labels=[LABELS["human"], LABELS["sim_fault"]])
    log("proof clips")
    out["split"] = dict(
        human=asset(render_clip("split_human", human, human_rigs, "r1_tray_miss_once", "r1_conv", t0=1.0, t1=27.0, force=force, still_at=14.0),
                    "cinema: engineer's port, r1_tray_miss_once", "measured"),
        looped=asset(render_clip("split_looped", looped, gofa_cell, "r1_tray_miss_once", "r1_conv", t0=1.0, t1=27.0, force=force, still_at=14.0),
                     "cinema: Argon looped, r1_tray_miss_once", "measured"),
        scenario="r1_tray_miss_once")
    out["split"]["human_events"] = rel(MEDIA / "split_human.events.json")
    out["split"]["looped_events"] = rel(MEDIA / "split_looped.events.json")
    alw = render_clip("looped_always", looped, gofa_cell, "r1_part_miss_always", "r1", t0=8.0, t1=24.0, force=force, still_at=16.0)
    out["safe_stop"] = dict(clip=asset(alw, "cinema: Argon looped, r1_part_miss_always", "measured"), events=rel(alw.with_suffix(".events.json")) if alw else None)
    out["hero_gofa"] = asset(render_clip("hero_gofa", looped, gofa_cell, "nominal", "orbit", size=HD, force=force, still_at=8.0),
                             "cinema: Argon looped @ GoFa, nominal", "measured")
    return out


def handoff(final_dir):
    d = MEDIA / "handoff"; d.mkdir(parents=True, exist_ok=True)
    prog, files = load_prog(final_dir), []
    notes = ["Requires the approved grip-confirmation input DI_GRIP_OK (1 = part held) on each GoFa."]
    if any(re.search(r"Conf[JL]\s*\\Off", prog[r][1]) for r in prog):
        notes.append("Configuration monitoring is switched off (ConfJ\\Off / ConfL\\Off) where the legacy code had confdata: the controller "
                     "picks the nearest configuration. Verify the chosen configurations at the first slow run.")
    if any("uframe" in prog[r][1] for r in prog):
        notes.append("The world-to-base work object (wobj_world) is corrected at runtime in INIT_PARAM; fold the corrected uframe into "
                     "the declaration before release.")
    for r, task in (("R1", "T_ROB1"), ("R2", "T_ROB2")):
        p = d / f"{task}_Module1.mod"; p.write_text(prog[r][1]); files.append(asset(p, f"Argon looped ({final_dir})", "measured"))
    rep = ROOT / "runs/report/MIGRATION_REPORT.md"
    if rep.exists():
        shutil.copy(rep, d / "MIGRATION_REPORT.md"); files.append(asset(d / "MIGRATION_REPORT.md", "loop/report.py (Argon)", "measured"))
    return dict(files=files, notes=notes)


def calls(runs):
    out = []
    u = json.loads(stage1.UNIFIED.read_text())
    out.append(dict(label="stage1_unified", what="Stage 1: shift video + telemetry + legacy code in one context", latency_s=round(u["gen_s"], 1),
                    usage=u["usage"], parts=[dict(kind="video", source="shift_v2.mp4 @ 3 fps"), dict(kind="text", source="telemetry 5 Hz (218 episodes)"),
                                             dict(kind="text", source="legacy RAPID + PLC code")], quarantine="no answer-key paths (GoFa files excluded by path)"))
    for p in sorted(ROOT.glob("runs/sensor_*/sensor_proposal.manifest.json"))[-1:]:
        out.append(dict(json.loads(p.read_text()), what="Sensor proposal from Stage 1"))
    for rd in runs:
        for p in sorted(pathlib.Path(rd).rglob("*.manifest.json")):
            m = json.loads(p.read_text()); m["what"] = "single-pass port" if "single_pass" in p.name else f"critique + patch ({p.parent.name})"
            m["run"] = pathlib.Path(rd).name; out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", required=True); ap.add_argument("--repeats", default="")
    ap.add_argument("--single", required=True, help="runs/single_pass_<ts> (trials)")
    ap.add_argument("--mc"); ap.add_argument("--agents")
    ap.add_argument("--skip-render", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    global RENDER
    RENDER = not a.skip_render
    B.mkdir(exist_ok=True); MEDIA.mkdir(exist_ok=True)
    loop_dir = pathlib.Path(a.loop).resolve()
    a.single = str(pathlib.Path(a.single).resolve())
    trials = json.loads((pathlib.Path(a.single) / "trials.json").read_text())
    clean = next(t for t in trials if t["nominal"])
    single_dir = ROOT / clean["dir"]
    mcp = pathlib.Path(a.mc) if a.mc else max(ROOT.glob("runs/mc_*/mc.json"), default=None, key=lambda p: p.stat().st_mtime)
    if mcp and mcp.is_dir(): mcp = mcp / "mc.json"
    mc = json.loads(mcp.read_text()) if mcp and mcp.exists() else None
    agp = pathlib.Path(a.agents) / "agents.json" if a.agents else max(ROOT.glob("runs/agents_*/agents.json"), default=None, key=lambda p: p.stat().st_mtime)
    log("evidence"); ev, _ = evidence(a.skip_render, a.force)
    log("twin"); tw = twin(single_dir, a.skip_render, a.force)
    log("loop runs")
    runs = {"primary": loop_run(loop_dir, loop_dir.name.split("_")[-1], True, a.single, mc, a.skip_render, a.force)}
    for r in [x for x in a.repeats.split(",") if x]:
        runs[pathlib.Path(r).name.split("_")[-1]] = loop_run(r, pathlib.Path(r).name.split("_")[-1], False, a.single, mc, True, a.force)
    final_dir = loop_dir / f"iter{runs['primary']['final_iter']:02d}"
    log("proof"); pr = proof(final_dir, single_dir, mc, a.skip_render, a.force)
    bundle = dict(
        meta=dict(built_at=time.strftime("%Y-%m-%d %H:%M:%S"), git=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
                  primary_run=runs["primary"]["dir"], mc=str(mcp.relative_to(ROOT)) if mcp else None, labels=LABELS, model="gemini-4-argon"),
        persona=dict(role="Manufacturing automation engineer", task="Replace two ABB IRB 1200s (15-year-old RAPID) with ABB GoFa CRB 15000 cobots",
                     deadline="by Monday", inputs=["19 min of shift footage", "218 robot logs", "legacy RAPID + PLC code"]),
        cell_facts=CELL_FACTS, evidence=ev, twin=tw,
        single_pass_trials=[dict(t, dir=t["dir"]) for t in trials], runs=runs, proof=pr,
        suite=[dict(id=s["id"], kind=s["kind"]) for s in SUITE], heldout_suite=[dict(id=s["id"], kind=s["kind"]) for s in HELD_OUT],
        agents=json.loads(agp.read_text()) if agp and agp.exists() else None,
        calls=calls([loop_dir, ROOT / clean["dir"]]),
        handoff=handoff(final_dir))
    (B / "bundle.json").write_text(json.dumps(bundle, indent=1, default=str))
    asset(B / "bundle.json", "tools/build_demo.py", "measured")
    (B / "manifest.json").write_text(json.dumps(dict(built_at=bundle["meta"]["built_at"], assets=ASSETS), indent=1))
    log(f"bundle -> {B} ({len(ASSETS)} assets)")


if __name__ == "__main__":
    main()
