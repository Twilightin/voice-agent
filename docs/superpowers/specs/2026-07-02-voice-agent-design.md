# Voice Agent — Realtime × LangGraph Supervisor (Design)

**Date:** 2026-07-02
**Status:** Approved design, pending spec review
**Goal:** Turn the `reference.md` architecture and the `backend.py` / `voice.ts` snippets into a
**runnable end-to-end demo**: speak into the browser → LangGraph Supervisor routes to a task agent →
spoken answer back. Weather + TODO stay as dummy agents; this is a template to extend later.

## Architecture

```
[user voice]
   ↓
[OpenAI Realtime (browser, WebRTC)]   ← voice I/O + intent only, one tool: ask_backend
   ↓  POST /ask
[LangGraph Supervisor (FastAPI)]      ← router only, no real work
   ├─→ weather_agent (+ get_weather)
   └─→ todo_agent    (+ add_todo)
```

Role split (unchanged from `reference.md`):
- **Realtime**: speech↔text + read-back. No business logic. Only tool = `ask_backend`.
- **Supervisor**: reads intent, dispatches to one task agent, returns a 1–2 sentence summary.
- **Task agents**: run the actual tool and report the result.

## Project layout (root-rooted Python + separate frontend)

```
voice-agent/
├── pyproject.toml            # at root; add deps (was empty)
├── .python-version           # 3.12
├── .env                      # OPENAI_API_KEY=...  (gitignored)
├── .env.example              # committed template
├── .venv/                    # recreated at root via `uv sync`
├── backend/
│   ├── __init__.py           # makes `backend` importable
│   └── app.py                # supervisor + FastAPI (from backend.py) + CORS + /session
├── frontend/
│   ├── package.json          # @openai/agents, zod, vite, typescript
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html            # Start button + status line
│   └── src/main.ts           # from voice.ts; fetch /session → connect
├── reference.md
├── README.md                 # how to run both processes
└── docs/superpowers/specs/2026-07-02-voice-agent-design.md
```

### Cleanup of uv-init artifacts
- **Delete** root `main.py` (hello-world stub — unused).
- **Delete** the stray empty `backend/.venv` (no deps installed); `uv sync` recreates `.venv` at root.
- `pyproject.toml` and `.env` stay at root (where the user placed them).

## Backend (`backend/app.py`)

Keeps the reference verbatim: `llm`, `get_weather`/`weather_agent`, `add_todo`/`todo_agent`,
`create_supervisor(...).compile()`, and `POST /ask` returning `result["messages"][-1].content`.

Adds:
1. **dotenv** — `load_dotenv()` at import so `OPENAI_API_KEY` is available.
2. **CORS** — `CORSMiddleware` allowing `http://localhost:5173` (Vite dev origin) so the browser can call `/ask` and `/session`.
3. **`POST /session`** — mints an ephemeral Realtime client secret:
   - Server-side `httpx` POST to `https://api.openai.com/v1/realtime/client_secrets`
     with `Authorization: Bearer <OPENAI_API_KEY>` and body
     `{"expires_after": {"anchor": "created_at", "seconds": 600},
       "session": {"type": "realtime", "model": "gpt-realtime"}}`.
   - Returns `{"value": "<ek_...>"}` (the top-level `value` from OpenAI's response) to the browser.
   - The real API key never leaves the server.

**Model note:** `backend.py` uses `ChatOpenAI(model="gpt-4.1")` for the supervisor/agents (text LLM);
the Realtime browser side uses `gpt-realtime`. Both are kept as-is from the references.

**Dependencies:** `langgraph`, `langgraph-supervisor`, `langchain-openai`, `fastapi`,
`uvicorn[standard]`, `httpx`, `python-dotenv`, `pydantic`. Dev: `pytest`, `pytest-asyncio`.

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
4. `ask_backend` → `POST /ask {text}` → supervisor routes to weather/todo agent → summary text.
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
- **Voice loop:** verified manually in-browser (speak "東京の天気は？" → weather agent;
  "牛乳を買うのをTODOに入れて" → todo agent). Documented in README as a manual check.

## Run instructions (README)

```bash
# one-time
uv sync                     # installs backend deps into root .venv
cd frontend && npm install  # installs frontend deps

# terminal 1 — backend
uv run uvicorn backend.app:app --port 8000 --reload

# terminal 2 — frontend
cd frontend && npm run dev  # http://localhost:5173
```
Requires `OPENAI_API_KEY` in root `.env` (already present).

## Out of scope (YAGNI)

- Auth / multi-user sessions, rate limiting, production CORS lockdown.
- Persisting TODOs (dummy in-memory string only).
- Deploy/hosting config. Streaming partial supervisor results ("確認中です" async pattern from
  reference.md is noted but not implemented — the demo returns synchronously).
```