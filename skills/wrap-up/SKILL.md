---
name: quasi:wrap-up
description: >
  Use when the user wants to finalise a draft by proofreading text and checking
  citations, or clean up proofread records after review.
---

# Wrap-Up — 文章收尾

## 任务

校对用户提供的 draft,审定引用并输出 bibliography。

## 输入

从用户请求中归一化出:

- `draft_path`:单个 draft 或 draft 目录
- `no_recover`:可选;Phase 2.3 跳过,不在线找 missing
- `citation_only`:可选;跳 Phase 1,只跑 Phase 2

`--citation-only` 是"补完 vault 后增量重跑"的快捷入口: proofread 已经做过、draft 文本已经定稿、只是 vault 增量补了几本书想重新审引用 + 出 .bib。**直接跳过 Phase 1**, 从 Phase 2 进。

## 状态

- 主进程 owns state:`.quasi/proofread/{stem}/`,
  `.quasi/citation/{stem}/decisions.json`,recovery files,以及最终
  `references.bib` 的生成触发。
- `decisions.json` 是 citation review 的 single source of truth。
- draft 末尾 `<!-- proofread:start -->...<!-- proofread:end -->` 块是
  proofread 改动记录的 single source of truth。

## Agent / Helper 合同

- `proofread-agent` 只处理一个 draft section;全局收敛和人工审稿由主进程完成。
- `citecheck-agent` 只写指定 `verdict_out`;每条 note 是一张 review card,供主进程透传给用户。
- `quasi-helpers citation review-cards` 只合并 `verdicts/batch-*.json` 为 `{ct_dir}/review-cards.json`;不做判断、不改 decisions。
- `search-agent` 只为 miss citation 返回 recovery 候选;主进程判断是否进入
  `vault_todo/draft_rewrites/skip`。
- 所有人类决策集中在 Phase 2.4,不要拆给 agent。

## 硬约束

- Phase 1 必须全部完成才进入 Phase 2;proofread 改字会让 citation parse 行号失效。
- Phase 2.2 + 2.3 必须完成才进入 Phase 2.4;主进程需要完整 review cards / recoveries 才能问用户。
- Phase 2.4 是 Claude Code 主进程驱动的 CC-native review,不要拆给 agent,不要转 HTML/TUI。
- Phase 2.4 默认每轮最多 4 张 card:主进程先用普通消息展示这 1-4 张 card 的必要上下文,再用 `AskUserQuestion` 收同一轮裁决。不要让用户在 terminal 里一次读十几张 card。
- 主进程每收到一轮用户裁决,必须立即执行一轮 apply:增量写 `decisions.json`、按需修改文件、重导 bibliography、报告本轮改动和剩余 pending。
- Phase 3 cleanup 只在用户明确说审完或清理记录块后执行。

## 工作流

```
┌─ Phase 1  PROOFREAD   ─ sonnet 节内多轮 + codex 提议 + 主进程审稿
├─ Phase 2  CITATION    ─ 解析 + LLM review cards + 在线 recover + CC-native 审定 + 增量 emit .bib
│   ├─ 2.1 parse + resolve                         (deterministic)
│   ├─ 2.2 citecheck-agent 批(single + multi only)  → review cards
│   ├─ 2.3 search-agent 批(miss)                    → online recovery
│   ├─ 2.4 CC-native 审定(AskUserQuestion 每轮≤4张) ← 每轮答复后立即 apply
│   └─ 2.5 final summary + references.bib path
└─ Phase 3  CLEANUP     ─ 等用户审完触发("审完了" 等)删 proofread 记录块
```

agent 不直接裁决引用是否正确,只产出可问人的 review card。**主进程在主上下文里透传 card 的正文用途、当前条目、候选证据、建议和后果**,让用户裁决。主进程每轮最多展开 4 张 card,随后用 `AskUserQuestion` 一次收这 1-4 张的裁决;用户每答完一轮,主进程立刻落盘并重导,不把答案攒到最后。

