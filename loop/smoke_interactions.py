import sys, time, json; sys.path.insert(0, __import__("pathlib").Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
c = genai.Client()
t = time.time()
try:
    i = c.interactions.create(model="gemini-4-argon", input="Reply with the single word: ready")
    print("argon via interactions:", round(time.time()-t,1), "s", i.status)
    print(json.dumps(i.model_dump(exclude_none=True), default=str)[:1500])
except Exception as e:
    print("ARGON INTERACTIONS ERROR:", type(e).__name__, str(e)[:800])
