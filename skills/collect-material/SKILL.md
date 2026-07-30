---
name: collect-material
description: Use when the user wants to search, download, analyse, translate, or transcribe a book, paper, author's representative works, existing PDF, meeting, or lecture recording into structured outputs.
---

# Collect Material — 材料采集与处理

## 任务

用一张确定性编排图,把 paper / book / author / talk 从采集或本地录制跑到分析,
或为已有 PDF 产出可验证的 Translation derivative。

## 输入

从用户请求归一化出:

- `kind`:`book` | `paper` | `author` | `talk` | `translate`
- 该 kind 的参数,统一塞进 `args`:
  - book:`slug`(可由 title+author 先经 search 定)、`meta{title,authors,isbn,year,publisher,category,format?,confidence,topic}`；publisher 必须来自用户或 metadata search 明确证据，category 缺省只用非猜测 fallback `other`；format 缺失保持 null/auto，绝不在 skill 预填 PDF
  - paper:`slug` + `meta{doi,title,authors,journal}`;top-level `translate` 可选布尔；
    显式为 true 时可另带 top-level `target_language/toc_json/toc_page_side`,由同一次
    shared Workflow run 产生附加 `translation_receipt`
  - author:`name` + `meta{full_name,topic,maxBooks,maxPapers}`
  - talk:完整读取并遵守
    [`references/talk.md`](references/talk.md)；该 reference 定义本地 media、
    title/date/slug 人闸、可选 engines/lang 和 Talk MaterialReceipt 的完整入口合同
  - translate:`slug` + exact `source_file`(可选;不提供时由 Graph reconcile) +
    `target_language|target`(归一化为 `target_language`) +
    `toc_json/toc_page_side`(可选)；人工 source decision 只来自 Graph typed gate

四个 material/collection kind 与一个 Translation derivative 都由同一 bundle
承担;递归复用是重点——`author` 直接调用同图中的 `processBook` / `processPaper`,
Translation 则保持独立 receipt,不伪装成 Material。

单本 `book|paper` 的输入归一化是强制前置阶段:

- 用户只给题名/自然语言引文、没有 ISBN(book) / DOI(paper)时,**先 dispatch `quasi:search-agent` 一次**,再做 Step 0 和启动图。Book 即使已有 ISBN，只要缺 publisher，也必须用同一个 metadata agent 以 ISBN/title/authors 补 publisher；不可让 identifier-bearing request 静默进入 identity block。不可先凭题名猜 year、publisher、journal、作者顺序、材料类型或 canonical slug。
- search 命中后以 `picked` 补齐 `title/authors/year/isbn|doi/oa_url/url/journal`;Book
  还必须合并有证据的 `publisher` 与显式
  `category=monograph|edited-volume|handbook|other`。采用 picked 按
  `{首列作者姓}-{短题名}-{year}` 给出的 canonical `slug`,同时保留用户明确的
  topic/translate 等意图字段。
- Book search 若因 publisher 无证据而返回 `picked=null` / low confidence,立即报告并在
  Workflow 前停止。Paper search 无可靠 picked 时才可保留用户明示字段,用 provisional
  slug 交 download-agent 做一次获取恢复。两者都不得在主进程改用 WebSearch、WebFetch 或 browser
  猜 metadata。

## 硬约束

- **topic / draft 不走本 skill**——topic 用 `precise-topic`,draft 用
  `finalize-draft`。Talk 是本 skill 的 `kind:talk` 分支；只有命中 Talk 意图时才读取
  `references/talk.md`。
- shared `workflows/process-material.mjs` 在 Claude Code 走 Workflow 工具,在 Pi
  走薄 runner,在 Codex GUI 走原生 subagent driver;主进程只做 Step 0
  本地召回/去重、归一化输入、人工卡点、LOCALISE 回填与报告。Translation
  reconcile/run/re-OCR 控制边属于同一 shared Graph,不得在 Skill 内复制。
