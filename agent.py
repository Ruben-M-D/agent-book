"""agent-book — Your AI agent for bot-book."""

import json
import sys
import threading
import time

from config import settings
from llm import run_agent_loop, simple_completion
from personality import generate_system_prompt, load_personality, save_personality
from tools import TOOLS, execute_tool

# -- Shared state -------------------------------------------------------------

auto_paused = threading.Event()
running = threading.Event()
running.set()

print_lock = threading.Lock()

chat_messages: list[dict] = []
chat_lock = threading.Lock()

cycle_count = 0


def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs, flush=True)


# -- Auto loop ----------------------------------------------------------------


def auto_loop(personality: dict):
    global cycle_count

    # Wait before first cycle so the user sees the banner
    _sleep_interruptible(10)

    while running.is_set():
        cycle_count += 1

        if auto_paused.is_set():
            safe_print(f"\n[AUTO] Cycle {cycle_count} — paused. Type 'resume' to restart.")
        else:
            safe_print(f"\n[AUTO] Cycle {cycle_count} starting...")
            try:
                _run_auto_cycle(personality)
            except Exception as e:
                safe_print(f"[AUTO] Error: {e}")

        interval = settings.auto_interval
        safe_print(f"[AUTO] Next cycle in {interval // 60}:{interval % 60:02d}...")
        _sleep_interruptible(interval)


def _sleep_interruptible(seconds: int):
    """Sleep in 1-second increments so we can exit quickly."""
    for _ in range(seconds):
        if not running.is_set():
            return
        time.sleep(1)


def _run_auto_cycle(personality: dict):
    system = generate_system_prompt(personality)

    auto_prompt = (
        "You are running an autonomous cycle. Do the following:\n"
        "1. Check your notifications for any unread replies\n"
        "2. Browse recent posts (try 'hot' or 'new')\n"
        "3. Read 1-2 interesting posts\n"
        "4. If you have something genuine to say, reply to a post or create a new one\n"
        "5. Vote on posts you have opinions about\n\n"
        "Be selective — don't spam. Only post/reply when you have something worth saying. "
        "It's fine to just browse and vote if nothing catches your eye."
    )

    # Include recent chat context so the auto loop knows about user instructions
    with chat_lock:
        context_msgs = list(chat_messages[-6:])

    messages = context_msgs + [{"role": "user", "content": auto_prompt}]

    response, stats = run_agent_loop(
        messages=messages,
        system=system,
        tools=TOOLS,
        execute_tool=execute_tool,
        label="AUTO",
    )

    if response:
        safe_print(f"[AUTO] {response}")


# -- Personality update --------------------------------------------------------


def update_personality(personality: dict, user_message: str, agent_response: str):
    """Use Claude to analyze the conversation and update personality if needed."""
    prompt = (
        f"Current personality:\n{json.dumps(personality, indent=2)}\n\n"
        f"User said: {user_message}\n"
        f"Agent replied: {agent_response}\n\n"
        "Based on this exchange, should the personality be updated? "
        "The user might be shaping the agent's identity, interests, tone, or giving instructions.\n\n"
        "If updates are needed, return ONLY a JSON object with the updated personality fields. "
        "Keep existing values unless explicitly changed. "
        "If no updates needed, return exactly: NO_UPDATE\n\n"
        "Fields: name (string), description (string), interests (list of strings), "
        "tone (string), opinions (list of strings), instructions (list of strings)"
    )

    result = simple_completion(
        prompt,
        system="You analyze conversations to extract personality traits and instructions.",
    )

    if "NO_UPDATE" in result:
        return

    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            updates = json.loads(result[start:end])
            for key, value in updates.items():
                if key in personality and value:
                    personality[key] = value
            save_personality(personality)
            safe_print("  [personality updated]")
    except (json.JSONDecodeError, ValueError):
        pass


# -- Main ----------------------------------------------------------------------


def main():
    if not settings.anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)
    if not settings.bot_book_api_key:
        print("Error: BOT_BOOK_API_KEY not set. Register a bot at your bot-book instance first.")
        sys.exit(1)

    personality = load_personality()

    name = personality.get("name", "Agent")
    print()
    print("=" * 50)
    print(f"  agent-book — {name}")
    print("  Your AI agent for bot-book")
    print(f"  Forum: {settings.bot_book_url}")
    print()
    print("  Type messages to chat, or just let it run.")
    print('  Commands: "stop" / "resume" / "quit"')
    print("=" * 50)
    print()

    # Start auto loop in background
    auto_thread = threading.Thread(target=auto_loop, args=(personality,), daemon=True)
    auto_thread.start()

    system = generate_system_prompt(personality)

    while running.is_set():
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            safe_print("\nShutting down...")
            running.clear()
            break

        if not user_input:
            continue

        lower = user_input.lower()
        if lower in ("quit", "exit", "q"):
            safe_print("Shutting down...")
            running.clear()
            break
        elif lower in ("stop", "stop posting", "pause"):
            auto_paused.set()
            safe_print("Agent: Got it, I'll stop the auto cycle. Type 'resume' to restart.")
            continue
        elif lower == "resume":
            auto_paused.clear()
            safe_print("Agent: Resumed! I'll start posting again next cycle.")
            continue

        # Chat with the agent (with tools available)
        with chat_lock:
            chat_messages.append({"role": "user", "content": user_input})
            messages = list(chat_messages)

        system = generate_system_prompt(personality)

        response, stats = run_agent_loop(
            messages=messages,
            system=system,
            tools=TOOLS,
            execute_tool=execute_tool,
            label="CHAT",
        )

        safe_print(f"Agent: {response}")

        with chat_lock:
            chat_messages.append({"role": "assistant", "content": response})

        # Background personality update
        threading.Thread(
            target=update_personality,
            args=(personality, user_input, response),
            daemon=True,
        ).start()

    save_personality(personality)
    safe_print("Personality saved. Goodbye!")


if __name__ == "__main__":
    main()
