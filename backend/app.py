# ============================================================================
# app.py — このアプリの「バックエンド(サーバー側)」全部
# ============================================================================
#
# 【このアプリ全体の地図】(reference.md の構成)
#
#   ユーザーの声
#      ↓  マイク
#   ブラウザ (frontend/src/main.ts) ── OpenAI Realtime と音声で会話する
#      ↓  ask_backend というツールを1つだけ持つ
#   このファイル (backend/app.py) の /ask ── 司令塔(Supervisor)に依頼を渡す
#      ↓
#   Supervisor(司令塔) ── 依頼を見て、担当エージェントに振り分けるだけ
#      ├─→ qa_agent            … query_graphdb で既存グラフを読む
#      └─→ registration_agent  … draft_registration_record で登録候補を作る
#
# 【このファイルが持つ「窓口(URL)」は2つ】
#   - POST /ask     : ブラウザの ask_backend ツールから呼ばれる。依頼文をもらって
#                     Supervisor に渡し、要約された答えのテキストを返す。
#   - POST /session : ブラウザが OpenAI に直接つなぐための「使い捨ての鍵(ek_...)」を
#                     発行する。本物の API キーはブラウザに絶対渡さないための仕組み。
#
# 【起動コマンド】(backend フォルダの中で実行)
#   uv run uvicorn app:app --port 8000 --reload
#     - uvicorn  … Python の Web サーバー。FastAPI アプリを動かす。
#     - app:app  … 「app.py の中の app という変数」を動かす、という意味。
#     - --reload … コードを保存するたびに自動で再起動してくれる(開発中に便利)。
# ============================================================================


# ---- 1. 必要な道具(ライブラリ)を読み込む --------------------------------
# import は「他の人が作った便利な機能を、このファイルで使えるようにする」宣言。

import json  # Python のデータを JSON 文字列に変換する道具。
import os  # OS の機能。ここでは環境変数(os.environ)から API キーを読むのに使う。
from pathlib import Path  # ファイルの場所(パス)を扱いやすくする道具。

import httpx  # HTTP 通信をするライブラリ。ここでは OpenAI に鍵を発行してもらうのに使う。
from dotenv import load_dotenv  # .env ファイルから設定を読み込む道具。
from fastapi import FastAPI, HTTPException  # Web フレームワーク本体とエラー返却用。
from fastapi.middleware.cors import CORSMiddleware  # ブラウザからの通信を許可する設定。
from langchain.agents import create_agent  # 1体の「エージェント(AI+ツール)」を作る関数。
from langchain_openai import ChatOpenAI  # OpenAI のテキスト用モデルを使うためのクラス。
from langgraph_supervisor import create_supervisor  # 司令塔(振り分け役)を作る関数。
from langgraph.checkpoint.memory import MemorySaver  # セッションごとの会話記憶(thread)
from pydantic import BaseModel  # 受け取るデータの「型(かたち)」を定義する道具。

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None


# ---- 2. 設定(.env の読み込みと定数) ------------------------------------

# .env ファイルには秘密の API キーを書いてある。それをこのプログラムに読み込む。
# .env はこのリポジトリの一番上(このファイルの2つ上の階層)に置いてある。
#   Path(__file__)              … このファイル(app.py)自身の場所
#   .resolve()                  … 省略のない完全な場所に変換
#   .parent.parent              … 1つ上(backend/)→もう1つ上(リポジトリ直下)
#   / ".env"                    … そこにある .env を指す
# 「実行時のカレントディレクトリ」に頼らず、明示的な場所から読むのがポイント。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# アプリ設定は backend/app.py の外、リポジトリ直下の app_config.json に置く。
# モデル名やローカル接続先を変えるときは、まずこのファイルを編集する。
CONFIG_PATH = Path(__file__).resolve().parent.parent / "app_config.json"


# 所属: shared config / Supervisor・qa_agent・registration_agent が共通で使う設定読み込み
def load_app_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


APP_CONFIG = load_app_config()

# 音声用モデルと、頭脳用のテキストモデルは別物。混同しない。
# realtime_model … 声を聞いて声で返すためのモデル(ブラウザ側が使う)。
CHAT_MODEL = os.environ.get(
    "OPENAI_CHAT_MODEL",
    APP_CONFIG["openai"]["chat_model"],
)
REALTIME_MODEL = os.environ.get(
    "OPENAI_REALTIME_MODEL",
    APP_CONFIG["openai"]["realtime_model"],
)
# ユーザーの声を文字起こしするモデル。これを有効にすると Realtime が
# conversation.item.input_audio_transcription.completed イベントで
# ユーザー発話のテキストを送ってくる(=画面に「あなたの発言」を出せる)。
TRANSCRIBE_MODEL = os.environ.get(
    "OPENAI_TRANSCRIBE_MODEL",
    APP_CONFIG["openai"]["transcribe_model"],
)

