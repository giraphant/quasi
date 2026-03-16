# Permissions Agent Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a permissions-agent that intelligently merges quasi's required Claude Code permissions into any project's `settings.local.json`.

**Architecture:** Single agent file (`agents/permissions-agent.md`) with hardcoded `required` and `deprecated` permission lists. Agent reads target settings, adds missing required permissions, removes deprecated ones, preserves everything else, writes back.

**Tech Stack:** Claude Code agent (markdown), no scripts needed — the agent uses Read/Write tools directly on JSON.

---

## Chunk 1: Implementation

### Task 1: Create the permissions agent

**Files:**
- Create: `agents/permissions-agent.md`

- [ ] **Step 1: Write the agent file**

```markdown
---
name: permissions-agent
description: 权限配置代理：读取 .claude/settings.local.json，合并 quasi 所需权限，清理废弃权限。幂等运行。
tools: Read, Write, Glob
model: sonnet
---

你是权限配置代理。管理 `.claude/settings.local.json` 中 quasi 插件所需的工具权限。

## 输入参数（调用方在 prompt 中提供）

- `project_dir`: 目标项目根目录（即 `.claude/` 所在目录）

## 权限清单

### 当前需要 (`required`)

- `Read(/private/tmp/**)`
- `Bash(git add:*)`
- `Bash(git mv:*)`
- `Bash(git rm:*)`
- `Bash(git commit:*)`
- `Bash(git push:*)`
- `Bash(git pull:*)`
- `Bash(git rebase:*)`
- `Bash(git fetch:*)`
- `Bash(git revert:*)`
- `Bash(find:*)`
- `Bash(ls:*)`
- `Bash(cat:*)`
- `WebSearch`

### 已废弃 (`deprecated`)

（v1 为空，后续权限被移除时挪到这里）

## 执行流程

1. **读取** `{project_dir}/.claude/settings.local.json`
   - 文件不存在 → 以 `{"permissions": {"allow": []}}` 起步
   - 文件存在但 JSON 无效 → **终止**，报错："settings.local.json JSON 格式损坏，请手动修复"
   - 文件存在但缺少 `permissions` 或 `permissions.allow` key → 初始化为空数组后继续
2. **添加缺失权限** — 遍历 `required` 列表，不在 `permissions.allow` 中的逐条追加（字符串精确匹配）
3. **清理废弃权限** — 遍历 `permissions.allow`，匹配 `deprecated` 列表中的条目则删除
4. **保留其他内容** — `permissions.deny`、`env`、`mcpServers` 等非 `permissions.allow` 的 key 完全不动
5. **写回** `settings.local.json`（2-space indent JSON，末尾换行）
6. **报告变更**

## 输出协议

最后一条消息**必须**包含：

```
PERMISSIONS_RESULT:
- added: [新增的权限列表]
- removed: [清理的权限列表]
- unchanged: N（未动的条目数）
- status: success | error
```

## 注意事项

- 幂等：连续执行两次，第二次 added 和 removed 均为空
- 不管理用户个人路径权限（如 `Read(/Users/.../Vibe/**)`)
- 不管理 `permissions.deny`
- 不做跨平台路径适配
```

- [ ] **Step 2: Verify agent file matches existing agent format**

Run: `head -6 agents/download-agent.md agents/extract-agent.md agents/permissions-agent.md`
Expected: All three have consistent `---` frontmatter with name, description, tools, model fields.

- [ ] **Step 3: Commit**

```bash
git add agents/permissions-agent.md
git commit -m "feat: add permissions-agent for settings.local.json management"
```

### Task 2: Register agent in plugin and update docs

**Files:**
- Modify: `.claude-plugin/plugin.json` (version bump)
- Modify: `CLAUDE.md` (version + release notes)

- [ ] **Step 1: Bump version in plugin.json to 0.4.3**

- [ ] **Step 2: Update CLAUDE.md with release notes**

Add to Recent Major Features:
```
- 0.4.3: Add permissions-agent for automated settings.local.json permission management
```

- [ ] **Step 3: Update context.md if one exists for agents/**

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json CLAUDE.md
git commit -m "chore: bump version to 0.4.3, add permissions-agent release notes"
```

### Task 3: Manual validation

- [ ] **Step 1: Test — dispatch agent on the current project**

Dispatch the permissions-agent with `project_dir` set to the quasi project root. Verify it reads the existing `settings.local.json`, reports all permissions as already present (added: [], removed: []), and does not modify the file.

- [ ] **Step 2: Test — simulate a fresh project**

Create a temp directory with an empty `.claude/settings.local.json` (`{"permissions": {"allow": []}}`). Dispatch the agent. Verify it adds all 14 required permissions.

- [ ] **Step 3: Test — verify non-quasi permissions preserved**

Use the temp directory but add a custom permission like `Bash(docker:*)` to the allow list before running. Verify the agent keeps it.
