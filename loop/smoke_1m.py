"""Near-1M unified-context probe: full shift video (3 fps) + 5 Hz telemetry + legacy RAPID/PLC code in ONE prompt."""
import sys, time, json, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
ROOT = pathlib.Path(__file__).resolve().parents[1]
f = json.loads((ROOT / "runs/smoke/shift_file.json").read_text())
tele = (ROOT / "runs/smoke/telemetry_step3.csv").read_text()
LC = ROOT / "brownfield_robot_inputs_candidate/inputs/legacy_code"
code = "\n".join(f"=== {p.relative_to(ROOT)}\n{p.read_text(errors='replace')}" for p in sorted(LC.rglob("*"))
                 if p.suffix in {".mod", ".sys", ".cfg", ".c", ".h", ".var", ".typ"} and "CRB_15000" not in str(p) and "GoFa" not in str(p))
Q = """You have (1) an 18:57 chronological replay of 218 teleoperated pick-and-place episodes (hard cuts reset the scene),
(2) the robot telemetry for every episode (gripper 0=open..1=closed; a closure that stops near 0.5-0.6 means an object is between the fingers, closure >=0.85 means the fingers closed on nothing),
(3) legacy ABB RAPID / PLC code for a sorting cell whose gripping is open-loop.
Tasks:
A. List every failed episode. For each give the video timestamp, the telemetry evidence (shift_t_s and gripper value that proves or contradicts it), and whether video and telemetry AGREE.
B. List any episode where telemetry suggests a failure the video does not show, or vice versa.
C. Name the exact legacy RAPID file:line(s) that would let the dominant failure pass silently, and the minimal guarded rewrite (RAPID).
Return JSON {"failures":[{"t_video":"MM:SS","type":str,"telemetry_t_s":num,"gripper_peak":num,"agree":bool,"evidence":str}],"disagreements":[...],"legacy_hazard":{"file":str,"lines":str,"why":str,"guarded_rapid":str}}"""
c = genai.Client()
t = time.time()
r = c.models.generate_content(model="gemini-4-argon",
    contents=[types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=f["uri"], mime_type=f["mime"]), video_metadata=types.VideoMetadata(fps=3)),
        types.Part(text="=== TELEMETRY\n" + tele), types.Part(text="=== LEGACY CODE\n" + code), types.Part(text=Q)])],
    config=types.GenerateContentConfig(media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        thinking_config=types.ThinkingConfig(thinking_level="medium"), response_mime_type="application/json"))
dt = time.time() - t
u = r.usage_metadata.model_dump(exclude_none=True, mode="json")
(ROOT / "runs/smoke/unified_1m.json").write_text(json.dumps({"gen_s": dt, "usage": u, "response": json.loads(r.text)}, indent=1))
print(f"{dt:.0f}s usage={u}")
