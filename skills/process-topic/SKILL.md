---
name: quasi:process-topic
description: >
  Use when the user wants to grow a topic corpus from a seed paper, citation
  trail, or research question and synthesize the resulting literature.
---

# Process Topic — 主题语料(原: citation snowball)

## 任务

从种子论文逐轮扩展引用链并综合主题语料。

## 输入

从用户请求中归一化出:

- `topic_slug`:主题语料目录名
- `seed`:种子论文 DOI
- `topic_desc`:主题描述

## Agent / Helper 合同

- 主进程 owns state:`vault/topics/{topic_slug}/manifest.json`。
- `search-agent` 只补 metadata;本 skill 写回 manifest。
- `download-agent` 只获取本轮 paper PDF;本 skill 写 `pdf_path/status/failure_note`。
- `analyse-agent` 每篇论文一个 background worker;引用提取和 dedupe 由主进程完成。
- `synthesis-agent` 只写最终 topic synthesis / reading list。

## 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成
- **每篇论文独立 dispatch 一个 analyse-agent**：禁止把多篇论文合并到一个 agent 调用中。一篇 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 工作流

```
主进程 (dispatcher + 引用提取)
├─ Phase 0: SEED
│   ├─ download-agent → 种子 PDF
│   ├─ analyse-agent → 种子分析
│   └─ 主进程: 读引用段落 → 创建 manifest
├─ Phase 1-N: EXPAND (循环)
│   ├─ search-agent → metadata 补齐
│   ├─ download-agent(kind=paper, items=[...]) → 本轮 PDF
│   ├─ analyse-agent ×N (后台) → Glob 轮询
│   ├─ 主进程: 读引用段落 → 更新 manifest
│   └─ new_refs == 0? 停止
└─ FINAL: synthesis-agent
```

## 执行流程

```python
topic_slug, seed, topic_desc = parse_args()
manifest_path = f"vault/topics/{topic_slug}/manifest.json"
MAX_ROUNDS = 5

# Phase 0: SEED
if not exists(manifest_path):
    seed_download = Agent("quasi:download-agent", foreground=True,
                          prompt=f"""\
kind: paper
items:
  - slug: {topic_slug}-seed
    expected_title: seed paper for {topic_desc}
    identifiers:
      doi: {seed}
output_dir: sources/
""")
    seed_item = seed_download.per_item[0]
    if seed_item["status"] != "ok":
        report(f"seed download failed: {seed_item.get('verdict_note', 'download_failed')}")
        return

    Agent("quasi:analyse-agent", foreground=True,
          prompt=f"type: B, input: {seed_item['path']}, "
                 f"output: vault/topics/{topic_slug}/seed.md, topic: {topic_desc}")

    analysis = Read(f"vault/topics/{topic_slug}/seed.md")
    citations = parse_citation_section(analysis)
    create_manifest(manifest_path, seed, citations)
    
    # Per-entry metadata fetch. search-agent returns curated JSON; this skill
    # owns manifest writes.
    for key, paper in manifest["papers"].items():
        doi = paper.get('doi')
        if not doi:
            continue
        search = Agent("quasi:search-agent", foreground=True,
                       prompt=f"kind: paper\ndoi: {doi}\nconstraints:\n  count: 1")
        rec = search.picked
        if not rec:
            continue
        for field in ('title', 'authors', 'year', 'abstract', 'cited_by_count', 'is_oa', 'oa_url'):
            if rec.get(field) and not paper.get(field):
                paper[field] = rec[field]
        paper["status"] = "metadata_found"
    write_json(manifest_path, manifest)

# Phase 1-N: EXPAND
manifest = read_json(manifest_path)
for round_num in range(manifest["rounds_completed"] + 1, MAX_ROUNDS + 1):
    discovered = get_discovered(manifest, round_num)
    if not discovered:
        break

    # Per-entry metadata fetch. Keep this explicit in the skill: topic expansion
    # is the state machine; search-agent remains a narrow metadata worker.
    for key, paper in discovered:
        doi = paper.get('doi')
        if not doi:
            continue
        search = Agent("quasi:search-agent", foreground=True,
                       prompt=f"kind: paper\ndoi: {doi}\nconstraints:\n  count: 1")
        rec = search.picked
        if not rec:
            continue
        for field in ('title', 'authors', 'year', 'abstract', 'cited_by_count', 'is_oa', 'oa_url'):
            if rec.get(field) and not paper.get(field):
                paper[field] = rec[field]
        if paper.get("title"):
            paper["status"] = "metadata_found"
    write_json(manifest_path, manifest)

    download_items = [
        {
            "slug": paper.get("slug") or key,
            "expected_author": (paper.get("authors") or [""])[0],
            "expected_title": paper.get("title") or key,
            "identifiers": {"doi": paper.get("doi", "")},
        }
        for key, paper in discovered
        if paper.get("status") == "metadata_found"
    ]
    if not download_items:
        manifest["rounds_completed"] = round_num
        write_json(manifest_path, manifest)
        continue

    download_result = Agent("quasi:download-agent", foreground=True,
                            prompt=f"""\
kind: paper
items:
{format_yaml_list(download_items)}
output_dir: sources/
""")
    # Merge per_item back into manifest: ok -> acquired with local path;
    # download_failed -> failed. No hidden batch CLI owns this mutation.
    for item in download_result.per_item:
        paper = find_manifest_paper(manifest, item["slug"])
        if item["status"] == "ok":
            paper["status"] = "acquired"
            paper["pdf_path"] = item["path"]
        else:
            paper["status"] = "failed"
            paper["failure_note"] = item.get("verdict_note", "download_failed")
    write_json(manifest_path, manifest)

    acquired = get_acquired(manifest, round_num)
    for paper in acquired:
        Agent("quasi:analyse-agent", background=True,
              prompt=f"type: B, input: {paper.pdf_path}, "
                     f"output: vault/topics/{topic_slug}/{paper.key}.md, topic: {topic_desc}")

    while not all_analyzed:
        sleep(30)

    new_refs = 0
    for paper in acquired:
        refs = parse_citation_section(Read(f"vault/topics/{topic_slug}/{paper.key}.md"))
        new_refs += deduplicate_and_add(manifest, refs, round_num + 1)
    manifest["rounds_completed"] = round_num
    write_json(manifest_path, manifest)
    if new_refs == 0:
        break

# FINAL
if not exists(f"vault/topics/{topic_slug}-synthesis.md"):
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"source_name: {topic_desc}, "
                 f"analysis_dir: vault/topics/{topic_slug}/, "
                 f"output_path: vault/topics/{topic_slug}-synthesis.md, "
                 f"reading_list_path: vault/topics/{topic_slug}-reading-list.md, topic: ...")

# TYPECHECK
# 校验 + 修复本次滚雪球产出的所有 paper 分析(在 vault/topics/{slug}/ 下)。
# synthesis.md 自身不打 type,不在 schema 校验范围内 —— typecheck 只扫子目录里的论文。
audit = Agent("quasi:audit-agent", foreground=True,
              prompt=f"path: vault/topics/{topic_slug}/")

if audit.audit_result.escalated:
    for item in audit.audit_result.escalated:
        paper = find_manifest_paper_for_output(manifest, item.path)
        if not paper:
            report(f"audit escalated unknown topic paper path: {item.path}")
            continue
        Agent("quasi:analyse-agent", foreground=True,
              prompt=f"type: B, input: {paper.pdf_path}, "
                     f"output: {item.path}, topic: {topic_desc}\n"
                     f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")

    audit = Agent("quasi:audit-agent", foreground=True,
                  prompt=f"path: vault/topics/{topic_slug}/")
    if audit.audit_result.escalated:
        report("audit still has escalated topic items after one regeneration pass")
        return
```

