# Codex 统一入口

Codex 只安装独立 `quasi` Skill，依赖可用的 Orca orchestration。Quasi 完整插件继续安装在 Claude Code；Codex 不安装 Quasi 插件，不加载它的 hooks 或 Workflow。

## 安装

将仓库 `codex/skills/quasi/` 复制到 Codex 的技能目录（默认 `~/.codex/skills/quasi/`）。它只包含 SKILL.md 与 CC 任务模板，不依赖仓库相对路径。

已有旧版安装时，先用 `codex plugin list --json` 核对准确的 Quasi pluginId，再用 `codex plugin remove <pluginId>` 移除。旧版本可能登记在不同 marketplace 下，移除后再次核对安装列表；不要移除其他插件或 Claude 的安装。

卸载含 hooks 的旧插件后，已经打开的会话可能仍引用旧缓存。新线程是切换边界；不要在旧会话里通过删除或跳过 hook 来继续执行。安装后检查新会话的技能发现列表，只应出现一个独立 `quasi` 入口，不能再有旧的 Quasi 子技能。

依赖：本机可用的 Orca、Claude Code、CC 中启用且支持 Workflow 的 Quasi 插件。CC 启动固定使用用户指定命令 `claude --settings /users/ramudai/.agents/models/monster.json --dangerously-skip-permissions`。这是用户明确要求的运行配置；不复制文件内容或凭据。Orca 通过自定义命令创建 CC 后，用 worker-start --terminal 管理任务生命周期。

## 职责与交接

Codex 拥有研究、搜索分工、候选取舍、阅读与综合、Topic 共享文件。CC 按一件完整材料执行 `collect-material`，或对明确 draft 执行 `finalise-draft`。一项材料内部的 Workflow、观察和审计不回传给 Codex 逐阶段驱动。

CC 通过真实 Orca Task/Dispatch 回报精简报告、原样材料 terminal 和 exact 产物。Codex 核对文件与最终状态，继续研究。`needs_input` 和引用裁决通过 Orca ask/reply 传到 Codex，不在后台 CC 的本地提问界面等待用户。普通直接使用 Claude Skill 的提问方式保持不变。

Topic 格式从 CC 当前插件的生成合同读取，不在独立 Skill 中复制 schema。跨主机时由 CC 在报告中提供合同内容与可供主代理读取的材料，不能把远程路径当成本地文件。

## 验收

1. 新 Codex 会话只发现一个独立 Quasi Skill，没有 Quasi 插件 hooks。
2. 从实际安装并启用 Quasi 的资料库（本用户为 BTS）启动 CC，派一个已有 Archive 的续跑任务，经 Orca 进入真实 Workflow 完成审计，回报 exact 状态；不重新下载原件。隔离目录必须另行具备插件环境，不能假定继承项目安装。
3. Codex 接回结果，核对产物并结算 worker；未知写入状态不能成为重复采集的授权。
4. 校对任务的人工 gate 使用同一 ask/reply 通道，不能将尚未裁决的任务报告成功。

本适配不实现 Codex Workflow 解释器，不维护第二套材料回执或校验器。

2026-09-23 的 [BTS 实测记录](evals/codex-cc-handoff.md) 验证了已有 Archive 的真实审计与完整交接。人工 gate 和其他材料类型没有在这次测试中覆盖。
