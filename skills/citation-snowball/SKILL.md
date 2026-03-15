---
name: quasi:citation-snowball
type: workflow
description: >
  Composite skill: builds a topic-focused reading corpus by chaining citations
  from a seed paper, round by round, until saturation.
  Use when the user says "滚雪球", "citation chain", "expand references".
argument-hint: "<topic-slug> --seed <doi-or-pdf> --topic \"<description>\""
---

# Citation Snowball — 引用滚雪球

种子论文 → 逐轮扩展引用链 → 饱和。扁平 agent 调度 + 主进程引用提取。

## 调用方式

```
/quasi:citation-snowball {topic-slug} --seed {doi} --topic "{description}"
```

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成

## 编排架构

```
主进程 (dispatcher + 引用提取)
├─ Phase 0: SEED
│   ├─ download-agent → 种子 PDF
│   ├─ analyze-agent → 种子分析
│   └─ 主进程: 读引用段落 → 创建 manifest
├─ Phase 1-N: EXPAND (循环)
│   ├─ search.py metadata (Bash)
│   ├─ download-agent → 本轮 PDF
│   ├─ analyze-agent ×N (后台) → Glob 轮询
│   ├─ 主进程: 读引用段落 → 更新 manifest
│   └─ new_refs == 0? 停止
└─ FINAL: synthesis-agent
```

## 执行流程

```python
topic_slug, seed, topic_desc = parse_args()
manifest_path = f"vault/journals/{topic_slug}/manifest.json"
MAX_ROUNDS = 5

# Phase 0: SEED
if not exists(manifest_path):
    Agent("quasi:download-agent", foreground=True,
          prompt=f"doi: {seed}, output_dir: /tmp/{topic_slug}-pdfs/, filename: seed")

    Agent("quasi:analyze-agent", foreground=True,
          prompt=f"type: B, input: /tmp/{topic_slug}-pdfs/seed.pdf, "
                 f"output: vault/journals/{topic_slug}/seed.md, topic: {topic_desc}")

    analysis = Read(f"vault/journals/{topic_slug}/seed.md")
    citations = parse_citation_section(analysis)
    create_manifest(manifest_path, seed, citations)
    Bash(f"python3 scripts/search/search.py metadata --manifest {manifest_path} --all")

# Phase 1-N: EXPAND
manifest = read_json(manifest_path)
for round_num in range(manifest["rounds_completed"] + 1, MAX_ROUNDS + 1):
    discovered = get_discovered(manifest, round_num)
    if not discovered:
        break

    Bash(f"python3 scripts/search/search.py metadata --manifest {manifest_path} --all")
    Agent("quasi:download-agent", foreground=True,
          prompt=f"manifest_path: {manifest_path}, mode: papers")

    acquired = get_acquired(manifest, round_num)
    for paper in acquired:
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: B, input: {paper.pdf_path}, "
                     f"output: vault/journals/{topic_slug}/{paper.key}.md, topic: {topic_desc}")

    while not all_analyzed:
        sleep(30)

    new_refs = 0
    for paper in acquired:
        refs = parse_citation_section(Read(f"vault/journals/{topic_slug}/{paper.key}.md"))
        new_refs += deduplicate_and_add(manifest, refs, round_num + 1)
    manifest["rounds_completed"] = round_num
    write_json(manifest_path, manifest)
    if new_refs == 0:
        break

# FINAL
if not exists(f"vault/journals/{topic_slug}-synthesis.md"):
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"source_name: {topic_desc}, "
                 f"analysis_dir: vault/journals/{topic_slug}/, "
                 f"output_path: vault/journals/{topic_slug}-synthesis.md, "
                 f"reading_list_path: vault/journals/{topic_slug}-reading-list.md, topic: ...")
```

## Manifest 格式

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

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 | `manifest.json` | 存在则跳过 |
| Phase N | `rounds_completed >= N` | 跳过已完成轮次 |
| FINAL | `synthesis.md` | 存在则跳过 |
