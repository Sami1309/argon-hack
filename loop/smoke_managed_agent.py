"""Probe: can a Managed Agent sandbox install MuJoCo and render headless? Can a custom agent run on Argon?"""
import sys, os, time, json, tarfile, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
import requests
from google import genai
c = genai.Client()
OUT = pathlib.Path(__file__).resolve().parents[1] / "runs/smoke/managed_agent"
OUT.mkdir(parents=True, exist_ok=True)
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)

TASK = r"""You are probing this sandbox. Do these steps exactly, then report.
1. Run and capture: uname -a; nproc; free -m (or cat /proc/meminfo | head -3); df -h /; python3 --version; which nvidia-smi && nvidia-smi; pip --version.
2. Run: pip install mujoco imageio imageio-ffmpeg numpy  (record wall time and whether it succeeded; if pip blocked, try pip install --user or uv).
3. Write /workspace/out/render_test.py that builds this MJCF and renders 150 frames at 1280x720 offscreen, then writes /workspace/out/test.mp4 at 15 fps with imageio:
<mujoco><visual><global offwidth="1280" offheight="720"/></visual><worldbody><light pos="0 0 3"/><geom type="plane" size="2 2 .1"/><body pos="0 0 .5"><freejoint/><geom type="box" size=".1 .1 .1" rgba=".2 .6 .2 1"/></body><camera name="cam" pos="1.5 -1.5 1.2" xyaxes="1 1 0 -.4 .4 1"/></worldbody></mujoco>
   Try MUJOCO_GL=egl first; if it fails try MUJOCO_GL=osmesa (apt-get install -y libosmesa6 if needed); record which backend worked, the render wall time, and any errors verbatim.
4. ls -la /workspace/out
Reply with ONLY a JSON object: {"uname":..., "nproc":..., "mem_mb":..., "gpu":..., "python":..., "pip_install_ok":bool, "pip_install_s":num, "gl_backend_ok":"egl"|"osmesa"|null, "render_s":num, "frames":int, "mp4_bytes":int, "errors":[...], "network_ok":bool}"""

t = time.time()
log("creating remote interaction ...")
try:
    i = c.interactions.create(agent="antigravity-preview-09-2026", input=TASK, environment="remote", timeout=900)
    log(f"done in {time.time()-t:.0f}s status={i.status} env={i.environment_id}")
    (OUT / "interaction.json").write_text(json.dumps(i.model_dump(exclude_none=True), default=str, indent=1))
    log("OUTPUT:", (i.output_text or "")[:3000])
    u = getattr(i, "usage", None); log("usage:", u.model_dump(exclude_none=True) if u else None)
    r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/files/environment-{i.environment_id}:download",
                     params={"alt": "media"}, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, allow_redirects=True, timeout=300)
    log("snapshot download:", r.status_code, len(r.content), "bytes")
    if r.ok:
        (OUT / "snapshot.tar").write_bytes(r.content)
        with tarfile.open(OUT / "snapshot.tar") as tar:
            names = tar.getnames()
            log("snapshot entries:", len(names), [n for n in names if "out" in n][:20])
except Exception as e:
    log("MANAGED AGENT ERROR:", type(e).__name__, str(e)[:1500])

log("--- custom agent on gemini-4-argon")
for model in ("gemini-4-argon",):
    try:
        a = c.agents.create(id=f"argon-probe-{int(time.time())}", base_agent="antigravity-preview-09-2026",
                            agent_config={"type": "antigravity", "model": model})
        log("agents.create OK:", json.dumps(a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else str(a), default=str)[:800])
        t = time.time()
        r = c.interactions.create(agent=a.id if hasattr(a, "id") else a.name, input="Reply with the single word: ready, then state your underlying model id.", environment="remote", timeout=600)
        log(f"custom agent run {time.time()-t:.0f}s:", r.status, (r.output_text or "")[:500])
    except Exception as e:
        log("CUSTOM AGENT ERROR:", type(e).__name__, str(e)[:1500])
log("ALL DONE")
