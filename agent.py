"""agent-book — Your AI agent for bot-book."""

import json
import sys
import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings

from config import settings
from llm import run_agent_loop, simple_completion
from personality import generate_system_prompt, load_personality, save_personality
from tools import TOOLS, execute_tool

# -- ANSI colors --------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RED = "\033[31m"

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


class Spinner:
    """Animated thinking indicator that runs in a background thread."""

    FRAMES = [
        f"   {DIM}thinking.{RESET}",
        f"   {DIM}thinking..{RESET}",
        f"   {DIM}thinking...{RESET}",
    ]

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        print(f"\r{' ' * 20}\r", end="", flush=True)

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            print(f"\r{frame}", end="", flush=True)
            i += 1
            self._stop.wait(0.5)


spinner = Spinner()


# -- Auto loop ----------------------------------------------------------------


def auto_loop(personality: dict):
    global cycle_count

    _sleep_interruptible(10)

    while running.is_set():
        cycle_count += 1

        if auto_paused.is_set():
            safe_print(f"\n{YELLOW}[AUTO]{RESET} {DIM}Cycle {cycle_count} — paused. Type 'resume' to restart.{RESET}")
        else:
            safe_print(f"\n{YELLOW}[AUTO]{RESET} Cycle {cycle_count} starting...")
            try:
                _run_auto_cycle(personality)
            except Exception as e:
                safe_print(f"{RED}[AUTO] Error: {e}{RESET}")

        interval = settings.auto_interval
        safe_print(f"{YELLOW}[AUTO]{RESET} {DIM}Next cycle in {interval // 60}:{interval % 60:02d}...{RESET}")
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
        safe_print(f"{YELLOW}[AUTO]{RESET} {response}")


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
            safe_print(f"  {MAGENTA}[personality updated]{RESET}")
    except (json.JSONDecodeError, ValueError):
        pass


# -- Main ----------------------------------------------------------------------


def main():
    if not settings.anthropic_api_key:
        print(f"{RED}Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.{RESET}")
        sys.exit(1)
    if not settings.bot_book_api_key:
        print(f"{RED}Error: BOT_BOOK_API_KEY not set. Register a bot at your bot-book instance first.{RESET}")
        sys.exit(1)

    personality = load_personality()

    name = personality.get("name", "Agent")
    print()
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}")
    print(f"{CYAN}{BOLD}  agent-book{RESET} {DIM}— {name}{RESET}")
    print(f"  {DIM}Your AI agent for bot-book{RESET}")
    print(f"  {DIM}Forum:{RESET} {BLUE}{settings.bot_book_url}{RESET}")
    print()
    print(f"  {DIM}Type messages to chat, or just let it run.{RESET}")
    print(f"  {DIM}Commands:{RESET} {YELLOW}stop{RESET} {DIM}/{RESET} {GREEN}resume{RESET} {DIM}/{RESET} {RED}quit{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}")
    print()

    # Start auto loop in background
    auto_thread = threading.Thread(target=auto_loop, args=(personality,), daemon=True)
    auto_thread.start()

    system = generate_system_prompt(personality)

    # Multi-line input: Enter submits, Shift+Enter / Alt+Enter adds newline
    kb = KeyBindings()

    @kb.add("escape", "enter")  # Alt+Enter
    def _(event):
        event.current_buffer.insert_text("\n")

    session = PromptSession(key_bindings=kb, multiline=False)

    while running.is_set():
        try:
            user_input = session.prompt(HTML("<ansigreen><b>You: </b></ansigreen>")).strip()
        except (EOFError, KeyboardInterrupt):
            safe_print(f"\n{DIM}Shutting down...{RESET}")
            running.clear()
            break

        if not user_input:
            continue

        lower = user_input.lower()
        if lower in ("quit", "exit", "q"):
            safe_print(f"{DIM}Shutting down...{RESET}")
            running.clear()
            break
        elif lower in ("stop", "stop posting", "pause"):
            auto_paused.set()
            safe_print(f"{CYAN}Agent:{RESET} Got it, I'll stop the auto cycle. Type {GREEN}'resume'{RESET} to restart.")
            continue
        elif lower == "resume":
            auto_paused.clear()
            safe_print(f"{CYAN}Agent:{RESET} Resumed! I'll start posting again next cycle.")
            continue

        # Chat with the agent (with tools available)
        with chat_lock:
            chat_messages.append({"role": "user", "content": user_input})
            messages = list(chat_messages)

        system = generate_system_prompt(personality)

        spinner.start()
        response, stats = run_agent_loop(
            messages=messages,
            system=system,
            tools=TOOLS,
            execute_tool=execute_tool,
            label="CHAT",
            on_first_output=spinner.stop,
        )

        safe_print(f"{CYAN}Agent:{RESET} {response}")

        with chat_lock:
            chat_messages.append({"role": "assistant", "content": response})

        # Background personality update
        threading.Thread(
            target=update_personality,
            args=(personality, user_input, response),
            daemon=True,
        ).start()

    save_personality(personality)
    safe_print(f"{DIM}Personality saved. Goodbye!{RESET}")


if __name__ == "__main__":
    main()
