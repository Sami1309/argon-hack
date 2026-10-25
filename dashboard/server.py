"""Dashboard server: serves the built UI, demo_bundle/ (Replay) and runs/ (Live clips), and runs the real loop live.

    python dashboard/server.py            # http://127.0.0.1:8787 (PORT=... to change)  (UI from dashboard/dist; npm run build first)

Live modes (POST /api/live/start {"mode": ..., "start": ...}):
  loop  - the real Argon loop from a cached single-pass port (~2 min): start "buggy" (0%, frame sign error) or "clean" (10%)
  full  - the whole pipeline (~6 min): Stage 1 on the 19-min shift (~755K tokens) -> sensor proposal -> engineer approval
          (POST /api/live/approve/<id>) -> single-pass port -> loop
Events stream as Server-Sent Events from GET /api/live/stream/<id>. Any failure emits {"ev": "error"} and the UI falls
back to the recorded run with a Replay label.
"""
import json, pathlib, sys, threading, time, traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

app = FastAPI(title="Argon cell port")
RUNS, LOCK = {}, threading.Lock()
BUNDLE, DIST = ROOT / "demo_bundle", ROOT / "dashboard/dist"


def _single_pass_dirs():
    b = json.loads((BUNDLE / "bundle.json").read_text())
    trials = b["single_pass_trials"]
    clean = next(t for t in trials if t["nominal"])
    buggy = next((t for t in trials if not t["nominal"]), clean)
    return {"clean": ROOT / clean["dir"], "buggy": ROOT / buggy["dir"]}


def _url(p):
    p = pathlib.Path(p)
    return "/" + str(p.resolve().relative_to(ROOT)) if p.is_absolute() else "/" + str(p)


class LiveRun:
    def __init__(self, mode, start):
        self.id = time.strftime("live_%Y%m%d_%H%M%S")
        self.mode, self.start, self.events, self.cv = mode, start, [], threading.Condition()
        self.dir = ROOT / "runs" / self.id
        self.approved = threading.Event()
        self.finished = False

    def emit(self, e):
        e = dict(e, t_wall=round(time.time(), 2))
        if e.get("ev") == "watching" and e.get("clip"): e["clip_url"] = "/" + e["clip"]
        if e.get("ev") == "iteration" and e.get("iter", 0) > 0:
            d = self.dir / f"iter{e['iter']:02d}"
            try:
                dec = json.loads((d / "decision.json").read_text())
                from loop.run_loop import routine_diff
                e["decision"] = dict(dec, diff=routine_diff(dec.get("old_routine"), dec["patch"]["new_routine"]), clip_url=_url(d / dec["clip"]))
            except Exception as ex:  # never let enrichment kill the stream
                e["decision_error"] = str(ex)
        with self.cv:
            self.events.append(e); self.cv.notify_all()

    def run(self):
        from loop import run_loop, stage1, sensor
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            context, start = None, None
            if self.mode == "full":
                self.emit(dict(ev="stage", stage="stage1", status="running", note="shift video + telemetry + legacy code in one context"))
                src = stage1.run_live(self.dir / "stage1")
                s1 = stage1.build(src, self.dir / "stage1/stage1.json")
                self.emit(dict(ev="stage", stage="stage1", status="done", tokens=s1["source"]["prompt_tokens"],
                               latency_s=s1["source"]["latency_s"], counts=s1["counts"], agreement=s1["agreement"],
                               summary=stage1.summary_text(s1)))
                self.emit(dict(ev="stage", stage="sensor", status="running"))
                prop, meta = sensor.propose(self.dir / "sensor", s1)
                ver = sensor.verify(prop["telemetry_rule"])
                sens = dict(proposal=prop, verification=ver, call=dict(latency_s=meta["latency_s"]))
                self.emit(dict(ev="stage", stage="sensor", status="awaiting_approval", proposal=prop, verification=ver))
                if not self.approved.wait(timeout=600): raise RuntimeError("sensor not approved within 10 min")
                sens["approval"] = dict(approved=True, wired_as=sensor.WIRED_AS, by="engineer (live)", at=time.strftime("%H:%M:%S"))
                (self.dir / "sensor.json").write_text(json.dumps(sens, indent=1))
                self.emit(dict(ev="stage", stage="sensor", status="approved"))
                context = dict(stage1_text=stage1.summary_text(s1), sensor_facts=sensor.facts(sens))
            else:
                start = _single_pass_dirs()[self.start]
            self.emit(dict(ev="stage", stage="loop", status="running", start=self.start if start else "live single pass"))
            run_loop.run(self.dir, iters=8, start=start, emit=self.emit, context=context)
            self.emit(dict(ev="finished", run=self.id))
        except BaseException as ex:  # SystemExit included: surface every failure to the UI
            self.emit(dict(ev="error", message=f"{type(ex).__name__}: {ex}", trace=traceback.format_exc()[-1500:]))
        finally:
            self.finished = True
            with self.cv: self.cv.notify_all()


@app.post("/api/live/start")
def live_start(body: dict):
    mode, start = body.get("mode", "loop"), body.get("start", "buggy")
    if mode not in ("loop", "full") or start not in ("buggy", "clean"): raise HTTPException(400, "bad mode/start")
    with LOCK:
        if any(not r.finished for r in RUNS.values()): raise HTTPException(409, "a live run is already in progress")
        r = LiveRun(mode, start); RUNS[r.id] = r
    threading.Thread(target=r.run, daemon=True).start()
    return {"id": r.id, "mode": mode, "start": start}


@app.post("/api/live/approve/{rid}")
def live_approve(rid: str):
    if rid not in RUNS: raise HTTPException(404)
    RUNS[rid].approved.set(); return {"ok": True}


@app.get("/api/live/stream/{rid}")
def live_stream(rid: str):
    if rid not in RUNS: raise HTTPException(404)
    r = RUNS[rid]

    def gen():
        i = 0
        while True:
            with r.cv:
                while i >= len(r.events) and not r.finished: r.cv.wait(timeout=10)
                batch, done = r.events[i:], r.finished and i + len(r.events[i:]) >= len(r.events)
            for e in batch:
                yield f"data: {json.dumps(e, default=str)}\n\n"
            i += len(batch)
            if done and i >= len(r.events): yield "event: end\ndata: {}\n\n"; return
            if not batch: yield ": keep-alive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/live/runs")
def live_runs():
    return [dict(id=r.id, mode=r.mode, start=r.start, finished=r.finished, events=len(r.events)) for r in RUNS.values()]


@app.get("/api/health")
def health():
    return {"ok": True, "bundle": (BUNDLE / "bundle.json").exists(), "dist": (DIST / "index.html").exists()}


app.mount("/bundle", StaticFiles(directory=BUNDLE, follow_symlink=True), name="bundle")
app.mount("/runs", StaticFiles(directory=ROOT / "runs"), name="runs")
if (DIST / "assets").exists(): app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/")
def index():
    if not (DIST / "index.html").exists(): return JSONResponse({"error": "UI not built: cd dashboard && npm run build"}, 503)
    return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    import os
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8787)), log_level="warning")
