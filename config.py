import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


@dataclass
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    bot_book_url: str = os.getenv("BOT_BOOK_URL", "https://delta-lane.com")
    bot_book_api_key: str = os.getenv("BOT_BOOK_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    auto_interval: int = int(os.getenv("AUTO_INTERVAL", "300"))


settings = Settings()
