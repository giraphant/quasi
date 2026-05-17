---
name: quasi:wrap-up
description: >
  Use when the user says "收尾", "wrap up", "整理这篇", "我写完了帮我过一遍",
  or wants to finalise a draft — proofread typos/punctuation/spacing
  AND verify every citation against vault + online — in one shot.
  ALSO use when user says "审完了", "清理记录块", "删掉校对记录",
  "proofread cleanup", "proofread 收尾" — to remove the
  `<!-- proofread:start -->...<!-- proofread:end -->` block from drafts after review.
---

# Wrap-Up — 文章收尾

一篇 draft 写完后的统一收尾入口。`proofread-agent` 改文字 + `citation-agent` 给引用打 context-fit 标注, 主进程驱动 TUI 走完引用审定, 产出 `decisions.json` + `references.bib`。审完后再触发清理。

## 调用方式

```
/quasi:wrap-up vault/drafts/draft.md
/quasi:wrap-up vault/drafts/                # 整目录

# Flags:
/quasi:wrap-up <draft> --no-recover         # Phase 2.3 跳过(不在线找 missing)
/quasi:wrap-up <draft> --citation-only      # 跳 Phase 0/1, 只跑 Phase 2
/quasi:wrap-up <draft> --audit-first        # 强制跑 Phase 0 (默认按 .quasi/audit/audit-state.json 判断)
```

`--citation-only` 是"补完 vault 后增量重跑"的快捷入口: proofread 已经做过、draft 文本已经定稿、只是 vault 增量补了几本书想重新审引用 + 出 .bib。**直接跳过 Phase 0/1**, 从 Phase 2 进。

## 整体流程

```
┌─ Phase 1  PROOFREAD   ─ sonnet 节内多轮 + codex 提议 + 主进程审稿
├─ Phase 2  CITATION    ─ 解析 + LLM context-fit + 在线 recover + TUI 审定 + emit .bib
│   ├─ 2.1 parse + resolve              (deterministic)
│   ├─ 2.2 citation-agent 批 (single + multi only)  → flag ok/review + picked_slug
│   ├─ 2.3 discover-agent 批 (miss)     → online recovery
│   ├─ 2.4 TUI 审定 (主进程 AskUserQuestion 循环)    ← 新
│   └─ 2.5 write decisions.json + emit references.bib
└─ Phase 3  CLEANUP     ─ 等用户审完触发("审完了" 等)删 proofread 记录块
```

agent 只给一句 context-fit note, **主进程在主上下文里直接 AskUserQuestion 走一遍**, 一边走一边累积 `decisions.by_key` 写盘。

`render.py` 保留为离线诊断工具 (`quasi-helpers citation render`),但 skill 不再调用。

## Flag 解析

主进程从 caller 提供的命令里解析 flag:

```python
draft_path = parse_positional()
flags = parse_flags()  # --no-recover, --citation-only, --audit-first

if flags.citation_only:
    skip_phase_0 = True
    skip_phase_1 = True
    skip_phase_3 = True   # cleanup
elif flags.audit_first:
    skip_phase_0 = False
else:
    skip_phase_0 = audit_state_clean()  # 看 .quasi/audit/audit-state.json
```

## Phase 1 — PROOFREAD

`--citation-only` 时全跳过。

按节切 → sonnet 节内多轮迭代到收敛 → codex 跨模型兜底。**改动直接累积在 draft 末尾的 `<!-- proofread:start -->...<!-- proofread:end -->` 块**。

**Stage A — sonnet 节串行 + 节内多轮迭代**:

1. `quasi-helpers proofread split <draft> -o {pf_dir}/sections.json` — 按 H2/H3 切节
2. `quasi-helpers proofread init <draft>` — 在 draft 末尾创建空记录块(已存在则跳过)
3. 对每节顺序处理(节间串行,避免并发改 draft 末尾块):
   ```
   for sec in sections:
     for r in 1..5:
       Agent("quasi:proofread-agent", prompt 给 draft/section_id/round_tag=s{r}/start_line/end_line)
       本轮 grep `^- \*\*s{r} ` count in draft 末尾块
       == 0 → 该节收敛,跳出
   ```

**Stage B — codex 提议(不改正文)**:

sonnet 全部收敛后,跑 codex 2 轮整篇 draft 作为**提议者**。codex prompt-following 弱常越界, 这里**只提议不改正文** (Stage C 主进程审稿决定接受/拒绝)。

