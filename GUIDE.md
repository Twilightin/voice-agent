# Voice Agent 初心者ガイド

このアプリを「はじめて触る人」向けに、仕組み・動かし方・困ったときの対処まで
ひととおり説明します。コード自体の1行ずつの解説は各ファイルのコメントにあります
（`backend/app.py` / `frontend/lib/realtime.ts` / `frontend/app/v1/page.tsx`）。

---

## 1. これは何?

**声で話しかけると、AI が内容を理解して担当エージェントに振り分け、声で答えてくれる**
アプリです。今の担当は「工場の故障」に関する2人：

- **qa_agent（質問担当）** … ローカルの Neo4j グラフDBに保存された「工場故障の知識」を
  **読み取り専用**で検索して答える（例:「ポンプAが過熱したときの対策は？」）。
- **registration_agent（登録担当）** … 新しい故障ケースを会話で聞き取り、4項目
  （設備・故障・原因・対策）がそろうと画面に**読み取り専用の確認表**を出し、AI が音声で
  「下記の情報で登録してよろしいでしょうか」と確認する。人が**声で「はい」**と答えると
  **Neo4j に登録**され「ナレッジに登録しました。」と返す（訂正も声でできる）。

ポイントは **役割の分離**：

- **声の担当（ブラウザ）** … 聞く・話すことに専念。頭は使わない。
- **頭脳の担当（サーバー）** … 依頼を理解して振り分け、答えを要約する。

グラフDBのデータ構造や運用の詳細は
[`LANGCHAIN_AGENT_CONTEXT.md`](LANGCHAIN_AGENT_CONTEXT.md) にまとまっています。

---

## 2. 全体像（図）

```
  あなたの声
     ↓ マイク
  ブラウザ  frontend（Next.js: /v1=新UI, /v0=旧UI, 共通ロジック lib/realtime.ts）
     │   OpenAI Realtime と音声で会話。ツールは ask_backend の1つだけ。
     ↓ POST /ask（依頼文を渡す）
  サーバー  backend/app.py
     │   Supervisor(司令塔) が依頼を見て振り分ける
     ├─→ qa_agent            … query_graphdb（Neo4jをread-onlyで検索）
     └─→ registration_agent  … 4項目を聞き取る→確認表＋音声確認→声で「はい」でNeo4jへ登録
     ↑ 最後の答えの文だけを返す
  ブラウザが受け取り、AI が声で読み上げる（あなたの発言も文字起こしして画面に表示）
```

サーバーには「窓口(URL)」が2つあります：

| 窓口 | 役割 |
|---|---|
| `POST /ask` | ブラウザの ask_backend から呼ばれ、Supervisor の答えを返す |
| `POST /session` | ブラウザが OpenAI に直接つなぐための「使い捨ての鍵(ek_...)」を発行する |

---

## 3. データの流れ（文字で1歩ずつ）

「ポンプAが過熱したときの対策は？」と話した場合の、フロント↔バックの往復：

```
[1] ユーザー（声）        : 「ポンプAが過熱したときの対策は？」
        ↓ マイク → OpenAI Realtime（ブラウザが接続）
[2] Realtime(AI)         : 「タスク依頼だ」と判断し ask_backend ツールを呼ぶ
        ↓ ブラウザ: fetch POST http://localhost:8000/ask
            body = {"text": "ポンプAが過熱したときの対策は？"}
[3] /ask (backend)       : 受け取った text を Supervisor に渡す
        ↓ supervisor.ainvoke(
              {"messages": [{"role": "user",
                             "content": "ポンプAが過熱したときの対策は？"}]}
          )
[4] Supervisor(司令塔)    : 「既存グラフへの質問」→ qa_agent に振り分け
        ↓
[5] qa_agent             : read-only Cypher を組み立て query_graphdb を実行
        ↓ Neo4j へ
        MATCH (:Equipment {name:'ポンプA'})-[:HAS_FAILURE]->(:Failure {name:'過熱'})
              -[:CAUSED_BY]->(:Cause)-[:RESOLVED_BY]->(a:Action) RETURN a.name
        ↑ 結果（例: 再潤滑）
[6] Supervisor           : 結果を1〜2文に要約
        ↑ result["messages"] の一番最後の .content だけを取り出す
[7] /ask のレスポンス     : {"answer": "ポンプAの過熱には再潤滑が有効です"}
        ↑ ブラウザへ
[8] ブラウザ              : answer を function_call_output として AI に返す
        ↓ 続けて response.create
[9] Realtime(AI)         : その文を「声」で読み上げる → ユーザーが聞く
```

