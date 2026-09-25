"""Regression coverage for request-time auth on delegated agent sessions."""

import asyncio
from types import SimpleNamespace

import src.agent_tools.session_tools as session_tools


class _ReloadedSession:
    id = "child-1"
    name = "DeepSeek child"
    owner = "alice"
    endpoint_url = "https://api.deepseek.com/v1/chat/completions"
    model = "deepseek-chat"
    headers = {}

    def get_context_messages(self):
        return []

    def add_message(self, message):
        pass


class _Manager:
    def get_session(self, session_id):
        return _ReloadedSession() if session_id == "child-1" else None


def test_reloaded_delegated_session_resolves_auth_request_locally(monkeypatch):
    calls = {}

    def resolve(sess, session_id, owner=None, *, persist_headers=True):
        calls.update({"session_id": session_id, "owner": owner, "persist_headers": persist_headers})
        sess.headers = {"Authorization": "Bearer request-only"}
        return True

    async def llm_call(url, model, messages, headers=None, timeout=None):
        assert headers == {"Authorization": "Bearer request-only"}
        return "child response"

    monkeypatch.setattr(session_tools, "get_session_manager", lambda: _Manager())
    monkeypatch.setattr("routes.chat_helpers.resolve_session_auth", resolve)
    monkeypatch.setattr("src.llm_core.llm_call_async", llm_call)

    result = asyncio.run(session_tools.send_to_session("child-1\nhello", owner="alice"))

    assert result["response"] == "child response"
    assert calls == {"session_id": "child-1", "owner": "alice", "persist_headers": False}


def test_invalid_delegated_endpoint_fails_closed(monkeypatch):
    monkeypatch.setattr(session_tools, "get_session_manager", lambda: _Manager())
    monkeypatch.setattr("routes.chat_helpers.resolve_session_auth", lambda *args, **kwargs: False)

    result = asyncio.run(session_tools.send_to_session("child-1\nhello", owner="alice"))

    assert result == {"error": "Unable to resolve a valid endpoint for this session"}
