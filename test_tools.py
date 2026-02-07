"""Tests for influence-related changes in tools.py."""

from unittest.mock import MagicMock, patch

import pytest

from tools import TOOLS, execute_tool


# ── Schema tests ──────────────────────────────────────────────────────────


def _tool_by_name(name: str) -> dict:
    return next(t for t in TOOLS if t["name"] == name)


class TestReplyToPostSchema:
    tool = _tool_by_name("reply_to_post")
    props = tool["input_schema"]["properties"]

    def test_influence_property_exists(self):
        assert "influence" in self.props

    def test_influence_type_is_integer(self):
        assert self.props["influence"]["type"] == "integer"

    def test_influence_min_max(self):
        assert self.props["influence"]["minimum"] == -5
        assert self.props["influence"]["maximum"] == 5

    def test_influence_is_required(self):
        assert "influence" in self.tool["input_schema"]["required"]


class TestReplyToReplySchema:
    tool = _tool_by_name("reply_to_reply")
    props = tool["input_schema"]["properties"]

    def test_influence_property_exists(self):
        assert "influence" in self.props

    def test_influence_type_is_integer(self):
        assert self.props["influence"]["type"] == "integer"

    def test_influence_min_max(self):
        assert self.props["influence"]["minimum"] == -5
        assert self.props["influence"]["maximum"] == 5

    def test_influence_is_required(self):
        assert "influence" in self.tool["input_schema"]["required"]


class TestGetInfluenceSchema:
    tool = _tool_by_name("get_influence")

    def test_tool_exists(self):
        assert self.tool["name"] == "get_influence"

    def test_bot_name_required(self):
        assert "bot_name" in self.tool["input_schema"]["required"]

    def test_has_pagination_params(self):
        props = self.tool["input_schema"]["properties"]
        assert "page" in props
        assert "per_page" in props

    def test_bot_name_is_string(self):
        assert self.tool["input_schema"]["properties"]["bot_name"]["type"] == "string"


class TestDescriptionUpdates:
    def test_list_bots_mentions_influence_score(self):
        tool = _tool_by_name("list_bots")
        assert "influence_score" in tool["description"]

    def test_get_bot_mentions_influence_score(self):
        tool = _tool_by_name("get_bot")
        assert "influence_score" in tool["description"]


# ── Execution tests ───────────────────────────────────────────────────────


def _mock_response(text='{"ok": true}', status_code=200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


class TestReplyToPostExecution:
    @patch("tools.httpx.post")
    def test_influence_sent_in_payload(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_post", {
            "post_id": 1,
            "body": "Great post!",
            "influence": 3,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["influence"] == 3

    @patch("tools.httpx.post")
    def test_negative_influence_sent(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_post", {
            "post_id": 1,
            "body": "Disagree",
            "influence": -4,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["influence"] == -4

    @patch("tools.httpx.post")
    def test_zero_influence_sent(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_post", {
            "post_id": 1,
            "body": "Neutral",
            "influence": 0,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["influence"] == 0

    @patch("tools.httpx.post")
    def test_parent_id_still_works(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_post", {
            "post_id": 1,
            "body": "Nested reply",
            "influence": 2,
            "parent_id": 42,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["parent_id"] == 42
        assert kwargs["json"]["influence"] == 2


class TestReplyToReplyExecution:
    @patch("tools.httpx.post")
    def test_influence_sent_in_payload(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_reply", {
            "reply_id": 10,
            "body": "Interesting point",
            "influence": 5,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["influence"] == 5
        assert kwargs["json"]["body"] == "Interesting point"

    @patch("tools.httpx.post")
    def test_negative_influence_sent(self, mock_post):
        mock_post.return_value = _mock_response()
        execute_tool("reply_to_reply", {
            "reply_id": 10,
            "body": "Hard disagree",
            "influence": -5,
        })
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["influence"] == -5


class TestGetInfluenceExecution:
    @patch("tools.httpx.get")
    def test_calls_correct_endpoint(self, mock_get):
        mock_get.return_value = _mock_response()
        execute_tool("get_influence", {"bot_name": "TestBot"})
        args, kwargs = mock_get.call_args
        assert "/bots/TestBot/influence" in args[0]

    @patch("tools.httpx.get")
    def test_passes_pagination(self, mock_get):
        mock_get.return_value = _mock_response()
        execute_tool("get_influence", {
            "bot_name": "TestBot",
            "page": 2,
            "per_page": 25,
        })
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["page"] == 2
        assert kwargs["params"]["per_page"] == 25

    @patch("tools.httpx.get")
    def test_returns_response_text(self, mock_get):
        mock_get.return_value = _mock_response('{"items": []}')
        result = execute_tool("get_influence", {"bot_name": "TestBot"})
        assert result == '{"items": []}'

    @patch("tools.httpx.get")
    def test_no_pagination_params_when_omitted(self, mock_get):
        mock_get.return_value = _mock_response()
        execute_tool("get_influence", {"bot_name": "TestBot"})
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {}


class TestUnknownTool:
    def test_unknown_tool_still_works(self):
        result = execute_tool("nonexistent_tool", {})
        assert "Unknown tool" in result
