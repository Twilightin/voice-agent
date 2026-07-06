# コード解説: `backend/app.py`(頭脳担当の中身)

`app.py` を**ブロックごと**に「これは何をするコードか・なぜ必要か」を説明します。
全体の役割は [`MENTAL_MODEL.md`](MENTAL_MODEL.md)、登録の1歩ずつの流れは
[`REGISTRATION_FLOW.md`](REGISTRATION_FLOW.md) を参照。

## まず「2つの時間帯」を分けて考える

`app.py` のコードは、走るタイミングが2種類あります。ここを分けると一気に分かりやすくなります。

- **起動時に1回だけ走る「組み立て」**(ファイルの上半分) … ライブラリ読み込み・設定・ツール・
  エージェント・司令塔(Supervisor)を**一度だけ**用意する。`uv run uvicorn app:app` の瞬間に実行。
- **リクエストのたびに走る「窓口」**(ファイルの下半分) … `/ask` と `/session`。ユーザーの操作の
  たびに何度でも呼ばれる。

以下、上から順に見ます(ブロック1〜9=組み立て、ブロック10〜13=窓口)。

---

## ブロック1: 道具(ライブラリ)の読み込み

```python
import json, os
from pathlib import Path
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph_supervisor import create_supervisor
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None
```
- **目的:** 使う道具を全部そろえる。`fastapi`=Webサーバー、`create_agent`/`create_supervisor`=AI、
  `httpx`=OpenAIへの通信、`MemorySaver`=会話記憶、`neo4j`=グラフDB。
- **`try/except` の意味:** Neo4j ドライバが未インストールでも**落ちないように**する保険。
  無ければ `GraphDatabase = None` にしておき、使う直前に「入ってません」と案内できる。

---

## ブロック2: 設定(秘密キー・モデル名・接続先)

```python
load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # OPENAI_API_KEY を読む
CONFIG_PATH = Path(__file__).resolve().parent.parent / "app_config.json"
APP_CONFIG = load_app_config()

CHAT_MODEL      = os.environ.get("OPENAI_CHAT_MODEL",      APP_CONFIG["openai"]["chat_model"])
REALTIME_MODEL  = os.environ.get("OPENAI_REALTIME_MODEL",  APP_CONFIG["openai"]["realtime_model"])
TRANSCRIBE_MODEL= os.environ.get("OPENAI_TRANSCRIBE_MODEL", APP_CONFIG["openai"]["transcribe_model"])
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN",       APP_CONFIG["frontend"]["origin"])
NEO4J_URI = os.environ.get("NEO4J_URI", APP_CONFIG["neo4j"]["uri"])   # user/password/database も同様
```
- **目的:** 秘密のキーは `.env` から、モデル名や接続先は `app_config.json` から読み込み、定数にする。
- **`os.environ.get("X", 既定値)` の形:** 「環境変数 X があればそれ、無ければ既定値」。
  本番では環境変数で上書きし、開発では `app_config.json` の値を使う、という切り替えができる。
- **なぜ:** 設定を**コードの外**に出しておくと、モデルや接続先を変えるのにコードを触らずに済む。

---

## ブロック3: Realtime(音声)側の設定

```python
FRONTDESK_INSTRUCTIONS = ("あなたは音声窓口です。… 登録に関する発言は ask_backend に渡すだけ …")
ASK_BACKEND_TOOL = {
    "type": "function", "name": "ask_backend",
    "description": "挨拶・聞き返し以外のあらゆるタスク依頼をバックエンドに委譲する。…",
    "parameters": {"type": "object",
                   "properties": {"request": {"type": "string"}},
                   "required": ["request"]},
}
```
- **目的:** ブラウザの音声AI(Realtime)に与える「人格(指示文)」と「唯一のツールの設計図」を用意する。
- **どこで使う?** ブロック13の `/session` が鍵を発行するとき、この2つを OpenAI に渡す。
  → 接続直後から音声AIは「窓口の振る舞い」と「ask_backend の呼び方」を知っている。
- **ポイント:** ツールは `ask_backend` の**1つだけ**。判断は全部バックエンドに寄せる設計。

---

## ブロック4: 頭脳のモデル

```python
llm = ChatOpenAI(model=CHAT_MODEL)   # 既定 gpt-4o-mini
```
- **目的:** Supervisor もエージェントも、この**テキスト用モデル**で考える。
- **注意:** 音声用(`REALTIME_MODEL`)とは別物。ここは「文字で考える脳」。

---

## ブロック5: スキーマ と 受け渡しメモ `_PENDING`

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
_PENDING: dict = {}
```
- **`FAILURE_CASE_SCHEMA`:** 登録レコードの「必須項目と表示ラベル」の定義。
  「何が足りないか」の判定と、画面の表ラベルに使う。将来項目を増やす“土台”。
- **`_PENDING`:** ツールと `/ask` の間だけで使う「1リクエストの受け渡しメモ」。
  ツールが構造化データを入れ、`/ask` が拾って画面情報(`ui`)にする。**LLMからは見えない**。
  詳しくは [`REGISTRATION_FLOW.md`](REGISTRATION_FLOW.md)。

---

## ブロック6: qa_agent のツール(Neo4jを“読む”)

```python
WRITE_CYPHER_KEYWORDS = ("CREATE","MERGE","SET","DELETE","DETACH","DROP","REMOVE")

