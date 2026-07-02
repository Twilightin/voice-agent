# voice-agent

A runnable demo of the architecture in [`reference.md`](reference.md): **OpenAI Realtime (browser voice)**
talks to a **LangGraph Supervisor** that routes to task agents. Weather + TODO are dummy agents — this is a
template to extend.

```
[user voice]
   ↓
[OpenAI Realtime (browser, WebRTC)]   ← voice I/O only, single tool: ask_backend
   ↓  POST /ask
[LangGraph Supervisor (FastAPI)]      ← router only
   ├─→ weather_agent (get_weather)
   └─→ todo_agent    (add_todo)
```

Design details: [`docs/superpowers/specs/2026-07-02-voice-agent-design.md`](docs/superpowers/specs/2026-07-02-voice-agent-design.md).
Guidance for future work: [`CLAUDE.md`](CLAUDE.md).

## Layout

```
voice-agent/
├── .env                # OPENAI_API_KEY=... (gitignored; you provide this)
├── .env.example
├── backend/            # Python uv project (Supervisor + FastAPI)
│   ├── app.py          #   /ask (supervisor) + /session (ephemeral key) + CORS
│   ├── pyproject.toml
│   └── tests/test_ask.py
└── frontend/           # Vite + TypeScript (Realtime voice client)
    ├── index.html      #   Start button + status
    └── src/main.ts     #   fetch /session → session.connect(ek_…)
```

## Prerequisites

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Node ≥ 20 and npm
- An OpenAI API key with Realtime access, in root `.env`:
  ```
  OPENAI_API_KEY=sk-...
  ```
  (copy `.env.example` → `.env`). The key stays server-side; the browser only ever gets a short-lived
  `ek_...` token minted by `POST /session`.

## Setup

```bash
cd backend && uv sync         # installs backend deps into backend/.venv
cd ../frontend && npm install # installs frontend deps
```

## Run (two terminals)

```bash
# terminal 1 — backend on :8000
cd backend && uv run uvicorn app:app --port 8000 --reload

# terminal 2 — frontend on :5173
cd frontend && npm run dev
```

Open http://localhost:5173, click **会話をはじめる**, allow the microphone, and speak.

## Verify

- **Backend, headless (no audio/LLM):**
  ```bash
  cd backend && uv run pytest
  ```
- **Voice loop, manual:** with both processes running, speak a weather question (routes to `weather_agent`)
  or a "add this to my TODO" request (routes to `todo_agent`); the agent speaks back a short summary.

## Notes

- Two models on purpose: the supervisor/agents use a text LLM (`gpt-4.1`); the browser voice session uses
  `gpt-realtime`. Change the Realtime model in **both** `app.py`'s `/session` payload and `main.ts`.
- Add a capability by adding a `create_react_agent(...)` to the `agents=[...]` list in `app.py` — **not** by
  adding tools to the frontend (routing must stay in one place).