**Supervisor に渡すメッセージの形**（覚えておくと理解が早い）：

```json
{ "messages": [ { "role": "user", "content": "ユーザーの依頼文" } ] }
```

- `role` … 発言者。ユーザーの発言は必ず `"user"`。
- `content` … 発言の中身（ここではブラウザから届いた依頼文そのまま）。
- 返ってくる `result["messages"]` は会話全体のリスト。`/ask` はその**最後の1件の
  `.content`**（＝最終的な答え）だけをブラウザに返す。

---

## 4. 音声とテキスト：何が「声」で、何が「テキスト」か

このアプリは**音声で対話する**アプリです。ただし画面のチャット（吹き出し）に出る
**テキストは「声そのもの」ではなく、別々に作られた文字**です。ここを具体的に押さえます。

### 通り道は「2つのAPI」だけ

1. **OpenAI Realtime API**（ブラウザ ⇄ OpenAI、WebRTC で1本つながっている）
   - あなたのマイク音声を送り、AIの音声を受け取る（＝🔊 音声のやり取り本体）。
   - おまけに **2種類の文字起こしテキスト**を、同じデータチャネル経由で送ってくる：
     - **あなたの声**の文字起こし（Realtime が内部で `transcribe_model` を実行）
     - **AI自身の発話**の文字起こし（Realtimeモデルが発話と同時に出力）
2. **自前 backend（FastAPI）の `/ask`**（ブラウザ ⇄ 自分のサーバー、ふつうのHTTP）
   - ここで Supervisor が答えの**テキスト**（`answer`）を作る。これは声ではなく純粋な文字で、
     吹き出しにも直接は出ない“裏方”。

| 何 | 種類 | 誰が作るか（具体的に） | どう扱われる |
|---|---|---|---|
| あなたの声 | 🔊音声 | あなた（マイク） | WebRTCでRealtimeへ送信（画面に出ない） |
| あなたの発言テキスト | 📝テキスト | **Realtime API**（内部で `transcribe_model`=gpt-4o-mini-transcribe を実行） | **右の吹き出し（あなた）** |
| `ask_backend` の `request` | 📝テキスト | **Realtimeモデル**が依頼を要約して作る | 裏方（画面に出ない） |
| Supervisor の `answer` | 📝テキスト | **自前 `/ask`**（Supervisor/エージェント） | 裏方（AIが声にする材料） |
| AIの声 | 🔊音声 | **Realtimeモデル**が発話を生成 | スピーカーで再生 |
| AIの発言テキスト | 📝テキスト | **Realtimeモデル**が発話と同時に出力 | **左の吹き出し（エージェント）** |

### つまずきやすい3点（Q&A）

**Q1. `transcribe_model` はどのAPIのもの？**
自分で `POST /v1/audio/transcriptions` を叩くのではありません。`/session`（`client_secrets`
発行）で `session.audio.input.transcription.model` に名前を書くだけ。すると **Realtime API が
サーバー側でその文字起こしモデルを回し**、結果を同じ WebRTC データチャネルに
`conversation.item.input_audio_transcription.completed` として流してきます。
→ あなたの声のテキストは **Realtime API の中**で生まれる（あなたのコードは受け取るだけ）。

**Q2. Realtimeモデルは Supervisor の `answer` を声に「変換」する？**
いいえ、TTSのような逐語変換ではありません。`answer` を `function_call_output`（ツール結果）
としてデータチャネルで渡し、`response.create` を送ると、**Realtimeモデルはそれを“材料”に
新しい発話を生成**します（指示により短く言い換える）。声はモデルが**作り直したもの**で、
`answer` をそのまま読み上げているのではありません。

**Q3. Realtimeモデルは自分の声を文字起こしできる？**
自分の音声を聞き直して起こすのではありません。Realtimeモデルは**音声とテキストを同時に
生成**します。喋ると同時に内容を `response.output_audio_transcript.delta`（逐次）→
`.done`（確定）としてテキストで送ってきます。これが左の吹き出しです。
→ AIのテキストは `transcribe_model` ではなく **Realtimeモデル自身**が出す。
（`transcribe_model` が担当するのは **あなたの声だけ**。）

### 例A：qa_agent（1往復の質問）

```
① 🔊あなた→AI : 「ポンプAが過熱したときの対策は？」（声）
② 📝表示      : transcribe_model が①を文字化 → 右の吹き出し
                「ポンプAが過熱したときの対策は？」
③ 📝裏方      : AI が ask_backend(request="ポンプAの過熱の対策") を呼ぶ
④ 📝裏方      : /ask → Supervisor → qa_agent → query_graphdb（read-only）
                answer = "ポンプAの過熱には再潤滑が有効です"
⑤ 🔊AI→あなた : AI が④を材料に発話を生成 → スピーカーで再生（声）
⑥ 📝表示      : AI が⑤の発話を文字化 → 左の吹き出し
                「再潤滑がおすすめです」
```

