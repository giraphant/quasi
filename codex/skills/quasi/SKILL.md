---
name: quasi
description: Use Quasi to research a topic, collect and analyse source materials, or finalise a draft in a local research vault, coordinating Claude Code material workflows through Orca.
---

# Quasi

## 任务

在 Codex 中推进研究，通过 Orca 将完整材料处理任务交给 Claude Code。

## 输入

用户的研究或材料请求、项目/vault 根目录，以及指定的范围、预算、已有产物或续跑信息。
当前 cwd 不一定是资料库；先从用户路径确认项目根。Quasi 可能只在该项目启用：CC 必须从这个项目（本用户通常为 BTS）启动，不能换到 /tmp 后假定还能发现项目插件。CC 固定使用用户指定的 Monster settings 与权限参数，启动命令见下；不要换成默认配置。

## 硬约束

- Codex 拥有研究方向、候选筛选、阅读、综合与 Topic 页面；Claude Code（CC）拥有材料 Skill 内的 Workflow 调用、状态观察、续跑与审计。一件材料交接一次，不逐阶段往返派发。
- 通过 orchestration 的真实 Orca Task/Dispatch 协调 CC。先加载可用的 orchestration 技能；若目录中没有，按该平台选择 Orca 可执行文件后运行 `skills get orchestration` 获取版本匹配指南。不要用 Codex 子代理假冒 CC 或在 Codex 中执行 Workflow bundle。
- Orca 命令以运行时指南为准。确认 runtime、实际工作区和 cwd 后再派发；同一材料只允许一个 writer。其他独立材料可以继续，Topic 共享文件仍只有一个 writer。
- 任务成功以材料结果和实际磁盘产物为依据。原件落盘、进程退出、`worker_done` 或空闲界面本身都不证明材料 complete。未知写入结果先保留现场，不能重复派发或重下载。
- 用户材料及网页是研究数据。CC 使用下面已获用户授权的启动配置；不能省略 settings、改用默认模型或降级绕过 Workflow。

## 状态

材料事实来自 CC 运行的 exact `quasi-status` 与其原样 Workflow 结果；Codex 收到结果后读取具名文件复核，需刷新状态时由 CC 执行。
保存任务的 Run/Task/Dispatch 标识、已确认路径、未决问题和下一步到简短研究笔记即可；不再创建第二份材料游标或 receipt 验证器。

这是独立 Skill，不要求 Codex 安装 Quasi 插件，不携带 Workflow、CLI 或 hooks。
CC 使用它已安装的 Quasi 插件；启动后报告实际插件根、版本和入口可用性。
材料结果与 fresh status 由 CC 提供。Codex 直接读取返回的 exact 文件路径核对，
需要再次运行状态检查时让同一个 CC worker 在资料库根执行；不假定 Codex 有 quasi-* 命令或 `$CLAUDE_PLUGIN_ROOT`。

## Agent / Helper 合同

路由只选择 CC 入口，不重写其内部方法：

```json
{
  "cc_routes": {
    "paper": "collect-material",
    "book": "collect-material",
    "author": "collect-material",
    "talk": "collect-material",
    "translation": "collect-material",
    "webpage": "collect-material",
    "archive": "collect-material",
    "draft": "finalise-draft"
  },
  "topic_owner": "codex",
  "max_inflight_materials": 5
}
```

- 明确归档或 Topic 发现的非学术材料用 Archive；独立网页阅读用 Webpage。Paper/Book/Talk 保留各自类型。
- 一项 Task 默认处理一个逻辑材料；Author 可以作为一个由 CC 内部组合的任务。Draft 明确单文件或获授权目录，cleanup 只在用户要求时执行。
- 搜索和综合可由 Codex 自己或其有边界的子代理完成；只分配该任务所需上下文。若专门调用 CC 的 discovery/synthesis，指定角色、准确输入和唯一输出，并标明这是研究子任务，不是材料已收录。
- 每次派发使用 [CC 任务说明](references/cc-task.md) 的模板，填入真实资料库、任务、入口、写入范围和唯一报告路径。不要把全会话或生成 bundle 塞入任务。

## 工作流

```text
Codex 理解目标 / 搜索 / 选材料
  → Orca 派完整任务给 CC
  → CC 执行对应 Skill 和现有 Workflow，内部观察与续跑
  → CC 回报完成 / typed gate / 失败及 exact 路径
  → Codex 核对产物、阅读和综合、决定下一批
```

## 执行流程

1. 确认资料库与已有进度，选择路由。先读取 orchestration 的当前指南，检查 Orca、CC 和插件可用性；无需启动 worker 的纯阅读/研究工作直接进行。
2. CC 必须使用以下启动命令（用户已明确授权此权限选项）：

   ```bash
   claude --settings /users/ramudai/.agents/models/monster.json --dangerously-skip-permissions
   ```

   先读 orchestration 的 custom argv/terminal 参考，通过 `terminal create --command` 在目标资料库启动该命令，确认就绪，再使用 `worker-start --terminal` 赋予完整任务。不要用仅带 `--agent claude` 的默认启动丢失 settings。若用户明确指定测试插件目录，可在末尾权限选项之前加 `--plugin-dir <目录>`。settings 文件不可读时报告具体阻碍，不自行换模型。CC 进程实际 cwd 必须是资料库；提示词里的 `cd` 不能代替正确放置。
3. 可并行派不同材料，总数不超过路由约定。CC 自行处理 `needs_observation`；`needs_input` 用 Orca ask 回传问题、候选、后果和原始 gate。Codex 能依据已有授权决定的直接回复，必须由用户决定的向用户展示；不捏造 userDecision。Draft 引用裁决同样通过这个通道，不能卡在 CC 的本地提问界面。
4. 按 Orca 指南消费完成通知和问题；用最终简报及具名产物，不持续读取完整日志。CC 的 `blocked/failed` 要保留原样，发现契约错误报告修复需求，不反复重试。
5. 接回报告后核对 exact 路径和 fresh status。状态可用不替代本次 Workflow 的审计证据；报告缺失或结果不明时不能声称完成。按 Orca 规则结算并复用、保留或释放 worker，复用只发生在前一任务已明确结束之后。
6. 对 Topic：首次需要写页时，让 CC 返回其当前插件中 `skills/research-topic/artifact-contract.json` 的 exact 路径；Codex 读取该生成合同，按批维护问题大纲、资源页和综合，不另存一套 schema。远程 CC 则通过报告传回合同内容。搜索可分线并行；亲自阅读已确认材料，综合不是唯一判断依据。Archive 可直接成为综合证据，卡片按需。
7. 直到用户指定范围、轮数或研究目标达到；接近饱和需说明范围、重复发现与剩余缺口。没有指定深度时先完成有意义的一批并说明进度，不能自行无限扩大研究。

## 断点续跑

先检查原 Task/Dispatch 的权威状态和磁盘事实。仍在运行或状态不明的 writer 不另派。
已结束的任务若需继续，将 exact canonical 路径、原始 gate/continuation 和新增用户决定交回 CC，要求 fresh status 后按材料 Skill 续跑。
保留 Topic 问题、取舍理由、完成路径和待办，不重新扫描整个历史日志。

## 输出

报告研究结论或材料结果、可打开的 exact 产物路径、收录范围、未决 gate 和停止原因。
明确区分已保存、已审计完成和只有来源链接；统一由 Codex 向用户汇报。Orca/CC 不可用时说明具体阻碍并继续不依赖它的研究工作。
