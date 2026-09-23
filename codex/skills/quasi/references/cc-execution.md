# CC 执行参考

仅在需要材料处理、draft 校对、材料续跑或首次获取 Topic 格式合同时读取。研究工作由主 Skill 指导。
Codex 只安装独立 Skill；CC 使用它已安装的完整 Quasi 插件，拥有材料内部的 Workflow、观察、续跑与审计。

## 启动与放置

先加载可用的 orchestration 技能及其版本匹配运行时指南，按指南确认 Orca runtime。
使用真实 Orca Task/Dispatch 协调 CC；不要用 Codex 子代理替代 CC 或在 Codex 解释执行 Workflow bundle。

CC 必须从实际安装并启用 Quasi 的资料库启动，本用户通常为 `/Users/ramudai/Documents/Learn/bts`。
当前 cwd 不一定是资料库，临时目录也不自动继承项目插件；提示词里的 `cd` 不能代替正确的进程放置。
固定使用用户明确授权的启动命令：

```bash
claude --settings /users/ramudai/.agents/models/monster.json --dangerously-skip-permissions
```

读取 orchestration 的 custom argv/terminal 参考，通过 `terminal create --command` 在目标项目启动，确认就绪，再用 `worker-start --terminal` 派任务。
不要用仅带 `--agent claude` 的默认启动丢失 settings。settings 不可读时报告具体阻碍，不自行换模型。
只有用户明确指定测试插件目录时，才在末尾权限选项前添加 `--plugin-dir <目录>`。
首次启动确认实际插件根、版本和 Skill/Workflow 可用性；同一 worker 中已确认的环境无需每件重新调查。

## 材料路由

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

明确归档或 Topic 发现的非学术材料用 Archive；独立网页阅读用 Webpage。Paper/Book/Talk 保留各自类型。
一项 Task 默认处理一个逻辑材料；Author 可由 CC 内部组合。Draft 明确单文件或获授权目录，cleanup 只在用户要求时执行。
使用 [CC 任务说明](cc-task.md) 填入本次研究问题、材料、资料库、入口、写入范围和唯一报告路径。
不同材料最多五件并发，同一 URL 或已知 canonical owner 只有一个 writer；这个上限不规定每轮收录数量。

## 结果与问题

让 CC 自行处理 Skill 内部的 `needs_observation`，材料整体完成后才交回主代理。
`needs_input` 通过 Orca ask 回传原样 gate、候选和后果；Codex 能依据已有授权决定的直接回复，必须由用户决定的向用户展示，不捏造 userDecision。Draft 引用裁决使用同一通道。
单件受阻时保留问题并继续独立研究，不把它扩成整个 Topic 的停止条件。

正常验收读取 CC 报告里的最终材料结果与 fresh exact status，确认具名产物与本次任务对应，再阅读其中的研究内容。
Workflow 的审计结论由 CC 负责。没有具体矛盾时不重跑审计、不打开 specialist transcript、不比较文件哈希，也不反复轮询状态。
报告与产物矛盾或材料结果缺失时，只调查该具体问题；原件已保存、worker_done 或进程退出本身不能证明材料 complete。
不创建第二份材料游标或 receipt 验证器；需刷新 exact status 时让 CC 在资料库执行，不假定 Codex 有 quasi-* 命令或 `$CLAUDE_PLUGIN_ROOT`。

按 Orca 指南接收问题和完成通知，核对后结算并复用、保留或释放 worker。
复用只在前一任务明确结束后进行；未知 writer 结果不重复派发。CC 的 blocked/failed 保留原样，不自动重放。
已结束材料的续跑交回 exact canonical 路径、原始 gate/continuation 和新增用户决定，由 CC fresh status 后继续。

## Topic 格式

首次需要写 Topic 页时，让 CC 返回其当前插件的 `skills/research-topic/artifact-contract.json` exact 路径，读取该生成合同；已取得且插件版本未变时直接复用。
可以随首个材料任务一并返回。远程 CC 通过报告传回合同内容与可读取的材料，不把远程路径当本地文件。
主代理按合同维护现有三页，札记放在已有正文中，不增加 notes 类型、强制卡片或逐材料 Topic 审计。