### 例B：registration_agent（複数往復の聞き取り）

```
① 🔊あなた→AI : 「新しい故障ケースを登録したい」（声）
② 📝表示      : → 右の吹き出し「新しい故障ケースを登録したい」
③ 📝裏方      : ask_backend(request="故障ケースを登録したい")
④ 📝裏方      : Supervisor → registration_agent → draft_registration_record()
                4項目(equipment/failure/cause/action)が未入力 → 「不足項目」を返す
⑤ 🔊/📝 AI    : 「どの設備の、どんな故障ですか？」（声＋左の吹き出し）
── ここでもう1往復 ──
⑥ 🔊あなた→AI : 「モーターBの異音。原因はベアリング摩耗、対策はベアリング交換」（声）
⑦ 📝表示      : → 右の吹き出し
⑧ 📝裏方      : ask_backend → registration_agent → draft_registration_record(4項目そろう)
                → 画面に読み取り専用の確認表を表示（設備/故障/原因/対策）
⑨ 🔊/📝 AI    : 「下記の情報で登録してよろしいでしょうか」と確認
⑩ 🔊人が承諾   : 声で「はい」→ registration_agent が register_case → Neo4j に MERGE で書き込み
                → AIが「ナレッジに登録しました。」と言い、確認表が消える（訂正も声でできる）
```

2つの例は **担当エージェントが違う**（例A=qa_agent は既存グラフを読む、
例B=registration_agent は聞き取って下書きを作る）だけで、
**声とテキストの流れ方（🔊は音声、📝は文字起こし/裏方）は同じ**なのがポイントです。

---

## 5. 必要なもの（準備）

