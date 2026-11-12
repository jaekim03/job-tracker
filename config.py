import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"
CACHE_DIR = ROOT / ".cache"


# Providers reached through the OpenAI-compatible chat API: base URL and the env var holding the key.
OPENAI_COMPATIBLE = {
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "openai-compatible": (None, "LLM_API_KEY"),
}
PROVIDERS = ["anthropic", *OPENAI_COMPATIBLE]
DEFAULT_MODEL = {"anthropic": "claude-haiku-5-5"}


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = ""
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None

    def __post_init__(self):
        self.provider = (self.provider or "anthropic").strip().lower()
        if self.provider not in PROVIDERS:
            raise SystemExit(f"llm.provider must be one of: {', '.join(PROVIDERS)}")
        self.model = self.model or DEFAULT_MODEL.get(self.provider, "")
        if not self.model:
            raise SystemExit(f"Set llm.model in config.yaml (any model {self.provider} offers).")
        if self.provider == "openai-compatible" and not self.base_url:
            raise SystemExit("llm.base_url is required for provider openai-compatible.")
        if self.provider in OPENAI_COMPATIBLE:
            default_url, default_key = OPENAI_COMPATIBLE[self.provider]
            self.base_url = self.base_url or default_url
            self.api_key_env = self.api_key_env or default_key
        else:
            self.api_key_env = self.api_key_env or "ANTHROPIC_API_KEY"


@dataclass
class Config:
    spreadsheet_id: str
    gmail_query: str
    ghosted_days: int = 60
    max_body_chars: int = 4000
    workers: int = 8
    llm: LLMConfig = field(default_factory=LLMConfig)


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
    llm = data.get("llm") or {}
    if not isinstance(llm, dict):
        raise SystemExit("llm in config.yaml must be a section with provider and model.")
    data["llm"] = LLMConfig(**{k: v for k, v in llm.items() if k in LLMConfig.__dataclass_fields__})
    known = Config.__dataclass_fields__.keys()
    return Config(**{k: v for k, v in data.items() if k in known})
