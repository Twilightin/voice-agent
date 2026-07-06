# Registration flow: how the two tools and `_PENDING` work

This traces a spoken registration all the way to a row in Neo4j, and clears up the two things that
usually confuse people:

1. **Does the LLM check `_PENDING`?**  → **No.** `_PENDING` is a plain Python variable. The LLM never
   sees it. (Details below.)
2. **How does the LLM turn a sentence into `equipment/failure/cause/action`?**  → It emits a *tool call*
   with those four as arguments. That step is shown explicitly below.

Code: `backend/app.py`.

---

## The mental model: two brains + Python glue

There are **three** actors. Keeping them separate removes all the confusion.

| Actor | Where | Its job | Sees `_PENDING`? |
|---|---|---|---|
| **Voice LLM** (`gpt-realtime-mini`) | browser | speech ↔ text; for registration it just **relays** your words via the `ask_backend` tool | no |
| **Text LLM** (`gpt-4o-mini`) | backend (supervisor + `registration_agent`) | reads the conversation, **breaks your sentence into the 4 fields**, decides which tool to call, writes the reply | **no** |
| **Python** | backend (`draft_registration_record`, `register_case`, `/ask`) | completeness check, the Neo4j write, and **owns `_PENDING`** | yes |

> **Direct answer to "is `_PENDING` checked by the LLM?" → No.**
> The Text LLM only ever sees **text**: your messages, its own messages, and each tool's **string** return
> value. `_PENDING` is a Python-only side-channel: the tool *body* writes into it, and the `/ask` function
> reads it to decide what to show on screen. Neither LLM can see it or "check" it.

**Why `_PENDING` has to exist:** a tool can only hand the LLM back a **string**. But the screen needs the
**structured 4 fields** (to show a review) and a "written" signal. So Python smuggles that structured data
from the tool to the HTTP response through `_PENDING`.

---

## What are `session_id` and `thread`?

When you press **「会話をはじめる」**, the browser makes **one random id for this whole conversation**:

```ts
// frontend/lib/realtime.ts
const sessionId = crypto.randomUUID();
// e.g. "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a"
```

It sends that id with **every** `/ask` call. The backend hands it to LangGraph as the **`thread_id`**.
"thread" is just LangGraph's word for *"one ongoing conversation's memory."* Because every turn uses the
**same** `thread_id`, the Text LLM **remembers the earlier turns** — that is why, by the end, it can fill
all 4 fields even though you said them one at a time. Reload / reconnect → new `sessionId` → fresh memory.

Throughout this doc the id is the realistic value `7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a`.

---

## What is a "checkpointer"? (the thing that actually remembers)

A **checkpointer is a save-file for the conversation.** LangGraph uses it to store the running message
history after every turn, filed under the `thread_id`.

**Without** a checkpointer, each `/ask` call is amnesiac — `ainvoke` only sees the one sentence you pass in:
```python
await supervisor.ainvoke({"messages": [{"role": "user", "content": "対策は冷却系点検"}]})
# ↑ only THIS sentence; turns 1–2 are gone. The agent could never gather all 4 fields.
```

**With** a checkpointer, every turn is **load → append → run → save**, keyed by `thread_id`:
```
Turn 3 for thread 7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a:
  1. LOAD    saved history for that thread
             = [「登録したい」, "どの設備…？", 「ポンプCの過熱…冷却不足」, "対策は？"]
  2. APPEND  the new user message   「対策は冷却系点検」
  3. RUN     the agent on the FULL history  → it now sees all 4 fields → can fill the tool args
  4. SAVE    the updated history back under that thread
```

We use the simplest built-in one, **`MemorySaver`**, which keeps everything **in RAM** inside the backend
process:
- it is lost when the backend restarts, and not shared between processes — fine for a single-user demo;
- production would swap in a durable checkpointer (SQLite / Postgres / Redis) — same interface, no other code
  changes.

In code it is just two small pieces (`backend/app.py`):
```python
from langgraph.checkpoint.memory import MemorySaver

supervisor = create_supervisor(...).compile(checkpointer=MemorySaver())   # 1) turn saving ON

await supervisor.ainvoke(
    {"messages": [{"role": "user", "content": q.text}]},
    config={"configurable": {"thread_id": q.session_id}},                 # 2) which save-slot
)
```

So the whole "memory" mechanism is: **`session_id`** (made by the browser) → **`thread_id`** (the save-slot
name) → the **checkpointer** loads/saves that slot's message history on every turn. That is why the agent can
fill all 4 fields at Turn 3 even though you said them one at a time — and why `_PENDING` does **not** need to
remember anything (it only carries "what to show right now").

---

## Zoom in: how the Text LLM breaks a sentence into elements

You say: **「ポンプCの過熱です。原因は冷却不足」**

1. **Voice LLM** relays it — calls its `ask_backend` tool with
   `request = "ポンプCの過熱です。原因は冷却不足"`; the browser then sends that **same string** as the
   `text` of the POST (so `text === request ===` your spoken words, unchanged):
   ```json
   POST /ask
   { "text": "ポンプCの過熱です。原因は冷却不足",
     "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }
   ```
