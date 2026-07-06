"use client";

// /v0 — 旧アプリを React に移植したもの。挙動・見た目はほぼ従来どおり(素朴なログ)。
// WebRTC の中身は lib/realtime.ts を共有して使う。

import { useRef, useState } from "react";
import Link from "next/link";
import { connectRealtime, type RealtimeHandle } from "@/lib/realtime";

type Bubble = { id: string; role: "user" | "assistant"; text: string };

export default function V0Page() {
  const [status, setStatus] = useState("未接続");
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const handleRef = useRef<RealtimeHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  function add(role: "user" | "assistant", text: string) {
    if (!text) return;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random()}`, role, text },
    ]);
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
        onUserTranscript: (t) => add("user", t),
        onAssistantTranscript: (t) => add("assistant", t),
      });
      setConnected(true);
    } catch (e) {
      setStatus(`接続に失敗しました: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell v0">
      <div className="topbar">
        <span className="title">Voice Agent — v0</span>
        <nav className="nav">
          <Link href="/v0" className="active">v0</Link>
          <Link href="/v1">v1</Link>
        </nav>
      </div>

      <div className="log">
        {messages.length === 0 ? (
          <p className="empty">「会話をはじめる」を押してマイクを許可し、話しかけてください。</p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`row ${m.role}`}>
              <div className="bubble">{m.text}</div>
            </div>
          ))
        )}
      </div>

      <div className="controls">
        <button
          className={`mic ${connected ? "live" : ""}`}
          onClick={onClick}
          disabled={busy}
        >
          {connected ? "切断する" : "会話をはじめる"}
        </button>
        <span className="status">{status}</span>
      </div>

      <audio ref={audioRef} autoPlay hidden />
    </main>
  );
}
