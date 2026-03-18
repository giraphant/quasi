# Harness Engineering — learn-claude-code 要点

> Source: github.com/shareAI-lab/learn-claude-code
> Context: 12 节渐进式教程，从零构建 agent harness，理解 Claude Code 底层原理

## 核心哲学

> "Agent 是模型本身，不是代码。代码是 harness（驾驶舱），不是 agent。"

Harness = Tools + Knowledge + Context + Permissions

## 12 层渐进架构

| 层级 | 能力 | 解决的问题 |
|------|------|-----------|
| s01-02 | 循环 + 工具分发 | 模型能行动 |
| s03 | TodoWrite 计划 | 多步任务不丢方向 |
| s04 | 子 agent（上下文隔离）| 防止 context 污染 |
| s05 | Skill 加载（两层设计）| 按需知识注入 |
| s06 | 上下文压缩（三层）| 无限会话 |
| s07 | 持久任务系统 | 断点续跑 |
| s08 | 后台任务 | 非阻塞执行 |
| s09 | Agent 团队（JSONL 邮箱）| 多 agent 通信 |
| s10 | 团队协议（request-response FSM）| 结构化握手 |
| s11 | 自主认领（idle poll + task board）| 自组织 |
| s12 | Worktree 隔离 | 并行执行不碰撞 |

## 关键设计模式

### s04: 子 agent 上下文隔离

- 子 agent 以 `messages=[]` 启动，跑完只返回摘要文本
- 整个消息历史丢弃，不污染父 agent
- 子 agent 不能再 spawn 子 agent（禁止递归）

### s05: Skill 两层加载

- Layer 1（System Prompt）：skill 名称 + 简短描述（~100 tokens/skill）
- Layer 2（Tool Result）：`load_skill()` 按需注入完整内容（~2000 tokens）
- 避免 10 skill × 2000 token = 20000 token 的前置浪费

### s06: 三层上下文压缩

1. **Micro-compact**（每轮）：3 轮前的 tool_result 替换为 `[Previous: used {tool_name}]`
2. **Auto-compact**（token 超阈值）：保存 transcript 到磁盘，LLM 摘要替换全部 messages
3. **Manual compact**：模型主动调用 compact 工具

### s09: 团队通信 — JSONL 邮箱

- `.team/config.json`：团队名册（name/role/status）
- `.team/inbox/{name}.jsonl`：append-only 邮箱，read 时 drain
- 每个 teammate 是独立 agent loop（线程），每次 LLM 调用前先 drain inbox
- 持久化仅限单会话（daemon thread，主进程退出即销毁）

### s10: 协议 — 统一 FSM

所有协议共用一个模式：`pending → approved | rejected`，用 request_id 关联：
- **Shutdown Protocol**：Lead request → Teammate approve/reject
- **Plan Approval**：Teammate submit → Lead approve/reject

### s11: 自主认领

```
WORK → 没活了 → IDLE（每 5s 轮询）
  ├→ inbox 有消息 → 回到 WORK
  ├→ .tasks/ 有未认领任务 → claim → 回到 WORK
  └→ 60s 没活 → SHUTDOWN
```

- `claim_task()` 用 lock 防止竞态
- 身份重注入：context 被压缩后在开头插入 `<identity>` 块

### s12: Worktree 隔离

- 控制平面（.tasks/）+ 执行平面（.worktrees/）
- 任务和 worktree 双向绑定（task_id ↔ worktree name）
- 事件流：`.worktrees/events.jsonl`

## 5 个 Harness 工程原则

1. **Trust the model** — 不要用 if-else 替模型做决策
2. **Constraints enable** — 约束是聚焦不是限制
3. **Progressive complexity** — 从最简单开始，用了才加
4. **Context is precious** — 隔离噪音、压缩历史、持久化目标
5. **Iteration reveals** — 从实际使用中发现需求

## 反模式

| 模式 | 问题 | 解法 |
|------|------|------|
| 过度工程 | 需求没到就建 | 从最低层级开始 |
| 工具太多 | 模型混淆 | 3-5 个起步 |
| 死板工作流 | 无法适应 | 让模型决定 |
| 前置加载知识 | Context 膨胀 | 按需加载 |
| 微观管理 | 削弱智能 | 信任模型 |

## 对 Claude Code 的映射

| 教学实现 | Claude Code 实际对应 |
|---|---|
| Python threading.Thread | `Agent()` tool (background) |
| `.tasks/task_*.json` | 文件系统 task board |
| `BUS.read_inbox()` | Agent 完成通知 |
| `run_subagent()` | `Agent(run_in_background=True)` |
| 多 CLI 实例 + 共享文件 | 真蜂群模式 |

## 对 quasi 的适用性评估（2026-03-18）

- **已在用**：s04 子 agent 隔离、s05 skill 加载、s08 后台 agent + Glob 轮询
- **不需要**：s09-s11 团队/蜂群（quasi 的并行分析是 embarrassingly parallel，无需 agent 间通信）
- **可借鉴**：s06 micro-compact 思路（减少 dispatcher context 中的轮询垃圾）
- **未来可能需要**：真蜂群模式（如果任务间出现复杂动态依赖）
