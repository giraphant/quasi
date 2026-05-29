---
name: quasi:process-topic
description: >
  Use when the user wants to build a navigable topic review and reading-list
  index over the vault from a research question, theme, or optional seed paper.
---

# Process Topic — 主题综述 + 阅读清单索引

## 任务

把一个主题构建成 vault 上可导航的综述 + 阅读清单索引。

## 输入

从用户请求中归一化出:

- `topic_slug`:topic 目录名(`vault/topics/{topic_slug}/`)。
- `topic_desc` / 研究问题:主题描述(主入口)。
- `seed`(可选):种子论文 DOI;不再是必需入口。

## 硬约束

- **运行时依赖 superset**:per-item 处理用 `superset agents run` 委派整条
  process-paper / process-book。`$SUPERSET_WORKSPACE_ID` 由会话注入;**缺失即报错并停**,
  不要用 `superset workspaces list --local` 猜(可能命中错误 worktree / 分支)。
- **不用 in-harness Agent 工具委派 per-item 管线**:被 spawn 的 subagent 是叶子层,拿不到
  Agent 工具、无法再嵌套。整条 process-paper / process-book 必须经 `superset agents run`
  这个 Bash 子进程委派给顶层 agent。
- **禁止用 TaskOutput 检查委派出去的 agent**:会卡住。**必须用 Glob 轮询 vault 产物**
  (`vault/papers/{slug}.md` / `vault/books/{slug}/00-overview.md`)判完成。
- **每个条目独立 dispatch 一次** `superset agents run`:一篇 paper / 一本 book = 一次委派。
- **不囤副本**:topic 目录下不放任何论文 / 书的分析 `.md`,只放 manifest + 索引页。
- **并发上限 ~5**:同 workspace 同时 fire 的委派 agent 不超过 5 个。
- **Dispatcher context 卫生**:Glob 轮询只看完成数 vs 总数,不逐一列举文件名;委派完成通知是
  冗余信息,收到无需额外处理;阶段间不回顾前序输出,关键状态都在磁盘 manifest 上。

## 状态

主进程 owns `vault/topics/{topic_slug}/manifest.json`:

```json
{
  "topic": "...",
  "topic_slug": "...",
  "topic_desc": "...",
  "seed_doi": null,
  "rounds_completed": 0,
  "discovery_rounds": [
    { "round": 0, "queries": ["..."], "source": "paper_query" }
  ],
  "items": {
    "<slug>": {
      "kind": "paper | book",
      "source": "paper_query | kagi | citation | user",
      "vault_path": "vault/papers/<slug>.md",
      "title": "...", "authors": ["..."], "year": 2023, "doi": "...",
      "round": 1,
      "status": "discovered | processing | analysed | failed",
      "failure_note": null
    }
  }
}
```

status enum:

- `discovered` — 候选,metadata 够发现但还没委派处理。
- `processing` — 已 fire `superset agents run`,等 vault 产物落地。
- `analysed` — 已落 vault(`vault_path` 存在),可读核心理论段取引用。
- `failed` — 发现 / 委派 / 分析失败,带 `failure_note`。

`round` 控制本轮扩展;`rounds_completed` 只在本轮全部 analysed + 引用提取完成后递增。

## Agent / Helper 合同

- `search-agent`(foreground)— 只补 metadata,本 skill 写回 manifest。
- **per-item 委派**(`superset agents run`,**不是** Agent 工具)— 跑 `/quasi:process-paper`
  或 `/quasi:process-book`,各自内部派 download / analyse / audit worker,落正常 vault 目录。
- `synthesis-agent`(foreground,最终一次)— 写 `00-overview.md` + `01-resources.md`,
  主进程判断是否生 `02+` 子页。
- `audit-agent`(foreground,收尾)— 只校验 topic 页(`type: topic`);论文 / 书由各自
  process-paper / book 内部审计,不在此重复。

## 工作流

