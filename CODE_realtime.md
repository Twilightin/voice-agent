# コード解説: `frontend/lib/realtime.ts`(声担当の中身)

`realtime.ts` を**ブロックごと**に「これは何をするコードか・なぜ必要か」を説明します。
全体の役割は [`MENTAL_MODEL.md`](MENTAL_MODEL.md) を先に読むと分かりやすいです。

このファイルの登場人物(関数)は3つだけ:
- `connectRealtime()` … 入口。ボタンを押すと呼ばれ、接続を丸ごと組み立てる。
- `handleEvent()` … 会話中、OpenAI から届くイベントを1件ずつさばく。
- `askBackend()` … 依頼を backend の `/ask` に投げて答えをもらう。

呼ばれる順番:**`connectRealtime` → (会話中) `handleEvent` → `askBackend`**。

---

## ブロック1: バックエンドの住所

```ts
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
```

- **目的:** `/session` や `/ask` を呼ぶ先(バックエンドのURL)を1か所で決める。
- **何をする:** 環境変数 `NEXT_PUBLIC_API_BASE` があればそれを使い、無ければ
  `http://localhost:8000`(開発用)を使う。`??` は「左が無ければ右」。
- **なぜ:** 本番に移すとき、この1行(または環境変数)を変えるだけで接続先を切り替えられる。

---

## ブロック2: データの「形」を決める型

```ts
export type ReviewUI = {
  kind: "review";
  title: string;
  fields: { label: string; value: string }[];
};
type Ui = ReviewUI | { kind: "registered" } | null;

export type RealtimeCallbacks = {
  onStatus?: (status: string) => void;
  onUserTranscript?: (text: string) => void;
  onAssistantTranscript?: (text: string) => void;
  onReview?: (review: ReviewUI) => void;
  onRegistered?: () => void;
};

export type RealtimeHandle = { disconnect: () => void };
```

- **目的:** やり取りするデータの「形(かたち)」をあらかじめ約束しておく(TypeScript の型)。
  実行時の処理はしない。設計図のようなもの。
- **`Ui`** … `/ask` が返す `ui` の中身は「登録確認の表(review)」「登録完了(registered)」
  「なし(null)」の3通り、という宣言。
- **`RealtimeCallbacks`** … 画面(呼び出し側)が渡す「通知の受け口」一覧。`?` は「省略可」。
  - `onStatus` 接続状態、`onUserTranscript` あなたの発話、`onAssistantTranscript` AIの発話、
    `onReview` 登録確認、`onRegistered` 登録完了。
- **`RealtimeHandle`** … `connectRealtime` の戻り値の形。`disconnect()` で通話を切れる、という約束。
- **なぜ:** `realtime.ts` は「声の処理」だけを担当し、**画面への反映はコールバックに丸投げ**する。
  だから React でも他のUIでも、この型に合わせて受け口を渡せば動く(UIから独立)。

---

## ブロック3: `askBackend()` — 依頼を `/ask` に投げる

```ts
async function askBackend(
  request: string,
  sessionId: string,
): Promise<{ answer: string; ui: Ui }> {
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: request, session_id: sessionId }),
  });
  const data = await res.json();
  return { answer: (data.answer as string) ?? "", ui: (data.ui as Ui) ?? null };
}
```

- **目的:** ユーザーの依頼文を backend に送り、`answer`(声で話す文)と `ui`(画面情報)をもらう。
- **何をする:**
  - `fetch(.../ask, POST)` で `{ text: 依頼文, session_id: 会話ID }` を送る。
  - `await` は「返事が来るまで待つ」。`res.json()` で返ってきた JSON を取り出す。
  - `?? ""` / `?? null` は「値が無ければ空文字/なし」にする安全策。
- **なぜ:** `text` と `session_id` を送るのがポイント。`text`=あなたの言葉、
  `session_id`=会話の記憶キー(これで backend は前のターンを覚えていられる)。

