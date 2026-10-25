"""Managed Agents doing real work (PLAN_NEW Phase D): one parallel fan-out of custom Argon agents in remote sandboxes.

    python loop/agents.py [--looped runs/loop_final_a/iter04] [--mc 200]      -> runs/agents_<ts>/agents.json

Roles (all at once):
- log-verifier: re-checks Argon's proposed grip rule (derived/sensor.json) and Stage 1's flags (derived/stage1.json)
  on all 218 real episode logs, mounted into the sandbox as an inline source; the agent writes and runs its own script.
- commissioner x3 (legacy@IRB, Argon single-pass@GoFa, Argon looped@GoFa): clones the public code at a pinned commit,
  rebuilds the robot models from the public ROS descriptions, runs tools/commission.py (training + held-out suites,
  seeded Monte Carlo, proof clip) and writes a commissioning note.
The human GoFa port is never sent anywhere (answer-key quarantine). Every agent input (text and mounted files) passes
argon_client.check_quarantine. Each result is compared with the same computation run locally on the same commit.
"""
import argparse, base64, concurrent.futures as cf, gzip, json, os, pathlib, re, subprocess, sys, tarfile, io, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client, stage1  # noqa: E402

BASE_AGENT = "antigravity-preview-09-2026"
COMMIT = "ca2740c"
REPO = "https://github.com/Sami1309/argon-hack.git"
API = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_S = 1200
PROGRAMS = {  # label -> (program dir or None for legacy, cell)
    "legacy@IRB": (None, "irb"),
    "argon_single_pass@GoFa": (ROOT / "runs/single_pass_20261025_152644/trial1/iter00", "gofa"),
    "argon_looped@GoFa": (ROOT / "runs/loop_final_a/iter04", "gofa"),
}

SETUP_SH = f"""#!/bin/bash
# Rebuild the twin from public sources only (pinned commits). Nothing private is needed.
set -euo pipefail
cd /workspace
[ -d repo ] || git clone -q {REPO} repo
git -C repo checkout -q {COMMIT}
mkdir -p repo/third_party
if [ ! -d repo/third_party/abb_ros2 ]; then
  git clone -q --filter=blob:none --sparse https://github.com/PickNikRobotics/abb_ros2 repo/third_party/abb_ros2
  git -C repo/third_party/abb_ros2 checkout -q e6486f7
  git -C repo/third_party/abb_ros2 sparse-checkout set robot_specific_config/abb_irb1200_support
fi
if [ ! -d repo/third_party/abb_gofa_robot ]; then
  git clone -q https://github.com/byeongkyu/abb_gofa_robot repo/third_party/abb_gofa_robot
  git -C repo/third_party/abb_gofa_robot checkout -q 6b4f2d7
fi
pip install -q mujoco==3.17.0 numpy scipy imageio imageio-ffmpeg pillow PyOpenGL 2>&1 | tail -2 || true
(apt-get install -y -q libosmesa6 >/dev/null 2>&1) || true
cd repo && python tools/build_robot_mjcf.py
echo SETUP_OK
"""

COMMISSIONER_TASK = """You are the independent COMMISSIONING ENGINEER for a robot-cell migration (two legacy ABB IRB 1200 robots being
replaced by ABB GoFa cobots). You did not write the program under test. Your job: rebuild the digital twin from public
sources, commission the program, and report what you measured. Do not modify the program or the twin.

Files mounted in this sandbox:
- /workspace/in/setup.sh       clones the public twin code (pinned commit) + public ROS robot descriptions, builds models
- /workspace/in/commission.py  runs the training suite, the held-out suite, a seeded Monte Carlo and renders a proof clip
- /workspace/in/program/       the RAPID program under test: {program_label} (R1_/R2_ CalibData.mod + Module1.mod)

Steps:
1. bash /workspace/in/setup.sh   (if a step fails, diagnose and fix the environment, e.g. missing system libraries)
2. cd /workspace/repo && MUJOCO_GL=osmesa python /workspace/in/commission.py --repo /workspace/repo \\
     --program /workspace/in/program --cell {cell} --mc {mc} --p 0.06 --workers $(nproc) --out /workspace/out --clip
3. Read /workspace/out/results.json. Open the program and look at how it handles a failed grasp (is the grip confirmed?
   what happens if it is not?). Write /workspace/out/commissioning_note.md (max 12 lines): verdict (ready / not ready for
   production), the evidence (pass rates, Monte Carlo silent bad boxes), and the routine/line that explains it.
4. Reply with ONLY one JSON object, no prose:
{{"program": "{program_label}", "cpr": num, "heldout": num, "nominal": bool, "fault_pass": int, "violations": int,
 "rows": [{{"id": str, "passed": bool, "why": str}}], "heldout_rows": [...same...], "monte_carlo": {{...as in results.json}},
 "clip_path": str|null, "clip_error": str|null, "verdict": "ready"|"not ready", "note": str}}
Copy the numbers exactly from results.json; if a step failed, say so in note and use null rather than guessing."""

