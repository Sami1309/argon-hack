"""Stage 1: what Argon mined from the real shift, in one context (18:57 video + 5 Hz telemetry + legacy code).

    python loop/stage1.py            # build derived/stage1.json from the recorded Argon call
    python loop/stage1.py --live     # re-run the unified ~755K-token Argon call first (~2 min), then build

derived/stage1.json is the only Stage 1 material the port loop sees (quoted with its source file), so the evidence
chain footage -> finding -> sensor -> loop is mechanical, not hand-written.
"""
import argparse, json, pathlib, re, sys, time
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
V = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/video"
SHIFT = V / "shift_v2.mp4"
UNIFIED = ROOT / "runs/smoke/unified_1m.json"            # recorded unified call (video + telemetry + code)
VIDEO_ONLY = ROOT / "runs/smoke/shift_fps3_low_medium.json"
OUT = ROOT / "derived/stage1.json"
FPS = 15
LEGACY_CODE = ROOT / "brownfield_robot_inputs_candidate/inputs/legacy_code"
TELEMETRY = ROOT / "runs/smoke/telemetry_step3.csv"

UNIFIED_Q = """You have (1) an 18:57 chronological replay of 218 teleoperated pick-and-place episodes (hard cuts reset the scene),
(2) the robot telemetry for every episode (gripper 0=open..1=closed; a closure that stops near 0.5-0.6 means an object is between the fingers, closure >=0.85 means the fingers closed on nothing),
(3) legacy ABB RAPID / PLC code for a sorting cell whose gripping is open-loop.
Tasks:
A. List every failed episode. For each give the video timestamp, the telemetry evidence (shift_t_s and gripper value that proves or contradicts it), and whether video and telemetry AGREE.
B. List any episode where telemetry suggests a failure the video does not show, or vice versa.
C. Name the exact legacy RAPID file:line(s) that would let the dominant failure pass silently, and the minimal guarded rewrite (RAPID).
Return JSON {"failures":[{"t_video":"MM:SS","type":str,"telemetry_t_s":num,"gripper_peak":num,"agree":bool,"evidence":str}],"disagreements":[...],"legacy_hazard":{"file":str,"lines":str,"why":str,"guarded_rapid":str}}"""


def sec(s):
    if isinstance(s, (int, float)): return float(s)
    p = [float(x) for x in str(s).split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0]


def segments():
    return json.loads((V / "source_map_v2.json").read_text())["segments"]


def labels():
    return {e["uuid"]: e for e in json.loads((V / "event_annotations_v2.json").read_text())["events"]}


def seg_at(segs, t):
    for s in segs:
        if s["output_start_frame"] / FPS <= t < s["output_end_frame"] / FPS: return s["segment_index"]
    return None


def gripper(seg):
    d = pd.read_parquet(V / seg["log_file"], columns=["observation.gripper_position", "action.gripper_position"])
    return d["observation.gripper_position"].to_numpy(), d["action.gripper_position"].to_numpy()


def grip_rule(closed_on_nothing=0.9, commanded=0.5):
    """'Fingers close past X while commanded closed' per episode, vs the dataset's labels (which Argon never saw)."""
    segs, lab = segments(), labels()
    flagged, per = [], {}
    for s in segs:
        obs, act = gripper(s)
        peak = float(obs[act >= commanded].max()) if (act >= commanded).any() else 0.0
        label = lab[s["uuid"]]["failure_type"] if s["uuid"] in lab else s["kind"]
        hit = peak >= closed_on_nothing
        per.setdefault(label, [0, 0]); per[label][0] += hit; per[label][1] += 1
        if hit: flagged.append(dict(seg=s["segment_index"], label=label, peak=round(peak, 3)))
    return dict(rule=f"observation.gripper_position >= {closed_on_nothing} while action.gripper_position >= {commanded}",
                by_label={k: dict(flagged=v[0], total=v[1]) for k, v in per.items()}, flagged=flagged)


