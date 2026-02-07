"""agent-book — Your AI agent for bot-book."""

import json
import os
import random
import re
import sys
import threading
import time
from functools import partial

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
from memory import MemoryStore, load as load_memory, save as save_memory
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

# -- Session stats ------------------------------------------------------------

session_stats = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cost_usd": 0.0,
    "cycles_completed": 0,
    "posts_created": 0,
    "replies_sent": 0,
    "votes_cast": 0,
    "session_start": time.time(),
}
stats_lock = threading.Lock()

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

# Memory instance (loaded in main)
memory: MemoryStore | None = None


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


def append_output(text: str):
    """Thread-safe append to the output area, with buffer cap."""
    lines = text.split('\n')
    clean_lines = [strip_ansi(l) for l in lines]
    cap = settings.output_buffer_lines

    with output_lock:
        output_raw_lines.extend(lines)
        # Trim from front if over cap
        if len(output_raw_lines) > cap:
            excess = len(output_raw_lines) - cap
            del output_raw_lines[:excess]

    # Rebuild buffer text from raw lines
    with output_lock:
        new_text = "\n".join(strip_ansi(l) for l in output_raw_lines)

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


# -- Stats helpers ------------------------------------------------------------


def _update_stats(stats: dict):
    """Update session_stats from an LLM call's returned stats dict."""
    with stats_lock:
        usage = stats.get("usage", {})
        session_stats["total_input_tokens"] += usage.get("input_tokens", 0)
        session_stats["total_output_tokens"] += usage.get("output_tokens", 0)
        session_stats["total_cost_usd"] += stats.get("cost_usd", 0.0)
        for tool in stats.get("tools_used", []):
            if tool == "create_post":
                session_stats["posts_created"] += 1
            elif tool in ("reply_to_post", "reply_to_reply"):
                session_stats["replies_sent"] += 1
            elif tool == "vote":
                session_stats["votes_cast"] += 1


def _format_stats() -> str:
    with stats_lock:
        s = session_stats
    elapsed = time.time() - s["session_start"]
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    total_tokens = s["total_input_tokens"] + s["total_output_tokens"]
    return (
        f"{CYAN}{BOLD}Session Stats{RESET}\n"
        f"  {DIM}Uptime:{RESET} {mins}m {secs}s\n"
        f"  {DIM}Cycles completed:{RESET} {s['cycles_completed']}\n"
        f"  {DIM}Total tokens:{RESET} {total_tokens:,} ({s['total_input_tokens']:,} in / {s['total_output_tokens']:,} out)\n"
        f"  {DIM}Total cost:{RESET} ${s['total_cost_usd']:.4f}\n"
        f"  {DIM}Posts created:{RESET} {s['posts_created']}\n"
        f"  {DIM}Replies sent:{RESET} {s['replies_sent']}\n"
        f"  {DIM}Votes cast:{RESET} {s['votes_cast']}\n"
        f"  {DIM}Model:{RESET} {settings.claude_model}"
    )


# -- Adaptive cycle strategy --------------------------------------------------


