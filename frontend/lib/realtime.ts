// lib/realtime.ts — /v0 と /v1 が共有する WebRTC 接続ロジック。
// 旧 frontend/src/main.ts を移植し、UI 依存を無くしてコールバックで結果を渡す。
// 登録レビューは backend が返す ui ペイロードで駆動する(状態は backend が持つ)。

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// backend が返す ui ペイロード。
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
  onReview?: (review: ReviewUI) => void; // 4項目そろって確認中(表を出す/更新)
  onRegistered?: () => void; // 登録完了(表を消す)
};

export type RealtimeHandle = { disconnect: () => void };

// ask_backend の実行: backend の Supervisor に丸投げする。session_id で会話を記憶させる。
// answer(音声で話す文)と ui(登録レビュー/完了/なし)を返す。
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

// データチャネル経由の Realtime イベント処理。
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
        // backend の指示どおり、登録レビュー表を出す/更新する、または消す。
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

// Realtime に接続する。remoteAudio に相手(AI)の音声を流す。
export async function connectRealtime(
  remoteAudio: HTMLAudioElement,
  cbs: RealtimeCallbacks = {},
): Promise<RealtimeHandle> {
  cbs.onStatus?.("接続中…");
  const sessionId = crypto.randomUUID(); // 会話ごとの記憶キー(thread_id)

  // 1) ephemeral key と model を backend から取得。
  const sess = await fetch(`${API_BASE}/session`, { method: "POST" }).then((r) => {
    if (!r.ok) throw new Error(`/session が失敗しました (${r.status})`);
    return r.json();
  });
  const ephemeral: string = sess.value;
  const model: string = sess.model || "gpt-realtime-mini";

  // 2) WebRTC を組み立てる。相手の音声は <audio> に流す。
  const pc = new RTCPeerConnection();
  pc.ontrack = (e) => {
    remoteAudio.srcObject = e.streams[0];
  };

  const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micStream.getTracks().forEach((t) => pc.addTrack(t, micStream));

  const dc = pc.createDataChannel("oai-events");
  dc.onmessage = (e) => {
    void handleEvent(JSON.parse(e.data), dc, cbs, sessionId);
  };

  // 3) offer を作って /realtime/calls に渡し、answer を貼る。
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

  return {
    disconnect() {
      dc.close();
      pc.close();
      micStream.getTracks().forEach((t) => t.stop());
      cbs.onStatus?.("未接続");
    },
  };
}