---

## ブロック4: `handleEvent()` — OpenAI からのイベントをさばく

会話中、OpenAI Realtime は「データチャネル」を通じて色々な**イベント**を送ってきます。
この関数はイベントの種類(`ev.type`)ごとに処理を振り分けます。

```ts
async function handleEvent(
  ev: any,
  dc: RTCDataChannel,
  cbs: RealtimeCallbacks,
  sessionId: string,
) {
  switch (ev.type) {
    case "conversation.item.input_audio_transcription.completed":
      cbs.onUserTranscript?.(ev.transcript || "");
      break;
    case "response.output_audio_transcript.done":
      cbs.onAssistantTranscript?.(ev.transcript || "");
      break;
    case "response.function_call_arguments.done":
      if (ev.name === "ask_backend") {
        let request = "";
        try {
          request = JSON.parse(ev.arguments || "{}").request || "";
        } catch {
          /* 引数が壊れていたら空依頼として扱う */
        }
        const { answer, ui } = await askBackend(request, sessionId);
        if (ui?.kind === "review") cbs.onReview?.(ui);
        else if (ui?.kind === "registered") cbs.onRegistered?.();
        dc.send(
          JSON.stringify({
            type: "conversation.item.create",
            item: {
              type: "function_call_output",
              call_id: ev.call_id,
              output: answer,
            },
          }),
        );
        dc.send(JSON.stringify({ type: "response.create" }));
      }
      break;
  }
}
```

種類ごとの意味:

- **`…input_audio_transcription.completed`**(あなたの声の文字起こし完成)
  → `onUserTranscript` で画面へ(右の吹き出し)。
- **`response.output_audio_transcript.done`**(AIの発話の文字起こし完成)
  → `onAssistantTranscript` で画面へ(左の吹き出し)。
- **`response.function_call_arguments.done`**(AIが「ツールを使う」と決めた)
  この中が一番大事:
  1. `ev.arguments` は文字列のJSON。`JSON.parse` して `request`(依頼文)を取り出す。
     `try/catch` は壊れたJSONでもアプリを落とさないための保険。
  2. `askBackend(request, sessionId)` で backend に投げ、`{answer, ui}` をもらう。
  3. `ui` があれば画面へ:`review` なら `onReview`、`registered` なら `onRegistered`。
  4. `dc.send(... function_call_output ...)` で**ツールの結果(answer)を OpenAI に返す**
     (`call_id` でどの呼び出しへの返事かを紐づける)。
  5. `dc.send({type:"response.create"})` で「では、それを踏まえて喋って」と続きを促す。

- **目的:** 「聞こえたこと・AIが言ったこと」を画面に出し、AIがツールを呼んだら backend に
  中継して結果を返す。**これが声↔頭脳をつなぐ心臓部**。

---

## ブロック5: `connectRealtime()` — 接続を組み立てる入口

ボタンを押すと呼ばれ、WebRTC の通話を丸ごと用意します。小分けにして見ます。

### 5-1. 会話IDを作る

```ts
export async function connectRealtime(
  remoteAudio: HTMLAudioElement,
  cbs: RealtimeCallbacks = {},
): Promise<RealtimeHandle> {
  cbs.onStatus?.("接続中…");
  const sessionId = crypto.randomUUID();
```
- **目的:** この会話1回分の「記憶キー」を作る。`crypto.randomUUID()` はランダムな一意ID。
- 以降の `/ask` すべてにこの `sessionId` を付ける → backend が前のターンを覚えられる。

### 5-2. 使い捨ての鍵と model をもらう

```ts
  const sess = await fetch(`${API_BASE}/session`, { method: "POST" }).then((r) => {
    if (!r.ok) throw new Error(`/session が失敗しました (${r.status})`);
    return r.json();
  });
  const ephemeral: string = sess.value;   // ek_... (10分だけ有効な鍵)
  const model: string = sess.model || "gpt-realtime-mini";
```
- **目的:** OpenAI に直接つなぐための短命の鍵(`ek_...`)と、使う音声モデル名をもらう。
- **なぜ:** 本物のAPIキーはブラウザに置かない。だから毎回サーバーで使い捨て鍵を発行する。