VERIFIER_TASK = """You are an independent LOG VERIFIER. Another model (Argon) watched 19 minutes of real robot footage and proposed a
grip-confirmation rule. Check it yourself against all 218 real episode logs by writing and running your own script.

Files mounted in this sandbox:
- /workspace/in/episodes.json.gz  {{"segments": [{{"seg", "label", "dataset_kind", "obs", "act"}}]}} for 218 episodes.
  obs = measured gripper position, act = commanded gripper position, both in PERCENT (round(100*x); 0 open .. 100
  fully closed), one row per 15 Hz frame. label = dataset label ("success", "missed_grasp", or another failure type).
- /workspace/in/rule.json         Argon's proposed rule (thresholds as fractions 0..1)
- /workspace/in/stage1_flags.json Argon's Stage 1 flags: episodes (seg) it called failures, with its type

Task:
1. Implement the rule exactly: an episode is FLAGGED if any frame has act >= 100*commanded_closed_min AND
   obs >= 100*closed_on_nothing_min (integers, >= comparisons).
2. Confusion matrix over three groups: missed_grasp, other_failure (any other non-success label), success.
3. For every flagged episode: seg, label, peak obs while commanded closed, the frame index of the first trigger, and
   one sentence of evidence from the trace (e.g. "closes to 96% while commanded 100%; a held block stalls near 55%").
4. Agreement with Stage 1: compare the flagged set with Stage 1 flags whose type contains "missed_grasp".
5. For any SUCCESS that is flagged, look at its trace and say whether it looks like a genuine missed grasp followed by a
   re-grasp (closure high, reopen, close again to ~50%).
Save your script as /workspace/out/verify_rule.py and its output as /workspace/out/verification.json.
Reply with ONLY one JSON object, no prose:
{{"rule": str, "confusion": {{"missed_grasp": {{"flagged": int, "total": int}}, "other_failure": {{...}}, "success": {{...}}}},
 "flagged": [{{"seg": int, "label": str, "peak_obs_pct": int, "first_trigger_frame": int, "evidence": str}}],
 "stage1_agreement": {{"stage1_missed_grasp_segs": [int], "rule_flagged_segs": [int], "both": [int], "stage1_only": [int], "rule_only": [int]}},
 "success_flagged_review": str, "verdict": str}}"""


# ---------------------------------------------------------------- inputs
def b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


def episode_table():
    segs, lab = stage1.segments(), stage1.labels()
    rows = []
    for s in segs:
        o, a = stage1.gripper(s)
        rows.append(dict(seg=s["segment_index"], label=lab[s["uuid"]]["failure_type"] if s["uuid"] in lab else s["kind"],
                         dataset_kind=s["kind"], obs=[int(round(x * 100)) for x in o], act=[int(round(x * 100)) for x in a]))
    return rows


