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


def generate_system_prompt(personality: dict, memory=None) -> str:
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
        "CRITICAL: When you want to post or reply, you MUST use the tools (create_post, reply_to_post, reply_to_reply). "
        "Never just compose text without submitting it via the appropriate tool call.",
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

    if memory:
        context = memory.to_context_string()
        if context:
            parts.append(f"\n--- YOUR MEMORY (what you did recently) ---\n{context}")
            parts.append(
                "\nIMPORTANT: Do NOT reply to posts you already replied to. "
                "Check the list above before replying."
            )

        relationships = memory.relationships_summary()
        if relationships:
            parts.append(f"\n--- SOCIAL AWARENESS ---\n{relationships}")

    return "\n".join(parts)
