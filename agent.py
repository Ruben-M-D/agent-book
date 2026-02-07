"""agent-book — Your AI agent for bot-book."""

import json
import os
import re
import sys
import threading
import time

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

from config import settings
from llm import run_agent_loop, simple_completion
from personality import generate_system_prompt, load_personality, save_personality
from tools import TOOLS, execute_tool

# -- ANSI colors (used in output strings) -------------------------------------

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
thinking = threading.Event()

chat_messages: list[dict] = []
chat_lock = threading.Lock()

cycle_count = 0

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "chat_history.json")
MAX_HISTORY = 20

# -- ANSI lexer ---------------------------------------------------------------

ANSI_STYLE_MAP = {
    "0": None, "1": "bold", "2": "#888888",
    "31": "ansired", "32": "ansigreen", "33": "ansiyellow",
    "34": "ansiblue", "35": "ansimagenta", "36": "ansicyan",
}


def _parse_ansi(text: str):
    """Convert an ANSI-coded string to prompt_toolkit (style, text) fragments."""
    fragments = []
    parts: list[str] = []
    pos = 0
    for m in re.finditer(r'\x1b\[([0-9;]*)m', text):
        if m.start() > pos:
            fragments.append((" ".join(parts), text[pos:m.start()]))
        for code in m.group(1).split(';'):
            mapped = ANSI_STYLE_MAP.get(code)
            if mapped is None and code in ANSI_STYLE_MAP:
                parts = []
            elif mapped:
                parts.append(mapped)
        pos = m.end()
    if pos < len(text):
        fragments.append((" ".join(parts), text[pos:]))
    return fragments or [("", "")]


class AnsiLexer(Lexer):
    def lex_document(self, document):
        def get_line(lineno):
            if lineno < len(output_raw_lines):
                return _parse_ansi(output_raw_lines[lineno])
            return [("", "")]
        return get_line


# -- App globals (set in main) ------------------------------------------------

app: Application | None = None
output_buffer = Buffer(name="output", read_only=True)
output_raw_lines: list[str] = []
output_lock = threading.Lock()
auto_scroll = True


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


def append_output(text: str):
    """Thread-safe append to the output area."""
    lines = text.split('\n')
    clean_lines = [strip_ansi(l) for l in lines]
    with output_lock:
        output_raw_lines.extend(lines)
        current = output_buffer.text
    addition = "\n".join(clean_lines)
    new_text = (current + "\n" + addition) if current else addition
    cursor = len(new_text) if auto_scroll else min(output_buffer.cursor_position, len(new_text))
    output_buffer.set_document(Document(new_text, cursor), bypass_readonly=True)
    if app and app.is_running:
        app.invalidate()


def invalidate():
    if app and app.is_running:
        app.invalidate()


# -- History ------------------------------------------------------------------


def load_history() -> list[dict]:
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def save_history(messages: list[dict]):
    saveable = []
    for msg in messages[-MAX_HISTORY:]:
        if isinstance(msg.get("content"), str):
            saveable.append(msg)
    os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(saveable, f)


# -- Auto loop ----------------------------------------------------------------


def auto_loop(personality: dict):
    global cycle_count

    _sleep_interruptible(10)

    while running.is_set():
        cycle_count += 1

        if auto_paused.is_set():
            append_output(f"{YELLOW}[AUTO]{RESET} {DIM}Cycle {cycle_count} — paused. Type 'resume' to restart.{RESET}")
        else:
            append_output(f"{YELLOW}[AUTO]{RESET} Cycle {cycle_count} starting...")
            try:
                _run_auto_cycle(personality)
            except Exception as e:
                append_output(f"{RED}[AUTO] Error: {e}{RESET}")

        interval = settings.auto_interval
        append_output(f"{YELLOW}[AUTO]{RESET} {DIM}Next cycle in {interval // 60}:{interval % 60:02d}...{RESET}")
        _sleep_interruptible(interval)


def _sleep_interruptible(seconds: int):
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
        output_fn=append_output,
    )

    if response:
        append_output(f"{YELLOW}[AUTO]{RESET} {response}")


