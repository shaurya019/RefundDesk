"""Settings from environment variables (.env). No secrets in code."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


class Settings(BaseModel):
    # "openai" calls the real model. "scripted" uses a deterministic fake LLM (app/llm.py) so you can
    # run the whole stack, UI included, without an API key. Every guard runs for real in both modes.
    llm_mode: str = Field(default_factory=lambda: os.getenv("LLM_MODE", "openai"))
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))
    # gpt-5.x are reasoning models; "low" keeps latency down. Set to "" for non-reasoning models.
    reasoning_effort: str = Field(default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "low"))

    # mongodb://... for a real server, or mongomock:// for an in-memory database (no MongoDB needed).
    mongo_uri: str = Field(default_factory=lambda: os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    mongo_db: str = Field(default_factory=lambda: os.getenv("MONGO_DB", "guardrails_p5"))
    cors_origins: list[str] = Field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))

    auto_approve_limit: int = Field(default_factory=lambda: _int("AUTO_APPROVE_LIMIT", 1000))   # rupees
    num_reasks: int = Field(default_factory=lambda: _int("NUM_REASKS", 2))
    max_agent_steps: int = 4
    max_message_chars: int = 1500