旧 `render.py` 仅作为源码归档参考,skill 不再调用。

## Flag 解析

主进程从 caller 提供的命令里解析 flag:

```python
draft_path = parse_positional()
flags = parse_flags()  # --no-recover, --citation-only

if flags.citation_only:
    skip_phase_1 = True
    skip_phase_3 = True   # cleanup
```

## 执行流程

下面按 Phase 1-3 展开。Phase 1 负责 proofread,Phase 2 负责 citation review
和 bibliography 输出,Phase 3 只在用户明确审完后清理 proofread 记录块。

## Phase 1 — PROOFREAD

`--citation-only` 时全跳过。

按节切 → sonnet 节内多轮迭代到收敛 → codex 跨模型兜底。**改动直接累积在 draft 末尾的 `<!-- proofread:start -->...<!-- proofread:end -->` 块**。

设 `pf_dir = .quasi/proofread/{draft-stem}/`。

**Stage A — sonnet 节串行 + 节内多轮迭代**:

1. `quasi-helpers proofread prepare <draft> -o {pf_dir}/sections.json` — 按 H2/H3 切节,并在 draft 末尾创建空记录块(已存在则跳过)
2. 对每节顺序处理(节间串行,避免并发改 draft 末尾块):
   ```
   for sec in sections:
     for r in 1..5:
       before = count_records(round_tag=f"s{r}")  # 只数末尾记录块里的现有 s{r} 行
       Agent("quasi:proofread-agent", prompt 给 draft/section_id/round_tag=s{r}/start_line/end_line)
       after = count_records(round_tag=f"s{r}")
       after - before == 0 → 该节收敛,跳出
   ```

注意:记录块是整篇 draft 共享的,不同节都会写 `s1/s2/...`。因此收敛判断必须看
本轮前后 delta,不能用全局 grep 总数判断。

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

(若 `{ct_dir}/biblio.json` 不存在,先 `quasi-helpers citation biblio -o {ct_dir}/biblio.json`。)

manifest entries 每条带 `status ∈ {single-hit, multi-hit, miss}` 和 `candidates: [{slug, ...}]`。

### 2.2 — citecheck-agent 批 (single + multi only)

主进程**过滤** manifest entries:

```python
todo = [e for e in manifest.entries if e.status in {"single-hit", "multi-hit"}]
batches = chunk(todo, size=8)
```

并发 dispatch (cap 4):

```
Agent("quasi:citecheck-agent", background=True,
      prompt=f"manifest: {ct_dir}/manifest.json\n"
             f"batch_keys: {batch_keys_json}\n"
             f"verdict_out: {ct_dir}/verdicts/batch-{NNN}.json")
```

每批产出 `verdicts/batch-NNN.json`,每条 note 是 review card,含 `key`, `picked_slug`, `status`, `flag`, `decision_question`, `draft_context`, `current_bib`, `candidates`, `recommended_action`, `confidence`, `missing_evidence`, `note`。`flag` 只是兼容字段。

**等所有 batch 完成** (foreground or harness task notifications)。然后合并:

```bash
quasi-helpers citation review-cards {ct_dir}/verdicts -o {ct_dir}/review-cards.json
```

### 2.3 — search-agent recover (miss only) — `--no-recover` 时跳过

```python
miss = [e for e in manifest.entries if e.status == "miss"]
recovery_jobs = []
for v in miss:  # 并发, cap 4
    job = Agent("quasi:search-agent", background=True,
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
""")
    recovery_jobs.append((v, job))

# 等 search-agent 全部返回后,主进程自己判断/归一化/落盘。
for v, job in recovery_jobs:
    search = job.result
    recovery = choose_recovery_candidate(
        key=v.key,
        parsed_author=v.parsed_author,
        parsed_year=v.parsed_year,
        mention_context=v.mention_snippet,
        search_result=search,
    )
    write_json(f"{ct_dir}/verdicts/recovery-{v.key}.json", {
      "key": v.key,
      "online_recovery": recovery,
    })
```

