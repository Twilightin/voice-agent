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


def test_app_config_controls_openai_models():
    assert app_module.CONFIG_PATH.name == "app_config.json"
    assert app_module.REALTIME_MODEL == "gpt-realtime-mini"
    assert app_module.CHAT_MODEL == "gpt-4o-mini"
    assert app_module.TRANSCRIBE_MODEL == "gpt-4o-mini-transcribe"


def test_query_graphdb_rejects_write_cypher(monkeypatch):
    class _GraphDatabase:
        @staticmethod
        def driver(*a, **k):
            raise AssertionError("write queries must not touch Neo4j")

    monkeypatch.setattr(app_module, "GraphDatabase", _GraphDatabase)

    answer = app_module.query_graphdb("CREATE (:Equipment {name:'ポンプC'})")

    assert "read-only" in answer


def test_query_graphdb_returns_rows_from_neo4j(monkeypatch):
    class _Record:
        def data(self):
            return {"action": "再潤滑"}

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, cypher):
            assert "MATCH" in cypher
            return [_Record()]

    class _Driver:
        def verify_connectivity(self):
            return None

        def session(self, database):
            assert database == "neo4j"
            return _Session()

        def close(self):
            return None

    class _GraphDatabase:
        @staticmethod
        def driver(uri, auth):
            assert uri == app_module.NEO4J_URI
            assert auth == (app_module.NEO4J_USER, app_module.NEO4J_PASSWORD)
            return _Driver()

    monkeypatch.setattr(app_module, "GraphDatabase", _GraphDatabase)

    answer = app_module.query_graphdb(
        "MATCH (:Equipment {name:'ポンプA'})-[:HAS_FAILURE]->(:Failure {name:'過熱'})"
        "-[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(a:Action) RETURN a.name AS action"
    )

    assert "再潤滑" in answer


def test_draft_registration_record_stashes_review_without_writing():
    app_module._PENDING.clear()
    msg = app_module.draft_registration_record(
        equipment="ポンプC",
        failure="過熱",
        cause="冷却不足",
        action="冷却系点検",
    )

    # returns human guidance (no write); the structured record is stashed for the review table
    assert "まだ登録していません" in msg
    assert app_module._PENDING["review"] == {
        "equipment": "ポンプC",
        "failure": "過熱",
        "cause": "冷却不足",
        "action": "冷却系点検",
    }


def test_draft_registration_record_reports_missing_fields():
    app_module._PENDING.clear()
    msg = app_module.draft_registration_record(equipment="ポンプC", failure="過熱")
    assert "必要です" in msg
    assert "review" not in app_module._PENDING  # incomplete → nothing to review


def test_register_case_requires_all_four_fields():
    msg = app_module.register_case(equipment="ポンプC", failure="過熱")
    assert "必要です" in msg
    assert "cause" in msg and "action" in msg


def test_register_case_writes_schema_correct_cypher(monkeypatch):
    captured = {}

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, cypher, **params):
            captured["cypher"] = cypher
            captured["params"] = params
            return []

    class _Driver:
        def verify_connectivity(self):
            return None

        def session(self, database):
            assert database == "neo4j"
            return _Session()

        def close(self):
            return None

    class _GraphDatabase:
        @staticmethod
        def driver(uri, auth):
            assert uri == app_module.NEO4J_URI
            assert auth == (app_module.NEO4J_USER, app_module.NEO4J_PASSWORD)
            return _Driver()

    monkeypatch.setattr(app_module, "GraphDatabase", _GraphDatabase)

    app_module._PENDING.clear()
    msg = app_module.register_case(
        equipment="ポンプC", failure="過熱", cause="冷却不足", action="冷却系点検"
    )

    assert msg == "ナレッジに登録しました。"
    assert app_module._PENDING.get("registered") is True  # /ask turns this into ui:registered
    cy = captured["cypher"]
    # nodes + the three schema relationships must be present
    assert "MERGE (e:Equipment" in cy and "MERGE (f:Failure" in cy
    assert "HAS_FAILURE" in cy and "CAUSED_BY" in cy and "RESOLVED_BY" in cy
    assert captured["params"] == {
        "equipment": "ポンプC",
        "failure": "過熱",
        "cause": "冷却不足",
        "action": "冷却系点検",
    }


def test_ask_surfaces_review_ui_when_draft_is_complete(monkeypatch):
    # When registration_agent stashes a complete review, /ask returns ui.kind == "review".
    async def _fake_ainvoke(_inp, config=None):
        app_module._PENDING["review"] = {
            "equipment": "ポンプC",
            "failure": "過熱",
            "cause": "冷却不足",
            "action": "冷却系点検",
        }
        return {"messages": [SimpleNamespace(content="下記の情報で登録してよろしいでしょうか")]}

    monkeypatch.setattr(app_module.supervisor, "ainvoke", _fake_ainvoke)

    resp = client.post("/ask", json={"text": "登録して", "session_id": "s1"})

    assert resp.status_code == 200
    ui = resp.json()["ui"]
    assert ui["kind"] == "review"
    assert {"label": "設備", "value": "ポンプC"} in ui["fields"]


def test_agent_names_are_qa_and_registration():
    assert hasattr(app_module, "qa_agent")
    assert not hasattr(app_module, "q_and_a_agent")
    assert hasattr(app_module, "registration_agent")
    assert not hasattr(app_module, "case_registration_agent")


def test_ask_returns_only_last_message_content(monkeypatch):
    # Supervisor returns a full messages list; /ask must surface only the last .content.
    fake_result = {
        "messages": [
            SimpleNamespace(content="(user)"),
            SimpleNamespace(content="ポンプAの過熱には再潤滑が有効です"),
        ]
    }
    monkeypatch.setattr(app_module.supervisor, "ainvoke", AsyncMock(return_value=fake_result))

    resp = client.post("/ask", json={"text": "ポンプAが過熱したときの対策は?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "ポンプAの過熱には再潤滑が有効です"
    assert body["ui"] is None  # not a registration → no review table


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
            return {"value": "ek_test_123", "session": {"model": "gpt-realtime-mini"}}

    sent = {}  # capture the payload sent to OpenAI so we can assert on it

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            sent["json"] = k.get("json")
            return _FakeResp()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", _FakeClient)

    resp = client.post("/session")

    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == "ek_test_123"
    assert body["model"] == "gpt-realtime-mini"  # frontend needs it for /realtime/calls?model=
    # user-voice transcription must be requested so the frontend can show user turns
    transcription = sent["json"]["session"]["audio"]["input"]["transcription"]
    assert transcription["model"] == "gpt-4o-mini-transcribe"


def test_session_500_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resp = client.post("/session")

    assert resp.status_code == 500