2. **Text LLM** (registration_agent) sees the whole conversation for that thread (it remembers the earlier
   「登録したい」 + this new sentence). It maps the words onto the schema's roles and **outputs a tool call**
   — *this is the breakdown into elements* (it is a function call, not spoken text):
   ```jsonc
   {
     "tool": "draft_registration_record",
     "args": { "equipment": "ポンプC", "failure": "過熱", "cause": "冷却不足", "action": "" }
   }
   ```
   Note: nothing about `_PENDING` here — the LLM only chooses the function and fills the arguments.
3. **Python** runs `draft_registration_record(equipment="ポンプC", failure="過熱", cause="冷却不足",
   action="")`: computes `missing = [対策]`, leaves `_PENDING` untouched (incomplete), returns the **string**
   `"登録には次の項目が必要です: 対策"`.
4. That string is fed **back to the Text LLM** as the tool result; it then writes its reply, e.g.
   `"対策は何ですか？"`.
5. **Python `/ask`** reads `_PENDING` (still empty) → `ui = null`, returns `{answer:"対策は何ですか？",
   ui:null}`.

Every turn is this same 5-beat rhythm: **Voice relay → Text LLM emits tool-call(args) → Python tool runs
(maybe writes `_PENDING`) → Text LLM writes reply → Python `/ask` reads `_PENDING` → response**.

---

## Full scenario (realistic `session_id`, per-turn detail)

For the whole conversation: `session_id = thread_id = 7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a`.

> **Exact vs. generated.** The tool **arguments**, tool **return strings**, `_PENDING`, `params`, `cypher`,
> and `ui` shown below are the exact Python values. The one non-deterministic line is `answer` — that is the
> Text LLM's own wording (shown as a concrete example; the model may phrase it a little differently).

### Turn 1 — you: 「新しい故障ケースを登録したい」
```
Voice LLM → ask_backend(request="新しい故障ケースを登録したい")   # request = あなたの言葉
POST /ask { "text": "新しい故障ケースを登録したい",
            "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }

Python /ask: _PENDING.clear()   →  _PENDING = {}
Text LLM emits tool call:
    draft_registration_record(equipment="", failure="", cause="", action="")
Python tool runs:
    values   = {"equipment": "", "failure": "", "cause": "", "action": ""}
    missing  = ["設備", "故障", "原因", "対策"]
    _PENDING = {}                                   # incomplete → not touched
    return   = "登録には次の項目が必要です: 設備, 故障, 原因, 対策"
Text LLM → answer = "どの設備の、どんな故障ですか？"      # ← LLM wording (example)
Python /ask: _build_ui() sees _PENDING == {} → ui = null
RESPONSE = { "answer": "どの設備の、どんな故障ですか？", "ui": null }
```

### Turn 2 — you: 「ポンプCの過熱です。原因は冷却不足」
```
Voice LLM → ask_backend(request="ポンプCの過熱です。原因は冷却不足")
POST /ask { "text": "ポンプCの過熱です。原因は冷却不足",
            "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }

Python /ask: _PENDING.clear()   →  _PENDING = {}
Text LLM (remembers Turn 1) emits:
    draft_registration_record(equipment="ポンプC", failure="過熱", cause="冷却不足", action="")
Python tool runs:
    values   = {"equipment": "ポンプC", "failure": "過熱", "cause": "冷却不足", "action": ""}
    missing  = ["対策"]
    _PENDING = {}                                   # still incomplete
    return   = "登録には次の項目が必要です: 対策"
Text LLM → answer = "対策は何ですか？"
Python /ask: ui = null
RESPONSE = { "answer": "対策は何ですか？", "ui": null }
```

### Turn 3 — you: 「対策は冷却系点検」  ← all 4 known
```
Voice LLM → ask_backend(request="対策は冷却系点検")
POST /ask { "text": "対策は冷却系点検",
            "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }

Python /ask: _PENDING.clear()   →  _PENDING = {}
Text LLM (memory fills the first 3, new word fills the 4th) emits:
    draft_registration_record(equipment="ポンプC", failure="過熱",
                              cause="冷却不足", action="冷却系点検")
Python tool runs:
    values   = {"equipment": "ポンプC", "failure": "過熱", "cause": "冷却不足", "action": "冷却系点検"}
    missing  = []                                   # complete!
    _PENDING = {"review": {"equipment": "ポンプC", "failure": "過熱",
                           "cause": "冷却不足", "action": "冷却系点検"}}
    return   = "4項目がそろいました。ユーザーに『下記の情報で登録してよろしいでしょうか』と確認してください。まだ登録していません。"
Text LLM → answer = "下記の情報で登録してよろしいでしょうか"   # does NOT call register_case yet
Python /ask: _build_ui() sees _PENDING["review"] →
    ui = { "kind": "review", "title": "登録内容の確認",
           "fields": [ {"label": "設備", "value": "ポンプC"},
                       {"label": "故障", "value": "過熱"},
                       {"label": "原因", "value": "冷却不足"},
                       {"label": "対策", "value": "冷却系点検"} ] }
RESPONSE = { "answer": "下記の情報で登録してよろしいでしょうか", "ui": { …the review above… } }
SCREEN: a plain-text 「登録内容の確認 …」 block appears as an agent turn
```

