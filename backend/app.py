# app.py — LangGraph Supervisor (司令塔 + タスクエージェント2つ) + Realtime 窓口
# 起動: uv run uvicorn backend.app:app --port 8000 --reload
#
# 役割:
#   - Supervisor: 意図を見て task agent に振り分けるだけ。実処理はしない。
#   - task agents: 各自の tool で実タスクを実行。
#   - /ask   : Realtime の ask_backend ツールから叩かれる HTTP 窓口。
#   - /session: ブラウザ用の ephemeral key (ek_...) をサーバー側で発行する。

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph_supervisor import create_supervisor
from pydantic import BaseModel

# .env はリポジトリ直下(このファイルの1つ上)に置く。実行時の CWD に依存しないよう明示パスで読む。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 音声側は gpt-realtime、頭脳側(Supervisor/agents)はテキスト LLM。混同しない。
REALTIME_MODEL = "gpt-realtime"
FRONTEND_ORIGIN = "http://localhost:5173"

llm = ChatOpenAI(model="gpt-4.1")


# --- Task Agent A: 天気 ---
def get_weather(city: str) -> str:
    """指定した都市の天気を返す"""
    return f"{city}は晴れ、気温25度です"  # ダミー実装


weather_agent = create_agent(
    llm,
    tools=[get_weather],
    name="weather_agent",
    system_prompt="天気専門エージェント。get_weatherで調べて答える。",
)


# --- Task Agent B: TODO ---
def add_todo(task: str) -> str:
    """TODOを1件登録する"""
    return f"TODOに登録しました: {task}"  # ダミー実装


todo_agent = create_agent(
    llm,
    tools=[add_todo],
    name="todo_agent",
    system_prompt="TODO管理エージェント。add_todoで登録して結果を報告する。",
)


# --- Supervisor: 振り分け専任 ---
supervisor = create_supervisor(
    agents=[weather_agent, todo_agent],
    model=llm,
    prompt=(
        "あなたは司令塔。ユーザーの依頼内容を見て、"
        "天気ならweather_agent、TODOならtodo_agentに振り分ける。"
        "自分では実処理をしない。最後に結果を1〜2文で要約する。"
    ),
).compile()


# --- FastAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


class Query(BaseModel):
    text: str


@app.post("/ask")
async def ask(q: Query):
    """Realtime の ask_backend から呼ばれる。Supervisor の要約だけを返す。"""
    try:
        result = await supervisor.ainvoke(
            {"messages": [{"role": "user", "content": q.text}]}
        )
        # 最後のメッセージの content だけを Realtime へ返す
        return {"answer": result["messages"][-1].content}
    except Exception as e:  # 音声側が常に何か喋れるよう、失敗も文で返す
        return {"answer": f"すみません、処理中にエラーが発生しました: {e}"}


@app.post("/session")
async def session():
    """ブラウザに渡す短命の ephemeral key (ek_...) を発行する。
    本物の OPENAI_API_KEY はサーバーから外に出さない。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")

    payload = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": {"type": "realtime", "model": REALTIME_MODEL},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        # OpenAI 側のエラー内容は返すが、こちらの API キーは絶対に含めない
        raise HTTPException(
            status_code=502,
            detail=f"Failed to mint client secret: {resp.status_code} {resp.text}",
        )

    data = resp.json()
    value = data.get("value")
    if not value:
        raise HTTPException(status_code=502, detail="No client secret in response")
    return {"value": value}
