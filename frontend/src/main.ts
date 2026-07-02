// main.ts — Realtime 側(ブラウザ)。ツールは ask_backend の1つだけ。
// Start ボタン押下(ブラウザのマイク許可ジェスチャ)→ /session で ek_ を取得 → connect。

import { RealtimeAgent, RealtimeSession, tool } from "@openai/agents/realtime";
import { z } from "zod";

const BACKEND = "http://localhost:8000";

// 窓口ツール: バックエンドの Supervisor に丸投げする
const askBackend = tool({
  name: "ask_backend",
  description:
    "挨拶・聞き返し以外のあらゆるタスク依頼をバックエンドに委譲する。" +
    "requestにはユーザーの依頼内容をテキストでそのまま渡す。",
  parameters: z.object({ request: z.string() }),
  execute: async ({ request }) => {
    const res = await fetch(`${BACKEND}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: request }),
    });
    const data = await res.json();
    return data.answer; // Supervisor の要約テキストをそのまま返す
  },
});

const agent = new RealtimeAgent({
  name: "voice_frontdesk",
  instructions: `
あなたは音声窓口です。
- 挨拶や聞き返しは自分で短く応答する(許可リスト)。
- それ以外のタスク依頼は必ずask_backendを呼ぶ。自分で判断・処理しない。
- ツールを呼ぶ直前に「確認しますね」と一言添える。
- ツールの返答は、そのまま読まず短く音声向きに言い換えて話す。`,
  tools: [askBackend],
});

const startBtn = document.querySelector<HTMLButtonElement>("#start")!;
const statusEl = document.querySelector<HTMLParagraphElement>("#status")!;

let session: RealtimeSession | null = null;

startBtn.addEventListener("click", async () => {
  if (session) return;
  startBtn.disabled = true;
  statusEl.textContent = "接続中…";
  try {
    // ephemeral key(ek_...)は自前サーバー(/session)で発行したものを使う。
    // 本物の API キーはブラウザに出さない。
    const res = await fetch(`${BACKEND}/session`, { method: "POST" });
    if (!res.ok) throw new Error(`/session が失敗しました (${res.status})`);
    const { value } = (await res.json()) as { value: string };

    session = new RealtimeSession(agent, { model: "gpt-realtime" });
    await session.connect({ apiKey: value });

    statusEl.textContent = "接続しました。話しかけてください。";
  } catch (e) {
    session = null;
    startBtn.disabled = false;
    statusEl.textContent = `接続に失敗しました: ${
      e instanceof Error ? e.message : String(e)
    }`;
  }
});
