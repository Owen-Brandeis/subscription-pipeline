#!/usr/bin/env python3
"""Run the FastAPI web UI with uvicorn."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    print("Open http://localhost:8000")
    import uvicorn
    uvicorn.run("app.web:app", host="127.0.0.1", port=8000, reload=True)
