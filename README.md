# voice-agent

A runnable demo of the architecture in [`reference.md`](reference.md): **OpenAI Realtime (browser voice)**
talks to a **LangGraph Supervisor** that routes to graph-backed task agents. The backend now uses a local
Neo4j factory-failure graph described in [`LANGCHAIN_AGENT_CONTEXT.md`](LANGCHAIN_AGENT_CONTEXT.md).

```
[user voice]
   ↓
[OpenAI Realtime (browser, WebRTC)]   ← voice I/O only, single tool: ask_backend
   ↓  POST /ask
[LangGraph Supervisor (FastAPI)]      ← router only
   ├─→ qa_agent      (query_graphdb, read-only Neo4j Q&A)
   └─→ registration_agent (draft → /v1 review table → voice「はい」→ register_case, writes to Neo4j)
```

Design details: [`docs/superpowers/specs/2026-07-02-voice-agent-design.md`](docs/superpowers/specs/2026-07-02-voice-agent-design.md).
Guidance for future work: [`CLAUDE.md`](CLAUDE.md).

## Layout

```
voice-agent/
├── .env                # OPENAI_API_KEY=... (gitignored; you provide this)
├── .env.example
├── app_config.json     # model, frontend, and local Neo4j settings
├── backend/            # Python uv project (Supervisor + FastAPI)
│   ├── app.py          #   /ask (supervisor) + /session (ephemeral key) + CORS
│   ├── pyproject.toml
│   └── tests/test_ask.py
└── frontend/           # Next.js App Router (Realtime voice client)
    ├── app/v1/page.tsx #   new UI (Vercel useChat) — shows user + assistant transcripts
    ├── app/v0/page.tsx #   old UI, preserved
    └── lib/realtime.ts #   shared WebRTC: /session → /realtime/calls, ask_backend → /ask
```

## Prerequisites

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Node ≥ 20 and npm
- Neo4j running locally with the factory-failure data loaded
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

# terminal 2 — frontend on :3000
cd frontend && npm run dev
```

Open **http://localhost:3000** (redirects to **`/v1`**), click **会話をはじめる**, allow the microphone,
and speak. Your words and the agent's replies both appear as chat bubbles. The old UI stays at **`/v0`**.

## Verify

- **Backend, headless (no audio/LLM):**
  ```bash
  cd backend && uv run pytest
  ```
- **Voice loop, manual:** with both processes running, ask a factory-failure question such as
  "ポンプAが過熱したときの対策は？" (routes to `qa_agent`) or register a new failure case
  (routes to `registration_agent`: it collects equipment/failure/cause/action by voice across turns, shows a
  **read-only review table** in `/v1`, and on a spoken **「はい」** writes to Neo4j; spoken corrections update
  the table). See [`SCENARIO_TESTS.md`](SCENARIO_TESTS.md) for step-by-step manual tests.

## Notes

- Frontend is **Next.js** on `:3000` with two routes: **`/v1`** (new Vercel `useChat` UI) and **`/v0`**
  (the old UI, preserved). Both share `lib/realtime.ts` and hit the same backend.
- Three models, all in root `app_config.json`: text LLM `gpt-4o-mini` (supervisor/agents), Realtime
  `gpt-realtime-mini` (voice), and `gpt-4o-mini-transcribe` (**user-voice transcription**, so `/v1` can
  show what you said).
- Add a capability by adding a `create_agent(...)` to the `agents=[...]` list in `app.py` — **not** by
  adding tools to the frontend (routing must stay in one place).
