"""Sensor step: Argon proposes a grip-confirmation input from its Stage 1 findings; code verifies the implied rule on all
218 real episode logs; the engineer approves (the one human decision). Only then does the port loop know the sensor.

    python loop/sensor.py                 # Argon proposal (~15 s) + verification on the logs -> derived/sensor.json
    python loop/sensor.py --approve       # engineer approves; the loop wires it as DI_GRIP_OK (per robot)
"""
import argparse, json, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client, stage1  # noqa: E402

OUT = ROOT / "derived/sensor.json"
WIRED_AS = "DI_GRIP_OK"

SCHEMA = {"type": "object", "properties": {
    "hazard": {"type": "string"},
    "proposal": {"type": "object", "properties": {
        "signal": {"type": "string"}, "meaning": {"type": "string"}, "hardware": {"type": "string"},
        "rapid_usage": {"type": "string"}}, "required": ["signal", "meaning", "hardware", "rapid_usage"]},
    "telemetry_rule": {"type": "object", "properties": {
        "description": {"type": "string"},
        "commanded_closed_min": {"type": "number"}, "closed_on_nothing_min": {"type": "number"}},
        "required": ["description", "commanded_closed_min", "closed_on_nothing_min"]},
    "cited_evidence": {"type": "array", "items": {"type": "object", "properties": {
        "t_video_s": {"type": "number"}, "seg": {"type": "integer"}, "gripper": {"type": "number"}, "what": {"type": "string"}},
        "required": ["t_video_s", "seg", "gripper", "what"]}},
    "expected_effect": {"type": "string"}},
    "required": ["hazard", "proposal", "telemetry_rule", "cited_evidence", "expected_effect"]}

PROMPT = """You are helping an automation engineer replace two legacy ABB IRB 1200 robots with ABB GoFa cobots by Monday.
Your Stage 1 analysis of real footage + telemetry + the legacy code is below.

{stage1}

TELEMETRY FIELDS available on the real robots: observation.gripper_position (0 = open .. 1 = fully closed, measured),
action.gripper_position (commanded). The new cobots can take one extra digital input per robot.

Propose the ONE sensor/input that would turn the dominant silent failure into a detectable one:
- what it signals and how it would be wired (hardware),
- how the RAPID program should use it (one sentence),
- the telemetry rule that reproduces it offline on the real logs (fingers close past X while commanded closed past Y),
  with X and Y chosen from the gripper values in your evidence,
- which of your cited episodes it would have caught."""


def propose(run_dir):
    s1 = stage1.load()
    out, meta = argon_client.call([dict(kind="text", data=PROMPT.format(stage1=stage1.summary_text(s1)),
                                        source=f"Stage 1 findings ({stage1.OUT.relative_to(ROOT)}) + telemetry field names")],
                                  label="sensor_proposal", run_dir=run_dir, schema=SCHEMA, thinking="low")
    return out, meta


def verify(rule):
    return stage1.grip_rule(closed_on_nothing=float(rule["closed_on_nothing_min"]), commanded=float(rule["commanded_closed_min"]))


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else None


def approved():
    s = load()
    return bool(s and s.get("approval", {}).get("approved"))


def approve(by="engineer"):
    s = load()
    if not s: raise SystemExit("no proposal yet: run python loop/sensor.py first")
    s["approval"] = dict(approved=True, wired_as=WIRED_AS, by=by, at=time.strftime("%Y-%m-%d %H:%M:%S"),
                         note="proposed hardware addition; simulated in the twin as 1 while the gripper holds a part")
    OUT.write_text(json.dumps(s, indent=1))
    return s


def facts():
    """Cell-facts line the loop adds once (and only once) the engineer has approved the sensor."""
    s = load()
    p = s["proposal"]["proposal"]
    return (f"- APPROVED SENSOR (proposed by you from Stage 1, verified on 218 real logs, approved by the engineer): "
            f"{WIRED_AS} (per robot; your proposal called it {p['signal']}) = 1 while the gripper holds a part. {p['meaning']}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--approve", action="store_true"); a = ap.parse_args()
    if a.approve:
        s = approve(); print("approved:", s["approval"]); return
    run_dir = ROOT / f"runs/sensor_{time.strftime('%Y%m%d_%H%M%S')}"
    out, meta = propose(run_dir)
    v = verify(out["telemetry_rule"])
    s = dict(proposal=out, verification=v, call=dict(dir=str(run_dir.relative_to(ROOT)), latency_s=meta["latency_s"]),
             approval=dict(approved=False))
    OUT.write_text(json.dumps(s, indent=1))
    print(json.dumps(out["proposal"], indent=1))
    print("rule:", v["rule"]); print("by label:", v["by_label"])


if __name__ == "__main__":
    main()
