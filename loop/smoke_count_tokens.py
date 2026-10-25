"""Count tokens of the candidate long-context corpora (countTokens is free)."""
import sys, pathlib, json
sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())
import _env  # noqa
from google import genai
ROOT = pathlib.Path(__file__).resolve().parents[1]
LP = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing"
c = genai.Client()
def tok(paths):
    text = "\n".join(f"=== {p.relative_to(ROOT)}\n{p.read_text(errors='replace')}" for p in paths)
    return c.models.count_tokens(model="gemini-4-argon", contents=text).total_tokens, len(text)
code_ext = {".mod", ".sys", ".cfg", ".c", ".h", ".var", ".typ"}
groups = {
  "legacy_IRB1200_RAPID (input)": sorted((LP / "answer_key/Solution_IRB_1200").rglob("*.mod")),
  "GoFa_RAPID (answer key, quarantined)": sorted((LP / "answer_key/Solution_CRB_15000_GoFa").rglob("*.mod")),
  "plc_source (B&R C)": sorted(p for p in (LP / "plc_source").rglob("*") if p.suffix in code_ext),
  "v1 legacy_code (all code files)": sorted(p for p in (ROOT / "brownfield_robot_inputs_candidate/inputs/legacy_code").rglob("*") if p.suffix in code_ext),
}
for k, v in groups.items():
    t, n = tok(v) if v else (0, 0)
    print(f"{k:42s} files={len(v):3d} chars={n:8d} tokens={t}")