## 状态

```json
{
  "topic": "...", "topic_slug": "...", "seed_doi": "...",
  "rounds_completed": 0,
  "papers": {
    "<key>": {
      "title": "...", "authors": "...", "year": 2023, "doi": "...",
      "cited_by": [], "round": 1,
      "status": "discovered|metadata_found|acquired|refs_extracted|failed",
      "pdf_path": null, "oa_url": null, "abstract": null
    }
  }
}
```

Status enum:

- `discovered` — 从引用段落解析出的候选,metadata 还不完整。
- `metadata_found` — search-agent 已补齐到足够下载的 metadata。
- `acquired` — `pdf_path` 指向稳定 PDF。
- `refs_extracted` — 已完成分析并把新引用写回 manifest。
- `failed` — 下载或分析失败,带 `failure_note`。

`round` 控制本轮扩展;`rounds_completed` 只在本轮 analyse + refs extraction
完成后递增。

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 | `manifest.json` | 存在则跳过 |
| Phase N | `rounds_completed >= N` | 跳过已完成轮次 |
| FINAL | `synthesis.md` | 存在则跳过 |
| TYPECHECK | 无 —— 幂等,可重复跑 | 上次 typecheck clean 时几乎无成本 |

## 输出

```
vault/topics/{topic-slug}/
├── manifest.json
├── seed.md
└── {paper-key}.md
vault/topics/{topic-slug}-synthesis.md     ← 主题综述（与目录同级）
vault/topics/{topic-slug}-reading-list.md  ← 阅读清单
.quasi/temp/topic-pdfs/{topic-slug}/
└── *.pdf
```

注：`vault/topics/` 是 bts 中「按主题汇集的专题文献集」的归宿，与 `vault/journals/`（process-journal 的真实期刊扫描产出）严格分层，不混用。
