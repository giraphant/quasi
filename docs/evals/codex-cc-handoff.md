# Codex → Orca → Claude Code handoff

2026-09-23，在 BTS 中验证独立 Codex Skill 的材料委派路径。Codex 使用新入口，CC 使用 BTS 已安装的 Quasi **0.66.8**；没有将测试冒充为 CC 0.67.0 的全类型验收。

## 环境与任务

- cwd：`/Users/ramudai/Documents/Learn/bts`，Quasi 在此项目启用。
- 启动命令：`claude --settings /users/ramudai/.agents/models/monster.json --dangerously-skip-permissions`。
- 通过 Orca 自定义 terminal 启动，再以 `worker-start --terminal` 接管一个完整任务。
- 材料：`archive:visorcentral-emergency-charger`（R086 Emergency Charger）。只续跑已有材料的审计，不补采。
- Run：`run_c1cd600548d4`；Task：`task_7ba15deb2de0`；Dispatch：`ctx_2562a7158208`。

## 结果与证据

CC 成功加载 `quasi:collect-material`，执行初始 exact status，以 canonical seed 调用已安装的 `workflows/archive.mjs`，在完成后再次执行 exact status。主代理没有逐阶段派发，也没有解释执行 Workflow。

Workflow `wf_4d93d64d-687` 的 journal 记录了一次 `archive.audit`：specialist `a2cd9cc24037310fa` 实际执行 `quasi-audit --path vault/archives/visorcentral-emergency-charger/archive.md`，诊断返回 `clean`、零违规、零修改；Stage terminal 为 complete，最终 `quasi.material.result/0.1` 为 `complete`、`issue:null`、`next:null`。最后返回的档案页、manifest、三个 source refs 均在 fresh status 中 present/usable。

Codex 独立比较测试前后的 SHA-256：Archive 目录五个文件全部未变，没有增加原件。CC 仅新增 `.quasi/temp/codex-handoff-bts-report.md`。Orca 收到 succeeded 的 worker_done，协调者核对后执行 release 并确认消息；由于这是预先创建的 terminal，Orca 以 `external_terminal` 保留它，没有继续派发任务。

本机证据：

- CC 报告：`/Users/ramudai/Documents/Learn/bts/.quasi/temp/codex-handoff-bts-report.md`。
- Workflow journal 和 specialist transcript：`/Users/ramudai/.claude/projects/-Users-ramudai-Documents-Learn-bts/8cf7aa46-2fad-4650-83c7-721657ff73e7/subagents/workflows/wf_4d93d64d-687/`。

## 覆盖范围

这次证明的是已有 Archive 的真实审计与端到端委派。没有测试新的网络采集、其他材料类型、Topic 多轮研究或人工 ask/reply gate；没有扩展批量采集。

更早的一次隔离目录测试没有加载到项目 Quasi Skill，未进入 Workflow，之后由用户关闭，Orca 记录为 failed/operator_close。这项失败不计为验收通过。入口现要求 CC 从实际启用 Quasi 的资料库启动，不能假定临时目录继承项目安装。