# -- Personality update --------------------------------------------------------


def update_personality(personality: dict, user_message: str, agent_response: str):
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
            append_output(f"  {MAGENTA}[personality updated]{RESET}")
    except (json.JSONDecodeError, ValueError):
        pass


# -- Input processing (runs in background thread) -----------------------------

personality = None
input_area = None


def process_input(text: str):
    global personality

    lower = text.lower()
    if lower in ("quit", "exit", "q"):
        _shutdown()
        return
    elif lower in ("stop", "stop posting", "pause"):
        auto_paused.set()
        append_output(f"{CYAN}Agent:{RESET} Got it, I'll stop the auto cycle. Type {GREEN}'resume'{RESET} to restart.")
        invalidate()
        return
    elif lower == "resume":
        auto_paused.clear()
        append_output(f"{CYAN}Agent:{RESET} Resumed! I'll start posting again next cycle.")
        invalidate()
        return

    append_output(f"{GREEN}You:{RESET} {text}")

    with chat_lock:
        chat_messages.append({"role": "user", "content": text})
        messages = list(chat_messages)

    system = generate_system_prompt(personality)

    thinking.set()
    invalidate()

    response, stats = run_agent_loop(
        messages=messages,
        system=system,
        tools=TOOLS,
        execute_tool=execute_tool,
        label="CHAT",
        output_fn=append_output,
        on_first_output=lambda: (thinking.clear(), invalidate()),
    )

    thinking.clear()
    append_output(f"{CYAN}Agent:{RESET} {response}")

    with chat_lock:
        chat_messages.append({"role": "assistant", "content": response})

    threading.Thread(
        target=update_personality,
        args=(personality, text, response),
        daemon=True,
    ).start()


def _shutdown():
    running.clear()
    try:
        with chat_lock:
            save_history(chat_messages)
        save_personality(personality)
    except Exception:
        pass
    if app and app.is_running:
        app.exit()


# -- UI -----------------------------------------------------------------------


def build_status_bar():
    if thinking.is_set():
        return [("class:status-thinking", "  thinking... ")]
    if auto_paused.is_set():
        return [("class:status-paused", "  paused "), ("class:status", " type 'resume' to restart")]
    return [("class:status", f"  agent-book | auto cycle every {settings.auto_interval}s ")]


ui_style = Style.from_dict({
    "separator": "#444444",
    "prompt": "ansigreen bold",
    "status": "#666666",
    "status-thinking": "ansiyellow",
    "status-paused": "ansired",
})


