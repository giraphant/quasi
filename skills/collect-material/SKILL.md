---
name: collect-material
description: Use when the user wants to process or collect one or more papers, articles, or books; handle an existing PDF; analyse an author's works; translate a PDF; or transcribe a meeting or lecture recording.
---

# Collect Material

## 任务

把用户的材料请求交给统一 Workflow，并负责解释 typed result、处理人工卡点和报告故障。

## 输入

从用户请求提取 `kind` 和仍然可观察的原始字段，不在 Skill 中补全书目：

- Book：`title|isbn` 至少一个；可带 `authors/year/publisher/category/format`。
- Paper：`title|doi` 至少一个；可带 `authors/year/journal/oa_url/url`。
- Batch：同一用户请求中的 2–32 个 Book/Paper；可混合两种 kind，每项保留自己的
  原始字段和可选 derivative 参数。
- Author：`name` 与 `meta{full_name,topic,maxBooks,maxPapers}`。
- Talk：完整读取并执行 [`references/talk.md`](references/talk.md)。
- Translation：`slug`、可选 exact `source_file`、`target_language`，以及可选
  `toc_json/toc_page_side`。

Book/Paper 的 canonical slug、作者顺序、年份、identifier、publisher/journal 和已有
canonical owner 都由图内 `Recall → Search → Resolve` 决定。用户明确给出的 slug 只作为
查询提示；Skill 不根据题名自行生成写入路径。

Paper 可带 `translate:true`，在同一次图执行中请求独立 Translation derivative。

## 硬约束

- 收到 Book/Paper 请求后立即启动图。不要在图前 dispatch metadata Agent、运行
  `quasi-helpers vault resolve`、做 rg 模糊查重或按文件存在提前返回。
- 同一请求含 2–32 个 Book/Paper 时，必须构造一个 `kind:"batch"` envelope 并只调用
  **一次** Workflow。禁止 `for item: Workflow(...)`，禁止把一批材料展开成多张同名图。
- 不用通用 WebSearch、WebFetch 或 browser 替代 quasi 的 metadata/acquisition 合同。
- Skill 不解释 Agent 内部步骤，也不从 prose 猜成功。只消费
  `ingress_receipt`、`material_receipt`、`collection_receipt` 或
  `translation_receipt`。
- Writer 的 null、timeout、cancel、畸形 receipt 或 unknown outcome 都不自动重投。
  报告 exact failure/resume，等待用户决定或下一次明确调用。
- Topic 使用 `precise-topic`；draft 使用 `finalise-draft`。

## 状态

- Workflow 在本次执行中拥有 Recall、Search、Acquire、Prepare、Analyse、Synthesise、
  Audit 的控制边。
- Material 产物写入 `sources/`、`processing/` 和 `vault/`；Skill 不维护第二份 material
  manifest。
- `quasi.material-ingress.receipt/0.1` 记录原始请求如何变成 canonical identity。
- Paper/Book 使用 `quasi.material-loop.receipt/0.1`；Author 使用 collection receipt；
  Translation 使用 `quasi.derivative.translation.receipt/0.1`。
- Batch 使用 `quasi.collection.material-batch.receipt/0.1`，按输入顺序记录每项
  `complete|needs_input|blocked|failed`；一个卡点不取消其它材料。
- Paper 的 `material_receipt` 与可选 Translation derivative 相互独立；Derivative 失败
  不改写已经证明 complete 的 Paper MaterialReceipt。
- 用户决定只通过下一次 Workflow args 进入图，不修改旧 receipt。

## Agent / Helper 合同

- Claude Code：用 **Workflow 工具**调用
  `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`。
- Pi：把 args 写入 `.quasi/temp/`，调用
  `quasi-pi-runner --script "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" --args-file <path>`。
- Codex GUI：先完整读取
  [`references/codex-native-driver.md`](references/codex-native-driver.md)，再运行
  `quasi-codex-driver`，由当前 thread 的原生 subagents 回应 JSONL `agent_request`。
  没有原生 subagent / resumable exec 时才用 `quasi-codex-runner`。
- 图内 Agent 类型、operation envelope、schema 和 retry policy 由 Workflow 提供；
  Skill 不直接启动 metadata/download/extract/analyse/synthesis/audit Agent。
- LOCALISE 是完成后的可选 sidecar：仅在 Book 或 Author material 已 complete 时，
  `quasi-helpers localise scan` 可触发一次 `localisation-agent`，再由 helper 写缓存。
  单本使用 `result.slug`；Author 只遍历 `result.get("book_slugs")` 的 exact child 清单。

## 工作流