### Turn 4 — you correct: 「原因は潤滑不足に直して」
```
Voice LLM → ask_backend(request="原因は潤滑不足に直して")
POST /ask { "text": "原因は潤滑不足に直して",
            "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }

Python /ask: _PENDING.clear()   →  _PENDING = {}
Text LLM (remembers the 4, changes only cause) emits:
    draft_registration_record(equipment="ポンプC", failure="過熱",
                              cause="潤滑不足", action="冷却系点検")
Python tool runs:
    values   = {"equipment": "ポンプC", "failure": "過熱", "cause": "潤滑不足", "action": "冷却系点検"}
    missing  = []
    _PENDING = {"review": {"equipment": "ポンプC", "failure": "過熱",
                           "cause": "潤滑不足", "action": "冷却系点検"}}    # cause updated
    return   = "4項目がそろいました。ユーザーに『下記の情報で登録してよろしいでしょうか』と確認してください。まだ登録していません。"
Text LLM → answer = "下記の情報で登録してよろしいでしょうか"
Python /ask: ui = { "kind": "review", "title": "登録内容の確認",
                    "fields": [ {"label": "設備", "value": "ポンプC"},
                                {"label": "故障", "value": "過熱"},
                                {"label": "原因", "value": "潤滑不足"},
                                {"label": "対策", "value": "冷却系点検"} ] }
RESPONSE = { "answer": "下記の情報で登録してよろしいでしょうか", "ui": { …updated review… } }
```

### Turn 5 — you: 「はい」  ← only now does Python write to Neo4j
```
Voice LLM → ask_backend(request="はい")
POST /ask { "text": "はい",
            "session_id": "7f3d9c21-4b8e-4f2a-9c11-2a6b5e0d8f4a" }

Python /ask: _PENDING.clear()   →  _PENDING = {}
Text LLM (sees "はい" + remembers the 4) emits a DIFFERENT tool:
    register_case(equipment="ポンプC", failure="過熱", cause="潤滑不足", action="冷却系点検")
Python tool runs:
    params = {"equipment": "ポンプC", "failure": "過熱", "cause": "潤滑不足", "action": "冷却系点検"}
    cypher = "MERGE (e:Equipment {name: $equipment}) "
             "MERGE (f:Failure {name: $failure, equipment: $equipment}) "
             "  ON CREATE SET f.id = randomUUID() "
             "MERGE (c:Cause {name: $cause}) "
             "MERGE (a:Action {name: $action}) "
             "MERGE (e)-[:HAS_FAILURE]->(f) "
             "MERGE (f)-[:CAUSED_BY]->(c) "
             "MERGE (c)-[:RESOLVED_BY]->(a)"
    session.run(cypher, equipment="ポンプC", failure="過熱",
                cause="潤滑不足", action="冷却系点検")     # → writes 2 new nodes (ポンプC, 過熱)
    _PENDING = {"registered": True}
    return   = "ナレッジに登録しました。"
Text LLM → answer = "ナレッジに登録しました。"
Python /ask: _build_ui() sees _PENDING["registered"] → ui = { "kind": "registered" }
RESPONSE = { "answer": "ナレッジに登録しました。", "ui": { "kind": "registered" } }
SCREEN: agent says 「ナレッジに登録しました。」
```

---

## The one thing to remember

Two different kinds of "memory", owned by two different actors:

- **The 4 fields across turns** → the **Text LLM's** memory, provided by LangGraph's **checkpointer**, keyed
  by `thread_id = session_id`. This is what lets it fill all 4 args at turn 3/5 from things you said earlier.
- **"What to show on screen right now"** → the **Python** `_PENDING` slot, wiped and refilled every request.
  The LLM cannot see it.

`/ask` ties them together — it sets the thread for memory, and treats `_PENDING` as a one-request mailbox:

```python
_PENDING.clear()                                   # empty the Python mailbox
result = await supervisor.ainvoke(                  # Text LLM runs; a tool may fill _PENDING
    {"messages": [{"role": "user", "content": q.text}]},
    config={"configurable": {"thread_id": q.session_id}},   # ← memory key
)
return {"answer": result["messages"][-1].content,   # the LLM's spoken reply (a string)
        "ui": _build_ui()}                          # Python reads _PENDING → review / registered / null
```

The Neo4j write happens **only** inside `register_case`, and the Text LLM only calls it **after a spoken
「はい」**.

*(Single-user demo: `_PENDING` is one shared slot, so simultaneous conversations would collide — fine for
one at a time; making it per-session is a later step.)*