# フロントエンド(ブラウザ側の開発サーバー)の住所。CORS 許可でこの値を使う。
# フロントのポートを 3000 以外に変えたら、ここも必ず合わせること。
FRONTEND_ORIGIN = os.environ.get(
    "FRONTEND_ORIGIN",
    APP_CONFIG["frontend"]["origin"],
)

# Neo4j(グラフDB)の接続先。環境変数があればそちらを優先し、無ければ
# LANGCHAIN_AGENT_CONTEXT.md に書かれたローカル開発用の値を使う。
NEO4J_URI = os.environ.get("NEO4J_URI", APP_CONFIG["neo4j"]["uri"])
NEO4J_USER = os.environ.get("NEO4J_USER", APP_CONFIG["neo4j"]["user"])
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", APP_CONFIG["neo4j"]["password"])
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", APP_CONFIG["neo4j"]["database"])

# --- Realtime(音声)側の「人格」と「唯一のツール」の宣言 ---
# これらは /session で使い捨ての鍵を発行するときに OpenAI に渡す。
# こうしておくと、鍵で接続した瞬間から AI はこの人格・このツールを知っている。
#
# instructions … AI に与える「振る舞いの指示(システムプロンプト)」。
FRONTDESK_INSTRUCTIONS = (
    "あなたは音声窓口です。\n"
    "- 挨拶や聞き返しは自分で短く応答する(許可リスト)。\n"
    "- それ以外のタスク依頼は必ずask_backendを呼ぶ。自分で判断・処理しない。\n"
    "- 【重要】バックエンドが実際に返した内容だけを話す。処理中・完了などを"
    "勝手に作らない(「登録処理に入ります」「完了したらお知らせします」等の作り話は禁止)。\n"
    "- 【故障ケースの登録】登録に関する発言は、そのつど ask_backend に渡すだけでよい。"
    "4項目(設備・故障・原因・対策)を自分で覚えてまとめ直さなくてよい"
    "(バックエンドが会話を記憶している)。バックエンドが『下記の情報で登録してよろしい"
    "でしょうか』と返したら、その確認をユーザーに伝える。ユーザーの『はい』『登録して』や"
    "項目の訂正も、そのまま ask_backend に渡す。バックエンドが返した内容だけを話し、"
    "勝手に「登録しました」と言わない。\n"
    "- ツールを呼ぶ直前に「確認しますね」と一言添える。\n"
    "- ツールの返答は、そのまま読まず短く音声向きに言い換えて話す。"
)

# ask_backend ツールの「設計図」。AI に「こういう関数が呼べますよ」と伝えるための定義。
# 実際の中身(実行)はブラウザ側(main.ts)が /ask を叩くことで行う。ここは宣言だけ。
#   type       … "function"(関数を呼ぶ形式のツール、という意味)
#   name       … ツールの名前。AI はこの名前で呼ぶ。
#   description… いつ使うツールかの説明。AI はこれを読んで使うかどうか判断する。
#   parameters … ツールに渡す引数の形。ここでは request という文字列を1つ受け取る。
ASK_BACKEND_TOOL = {
    "type": "function",
    "name": "ask_backend",
    "description": (
        "挨拶・聞き返し以外のあらゆるタスク依頼をバックエンドに委譲する。"
        "requestにはユーザーの依頼内容をテキストでそのまま渡す。"
    ),
    "parameters": {
        "type": "object",
        "properties": {"request": {"type": "string"}},
        "required": ["request"],  # request は必須(省略できない)
    },
}


# ---- 3. 頭脳(LangGraph)の組み立て --------------------------------------

# 頭脳側で使うテキストモデル。Supervisor も各エージェントもこのモデルで考える。
llm = ChatOpenAI(model=CHAT_MODEL)


WRITE_CYPHER_KEYWORDS = (
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "DETACH",
    "DROP",
    "REMOVE",
)


# 所属: qa_agent / query_graphdb の安全チェック用ヘルパー
def _is_read_only_cypher(cypher: str) -> bool:
    normalized = cypher.upper()
    if not normalized.lstrip().startswith(("MATCH", "CALL")):
        return False
    return not any(keyword in normalized for keyword in WRITE_CYPHER_KEYWORDS)


