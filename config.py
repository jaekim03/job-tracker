import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"
CACHE_DIR = ROOT / ".cache"


@dataclass
class Config:
    spreadsheet_id: str
    gmail_query: str
    ghosted_days: int = 30
    review_threshold: float = 0.7
    max_body_chars: int = 4000
    workers: int = 8


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    if not CONFIG_PATH.exists():
        raise SystemExit("config.yaml not found. Copy config.example.yaml to config.yaml and fill it in.")
    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    if not data.get("spreadsheet_id") or "PASTE" in data["spreadsheet_id"]:
        raise SystemExit("Set spreadsheet_id in config.yaml.")
    # Accept a full sheet URL as well as a bare ID.
    m = re.search(r"/d/([A-Za-z0-9_-]+)", data["spreadsheet_id"])
    if m:
        data["spreadsheet_id"] = m.group(1)
    known = Config.__dataclass_fields__.keys()
    return Config(**{k: v for k, v in data.items() if k in known})
