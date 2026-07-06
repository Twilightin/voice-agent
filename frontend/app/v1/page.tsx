"use client";

// /v1 — 新UI。useChat() を会話の入れ物として使い、Realtime の文字起こしを流し込む。
// 登録の4項目がそろうと backend が ui:review を返し、確認表を「エージェントの発言」として
// 会話の中に差し込む(別枠のカードにはしない)。確定・訂正はすべて音声。

import { useRef, useState } from "react";
import Link from "next/link";
import { useChat } from "@ai-sdk/react";
import {
  connectRealtime,
  type RealtimeHandle,
  type ReviewUI,
} from "@/lib/realtime";

export default function V1Page() {
  const { messages, setMessages } = useChat();
  const [status, setStatus] = useState("未接続");
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const handleRef = useRef<RealtimeHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
    });
  }

  // 文字起こしの吹き出しを追加(ユーザー/AI)。
  function append(role: "user" | "assistant", text: string) {
    if (!text) return;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random()}`, role, parts: [{ type: "text", text }] },
    ]);
    scrollToBottom();
  }

  // 確認内容を「エージェントの発言」として、プレーンテキスト(改行区切り)で会話に差し込む。
  // .bubble は white-space: pre-wrap なので改行はそのまま表示される。
  function appendReview(review: ReviewUI) {
    const lines = [
      review.title,
      ...review.fields.map((f) => `${f.label}: ${f.value}`),
      "この内容で登録しますか？　音声で「はい」／訂正したい項目はそのまま話してください。",
    ];
    append("assistant", lines.join("\n"));
  }

  async function onClick() {
    if (handleRef.current) {
      handleRef.current.disconnect();
      handleRef.current = null;
      setConnected(false);
      return;
    }
    setBusy(true);
    try {
      handleRef.current = await connectRealtime(audioRef.current!, {
        onStatus: setStatus,
        onUserTranscript: (t) => append("user", t),
        onAssistantTranscript: (t) => append("assistant", t),
        onReview: (r) => appendReview(r), // 確認表を会話の中に差し込む
      });
      setConnected(true);
    } catch (e) {
      setStatus(`接続に失敗しました: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const dotClass = connected ? "dot live" : busy ? "dot busy" : "dot";

  return (
    <main className="shell">
      <div className="topbar">
        <span className="title">🎙️ Voice Agent</span>
        <nav className="nav">
          <Link href="/v0">v0</Link>
          <Link href="/v1" className="active">v1</Link>
        </nav>
      </div>

      <div className="log" ref={logRef}>
        {messages.length === 0 ? (
          <p className="empty">
            マイクをオンにして、工場の故障について話しかけてください。
            <br />
            例:「ポンプAが過熱したときの対策は？」／「新しい故障ケースを登録したい」
          </p>
        ) : (
          messages.map((m) => {
            const text = m.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
            return (
              <div key={m.id} className={`row ${m.role}`}>
                <div>
                  <div className="who">{m.role === "user" ? "あなた" : "エージェント"}</div>
                  <div className="bubble">{text}</div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="controls">
        <button
          className={`mic ${connected ? "live" : ""}`}
          onClick={onClick}
          disabled={busy}
        >
          {connected ? "■ 切断する" : "● 会話をはじめる"}
        </button>
        <span className="status">
          <span className={dotClass} />
          {status}
        </span>
      </div>

      <audio ref={audioRef} autoPlay hidden />
    </main>
  );
}
