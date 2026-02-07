import os

import yaml

from config import settings

PERSONALITY_PATH = os.path.join(os.path.dirname(__file__), "personality.yaml")

DEFAULT_PERSONALITY = {
    "name": "Agent",
    "description": "",
    "interests": [],
    "tone": "",
    "opinions": [],
    "instructions": [],
}


def load_personality() -> dict:
    if os.path.exists(PERSONALITY_PATH):
        with open(PERSONALITY_PATH) as f:
            data = yaml.safe_load(f)
            if data:
                return data
    return dict(DEFAULT_PERSONALITY)


def save_personality(personality: dict):
    with open(PERSONALITY_PATH, "w") as f:
        yaml.dump(personality, f, default_flow_style=False, allow_unicode=True)


def generate_system_prompt(personality: dict) -> str:
    name = personality.get("name", "Agent")
    desc = personality.get("description", "")
    interests = personality.get("interests", [])
    tone = personality.get("tone", "")
    opinions = personality.get("opinions", [])
    instructions = personality.get("instructions", [])

    parts = [
        f"You are {name}, an AI agent participating in bot-book — a public forum at {settings.bot_book_url}.",
        "You can browse posts, read discussions, create posts, reply, and vote.",
        "Be a genuine participant: share thoughts, ask questions, engage in debates.",
        "Keep posts and replies concise and natural — like a real forum user.",
    ]

    if desc:
        parts.append(f"\nAbout you: {desc}")

    if interests:
        parts.append(f"\nYour interests: {', '.join(interests)}")

    if tone:
        parts.append(f"\nYour tone/style: {tone}")

    if opinions:
        parts.append("\nYour opinions and stances:")
        for op in opinions:
            parts.append(f"  - {op}")

    if instructions:
        parts.append("\nSpecial instructions from the user:")
        for inst in instructions:
            parts.append(f"  - {inst}")

    return "\n".join(parts)
