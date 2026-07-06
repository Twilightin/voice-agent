# メンタルモデル: `app.py` と `realtime.ts` の頭の中

このアプリは大きく **2つのファイル**でできています。初心者がまず持つべき「頭の中のイメージ
(メンタルモデル)」を、たとえ話つきで説明します。1行ずつの動きは
[`REGISTRATION_FLOW.md`](REGISTRATION_FLOW.md)、全体の使い方は [`GUIDE.md`](GUIDE.md) を参照。

- **`frontend/lib/realtime.ts`** … ブラウザで動く「**声担当**」。耳(マイク)と口(スピーカー)。
- **`backend/app.py`** … サーバーで動く「**頭脳担当**」。考えて、振り分けて、答えを作る。

> このアプリの一番の肝は **「声」と「頭」を分けている** こと。
> 声担当は考えない。頭脳担当は喋らない。役割を混ぜないのがポイントです。

---

## 1. 一言でいうと

電話の窓口を思い浮かべてください。

- **`realtime.ts` = 受付の人**。お客さんの声を聞き、専門家の答えを声で伝えるだけ。
  自分では判断しない。難しい話は全部「奥のチーム」に回す。回すための電話が1本だけある
  （これが `ask_backend` というツール）。
- **`app.py` = 奥の専門家チーム**。受付から回ってきた依頼を、司令塔(Supervisor)が見て、
  担当者(エージェント)に振り分け、答えをまとめて受付に返す。

---

## 2. 全体像(図)

```
   あなた(声)
     │  マイク / スピーカー
     ▼
┌──────────────────────────┐        音声(WebRTC・直接)
│  realtime.ts (声担当)      │◀──────────────────────▶  OpenAI Realtime
│  ・耳と口                  │                          (声を聞く/声で話す)
│  ・ツールは ask_backend 1つ │
└──────────────────────────┘
     │  HTTP
     │  ① POST /session (鍵をもらう)
     │  ② POST /ask     (依頼を渡す)
     ▼
┌──────────────────────────┐
│  app.py (頭脳担当)         │
│  ・/session 受付           │───▶ OpenAI(使い捨て鍵の発行)
│  ・/ask 受付               │
│  ・Supervisor(司令塔)      │
│     ├─ qa_agent           │───▶ Neo4j(読む)
│     └─ registration_agent │───▶ Neo4j(書く)
└──────────────────────────┘
```

矢印が2種類あることに注目:
- **realtime.ts ⇄ OpenAI Realtime**（音声。ブラウザが直接つなぐ）
- **realtime.ts ⇄ app.py**（HTTP。`/session` と `/ask` の2本だけ）

---

## 3. `realtime.ts` の頭の中(声担当)

**役割:** 音声の入出力と、依頼の中継だけ。自分では考えない。

覚えることは3つ:

1. **接続する** — `connectRealtime()` が
   ① backend の `/session` から「使い捨ての鍵(ek_...)」をもらい、
   ② その鍵で OpenAI Realtime に **WebRTC で直接** つなぐ。
   （本物の API キーはブラウザに来ない。鍵だけ。安全のため）
2. **唯一のツール `ask_backend`** — AI が「タスクをやって」と判断したら、これが
   `POST /ask` を叩く。**ここ以外に頭脳はない**（振り分けは全部 app.py 側）。
3. **コールバックで画面に反映** — 届いたテキストを画面に出すための「通知口」:
   - `onUserTranscript` … あなたの声の文字起こし → 右の吹き出し
   - `onAssistantTranscript` … AI の発話の文字起こし → 左の吹き出し
   - `onReview` … 登録確認の情報 → 会話に確認テキストを出す
   - `onStatus` … 「接続中…」などの状態表示

> `realtime.ts` は「耳・口・1本の電話」。**判断ロジックを足してはいけない**
> （足すと頭脳担当と二重になる)。

---

## 4. `app.py` の頭の中(頭脳担当)

**役割:** 依頼を理解し、担当に振り分け、答えを作る。声は出さない。

覚えることは4つ:

1. **2つの窓口(URL)**
   - `POST /session` … ブラウザ用の「使い捨て鍵」を OpenAI から取って渡す受付。
   - `POST /ask` … 依頼を受けて答え(`answer`)と画面情報(`ui`)を返す受付。
2. **Supervisor(司令塔)** … 依頼を見て、`qa_agent`(質問)か `registration_agent`(登録)に
   振り分けるだけ。自分では作業しない。
3. **エージェントとツール** … エージェントが実作業ツールを呼ぶ:
   `query_graphdb`(Neo4jを読む)、`register_case`(Neo4jに書く)など。
4. **2つの記憶のしくみ**
   - **checkpointer**(session_idごとの会話記憶) … 複数ターンにわたって内容を覚える本体。
   - **`_PENDING`**(1リクエストだけの受け渡しメモ) … ツールが作った構造化データを
     `/ask` が拾って画面(`ui`)に載せるための一時置き場。**LLMからは見えない**。

> 詳しい流れ(ツールの引数・`_PENDING`・`ui`)は
> [`REGISTRATION_FLOW.md`](REGISTRATION_FLOW.md) にステップごとに書いてあります。

---

## 5. 2つはどうやり取りするか(順番)

「東京の天気は？」のような1往復の例:

```
[1] ボタン「会話をはじめる」
      realtime.ts → POST /session          (app.py へ)
      app.py → OpenAI に鍵を発行            (/session の中)
      app.py → { value: "ek_...", model }   を返す
[2] realtime.ts が ek_ で OpenAI Realtime に WebRTC 接続  (app.py は通らない・直接)
[3] あなたが話す
      OpenAI Realtime が ask_backend を呼ぶ
      realtime.ts → POST /ask { text:"...", session_id }  (app.py へ)
[4] app.py: Supervisor → 担当エージェント → ツール → 答え
      app.py → { answer:"...", ui:null }    を返す
[5] realtime.ts:
      ・answer を OpenAI に返す → AI が声で読み上げる
      ・文字起こしイベントを onUserTranscript / onAssistantTranscript で画面へ
```

ポイント:
- **音声そのもの**は realtime.ts ⇄ OpenAI の直通(app.py を通らない)。
- **依頼と答え(テキスト)**だけが realtime.ts ⇄ app.py を往復する。
- app.py が返すのは常に `{answer, ui}` の形。`answer`=声で話す文、`ui`=画面に出す追加情報。

---

## 6. 覚えておく「3つのこと」

1. **声と頭は別**。`realtime.ts` は考えない、`app.py` は喋らない。
2. **窓口は2つだけ**。`/session`(鍵)と `/ask`(依頼)。フロントのツールも `ask_backend` の1つだけ。
3. **記憶は2種類**。会話の記憶=**checkpointer**(session_idごと)、画面用の一時メモ=**`_PENDING`**
   (1リクエストだけ)。混同しない。

新しい機能を足すときは **app.py 側にエージェント/ツールを足す**。`realtime.ts`(フロント)は
`ask_backend` のまま触らない ── これがこのアプリの設計ルールです。