每条产出 `verdicts/recovery-{key}.json`,含 `online_recovery: {title, author, year, doi, isbn, suggested_slug, process_book_cmd, confidence}`。

Recovery 的判断和落盘属于 `wrap-up` 主进程:search-agent 只搜索并返回候选,不写
verdict 文件,也不决定是否进入后续用户审定。

### 2.4 — CC-native review cards 审定 (主进程, 关键步骤)

**主进程驱动**, **不要派 agent**, **不要转 HTML/TUI**。读所有 artifacts,按 review card 状态和 miss recovery 分箱。凡是问用户,都通过 Claude Code 主进程透传上下文和证据,并默认用 `AskUserQuestion` 收结构化裁决。

```python
manifest = read({ct_dir}/manifest.json)
review_cards = read({ct_dir}/review-cards.json)

recoveries = {}  # key → online_recovery dict
for f in glob({ct_dir}/verdicts/recovery-*.json):
    r = read(f)
    recoveries[r.key] = r.online_recovery

bins = {
  "auto_ok":       [],   # 不问用户, 本轮 apply 时自动写 decisions
  "needs_user":    [],   # 主进程逐张透传高上下文 card
  "unresolved":    [],   # 证据不足, 询问 search_more / skip / vault_todo
  "miss_recover":  [],   # miss + recoveries[key] 存在
  "miss_orphan":   [],   # miss + 无 recovery
}

for card in review_cards.cards:
    if card.status == "auto_ok":
        bins["auto_ok"].append(card)
    elif card.status == "needs_user":
        bins["needs_user"].append(card)
    else:
        bins["unresolved"].append(card)

for e in manifest.entries:
    if e.status == "miss":
        if e.key in recoveries:
            bins["miss_recover"].append((e, recoveries[e.key]))
        else:
            bins["miss_orphan"].append(e)
```

**先打印一次 queue summary**: 让用户知道总量和当前优先级,但不要展开所有 card。

```text
Citation review:
  auto-ok:      {len(auto_ok)} 条
  needs-user:   {len(needs_user)} 条
  unresolved:   {len(unresolved)} 条
  miss+recover: {len(miss_recover)} 条
  miss+orphan:  {len(miss_orphan)} 条
  总需人工裁决: {len(needs_user)+len(unresolved)+len(miss_recover)+len(miss_orphan)} 条
```

**Review card 提问格式**:

默认每轮最多处理 4 张 card。主进程先用普通消息展开当前 1-4 张 card 的必要上下文,再调用一次 `AskUserQuestion`:

- `questions` 数组中每个 question 对应 1 张 card。
- 每轮 `questions` 数量必须是 1-4;复杂 card 单独成轮,同类简单 card 可合并到同一轮。
- 每个 question 提供 2-4 个落盘后果清晰的选项,例如:按推荐处理 / 保留当前 / search more / skip 或 vault_todo。
- 不要把 5 张以上 card 展开在同一轮;更不要一次性倾倒十几张 card。

凡是问用户,普通消息中的 card 正文必须包含:

1. `key`
2. `draft_context.quote`
3. `draft_context.use_summary`
4. `current_bib.display`
5. `current_bib.concern`
6. `candidates[].display` + `candidates[].evidence`
7. `recommended_action` + `confidence`
8. 每个选项的落盘后果

复杂 card 示例:

