"""Headless tests for the backend HTTP surface.

No live LLM / audio: the supervisor and the OpenAI HTTP call are mocked, so these
prove the /ask routing contract and the /session ephemeral-key flow without network.
Run from backend/:  uv run pytest
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def test_ask_returns_only_last_message_content(monkeypatch):
    # Supervisor returns a full messages list; /ask must surface only the last .content.
    fake_result = {
        "messages": [
            SimpleNamespace(content="(user)"),
            SimpleNamespace(content="東京は晴れ、気温25度です"),
        ]
    }
    monkeypatch.setattr(app_module.supervisor, "ainvoke", AsyncMock(return_value=fake_result))

    resp = client.post("/ask", json={"text": "東京の天気は?"})

    assert resp.status_code == 200
    assert resp.json() == {"answer": "東京は晴れ、気温25度です"}


def test_ask_returns_a_spoken_message_on_error(monkeypatch):
    # On failure the voice side must still get something to say (200 + text), not a 500.
    monkeypatch.setattr(
        app_module.supervisor, "ainvoke", AsyncMock(side_effect=RuntimeError("boom"))
    )

    resp = client.post("/ask", json={"text": "anything"})

    assert resp.status_code == 200
    assert "エラー" in resp.json()["answer"]


def test_session_returns_ephemeral_value(monkeypatch):
    # /session must return only the ephemeral `value`, never the real API key.
    class _FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {"value": "ek_test_123", "session": {"model": "gpt-realtime"}}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _FakeResp()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", _FakeClient)

    resp = client.post("/session")

    assert resp.status_code == 200
    assert resp.json() == {"value": "ek_test_123"}


def test_session_500_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resp = client.post("/session")

    assert resp.status_code == 500
