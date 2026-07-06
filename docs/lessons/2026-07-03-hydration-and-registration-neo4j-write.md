# 语音 agent /v1 测试中的两个错误及修复

**日期：** 2026-07-03

在把前端迁移到 Next.js（`/v1` 使用 `useChat`）并加入用户语音转写后，实机测试暴露了两个问题。
记录现象、根因与修复，供日后遇到类似情况快速定位。

---

## 错误 1：打开应用报 hydration 不匹配

### 问题现象

打开 `/v1` 时控制台报错：

```
A tree hydrated but some attributes of the server rendered HTML didn't match the client properties.
<html
  lang="ja"
-  crosspilot-bridged=""
-  crosspilot=""
>
at ... chrome-extension://migomhggnppjdijnfkiimcpjgnhmnale/js/content/sandbox-content.js
```

### 为什么这是问题

**不是代码 bug。** 报错里被标红的属性 `crosspilot-bridged` / `crosspilot` 由浏览器扩展
（crosspilot，`chrome-extension://migomhggnppjdijnfkiimcpjgnhmnale`）在 React hydrate 之前注入到
`<html>` 上，导致服务端生成的 HTML 与客户端不一致。报错信息本身也列出了"浏览器扩展修改了 HTML"
这一原因，堆栈直接指向该扩展。

### 修复方案

在 `frontend/app/layout.tsx` 的 `<html>` / `<body>` 上加 `suppressHydrationWarning`：

```tsx
<html lang="ja" suppressHydrationWarning>
  <body suppressHydrationWarning>{children}</body>
</html>
```

### 预防措施

扩展注入属性引起的 hydration 警告，用 `suppressHydrationWarning` 只抑制**当前这一层**；
其他地方真正的 hydration bug（如 `Date.now()`、`Math.random()` 导致的服务端/客户端分支）仍会照常报错。

---

## 错误 2：语音登录不生效，AI 编造进度，Neo4j 无新数据

### 问题现象

登录新故障案例时，AI 会说「登録処理に入ります…完了したらお知らせします」「数分程度お待ちください」
这类话，但 Neo4j 节点数始终不变（仍是 40），既没有真正写入，也没有给出任何登录确认。

### 为什么这是问题（三个原因叠加）

1. **`/ask` 是无状态的**：每次 `ask_backend` 调用都跑
   `supervisor.ainvoke({"messages": [{"role":"user","content": 单句}]})`，是一次**全新、无记忆**的会话。
   而 `registration_agent` 的设计需要跨多轮累积 `equipment/failure/cause/action`，无状态后端根本记不住上一轮。
2. **没有任何一层累积这 4 个字段**：语音模型手里有完整对话但没被要求去收集字段；后端又记不住。
   两边都不保存状态，模型就用**编造**的"正在登录"来填补空缺（这些话后端从未返回过）。
3. **原设计 `registration_agent` 只产出草稿、不写 Neo4j**（draft-only）。所以"节点数不变"在旧设计下其实是符合预期的，
   但与用户"真正登录"的期望不符。

### 修复方案

在**语音层收齐字段 + 后端一次写入**，并新增写工具：

1. 前台语音指令 `FRONTDESK_INSTRUCTIONS`：登录时用语音把
   equipment/failure/cause/action 四项收齐，然后**一次性**传给 `ask_backend`；
   并**明令禁止编造进度/完成**（只转述后端真实返回）。
2. 新增 `register_case` 工具，按 schema 用 `MERGE` 写入 Neo4j：

   ```python
   # Equipment/Cause/Action 按 name 共享；Failure 按 name+equipment 区分
   cypher = (
       "MERGE (e:Equipment {name: $equipment}) "
       "MERGE (f:Failure {name: $failure, equipment: $equipment}) "
       "  ON CREATE SET f.id = randomUUID() "
       "MERGE (c:Cause {name: $cause}) "
       "MERGE (a:Action {name: $action}) "
       "MERGE (e)-[:HAS_FAILURE]->(f) "
       "MERGE (f)-[:CAUSED_BY]->(c) "
       "MERGE (c)-[:RESOLVED_BY]->(a)"
   )
   ```
3. `registration_agent` 同时持有两个工具：缺项时调 `draft_registration_record`（不写），
   四项齐全并确认后调 `register_case`（写入）；其 prompt 明确目标 =
   **凑齐构成一条完整图记录（`Equipment→Failure→Cause→Action`）所需的 4 个节点**。

### 验证结果（TC-2，已实测通过）

语音登录 `ポンプC / 過熱 / 冷却不足 / 冷却系点検`：

- 节点数 **40 → 42**（**+2**）。因为 `ポンプC`（Equipment）和 `過熱(ポンプC)`（Failure，按设备区分）是新增；
  而 `冷却不足`（Cause）/ `冷却系点検`（Action）已存在，被 `MERGE` 复用，不新增。
- 之后用 `qa_agent` 问「ポンプCの過熱の対策は？」能答出 `冷却系点検`，证明确实写进了图并可被读回。
- 若四项全是全新名字（如 `検証用設備Z`），则会 **+4**。

### 预防措施

「语音 → 单个 `ask_backend` → 无状态后端」这套架构**做不了后端多轮追问**：要么在**语音层**把字段收齐后
再单次调用后端（本次采用），要么给后端加**线程记忆**（LangGraph checkpointer + thread_id）。
另外，凡是"能写库"的工具都要按图 schema 用 `MERGE`（共享节点按 name，`Failure` 按 name+equipment），避免重复节点。