```markdown
### verbeek-2015 需要你判断

正文用途:
> Verbeek 的 mediation theory 说明技术中介身体经验。

用途摘要:正文在概括 postphenomenology 的框架性论点。

当前条目:
Verbeek, Peter-Paul (2015) Beyond Interaction: A Short Introduction to Mediation Theory.

疑点:
当前条目是短介绍,可能不足以支撑正文中的框架性概括。

候选替换:
Rosenberger and Verbeek (eds.) (2015) Postphenomenological Investigations.

证据:
- vault overview 显示该书聚焦 human-technology relations 和 postphenomenology。

Agent 建议:replace;confidence=medium。

选项后果:
1. 替换为候选 edited volume → decisions.by_key[key].bib_source = vault:{picked_slug},重导 references.bib
2. 保留当前候选 → decisions.by_key[key].bib_source = vault:{current_slug},重导 references.bib
3. search more → 暂不改 bib,记录为 draft_rewrites/vault_todo follow-up
4. skip → 本轮不出 bib skeleton 或跳过
```

四张以内同轮示例:

```markdown
本轮处理 3/18:下面 3 条都是同类 metadata/译名清理问题,agent 证据充分,建议批量接受。

Card 1 — toole-2023
正文用途: 引用声音/听觉技术材料。
当前条目: 中译本作者含中文名 + English Name。
建议: 只保留中文名。confidence=high。
选项后果:按推荐处理会立即修改对应 bib/cache,写 decisions.by_key[toole-2023],重导 references.bib。

Card 2 — tsing-2015
正文用途: 引用多物种关系和资本主义废墟材料。
当前条目: 中译本作者含中文名 + English Name。
建议: 只保留中文名。confidence=high。
选项后果:按推荐处理会立即修改对应 bib/cache,写 decisions.by_key[tsing-2015],重导 references.bib。

Card 3 — wajcman-2015
正文用途: 引用数字资本主义中的时间压力材料。
当前条目: 中译本作者含中文名 + English Name。
建议: 只保留中文名。confidence=high。
选项后果:按推荐处理会立即修改对应 bib/cache,写 decisions.by_key[wajcman-2015],重导 references.bib。
```

随后调用 `AskUserQuestion`:

```python
AskUserQuestion(questions=[
  {
    "header": "toole-2023",
    "question": "toole-2023 怎么处理?",
    "options": [
      {"label": "按推荐", "description": "只保留中文名,立即写 decisions 并重导 bib"},
      {"label": "保留当前", "description": "保留现有 bib/cache 条目,记录 keep"},
      {"label": "跳过", "description": "本轮不改,记录 skip"},
    ],
    "multiSelect": False,
  },
  # 本轮最多再放 3 个同形 question;复杂 card 单独成轮。
])
```

收到这轮 1-4 个答案后,马上执行 apply;不要继续展示下一轮 card 后再统一处理。

**miss_recover / miss_orphan 提问**:

- `miss_recover`:展示 mention 上下文 + recovery title/author/year + process_book_cmd + confidence。选项:加待跑列表 / 改 draft 引用 / 跳过。
- `miss_orphan`:展示 mention 上下文 + “在线也没找到”。选项:标 vault TODO / 改 draft 引用 / 跳过。
- miss 类条目也遵守每轮最多 4 张 card 的限制,并用 `AskUserQuestion` 一次收当前轮裁决。

**每轮答复后的立即 apply 协议**:

主进程收到用户对当前 1-4 张 cards 的 `AskUserQuestion` 裁决后,必须立刻执行:

1. 读当前 `{ct_dir}/decisions.json`。不存在则初始化 `{by_key:{}, vault_todo:[], draft_rewrites:[], summary:{}}`。
2. 将本轮裁决写入 `decisions.by_key`。auto-ok 可以按批写入,needs-user 必须带用户裁决 note。
3. 若用户裁决要求改 bib / draft / local cache,立即 Edit 对应文件。
4. 运行 `quasi-helpers citation emit-bib {ct_dir}/manifest.json --biblio {ct_dir}/biblio.json --decisions {ct_dir}/decisions.json -o {project_root}/references.bib`。
5. 向用户报告本轮修改了哪些 key、重导路径、剩余 `needs_user/unresolved/miss` 数。
6. 再展示下一轮最多 4 张 cards 并调用下一次 `AskUserQuestion`。

