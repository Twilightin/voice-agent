# Registration: backend-owned draft state + voice confirm/amend loop

**Date:** 2026-07-03
**Status:** Design for review (not yet implemented). Supersedes the voice-model-state draft.

## Context

Registration should end in a **read-only review table** + a voice confirm/amend loop: when all required
fields are gathered, `/v1` shows the record and the AI asks 「下記の情報で登録してよろしいでしょうか」.
"はい" → write → 「ナレッジに登録しました。」. A spoken correction updates a field, re-shows the table,
and re-asks.

**Why not let the voice model hold the fields:** the current Neo4j data is a simple 4-field record, but
future data will be complex (many fields, nested structures, multiple record types, validation, referential
integrity). A model holding N fields across turns drifts; validation/defaults/integrity belong server-side;
targeted corrections and auditability need a structured store. **So the backend owns the draft state.** The
voice layer goes back to dumb I/O (relay each utterance; the backend remembers).

## Target general architecture (future-proof)

```
Browser voice ──(session_id + text)──▶ POST /ask  [stateful, thread = session_id]
                                            │
                                  Supervisor (routing + memory via checkpointer)
                                       ├─▶ QA agent (read)
                                       └─▶ Collection agent ── schema-driven ──▶ Schema Registry
                                                │ update / validate / commit
                                        Draft Store (per-session structured record)
                                                │ commit
                                        GraphWriter (validated record → Cypher/MERGE, integrity)
                                            │
                       /ask returns { answer, ui }   # ui = review | registered | none
                                            │
                       Frontend renders the review table GENERICALLY from `ui`
```

Seven independently-testable pieces: **session/thread**, **schema registry**, **draft store**,
**collection agent**, **GraphWriter (persistence)**, **structured `ui` channel**, **supervisor (stateful)**.

## What we build NOW (incremental first slice)

Uses the general seams, but only for the current `FailureCase` (no multi-schema machinery yet).

### 1. Session + stateful backend (this is what "backend remembers" means)
- Frontend generates a stable `session_id` (once per connection) and sends it in every `/ask` body:
  `{ text, session_id }`.
- Compile the supervisor with a checkpointer: `create_supervisor(...).compile(checkpointer=MemorySaver())`
  (verify the API accepts it). `/ask` calls `supervisor.ainvoke(input, config={"configurable":
  {"thread_id": session_id}})`. → the collection agent now **remembers prior turns**, so it accumulates
  fields and applies corrections without the voice model re-sending them.

### 2. Tiny schema (seam for the future registry)
```python
FAILURE_CASE_SCHEMA = {
    "record": "FailureCase",
    "fields": [
        {"key": "equipment", "label": "設備", "required": True},
        {"key": "failure",   "label": "故障", "required": True},
        {"key": "cause",     "label": "原因", "required": True},
        {"key": "action",    "label": "対策", "required": True},
    ],
}
```
Drives required-field checks and the UI labels. Adding record types later = more schema entries.

### 3. Collection agent (generalizes `registration_agent`)
- Extracts the schema's fields from the remembered conversation.
- Calls `draft_registration_record(**fields)` with everything known so far → stashes the structured draft
  and computes `missing` from the schema. If missing → asks; if complete → review-ready.
- On the user's affirmation → `register_case(**fields)` → commit. Never fabricates completion.

### 4. Structured `ui` channel
- `draft_registration_record` stashes `{fields, missing}`; `register_case` sets a `registered` marker and
  returns 「ナレッジに登録しました。」.
- `/ask` returns `{ answer, ui }` where:
  - `ui = { kind: "review", title: "登録内容の確認", fields: [{label, value}, …], missing: [...] }` when a
    complete draft exists,
  - `ui = { kind: "registered" }` right after a write,
  - `ui = null` otherwise.
- Built from the stash (single-slot, single-user for now; session-keyed store is a later step).

### 5. Frontend renders `ui` generically
- `app/v1/page.tsx`: replace the editable form with a **read-only table** driven by `ui.fields`
  (label/value rows) + caption 「下記の情報で登録してよろしいでしょうか（音声で「はい」）」. Show on
  `ui.kind==="review"`, clear on `"registered"`. **No inputs, no buttons** (voice-only).
- `lib/realtime.ts`: send `session_id`; `askBackend` returns `{answer, ui}`; callbacks `onReview(ui)` and
  `onRegistered()`. Remove `registerCase()` and the `/register` call.

### 6. Persistence unchanged
- `register_case` remains the GraphWriter (record → schema-safe `MERGE`); only its success message changes to
  「ナレッジに登録しました。」.

### 7. Frontdesk (voice) prompt → dumb relay
- For registration, relay each user utterance to `ask_backend` (with `session_id`); do **not** try to hold or
  re-send the fields, and do **not** claim registration — only speak what the backend returns
  (「下記の情報で登録してよろしいでしょうか」, corrections, 「ナレッジに登録しました。」).

## Data flow (registration)
1. Speak → voice → `/ask(session_id, utterance)` → supervisor(thread) → collection agent.
2. Agent updates known fields (thread memory), validates vs schema. Missing → ask. Complete → `ui: review`.
3. Frontend shows the read-only table; AI asks the confirm question.
4. Correction → agent updates that field → `ui: review` refreshed → re-ask.
5. "はい" → agent `register_case` → GraphWriter writes → `ui: registered` → 「ナレッジに登録しました。」 →
   table clears.

## Error handling
- Write failure → surfaced in `answer`; table stays for retry.
- Checkpointer memory is in-process (dev). Restart loses in-flight drafts — acceptable for the demo.

## Testing
- `register_case` returns 「ナレッジに登録しました。」 and sets the `registered` marker; write Cypher unchanged.
- `draft_registration_record` stashes `{fields, missing}` (missing computed from schema); no write.
- `/ask` returns `ui.kind` review vs registered vs null (unit-level via direct stash + monkeypatched
  supervisor); `/ask` accepts and forwards `session_id` as `thread_id`.
- Remove the `POST /register` test.
- Manual voice re-test (TC-2) after implementation.

## Out of scope (later, when data gets complex)
- Multi-record-type **Schema Registry**, richer validation / referential integrity.
- **Session-keyed** draft store + **durable** checkpointer (Redis/Postgres) + multi-user concurrency.
- Nested/grouped review UI; editing in the UI; a `登録` button fallback.