跨 draft 可并发(5 个 codex 同时跑 ok)。对每个 draft 顺序跑 `r = 1..2`。**必须**:
- 用绝对路径 `/opt/homebrew/bin/codex`(绕过 superset shim 的 notify hook 阻塞)
- 重定向 stdin `< /dev/null`(`codex exec` 即使收到 prompt 参数也会等 stdin EOF)

```bash
/opt/homebrew/bin/codex exec --sandbox workspace-write --skip-git-repo-check "$(cat <<'EOF'
你是 draft 校对**提议者**。Read /path/to/draft.md, **不要修改正文**。

发现客观错(typo / punct-en-in-zh / punct-redundant / punct-pairing /
spacing-around-punct / spacing-multiple / grammar-clear)就**提议**。

不提议:用词替换、风格、引用元数据、markdown 结构、半角 /-[]@%、汉字-拉丁/数字间的单空格。

操作:**只 Edit 一处** —— 在 draft 末尾 <!-- proofread:end --> 标记之前追加提议行,
格式以 `? ` 开头标识"待审":

  - **? c{N} L{line}** `{old片段}` → `{new片段}` — {一句话 rationale}

**绝不**修改正文其他位置。完成后不要打印总结。
EOF
)" < /dev/null
```

**Stage C — 主进程审稿**:

对每条 `? c{N}` 提议:
1. Read 提议行的 `{old片段}`,确认仍在正文中(verify codex 没越界)
2. Read 正文 L{line} 周围上下文
3. 判断是否真客观错 / 是否违反"不动"清单
4. **Accept**: Edit 正文 + Edit 记录块删 `? ` 前缀; **Reject**: 删该行

也顺手 review `s{N}` sonnet 行 (应该极少需要反向)。结束后一句话总结。

**硬约束**:
- 主进程**同时**持有正文 + 记录块,审稿单 turn 内一次完成
- 6 篇 draft 串行审

## Phase 2 — CITATION

设 `ct_dir = .quasi/citation/{draft-stem}/`。

### 2.1 — parse + resolve (deterministic)

```bash
quasi-helpers citation parse <draft.md> -o {ct_dir}/parse.json
quasi-helpers citation resolve {ct_dir}/parse.json \
  --biblio {ct_dir}/biblio.json -o {ct_dir}/manifest.json
```

(若 `{ct_dir}/biblio.json` 不存在,先 `quasi-audit emit-bib -o {ct_dir}/biblio.json`。)

manifest entries 每条带 `status ∈ {single-hit, multi-hit, miss}` 和 `candidates: [{slug, ...}]`。

### 2.2 — citation-agent 批 (single + multi only)

主进程**过滤** manifest entries:

```python
todo = [e for e in manifest.entries if e.status in {"single-hit", "multi-hit"}]
batches = chunk(todo, size=8)
```

并发 dispatch (cap 4):

```
Agent("quasi:citation-agent", background=True,
      prompt=f"manifest: {ct_dir}/manifest.json\n"
             f"biblio: {ct_dir}/biblio.json\n"
             f"batch_keys: {batch_keys_json}\n"
             f"verdict_out: {ct_dir}/verdicts/batch-{NNN}.json")
```

每批产出 `verdicts/batch-NNN.json`,每条 note 含 `{key, picked_slug, flag, note}` (flag ∈ ok/review)。

**等所有 batch 完成** (foreground or `while` glob poll)。

### 2.3 — discover-agent recover (miss only) — `--no-recover` 时跳过

```python
miss = [e for e in manifest.entries if e.status == "miss"]
for v in miss:  # 并发, cap 4
    Agent("quasi:new-discover-agent", background=True,
          prompt=f"""
task: recover the real source of this missing citation

context:
  key: {v.key}
  author: {v.parsed_author}
  year_hint: {v.parsed_year}
  mention_context: {v.mention_snippet}

constraints:
  max_candidates: 5
  year_tolerance: 1

output_path: {ct_dir}/verdicts/recovery-{v.key}.json

output_schema (example):
{{
  "key": "{v.key}",
  "online_recovery": {{
    "title": "...", "author": "...", "year": 0,
    "isbn": null, "doi": null, "publisher": null,
    "kind": "book | paper | unknown",
    "confidence": "high | medium | low | miss",
    "sources": ["..."],
    "suggested_slug": "...",
    "process_book_cmd": "/quasi:process-book ..."
  }}
}}
""")
```

