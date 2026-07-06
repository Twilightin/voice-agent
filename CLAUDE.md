# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A voice agent demo wiring **OpenAI Realtime (browser voice)** to a **LangGraph Supervisor (Python backend)**.
The design doc is `docs/superpowers/specs/2026-07-02-voice-agent-design.md`; the original architecture note
is `reference.md` (Japanese). The active task agents now operate on the local Neo4j factory-failure graph
described in `LANGCHAIN_AGENT_CONTEXT.md`.

## The one architectural rule

**Intent routing lives in exactly one place: the Supervisor.** Everything else is deliberately dumb.

```
browser voice ──▶ Realtime agent ──(single tool: ask_backend)──▶ POST /ask
                                                                     │
                                                          LangGraph Supervisor (router only)
                                                            ├─▶ qa_agent      (query_graphdb)
                                                            └─▶ registration_agent (draft → /v1 review table → voice はい → register_case → Neo4j)
```

- **Realtime side (Next.js: `frontend/app/v1/page.tsx` + `/v0`, sharing `frontend/lib/realtime.ts`)** does
  voice↔text only. It has **one** tool, `ask_backend`, which forwards the raw user request to the backend.
  Do **not** add more tools or business logic here — that would duplicate routing. Greetings/reask are the
  only things it answers itself.
- **Supervisor (`backend/app.py`)** reads intent and dispatches to one task agent, then returns a
  1–2 sentence summary. It does no real work itself.
- **Task agents** own their tools and do the actual work. Add capabilities by adding a new
  `create_agent(...)` to the `agents=[...]` list in `create_supervisor` — not by touching the frontend.
- **Q&A agent** runs read-only Neo4j Cypher through `query_graphdb`. It must use only the factory graph schema
  from `LANGCHAIN_AGENT_CONTEXT.md`.
- **Registration agent** collects `equipment/failure/cause/action` across turns using **per-session memory**
  (the supervisor is compiled with a `MemorySaver` checkpointer; `/ask` passes `session_id` as `thread_id`),
  so the voice layer is a dumb relay. It calls `draft_registration_record`, which reports missing fields or
  (when complete) stashes the structured record in `_PENDING["review"]`. `/ask` turns that into a
  `ui:{kind:"review",fields}` payload → `/v1` shows a **read-only table** and the AI asks
  「下記の情報で登録してよろしいでしょうか」. On a voice **「はい」** the agent calls `register_case`
  (schema-safe `MERGE`; `Equipment`/`Cause`/`Action` shared by name, `Failure` scoped by name+equipment) →
  `/ask` returns `ui:{kind:"registered"}` (table clears) and the AI says 「ナレッジに登録しました。」.
  Corrections are spoken; there is **no** form/buttons and **no** `/register` endpoint. Record shape is defined
  by `FAILURE_CASE_SCHEMA` (the seam for a future multi-record schema registry).
- `/ask` returns `{answer, ui}` — `answer` is the last message's text (spoken by the voice layer); `ui` is an
  optional structured payload (registration review table / registered signal) rendered by `/v1`. Requests
  carry a `session_id` used as the supervisor `thread_id` for per-session memory.

## Three models, on purpose

All configured in root `app_config.json` (`openai.*`), each overridable by env var:
- Supervisor + task agents use a **text** LLM (`chat_model`, `gpt-4o-mini`).
- The browser voice session uses the **Realtime** model (`realtime_model`, `gpt-realtime-mini`).
- User speech is transcribed by `transcribe_model` (`gpt-4o-mini-transcribe`), enabled via
  `session.audio.input.transcription` in `/session` so `/v1` can display what the user said.
Don't collapse these into one.

## Secrets & the ephemeral-key flow

The browser must **never** see `OPENAI_API_KEY`. Instead:
`POST /session` (backend) calls `https://api.openai.com/v1/realtime/client_secrets` with the real key and
returns a short-lived `ek_...` token (`value` field) plus `model`. The frontend fetches that, then does a
plain WebRTC handshake — `POST https://api.openai.com/v1/realtime/calls?model=…` with the `ek_` as Bearer
(see `frontend/lib/realtime.ts`). If you change model settings, update root `app_config.json`.

`OPENAI_API_KEY` lives in root `.env` (gitignored, loaded via `load_dotenv()`). Never move it into `frontend/`.

## Commands

`backend/` **is** the Python uv project (its own `pyproject.toml` + `.venv`); run uv commands from inside it.
`frontend/` is a separate npm/Next.js (App Router) project. `.env` stays at the **repo root** (one level above `backend/`);
`app.py` loads it by explicit path, so CWD doesn't matter.

```bash
# setup
cd backend && uv sync                             # backend deps → backend/.venv
cd frontend && npm install                        # frontend deps

# run (two processes)
cd backend && uv run uvicorn app:app --port 8000 --reload   # backend
cd frontend && npm run dev                                  # frontend → http://localhost:3000

# backend tests (headless — no audio/LLM needed), from backend/
uv run pytest                                                       # all
uv run pytest tests/test_ask.py::test_session_returns_ephemeral_value -q   # single test

# frontend build (Next.js typecheck + compile)
cd frontend && npm run build                       # runs `next build`
```

CORS in `backend/app.py` allows the frontend origin `http://localhost:3000`; if you change the frontend port,
update the allowlist or `/ask` and `/session` calls will be blocked.

## Verifying the voice loop

Automated tests cover `/ask` routing headlessly. The end-to-end voice path is verified **manually** in the
browser at **`/v1`** (new `useChat` UI, shows both user and assistant transcripts) — the old UI is at
**`/v0`**. Example utterances: "ポンプAが過熱したときの対策は？" routes to `qa_agent`;
"新しい故障ケースを登録したい" routes to `registration_agent`.
