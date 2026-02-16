#!/usr/bin/env bash
# Bootstrap: install deps and run doctor. Run from repo root or any subdir.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Installing dependencies ==="
python3 -m pip install -r requirements.txt

echo ""
echo "=== Running doctor ==="
if python3 -m scripts.doctor; then
  echo ""
  echo "NEXT: python3 scripts/run_template_builder.py"
  exit 0
else
  exit 1
fi
