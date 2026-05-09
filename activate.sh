#!/usr/bin/env bash
# Source this file: `source ./activate.sh`
if [ ! -f ".venv/bin/activate" ]; then
  echo ".venv not found. Run ./setup_env.sh first." >&2
  return 1 2>/dev/null || exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