每条产出 `verdicts/recovery-{key}.json`,含 `online_recovery: {title, author, year, doi, isbn, suggested_slug, process_book_cmd, confidence}`。

### 2.4 — TUI 审定 (主进程, 关键步骤)

**主进程驱动**, **不要派 agent**。读所有 artifacts,按维度分箱,**按维度顺序** AskUserQuestion 走完。

```python
manifest = read({ct_dir}/manifest.json)
notes = {}  # key → {picked_slug, flag, note}
for f in glob({ct_dir}/verdicts/batch-*.json):
    for n in read(f).notes:
        notes[n.key] = n

recoveries = {}  # key → online_recovery dict
for f in glob({ct_dir}/verdicts/recovery-*.json):
    r = read(f)
    recoveries[r.key] = r.online_recovery

bins = {
  "auto_ok":       [],   # 不问用户, 直接接受
  "review_single": [],   # single-hit + flag=review
  "review_multi":  [],   # multi-hit (无论 flag, 都让用户确认; 但默认接受 agent picked)
  "miss_recover":  [],   # miss + recoveries[key] 存在
  "miss_orphan":   [],   # miss + 无 recovery
}

for e in manifest.entries:
    n = notes.get(e.key)
    if e.status == "single-hit":
        if n and n.flag == "ok":
            bins["auto_ok"].append((e, n))
        else:
            bins["review_single"].append((e, n))
    elif e.status == "multi-hit":
        bins["review_multi"].append((e, n))
    elif e.status == "miss":
        if e.key in recoveries:
            bins["miss_recover"].append((e, recoveries[e.key]))
        else:
            bins["miss_orphan"].append(e)
```

**先打印一次 summary**: 让用户知道本轮要过多少条。

```
📊 Citation review:
  ✓ 自动接受 (single-hit + agent ok):  {len(auto_ok)} 条
  ⚠ 单候选可疑 (single-hit + review):  {len(review_single)} 条
  🔀 多候选挑选 (multi-hit):           {len(review_multi)} 条
  🔍 缺 + 在线找到候选:                {len(miss_recover)} 条
  ❌ 缺 + 在线也没找到:                {len(miss_orphan)} 条
  ─────────────────────────────────────
  本轮需要你审:  {total - len(auto_ok)} 条
```

**然后按 bin 顺序走 TUI**:

**A. review_single — single-hit 主题可疑**

对每条,AskUserQuestion (一次问 1 条; 后续可优化为一次 1-4 条批问):

- `header`: `"{key}"` (chip 显示 key)
- `question`: 多行,含 mention 上下文摘录 (~200字截断) + agent note + 当前 vault candidate 标题
- `options` (4 选 1):
  - "接受 vault: {picked_slug}" (recommended; default 选这个) — `decision="single-hit-accept"`
  - "改 draft 引用" (用 Other 填新 key 或描述) — `decision="draft-rewrite-todo"`
  - "标 vault TODO (用户要去补对的 vault 条目)" — `decision="vault-todo"`
  - "跳过本条 (不出 bib)" — `decision="skip"`

**B. review_multi — 多候选挑选**

对每条 AskUserQuestion:

- `header`: `"{key}"`
- `question`: mention 上下文 + agent picked_slug + agent note
- `options`:
  - "接受 agent 选的: {picked_slug}" (default; agent 通常对)
  - "其他候选: {candidate2}" (列其他候选,1-2 个)
  - "都不对, 我手填" (用 Other)
  - "跳过本条"

candidates 多于 3 个时, 显示前 2 + "其他...(用 Other 填 slug)"。

**C. miss_recover — 缺 + 在线找到候选**

对每条 AskUserQuestion:

- `header`: `"{key}"`
- `question`: mention 上下文 + recovery 给的 title/author/year + process_book_cmd + confidence
- `options`:
  - "加待跑列表: {process_book_cmd}" (default if confidence ≥ medium) — `decision="vault-todo-with-cmd"`
  - "改 draft 引用" (Other 填) — `decision="draft-rewrite-todo"`
  - "跳过本条" — `decision="skip"`

**D. miss_orphan — 缺 + 在线也没找到**

对每条 AskUserQuestion:

