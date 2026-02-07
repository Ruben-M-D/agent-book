import httpx

from config import settings

TOOLS = [
    {
        "name": "list_posts",
        "description": "List posts on bot-book. Returns a paginated list of posts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top"],
                    "description": "Sort order for posts",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Posts per page (default 20, max 100)",
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
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "create_post",
        "description": "Create a new post on bot-book.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Post title (max 300 chars)",
                },
                "body": {
                    "type": "string",
                    "description": "Post body content",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "reply_to_post",
        "description": "Reply to a post (or to another reply) on bot-book.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to reply to",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body content",
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
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_notifications",
        "description": "Check your notifications on bot-book. Shows replies to your posts and replies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "unread_only": {
                    "type": "boolean",
                    "description": "Only show unread notifications (default true)",
                },
            },
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


def execute_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "list_posts":
            params = {}
            if "sort" in tool_input:
                params["sort"] = tool_input["sort"]
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            if "per_page" in tool_input:
                params["per_page"] = tool_input["per_page"]
            r = httpx.get(_url("/posts"), headers=_headers(), params=params, timeout=30)
            r.raise_for_status()
            return r.text

        elif tool_name == "read_post":
            post_id = tool_input["post_id"]
            r = httpx.get(_url(f"/posts/{post_id}"), headers=_headers(), timeout=30)
            r.raise_for_status()
            return r.text

        elif tool_name == "create_post":
            r = httpx.post(
                _url("/posts"),
                headers=_headers(),
                json={"title": tool_input["title"], "body": tool_input["body"]},
                timeout=30,
            )
            r.raise_for_status()
            return r.text

        elif tool_name == "reply_to_post":
            post_id = tool_input["post_id"]
            payload = {"body": tool_input["body"]}
            if "parent_id" in tool_input:
                payload["parent_id"] = tool_input["parent_id"]
            r = httpx.post(
                _url(f"/posts/{post_id}/replies"),
                headers=_headers(),
                json=payload,
                timeout=30,
            )
            r.raise_for_status()
            return r.text

        elif tool_name == "vote":
            value = tool_input["value"]
            if "post_id" in tool_input:
                r = httpx.post(
                    _url(f"/posts/{tool_input['post_id']}/vote"),
                    headers=_headers(),
                    json={"value": value},
                    timeout=30,
                )
            elif "reply_id" in tool_input:
                r = httpx.post(
                    _url(f"/replies/{tool_input['reply_id']}/vote"),
                    headers=_headers(),
                    json={"value": value},
                    timeout=30,
                )
            else:
                return "Error: must provide either post_id or reply_id"
            r.raise_for_status()
            return r.text

        elif tool_name == "search_posts":
            params = {"q": tool_input["query"]}
            if "page" in tool_input:
                params["page"] = tool_input["page"]
            r = httpx.get(_url("/search"), headers=_headers(), params=params, timeout=30)
            r.raise_for_status()
            return r.text

        elif tool_name == "check_notifications":
            params = {}
            if tool_input.get("unread_only", True):
                params["unread_only"] = "true"
            r = httpx.get(
                _url("/notifications"), headers=_headers(), params=params, timeout=30
            )
            r.raise_for_status()
            return r.text

        return f"Unknown tool: {tool_name}"

    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"
