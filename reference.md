結論：音声はRealtime、頭脳はLangGraphに分離し、Realtimeから窓口ツール1つでSupervisorを呼ぶ構成。

```
[ユーザー音声]
   ↓
[OpenAI Realtime]  ← 音声入出力・意図判定のみ
   ↓ function calling（ask_backend 1つだけ）
[LangGraph Supervisor]  ← 司令塔（振り分け専任）
   ├─→ [Task Agent A ＋ tools]
   └─→ [Task Agent B ＋ tools]

```

役割分担：

* **Realtime**：音声↔テキスト変換と読み上げ。判断ロジックは持たない。
* **Supervisor**：意図を見て2つのタスクエージェントに振り分け、結果を要約して返す。自分では実処理しない。
* **Task Agent A / B**：各自のtoolsを使って実タスクを実行。

設計上の要点：

* Realtimeに渡すツールは`ask_backend`の1つだけ（振り分けの二重化を防ぐ）
* Supervisor実行は非同期化し、待機中は「確認中です」と音声を返す
* 返り値は`messages`の最後の`.content`だけをRealtimeへ渡す
