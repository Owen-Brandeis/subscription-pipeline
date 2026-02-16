#!/usr/bin/env python3
"""Print the absolute path to the outbox directory."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTBOX = REPO_ROOT / "outbox"

if __name__ == "__main__":
    print(OUTBOX.resolve())