# 所属: qa_agent / Neo4j factory-failure graph をread-onlyで検索するツール
def query_graphdb(cypher: str) -> str:
    """Neo4jの工場故障グラフをread-only Cypherで検索する"""
    if not _is_read_only_cypher(cypher):
        return (
            "安全のためread-onlyのMATCH/CALLクエリだけ実行できます。"
            "CREATE、MERGE、SET、DELETEなどの書き込みは実行しません。"
        )

    if GraphDatabase is None:
        return "Neo4j Python driver is not installed. Run `uv sync` in backend/."

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session(database=NEO4J_DATABASE) as session:
            rows = [record.data() for record in session.run(cypher)]
    except Exception as e:
        return f"Neo4j query failed: {e}"
    finally:
        driver.close()

    if not rows:
        return "該当するグラフパスは見つかりませんでした。"
    return json.dumps(rows, ensure_ascii=False)


# 登録レコードのスキーマ。将来はここに種類を増やす(=スキーマレジストリの種)。
# 必須項目と表示ラベルをここで定義し、収集チェックと画面の表ラベルに使う。
FAILURE_CASE_SCHEMA = {
    "record": "FailureCase",
    "fields": [
        {"key": "equipment", "label": "設備", "required": True},
        {"key": "failure", "label": "故障", "required": True},
        {"key": "cause", "label": "原因", "required": True},
        {"key": "action", "label": "対策", "required": True},
    ],
}

# /ask が1リクエストの間だけ使う受け渡しスロット(単一ユーザーのデモ前提)。
#   review     … 4項目そろった構造化レコード(画面のレビュー表に出す)
#   registered … 直前に register_case が書き込んだ(表を消す合図)
# 会話の「記憶」自体は supervisor の checkpointer(thread=session_id)が保持する。
_PENDING: dict = {}


# 所属: registration_agent / スキーマの必須項目がそろったか確認し、そろえば保留に入れる
def draft_registration_record(
    equipment: str = "",
    failure: str = "",
    cause: str = "",
    action: str = "",
) -> str:
    """スキーマの必須項目がそろっているか確認する。Neo4jには書き込まない。
    そろっていれば構造化レコードを _PENDING["review"] に入れ(画面のレビュー表用)、
    足りなければ何が足りないかを返す。"""
    values = {
        "equipment": equipment.strip(),
        "failure": failure.strip(),
        "cause": cause.strip(),
        "action": action.strip(),
    }
    missing = [
        f["label"]
        for f in FAILURE_CASE_SCHEMA["fields"]
        if f["required"] and not values[f["key"]]
    ]
    if missing:
        return "登録には次の項目が必要です: " + ", ".join(missing)

    # 4項目そろったので、構造化レコードを保留に入れる(/ask が拾って画面のレビュー表へ)。
    _PENDING["review"] = values
    return (
        "4項目がそろいました。ユーザーに『下記の情報で登録してよろしいでしょうか』と"
        "確認してください。まだ登録していません。"
    )


# 所属: registration_agent / 4項目がそろったら Neo4j に実際に書き込むツール
def register_case(
    equipment: str = "",
    failure: str = "",
    cause: str = "",
    action: str = "",
) -> str:
    """故障ケースをNeo4jに登録する。スキーマ(Equipment->Failure->Cause->Action)に
    従って MERGE で書き込む。4項目すべて必須。"""
    fields = {
        "equipment": equipment,
        "failure": failure,
        "cause": cause,
        "action": action,
    }
    missing = [label for label, value in fields.items() if not value.strip()]
    if missing:
        return "登録するには次の項目が必要です: " + ", ".join(missing)

    if GraphDatabase is None:
        return "Neo4j Python driver is not installed. Run `uv sync` in backend/."

    params = {label: value.strip() for label, value in fields.items()}
    # スキーマ規則: Equipment/Cause/Action は name で共有(MERGE)。
    # Failure は設備ごと(name+equipment)なので、その2つで一意にする。
    cypher = (
        "MERGE (e:Equipment {name: $equipment}) "
        "MERGE (f:Failure {name: $failure, equipment: $equipment}) "
        "  ON CREATE SET f.id = randomUUID() "
        "MERGE (c:Cause {name: $cause}) "
        "MERGE (a:Action {name: $action}) "
        "MERGE (e)-[:HAS_FAILURE]->(f) "
        "MERGE (f)-[:CAUSED_BY]->(c) "
        "MERGE (c)-[:RESOLVED_BY]->(a)"
    )
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run(cypher, **params)
    except Exception as e:
        return f"Neo4j write failed: {e}"
    finally:
        driver.close()

    _PENDING["registered"] = True  # /ask が拾って画面のレビュー表を消す
    return "ナレッジに登録しました。"