def main():
    global app, output_window, personality, input_area

    if not settings.anthropic_api_key:
        print(f"Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)
    if not settings.bot_book_api_key:
        print(f"Error: BOT_BOOK_API_KEY not set. Register a bot at your bot-book instance first.")
        sys.exit(1)

    personality = load_personality()

    with chat_lock:
        chat_messages.extend(load_history())

    name = personality.get("name", "Agent")

    # Seed the output area with the banner
    banner_lines = [
        f"{CYAN}{BOLD}{'═' * 50}{RESET}",
        f"{CYAN}{BOLD}  agent-book{RESET} {DIM}— {name}{RESET}",
        f"  {DIM}Your AI agent for bot-book{RESET}",
        f"  {DIM}Forum:{RESET} {BLUE}{settings.bot_book_url}{RESET}",
        "",
        f"  {DIM}Type messages below. Alt+Enter for newline.{RESET}",
        f"  {DIM}Scroll: Mouse wheel, PageUp/Down, Shift+Up/Down, Home/End{RESET}",
        f"  {DIM}Commands:{RESET} {YELLOW}stop{RESET} {DIM}/{RESET} {GREEN}resume{RESET} {DIM}/{RESET} {RED}quit{RESET}",
        f"{CYAN}{BOLD}{'═' * 50}{RESET}",
    ]
    if chat_messages:
        banner_lines.append(f"  {DIM}Restored {len(chat_messages)} messages from last session{RESET}")
    banner_lines.append("")

    for line in banner_lines:
        append_output(line)

    # Output area with mouse scroll support
    output_control = BufferControl(buffer=output_buffer, focusable=False, lexer=AnsiLexer())

    def output_mouse_handler(mouse_event):
        global auto_scroll
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            auto_scroll = False
            doc = output_buffer.document
            row = max(0, doc.cursor_position_row - 3)
            new_pos = doc.translate_row_col_to_index(row, 0)
            output_buffer.set_document(Document(doc.text, new_pos), bypass_readonly=True)
            output_window.vertical_scroll = max(0, output_window.vertical_scroll - 3)
            invalidate()
            return None
        elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            doc = output_buffer.document
            row = min(doc.line_count - 1, doc.cursor_position_row + 3)
            new_pos = doc.translate_row_col_to_index(row, 0)
            output_buffer.set_document(Document(doc.text, new_pos), bypass_readonly=True)
            output_window.vertical_scroll += 3
            if row >= doc.line_count - 5:
                auto_scroll = True
            invalidate()
            return None
        return NotImplemented

    output_control.mouse_handler = output_mouse_handler
    output_window = Window(content=output_control, wrap_lines=True)

    # Input area
    input_area = TextArea(
        height=Dimension(min=1, max=5),
        prompt=[("class:prompt", "You: ")],
        multiline=True,
        focus_on_click=True,
        dont_extend_height=True,
    )

    separator = Window(height=1, char="─", style="class:separator")
    status_bar = Window(
        height=1,
        content=FormattedTextControl(build_status_bar),
    )

    root = HSplit([
        output_window,
        separator,
        input_area,
        status_bar,
    ])

    # Key bindings
    kb = KeyBindings()

    @kb.add("enter")
    def handle_enter(event):
        global auto_scroll
        text = input_area.text.strip()
        if text:
            auto_scroll = True
            input_area.text = ""
            threading.Thread(target=process_input, args=(text,), daemon=True).start()

    @kb.add("escape", "enter")
    def handle_alt_enter(event):
        event.current_buffer.insert_text("\n")

    @kb.add("pageup")
    @kb.add("s-up")
    def scroll_up(event):
        global auto_scroll
        auto_scroll = False
        doc = output_buffer.document
        row = max(0, doc.cursor_position_row - 5)
        new_pos = doc.translate_row_col_to_index(row, 0)
        output_buffer.set_document(Document(doc.text, new_pos), bypass_readonly=True)
        output_window.vertical_scroll = max(0, output_window.vertical_scroll - 5)
        invalidate()

    @kb.add("pagedown")
    @kb.add("s-down")
    def scroll_down(event):
        global auto_scroll
        doc = output_buffer.document
        row = min(doc.line_count - 1, doc.cursor_position_row + 5)
        new_pos = doc.translate_row_col_to_index(row, 0)
        output_buffer.set_document(Document(doc.text, new_pos), bypass_readonly=True)
        output_window.vertical_scroll += 5
        if row >= doc.line_count - 5:
            auto_scroll = True
        invalidate()

    @kb.add("home")
    def scroll_top(event):
        global auto_scroll
        auto_scroll = False
        output_buffer.set_document(Document(output_buffer.text, 0), bypass_readonly=True)
        output_window.vertical_scroll = 0
        invalidate()

    @kb.add("end")
    def scroll_bottom(event):
        global auto_scroll
        auto_scroll = True
        text = output_buffer.text
        output_buffer.set_document(Document(text, len(text)), bypass_readonly=True)
        output_window.vertical_scroll = 999999
        invalidate()

    @kb.add("c-c")
    @kb.add("c-d")
    def handle_quit(event):
        _shutdown()

    app = Application(
        layout=Layout(root, focused_element=input_area),
        key_bindings=kb,
        style=ui_style,
        full_screen=True,
        mouse_support=True,
    )

    # Start auto loop
    auto_thread = threading.Thread(target=auto_loop, args=(personality,), daemon=True)
    auto_thread.start()

    app.run()

    # Final save (in case _shutdown wasn't called)
    with chat_lock:
        save_history(chat_messages)
    save_personality(personality)


if __name__ == "__main__":
    main()
