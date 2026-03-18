# Lessons from Building Claude Code: How We Use Skills

> Source: Thariq (@trq212), Anthropic — 2026-03-17
> Context: Anthropic 内部数百个 skill 的实战经验总结

## 9 类 Skill 分类

1. **Library & API Reference** — 内部库用法 + gotchas
2. **Product Verification** — 配合 playwright/tmux 做验证
3. **Data Fetching & Analysis** — 连接监控/数据栈
4. **Business Process & Team Automation** — 日报、ticket 创建等重复流程
5. **Code Scaffolding & Templates** — 项目模板生成
6. **Code Quality & Review** — 代码审查、风格检查
7. **CI/CD & Deployment** — PR 看护、部署、cherry-pick
8. **Runbooks** — 症状 → 调查 → 报告
9. **Infrastructure Operations** — 清理孤儿资源、依赖管理

## 核心原则

### Don't State the Obvious

Claude 已经知道的不用写。Skill 应该聚焦于推动 Claude 脱离默认行为的信息。

### Gotchas 段是最高价值内容

从实际失败中积累，持续更新。这是 skill 中最重要的段落。

### 用文件系统做渐进披露（Progressive Disclosure）

Skill 是文件夹，不只是 markdown 文件。`references/`、`scripts/`、`assets/`、`templates/` — 告诉模型它们存在，按需读取。

**适用场景判断**：
- 主进程/dispatcher 加载 skill → 适合渐进披露（context 需要保持干净）
- 子 agent 执行指令 → 不适合（核心指令必须内嵌，多一次 Read = 多一个不遵循的风险点）

### 不要 Railroad（过度规定步骤）

给信息但留灵活性。别把每一步都写死。对执行 agent 尤其重要——信任模型的推理能力。

### Description 是给模型看的触发条件

不是功能摘要，是"什么时候该调用我"。Claude 在会话开始时扫描 description 来决定是否调用 skill。

示例：
- 差：`Perform thorough code reviews`
- 好：`Use when user asks to review code, check for bugs, or audit a codebase`

### Setup 用 config.json

需要用户输入的配置存在 skill 目录的 config.json 里。用 AskUserQuestion 做结构化交互。

### Memory 用 `${CLAUDE_PLUGIN_DATA}`

存日志/历史数据到 stable folder，升级不丢。

### 给 Claude 脚本和库

让 Claude 花时间在组合上而非重写样板代码。Skill 文件夹里放 helper 函数库，Claude 按需 import 和执行。

### On-demand Hooks

Skill 启动时注册钩子，会话级生效。适用于偶尔需要的严格约束（如 `/careful` 阻止危险操作）。

### 衡量 Skill 使用率

用 PreToolUse hook 做日志，发现触发不足或过度触发的 skill。

## 分发模式

- **小团队/少 repo**：直接 check in 到 `.claude/skills/`
- **规模化**：内部 plugin marketplace，有机发现 + traction 后入库
- **合成 skill**：可以 by name 引用其他 skill，模型会自动调用（如果已安装）
