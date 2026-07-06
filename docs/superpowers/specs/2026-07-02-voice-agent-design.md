# Voice Agent — Realtime × LangGraph Supervisor (Design)

**Date:** 2026-07-02
**Status:** Approved design, pending spec review
**Goal:** Turn the `reference.md` architecture and the `backend.py` / `voice.ts` snippets into a
**runnable end-to-end demo**: speak into the browser → LangGraph Supervisor routes to a task agent →
spoken answer back. The active agents operate on the local Neo4j factory-failure graph.

## Architecture

```
[user voice]
   ↓
[OpenAI Realtime (browser, WebRTC)]   ← voice I/O + intent only, one tool: ask_backend
   ↓  POST /ask
[LangGraph Supervisor (FastAPI)]      ← router only, no real work
   ├─→ qa_agent           (+ query_graphdb, read-only Neo4j Q&A)
   └─→ registration_agent (+ draft_registration_record, no write yet)
```

Role split (unchanged from `reference.md`):
- **Realtime**: speech↔text + read-back. No business logic. Only tool = `ask_backend`.
- **Supervisor**: reads intent, dispatches to one task agent, returns a 1–2 sentence summary.
- **Task agents**: run the actual tool and report the result. `qa_agent` reads the graph; `registration_agent`
  interviews for a proposed `Equipment -> Failure -> Cause -> Action` record without writing to Neo4j.

## Project layout (backend-contained Python + separate frontend)

> **Revised during implementation.** The plan started root-rooted, but the user consolidated the uv-init
> files into `backend/`, so `backend/` became the Python project root. `.env` stays at the repo root and
> `app.py` loads it by explicit path (independent of CWD).

```
voice-agent/
├── .env                      # OPENAI_API_KEY=...  (gitignored; repo root)
├── .env.example              # committed template
├── app_config.json            # OpenAI model, frontend origin, and local Neo4j settings
├── .gitignore                # root; ignores .env, .venv
├── reference.md / README.md / CLAUDE.md
├── backend/                  # Python uv project root
│   ├── pyproject.toml         # deps live here
│   ├── .python-version        # 3.12
│   ├── .gitignore
│   ├── .venv/                 # `uv sync` creates it here
│   ├── app.py                 # supervisor + FastAPI (from backend.py) + CORS + /session
│   └── tests/test_ask.py
└── frontend/
    ├── package.json           # @openai/agents, zod, vite, typescript
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html             # Start button + status line
    └── src/main.ts            # from voice.ts; fetch /session → connect
```

### Cleanup of uv-init artifacts
- **Delete** the `main.py` hello-world stubs and the superseded `backend/backend.py` / `voice.ts` snippets
  (content now lives in `app.py` / `main.ts`).
- **Delete** the duplicate empty `pyproject.toml` (deps consolidated into `backend/pyproject.toml`).
- `app.py` runs as `app:app` from inside `backend/`; no package `__init__.py` needed.

## Backend (`backend/app.py`)

Keeps the reference shape: `llm`, task agents created with `create_agent(...)`,
`create_supervisor(...).compile()`, and `POST /ask` returning `result["messages"][-1].content`.

Adds:
1. **config file** — root `app_config.json` holds `openai.chat_model`, `openai.realtime_model`,
   frontend origin, and Neo4j connection defaults.
2. **dotenv** — `load_dotenv()` at import so `OPENAI_API_KEY` is available.
3. **CORS** — `CORSMiddleware` allowing `http://localhost:3000` (frontend dev origin) so the browser can call `/ask` and `/session`.
4. **Neo4j tools** — `query_graphdb` accepts read-only `MATCH`/`CALL` Cypher only; `draft_registration_record`
   returns a proposed record and does not write.
5. **`POST /session`** — mints an ephemeral Realtime client secret:
   - Server-side `httpx` POST to `https://api.openai.com/v1/realtime/client_secrets`
     with `Authorization: Bearer <OPENAI_API_KEY>` and body
     `{"expires_after": {"anchor": "created_at", "seconds": 600},
       "session": {"type": "realtime", "model": "gpt-realtime-mini"}}`.
   - Returns `{"value": "<ek_...>"}` (the top-level `value` from OpenAI's response) to the browser.
   - The real API key never leaves the server.

**Model note:** root `app_config.json` defaults the supervisor/agents to `gpt-4o-mini` and the browser voice
session to `gpt-realtime-mini`.

**Dependencies:** `langgraph`, `langgraph-supervisor`, `langchain-openai`, `fastapi`,
`uvicorn[standard]`, `httpx`, `python-dotenv`, `pydantic`, `neo4j`. Dev: `pytest`, `pytest-asyncio`.

## Frontend (`frontend/`)

Vite + TypeScript. `src/main.ts` = `voice.ts` reworked so it runs in a real page:
- On **Start** click (needed for browser mic/audio gesture):
  1. `fetch('http://localhost:8000/session', {method:'POST'})` → `{ value }`.
  2. `await session.connect({ apiKey: value })`.
  3. Update status line to "connected / listening".
- `askBackend` tool unchanged: `POST http://localhost:8000/ask` with `{ text: request }`, returns `data.answer`.
- `RealtimeAgent` instructions unchanged from `voice.ts`.
- `index.html`: a `#start` button and a `#status` element; imports `src/main.ts` as a module.

## Data flow

1. Browser Start → `POST /session` → backend mints `ek_...` → returns to browser.
2. `session.connect({apiKey})` → WebRTC to Realtime; mic capture + playback auto-configured.
3. User speaks → Realtime decides tool call → `ask_backend({request})`.
4. `ask_backend` → `POST /ask {text}` → supervisor routes to `qa_agent` or `registration_agent` → summary text.
5. Summary returned to Realtime → spoken back to user (reworded short, per instructions).

## Error handling

- `/session`: if `OPENAI_API_KEY` missing → 500 with clear message; if OpenAI call fails → propagate status + short error body (no key leakage).
- `/ask`: wrap `supervisor.ainvoke` in try/except → return `{"answer": "<error message>"}` so the voice side always has something to say.
- Frontend: if `/session` fetch fails → show error in `#status`, keep Start enabled to retry.

## Testing

- **Backend (headless, no audio):** `tests/test_ask.py` with `pytest` + FastAPI `TestClient`.
  Monkeypatch the supervisor's `ainvoke` (or patch `ChatOpenAI`) so no live LLM call is made;
  assert `POST /ask` returns the last message content shape `{"answer": ...}`.
  Optionally a `/session` test that monkeypatches `httpx` to assert we return `value`.
- **Voice loop:** verified manually in-browser (speak "ポンプAが過熱したときの対策は？" → `qa_agent`;
  "新しい故障ケースを登録したい" → `registration_agent`). Documented in README as a manual check.

## Run instructions (README)

```bash
# one-time
cd backend && uv sync       # installs backend deps into backend/.venv
cd frontend && npm install  # installs frontend deps

# terminal 1 — backend
cd backend && uv run uvicorn app:app --port 8000 --reload

# terminal 2 — frontend
cd frontend && npm run dev  # http://localhost:3000
```
Requires `OPENAI_API_KEY` in root `.env` (already present).

## Out of scope (YAGNI)

- Auth / multi-user sessions, rate limiting, production CORS lockdown.
- Writing registration drafts into Neo4j.
- Deploy/hosting config. Streaming partial supervisor results ("確認中です" async pattern from
  reference.md is noted but not implemented — the demo returns synchronously).
```
