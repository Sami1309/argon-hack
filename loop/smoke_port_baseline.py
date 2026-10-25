"""Baseline: single-pass Argon port of IRB1200 T_ROB1 -> GoFa, NO answer key in the prompt. Scored separately."""
import sys, time, json, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Solution_IRB_1200/Rapid/T_ROB1"
files = {p.name: p.read_text() for p in sorted(SRC.glob("*.mod"))}
assert not any("CRB_15000" in str(p) for p in SRC.glob("*")), "answer key leak"
CELL = """Cell facts (from the controller MOC.cfg and the new layout drawing):
- Legacy robot: ABB IRB 1200-5/0.9 (ROB_1), base at world (-2943.42, -3356.18, 0) mm, rotated +90 deg about world Z. Legacy robtargets use wobj0 (= world frame).
- New robot: ABB GoFa CRB 15000-5/0.95, mounted at world (-2858.37, -3299.93, +1.5) mm, rotated +90 deg about world Z. The GoFa controller has NO world frame configured: wobj0 = robot base frame.
- Same tool (smc_gripper), same I/O signal names, same cell objects. RobotWare 7 on GoFa."""
PROMPT = f"""{CELL}

Port this legacy RAPID task (T_ROB1) to the GoFa so it performs the same sorting cycle.
Return JSON: {{"module1_mod": "<full ported Module1.mod>", "changes": ["<each change and why>"]}}.

""" + "\n".join(f"=== {k}\n{v}" for k, v in files.items())
c = genai.Client()
t = time.time()
r = c.models.generate_content(model="gemini-4-argon", contents=PROMPT,
    config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=sys.argv[1] if len(sys.argv) > 1 else "high"),
                                       response_mime_type="application/json"))
out = ROOT / "runs/smoke/port_baseline"; out.mkdir(parents=True, exist_ok=True)
j = json.loads(r.text)
(out / "Module1.mod").write_text(j["module1_mod"]); (out / "changes.json").write_text(json.dumps(j["changes"], indent=1))
print(f"{time.time()-t:.0f}s usage={r.usage_metadata.model_dump(exclude_none=True, mode='json')}")
print("\n".join("- " + c for c in j["changes"]))