```text
用户请求
  │
  ├─ Skill：识别 kind，保留原始提示
  │
  ▼
一次 Workflow（单项或 2–32 项 batch）
  Recall       本地只读召回；不把存在性当完成
  Search       规范 metadata，并用完整身份 resolve canonical owner
  Acquire      获取或核验 exact source
  Prepare      text/OCR/chapter/transcript 等结构化准备
  Analyse      写 exact Paper/Chapter/Talk canonical
  Synthesise   写 Book/Author 汇总产物
  Audit        验证 exact schema；按 producer owner 做一次有界修复
  │
  ▼
Skill：汇总整批进度与产物，集中展示 needs_input / blocked / failed
```

Author/Topic 图内已经产生 verified child identity 时，可直接进入 child Material Loop；
只有顶层单 Book/Paper 请求执行 ingress Recall/Search，避免重复检索。

## 执行流程

```python
requests = parse_user_requests()
if not requests:
    report("没有可处理的材料")
    return
if any(
    request.kind not in ("book", "paper", "author", "talk", "translate")
    for request in requests
):
    report(f"未知材料类型: {request.kind}")
    return

if len(requests) > 1:
    if len(requests) > 32 or any(
        request.kind not in ("book", "paper")
        for request in requests
    ):
        report("批量入口只接受 2–32 个 Book/Paper")
        return
    items = []
    for request in requests:
        raw = project_only_known_fields(request)
        item = {"kind": request.kind, "request": raw}
        if request.explicit_slug:
            item["slug"] = request.explicit_slug
        for field in (
            "translate",
            "target_language",
            "toc_json",
            "toc_page_side",
        ):
            if request.get(field) is not None:
                item[field] = request[field]
        items.append(item)
    # One batch request means exactly one Workflow row in Claude Code.
    wf_args = {"kind": "batch", "items": items}
    request = {"kind": "batch"}
else:
    request = requests[0]

if request.kind == "talk":
    follow_reference("references/talk.md")
    return

if request.kind == "batch":
    pass  # wf_args was built above; do not loop over run_graph.
elif request.kind in ("book", "paper"):
    raw = project_only_known_fields(request)
    wf_args = {"kind": request.kind, "request": raw}
    if request.explicit_slug:
        wf_args["slug"] = request.explicit_slug
    for field in (
        "translate",
        "target_language",
        "toc_json",
        "toc_page_side",
    ):
        if request.get(field) is not None:
            wf_args[field] = request[field]
elif request.kind == "author":
    wf_args = {
        "kind": "author",
        "name": request.name,
        "meta": request.meta,
    }
else:
    wf_args = {
        "kind": "translate",
        "slug": request.slug,
        "target_language": (
            request.target_language or request.target or "zh-CN"
        ),
    }
    for field in ("source_file", "toc_json", "toc_page_side"):
        if request.get(field) is not None:
            wf_args[field] = request[field]

def run_graph(args):
    args_file = write_temp_json(args)  # .quasi/temp/
    if env("PI_CODING_AGENT") == "true":
        return parse_json(Bash(
            "quasi-pi-runner "
            "--script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{args_file}'"
        ).stdout)
    if env("CODEX_THREAD_ID"):
        if has_tools(
            "spawn_agent",
            "wait_agent",
            "followup_task",
            "interrupt_agent",
            "resumable_exec",
        ):
            return drive_codex_native(
                command=(
                    "quasi-codex-driver "
                    "--script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
                    f"--args-file '{args_file}' --cwd '$CLAUDE_PROJECT_DIR'"
                ),
                protocol="quasi-codex-driver/1",
            )
        return parse_json(Bash(
            "quasi-codex-runner "
            "--script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{args_file}' --cwd '$CLAUDE_PROJECT_DIR'"
        ).stdout)
    return Workflow(
        scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
        args=args,
    )

result = run_graph(wf_args)

# Batch is one Workflow with independently progressing material loops. Interpret every child from
# the correlated `results[index]`; never rediscover paths or launch one Workflow per failed item.
if request.kind == "batch":
    batch = result.get("batch_receipt")
    entries = result.get("results")
    if (
        not batch
        or batch.get("schema_version")
            != "quasi.collection.material-batch.receipt/0.1"
        or not isinstance(entries, list)
        or len(entries) != batch.get("total")
    ):
        report("批量回执缺失或无法与输入逐项对账")
        return
    report_batch_progress(
        counts=batch["counts"],
        items=batch["items"],
    )
    for entry in entries:
        child = entry.get("result") or {}
        if entry.get("status") == "complete":
            report_completed_artifacts(child)
            maybe_localise_completed_books(child)
        elif entry.get("status") in (
            "needs_input",
            "blocked",
            "failed",
        ):
            report_batch_item_gate_or_failure(
                request_id=entry.get("request_id"),
                status=entry.get("status"),
                result=child,
            )
    # Any follow-up decisions are collected first, then submitted as one new batch containing
    # only affected original items. Never call run_graph separately inside this loop.
    return

# 顶层 Book/Paper 身份入口。
ingress = result.get("ingress_receipt")
if request.kind in ("book", "paper"):
    if not ingress:
        report("材料入口合同缺失；未继续解释下游状态")
        return
    if ingress["status"] == "needs_input":
        report_user_gate(
            stage=ingress["stage"],
            request=ingress["request"],
            failure=ingress["failure"],
        )
        return
    if ingress["status"] in ("blocked", "failed"):
        report(
            f"材料入口 {ingress['status']}: "
            f"stage={ingress['stage']}; failure={ingress['failure']}; "
            f"resume={ingress['resume']}"
        )
        return
    if ingress["status"] != "resolved":
        report("材料入口 receipt 状态无效")
        return

# Book 年份证据卡点。用户决定后发起一个新 run，不 resume 旧 JS cursor。
if result.status in ("year_mismatch", "year_ambiguous"):
    evidence = result["year_evidence"]
    choice = AskUserQuestion(
        present={
            "tmp_path": result["tmp_path"],
            "year_evidence": evidence,
        },
        options=allowed_year_actions(evidence),
    ).choice
    if choice == "reject":
        report("用户拒绝该候选；保留临时证据，不重投")
        return
    wf_args["year_decision"] = {
        "action": choice,
        "tmp_path": result["tmp_path"],
        "year_evidence": evidence,
    }
    result = run_graph(wf_args)

# Translation source ambiguity是另一种显式用户卡点。
translation = result.get("translation_receipt")
if translation and translation.get("status") == "blocked":
    gate = translation.get("gate")
    if gate and gate.get("kind") == "source_selection":
        selected_path = AskUserQuestion(
            present={
                "candidates": gate["candidates"],
                "candidates_fingerprint": gate["candidates_fingerprint"],
            },
            options=tuple(
                candidate["path"] for candidate in gate["candidates"]
            ),
        ).choice
        selected = exactly_one(
            candidate
            for candidate in gate["candidates"]
            if candidate["path"] == selected_path
        )
        wf_args["source_decision"] = {
            "path": selected["path"],
            "sha256": selected["sha256"],
            "candidates_fingerprint": gate["candidates_fingerprint"],
        }
        # 用户决定后开启一个显式新 run；不 resume 旧 cursor 或重投 prior writer。
        result = run_graph(wf_args)
        translation = result.get("translation_receipt")
    elif gate and gate.get("kind") == "configuration_required":
        report(
            f"Translation 配置缺失: {gate.get('missing_fields')}；"
            "请在 /plugin → Configure options 填写，本次不重投"
        )
        return

typed = (
    result.get("batch_receipt")
    or
    result.get("translation_receipt")
    or result.get("collection_receipt")
    or result.get("material_receipt")
    or result.get("ingress_receipt")
)
if result.status == "blocked":
    report(
        f"blocked: stage={(typed or {}).get('stage')}; "
        f"failure={(typed or {}).get('failure')}; "
        f"resume={(typed or {}).get('resume')}"
    )
    return
if result.status != "ok" and not derivative_completed(result):
    report_typed_failure(result, typed)
    return

report_completed_artifacts(result)
maybe_localise_completed_books(result)
best_effort_open_primary_artifact(result)
```

