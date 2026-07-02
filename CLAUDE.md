# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A voice agent demo wiring **OpenAI Realtime (browser voice)** to a **LangGraph Supervisor (Python backend)**.
The design doc is `docs/superpowers/specs/2026-07-02-voice-agent-design.md`; the original architecture note
is `reference.md` (Japanese). Weather + TODO are intentionally dummy task agents — this is a template to extend.

## The one architectural rule

**Intent routing lives in exactly one place: the Supervisor.** Everything else is deliberately dumb.

```
browser voice ──▶ Realtime agent ──(single tool: ask_backend)──▶ POST /ask
                                                                     │
                                                          LangGraph Supervisor (router only)
                                                            ├─▶ weather_agent (get_weather)
                                                            └─▶ todo_agent    (add_todo)
```

- **Realtime side (`frontend/src/main.ts`)** does voice↔text only. It has **one** tool, `ask_backend`,
  which forwards the raw user request to the backend. Do **not** add more tools or business logic here —
  that would duplicate routing. Greetings/reask are the only things it answers itself.
- **Supervisor (`backend/app.py`)** reads intent and dispatches to one task agent, then returns a
  1–2 sentence summary. It does no real work itself.
- **Task agents** own their tools and do the actual work. Add capabilities by adding a new
  `create_react_agent(...)` to the `agents=[...]` list in `create_supervisor` — not by touching the frontend.
- `/ask` returns only `result["messages"][-1].content` — the last message's text — nothing else crosses
  back to the voice layer.

## Two models, on purpose

- Supervisor + task agents use a **text** LLM (`ChatOpenAI(model="gpt-4.1")`).
- The browser voice session uses the **Realtime** model (`gpt-realtime`).
Don't collapse these into one.

## Secrets & the ephemeral-key flow

The browser must **never** see `OPENAI_API_KEY`. Instead:
`POST /session` (backend) calls `https://api.openai.com/v1/realtime/client_secrets` with the real key and
returns a short-lived `ek_...` token (`value` field). The frontend fetches that, then
`session.connect({ apiKey: value })`. If you change the Realtime model, change it in **both** the `/session`
session payload and the frontend `RealtimeSession` model.

`OPENAI_API_KEY` lives in root `.env` (gitignored, loaded via `load_dotenv()`). Never move it into `frontend/`.

## Commands

`backend/` **is** the Python uv project (its own `pyproject.toml` + `.venv`); run uv commands from inside it.
`frontend/` is a separate npm/Vite project. `.env` stays at the **repo root** (one level above `backend/`);
`app.py` loads it by explicit path, so CWD doesn't matter.

```bash
# setup
cd backend && uv sync                             # backend deps → backend/.venv
cd frontend && npm install                        # frontend deps

# run (two processes)
cd backend && uv run uvicorn app:app --port 8000 --reload   # backend
cd frontend && npm run dev                                  # frontend → http://localhost:5173

# backend tests (headless — no audio/LLM needed), from backend/
uv run pytest                                                       # all
uv run pytest tests/test_ask.py::test_session_returns_ephemeral_value -q   # single test

# frontend typecheck + build
cd frontend && npm run build                       # runs `tsc --noEmit && vite build`
```

CORS in `backend/app.py` allows the Vite origin `http://localhost:5173`; if you change the frontend port,
update the allowlist or `/ask` and `/session` calls will be blocked.

## Verifying the voice loop

Automated tests cover `/ask` routing headlessly. The end-to-end voice path is verified **manually** in the
browser (click Start, speak). Example utterances: a weather question routes to `weather_agent`; a
"add to my TODO" request routes to `todo_agent`.