def program_files(label, src_dir, run_dir):
    if src_dir is None:  # the legacy input program (D1), written out so the sandbox and the local reference share it
        from simulation.scenarios import legacy_programs
        src_dir = run_dir / "programs" / "legacy"
        src_dir.mkdir(parents=True, exist_ok=True)
        for r, (cal, mod) in legacy_programs().items():
            (src_dir / f"{r}_CalibData.mod").write_text(cal); (src_dir / f"{r}_Module1.mod").write_text(mod)
    return {f"{r}_{f}": (pathlib.Path(src_dir) / f"{r}_{f}").read_text() for r in ("R1", "R2") for f in ("CalibData.mod", "Module1.mod")}, src_dir


def guarded(text, sources):
    """Quarantine check over the input text AND the decoded content of every mounted source."""
    def decoded(s):
        raw = base64.b64decode(s["content"]) if s.get("encoding") == "base64" else s.get("content", "").encode()
        return (gzip.decompress(raw) if s["target"].endswith(".gz") else raw).decode(errors="ignore")
    blob = text + "\n".join(decoded(s) for s in sources)
    argon_client.check_quarantine(blob, [s["target"] for s in sources])
    return sum(len(s["content"]) for s in sources) + len(text)


# ---------------------------------------------------------------- local references (same code, same commit)
def local_verifier(rows, rule, flags):
    cmd, closed = int(round(100 * rule["commanded_closed_min"])), int(round(100 * rule["closed_on_nothing_min"]))
    groups = {"missed_grasp": [0, 0], "other_failure": [0, 0], "success": [0, 0]}
    flagged = []
    for r in rows:
        g = "success" if r["label"] == "success" else "missed_grasp" if r["label"] == "missed_grasp" else "other_failure"
        hit = any(a >= cmd and o >= closed for o, a in zip(r["obs"], r["act"]))
        groups[g][0] += hit; groups[g][1] += 1
        if hit: flagged.append(r["seg"])
    s1 = sorted(f["seg"] for f in flags if "missed_grasp" in f["type"])
    full = stage1.grip_rule(closed_on_nothing=rule["closed_on_nothing_min"], commanded=rule["commanded_closed_min"])
    return dict(confusion={k: dict(flagged=v[0], total=v[1]) for k, v in groups.items()}, rule_flagged_segs=sorted(flagged),
                stage1_missed_grasp_segs=s1, both=sorted(set(s1) & set(flagged)), stage1_only=sorted(set(s1) - set(flagged)),
                rule_only=sorted(set(flagged) - set(s1)), full_precision_by_label=full["by_label"])


def ref_tree(run_dir):
    """`git archive` of the pinned commit (read-only on the repo; no index/worktree changes) + local robot meshes."""
    d = run_dir / f"ref_{COMMIT}"
    if not d.exists():
        d.mkdir(parents=True)
        tar = subprocess.run(["git", "-C", str(ROOT), "archive", COMMIT], check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar)) as t: t.extractall(d, filter="data")
        (d / "models/assets").symlink_to(ROOT / "models/assets")
    return d


def local_commission(prog_dir, cell, mc, out):
    ref = ref_tree(out.parents[1])
    p = subprocess.run([sys.executable, str(ROOT / "tools/commission.py"), "--repo", str(ref), "--program", str(prog_dir),
                        "--cell", cell, "--mc", str(mc), "--p", "0.06", "--out", str(out)], capture_output=True, text=True, cwd=ref)
    if p.returncode: return dict(error=p.stderr[-1500:])
    return json.loads((out / "results.json").read_text())


# ---------------------------------------------------------------- remote
def parse_json(text):
    text = (text or "").strip()
    try: return json.loads(text)
    except ValueError: pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if m:
        try: return json.loads(m[1])
        except ValueError: pass
    return {"raw_text": text[:4000]}


def fetch_out(env_id, dest):
    """Download /workspace/out/* from the agent's environment (per-file endpoint)."""
    import requests
    H = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    got = []
    try:
        r = requests.get(f"{API}/environments/{env_id}/files/workspace/out", headers=H, timeout=60)
        for f in r.json().get("files", []) if r.ok else []:
            if f.get("type") != "FILE" or int(f.get("size_bytes", 0)) > 30_000_000: continue
            c = requests.get(f"{API}/environments/{env_id}/files/{f['path']}", params={"alt": "media"}, headers=H, timeout=300)
            if c.ok:
                p = dest / f["name"]; p.write_bytes(c.content); got.append(str(p.relative_to(ROOT)))
    except Exception as e:
        got.append(f"fetch error: {type(e).__name__}: {e}"[:300])
    return got