### 5-3. 「回線」を用意し、相手の声を再生する

```ts
  const pc = new RTCPeerConnection();
  pc.ontrack = (e) => {
    remoteAudio.srcObject = e.streams[0];
  };
```
- **目的:** `RTCPeerConnection` = OpenAI と音声/データをやり取りする「電話回線」。
- `pc.ontrack` = 相手(AI)の音声が届いたら、それを `<audio>` 要素に流して再生する。
  これが無いと **AIの声が聞こえない**。

### 5-4. 自分のマイクを回線に載せる

```ts
  const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micStream.getTracks().forEach((t) => pc.addTrack(t, micStream));
```
- **目的:** マイクの使用許可を取り(`getUserMedia`)、その音声を回線に追加する。
  これで自分の声が相手に届く。ここでブラウザの「マイク許可」ダイアログが出る。

### 5-5. 文字メッセージ用の通路を開く

```ts
  const dc = pc.createDataChannel("oai-events");
  dc.onmessage = (e) => {
    void handleEvent(JSON.parse(e.data), dc, cbs, sessionId);
  };
```
- **目的:** 音声とは別に、文字(イベント)を送り合う「データチャネル」を開く。名前は固定。
- 届いたメッセージを **ブロック4の `handleEvent`** に渡す(`void` は戻り値を使わない印)。

### 5-6. 接続の申し込み(offer)→ 承諾(answer)

```ts
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const sdpRes = await fetch(
    `https://api.openai.com/v1/realtime/calls?model=${encodeURIComponent(model)}`,
    {
      method: "POST",
      body: offer.sdp,
      headers: {
        Authorization: `Bearer ${ephemeral}`,
        "Content-Type": "application/sdp",
      },
    },
  );
  if (!sdpRes.ok) {
    throw new Error(
      `/realtime/calls ${sdpRes.status}: ${(await sdpRes.text()).slice(0, 200)}`,
    );
  }
  await pc.setRemoteDescription({ type: "answer", sdp: await sdpRes.text() });

  cbs.onStatus?.("接続しました。話しかけてください。");
```
- **目的:** WebRTC の「握手」。`offer`(こういう条件で話したい、という申込書=SDP)を作り、
  OpenAI に送り、`answer`(承諾書=SDP)をもらって回線に設定する → 通話開始。
- **ここは backend を通らず、ブラウザが OpenAI に直接**つなぐ(鍵 `ek_` を使う)。
- 失敗時はHTTPステータスと中身をエラーに出す(原因調査に役立つ)。

### 5-7. 「切断」ボタン用の後片付けを返す

```ts
  return {
    disconnect() {
      dc.close();
      pc.close();
      micStream.getTracks().forEach((t) => t.stop());
      cbs.onStatus?.("未接続");
    },
  };
}
```
- **目的:** 呼び出し側に `disconnect()` を渡す。押すと、通路・回線を閉じ、マイクを解放する。

---

## まとめ(関数どうしの関係)

```
ボタン押下
  └─ connectRealtime()            接続を組み立てる(5-1〜5-7)
        └─ dc.onmessage
              └─ handleEvent()    OpenAIのイベントをさばく(ブロック4)
                    └─ askBackend()  依頼を /ask に投げて {answer, ui} を得る(ブロック3)
```

- 画面への反映は**すべてコールバック**(`cbs.onXxx`)経由 → `realtime.ts` はUIに依存しない。
- 音声は OpenAI と直通、テキスト(依頼/答え)は backend 経由。
- 次に `backend/app.py` 側のブロック解説が欲しければ、同じ形で作れます。