def _is_read_only_cypher(cypher: str) -> bool:      # MATCH/CALL で始まり、書き込み語を含まないか
    normalized = cypher.upper()
    if not normalized.lstrip().startswith(("MATCH","CALL")): return False
    return not any(k in normalized for k in WRITE_CYPHER_KEYWORDS)

def query_graphdb(cypher: str) -> str:              # 読み取り専用でNeo4jを検索するツール
    if not _is_read_only_cypher(cypher): return "安全のためread-onlyの…だけ実行できます。…"
    if GraphDatabase is None: return "Neo4j Python driver is not installed. …"
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session(database=NEO4J_DATABASE) as session:
            rows = [record.data() for record in session.run(cypher)]
    except Exception as e: return f"Neo4j query failed: {e}"
    finally: driver.close()
    return "該当するグラフパスは見つかりませんでした。" if not rows else json.dumps(rows, ensure_ascii=False)
```
- **目的:** 質問に答えるため、Neo4j を**読み取り専用で**検索する。
- **安全弁 `_is_read_only_cypher`:** `MATCH`/`CALL` で始まり `CREATE`/`DELETE` 等を含まないクエリだけ許可。
  → qa_agent が誤ってデータを壊さないようにする(読むだけ)。
- **形:** ドライバを開く→つながるか確認→クエリ実行→結果をJSON文字列で返す→`finally` で必ず閉じる。

---

## ブロック7: registration のツール(候補づくり と 書き込み)

```python
def draft_registration_record(equipment="", failure="", cause="", action=""):   # 確認用(書き込まない)
    values  = {…strip した4項目…}
    missing = [f["label"] for f in FAILURE_CASE_SCHEMA["fields"] if f["required"] and not values[f["key"]]]
    if missing: return "登録には次の項目が必要です: " + ", ".join(missing)
    _PENDING["review"] = values                     # ★ そろったら受け渡しメモに入れる
    return "4項目がそろいました。…『下記の情報で登録してよろしいでしょうか』と確認してください。…"

def register_case(equipment="", failure="", cause="", action=""):               # 実際にNeo4jへ書く
    …4項目チェック…
    params = {…}
    cypher = "MERGE (e:Equipment {name:$equipment}) … MERGE (c)-[:RESOLVED_BY]->(a)"
    …driver で session.run(cypher, **params)…       # ← 書き込み
    _PENDING["registered"] = True                   # ★ 書けたら合図
    return "ナレッジに登録しました。"
```
- **`draft_registration_record`:** 4項目そろったか確認するだけ。**書き込まない**。
  そろえば `_PENDING["review"]` に入れて画面の確認表を出す材料にする。
- **`register_case`:** ユーザーが承諾したときだけ呼ばれ、`MERGE` で Neo4j に書き込む。
  書けたら `_PENDING["registered"]=True`。スキーマ規則(共有ノードは name で MERGE)に従う。

---

## ブロック8: エージェントを作る

```python
qa_agent = create_agent(llm, tools=[query_graphdb], name="qa_agent",
                        system_prompt="…read-onlyのCypherだけ…")
registration_agent = create_agent(llm, tools=[draft_registration_record, register_case],
                                   name="registration_agent",
                                   system_prompt="…4項目を集め、確認後に register_case…")
```
- **目的:** 「AI + 使えるツール + 指示文」を1体にまとめる。qa_agent は読む担当、
  registration_agent は登録担当。
- **`system_prompt`:** そのエージェントの仕事内容とルール(いつどのツールを呼ぶか)を書く。

---

## ブロック9: 司令塔(Supervisor)を作る + 会話記憶ON

```python
supervisor = create_supervisor(
    agents=[qa_agent, registration_agent], model=llm,
    prompt="…質問なら qa_agent、登録なら registration_agent に振り分ける…",
).compile(checkpointer=MemorySaver())
```
- **目的:** 依頼を見て担当エージェントに**振り分けるだけ**の司令塔を作る。自分では作業しない。
- **`.compile(checkpointer=MemorySaver())`:** 会話の記憶をONにする。`session_id` ごとに
  やり取りを保存し、次のターンで思い出す(=複数ターンにわたって4項目を覚えられる)。
  詳しくは [`REGISTRATION_FLOW.md`](REGISTRATION_FLOW.md) の「checkpointer」節。

> ここまで(ブロック1〜9)が**起動時に1回だけ**走る組み立て。以降が**毎回**走る窓口。

---

## ブロック10: Web サーバー本体 と CORS

```python
app = FastAPI()
app.add_middleware(CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],   # http://localhost:3000
    allow_methods=["POST"], allow_headers=["Content-Type"])
