# Permissions Agent Design

## Problem

quasi 插件迁移到新项目时，需要手动配置 `.claude/settings.local.json` 中的工具权限。这个过程容易遗漏、出错，也没有清理旧权限的机制。

## Solution

新建 `agents/permissions-agent.md`，一个独立的权限配置 agent。

## Core Behavior

1. **读取** 目标项目的 `.claude/settings.local.json`（不存在则视为空；如果文件存在但 JSON 格式损坏，终止并报错）
2. **比对** 当前权限与 quasi 所需权限（字符串精确匹配，不做模糊/相似度判断）
3. **智能合并** — 添加缺失的权限，保留项目自身的非 quasi 权限
4. **清理** — 移除 quasi 不再需要的旧权限条目
5. **写回** 更新后的 `settings.local.json`（2-space indent，保留文件中 `permissions` 以外的其他顶层 key 如 `env`、`mcpServers` 等不动）

运行应当是幂等的：连续执行两次，第二次不产生任何变更。

## Required Permissions (Hardcoded)

Agent 内硬编码两个列表：

### 当前需要的权限 (`required`)

```json
[
  "Read(/private/tmp/**)",
  "Bash(git add:*)",
  "Bash(git mv:*)",
  "Bash(git rm:*)",
  "Bash(git commit:*)",
  "Bash(git push:*)",
  "Bash(git pull:*)",
  "Bash(git rebase:*)",
  "Bash(git fetch:*)",
  "Bash(git revert:*)",
  "Bash(find:*)",
  "Bash(ls:*)",
  "Bash(cat:*)",
  "WebSearch"
]
```

### 曾经需要但已废弃的权限 (`deprecated`)

```json
[]
```

v1 启动时 deprecated 为空，后续有权限被移除时挪到这里。

**判断逻辑**：
- 权限在 `required` 中 → 确保存在
- 权限在 `deprecated` 中 → 删除
- 权限不在两个列表中 → 项目自有，不动

注意：`Read(/Users/ramudai/Documents/Vibe/**)` 等用户个人路径不属于 quasi 通用权限，agent 不应管理此类条目。

## Agent Specification

- **File**: `agents/permissions-agent.md`
- **Model**: sonnet（轻量任务，不需要 opus）
- **Tools**: Read, Write, Glob
- **Trigger**: 用户手动 dispatch，非自动

## Agent Logic (Pseudocode)

```
1. Read .claude/settings.local.json
   - File missing → start with {"permissions": {"allow": []}}
   - File exists but invalid JSON → ABORT with error message
2. Parse existing permissions.allow array
3. For each entry in `required`:
   - If not present in allow array → add it
4. For each entry in allow array:
   - If it matches an entry in `deprecated` → remove it
   - Otherwise → keep it (either current quasi permission or project-owned)
5. Write back the full settings.local.json
   - 2-space JSON indent
   - Preserve all non-permissions keys untouched
```

## Maintenance

每次 quasi 的 agent/skill 变更导致权限需求变化时：
1. 更新 `permissions-agent.md` 中的 `required` 列表
2. 被移除的权限挪到 `deprecated` 列表
3. 纳入 context.md 更新流程

## Out of Scope

- 不管理凭证/API key（`config/` 目录）
- 不管理用户个人路径权限
- 不管理 `permissions.deny` 或其他非 allow 配置
- 不自动触发，不做 hook
- 不做 skill 包装
- 不做跨平台路径适配（当前仅 macOS）