qa_agent = create_agent(
    llm,
    tools=[query_graphdb],
    name="qa_agent",
    system_prompt=(
        "あなたは工場故障グラフのQ&Aエージェント。"
        "Neo4jに対してread-onlyのCypherだけをquery_graphdbで実行して答える。"
        "使えるラベルはEquipment, Failure, Cause, Actionのみ。"
        "使える関係はHAS_FAILURE, CAUSED_BY, RESOLVED_BYのみ。"
        "Equipment -> Failure -> Cause -> Action の向きを守る。"
        "特定設備の故障を聞かれたら必ずEquipmentからMATCHを始める。"
        "CREATE, MERGE, SET, DELETE, DETACH DELETE, DROPは使わない。"
    ),
)


registration_agent = create_agent(
    llm,
    tools=[draft_registration_record, register_case],
    name="registration_agent",
    system_prompt=(
        "あなたは工場故障ケースの登録担当。目的は、グラフDBに1件の完全なレコードを作るのに"
        "必要な4項目 equipment(設備)・failure(故障)・cause(原因)・action(対策) をそろえること。"
        "1件のレコードは経路 Equipment -[HAS_FAILURE]-> Failure -[CAUSED_BY]-> Cause "
        "-[RESOLVED_BY]-> Action になる。\n"
        "会話の記憶から4項目を集める。ユーザーの発言を上の4つの役割に当てはめて取り出す。\n"
        "手順:\n"
        "1) 現在わかっている4項目で draft_registration_record を呼ぶ。足りない項目があれば、"
        "その戻り値どおり不足を短く聞き返す。\n"
        "2) 4項目そろったら、戻り値どおり『下記の情報で登録してよろしいでしょうか』と確認する。\n"
        "3) ユーザーが訂正したら、その項目を直して再度 draft_registration_record を呼び、もう一度確認する。\n"
        "4) ユーザーが『はい』『登録して』等で明確に承諾したときだけ register_case を呼んで登録し、"
        "その戻り値(「ナレッジに登録しました。」)をそのまま伝える。\n"
        "承諾前に register_case を呼ばない。自分の判断で「登録しました」と作り話をしない。"
        "推測で項目を埋めない。"
    ),
)


# --- Supervisor(司令塔):振り分け専任 ---
# create_supervisor で「複数のエージェントをまとめて指揮する司令塔」を作る。
# 司令塔は自分では作業せず、依頼を見て適切なエージェントに渡すのが仕事。
#   agents … 指揮下のエージェント一覧
#   model  … 司令塔自身が「どっちに振り分けるか」を考えるための頭脳
#   prompt … 司令塔への指示
# 最後の .compile() は「組み立てを完成させて、実際に呼び出せる状態にする」処理。
supervisor = create_supervisor(
    agents=[qa_agent, registration_agent],
    model=llm,
    prompt=(
        "あなたは司令塔。ユーザーの依頼内容を見て、"
        "既存の工場故障グラフへの質問ならqa_agent、"
        "新しい故障ケースの追加・登録・聞き取りならregistration_agentに振り分ける。"
        "自分では実処理をしない。最後に結果を1〜2文で要約する。"
    ),
    # checkpointer でセッションごと(thread=session_id)に会話を記憶する。
    # これにより registration_agent は複数ターンにわたって4項目を覚えていられる。
).compile(checkpointer=MemorySaver())


# ---- 4. Web サーバー(FastAPI)の設定 ------------------------------------

# FastAPI() で Web アプリ本体を作る。この app が「サーバーそのもの」。
app = FastAPI()

# CORS(オリジン間リソース共有)の設定。
# ブラウザは安全のため「別の住所(オリジン)のサーバー」への通信を既定でブロックする。
# フロント(localhost:3000)からこのバックエンド(localhost:8000)を呼べるよう、明示的に許可する。
# これが無いと、ブラウザのコンソールに CORS エラーが出て /ask も /session も呼べない。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],   # 許可する呼び出し元(フロントの住所)
    allow_methods=["POST"],            # 許可する HTTP メソッド(このアプリは POST だけ使う)
    allow_headers=["Content-Type"],    # 許可するヘッダー
)


# POST /ask で受け取るデータの「型」を定義する。
# ブラウザからは {"text": "ポンプAが過熱したときの対策は?"} のような JSON が届く。
# BaseModel を継承しておくと、FastAPI が自動で中身をチェックして q.text で取り出せる。
class Query(BaseModel):
    text: str
    session_id: str | None = None  # 会話ごとの記憶キー(thread_id)。ブラウザが発行する。