- **Python 3.12 以上** と [uv](https://docs.astral.sh/uv/)（Python の環境管理ツール）
- **Node.js 20 以上** と npm
- **Neo4j**（グラフDB）がローカルで起動していて、工場故障データが投入済みであること
  （データ投入や起動は `LANGCHAIN_AGENT_CONTEXT.md` を参照。Homebrew なら
  `brew services start neo4j`）
- **OpenAI の API キー**（Realtime が使えるもの）

### 秘密の鍵（.env）

API キーは、リポジトリ直下の **`.env`** に次の形で書きます（クォートも空白も付けない）：

```
OPENAI_API_KEY=sk-あなたのキー
```

> ⚠️ `.env` は秘密のファイルです。`.gitignore` で Git 管理から外してあるので、
> うっかり公開されません。中身（キー本体）を人に見せないこと。

### 設定ファイル（app_config.json）

モデル名・フロントの住所・Neo4j 接続先は、リポジトリ直下の
**`app_config.json`** にまとまっています。**まずここを編集**します。

```json
{
  "openai": {
    "chat_model": "gpt-4o-mini",            // 頭脳(Supervisor/agents)用のテキストモデル
    "realtime_model": "gpt-realtime-mini",   // 音声用モデル(ブラウザが使う)
    "transcribe_model": "gpt-4o-mini-transcribe" // ユーザーの声を文字に起こすモデル
  },
  "frontend": { "origin": "http://localhost:3000" },  // CORS 許可先
  "neo4j": {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "your-neo4j-password",
    "database": "neo4j"
  }
}
```

> 一時的に上書きしたいときは**環境変数**が優先されます:
> `OPENAI_CHAT_MODEL` / `OPENAI_REALTIME_MODEL` / `OPENAI_TRANSCRIBE_MODEL` / `FRONTEND_ORIGIN` /
> `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE`。

---

## 6. 動かす手順

### 6-1. 最初の1回だけ：セットアップ

```bash
cd backend && uv sync          # サーバー側の部品をインストール(Neo4jドライバ含む)
cd ../frontend && npm install  # ブラウザ側の部品をインストール
```

### 6-2. 毎回：Neo4j を起動 → 2つのターミナルでアプリ起動

```bash
brew services start neo4j      # グラフDBを起動(未起動なら)
```

**ターミナル1（サーバー / 8000番）**
```bash
cd backend && uv run uvicorn app:app --port 8000 --reload
```

**ターミナル2（ブラウザ用サーバー / 3000番）**
```bash
cd frontend && npm run dev
```

### 6-3. 使う

ブラウザで **http://localhost:3000** を開く（自動で新UIの **/v1** に移動）→「会話をはじめる」を
押す → マイクを許可 → 話しかける。**あなたの発言も相手の返答も、チャットの吹き出しで表示されます。**
（従来の見た目は **/v0** に残してあります。）

試す例：
- 「ポンプAが過熱したときの対策は？」→ `qa_agent`（グラフを検索して答える）
- 「新しい故障ケースを登録したい」→ `registration_agent`（項目を聞き取って下書きを作る）

---

## 7. ファイル構成

```
voice-agent/
├── .env                       秘密のキー（自分で用意。Git 管理外）
├── .env.example               .env の見本
├── app_config.json            モデル・フロント・Neo4j の設定
├── LANGCHAIN_AGENT_CONTEXT.md  Neo4j グラフの構造と運用メモ
├── GUIDE.md                    このガイド
├── README.md                  手順の要約
├── reference.md               設計の元になった構成メモ
├── CLAUDE.md                  AI 開発アシスタント向けのメモ
├── backend/                   サーバー側（Python）
│   ├── app.py                 ★ 本体：Supervisor + qa/registration + /ask + /session
│   ├── pyproject.toml          使うライブラリの一覧（neo4j を含む）
│   └── tests/test_ask.py       自動テスト（音声・Neo4jなしで動作確認）
└── frontend/                  ブラウザ側（Next.js App Router）
    ├── app/v1/page.tsx         ★ 新UI（Vercel useChat）：発言と返答を吹き出し表示
    ├── app/v0/page.tsx           旧UI（従来の見た目を保存）
    ├── app/layout.tsx           全ページ共通の枠
    ├── app/globals.css          見た目（CSS）
    └── lib/realtime.ts         ★ 共通：WebRTC 接続と ask_backend 実行
```

> `app.py` の各関数の前には `所属:` コメントが付いていて、その関数が
> qa_agent / registration_agent / 共通設定 / FastAPIの窓口 のどれに属するか一目で分かります。

---

## 8. グラフDB（Neo4j）の構造だけ最低限

qa_agent が検索する「工場故障グラフ」は、4種類のノードと3種類の関係だけでできています。

```
(:Equipment) -[:HAS_FAILURE]-> (:Failure) -[:CAUSED_BY]-> (:Cause) -[:RESOLVED_BY]-> (:Action)
   設備            故障が起きる      故障        原因は        原因      直し方は        対策
```

- ラベル(種類)は **Equipment / Failure / Cause / Action** の4つだけ。
- 矢印の向きは上記の通り固定。特定設備の故障を調べるときは**必ず Equipment から**たどる。
- qa_agent は安全のため **読み取り専用（MATCH / CALL）** の検索しかしません。
  CREATE/MERGE/SET/DELETE などの書き込みは実行しません。

---

## 9. 用語ミニ辞典

| 用語 | かんたんな意味 |
|---|---|
| **Realtime** | OpenAI の「声で会話できる」モデル。ブラウザが直接つなぐ。 |
| **Supervisor（司令塔）** | 依頼を見て担当に振り分けるだけの役。自分では作業しない。 |
| **エージェント** | 「AI + 専用ツール」を1体にまとめたもの（例：qa_agent）。 |
| **ツール** | AI が呼べる関数（例：query_graphdb）。中身は普通のコード。 |
| **Neo4j / グラフDB** | 「もの同士のつながり」を保存するデータベース。工場故障の知識を入れてある。 |
| **Cypher** | Neo4j に問い合わせるための言語（SQL のグラフ版）。 |
| **read-only（読み取り専用）** | データを変えず、探すだけ。qa_agent はこれだけ許可。 |
| **ephemeral key（ek_...）** | 10分だけ有効な使い捨ての鍵。ブラウザに本物のキーを置かないための仕組み。 |
| **WebRTC** | ブラウザと相手が音声・データを直接やり取りする技術。 |
| **Next.js / useChat** | 画面を作る React の枠組みと、会話UIを作る Vercel の部品。/v1 で使用。 |
| **文字起こし(transcription)** | ユーザーの声をテキストに変換すること。`transcribe_model` で有効化。 |
| **CORS** | ブラウザが「別の住所のサーバー」への通信を許すかどうかの仕組み。 |
| **.env / app_config.json** | 秘密の鍵は .env、モデルや接続先は app_config.json に書く。 |

---

## 10. 機能を増やすには（例：新しい担当を追加）

**うれしいポイント：新機能はサーバー側(`app.py`)だけで足せます。**
ブラウザ側は「ask_backend ひとつ」のままで OK（振り分けはサーバーの仕事だから）。

`backend/app.py` に次の2ステップを足すだけ：

```python
# ① ツール（普通の関数）を作る
def search_manuals(keyword: str) -> str:
    """マニュアルをキーワード検索する"""
    return f"「{keyword}」に関するマニュアルはこちらです"  # ← 本来は検索処理

# ② その関数を使うエージェントを作り、Supervisor の一覧に加える
manual_agent = create_agent(
    llm, tools=[search_manuals], name="manual_agent",
    system_prompt="マニュアル検索担当。search_manualsで調べて答える。",
)

# create_supervisor(...) の agents=[...] に manual_agent を追加し、
# prompt に「マニュアルなら manual_agent」の一文を足す。
```

> Neo4j を触るツールを足すときは、`LANGCHAIN_AGENT_CONTEXT.md` の
> スキーマ（Equipment/Failure/Cause/Action と3つの関係、向き）を必ず守ること。

---

## 11. 困ったとき（実際に出たエラーと対処）

| 症状 | 原因と対処 |
|---|---|
| `/session が失敗しました (502)` / `Incorrect API key` | `.env` のキーが無効。**新しい有効なキーに書き換える**。 |
| キーを直したのに直らない | `--reload` は `.py` の変更しか見ない。**`.env` や `app_config.json` を変えたらサーバーを再起動**（Ctrl+C → 起動し直し）。 |
| ブラウザに **CORS エラー** | フロントのポートと設定の `frontend.origin` が不一致。両方 3000 に揃える。 |
| `Failed to parse SessionDescription. Expect line: v=` | 音声接続で OpenAI が SDP でなくエラーを返した。多くは**マイク未許可**か音声トラック無し。アドレスバーの🔒→サイト設定→マイクを「許可」に。状態表示に本当の `/realtime/calls` の中身が出るのでそれを見る。 |
| 回答が「Neo4j query failed」 | Neo4j が起動していない/接続情報が違う。`brew services start neo4j`。パスワード不一致なら `app_config.json` か `NEO4J_PASSWORD` を確認。 |
| `Neo4j Python driver is not installed` | `cd backend && uv sync` で依存を入れ直す。 |
| 回答が「read-onlyの…だけ実行できます」 | qa_agent が書き込みクエリを作ろうとした（安全機能が拒否）。質問を「調べる」形に言い換える。 |
| AI の声が聞こえない | スピーカーの音量/ミュートを確認。ページの `<audio autoPlay>`（`app/v1/page.tsx` など）が消えていないか確認。 |
| 自分の発言が吹き出しに出ない | ユーザー音声の文字起こしは `app_config.json` の `transcribe_model` で有効化される。変更したらサーバー再起動。マイク許可も確認。 |
| ポートが使用中で起動できない | 別プロセスが 8000/3000/7687 を使用中。止めるかポートを変える（変えたら設定も合わせる）。 |
| VS Code で `インポート "..." を解決できませんでした` の赤線 | コードのエラーではない。Pylance が別の Python を見ているだけ。**Cmd+Shift+P →「Python: Select Interpreter」→ `backend/.venv/bin/python`** を選ぶ。 |

### 動作確認（音声・Neo4j なしのテスト）

サーバーの中身だけ確認したいとき（Neo4j も本物の OpenAI も呼ばずに動く）：

```bash
cd backend && uv run pytest        # すべて
cd backend && uv run pytest tests/test_ask.py -q
```

---

## 12. もっと知るには

- **コードの1行解説** … `backend/app.py`、`frontend/lib/realtime.ts`、`frontend/app/v1/page.tsx` の
  コメントを上から読む（このガイドと対応しています）。
- **全体のメンタルモデル** … `MENTAL_MODEL.md`（`app.py` と `realtime.ts` の役割と、2つのやり取り）。
- **realtime.ts のコード解説** … `CODE_realtime.md`（ブロックごとに目的と動きを解説）。
- **app.py のコード解説** … `CODE_app.md`（起動時の組み立て／2つの窓口をブロックごとに解説）。
- **登録の内部フロー** … `REGISTRATION_FLOW.md`（2つのツールと `_PENDING` の流れを会話例で1歩ずつ解説）。
- **グラフDBの中身と運用** … `LANGCHAIN_AGENT_CONTEXT.md`（スキーマ・安全なクエリ例・起動手順）。
- **設定の場所** … `app_config.json`（モデル・フロント・Neo4j）。
- **設計の考え方** … `reference.md` と `docs/superpowers/specs/2026-07-02-voice-agent-design.md`。
- **手順の要約** … `README.md`。
