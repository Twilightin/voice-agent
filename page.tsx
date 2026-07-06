// mode 3: 实时
// 这里只保留 mode 3-c：Realtime native function tool only（get_weather）。
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";

type Bubble = { id: string; role: "user" | "assistant"; content: string };

export default function Mode3RealtimePage() {
  // mode 3-c 专用变量：Realtime 会话、消息、WebRTC 和音频播放。
  const [rtStatus, setRtStatus] = useState<"idle" | "connecting" | "live">("idle");
  const [rtMessages, setRtMessages] = useState<Bubble[]>([]);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // mode 3-c 专用函数：追加 Realtime 转写气泡。
  function addRt(role: "user" | "assistant", content: string) {
    if (!content) return;
    setRtMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random()}`, role, content },
    ]);
  }

  // mode 3-c 专用函数：本地执行 get_weather 原生 Realtime function tool。
  function getWeather(location: string) {
    const place = location.trim() || "your area";
    return {
      location: place,
      summary: `${place} is mild and partly cloudy right now.`,
      temperature_c: 22,
      note: "Demo weather from the local get_weather tool.",
    };
  }

  // mode 3-c 专用函数：处理 Realtime 事件，只响应 get_weather 工具调用。
  async function handleRealtimeEvent(ev: any) {
    if (ev.type === "conversation.item.input_audio_transcription.completed") {
      addRt("user", ev.transcript || "");
    } else if (ev.type === "response.output_audio_transcript.done") {
      addRt("assistant", ev.transcript || "");
    } else if (ev.type === "response.function_call_arguments.done" && ev.name === "get_weather") {
      let location = "";
      try {
        location = JSON.parse(ev.arguments || "{}").location || "";
      } catch {
        /* 参数解析失败就当空 */
      }

      dcRef.current?.send(
        JSON.stringify({
          type: "conversation.item.create",
          item: {
            type: "function_call_output",
            call_id: ev.call_id,
            output: JSON.stringify(getWeather(location)),
          },
        })
      );
      dcRef.current?.send(JSON.stringify({ type: "response.create" }));
    }
  }

  // mode 3-c 专用函数：向后端请求只带 get_weather 的 Realtime 临时会话。
  async function connectRealtime() {
    setRtStatus("connecting");
    try {
      const sess = await fetch(`${API_BASE}/realtime/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approach: "3-c" }),
      }).then((r) => r.json());
      const EPHEMERAL: string = sess.value;
      const model: string = sess.session?.model || "gpt-realtime";

      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      pc.ontrack = (e) => {
        if (remoteAudioRef.current) remoteAudioRef.current.srcObject = e.streams[0];
      };

      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = mic;
      mic.getTracks().forEach((t) => pc.addTrack(t, mic));

      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;
      dc.onmessage = (e) => handleRealtimeEvent(JSON.parse(e.data));

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const sdpRes = await fetch(`https://api.openai.com/v1/realtime/calls?model=${model}`, {
        method: "POST",
        body: offer.sdp,
        headers: { Authorization: `Bearer ${EPHEMERAL}`, "Content-Type": "application/sdp" },
      });
      await pc.setRemoteDescription({ type: "answer", sdp: await sdpRes.text() });

      setRtStatus("live");
    } catch (err) {
      console.error("realtime connect failed", err);
      setRtStatus("idle");
    }
  }

  // mode 3-c 专用函数：结束 Realtime 通话并释放麦克风。
  function disconnectRealtime() {
    dcRef.current?.close();
    pcRef.current?.close();
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    dcRef.current = null;
    pcRef.current = null;
    micStreamRef.current = null;
    setRtStatus("idle");
  }

  // mode 3-c 专用函数：消息变化后滚动到底部。
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [rtMessages]);

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem" }}>
      <Header title="mode 3: 实时 / 3-c get_weather" />
      <audio ref={remoteAudioRef} autoPlay />

      <div
        style={{
          height: 420,
          overflowY: "auto",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          padding: "1rem",
          marginBottom: "1rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.5rem",
        }}
      >
        {rtMessages.map((m) => (
          <div
            key={m.id}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              background: m.role === "user" ? "#2563eb" : "#f3f4f6",
              color: m.role === "user" ? "#fff" : "#111",
              padding: "0.5rem 0.75rem",
              borderRadius: 8,
              maxWidth: "75%",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {m.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <button
          onClick={rtStatus === "idle" ? connectRealtime : disconnectRealtime}
          disabled={rtStatus === "connecting"}
          style={{
            padding: "0.75rem 1.5rem",
            background: rtStatus === "live" ? "#dc2626" : "#16a34a",
            color: "#fff",
            border: "none",
            borderRadius: 9999,
            fontSize: "1rem",
            cursor: rtStatus === "connecting" ? "not-allowed" : "pointer",
            opacity: rtStatus === "connecting" ? 0.6 : 1,
          }}
        >
          {rtStatus === "live" ? "结束通话" : rtStatus === "connecting" ? "连接中..." : "开始实时对话"}
        </button>
        <span style={{ color: "#6b7280", fontSize: "0.875rem" }}>
          {rtStatus === "live" ? "已连接，试着问天气" : "只启用 Realtime 原生 get_weather 工具"}
        </span>
      </div>
    </main>
  );
}

function Header({ title }: { title: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600 }}>{title}</h1>
      <Link href="/" style={{ color: "#2563eb", fontSize: "0.875rem", textDecoration: "none" }}>
        Back
      </Link>
    </div>
  );
}
