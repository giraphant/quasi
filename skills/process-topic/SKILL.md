---
name: quasi:process-topic
description: >
  Use when the user says "滚雪球", "process topic", "topic corpus", "citation chain",
  "expand references", or wants to build a topic-centred reading corpus by iteratively
  tracing citations from a seed paper. (前身: /quasi:citation-snowball, 2026-05-17 重命名)
---

# Process Topic — 主题语料(原: citation snowball)

种子论文 / 主题关键词 → 逐轮扩展引用链 → 饱和。扁平 agent 调度 + 主进程引用提取。

> 🚧 **本轮(2026-05-17)只改名,内部逻辑保留**。下一轮重做 SKILL.md 把入口泛化到 topic/keyword,
> 不仅是 seed paper(LAYERS.md Q snowball)。

## 调用方式

```
/quasi:process-topic {topic-slug} --seed {doi} --topic "{description}"
```

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成
- **每篇论文独立 dispatch 一个 analyse-agent**：禁止把多篇论文合并到一个 agent 调用中。一篇 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 编排架构

```
主进程 (dispatcher + 引用提取)
├─ Phase 0: SEED
│   ├─ download-agent → 种子 PDF
│   ├─ analyse-agent → 种子分析
│   └─ 主进程: 读引用段落 → 创建 manifest
├─ Phase 1-N: EXPAND (循环)
│   ├─ search.py metadata (Bash)
│   ├─ download-agent → 本轮 PDF
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
    Agent("quasi:download-agent", foreground=True,
          prompt=f"doi: {seed}, output_dir: /tmp/{topic_slug}-pdfs/, filename: seed")

    Agent("quasi:analyse-agent", foreground=True,
          prompt=f"type: B, input: /tmp/{topic_slug}-pdfs/seed.pdf, "
                 f"output: vault/topics/{topic_slug}/seed.md, topic: {topic_desc}")

    analysis = Read(f"vault/topics/{topic_slug}/seed.md")
    citations = parse_citation_section(analysis)
    create_manifest(manifest_path, seed, citations)
    
    # Per-entry metadata fetch (caller-side)
    for key, paper in manifest['papers'].items():
        doi = paper.get('doi')
        if not doi:
            continue
        out = subprocess.run(
            ['quasi-search', 'paper', '--doi', doi, '--json', '--shape', 'single'],
            capture_output=True, text=True, check=False,
        )
        if out.returncode != 0:
            continue
        resp = json.loads(out.stdout)
        if not resp.get('results'):
            continue
        rec = resp['results'][0]
        for field in ('title', 'authors', 'year', 'abstract', 'cited_by_count', 'is_oa', 'oa_url'):
            if rec.get(field) and not paper.get(field):
                paper[field] = rec[field]

# Phase 1-N: EXPAND
manifest = read_json(manifest_path)
for round_num in range(manifest["rounds_completed"] + 1, MAX_ROUNDS + 1):
    discovered = get_discovered(manifest, round_num)
    if not discovered:
        break

    # Per-entry metadata fetch (caller-side)
    for key, paper in manifest['papers'].items():
        doi = paper.get('doi')
        if not doi:
            continue
        out = subprocess.run(
            ['quasi-search', 'paper', '--doi', doi, '--json', '--shape', 'single'],
            capture_output=True, text=True, check=False,
        )
        if out.returncode != 0:
            continue
        resp = json.loads(out.stdout)
        if not resp.get('results'):
            continue
        rec = resp['results'][0]
        for field in ('title', 'authors', 'year', 'abstract', 'cited_by_count', 'is_oa', 'oa_url'):
            if rec.get(field) and not paper.get(field):
                paper[field] = rec[field]
    
    Agent("quasi:download-agent", foreground=True,
          prompt=f"manifest_path: {manifest_path}, mode: papers")

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
| TYPECHECK | 无 —— 幂等,可重复跑 | 上次 typecheck clean 时几乎无成本 |

## 目录结构

```
vault/topics/{topic-slug}/
├── manifest.json
├── seed.md
└── {paper-key}.md
vault/topics/{topic-slug}-synthesis.md     ← 主题综述（与目录同级）
vault/topics/{topic-slug}-reading-list.md  ← 阅读清单
/tmp/{topic-slug}-pdfs/
└── *.pdf
```

注：`vault/topics/` 是 bts 中「按主题汇集的专题文献集」的归宿，与 `vault/journals/`（process-journal 的真实期刊扫描产出）严格分层，不混用。