def _pick_cycle_strategy(mem: MemoryStore) -> str:
    """Pick a varied strategy for the auto-cycle based on memory context."""
    strategies = []

    # Follow-up conversations — prioritize responding to bots who replied to us
    if mem.has_pending_conversations():
        strategies.append(("follow_up", 3))
    else:
        strategies.append(("follow_up", 1))

    # Create new post — more likely if it's been a while
    if mem.cycles_since_last_post() > 4:
        strategies.append(("create_post", 2))
    else:
        strategies.append(("create_post", 1))

    # Engage & reply — always available
    strategies.append(("engage_reply", 2))

    # Lurk mode — browse and vote only
    strategies.append(("lurk", 1))

    # Search & discover
    strategies.append(("search_discover", 1))

    # Weighted random selection
    names, weights = zip(*strategies)
    choice = random.choices(names, weights=weights, k=1)[0]

    prompts = {
        "follow_up": (
            "You are running an autonomous cycle. STRATEGY: Follow up on conversations.\n"
            "1. Check your notifications for any unread replies — this is your TOP PRIORITY\n"
            "2. For each notification where another bot replied to you, read that post and reply back thoughtfully\n"
            "3. If no notifications, browse 'new' posts and engage with 1-2\n"
            "4. Vote on posts you have opinions about\n\n"
            "Focus on continuing existing conversations. Be responsive and engaged."
        ),
        "create_post": (
            "You are running an autonomous cycle. STRATEGY: Create a new post.\n"
            "1. Check your notifications for any unread replies first\n"
            "2. Browse 'hot' and 'new' posts for inspiration\n"
            "3. Create an original post about something that interests you — share a thought, ask a question, or start a debate\n"
            "4. Vote on a few posts while browsing\n\n"
            "Be creative! Post something fresh and interesting that invites discussion.\n"
            "IMPORTANT: You MUST actually call the create_post tool to publish your post. Don't just compose it — submit it."
        ),
        "engage_reply": (
            "You are running an autonomous cycle. STRATEGY: Engage and reply.\n"
            "1. Check your notifications for any unread replies\n"
            "2. Browse recent posts (try 'hot' or 'new')\n"
            "3. Read 1-2 interesting posts in full\n"
            "4. Reply to posts where you have something genuine to say\n"
            "5. Vote on posts you have opinions about\n\n"
            "Be selective — only reply when you have something worth saying.\n"
            "IMPORTANT: You MUST actually call reply_to_post or reply_to_reply to submit your reply. Don't just compose it — submit it."
        ),
        "lurk": (
            "You are running an autonomous cycle. STRATEGY: Lurk mode.\n"
            "1. Check your notifications for any unread replies (reply if someone directly addressed you)\n"
            "2. Browse 'hot' and 'new' posts\n"
            "3. Read 2-3 interesting posts\n"
            "4. Vote on posts and replies — upvote good content, downvote bad\n"
            "5. Do NOT create new posts or replies this cycle (unless replying to a direct notification)\n\n"
            "Just observe and vote. Take it easy this round."
        ),
        "search_discover": (
            "You are running an autonomous cycle. STRATEGY: Search and discover.\n"
            "1. Check your notifications for any unread replies\n"
            "2. Search for posts about topics that interest you\n"
            "3. Read 1-2 posts from the search results\n"
            "4. If you find something interesting, reply or vote\n\n"
            "Explore and discover new conversations on topics you care about."
        ),
    }

    return prompts[choice]


# -- Auto loop ----------------------------------------------------------------


def auto_loop(personality: dict):
    global cycle_count

    _sleep_interruptible(10)

    while running.is_set():
        cycle_count += 1
        if memory:
            memory.cycle_count = cycle_count

        if auto_paused.is_set():
            append_output(f"{YELLOW}[AUTO]{RESET} {DIM}Cycle {cycle_count} — paused. Type 'resume' to restart.{RESET}")
        else:
            append_output(f"{YELLOW}[AUTO]{RESET} Cycle {cycle_count} starting...")
            try:
                _run_auto_cycle(personality)
            except Exception as e:
                append_output(f"{RED}[AUTO] Error: {e}{RESET}")

            with stats_lock:
                session_stats["cycles_completed"] = cycle_count

            # Save memory after each cycle
            if memory:
                try:
                    save_memory(memory)
                except Exception:
                    pass

        interval = settings.auto_interval
        append_output(f"{YELLOW}[AUTO]{RESET} {DIM}Next cycle in {interval // 60}:{interval % 60:02d}...{RESET}")
        _sleep_interruptible(interval)


def _sleep_interruptible(seconds: int):
    for _ in range(seconds):
        if not running.is_set():
            return
        time.sleep(1)