# _PENDING の内容から、画面に渡す ui ペイロードを組み立てる。
# スキーマのラベル順に {label, value} の行を作るので、将来項目が増えても表はそのまま出せる。
def _build_ui() -> dict | None:
    if _PENDING.get("registered"):
        return {"kind": "registered"}  # 書き込み完了 → 画面の表を消す合図
    review = _PENDING.get("review")
    if review:
        return {
            "kind": "review",
            "title": "登録内容の確認",
            "fields": [
                {"label": f["label"], "value": review.get(f["key"], "")}
                for f in FAILURE_CASE_SCHEMA["fields"]
            ],
        }
    return None


# ---- 5. 窓口(エンドポイント)その1:/ask ---------------------------------
@app.post("/ask")
# 所属: FastAPI endpoint / Realtime frontdesk から Supervisor へ依頼を渡す窓口
async def ask(q: Query):
    """Realtime の ask_backend から呼ばれる。Supervisor の要約(answer)と、画面に出す
    ui(登録レビュー表 / 登録完了 / なし)を返す。

    会話の記憶は session_id(=thread_id)ごとに checkpointer が保持するので、
    registration_agent は複数ターンにわたって4項目を覚えていられる(=状態は後段が持つ)。
    """
    _PENDING.clear()  # 前のリクエストの受け渡しスロットを消してから実行
    config = {"configurable": {"thread_id": q.session_id or "default"}}
    try:
        result = await supervisor.ainvoke(
            {"messages": [{"role": "user", "content": q.text}]}, config=config
        )
        answer = result["messages"][-1].content
    except Exception as e:
        # 途中で失敗しても音声側が黙り込まないよう「文」で返す。
        return {"answer": f"すみません、処理中にエラーが発生しました: {e}", "ui": None}
    return {"answer": answer, "ui": _build_ui()}


# ---- 6. 窓口(エンドポイント)その2:/session -----------------------------
@app.post("/session")
# 所属: FastAPI endpoint / Realtime frontdesk 用の短命 client secret を発行する窓口
async def session():
    """ブラウザに渡す短命の ephemeral key (ek_...) を発行する。
    本物の OPENAI_API_KEY はサーバーから外に出さない。

    なぜ必要?
      ブラウザのコードは誰でも中身を見られるので、本物の API キーを置くと盗まれる。
      そこで「10分だけ有効な使い捨ての鍵(ek_...)」をサーバーで作ってブラウザに渡す。
      ブラウザはこの ek_ を使って OpenAI に直接つなぐ。
    """
    # .env から読み込んだ本物の API キーを取り出す。無ければ設定ミスなのでエラー。
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")

    # OpenAI に「使い捨ての鍵を発行して」と頼むときに送る中身。
    #   expires_after … 鍵の有効期限。created_at(作成時点)から 600 秒(=10分)。
    #   session        … 発行する Realtime セッションの設定。ここで人格やツールを埋め込む。
    #     model        … 使う音声モデル
    #     instructions … AI の人格・指示(上で定義したもの)
    #     tools        … 使えるツール一覧(ここでは ask_backend だけ)
    #     tool_choice  … "auto" は「AI が必要に応じて自分でツールを使う」設定
    payload = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "instructions": FRONTDESK_INSTRUCTIONS,
            "tools": [ASK_BACKEND_TOOL],
            "tool_choice": "auto",
            # ユーザー音声の文字起こしを有効化(GA Realtime の場所)。
            # これが無いと「あなたの発言」テキストは届かない。
            "audio": {"input": {"transcription": {"model": TRANSCRIBE_MODEL}}},
        },
    }

    # httpx.AsyncClient で OpenAI に HTTP リクエストを送る。
    # async with … 使い終わったら自動で接続を後片付けしてくれる書き方。
    # headers の Authorization に本物のキーを載せる(これはサーバー内だけの通信なので安全)。
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    # OpenAI がエラー(400以上)を返したら、その内容を添えて 502 で返す。
    # 注意:ここで本物の api_key は絶対に含めない(resp.text には含まれない)。
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to mint client secret: {resp.status_code} {resp.text}",
        )

    # 成功した場合、返ってきた JSON の中の "value" が使い捨ての鍵(ek_...)。
    data = resp.json()
    value = data.get("value")
    if not value:
        raise HTTPException(status_code=502, detail="No client secret in response")

    # ブラウザはこの後 https://api.openai.com/v1/realtime/calls?model=... に接続する。
    # そのとき model 名が必要なので、鍵と一緒に返してあげる。
    return {"value": value, "model": REALTIME_MODEL}