- 主进程不得用通用 web/browser 工具旁路 quasi 的 search/download 合同。`download_failed` 时报告图回执的 `failure_reason/attempts`,不要临时改材料类型或抓活动页兜底。

## 状态

- 图产物照常落 `vault/` `processing/` `sources/`——全库统一命名空间、文件幂等续跑。
- **编排状态只活在本次图执行内,不落 skill manifest。** Paper / Book Material Loop 与 Author Collection Loop 的 strict writer 通过 exact-output reconciliation 和 typed receipt 续跑；unknown writer outcome fail closed，不能以“文件存在即 success”或同 run 重投代替 reconcile。Author、Talk、Translation 与 Topic 各自按其当前 typed receipt 合同处理；Paper/Book 不再保留旧 Agent 分派。
- Translation 使用独立 `quasi.derivative.translation.receipt/0.1`;Paper
  `material_receipt` 的完成事实与可选 derivative 独立。现有 PDF 或 staging 只能由
  `translation.reconcile` 的 fingerprint/hash/validation 证明,不得按文件存在跳过。
- Book auto format 只授权 `sources/{slug}.epub` 与 `sources/{slug}.pdf` 两个 exact
  candidates；download receipt 必须证明唯一 path/format pair。两者同时存在、path
  越界或 format 无法证明均 blocked，不由 skill/Graph 猜扩展名。
- LOCALISE 中译本缓存写入 `.quasi/localise/cndouban.json`,按原书 ISBN 幂等。

## Agent / Helper 合同

- Claude Code:通过 **Workflow 工具**调 `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`,把 `{kind, ...}` 作为 `args` 传入。
- Pi:把同一份 args 写到 `.quasi/temp/` JSON,运行 `quasi-pi-runner --script "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" --args-file <path>`;stdout 是最终 JSON 回执。
- Codex GUI:启动长驻 `quasi-codex-driver`,由**当前会话**响应其 JSONL `agent_request`,用原生 `spawn_agent` 启动 worker;这些 worker 必须登记在当前 thread 的 agent tree。启动前必须完整读取并遵守 `$CLAUDE_PLUGIN_ROOT/skills/collect-material/references/codex-native-driver.md`。只有当前宿主没有原生 subagent / 可续写 exec 工具时才回退 `quasi-codex-runner`。
- Codex 的 title-only metadata 前置搜索也必须是当前 thread 的可见原生 worker:用 `fork_turns:"none"` 和已注册的 `quasi_search` role(若当前 `spawn_agent` 暴露 `agent_type`)启动唯一 target;task name 采用 `metadata_{slug}_{id_suffix}` 这样的可读唯一名。无 role selector 时才让通用 worker 读取本插件 `agents/search-agent.md`。只返回该 agent 合同的 JSON,不要由主进程自己 WebSearch。
- 图内用 `agent(prompt, {agentType:'quasi:<name>'})` 起 worker
  agent(download/extract/analyse/synthesis/audit/translate)。
- 图不写 skill 状态文件;人工卡点由本 skill 主进程用 `AskUserQuestion` 处理。
- **Step 0 召回与 LOCALISE 是主进程(图外)的活**:图无 fs、不能调 bin,所以本地
  召回/去重与 `quasi-helpers localise scan|write` 由本 skill 主进程执行。
- LOCALISE 时按需 dispatch `search-agent`(kind=book,读 overview 搜 `localisations.zh.candidates`),主进程再用 `quasi-helpers localise write` 落盘;幂等于原书 ISBN。适用面:单本 book 的产物,和 author 跑落地的每本书(图回执带 `book_slugs` 名单)。
- TRANSLATE:Paper 的 top-level `translate:true` 随 Paper args 进入同一次 shared
  Workflow;直接翻译请求使用同 bundle 的 `kind:translate`。Skill 只消费
  `translation_receipt`、展示 typed gate 并在用户明确选择 source 后发起新 run;
  不直接 dispatch translate-agent,不根据文件存在跳过,不在同 run 重投 writer。

