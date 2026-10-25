"""The only path from this repo to Gemini 4 Argon. Enforces the answer-key quarantine and logs every call.

Every call writes <run_dir>/<label>.manifest.json: parts sent (kind, source, size, sha256), token usage by
modality, latency. That manifest is the judges' proof of what went into each Argon call.
"""
import hashlib, json, pathlib, re, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import _env  # noqa: F401,E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = "gemini-4-argon"
DENY_PATHS = ("Solution_CRB_15000_GoFa", "PORT_ANALYSIS.md", "IRB1200_vs_GoFa", "analysis/")
_AK = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Solution_CRB_15000_GoFa"


def _answer_key_literals():
    """Distinctive numeric literals of the human GoFa port's robtargets (>= 3 decimals)."""
    lits = set()
    for f in _AK.rglob("*.mod"):
        for m in re.finditer(r"robtarget\s+\w+\s*:=\s*\[\[([^\]]+)\]", f.read_text()):
            lits.update(x.strip() for x in m[1].split(",") if re.fullmatch(r"-?\d+\.\d{3,}", x.strip()))
    return lits


_LITERALS = _answer_key_literals() if _AK.exists() else set()
_client = None


class QuarantineViolation(Exception):
    pass


def client():
    global _client
    if _client is None: _client = genai.Client()
    return _client


def check_quarantine(text, sources):
    for s in sources:
        if any(d in str(s) for d in DENY_PATHS): raise QuarantineViolation(f"denied source: {s}")
    hits = [l for l in _LITERALS if l in text]
    if hits: raise QuarantineViolation(f"answer-key literals in payload: {hits[:5]}")


def call(parts, *, label, run_dir, schema=None, thinking="medium", fps=5, system=None):
    """parts: list of dicts {kind: text|video, data: str|bytes, source: str}. Returns (parsed JSON or text, meta)."""
    run_dir = pathlib.Path(run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    texts = "\n".join(p["data"] for p in parts if p["kind"] == "text") + (system or "")
    check_quarantine(texts, [p.get("source", "") for p in parts])
    gparts, manifest = [], []
    for p in parts:
        raw = p["data"].encode() if isinstance(p["data"], str) else p["data"]
        manifest.append(dict(kind=p["kind"], source=p.get("source", "inline"), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()[:16]))
        if p["kind"] == "text":
            gparts.append(types.Part(text=p["data"]))
        else:
            gparts.append(types.Part(inline_data=types.Blob(data=p["data"], mime_type="video/mp4"), video_metadata=types.VideoMetadata(fps=fps)))
    cfg = types.GenerateContentConfig(
        system_instruction=system, thinking_config=types.ThinkingConfig(thinking_level=thinking),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        response_mime_type="application/json" if schema else None, response_json_schema=schema)
    t = time.time()
    resp = client().models.generate_content(model=MODEL, contents=[types.Content(role="user", parts=gparts)], config=cfg)
    dt = time.time() - t
    usage = resp.usage_metadata.model_dump(exclude_none=True, mode="json") if resp.usage_metadata else {}
    meta = dict(label=label, model=MODEL, thinking=thinking, latency_s=round(dt, 2), parts=manifest, usage=usage,
                quarantine="passed: no answer-key paths or GoFa target literals")
    (run_dir / f"{label}.manifest.json").write_text(json.dumps(meta, indent=1))
    out = json.loads(resp.text) if schema else resp.text
    (run_dir / f"{label}.response.json").write_text(json.dumps(out, indent=1) if schema else json.dumps({"text": out}))
    return out, meta