def build(unified_path=UNIFIED):
    segs, lab = segments(), labels()
    uni, vid = json.loads(pathlib.Path(unified_path).read_text()), json.loads(VIDEO_ONLY.read_text())
    flags = []
    for f in uni["response"]["failures"]:
        t = sec(f.get("t_video") or f.get("t_onset"))
        m = re.search(r"seg (\d+)", f.get("evidence", ""))
        flags.append(dict(t=round(t, 2), seg=int(m[1]) if m else seg_at(segs, t), type=f["type"], evidence=f["evidence"],
                          gripper_peak=f.get("gripper_peak")))
    by_seg = {f["seg"]: f for f in flags}
    eps = []
    for s in segs:
        label = lab[s["uuid"]]["failure_type"] if s["uuid"] in lab else "success"
        a = by_seg.get(s["segment_index"])
        eps.append(dict(seg=s["segment_index"], t0=round(s["output_start_frame"] / FPS, 2), t1=round(s["output_end_frame"] / FPS, 2),
                        dataset_kind=s["kind"], label=label, argon=a["type"] if a else None))
    labelled_fail = {e["seg"] for e in eps if e["dataset_kind"] == "failure" and e["label"] != "no_visible_failure_source_label_discrepancy"}
    argon_fail = {f["seg"] for f in flags if f["type"] != "camera_blackout"}
    u = uni.get("usage", {})
    mods = {d["modality"]: d["token_count"] for d in u.get("prompt_tokens_details", [])}
    out = dict(
        source=dict(file=str(pathlib.Path(unified_path).relative_to(ROOT)), latency_s=round(uni.get("gen_s", 0), 1),
                    prompt_tokens=u.get("prompt_token_count"), tokens_by_modality=mods,
                    inputs=["shift_v2.mp4 (18:57, 218 episodes, 3 fps)", "telemetry 5 Hz, all 218 episodes",
                            "legacy RAPID + PLC code (IRB 1200 cell)"]),
        video_only=dict(file=str(VIDEO_ONLY.relative_to(ROOT)), latency_s=round(vid["gen_s"], 1),
                        prompt_tokens=vid["usage"]["prompt_token_count"], flagged=len(vid["response"]["failures"])),
        flags=flags, episodes=eps,
        agreement=dict(argon_flagged=len(argon_fail), dataset_failures=len(labelled_fail), both=len(argon_fail & labelled_fail),
                       argon_only=sorted(argon_fail - labelled_fail), dataset_only=sorted(labelled_fail - argon_fail)),
        counts={t: sum(f["type"] == t for f in flags) for t in sorted({f["type"] for f in flags})},
        disagreements=uni["response"].get("disagreements", []), legacy_hazard=uni["response"].get("legacy_hazard"),
        built_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    return out


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else build()


def summary_text(s1=None):
    """The Stage 1 paragraph quoted into the port loop's prompt: Argon's own output, with its source file."""
    s1 = s1 or load()
    missed = [f for f in s1["flags"] if "missed_grasp" in f["type"]]
    h = s1["legacy_hazard"] or {}
    lines = [f"STAGE 1 - Argon's own findings, quoted from {s1['source']['file']} (one {s1['source']['prompt_tokens']:,}-token call: "
             f"{'; '.join(s1['source']['inputs'])}). Footage is a teleoperated Franka in a different cell.",
             f"- {len(s1['flags'])} episodes flagged; by type: " + ", ".join(f"{k} x{v}" for k, v in s1["counts"].items()),
             f"- The dominant failure is the MISSED GRASP ({len(missed)} of {len(s1['flags'])}). Argon's evidence, verbatim:"]
    lines += [f"    [{f['t']:.0f}s] {f['evidence']}" for f in missed[:4]]
    if h: lines.append(f"- Legacy hazard (Argon): {pathlib.Path(h['file']).parts[-3]}/{pathlib.Path(h['file']).name} lines {h['lines']}: {h['why']}")
    return "\n".join(lines)


def run_live(out_dir):
    """Re-run the unified call through argon_client (quarantine + manifest). Uses the Files API copy of the shift."""
    from loop import argon_client
    from google.genai import types
    c = argon_client.client()
    cache = ROOT / "runs/smoke/shift_file.json"
    f = None
    if cache.exists():
        try:
            f = c.files.get(name=json.loads(cache.read_text())["name"])
            if f.state.name != "ACTIVE": f = None
        except Exception: f = None
    if f is None:
        f = c.files.upload(file=str(SHIFT))
        while f.state.name == "PROCESSING": time.sleep(5); f = c.files.get(name=f.name)
        cache.write_text(json.dumps({"name": f.name, "uri": f.uri, "mime": f.mime_type}))
    code = "\n".join(f"=== {p.relative_to(ROOT)}\n{p.read_text(errors='replace')}" for p in sorted(LEGACY_CODE.rglob("*"))
                     if p.suffix in {".mod", ".sys", ".cfg", ".c", ".h", ".var", ".typ"} and "CRB_15000" not in str(p) and "GoFa" not in str(p))
    parts = [dict(kind="file", data=f.uri, mime=f.mime_type, source="shift_v2.mp4 (Files API)"),
             dict(kind="text", data="=== TELEMETRY\n" + TELEMETRY.read_text(), source=str(TELEMETRY.relative_to(ROOT))),
             dict(kind="text", data="=== LEGACY CODE\n" + code, source=str(LEGACY_CODE.relative_to(ROOT))),
             dict(kind="text", data=UNIFIED_Q, source="stage 1 question")]
    resp, meta = argon_client.call(parts, label="stage1_unified", run_dir=out_dir, schema=None, json_out=True, fps=3, thinking="medium")
    p = pathlib.Path(out_dir) / "unified.json"
    p.write_text(json.dumps(dict(gen_s=meta["latency_s"], usage=meta["usage"], response=resp), indent=1))
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true"); a = ap.parse_args()
    src = run_live(ROOT / f"runs/stage1_{time.strftime('%Y%m%d_%H%M%S')}") if a.live else UNIFIED
    s1 = build(src)
    print(summary_text(s1))
    print("\nagreement with dataset labels:", s1["agreement"])