```
输入: topic_slug + topic_desc (seed DOI 可选)
├─ Phase 0  DISCOVER
│    search-agent: quasi-search paper --query <主题> (按需 book --query)
│    主进程判断: 搜不到/非结构化 → 自行 kagi + dokobot
│    → 候选写 manifest.items (status=discovered)
├─ Phase 1-N  SNOWBALL
│    每个 discovered 条目: superset agents run --agent claude
│      (跑 /quasi:process-paper|book) → 异步 fire (并发 ~5)
│    Glob 轮询 vault 产物判完成 → status=analysed
│    读各条目核心理论段 → 取引用 → dedupe 进 manifest (新 round, source=citation)
│    new_refs == 0 → 退出循环
├─ DEAD-END  RE-DISCOVER (用户闸门)
│    轻信号提取 → AskUserQuestion 提议查询词
│    → 拒 → FINAL;  选 → DISCOVER 新种子 → 回 SNOWBALL
├─ FINAL  synthesis-agent → 00-overview.md ([[wikilink]]) + 01-resources.md
└─ AUDIT (topic 页) + Marple open (00-overview)
```

## 执行流程

```python
topic_slug, topic_desc, seed = parse_args()
workspace = env("SUPERSET_WORKSPACE_ID")
if not workspace:
    report("SUPERSET_WORKSPACE_ID 未注入;process-topic 需在 superset 会话内运行。停止。")
    return

topic_dir = f"vault/topics/{topic_slug}"
manifest_path = f"{topic_dir}/manifest.json"
MAX_ROUNDS = 5
CONCURRENCY = 5

def dispatch_item(slug, item):
    """Fire one top-level agent to run the whole per-item skill. Async."""
    skill = "process-paper" if item["kind"] == "paper" else "process-book"
    if item["kind"] == "paper" and item.get("doi"):
        ask = f"Run /quasi:{skill} for DOI {item['doi']} (slug {slug})."
    else:
        ask = (f"Run /quasi:{skill} for slug {slug} "
               f"(title {item.get('title','?')}, authors {item.get('authors',[])}).")
    out = (f"vault/papers/{slug}.md" if item["kind"] == "paper"
           else f"vault/books/{slug}/00-overview.md")
    Bash(f"""superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent claude \
  --prompt {shquote(ask + f" Write {out}; tag frontmatter topics: [{topic_slug}]; report final path + status.")} \
  --json --quiet""")
    item["status"] = "processing"

# Phase 0: DISCOVER
if not exists(manifest_path) or not read_json(manifest_path).get("items"):
    search = Agent("quasi:search-agent", foreground=True,
                   prompt=f"kind: paper\nquery: {topic_desc}\nconstraints:\n  count: 25")
    items = {}
    for rec in search.results:
        slug = slugify(rec)
        items[slug] = {
            "kind": "paper", "source": "paper_query",
            "vault_path": f"vault/papers/{slug}.md",
            "title": rec.get("title"), "authors": rec.get("authors", []),
            "year": rec.get("year"), "doi": rec.get("doi"),
            "round": 1, "status": "discovered", "failure_note": None,
        }
    # 主进程 affordance: 结构化搜不到 / 非结构化资料 → 自行 kagi + dokobot,
    # 命中的书/线索同样写进 items(kind=book, source=kagi)。不默认并行。
    manifest = {
        "topic": topic_desc, "topic_slug": topic_slug, "topic_desc": topic_desc,
        "seed_doi": seed, "rounds_completed": 0,
        "discovery_rounds": [{"round": 0, "queries": [topic_desc], "source": "paper_query"}],
        "items": items,
    }
    write_json(manifest_path, manifest)

# Phase 1-N: SNOWBALL
manifest = read_json(manifest_path)
new_refs = 0   # hoisted: DEAD-END gate reads this even if the round loop never runs
for round_num in range(manifest["rounds_completed"] + 1, MAX_ROUNDS + 1):
    # Resume reconcile: promote already-finished processing items before this round.
    for s, it in manifest["items"].items():
        if it["status"] == "processing" and exists(it["vault_path"]):
            it["status"] = "analysed"
    write_json(manifest_path, manifest)

    # pending = this round's unfinished items: fresh discovered + stranded processing
    # (fired on a previous run but no vault product yet) -- re-fire those.
    pending = [(s, it) for s, it in manifest["items"].items()
               if it["round"] == round_num
               and (it["status"] == "discovered"
                    or (it["status"] == "processing" and not exists(it["vault_path"])))]
    if not pending:
        break

    # Fire delegations in waves of CONCURRENCY.
    for s, it in pending:
        dispatch_item(s, it)
        write_json(manifest_path, manifest)
        while count(processing(manifest)) >= CONCURRENCY:
            # Glob-poll vault products; promote finished items.
            for ps, pit in processing(manifest):
                if exists(pit["vault_path"]):
                    pit["status"] = "analysed"
            write_json(manifest_path, manifest)
            sleep(30)

    # Drain remaining processing items.
    while processing(manifest):
        for ps, pit in processing(manifest):
            if exists(pit["vault_path"]):
                pit["status"] = "analysed"
        write_json(manifest_path, manifest)
        sleep(30)

    # Snowball: read each analysed item's core-theory section, harvest refs.
    new_refs = 0
    for s, it in manifest["items"].items():
        if it["round"] != round_num or it["status"] != "analysed":
            continue
        refs = parse_citation_section(Read(it["vault_path"]))
        new_refs += deduplicate_and_add(manifest, refs, round_num + 1, source="citation")
    manifest["rounds_completed"] = round_num
    write_json(manifest_path, manifest)
    if new_refs == 0:
        break

# DEAD-END: RE-DISCOVER (user gate)
if new_refs == 0 and not exists(f"{topic_dir}/00-overview.md"):
    signals = extract_light_signals(manifest)   # 高频作者 / 反复术语 / 明显空白
    choice = AskUserQuestion(
        question=f"主题 {topic_desc} 的结构化扩展到头了。是否用这些查询词再发现一轮?",
        options=signals + ["不再发现,直接综述"])
    if choice not in ("不再发现,直接综述", REJECTED):
        # New seed query: mirror Phase 0 DISCOVER for `choice` (主进程判断是否补 kagi),
        # append candidates as a fresh round = rounds_completed + 1 with status=discovered,
        # write manifest, then re-run this SNOWBALL block to process the new round.
        discover_into(manifest, choice, round=manifest["rounds_completed"] + 1, source="user")
        write_json(manifest_path, manifest)

# FINAL: synthesis
if not exists(f"{topic_dir}/00-overview.md"):
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"""\
mode: topic
topic: {topic_desc}
topic_slug: {topic_slug}
manifest: {manifest_path}
overview_path: {topic_dir}/00-overview.md
resources_path: {topic_dir}/01-resources.md
note: |
  00-overview.md frontmatter = {{type: topic, kind: overview}};
  01-resources.md frontmatter = {{type: topic, kind: resources}}.
  正文用 [[slug]] / [[slug|显示名]] 指向 vault/papers/{{slug}} 与
  vault/books/{{slug}}/00-overview。入库项标类型(论文/书/网资),
  外部/未入库项用 citation/URL + 一句说明 + 状态标记。
  某类确实大/异质时,在 01 用 [[]] 点名新生的 02+ 子页(kind: resources)。
""")

# AUDIT (topic pages only) + Marple open
audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {topic_dir}/")
if audit.audit_result.escalated:
    report(f"topic 页 audit 升级未决: {audit.audit_result.escalated}")

final_page = f"{topic_dir}/00-overview.md"
Bash(f"/opt/homebrew/bin/marple-cli open '{final_page}' || marple-cli open '{final_page}' || echo 'Marple open skipped; run: marple-cli open {final_page}'")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 | `manifest.json` 存在且有 `items` | 存在则跳发现 |
| Phase N | `rounds_completed >= N` | 跳已完成轮 |
| 单条目 | `items[slug].status == analysed` 且 `vault_path` 存在 | 跳已处理(不重复委派) |
| FINAL | `00-overview.md` 存在 | 存在则跳综述 |
| AUDIT | 幂等,可重复跑 | clean 时几乎无成本 |

委派是异步 fire:续跑时把 `status == processing` 但 `vault_path` 已存在的条目提升为
`analysed`;仍缺产物的重新 fire。

## 输出

```
vault/topics/{slug}/
├── manifest.json        ← 编排状态(不渲染给用户)
├── 00-overview.md       ← 综述(核心产物,带 [[wikilink]] 跳转)
├── 01-resources.md      ← 阅读清单总目(带跳转)
└── 02+ (按需子页)        ← type: topic / kind: resources
vault/papers/{slug}.md            ← 正常论文条目(委派 process-paper 产出,frontmatter 带 topics:[slug])
vault/books/{slug}/00-overview.md ← 正常书条目(委派 process-book 产出,frontmatter 带 topics:[slug])
```

topic 页只持有**索引与综述**,不持有分析副本。`vault/topics/` 与 `vault/journals/`
(process-journal 的真实期刊扫描产出)严格分层,不混用。
