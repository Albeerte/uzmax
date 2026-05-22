"""Local launcher for the UzMAX Medicine + Robot Control MVP.

This keeps the simple command `python app.py` while making the FastAPI app in
medicine-rag the canonical local server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "medicine-rag"

sys.dont_write_bytecode = True
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

from main import app  # noqa: E402


if __name__ == "__main__":
    print("=" * 56)
    print("  UzMAX Local MVP -> http://127.0.0.1:5000")
    print("  Medicine AI + Robot Control (HAND/HEAD/MOVE)")
    print("=" * 56)
    uvicorn.run(app, host="127.0.0.1", port=5000, log_level="info")