## 工作流

```
主进程(瘦入口:召回 + 编排 + 卡点 + 回填)
├─ 归一化 kind + args
├─ Step 0 本地召回/去重(图外,主进程)
│    ├─ paper:`quasi-helpers vault resolve` 命中且未请求 translate → return;
│    │         显式 translate=true → 采用 existing canonical slug 继续 Graph reconcile
│    ├─ book:同样 resolve 命中 → 报告 existing 并继续 strict Graph reconcile/audit，不直接 return
│    ├─ author:产物存在 → 只提示"增量更新",继续跑(累积型材料,重跑就是为了吸收新条目)
│    ├─ translate:不做 vault recall;把 exact source intent 交 translation.reconcile
│    ├─ 均 miss → rg 模糊召回近似 key → 命中则列候选,提示可能重复(勿盲目新建)
│    └─ 否则继续
├─ Workflow / quasi-pi-runner / quasi-codex-driver(process-material.mjs, {kind, ...args}) → 跑图(采集→分析),完成回 result
├─ 若有 translation_receipt:
│    ├─ complete          → 报告 derivative canonical/validation
│    ├─ source_selection  → AskUserQuestion(exact candidates)→带 source_decision 发起新 run
│    ├─ configuration     → 指向 /plugin Configure options,不自动重投
│    ├─ blocked/unknown   → 报告 failure/resume,绝不重投 writer
│    └─ failed            → 报告 typed failure;不改写 Paper MaterialReceipt
├─ 读 result.status:
│    ├─ ok               → 报告(kind 各异)→ LOCALISE
│    ├─ year_ambiguous   → (仅单本 book)AskUserQuestion(year_evidence 原样)→ 带决定重投
│    ├─ blocked          → 报告 typed receipt 的 exact failure/resume；不得同 run 重投 writer 或整张图
│    ├─ synth_failed     → 报告 known failure；Paper/Book/Author 均不得自动重投 writer 或整张图
│    ├─ audit_escalated  → 报告 escalated,交人工
│    └─ 其余一律按失败报出(枚举 ok,不枚举失败态)
├─ LOCALISE(book,及 author 的 book_slugs;ok 后,图外):localise scan → pending 则 search-agent → localise write
└─ marple open 最终产物(best-effort)
```

## 执行流程