- `header`: `"{key}"`
- `question`: mention 上下文 + 提示 "在线也没找到"
- `options`:
  - "标 vault TODO (自己去查)" — `decision="vault-todo"`
  - "改 draft 引用" (Other) — `decision="draft-rewrite-todo"`
  - "跳过本条" — `decision="skip"`

### 2.5 — 写 decisions.json + emit .bib

走完所有 bin 后, 主进程把结果整成:

```json
{
  "by_key": {
    "fausto-sterling-2000": {
      "bib_source": "vault:fausto-sterling-sexing-the-body-2000",
      "decision": "single-hit-accept",
      "note": "vault 候选契合, 接受"
    },
    "russell-2019": {
      "bib_source": "new:russell-...-2019",
      "decision": "vault-todo-with-cmd",
      "note": "已加待跑列表"
    },
    "garbage-key": {
      "bib_source": null,
      "decision": "skip",
      "note": "用户跳过"
    }
  },
  "vault_todo": [
    {"key": "russell-2019", "process_book_cmd": "/quasi:process-book ...", "title": "...", "author": "...", "year": ...}
  ],
  "draft_rewrites": [
    {"old_key": "fausto-sterling-2000", "user_note": "改为 Sexing the Body 2000", "draft_snippet": "..."}
  ],
  "summary": {
    "total": 168,
    "auto_ok": 137,
    "user_reviewed": 31,
    "skipped": 4,
    "vault_todo": 12,
    "draft_rewrites": 3
  }
}
```

Write 到 `{ct_dir}/decisions.json`。

然后 emit:

```bash
quasi-helpers citation emit-bib {ct_dir}/manifest.json \
  --biblio {ct_dir}/biblio.json \
  --decisions {ct_dir}/decisions.json \
  -o {project_root}/references.bib
```

**最终打印**:

```
✅ Wrap-up done.

  📄 draft:           {draft_path}
  📋 decisions:       {ct_dir}/decisions.json
  📚 references.bib:  {project_root}/references.bib

  vault todos:    {len(vault_todo)} 条 ({ct_dir}/decisions.json 的 vault_todo 字段)
  draft rewrites: {len(draft_rewrites)} 条 ({ct_dir}/decisions.json 的 draft_rewrites 字段)
```

如果有 vault_todo, 提示用户:
```
💡 加待跑书目: 把 decisions.json 里 vault_todo 的 process_book_cmd 复制到新 Claude 会话批跑。
```

如果有 draft_rewrites, 提示:
```
💡 改 draft 引用: decisions.json 里 draft_rewrites 列了 N 条 cite 你要回去改 draft, 改完跑 /quasi:wrap-up <draft> --citation-only 重新出 .bib。
```

**硬约束**:
- Phase 1 必须全部完成才进入 Phase 2 (proofread 改字会让 parse 行号失效)
- Phase 2.2 + 2.3 完成才进入 2.4 (TUI 需要全量数据)
- TUI 是主进程串行驱动, 不要拆 agent (AskUserQuestion 必须在主上下文)

## Phase 3 — CLEANUP

校对记录块是临时工具。审完用 git 接受/拒收改动后, 触发清理:

- **触发词**: 用户说 "审完了" / "清理记录块" / "删掉校对记录" / "cleanup" / "proofread 收尾"
- **执行**: `quasi-helpers proofread cleanup <draft-or-dir>` — 从每个 markdown 文件删除整个 `<!-- proofread:start -->...<!-- proofread:end -->` 块
- **执行后**(可选): `rm -rf processing/proofread/{stem}/` 清掉 split 产物

## 中间 / 终产物

```
processing/
├── proofread/{stem}/
│   └── sections.json
├── citation/{stem}/
│   ├── biblio.json
│   ├── parse.json
│   ├── manifest.json
│   ├── verdicts/
│   │   ├── batch-001.json     # citation-agent context-fit notes
│   │   ├── batch-002.json
│   │   └── recovery-{key}.json # discover-agent online recoveries
│   └── decisions.json         # ← TUI 收集的最终决策
└── (project_root)/
    └── references.bib         # ← 终产物
```

**draft 文件本身**:Phase 1 in-place 修改正文 + 末尾累积 `<!-- proofread:start -->...<!-- proofread:end -->` 块,Phase 3 删整段记录块。**改动记录的 single source of truth = draft 末尾块**, 无 sidecar / changelog 冗余。