```
- **`app = FastAPI()`:** サーバーそのもの。`uvicorn app:app` の `app` はこれ。
- **CORS:** ブラウザは既定で「別の住所のサーバー」への通信を止める。フロント(3000番)から
  このサーバー(8000番)を呼べるよう**明示的に許可**する。無いと `/ask`・`/session` がCORSエラーになる。

---

## ブロック11: `/ask` の受け取り型 と `_build_ui()`

```python
class Query(BaseModel):
    text: str
    session_id: str | None = None      # 会話ごとの記憶キー

def _build_ui() -> dict | None:        # _PENDING の中身を「画面情報」に変換
    if _PENDING.get("registered"): return {"kind": "registered"}
    review = _PENDING.get("review")
    if review:
        return {"kind": "review", "title": "登録内容の確認",
                "fields": [{"label": f["label"], "value": review.get(f["key"], "")}
                           for f in FAILURE_CASE_SCHEMA["fields"]]}
    return None
```
- **`Query`:** ブラウザから届くJSONの形(`text` と `session_id`)。FastAPI が自動でチェックしてくれる。
- **`_build_ui()`:** `_PENDING` を見て、画面に返す `ui` を組み立てる。`registered`→完了、
  `review`→確認表(スキーマのラベル順に行を作る)、どちらも無ければ `None`。

---

## ブロック12: 窓口①  `POST /ask`

```python
@app.post("/ask")
async def ask(q: Query):
    _PENDING.clear()                                          # 受け渡しメモを空にする
    config = {"configurable": {"thread_id": q.session_id or "default"}}   # 記憶キー
    try:
        result = await supervisor.ainvoke(
            {"messages": [{"role": "user", "content": q.text}]}, config=config)
        answer = result["messages"][-1].content
    except Exception as e:
        return {"answer": f"…エラー…: {e}", "ui": None}       # 失敗しても声で言えるよう文で返す
    return {"answer": answer, "ui": _build_ui()}
```
- **目的:** ブラウザの `ask_backend` から呼ばれる本窓口。依頼を Supervisor に渡し、
  `answer`(声で話す文)と `ui`(画面情報)を返す。
- **流れ:** `_PENDING.clear()` → `thread_id` を付けて `supervisor.ainvoke`(途中でツールが `_PENDING` を
  埋めるかも)→ 最後のメッセージを `answer` に → `_build_ui()` で `ui` を作って返す。
- **`session_id`→`thread_id`:** これで会話が記憶される(ブロック9の checkpointer と対)。

---

## ブロック13: 窓口②  `POST /session`

```python
@app.post("/session")
async def session():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key: raise HTTPException(500, "OPENAI_API_KEY is not set")
    payload = {"expires_after": {"anchor": "created_at", "seconds": 600},
               "session": {"type":"realtime", "model": REALTIME_MODEL,
                           "instructions": FRONTDESK_INSTRUCTIONS,
                           "tools": [ASK_BACKEND_TOOL], "tool_choice": "auto",
                           "audio": {"input": {"transcription": {"model": TRANSCRIBE_MODEL}}}}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post("https://api.openai.com/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload)
    …エラー処理…
    return {"value": resp.json()["value"], "model": REALTIME_MODEL}
```
- **目的:** ブラウザ用の「使い捨ての鍵(ek_...)」を OpenAI から取って渡す。
- **payload の中身:** 音声モデル、人格(`FRONTDESK_INSTRUCTIONS`)、唯一のツール(`ASK_BACKEND_TOOL`)、
  ユーザー音声の文字起こし設定。→ 鍵で接続した瞬間から、この設定のセッションが使える。
- **安全のキモ:** 本物の `OPENAI_API_KEY` は**サーバー内だけ**で使い、ブラウザには短命の鍵しか渡さない。
- **返り値:** `value`(=ek_...)と `model`。ブラウザは `realtime.ts` でこれを使って接続する
  (→ [`CODE_realtime.md`](CODE_realtime.md) のブロック5-2)。

---

## まとめ(このファイルの地図)

```
[起動時に1回]  import → 設定 → Realtime設定 → llm → schema/_PENDING
               → ツール(query_graphdb / draft… / register_case)
               → エージェント(qa / registration) → Supervisor(+checkpointer)
[毎リクエスト] /ask     … 依頼を Supervisor に渡し {answer, ui} を返す
               /session … 使い捨て鍵(ek_)を発行して渡す
```

- 上半分=**一度だけ組み立てる部品**、下半分=**毎回動く2つの窓口**。
- 声側との対応:`/session` はブラウザの接続用(鍵)、`/ask` はブラウザの `ask_backend` の呼び先。
- 会話の記憶=**checkpointer**(session_idごと)、画面用の一時メモ=**`_PENDING`**(1リクエスト)。