def _run_auto_cycle(personality: dict):
    system = generate_system_prompt(personality, memory=memory)

    auto_prompt = _pick_cycle_strategy(memory) if memory else (
        "You are running an autonomous cycle. Do the following:\n"
        "1. Check your notifications for any unread replies\n"
        "2. Browse recent posts (try 'hot' or 'new')\n"
        "3. Read 1-2 interesting posts\n"
        "4. If you have something genuine to say, reply to a post or create a new one\n"
        "5. Vote on posts you have opinions about\n\n"
        "Be selective — don't spam. Only post/reply when you have something worth saying. "
        "It's fine to just browse and vote if nothing catches your eye."
    )

    # Inject memory context into the prompt itself
    if memory:
        replied_ids = list(memory.posts_replied.keys())
        if replied_ids:
            auto_prompt += f"\n\nREMINDER: You already replied to these post IDs: {replied_ids[-20:]}. Do NOT reply to them again."

    with chat_lock:
        context_msgs = list(chat_messages[-6:])

    messages = context_msgs + [{"role": "user", "content": auto_prompt}]

    # Create execute_tool wrapper that passes memory
    tool_executor = partial(execute_tool, memory=memory)

    response, stats = run_agent_loop(
        messages=messages,
        system=system,
        tools=TOOLS,
        execute_tool=tool_executor,
        label="AUTO",
        output_fn=append_output,
    )

    _update_stats(stats)

    # Record cycle summary
    if memory:
        memory.add_cycle_summary(
            cycle=cycle_count,
            actions=stats.get("tools_used", []),
            summary=response[:150] if response else "no response",
        )

    if response:
        append_output(f"{YELLOW}[AUTO]{RESET} {response}")

    # Evolve personality from posts read this cycle (async)
    if "read_post" in stats.get("tools_used", []):
        posts_content = _extract_read_post_content(messages)
        if posts_content:
            threading.Thread(
                target=evolve_personality_from_posts,
                args=(personality, posts_content),
                daemon=True,
            ).start()


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


def _extract_read_post_content(messages: list[dict]) -> list[str]:
    """Walk messages to find tool_result content for read_post tool calls."""
    # Build a set of tool_use_ids that correspond to read_post calls
    read_post_ids = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, str):
            continue
        for block in content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "read_post":
                read_post_ids.add(block.id)

    # Now collect the tool_result content for those IDs
    posts = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if isinstance(content, str):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                if block.get("tool_use_id") in read_post_ids:
                    posts.append(block.get("content", ""))
    return posts


def evolve_personality_from_posts(personality: dict, posts_content: list[str]):
    """Evaluate posts read during an auto-cycle for personality influence.

    Only genuinely strong, well-argued points can update interests/opinions.
    """
    if not posts_content:
        return

    current_interests = json.dumps(personality.get("interests", []), indent=2)
    current_opinions = json.dumps(personality.get("opinions", []), indent=2)

    posts_text = "\n\n---\n\n".join(posts_content[:10])  # cap to avoid huge prompts

    prompt = (
        f"Current interests:\n{current_interests}\n\n"
        f"Current opinions:\n{current_opinions}\n\n"
        f"Posts read this cycle:\n{posts_text}\n\n"
        "You are evaluating whether any of these posts should influence this agent's personality.\n\n"
        "SET A VERY HIGH BAR. Most posts should result in NO_UPDATE.\n"
        "Only update if a post makes a genuinely strong, well-argued, thought-provoking point "
        "that would meaningfully shift this agent's thinking or introduce a new deep interest.\n\n"
        "Examples of what QUALIFIES:\n"
        "- A compelling argument that challenges an existing opinion\n"
        "- An insight that opens a genuinely new area of interest\n"
        "- A well-reasoned stance the agent hadn't considered\n\n"
        "Examples of what does NOT qualify:\n"
        "- Generic opinions or mild takes\n"
        "- Anything the agent already believes or is interested in\n"
        "- Casual conversation, jokes, or questions without substance\n"
        "- Short or low-effort posts\n\n"
        "You may ONLY modify:\n"
        "- interests: add new ones (do not remove existing)\n"
        "- opinions: add new or modify existing stances\n\n"
        "If any update is warranted, return ONLY a JSON object like:\n"
        '{"interests": ["existing1", "existing2", "new_interest"], '
        '"opinions": ["existing1", "modified_or_new_opinion"]}\n\n'
        "Include ALL existing values plus any additions/modifications.\n"
        "If no update is warranted (the usual case), return exactly: NO_UPDATE"
    )

    result = simple_completion(
        prompt,
        system="You strictly evaluate whether posts contain genuinely compelling points worth absorbing into a personality. You almost always return NO_UPDATE.",
    )

    if "NO_UPDATE" in result:
        return

    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            updates = json.loads(result[start:end])
            changed = False
            for key in ("interests", "opinions"):
                if key in updates and updates[key]:
                    personality[key] = updates[key]
                    changed = True
            if changed:
                save_personality(personality)
                append_output(f"  {MAGENTA}[personality evolved from post]{RESET}")
    except (json.JSONDecodeError, ValueError):
        pass


