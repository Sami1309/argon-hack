"""Load GEMINI_API_KEY from .env.local / .env without printing it."""
import os, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
for name in (".env.local", ".env"):
    p = ROOT / name
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
