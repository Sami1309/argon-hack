"""Fan-out feasibility: N parallel Argon managed agents forked from a pre-baked env (mujoco installed). Measures wall time."""
import sys, time, json, pathlib, concurrent.futures as cf
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/smoke/managed_agent"
BASE_ENV = json.loads((OUT / "interaction.json").read_text())["environment_id"]
c = genai.Client()
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)
agent = c.agents.create(id=f"argon-fanout-{int(time.time())}", base_agent="antigravity-preview-09-2026",
                        agent_config={"type": "antigravity", "model": "gemini-4-argon"}, base_environment=BASE_ENV)
log("agent", agent.id, "base_env", BASE_ENV)
def job(k):
    t = time.time()
    task = (f"Candidate patch #{k}: in /workspace/out/render_test.py change the box rgba to a different colour (variant {k}) "
            f"and the camera pos x to {1.0 + 0.25 * k}. Then run it with MUJOCO_GL=osmesa, and reply ONLY JSON "
            '{"candidate": %d, "ran": bool, "render_s": num, "mp4_bytes": int, "error": str|null}' % k)
    i = c.interactions.create(agent=agent.id, input=task, environment="remote", timeout=900)
    return k, round(time.time() - t, 1), i.status, (i.output_text or "")[:400], i.model_dump(exclude_none=True, mode="json")
t0 = time.time()
with cf.ThreadPoolExecutor(3) as ex:
    for k, dt, st, txt, full in ex.map(job, range(3)):
        log(f"cand{k} {dt}s {st} model={full.get('model')} agent={full.get('agent')} tokens={full.get('usage',{}).get('total_tokens')} :: {txt}")
        (OUT / f"fanout_{k}.json").write_text(json.dumps(full, indent=1, default=str))
log(f"fan-out wall {time.time()-t0:.0f}s")
