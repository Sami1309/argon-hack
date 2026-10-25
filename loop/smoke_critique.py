"""Blind visual critique of sim rollouts. Usage: smoke_critique.py <thinking> [fps]"""
import sys, time, json, pathlib, concurrent.futures as cf
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
ROOT = pathlib.Path(__file__).resolve().parents[1]
SIM = ROOT / "runs/smoke/sim"
think, fps = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 5
c = genai.Client()
SCHEMA = {"type": "object", "properties": {
    "task_success": {"type": "boolean"},
    "violations": {"type": "array", "items": {"type": "object", "properties": {
        "type": {"type": "string", "enum": ["unreachable", "collision", "wrong_frame", "io_order", "task_fail", "unguarded_grip"]},
        "time_s": {"type": "number"}, "evidence": {"type": "string"},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]}},
        "required": ["type", "time_s", "evidence", "severity"]}},
    "suspected_root_cause": {"type": "string"},
    "proposed_fix": {"type": "string"}},
    "required": ["task_success", "violations", "suspected_root_cause", "proposed_fix"]}
PROMPT = ("You are verifying a robot program in a digital twin. Intended task: pick the green box from the YELLOW pad, "
          "carry it over the grey wall, and place it on the BLUE pad. The wall turns RED while anything intersects it (collision). "
          "Watch the rollout and report every violation with the time in seconds and visual evidence, whether the task succeeded, "
          "the most likely root cause in the program, and a concrete fix.")

def one(mp4):
    t = time.time()
    data = mp4.read_bytes()  # inline (<20MB) avoids file-upload latency in the loop
    resp = c.models.generate_content(model="gemini-4-argon",
        contents=[types.Content(parts=[
            types.Part(inline_data=types.Blob(data=data, mime_type="video/mp4"), video_metadata=types.VideoMetadata(fps=fps)),
            types.Part(text=PROMPT)])],
        config=types.GenerateContentConfig(media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            thinking_config=types.ThinkingConfig(thinking_level=think),
            response_mime_type="application/json", response_json_schema=SCHEMA))
    return mp4.stem, time.time() - t, resp.usage_metadata.prompt_token_count, json.loads(resp.text)

with cf.ThreadPoolExecutor(4) as ex:
    results = list(ex.map(one, sorted(SIM.glob("*.mp4"))))
out = {}
for name, dt, ptok, r in results:
    out[name] = {"latency_s": round(dt, 1), "prompt_tokens": ptok, **r}
    print(f"== {name}  {dt:.1f}s  prompt_tokens={ptok}  success={r['task_success']}")
    for v in r["violations"]: print(f"   [{v['type']}] t={v['time_s']}s  {v['evidence'][:150]}")
    print("   cause:", r["suspected_root_cause"][:200]); print("   fix:", r["proposed_fix"][:200])
(ROOT / f"runs/smoke/sim/critique_{think}.json").write_text(json.dumps(out, indent=1))