```python
args = parse_request()   # kind + 该 kind 参数
if args.kind not in ("book", "paper", "author", "talk", "translate"):
    report(f"未知 kind: {args.kind}"); return
if args.kind == "talk":
    follow_reference("references/talk.md")  # 完整执行 Talk ingress 后 return
    return
if args.kind == "translate":
    args.target_language = args.get("target_language") or args.get("target") or "zh-CN"

# 单本 title-only 请求先走专用 metadata agent。Claude 用注册的
# Agent("quasi:search-agent");Codex 用当前 thread 原生 spawn_agent,worker 读取
# $CLAUDE_PLUGIN_ROOT/agents/search-agent.md;Pi 用其原生 subagent。主进程不做 web search。
identifier = (
    args.meta.get("isbn") if args.kind == "book"
    else args.meta.get("doi") if args.kind == "paper"
    else None
)
needs_metadata = (
    args.kind in ("book", "paper")
    and (
        not identifier
        or (args.kind == "book" and not args.meta.get("publisher"))
    )
)
if needs_metadata:
    metadata = Agent("quasi:search-agent", foreground=True,
                     prompt=f"kind: {args.kind}\ntitle: {args.meta.get('title')}\n"
                            f"author: {first(args.meta.get('authors'))}\n"
                            f"identifier: {identifier}\n"
                            "book picked must include evidence-backed publisher and category\n"
                            "return one verified picked record with canonical slug")
    picked = metadata.get("picked")
    picked_confidence = picked.get("confidence") if picked else "low"
    trusted_picked = (
        picked
        and picked_confidence in ("high", "medium")
        and metadata.confidence != "low"
    )
    if args.kind == "book" and not trusted_picked:
        report("Book metadata 无可靠 picked/publisher evidence；未启动 Workflow"); return
    if trusted_picked:
        intent = pick(
            args,
            "topic",
            "translate",
            "target_language",
            "toc_json",
            "toc_page_side",
        )
        args.meta = merge_non_null(args.meta, picked)
        # search-agent uses high|medium for its own candidate judgement; the
        # Workflow ingress contract records that accepted judgement as verified.
        args.meta["confidence"] = "verified"
        args.slug = picked.slug
        args |= intent
if args.kind == "paper" and not args.meta.get("journal"):
    # Search adapters may expose a proceedings/book container as container_title
    # or venue. Paper identity uses the same bibliographic fact under `journal`.
    args.meta["journal"] = (
        args.meta.get("container_title") or args.meta.get("venue")
    )
if args.kind == "book":
    if not args.meta.get("publisher"):
        report("Book publisher 无可靠 metadata evidence；未启动 Workflow"); return
    # category is not bibliographic identity; use an explicit non-guess fallback.
    args.meta["category"] = args.meta.get("category") or "other"
    # Missing format is intentional auto negotiation inside the strict download handoff.
    # Do not inject a PDF default.

# 该 kind 的主键 + 最终产物路径
if args.kind == "book":    key, product = args.slug, f"vault/books/{args.slug}/00-overview.md"
elif args.kind == "paper": key, product = args.slug, f"vault/papers/{args.slug}.md"
elif args.kind == "author": key, product = args.name, f"vault/authors/{args.name}.md"
else:                       key, product = args.slug, None                  # translate

# Step 0: 本地召回/去重(主进程,图外)——mirror process-{book,paper,author} Step 0
# book/paper 走确定性三级匹配(slug 精确 → ISBN/DOI → 标题+作者姓):同一作品换个 slug 也认得出,
# 不靠 LLM 眼力。title/authors 一定要带上——vault 条目自己没 ISBN/DOI 时前两级必然 miss。
# author 无标识符,用产物路径。
if args.kind in ("book", "paper"):
    ident = {"isbn": args.meta.get("isbn")} if args.kind == "book" else {"doi": args.meta.get("doi")}
    ident |= {"title": args.meta.get("title"), "authors": args.meta.get("authors")}
    resolve_items = [{"kind": args.kind, "slug": key, **ident}]
    resolve_items_file = write_temp_json(resolve_items)  # helper-owned exact path under .quasi/temp/
    resolve_result = parse_json(Bash(
        f"quasi-helpers vault resolve --items-file '{resolve_items_file}'"
    ).stdout)
    hit = resolve_result["resolved"][0]
    if hit["vault_slug"]:
        if args.kind == "paper":
            if not args.get("translate"):
                report(f"已有产物({hit['match']} 命中): {hit['path']}"); return
            # 显式 derivative 仍须进入 Graph；已有 Paper 只证明 Material，
            # 不证明 Translation generation。
            report(f"已有 Paper 产物({hit['match']} 命中),继续 strict translation reconcile")
            key = hit["vault_slug"]
            args.slug = key
            product = f"vault/papers/{key}.md"
        # Strict Book 仍让 Graph 对 exact artifacts 做 typed reconciliation + audit。
        # resolver 命中不同 slug 时采用已存在的 canonical owner，避免创建重复路径。
        else:
            report(f"已有 Book 产物({hit['match']} 命中),进入 strict reconcile: {hit['path']}")
            key = hit["vault_slug"]
            args.slug = key
            product = f"vault/books/{key}/00-overview.md"
elif args.kind == "author" and exists(product):
    # author 是累积型材料:存在不是终止条件。strict Author 图会只读观察 exact output，
    # 让每个候选仍进入其 Paper/Book Material Loop 做 typed reconcile/audit，再由
    # author.synthesise 对 exact child canonicals 做 repair/reconciled；不能把存在直接
    # 升级成完成，也不能让 Author 自己理解 child 内部阶段。
    report(f"已有产物,本次为增量更新: {product}")
if args.kind in ("book", "paper", "author"):
    dup = rg_fuzzy_recall(key, args.meta)   # 兜底:候选没带 ISBN/DOI 时的近似命中
    if dup.candidates:
        report_candidate_list(dup.candidates, note="rg fuzzy recall only; 可能重复,勿盲目新建")

# 跑图。book/paper 传 slug+meta;author 传 name+meta。Claude 与 Pi 共用同一脚本/args。
def run_graph(wf_args):
    if env("PI_CODING_AGENT") == "true":
        wf_file = write_temp_json(wf_args)   # .quasi/temp/
        return parse_json(Bash(f"quasi-pi-runner --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
                               f"--args-file '{wf_file}'").stdout)
    if env("CODEX_THREAD_ID"):
        wf_file = write_temp_json(wf_args)   # .quasi/temp/
        if has_tools("spawn_agent", "wait_agent", "followup_task",
                     "interrupt_agent", "resumable_exec"):
            return drive_codex_native(
                command=f"quasi-codex-driver --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
                        f"--args-file '{wf_file}' --cwd '$CLAUDE_PROJECT_DIR'",
                protocol="quasi-codex-driver/1")
        return parse_json(Bash(
            f"quasi-codex-runner --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{wf_file}' --cwd '$CLAUDE_PROJECT_DIR'").stdout)
    return Workflow(scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs", args=wf_args)

if args.kind == "translate":
    wf_args = {
        "kind": "translate",
        "slug": key,
        "target_language": args.target_language,
    }
    for field in ("source_file", "toc_json", "toc_page_side"):
        if args.get(field) is not None:
            wf_args[field] = args[field]
else:
    wf_args = {"kind": args.kind, "meta": args.meta}
    wf_args["slug" if args.kind != "author" else "name"] = key
    if args.kind == "paper" and args.get("translate"):
        wf_args["translate"] = True
        for field in ("target_language", "toc_json", "toc_page_side"):
            if args.get(field) is not None:
                wf_args[field] = args[field]
result = run_graph(wf_args)

# 人工卡点:仅单本 book 会 year_mismatch/year_ambiguous(author 批量自动收、不冒泡)。
# 两者都把候选留在 exact tmp_path。第二次调用必须带 Graph 定义的 exact year_decision
# envelope；不能让用户另填 slug/path/evidence，也不能把它偷换成 batch_accept_year。
if result.status in ("year_mismatch", "year_ambiguous"):
    prior_slug = wf_args["slug"]
    prior_meta = wf_args["meta"]
    prior_tmp_path = result["tmp_path"]
    prior_year_evidence = result["year_evidence"]
    recommended_year = prior_year_evidence.get("recommended_year")
    year_options = ["accept-current", "reject"]
    if (prior_year_evidence.get("verdict") == "MISMATCH"
            and recommended_year is not None):
        year_options.insert(1, "use-recommended-year")
    year_choice = AskUserQuestion(
        present={
            "tmp_path": prior_tmp_path,
            "year_evidence": prior_year_evidence,
        },
        options=tuple(year_options),
    ).choice
    if year_choice == "reject":
        report("用户拒绝年份候选；保留 prior tmp_path，未重投 Workflow"); return
    if year_choice == "use-recommended-year":
        prior_year = prior_meta.get("year")
        prior_year_suffix = f"-{prior_year}"
        if recommended_year is None or not prior_slug.endswith(prior_year_suffix):
            report("recommended_year 或 canonical slug year suffix 无法证明；未重投 Workflow"); return
        wf_args["slug"] = (
            prior_slug.removesuffix(prior_year_suffix) + f"-{recommended_year}"
        )
        wf_args["meta"] = {**prior_meta, "year": recommended_year}
    # accept-current 有意保持 wf_args.slug 与 wf_args.meta 字节语义不变。
    wf_args["year_decision"] = {
        "action": year_choice,
        "tmp_path": prior_tmp_path,
        "year_evidence": prior_year_evidence,
    }
    result = run_graph(wf_args)

# Strict Paper/Book/Author writer policy remains unchanged; Translation receipt handling below
# only consumes a typed gate or starts a user-authorized new reconcile run.
# Translation 是独立 Derivative receipt，不由 Paper MaterialReceipt 冒充。
# source ambiguity 是唯一在本流程内取用户决定后新开一次 run 的 gate；它不是
# writer retry。configuration gate 只引导 Configure 后结束本次流程。
translation_requested = (
    args.kind == "translate"
    or (args.kind == "paper" and args.get("translate") is True)
)
translation_receipt = result.get("translation_receipt")
legacy_translation_status = result.get("translation_status")
if translation_requested and not translation_receipt:
    report("translation contract invalid: 缺少 translation_receipt"); return
def expected_translation_legacy(receipt):
    if receipt.get("status") == "complete":
        return "success"
    if receipt.get("status") == "failed":
        return "error"
    if receipt.get("status") != "blocked":
        return None
    gate_kind = (receipt.get("gate") or {}).get("kind")
    if gate_kind == "source_selection":
        return "needs_source_selection"
    if gate_kind == "configuration_required":
        return "needs_auth"
    return "blocked"

if translation_receipt:
    expected_legacy = expected_translation_legacy(translation_receipt)
    if not expected_legacy:
        report("translation receipt terminal status invalid"); return
    if legacy_translation_status and legacy_translation_status != expected_legacy:
        report("translation legacy status 与 translation_receipt 冲突"); return

if translation_receipt and translation_receipt.get("status") == "blocked":
    gate = translation_receipt.get("gate")
    if gate and gate.get("kind") == "source_selection":
        if wf_args.get("source_decision") is not None:
            report("translation source gate 重复出现；未再次询问或重投"); return
        source_choice = AskUserQuestion(
            present={
                "derivative_key": translation_receipt.get("derivative_key"),
                "candidates": gate["candidates"],
                "candidates_fingerprint": gate["candidates_fingerprint"],
            },
            options=tuple(candidate["path"] for candidate in gate["candidates"]),
        ).choice
        selected = exactly_one(
            candidate for candidate in gate["candidates"]
            if candidate["path"] == source_choice
        )
        wf_args["source_decision"] = {
            "path": selected["path"],
            "sha256": selected["sha256"],
            "candidates_fingerprint": gate["candidates_fingerprint"],
        }
        # 用户决定后的显式新 run 从 translation.reconcile 开始；不 resume JS cursor，
        # 不重投 prior writer，也不允许 Agent 自己选择 source。
        result = run_graph(wf_args)
        translation_receipt = result.get("translation_receipt")
        legacy_translation_status = result.get("translation_status")
        if not translation_receipt:
            report("translation contract invalid after source decision"); return
        expected_legacy = expected_translation_legacy(
            translation_receipt
        )
        if not expected_legacy or (
            legacy_translation_status
            and legacy_translation_status != expected_legacy
        ):
            report("translation receipt/legacy status invalid after source decision"); return
    elif gate and gate.get("kind") == "configuration_required":
        report(
            f"Translation 配置缺失:{gate.get('missing_fields')};"
            "请到 /plugin → Configure options；本次不自动重投"
        ); return
    else:
        report(
            f"Translation blocked:{translation_receipt.get('failure')};"
            f"resume={translation_receipt.get('resume')};绝不自动重投 writer"
        ); return

if translation_receipt:
    if translation_receipt.get("status") == "blocked":
        gate = translation_receipt.get("gate")
        if gate and gate.get("kind") == "configuration_required":
            report(
                f"Translation 配置缺失:{gate.get('missing_fields')};"
                "请到 /plugin → Configure options；本次不自动重投"
            ); return
        report(
            f"Translation blocked:{translation_receipt.get('failure')};"
            f"resume={translation_receipt.get('resume')};绝不自动重投 writer"
        ); return
    if translation_receipt.get("status") == "failed":
        report(f"Translation failed:{translation_receipt.get('failure')}")
        if args.kind == "translate":
            return
    elif translation_receipt.get("status") == "complete":
        canonical = exactly_one(
            artifact for artifact in translation_receipt["artifacts"]
            if artifact["role"] == "canonical"
        )
        report(
            f"Translation {translation_receipt.get('disposition')}:"
            f"{canonical['path']}; validation={translation_receipt.get('validation')}"
        )
        if args.kind == "translate":
            product = canonical["path"]
    else:
        report("translation receipt terminal status invalid"); return

# Strict Paper/Book/Author/Translation writer 都只允许一次 invocation。null/timeout/cancel/畸形
# receipt 不能盲目重投。唯一可自动发起的新 run 是 Paper acquisition 的只读式
# reconciliation：receipt 明确要求 paper.reconcile，且 exact source 已存在，因此下一次
# acquire invocation 只能核验 existing target，不允许再次 fetch。该新 run 最多一次。
if result.status == "blocked":
    typed = (
        result.get("translation_receipt")
        or result.get("collection_receipt")
        or result.get("material_receipt")
    )
    failure = (typed or {}).get("failure") or {}
    resume = (typed or {}).get("resume") or {}
    safe_paper_acquire_reconcile = (
        args.kind == "paper"
        and failure.get("code") == "paper.writer_receipt_mismatch"
        and failure.get("operation_key") in ("paper.acquire", "paper.download.legacy")
        and failure.get("outcome") == "unknown"
        and resume.get("operation_key") == "paper.reconcile"
        and exists(f"sources/{key}.pdf")
    )
    if safe_paper_acquire_reconcile:
        report(
            "Paper acquisition 回执未知，但 exact source 已存在；"
            "发起一次 bounded paper.reconcile 新 run（只核验 existing target，不再 fetch）"
        )
        result = run_graph(wf_args)
        typed = result.get("material_receipt")
    if result.status == "blocked":
        typed = typed or result.get("material_receipt")
        report(
            f"blocked: stage={(typed or {}).get('stage')};"
            f"failure={(typed or {}).get('failure') or result};"
            f"resume={(typed or {}).get('resume')};"
            "未绕过合同或继续重投 writer"
        ); return

if result.status == "audit_escalated":
    report(f"audit 仍 escalated:{result.escalated};交人工"); return
# chapters_incomplete = 章分析没跑齐(通常是瞬时 API 错误连着打死同一章)。产物本身没坏,
# 重跑本 skill 只会补缺的那几章(已完成的章 agent 见文件即 no-op),所以提示重跑而不是报死。
if result.status == "chapters_incomplete":
    report(f"章节残缺 expected={result.get('expected_slots')}, "
           f"present={result.get('present_slots')}, missing={result.get('missing_slots')};"
           "仅 caller 下一次 run 可补缺章"); return
# 兜底:枚举**成功**态,不枚举失败态。图里 processBook 把 download-agent 的 status 原样上抛,
# 那个枚举会长(year_mismatch 就这么漏过一次),枚举失败态迟早再漏一个,而漏掉的后果是
# 静默报成功——最坏的一种。不是 ok 就是没跑成,一律报出来。
paper_material_complete = (
    args.kind == "paper"
    and result.get("material_receipt")
    and result["material_receipt"].get("status") == "complete"
)
if result.status != "ok" and not (
    args.kind == "translate"
    and translation_receipt
    and translation_receipt.get("status") == "complete"
) and not (
    paper_material_complete
    and translation_receipt
    and translation_receipt.get("status") in ("complete", "failed")
):
    report(f"失败:{result.status}; {result.get('failure_reason') or result.get('notes') or ''}"); return

# 成功报告(kind 各异)
if args.kind == "book" and result.get("year_warning"):
    report(f"完成,但年份存疑:{result.year_warning}")
if args.kind == "author":
    report(f"作者完成:{result.books} 本书 / {result.papers} 篇论文"
           + (f";{len(result.year_warnings)} 本年份存疑" if result.get("year_warnings") else "")
           + (f";{result.book_failures}+{result.paper_failures} 项获取失败" if result.book_failures or result.paper_failures else ""))
# LOCALISE 中译本回填:单本 book 用 [key];author 用图回执的 book_slugs 名单(scan 按
# ISBN 幂等,已回填过的书 pending=0 秒过,所以名单里混着历史入库的书也没有代价)。paper 无。
localise_slugs = [key] if args.kind == "book" else (result.get("book_slugs") or [])
for slug in localise_slugs:
    scan = Bash(f"quasi-helpers localise scan --path vault/books/{slug} --json")
    if scan.pending > 0:
        overview = f"vault/books/{slug}/00-overview.md"
        search = Agent("quasi:search-agent", foreground=True,
                       prompt=f"kind: book\ncontext: read {overview} and search metadata/localisations")
        candidates_file = write_temp_json(search.localisations.zh.candidates)   # .quasi/temp/
        Bash(f"quasi-helpers localise write --book-path {overview} --candidates-file {candidates_file}")

# marple open 最终产物(best-effort UX;失败不影响流程)
Bash(f"/opt/homebrew/bin/marple-cli open '{product}' || marple-cli open '{product}' || echo skip")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
| ------ | ------ | --------- |
| Step 0 召回 | `quasi-helpers vault resolve`(slug 精确 → ISBN/DOI → 标题+作者姓);均 miss 后 rg 模糊召回 | paper 命中跳过；book 命中采用 existing canonical slug 并继续 strict reconcile/audit；author 走增量；模糊命中只列候选 |
| Book spine(图) | typed operation receipts + exact artifact reconciliation | succeeded/reconciled 可继续；unknown writer outcome 当次 blocked，caller 下一 run audit/reconcile，绝不在同 run 重投 |
| 批量条目(author) | 图内 `author.resolve-membership` 只读关联，随后每个 unique demand 进入 child Material Loop | 只有 exact child MaterialReceipt complete + canonical artifact 才进入 Author synth；存在性本身不算完成 |
| Author output(图) | `collection_receipt` + exact child receipts + author.synthesise/audit receipts | identical corpus 可 reconciled；unknown Author writer blocked，下一次从 author.reconcile 观察 |
| 卡点重投 | `year_decision` | 用户拍板后带决定重投,只补未定的一步 |
| LOCALISE | `.quasi/localise/cndouban.json#by_isbn[isbn]` | 已有 entry(found/none)则 helper scan 跳过 |
| TRANSLATE | `translation_receipt` + exact source/output hash、manifest fingerprint、validation | 只有 Graph reconcile 证明 committed generation 才 reused；文件存在、staging 或 provider prose 均不能跳过 |

## 输出

```
sources/{book-slug}.{epub,pdf}
processing/chapters/{book-slug}/{manifest.json,*.txt}
vault/books/{book-slug}/{00-overview.md,ch{slot}-*.md}
vault/papers/{paper-slug}.md
vault/authors/{author-name}.md
processing/translations/{slug}-{full-lowercase-tag}.pdf
                                                       ← 例如 zh-CN → -zh-cn.pdf;仅 receipt complete
processing/translations/{slug}-{full-lowercase-tag}.manifest.json
                                                       ← derivative commit proof
.quasi/localise/cndouban.json                          ← 中译本缓存(按原书 ISBN 幂等)
```
