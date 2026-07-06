import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Voice Agent",
  description: "OpenAI Realtime × LangGraph Supervisor voice agent",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: ブラウザ拡張機能が <html>/<body> に属性を差し込むと
    // サーバー生成HTMLと食い違い hydration 警告が出る。これはこちらのコードの不具合では
    // ないため、この1階層だけ警告を抑止する(拡張なしの環境なら元々出ない)。
    <html lang="ja" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