## 断点续跑

| 状态 | Skill 行为 |
| --- | --- |
| Batch `partial` | 报告所有 item 状态；集中收集决定，下一次只把受影响项组成一张新 batch 图 |
| Batch `blocked|failed` | 保留已完成项，逐项报告 failure；不重新运行整批或单独重投 writer |
| ingress `needs_input` | 展示 query 与缺失/冲突证据；用户修正请求后开启新 run |
| ingress `blocked` | 报告 exact operation/failure/resume；不在当前 run 重投 |
| Book `year_mismatch|year_ambiguous` | 展示原始 evidence；仅把用户选择放进 `year_decision` 新 run |
| Translation source gate | 逐字选择 typed candidate，带 fingerprint 发起新 run |
| writer outcome unknown | 停止并报告；下一次用户调用从图内 Recall/reconcile 重新观察 |
| complete | 报告 canonical artifacts；可做 LOCALISE sidecar 和 best-effort open |

## 输出

主要输出由 typed receipts 决定，常见路径为：

```text
sources/{slug}.{pdf|epub}
processing/papers/{slug}/source.txt
processing/chapters/{slug}/{manifest.json,*.txt}
vault/papers/{slug}.md
vault/books/{slug}/{00-overview.md,ch{slot}-*.md}
vault/authors/{author}.md
processing/translations/{slug}-{language}.pdf
.quasi/localise/cndouban.json
```

不要根据路径模板自行宣告成功；只报告 receipt 中 `exists:true` 且属于 exact role 的产物。
