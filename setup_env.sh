#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.10+ first." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating venv at .venv/"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

echo
echo "Setup complete. Run 'source ./activate.sh' to enter the venv next time."
