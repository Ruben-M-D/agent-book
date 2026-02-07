import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


# Pricing per 1M tokens (input, output) in USD
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
}


@dataclass
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    bot_book_url: str = os.getenv("BOT_BOOK_URL", "https://delta-lane.com")
    bot_book_api_key: str = os.getenv("BOT_BOOK_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    auto_interval: int = int(os.getenv("AUTO_INTERVAL", "300"))
    max_iterations: int = int(os.getenv("MAX_ITERATIONS", "20"))
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "30"))
    output_buffer_lines: int = int(os.getenv("OUTPUT_BUFFER_LINES", "5000"))


settings = Settings()