# -- Input processing (runs in background thread) -----------------------------

personality = None
input_area = None


def process_input(text: str):
    global personality

    lower = text.lower().strip()
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
    elif lower == "stats":
        append_output(_format_stats())
        invalidate()
        return
    elif lower == "memory":
        if memory:
            append_output(f"{CYAN}{BOLD}Memory Summary{RESET}\n{memory.to_context_string()}")
        else:
            append_output(f"{DIM}Memory not loaded.{RESET}")
        invalidate()
        return

    append_output(f"{GREEN}You:{RESET} {text}")

    with chat_lock:
        chat_messages.append({"role": "user", "content": text})
        messages = list(chat_messages)

    system = generate_system_prompt(personality, memory=memory)

    thinking.set()
    invalidate()

    # Create execute_tool wrapper that passes memory
    tool_executor = partial(execute_tool, memory=memory)

    response, stats = run_agent_loop(
        messages=messages,
        system=system,
        tools=TOOLS,
        execute_tool=tool_executor,
        label="CHAT",
        output_fn=append_output,
        on_first_output=lambda: (thinking.clear(), invalidate()),
    )

    _update_stats(stats)

    thinking.clear()
    append_output(f"{CYAN}Agent:{RESET} {response}")

    with chat_lock:
        chat_messages.append({"role": "assistant", "content": response})

    # Save memory after chat interactions too
    if memory:
        try:
            save_memory(memory)
        except Exception:
            pass

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
        if memory:
            save_memory(memory)
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

    with stats_lock:
        cost = session_stats["total_cost_usd"]
        total_tokens = session_stats["total_input_tokens"] + session_stats["total_output_tokens"]

    parts = f"  cycle {cycle_count} | ${cost:.4f} | {total_tokens:,} tokens | auto every {settings.auto_interval}s "
    return [("class:status", parts)]


ui_style = Style.from_dict({
    "separator": "#444444",
    "prompt": "ansigreen bold",
    "status": "#666666",
    "status-thinking": "ansiyellow",
    "status-paused": "ansired",
})


def main():
    global app, output_window, personality, input_area, memory

    if not settings.anthropic_api_key:
        print(f"Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)
    if not settings.bot_book_api_key:
        print(f"Error: BOT_BOOK_API_KEY not set. Register a bot at your bot-book instance first.")
        sys.exit(1)

    personality = load_personality()
    memory = load_memory()

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
        f"  {DIM}Commands:{RESET} {YELLOW}stop{RESET} {DIM}/{RESET} {GREEN}resume{RESET} {DIM}/{RESET} {YELLOW}stats{RESET} {DIM}/{RESET} {YELLOW}memory{RESET} {DIM}/{RESET} {RED}quit{RESET}",
        f"{CYAN}{BOLD}{'═' * 50}{RESET}",
    ]
    if chat_messages:
        banner_lines.append(f"  {DIM}Restored {len(chat_messages)} messages from last session{RESET}")
    if memory and (memory.posts_read or memory.posts_created):
        banner_lines.append(
            f"  {DIM}Memory loaded: {len(memory.posts_read)} posts read, "
            f"{len(memory.posts_created)} created, "
            f"{len(memory.bots_interacted)} bots known{RESET}"
        )
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
    if memory:
        save_memory(memory)


if __name__ == "__main__":
    main()
