"""Stage-1 feasibility: mine failures from the full 18:57 shift. Usage: smoke_shift.py <fps> <low|medium|high> <thinking>"""
import sys, time, json, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
ROOT = pathlib.Path(__file__).resolve().parents[1]
VID = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/video/shift_v2.mp4"
fps, res, think = float(sys.argv[1]), sys.argv[2].upper(), sys.argv[3]
c = genai.Client()
cache = ROOT / "runs/smoke/shift_file.json"
f = None
if cache.exists():
    try:
        f = c.files.get(name=json.loads(cache.read_text())["name"])
        if f.state.name != "ACTIVE": f = None
    except Exception: f = None
t0 = time.time()
if f is None:
    f = c.files.upload(file=str(VID))
    while f.state.name != "ACTIVE":
        if f.state.name == "FAILED": raise SystemExit("file processing failed")
        time.sleep(5); f = c.files.get(name=f.name)
    cache.write_text(json.dumps({"name": f.name, "uri": f.uri, "mime": f.mime_type}))
t_up = time.time() - t0
print(f"file ready {f.name} in {t_up:.0f}s", flush=True)
PROMPT = ("This 18:57 video is a chronological replay of ~218 teleoperated robot episodes from one shift: "
          "a Franka arm picks a green block and places it in a black bowl. Hard cuts separate episodes and reset "
          "the scene; a cut is NOT a failure. Find EVERY episode where the attempt fails "
          "(block not in the bowl at the end of the episode, or block knocked/displaced, or gripper closes on nothing). "
          "For each failure return: t_start and t_end (MM:SS), t_onset (MM:SS, the moment the failure becomes visible), "
          "type one of [missed_grasp, contact_displacement, dropped, incomplete, other], and evidence (one sentence citing what is visible). "
          'Also return episode_count_estimate. Return JSON {"episode_count_estimate": int, "failures": [...]}.')
t1 = time.time()
resp = c.models.generate_content(
    model="gemini-4-argon",
    contents=[types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type),
                   video_metadata=types.VideoMetadata(fps=fps)),
        types.Part(text=PROMPT)])],
    config=types.GenerateContentConfig(
        media_resolution=getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{res}"),
        thinking_config=types.ThinkingConfig(thinking_level=think),
        response_mime_type="application/json"),
)
t_gen = time.time() - t1
u = resp.usage_metadata.model_dump(exclude_none=True, mode="json")
out = ROOT / f"runs/smoke/shift_fps{fps:g}_{res.lower()}_{think}.json"
out.write_text(json.dumps({"gen_s": t_gen, "usage": u, "response": json.loads(resp.text)}, indent=1))
print(f"generate {t_gen:.0f}s -> {out}\nusage: {u}", flush=True)
