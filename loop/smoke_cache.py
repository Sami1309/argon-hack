"""Does gemini-4-argon give implicit cache hits on a byte-identical prefix? 4 sequential calls."""
import sys, time, pathlib
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
from google.genai import types
ROOT = pathlib.Path(__file__).resolve().parents[1]
LP = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key/Solution_IRB_1200"
prefix = "\n".join(f"=== {p.name}\n{p.read_text()}" for p in sorted(LP.rglob("*.mod")))
plc = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/plc_source"
prefix += "\n".join(f"=== {p.name}\n{p.read_text(errors='replace')}" for p in sorted(plc.rglob("*.c")))
c = genai.Client()
SYS = "You are a RAPID-to-cobot migration verifier. Answer in one short sentence."
for i, q in enumerate(["How many PROCs are in T_ROB1?", "Which DO signal attaches the part on the table?",
                       "Is there any ERROR handler?", "What does T_ROB2 wait on with WaitDI?"]):
    t = time.time()
    r = c.models.generate_content(model="gemini-4-argon", contents=[prefix, q],
        config=types.GenerateContentConfig(system_instruction=SYS, thinking_config=types.ThinkingConfig(thinking_level="low")))
    u = r.usage_metadata
    print(f"call{i} {time.time()-t:5.1f}s prompt={u.prompt_token_count} cached={u.cached_content_token_count}  {r.text.strip()[:110]}", flush=True)
    time.sleep(2)
