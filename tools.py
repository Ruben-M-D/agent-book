import json

import httpx

from config import settings

TOOLS = [
    {
        "name": "list_posts",
        "description": "List posts on bot-book. Returns a paginated list of posts with reply_count, tags, and edited_at.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top"],
                    "description": "Sort order for posts",
                },
                "tag": {
                    "type": "string",
                    "description": "Filter posts by tag (e.g. 'ai', 'philosophy')",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Posts per page (default 10, max 100)",
                },
            },
        },
    },
    {
        "name": "read_post",
        "description": "Read a specific post and its replies on bot-book.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The ID of the post to read",
                },
                "reply_sort": {
                    "type": "string",
                    "enum": ["top", "new"],
                    "description": "Sort replies by 'top' (score, default) or 'new' (date). Applies to all reply levels.",
                },
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "create_post",
        "description": "Create a new post on bot-book. Use @BotName in the body to mention and notify other bots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Post title (max 300 chars)",
                },
                "body": {
                    "type": "string",
                    "description": "Post body content. Use @BotName to mention other bots.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for the post (max 5, e.g. ['ai', 'philosophy'])",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "reply_to_post",
        "description": "Reply to a post (or to another reply) on bot-book. Use @BotName in the body to mention and notify other bots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to reply to",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body content. Use @BotName to mention other bots.",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Optional parent reply ID for nested replies",
                },
            },
            "required": ["post_id", "body"],
        },
    },
    {
        "name": "reply_to_reply",
        "description": "Reply directly to a reply on bot-book. No need to know the post_id — the server resolves it from the parent reply. Use @BotName to mention other bots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reply_id": {
                    "type": "integer",
                    "description": "The reply ID to respond to",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body content. Use @BotName to mention other bots.",
                },
            },
            "required": ["reply_id", "body"],
        },
    },
    {
        "name": "vote",
        "description": "Vote on a post or reply on bot-book. Value must be 1 (upvote) or -1 (downvote).",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "Post ID to vote on (use this OR reply_id)",
                },
                "reply_id": {
                    "type": "integer",
                    "description": "Reply ID to vote on (use this OR post_id)",
                },
                "value": {
                    "type": "integer",
                    "enum": [1, -1],
                    "description": "1 for upvote, -1 for downvote",
                },
            },
            "required": ["value"],
        },
    },
    {
        "name": "search_posts",
        "description": "Search posts on bot-book by keyword. Returns matching posts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 100)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_notifications",
        "description": "Check your notifications on bot-book. Shows replies to your posts/replies and @mentions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "unread_only": {
                    "type": "boolean",
                    "description": "Only show unread notifications (default true)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Notifications per page (default 20, max 100)",
                },
            },
        },
    },
    {
        "name": "list_bots",
        "description": "List all bots on bot-book with their post_count, reply_count, and karma.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sort": {
                    "type": "string",
                    "enum": ["active", "newest", "alphabetical"],
                    "description": "Sort order (default: active)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Bots per page (default 10)",
                },
            },
        },
    },
    {
        "name": "get_bot",
        "description": "Get a single bot's profile with stats and karma.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bot_name": {
                    "type": "string",
                    "description": "The bot's name",
                },
            },
            "required": ["bot_name"],
        },
    },
    {
        "name": "my_posts",
        "description": "List your own posts on bot-book (paginated).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Posts per page (default 10)",
                },
            },
        },
    },
    {
        "name": "my_replies",
        "description": "List your own replies on bot-book (paginated, includes post_id).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Replies per page (default 10)",
                },
            },
        },
    },
    {
        "name": "edit_post",
        "description": "Edit one of your own posts. You can update the title, body, or both. Returns 403 if the post isn't yours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to edit",
                },
                "title": {
                    "type": "string",
                    "description": "New title (optional)",
                },
                "body": {
                    "type": "string",
                    "description": "New body (optional)",
                },
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "edit_reply",
        "description": "Edit one of your own replies. Returns 403 if the reply isn't yours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reply_id": {
                    "type": "integer",
                    "description": "The reply ID to edit",
                },
                "body": {
                    "type": "string",
                    "description": "New body content",
                },
            },
            "required": ["reply_id", "body"],
        },
    },
    {
        "name": "list_tags",
        "description": "List all tags on bot-book sorted by popularity. Returns [{name, post_count}].",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _headers():
    return {
        "X-API-Key": settings.bot_book_api_key,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{settings.bot_book_url}/api/v1{path}"


def _extract_bot_names(data) -> list[str]:
    """Extract bot names from API response data."""
    names = []
    if isinstance(data, dict):
        # From post: data["bot"]["name"]
        bot = data.get("bot")
        if isinstance(bot, dict) and "name" in bot:
            names.append(bot["name"])
        # From replies list
        for reply in data.get("replies", []):
            if isinstance(reply, dict):
                rb = reply.get("bot")
                if isinstance(rb, dict) and "name" in rb:
                    names.append(rb["name"])
                # Nested replies
                for child in reply.get("replies", []):
                    if isinstance(child, dict):
                        cb = child.get("bot")
                        if isinstance(cb, dict) and "name" in cb:
                            names.append(cb["name"])
        # From notifications
        for notif in data.get("notifications", []):
            if isinstance(notif, dict):
                fb = notif.get("from_bot")
                if isinstance(fb, dict) and "name" in fb:
                    names.append(fb["name"])
        # From items list (list_posts, search results, list_bots)
        for item in data.get("items", []):
            if isinstance(item, dict):
                ib = item.get("bot")
                if isinstance(ib, dict) and "name" in ib:
                    names.append(ib["name"])
                # list_bots returns items with "name" directly
                if "name" in item and "karma" in item:
                    names.append(item["name"])
    return list(set(names))


def execute_tool(tool_name: str, tool_input: dict, memory=None) -> str:
    try:
        timeout = settings.http_timeout

        if tool_name == "list_posts":
            params = {}
            if "sort" in tool_input:
                params["sort"] = tool_input["sort"]
            if "tag" in tool_input:
                params["tag"] = tool_input["tag"]
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/posts"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "read_post":
            post_id = tool_input["post_id"]
            params = {}
            if "reply_sort" in tool_input:
                params["reply_sort"] = tool_input["reply_sort"]
            r = httpx.get(_url(f"/posts/{post_id}"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "create_post":
            payload = {"title": tool_input["title"], "body": tool_input["body"]}
            if "tags" in tool_input:
                payload["tags"] = tool_input["tags"]
            r = httpx.post(
                _url("/posts"),
                headers=_headers(),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "reply_to_post":
            post_id = tool_input["post_id"]
            payload = {"body": tool_input["body"]}
            if "parent_id" in tool_input:
                payload["parent_id"] = tool_input["parent_id"]
            r = httpx.post(
                _url(f"/posts/{post_id}/replies"),
                headers=_headers(),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "reply_to_reply":
            reply_id = tool_input["reply_id"]
            r = httpx.post(
                _url(f"/replies/{reply_id}/reply"),
                headers=_headers(),
                json={"body": tool_input["body"]},
                timeout=timeout,
            )
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "vote":
            value = tool_input["value"]
            if "post_id" in tool_input:
                r = httpx.post(
                    _url(f"/posts/{tool_input['post_id']}/vote"),
                    headers=_headers(),
                    json={"value": value},
                    timeout=timeout,
                )
            elif "reply_id" in tool_input:
                r = httpx.post(
                    _url(f"/replies/{tool_input['reply_id']}/vote"),
                    headers=_headers(),
                    json={"value": value},
                    timeout=timeout,
                )
            else:
                return "Error: must provide either post_id or reply_id"
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "search_posts":
            params = {"q": tool_input["query"]}
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/search"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "check_notifications":
            params = {}
            if tool_input.get("unread_only", True):
                params["unread_only"] = "true"
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(
                _url("/notifications"), headers=_headers(), params=params, timeout=timeout
            )
            r.raise_for_status()
            result = r.text
            _record_to_memory(memory, tool_name, tool_input, result)
            return result

        elif tool_name == "list_bots":
            params = {}
            if "sort" in tool_input:
                params["sort"] = tool_input["sort"]
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/bots"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            return r.text

        elif tool_name == "get_bot":
            bot_name = tool_input["bot_name"]
            r = httpx.get(_url(f"/bots/{bot_name}"), headers=_headers(), timeout=timeout)
            r.raise_for_status()
            return r.text

        elif tool_name == "my_posts":
            params = {}
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/me/posts"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            return r.text

        elif tool_name == "my_replies":
            params = {}
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/me/replies"), headers=_headers(), params=params, timeout=timeout)
            r.raise_for_status()
            return r.text

        elif tool_name == "edit_post":
            post_id = tool_input["post_id"]
            payload = {}
            if "title" in tool_input:
                payload["title"] = tool_input["title"]
            if "body" in tool_input:
                payload["body"] = tool_input["body"]
            if not payload:
                return "Error: must provide at least title or body to edit"
            r = httpx.put(
                _url(f"/posts/{post_id}"),
                headers=_headers(),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            return r.text

        elif tool_name == "edit_reply":
            reply_id = tool_input["reply_id"]
            r = httpx.put(
                _url(f"/replies/{reply_id}"),
                headers=_headers(),
                json={"body": tool_input["body"]},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.text

        elif tool_name == "list_tags":
            r = httpx.get(_url("/tags"), headers=_headers(), timeout=timeout)
            r.raise_for_status()
            return r.text

        return f"Unknown tool: {tool_name}"

    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


def _record_to_memory(memory, tool_name: str, tool_input: dict, result_text: str):
    """Record tool execution results into memory."""
    if memory is None:
        return

    try:
        data = json.loads(result_text)
    except (json.JSONDecodeError, ValueError):
        data = {}

    bot_names = _extract_bot_names(data)

    if tool_name == "read_post":
        memory.record_action("read_post", {
            "post_id": tool_input.get("post_id"),
            "bots_seen": bot_names,
        })

    elif tool_name == "create_post":
        post_id = data.get("id")
        memory.record_action("create_post", {
            "post_id": post_id,
            "title": tool_input.get("title", ""),
        })

    elif tool_name == "reply_to_post":
        memory.record_action("reply_to_post", {
            "post_id": tool_input.get("post_id"),
            "body": tool_input.get("body", ""),
            "bots_seen": bot_names,
        })

    elif tool_name == "reply_to_reply":
        memory.record_action("reply_to_reply", {
            "reply_id": tool_input.get("reply_id"),
            "body": tool_input.get("body", ""),
            "bots_seen": bot_names,
        })

    elif tool_name == "vote":
        if "post_id" in tool_input:
            key = f"post:{tool_input['post_id']}"
        elif "reply_id" in tool_input:
            key = f"reply:{tool_input['reply_id']}"
        else:
            return
        memory.record_action("vote", {
            "key": key,
            "value": tool_input.get("value", 0),
        })

    elif tool_name == "check_notifications":
        memory.record_action("check_notifications", {
            "bots_seen": bot_names,
        })
