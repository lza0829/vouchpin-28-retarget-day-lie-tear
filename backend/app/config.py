from __future__ import annotations
import os
from pathlib import Path

PROJECT_NAME = "Vouchpin"
API_PORT = 10800
DATA_DIR = Path(os.environ.get("DATA_DIR") or (Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "clipbond.db"
