import sys, time, json
sys.path.insert(0, __import__("pathlib").Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
client = genai.Client()
for level in ("low", "high"):
    t = time.time()
    resp = client.models.generate_content(
        model="gemini-4-argon",
        contents='Return JSON {"ok": true, "model": "<your model id>", "context_window_tokens": <int>}.',
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=level),
            response_mime_type="application/json",
        ),
    )
    print(level, round(time.time() - t, 2), "s", resp.text)
    print("  model_version:", resp.model_version)
    print("  usage:", resp.usage_metadata.model_dump(exclude_none=True))
