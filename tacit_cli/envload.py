"""Minimal .env loader. Reads only TACIT_* keys to avoid silently slurping
unrelated secrets, and never logs values.
"""

import os
from pathlib import Path
from typing import Optional


def load_dotenv(start: Optional[Path] = None, max_levels: int = 4) -> Optional[Path]:
  """Walk up from `start` looking for a .env. Returns the path used, or None.

  Only TACIT_* keys are imported; lines starting with # are ignored. Existing
  process env wins so an explicit `set TACIT_WIF=` overrides .env.
  """
  cur = (start or Path.cwd()).resolve()
  for _ in range(max_levels):
    candidate = cur / ".env"
    if candidate.is_file():
      _read(candidate)
      return candidate
    if cur.parent == cur:
      break
    cur = cur.parent
  return None


def _read(path: Path) -> None:
  with open(path, "r", encoding="utf-8") as fp:
    for raw in fp:
      line = raw.strip()
      if not line or line.startswith("#"):
        continue
      if "=" not in line:
        continue
      k, v = line.split("=", 1)
      k = k.strip()
      v = v.strip().strip('"').strip("'")
      if not k.startswith("TACIT_"):
        continue
      if k in os.environ and os.environ[k]:
        # Existing env wins. Don't shadow.
        continue
      os.environ[k] = v