def run_agent(c, agent_id, job, run_dir, log):
    t = time.time()
    rec = dict(role=job["role"], label=job["label"], agent_id=agent_id, interaction_id=None, environment_id=None,
               duration_s=None, status=None, tokens=None, input_bytes=job["input_bytes"], output=None, files=[])
    try:
        i = c.interactions.create(agent=agent_id, input=job["text"], environment={"type": "remote", "sources": job["sources"]},
                                  timeout=TIMEOUT_S)
        rec.update(interaction_id=i.id, environment_id=i.environment_id, status=i.status,
                   tokens=(i.usage.total_tokens if i.usage else None), output=parse_json(i.output_text))
        (run_dir / job["label"].replace("@", "_")).mkdir(exist_ok=True)
        (run_dir / job["label"].replace("@", "_") / "interaction.json").write_text(
            json.dumps(i.model_dump(exclude_none=True, mode="json"), indent=1, default=str))
        if i.environment_id: rec["files"] = fetch_out(i.environment_id, run_dir / job["label"].replace("@", "_"))
    except Exception as e:
        rec.update(status="error", output={"error": f"{type(e).__name__}: {e}"[:1500]})
    rec["duration_s"] = round(time.time() - t, 1)
    log(f"{job['label']}: {rec['status']} in {rec['duration_s']}s")
    return rec


# ---------------------------------------------------------------- compare
def commission_match(remote, local):
    if not isinstance(remote, dict) or "cpr" not in remote or "error" in local: return False, "missing result"
    keys = ("cpr", "heldout", "nominal", "fault_pass", "violations")
    diffs = [k for k in keys if remote.get(k) != local.get(k)]
    rr = {r["id"]: r["passed"] for r in remote.get("rows", []) + remote.get("heldout_rows", [])}
    lr = {r["id"]: r["passed"] for r in local["rows"] + local["heldout_rows"]}
    diffs += [f"row {k}" for k in lr if rr.get(k) != lr[k]]
    rm, lm = remote.get("monte_carlo") or {}, local["monte_carlo"]
    diffs += [f"mc.{k}" for k in ("good", "silent_bad", "safe_stop", "other") if rm.get(k) != lm.get(k)]
    return not diffs, ("all metrics identical" if not diffs else "differs: " + ", ".join(diffs))