禁止把多个轮次的用户答案存在对话上下文里等最后统一 apply。

### 2.5 — final summary + references.bib path

所有 pending 轮次处理完后,主进程只做最终汇总,不再集中 apply 一次。此时 `{ct_dir}/decisions.json` 已经随着每轮答复增量更新,`references.bib` 也已在每轮 apply 后重导。

最终打印:

```text
Wrap-up citation review done.

  draft:          {draft_path}
  review cards:   {ct_dir}/review-cards.json
  decisions:      {ct_dir}/decisions.json
  references.bib: {project_root}/references.bib

  vault todos:    {len(vault_todo)} 条
  draft rewrites: {len(draft_rewrites)} 条
```

如果有 vault_todo,提示用户把 `decisions.json` 里 `vault_todo[].process_book_cmd` 复制到新 Claude 会话批跑。

如果有 draft_rewrites,提示用户按 `decisions.json` 里的 `draft_rewrites` 回改 draft,改完跑 `/quasi:wrap-up <draft> --citation-only` 重新审引用。

**硬约束**:
- Phase 1 必须全部完成才进入 Phase 2 (proofread 改字会让 parse 行号失效)
- Phase 2.2 + 2.3 完成才进入 2.4 (主进程需要完整 review cards / recoveries)
- CC-native review 是主进程串行驱动,每轮最多 4 张 card 并用 `AskUserQuestion` 收裁决;不要拆 agent,不要转 HTML/TUI

## Phase 3 — CLEANUP

校对记录块是临时工具。审完用 git 接受/拒收改动后, 触发清理:

- **触发词**: 用户说 "审完了" / "清理记录块" / "删掉校对记录" / "cleanup" / "proofread 收尾"
- **执行**: `quasi-helpers proofread cleanup <draft-or-dir>` — 从每个 markdown 文件删除整个 `<!-- proofread:start -->...<!-- proofread:end -->` 块
- **执行后**: `rm -rf .quasi/proofread/{stem}/` 清掉 split 输出

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `citation_only` flag | 直接跳过 proofread |
| Phase 1 prepare | `.quasi/proofread/{stem}/sections.json` | 存在则复用 section manifest |
| Phase 2.1 | `{ct_dir}/manifest.json` | 存在则可复用 parse/resolve 结果 |
| Phase 2.2 | `{ct_dir}/verdicts/batch-*.json` | 对已有 batch 不重复跑 citecheck-agent |
| Phase 2.2 merge | `{ct_dir}/review-cards.json` | batch verdicts 未变则复用 |
| Phase 2.3 | `no_recover` flag 或 `recovery-{key}.json` | flag 开启则跳过;已有 recovery 则复用 |
| Phase 2.4 per group | `{ct_dir}/decisions.json` | 已有 key 不重复问;从 pending key 继续 |
| Phase 3 | 用户触发词 | 用户未明确审完则不 cleanup |

## 输出

```
.quasi/
├── proofread/{stem}/
│   └── sections.json
└── citation/{stem}/
    ├── biblio.json
    ├── parse.json
    ├── manifest.json
    ├── review-cards.json      # citecheck-agent 批输出合并后的 CC-native cards
    ├── verdicts/
    │   ├── batch-001.json     # citecheck-agent review cards
    │   ├── batch-002.json
    │   └── recovery-{key}.json # search-agent online recoveries
    └── decisions.json         # ← CC-native review 增量收集的最终决策

(project_root)/
└── references.bib             # ← 最终输出
```

**draft 文件本身**:Phase 1 in-place 修改正文 + 末尾累积 `<!-- proofread:start -->...<!-- proofread:end -->` 块,Phase 3 删整段记录块。**改动记录的 single source of truth = draft 末尾块**, 无 sidecar / changelog 冗余。
