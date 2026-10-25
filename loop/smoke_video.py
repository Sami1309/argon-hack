"""Argon video smoke test: upload a clip, ask for grasp attempts with timestamps. Usage: smoke_video.py <mp4> [fps] [resolution low|high] [thinking]"""
import sys, time, json, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
path, fps = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
res = (sys.argv[3] if len(sys.argv) > 3 else "low").upper()
think = sys.argv[4] if len(sys.argv) > 4 else "medium"
c = genai.Client()
t0 = time.time()
f = c.files.upload(file=path)
while f.state.name != "ACTIVE":
    if f.state.name == "FAILED": raise SystemExit("file processing failed")
    time.sleep(3); f = c.files.get(name=f.name)
t_up = time.time() - t0
PROMPT = ("This is a chronological replay of a robot pick-and-place shift (green block -> black bowl), "
          "with hard cuts between episodes (a cut resets the scene; a cut is NOT a failure). "
          "List every grasp attempt. For each: start and end as MM:SS.s, outcome one of "
          "[success, missed_grasp, contact_displacement, incomplete, unclear], block_in_bowl_at_end (bool), "
          "and one-sentence visual evidence citing the timestamp. Also list every hard cut timestamp. "
          'Return JSON {"attempts":[...], "cuts":[...]}.')
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
out = pathlib.Path(__file__).resolve().parents[1] / "runs/smoke" / (pathlib.Path(path).stem + f"_fps{fps:g}_{res.lower()}_{think}.json")
u = resp.usage_metadata.model_dump(exclude_none=True, mode="json")
out.write_text(json.dumps({"upload_s": t_up, "gen_s": t_gen, "usage": u, "file": f.name, "response": json.loads(resp.text)}, indent=1))
print(f"upload {t_up:.1f}s  generate {t_gen:.1f}s  -> {out}")
print("usage:", u)
print(resp.text[:4000])