def verifier_match(remote, local):
    if not isinstance(remote, dict) or "confusion" not in remote: return False, "missing result"
    diffs = [g for g in local["confusion"] if (remote["confusion"].get(g) or {}) != local["confusion"][g]]
    rf = sorted(remote.get("stage1_agreement", {}).get("rule_flagged_segs", []) or [f["seg"] for f in remote.get("flagged", [])])
    if rf != local["rule_flagged_segs"]: diffs.append("flagged set")
    return not diffs, ("confusion matrix and flagged set identical" if not diffs else "differs: " + ", ".join(diffs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--looped", default=str(PROGRAMS["argon_looped@GoFa"][0]))
    ap.add_argument("--mc", type=int, default=200)
    ap.add_argument("--only", help="comma list of labels to run (default all)")
    a = ap.parse_args()
    progs = dict(PROGRAMS); progs["argon_looped@GoFa"] = (pathlib.Path(a.looped).resolve(), "gofa")
    run_dir = ROOT / f"runs/agents_{time.strftime('%Y%m%d_%H%M%S')}"; run_dir.mkdir(parents=True)
    log = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)
    c = argon_client.client()

    # ---- jobs
    jobs = []
    rows = episode_table()
    sensor = json.loads((ROOT / "derived/sensor.json").read_text())
    rule = sensor["proposal"]["telemetry_rule"]
    flags = [dict(seg=f["seg"], type=f["type"], t_video_s=f["t"]) for f in json.loads(stage1.OUT.read_text())["flags"]]
    gz = gzip.compress(json.dumps(dict(segments=rows), separators=(",", ":")).encode())
    src = [dict(type="inline", encoding="base64", content=b64(gz), target="/workspace/in/episodes.json.gz"),
           dict(type="inline", encoding="base64", content=b64(json.dumps(rule, indent=1)), target="/workspace/in/rule.json"),
           dict(type="inline", encoding="base64", content=b64(json.dumps(flags, indent=1)), target="/workspace/in/stage1_flags.json")]
    text = VERIFIER_TASK.format()
    jobs.append(dict(role="log-verifier", label="log-verifier", text=text, sources=src, input_bytes=guarded(text, src),
                     local=lambda: local_verifier(rows, rule, flags)))
    commission_py = (ROOT / "tools/commission.py").read_text()
    for label, (pdir, cell) in progs.items():
        files, pdir = program_files(label, pdir, run_dir)
        src = [dict(type="inline", encoding="base64", content=b64(SETUP_SH), target="/workspace/in/setup.sh"),
               dict(type="inline", encoding="base64", content=b64(commission_py), target="/workspace/in/commission.py")]
        src += [dict(type="inline", encoding="base64", content=b64(v), target=f"/workspace/in/program/{k}") for k, v in files.items()]
        text = COMMISSIONER_TASK.format(program_label=label, cell=cell, mc=a.mc)
        out = run_dir / label.replace("@", "_") / "local"
        jobs.append(dict(role="commissioner", label=label, text=text, sources=src, input_bytes=guarded(text, src),
                         local=(lambda pdir=pdir, cell=cell, out=out: local_commission(pdir, cell, a.mc, out)),
                         program_dir=str(pathlib.Path(pdir).relative_to(ROOT))))
    if a.only: jobs = [j for j in jobs if j["label"] in a.only.split(",")]
    log(f"{len(jobs)} jobs, quarantine passed for all inputs")

    # ---- agents (one per role) and the fan-out
    ts = int(time.time())
    agent_ids = {}
    for role in sorted({j["role"] for j in jobs}):
        ag = c.agents.create(id=f"argon-{role}-{ts}", base_agent=BASE_AGENT, agent_config={"type": "antigravity", "model": "gemini-4-argon"})
        agent_ids[role] = ag.id
    log("agents:", agent_ids)
    t0 = time.time()
    with cf.ThreadPoolExecutor(len(jobs) + 1) as ex:
        remote = {j["label"]: ex.submit(run_agent, c, agent_ids[j["role"]], j, run_dir, log) for j in jobs}
        local = {}
        for j in jobs:  # local references run while the agents work
            local[j["label"]] = j["local"](); log(f"local reference {j['label']} done")
        recs = {k: f.result() for k, f in remote.items()}
    wall = round(time.time() - t0, 1)

    agents = []
    for j in jobs:
        rec = recs[j["label"]]; rec["local_reference"] = local[j["label"]]
        ok, why = (verifier_match if j["role"] == "log-verifier" else commission_match)(rec["output"], local[j["label"]])
        rec["matches_local"], rec["notes"] = ok, why
        if j.get("program_dir"): rec["program_dir"] = j["program_dir"]
        agents.append(rec)
    out = dict(created_at=time.strftime("%Y-%m-%d %H:%M:%S"), fanout_wall_s=wall, commit=COMMIT, monte_carlo=dict(n=a.mc, p_miss=0.06, seed0=0),
               quarantine="every input (text + mounted files) passed argon_client.check_quarantine; the human GoFa port was never sent",
               agents=agents)
    (run_dir / "agents.json").write_text(json.dumps(out, indent=1, default=str))
    for r in agents: log(f"{r['label']:24s} {r['status']} {r['duration_s']}s tokens={r['tokens']} match={r['matches_local']} ({r['notes']})")
    log(f"fan-out wall {wall}s -> {run_dir.relative_to(ROOT)}/agents.json")


if __name__ == "__main__":
    main()
