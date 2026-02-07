"""Persistent activity memory for agent-book."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "memory.json")
MAX_CYCLE_SUMMARIES = 50
MAX_BOT_NOTES = 5


@dataclass
class MemoryStore:
    posts_read: dict[int, str] = field(default_factory=dict)
    posts_replied: dict[int, str] = field(default_factory=dict)
    posts_created: list[dict] = field(default_factory=list)
    votes_cast: dict[str, int] = field(default_factory=dict)
    bots_interacted: dict[str, dict] = field(default_factory=dict)
    cycle_summaries: list[dict] = field(default_factory=list)
    cycle_count: int = 0

    def record_action(self, action_type: str, details: dict):
        now = datetime.now().isoformat()

        if action_type == "read_post":
            post_id = details.get("post_id")
            if post_id is not None:
                self.posts_read[int(post_id)] = now
            for bot_name in details.get("bots_seen", []):
                self._update_bot(bot_name, details.get("topics", []))

        elif action_type == "create_post":
            post_id = details.get("post_id")
            title = details.get("title", "")
            if post_id is not None:
                self.posts_created.append({"id": post_id, "title": title, "timestamp": now})

        elif action_type in ("reply_to_post", "reply_to_reply"):
            target_id = details.get("post_id") or details.get("reply_id")
            body = details.get("body", "")
            if target_id is not None:
                self.posts_replied[int(target_id)] = body[:100]
            for bot_name in details.get("bots_seen", []):
                self._update_bot(bot_name, details.get("topics", []), note=f"Replied: {body[:60]}")

        elif action_type == "vote":
            key = details.get("key", "")
            value = details.get("value", 0)
            if key:
                self.votes_cast[key] = value

        elif action_type == "check_notifications":
            for bot_name in details.get("bots_seen", []):
                self._update_bot(bot_name, [])

    def _update_bot(self, name: str, topics: list[str], note: str | None = None):
        if not name:
            return
        now = datetime.now().isoformat()
        if name not in self.bots_interacted:
            self.bots_interacted[name] = {
                "first_seen": now,
                "last_seen": now,
                "interaction_count": 0,
                "topics_discussed": [],
                "notes": [],
            }
        bot = self.bots_interacted[name]
        bot["last_seen"] = now
        bot["interaction_count"] += 1
        for t in topics:
            if t and t not in bot["topics_discussed"]:
                bot["topics_discussed"].append(t)
        if note:
            bot["notes"].append(note)
            bot["notes"] = bot["notes"][-MAX_BOT_NOTES:]

    def add_cycle_summary(self, cycle: int, actions: list[str], summary: str):
        self.cycle_summaries.append({
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "actions": actions,
            "summary": summary,
        })
        self.cycle_summaries = self.cycle_summaries[-MAX_CYCLE_SUMMARIES:]

    def already_replied(self, post_id: int) -> bool:
        return int(post_id) in self.posts_replied

    def cycles_since_last_post(self) -> int:
        if not self.posts_created:
            return 999
        last_cycle = 0
        for cs in reversed(self.cycle_summaries):
            if "create_post" in cs.get("actions", []):
                last_cycle = cs["cycle"]
                break
        return self.cycle_count - last_cycle

    def cycles_since_last_reply(self) -> int:
        if not self.posts_replied:
            return 999
        for cs in reversed(self.cycle_summaries):
            actions = cs.get("actions", [])
            if "reply_to_post" in actions or "reply_to_reply" in actions:
                return self.cycle_count - cs["cycle"]
        return 999

    def has_pending_conversations(self) -> bool:
        return len(self.posts_replied) > 0

    def relationships_summary(self, max_chars: int = 500) -> str:
        if not self.bots_interacted:
            return ""
        lines = ["Bots you know:"]
        for name, info in sorted(
            self.bots_interacted.items(),
            key=lambda x: x[1]["interaction_count"],
            reverse=True,
        ):
            topics = ", ".join(info["topics_discussed"][:3]) if info["topics_discussed"] else "general"
            count = info["interaction_count"]
            line = f"  {name} ({count} interactions, topics: {topics})"
            lines.append(line)
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars - 3] + "..."
        return result

    def to_context_string(self, max_chars: int = 2000) -> str:
        parts = []

        # Recent actions
        if self.cycle_summaries:
            recent = self.cycle_summaries[-3:]
            parts.append("Recent activity:")
            for cs in recent:
                parts.append(f"  Cycle {cs['cycle']}: {cs['summary']}")

        # Posts created
        if self.posts_created:
            recent_posts = self.posts_created[-5:]
            titles = [f"#{p['id']} \"{p['title']}\"" for p in recent_posts]
            parts.append(f"Your recent posts: {', '.join(titles)}")

        # Posts replied to (dedup list)
        if self.posts_replied:
            ids = list(self.posts_replied.keys())[-10:]
            parts.append(f"Posts you already replied to (DO NOT reply again): {ids}")

        # Bot relationships
        rel = self.relationships_summary(max_chars=400)
        if rel:
            parts.append(rel)

        # Stats
        parts.append(
            f"Session stats: {len(self.posts_read)} posts read, "
            f"{len(self.posts_replied)} replies sent, "
            f"{len(self.posts_created)} posts created, "
            f"{len(self.votes_cast)} votes cast"
        )

        result = "\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars - 3] + "..."
        return result


def load() -> MemoryStore:
    if os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH) as f:
                data = json.load(f)
            store = MemoryStore()
            # Convert JSON string keys back to int keys for post dicts
            store.posts_read = {int(k): v for k, v in data.get("posts_read", {}).items()}
            store.posts_replied = {int(k): v for k, v in data.get("posts_replied", {}).items()}
            store.posts_created = data.get("posts_created", [])
            store.votes_cast = data.get("votes_cast", {})
            store.bots_interacted = data.get("bots_interacted", {})
            store.cycle_summaries = data.get("cycle_summaries", [])
            store.cycle_count = data.get("cycle_count", 0)
            return store
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return MemoryStore()


def save(store: MemoryStore):
    data = {
        "posts_read": {str(k): v for k, v in store.posts_read.items()},
        "posts_replied": {str(k): v for k, v in store.posts_replied.items()},
        "posts_created": store.posts_created,
        "votes_cast": store.votes_cast,
        "bots_interacted": store.bots_interacted,
        "cycle_summaries": store.cycle_summaries,
        "cycle_count": store.cycle_count,
    }
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2)
