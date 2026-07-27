from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def active_skill_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "agents").glob("*.md"))


def frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(?:>\s*)?\n(?P<body>(?:  .*\n)+)", text, re.MULTILINE)
    if match:
        return " ".join(line.strip() for line in match.group("body").splitlines())

    match = re.search(r"^description:\s*(?P<body>.+)$", text, re.MULTILINE)
    return match.group("body").strip() if match else ""


def test_skill_orchestration_contract_doc_exists():
    doc = PLUGIN_ROOT / "docs" / "SKILL_ORCHESTRATION.md"

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "## Runtime vs Maintainer" in text
    assert "## Skill File Schema" in text
    assert "## Ownership" in text
    assert "## Phase Contract" in text
    assert "## State" in text
    assert "输出" in text


def test_active_skills_follow_runtime_schema():
    required_sections = [
        "## 任务",
        "## 输入",
        "## 硬约束",
        "## 状态",
        "## Agent / Helper 合同",
        "## 工作流",
        "## 执行流程",
        "## 断点续跑",
        "## 输出",
    ]
    offenders: list[str] = []
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(PLUGIN_ROOT)
        for section in required_sections:
            if section not in text:
                offenders.append(f"{rel}: missing {section}")
        for forbidden in ("## 调用方式", "## 编排契约", "docs/SKILL_ORCHESTRATION.md"):
            if forbidden in text:
                offenders.append(f"{rel}: runtime skill contains maintainer-only text {forbidden!r}")

    assert offenders == []


def test_frontmatter_descriptions_are_routing_hints():
    offenders: list[str] = []

    for path in active_skill_files():
        desc = frontmatter_description(path)
        rel = path.relative_to(PLUGIN_ROOT)
        if not desc.startswith("Use when the user wants to "):
            offenders.append(f"{rel}: skill description should be user-intent facing")
        if len(desc) > 220:
            offenders.append(f"{rel}: skill description too long")
        for forbidden in ("user says", "前身", "Phase", "→"):
            if forbidden in desc:
                offenders.append(f"{rel}: description contains {forbidden!r}")

    for path in active_agent_files():
        desc = frontmatter_description(path)
        rel = path.relative_to(PLUGIN_ROOT)
        if not desc.startswith("Worker for "):
            offenders.append(f"{rel}: agent description should be worker-facing")
        if len(desc) > 220:
            offenders.append(f"{rel}: agent description too long")
        for forbidden in ("由 ", "Phase", "前身", "→"):
            if forbidden in desc:
                offenders.append(f"{rel}: description contains {forbidden!r}")

    assert offenders == []


def test_search_agent_documents_bounded_catalog_rescue_contract():
    text = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(encoding="utf-8")

    required = [
        "中文增强",
        "中文候选",
        "未能真正匹配原版",
        "最多处理前 3 个",
        "最多 5 次",
        "quasi-search kagi search --format json",
        "site:books.com.tw",
        "data[].title",
        "data[].url",
        "data[].snippet",
        "只补缺失字段",
        "不要覆盖 Douban",
        "不要写入 cache",
        "不要打开网页",
        "不要使用 DOKO",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


def test_audit_agent_documents_search_metadata_qa_contract():
    text = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(encoding="utf-8")

    required = [
        "metadata 校对",
        "quasi-search book",
        "quasi-search paper",
        "--json",
        "--isbn",
        "--doi",
        "--title",
        "--author",
        "results[0]",
        "diagnostics.conflicts",
        "frontmatter",
        "metadata_mismatch",
        "escalated",
        "不要写入 cache",
        "不要写 manifest",
        "不要新造 audit/search CLI",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []

    forbidden = [
        "quasi-audit metadata",
        "quasi-search metadata",
        "quasi-audit search",
    ]
    present = [token for token in forbidden if token in text]
    assert present == []


def test_orchestrate_noop_permission_always_carries_an_observable_exists_check():
    """A prompt may allow "no-op if output exists" only if it also tells the agent how to
    observe existence. Bare `test -e` prints nothing either way, so the agent defaults to
    "exists" and silently skips the write (0.44.3 probe, then 0.45.0 chapter analyse)."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    assert text.count("no-op 返回 success") == 1, "idempotent no-op must be granted in one place only"
    assert "echo MISSING" in text, "that one place must print an observable existence signal"
    assert text.count("noopIfExists(") >= 2, "every idempotent output-writing prompt routes through the helper"


def test_orchestrate_reads_every_receipt_it_branches_on():
    """A receipt without a schema comes back as prose, so its fields read as undefined and the
    branch silently takes the wrong path (0.43.0 shipped that way for download/extract/audit).
    Chapter completeness now branches on synth's chapters_analyzed and paper OCR fallback on
    analyse's status/notes, so those two receipts need schemas too."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    for schema in ("DL_SCHEMA", "EX_SCHEMA", "AU_SCHEMA", "SEARCH_SCHEMA", "PROBE_SCHEMA",
                   "AN_SCHEMA", "SY_SCHEMA", "OCR_SCHEMA", "STEER_SCHEMA", "RECALL_SCHEMA"):
        assert f"const {schema} =" in text, f"{schema} must be defined"
        assert f"schema: {schema}" in text, f"{schema} is defined but never attached to an agent() call"


def test_orchestrate_book_reconciles_chapter_count_before_reporting_ok():
    """Bowker 2005: 9 chapter agents all reported success, 2 files landed, synth honestly said
    chapters_analyzed: 2, and the graph still returned book_failures: 0. Silent truncation."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    assert "analysedCount(sy) < chapters.length" in text, "book must reconcile synth's count against extract's"
    assert "chapters_incomplete" in text, "an unreconciled book must not report ok"
    assert "overwrite: true" in text, "synth must always regenerate or its count is stale"


def test_process_material_reports_any_status_that_is_not_ok():
    """The entry skill must enumerate the SUCCESS status, not the failure ones. processBook
    re-raises download-agent's status verbatim, so the failure set grows outside this file:
    `year_mismatch` fell through an `endswith("_failed") or status in (...)` list straight into
    the success report, exactly as `chapters_incomplete` did before 0.47.1. Missing a name there
    means silently reporting a failed run as done."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(encoding="utf-8")

    assert 'result.status != "ok"' in text, "unhandled statuses must fail closed"
    assert 'endswith("_failed")' not in text, "do not enumerate failure statuses; enumerate ok"
    # year_mismatch keeps the file at tmp_path awaiting a human call, same as year_ambiguous.
    assert '("year_mismatch", "year_ambiguous")' in text


def test_orchestrate_paper_ocr_fallback_reads_a_structured_flag():
    """0.48.0 topic E2E: both Star papers were scans; analyse-agent put "需 OCR" in the receipt's
    `output` and paraphrased `notes`, so a regex over `notes` alone matched nothing, no ocr agent
    ever spawned, and both papers were silently dropped. Free text is not a control signal."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    assert "needs_ocr: { type: 'boolean' }" in text, "AN_SCHEMA must carry the structured flag"
    assert "an.needs_ocr === true" in text, "the OCR gate must branch on the flag, not on prose"
    assert "/OCR|扫描|图像|scan/i.test(an.notes || '')" not in text, "the notes-only regex is the bug"

    contract = (PLUGIN_ROOT / "agents" / "analyse-agent.md").read_text(encoding="utf-8")
    assert "needs_ocr" in contract, "the agent must be told to emit the flag the graph reads"


def topic_body(text: str) -> str:
    start = text.index("async function processTopic(")
    return text[start:text.index("\n// ── prompt builders", start)]


def test_orchestrate_topic_recurses_through_router():
    """The whole point of the graph is that a topic item IS a book/paper node. Re-implementing
    the book subflow inside processTopic is exactly the duplication old process-author carried
    ("keep naming in sync with process-book" as a prose contract). And a batch-dispatched book
    must carry batchYear, or one year-ambiguous book stalls the entire topic run at a gate."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = topic_body(text)

    assert "case 'topic': return processTopic(" in text, "router must dispatch topic"
    assert "router(kind," in body, "topic items must go through router, not an inlined subflow"
    assert "{ batchYear: true }" in body, "a batch must not stop on one book's year ambiguity"
    for inlined in ("processBook(", "processPaper(", "extractPrompt(", "analysePrompt("):
        assert inlined not in body, f"processTopic re-implements {inlined} instead of recursing"


def test_orchestrate_topic_recalls_the_vault_before_it_searches_online():
    """0.48.1 topic E2E (Bowker infrastructure): 6 strongly-relevant works were already analysed in
    the vault, online discovery surfaced 1 of them, and the finished overview carried zero
    [[wikilink]]s back into the vault. The probe can only skip works discovery *found* — anything
    it misses is invisible, so a topic's main corpus (the library the user already built on that
    topic) never enters the run. Recall must be its own step, and must feed round 1's snowball:
    those in-vault works are usually the most cited ones in the topic's citation network."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = topic_body(text)

    assert "vaultRecallPrompt(" in body, "topic must recall in-vault works, not only search online"
    assert "function vaultRecallPrompt(" in text, "the recall prompt builder must exist"
    assert "rg -il" in text, "recall needs an observable signal; rg -il prints the hits"
    assert "await parallel([" in body, "recall and discovery are independent; do not serialise them"
    assert "[...local, ...roundOk]" in body, "recalled works must seed round 1's snowball"
    assert "ok = [...local]" in body, "recalled works are already analysed — they are corpus"

    # Talks can ONLY come from recall — online discovery can never surface a recording the user
    # made, so a recall that skips vault/talks makes every talk permanently invisible to topics.
    # Talk pages carry their citations under `## 文献人物`, not `## 核心引用`.
    assert "vault/books vault/papers vault/talks" in text, "recall must sweep talks too"
    assert "vault/talks/${it.slug}/talk.md" in text, "itemPath must resolve talk corpus entries"
    steer_contract = (PLUGIN_ROOT / "agents" / "steer-agent.md").read_text(encoding="utf-8")
    assert "## 文献人物" in steer_contract, "steer must read the talk page's citation section"
    # The probe hands back vault_slugs; `seen` only guards candidate slugs, so a recalled work
    # rediscovered online re-enters `ok` and the synth contract carries duplicate paths
    # (0.48.2 E2E: 2 of 16 analysis_paths were duplicates). Corpus conformance is the graph's job.
    assert ".filter(i => !ok.some(o => o.slug === i.slug))" in body, "ok must stay duplicate-free"


def test_orchestrate_topic_steers_by_outline():
    """0.49.x 的平面滚雪球在书为主的库里向社科经典回退(Kopytoff/Thompson/Gereffi 进了
    手机形态主题),且综述每轮重织结构。闭环:steer-agent 掌舵、outline 持久、synth 分页。"""
    graph = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = topic_body(graph)

    assert "quasi:steer-agent" in body, "掌舵 agent 必须在图里"
    assert "02-outline.md" in graph, "outline 路径由图指定"
    assert "topicSearchPrompt" not in graph, "topic 首搜已被 steer 种子轮吞掉"
    assert "snowballPrompt" not in graph, "平面滚雪球已被 steer 吞掉"
    assert "steer:${slug}:r0" in graph and "steer:${slug}:r${round}" in graph, "种子轮与滚动轮 label 可区分"
    assert "STEER_SCHEMA" in graph, "掌舵回执必须有 schema,散文读不到字段"
    assert "page: dossier" in graph and "page: spine" in graph, "synth 分页派发"
    assert "synth-dossier" in body and "synth-topic:${slug}" in body
    assert "dirty" in body, "只重写脏专章"
    assert "saturated" in body, "掌舵可在轮数用尽前收口"
    assert "subq" in graph and "role" in graph, "候选带子问题与角色标签"
    assert "new Set((st0 && st0.dirty) || [])" in body, "种子轮回执的 dirty/建议词必须入账"
    assert "steerReceipts" in body, "收到过活回执才不全量重写手写老专章"
    assert "r1-close" in body, "recall-only 主题补一次收口掌舵"


def test_orchestrate_topic_runs_the_webcard_channel_on_its_own_track():
    """sky-mobi 类主题的证据在 SEC 文件/工信部规章/SDK 遗存/口述里,学术传感器全程失明:
    `queue` 恒空,只看它循环一轮都滚不起来。圈外通道必须能独立驱动循环,且证据卡**不进**
    ok 语料表 —— 卡不是 vault 分析件,itemPath() 会把它解析成一条读不到的 vault/papers 路径。"""
    graph = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = topic_body(graph)

    assert "quasi:webcard-agent" in body, "证据卡 agent 必须在图里"
    assert "CARD_SCHEMA" in graph, "卡回执要 schema,散文读不到 status"
    assert "while ((queue.length || webTasks.length)" in body, "web_tasks 单独也要能驱动循环"
    assert "!queue.length && !local.length && !webTasks.length" in body, "只有三条通道全空才是 no_works"
    # 卡与语料两条账:cards[] 独立累计,ok 里永远只有 book/paper/talk。
    assert "const cards = [], cardSlugs = new Set()" in body, "卡独立累计,不混进 ok"
    assert "ok.push(...roundOk)" in body and "cards.push(c)" in body
    assert "ok.length + cards.length" in body, "死胡同卡点按证据总量判,纯圈外主题不能被误判成没找到东西"
    # index 对齐:parallel() 用 null 占位死掉的 agent,filter 掉就会把标题安到别的 slug 上。
    assert "const cres = await parallel(" in body, "卡回执不得 filter(Boolean),会错位 index"
    assert "roundCards.forEach(c => c.subq && dirty.add(c.subq))" in body, "新卡要把其子问题报脏,否则专章不重写"
    # 卡路径是独立解析器,不并进 itemPath —— 共用会让任何手滑静默变成死链。
    assert "const cardPath = (topicSlug, cardSlug) =>" in graph
    assert "cards/${cardSlug}.md" in graph
    assert "card_paths:" in graph, "两种 synth 页都要收到卡通道"
    assert "new_cards:" in graph, "掌舵要收到本轮新卡,登记进 outline 的 cards"


def test_process_material_gates_topic_dead_end_back_to_the_user():
    """Snowball runs dry long before the corpus is useful; the graph can only report that, the
    seeds decision is the user's. Dropping the gate turns a 2-item topic into a silent `ok`."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(encoding="utf-8")

    assert "needs_seeds" in text, "the dead-end status must reach a human gate"
    assert "suggested_queries" in text, "the widening hints must be shown, not swallowed"


def test_process_material_carries_the_retired_skills_post_steps():
    """0.49.0 retired the per-kind process-* skills; the two post-processing contracts they owned
    must survive in process-material or they silently vanish: process-paper's opt-in translation
    (translate-agent → processing/translations/{slug}-zh.pdf) and process-author's LOCALISE loop
    over the books it landed (which needs the graph to report WHICH books — counts can't drive
    a loop)."""
    skill = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(encoding="utf-8")
    graph = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    assert "book_slugs: okBooks" in graph, "author receipt must name the landed books, not just count them"
    assert 'result.get("book_slugs")' in skill, "the LOCALISE loop must read the graph's book list"
    assert "quasi:translate-agent" in skill, "paper translation must remain reachable"
    assert "processing/translations/{slug}-zh.pdf" in skill or "processing/translations/{key}-zh.pdf" in skill
    assert "实验" not in skill, "the skill is no longer experimental; stale framing misroutes the model"

    # 0.49.1: the same duplicate-vault_slug account settled in topic (0.48.3) applies to author —
    # two candidate slugs can probe-resolve to one vault work; and topic-landed books need the
    # LOCALISE list too. synth_failed gets one automatic re-submit: items are idempotent, so a
    # transient double-kill of the synth agent (0.48.2 E2E) must not scrap a 90-minute run.
    assert "okBooks = [...new Set([" in graph, "author book corpus must be duplicate-free"
    assert "okPapers = [...new Set([" in graph, "author paper corpus must be duplicate-free"
    assert "ok.filter(i => i.kind === 'book')" in graph, "topic receipt must carry landed book slugs"
    assert 'result.status == "synth_failed"' in skill, "synth_failed must auto-resubmit once"


def test_extract_contract_promises_the_chapters_array_the_graph_fans_out_on():
    """extract-agent's declared EXTRACT_RESULT never mentioned the chapters[] array EX_SCHEMA
    requires — the chapter fan-out ran only because StructuredOutput coerced the field at
    dispatch time. Schema begging is not a contract (the needs_ocr class): the agent's own
    protocol must promise the field, with the manifest as its verbatim source."""
    ex = (PLUGIN_ROOT / "agents" / "extract-agent.md").read_text(encoding="utf-8")

    assert "- chapters:" in ex, "the receipt must carry the chapter table"
    assert "slot:" in ex and "filename:" in ex, "fan-out needs slot + filename per chapter"
    assert "manifest" in ex, "the receipt mirrors the manifest, not memory"


def test_synthesis_agent_bounds_its_reading_budget():
    """Philip Agre author run: §A1 ordered a full Read of every chapter of every book (34+
    chapters) plus 10 full papers — the subagent's context overflowed and synth-author died
    'Prompt is too long' twice, scrapping the branch. The corpus scales with the vault, the
    window doesn't; the contract must gate reading on an observable measurement, not vibes."""
    text = (PLUGIN_ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")

    # §B reading one book's own chapters is that mode's irreducible input and stays; the dead
    # instruction is §A's cross-corpus sweep: every chapter of EVERY book.
    assert "Glob 同目录 `ch*.md` 逐一 Read" not in text, "the exhaustive cross-book sweep is the overflow"
    assert "只取文件名" in text, "the chapter inventory is disclosed (cheap); reading stays budgeted"
    assert "wc -c" in text, "the budget gate needs an observable number"
    assert "Prompt is too long" in text, "the contract must say why the budget exists"
    assert text.count("300000") >= 2, "author AND topic/journal modes both need the gate"


def test_orchestrate_agents_carry_explicit_phase_and_distinguishable_labels():
    """A real Agre author run rendered 19 chapter agents as identical `analyse:agre-reinventing-tec…`
    rows filed under the *Paper* phase — read as "60+ runaway papers" when every cap had held.
    Two display defects, both real: `phase()` is global state and races under parallel recursion
    (opts.phase is the documented fix), and the chapter slot sat past the label truncation point."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = text[text.index("async function processBook("):text.index("// ── prompt builders")]

    assert "{ agentType:" not in body, "every agent call must pin its node's phase explicitly"
    assert body.count("phase: '") >= 30, "opts.phase belongs on every call site, not a sample"
    assert "label: `analyse-ch${ch.slot}:${slug}`" in text, "the chapter slot must survive truncation"
    assert "label: `refill-ch${ch.slot}:${slug}`" in text
    assert "label: `regen-ch${ch.slot}:${slug}`" in text


def test_orchestrate_retries_every_receipt_reading_agent():
    """agent() returns null when the subagent dies on a terminal API error, and every call site
    used to read that null as a content answer: a dead probe re-processes the whole author batch
    (destructive re-extract), a dead audit reads as clean, a dead chapter leaves the book at 8/9
    (Bowker 2005 — ch04 and ch07 both died, one refill round could only save one)."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    # 0.49.9: agent() is wrapped in guard() (timeout → null), so retryNull re-dispatches on guard's null.
    assert "?? guard(" in text, "retryNull must re-dispatch on a null receipt"
    # A receipt with a schema is one the script branches on, so it must go through retryNull.
    lines = text.splitlines()
    bare = []
    for i, line in enumerate(lines):
        if "await agent(" not in line:
            continue
        call = []                       # the call's own lines, up to the `})` that closes its opts
        for nxt in lines[i:i + 6]:
            call.append(nxt)
            if "})" in nxt:
                break
        if any("schema:" in c for c in call):
            bare.append(i + 1)
    assert bare == [], f"receipt-reading agent() calls must use retryNull; bare at lines {bare}"


def test_steer_agent_contract_carries_fence_quota_and_outline_ownership():
    """0.49.x topic 跑漂移的三个病根,栅栏各有一条合同文字守着:平面相关性(对象栅栏)、
    经典回退(theory 配额)、书哑巴(ch*.md 核心引用)。steer-agent 是 02-outline.md 唯一 writer。"""
    steer = (PLUGIN_ROOT / "agents" / "steer-agent.md").read_text(encoding="utf-8")

    assert "自身的研究对象" in steer, "对象栅栏:关于主题对象 vs 仅被主题文献引用"
    assert "theory_used" in steer and "≤3" in steer, "theory 配额账本"
    assert "ch*.md" in steer and "## 核心引用" in steer, "书的引用在章节分析里"
    assert "## 文献人物" in steer, "讲座引用节"
    assert "02-outline.md" in steer, "outline 是它唯一可写路径"
    assert "kind: outline" in steer
    assert "STEER_RESULT" in steer and "web_tasks" in steer and "dirty" in steer
    assert "saturated" in steer and "dossier" in steer
    assert "全量成员表" in steer, "成员表全量累计的合同文字"
    assert "缺失" in steer, "缺页自愈:dossier=true 但 page 文件缺失 → 列入 dirty"
    # 卡走独立通道:混进 items 就是给 synth 一条 vault/papers/{card}.md 的死链。
    assert "new_cards" in steer and "不进 `items`" in steer
    assert "card_slug" in steer, "卡文件名由掌舵定,才能选刷新旧卡还是开新卡"


def test_synthesis_topic_mode_is_outline_pinned_and_paged():
    """54 条平铺语料整篇重织是 0.49.x 综述'越滚越乱'的一半病根(另一半在采集)。§T 拆页:
    dossier 每页只读本聚类语料(读预算结构性受控),spine 恒薄且聚类结构照抄 outline,
    不再每次即兴。outline 页本身由 steer-agent 写,synth 不碰。"""
    synth = (PLUGIN_ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")

    assert "page: spine" in synth and "page: dossier" in synth
    assert "kind: dossier" in synth
    assert "kind(overview|resources|dossier)" in synth, "outline 不在 synth 的可写 kind 里"
    assert "inline_clusters" in synth and "dossier_pages" in synth
    assert "照抄" in synth, "聚类 id/标题/顺序来自 outline,不许重排"
    assert "子问题地图" in synth, "00 新模板围绕子问题"
    # 卡是一手证据不是同行评议结论;两页都收 card_paths,但 synth 永远不写 cards/。
    assert synth.count("card_paths") >= 2, "dossier 与 spine 两页都要收卡通道"
    assert "kind: card 归 webcard-agent" in synth
    assert "永远不写" in synth


def test_pending_cards_never_hands_two_agents_the_same_filename():
    """`card_slug` 直接就是文件名,所以它必须确定性且唯一 —— 重名的两张卡意味着两个并行
    agent 写同一个路径,后写的赢,前一张的抓取工作静默蒸发。这条是真跑 node,不是读源码:
    派生链(steer 给的 → query → subq → 'card')与补序号循环都是分支逻辑,静态断言看不出错。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")

    src = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    helpers = "const cardPath =" + src.split("const cardPath =")[1].split("// 掌舵 prompt")[0]
    script = helpers + """
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b))
  throw new Error(`${msg}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`) }

// steer 给了 slug 就照用;中文 query 派生后为空,退到 subq;两条同 subq 的任务补序号。
const st = { web_tasks: [
  { subq: 'sq-a', query: 'Sky-mobi SEC F-1 filing', note: 'n', card_slug: 'sky-mobi-sec-f1' },
  { subq: 'sq-b', query: '工信部入网许可' , note: 'n' },
  { subq: 'sq-b', query: '摩豆平台遗存', note: 'n' },
  { subq: 'sq-c', note: 'no query' },
] }
const out = pendingCards(st, [])
eq(out.map(t => t.card_slug), ['sky-mobi-sec-f1', 'sq-b', 'sq-b-2'], 'slug 派生与补序号')
eq(out.length, 3, '没有 query 的任务不派')
eq(new Set(out.map(t => t.card_slug)).size, out.length, '批内 slug 必须唯一')

// 本轮已写过的卡不重抓;派生出的 slug 也不许撞上已写过的。
eq(pendingCards(st, ['sky-mobi-sec-f1']).map(t => t.card_slug), ['sq-b', 'sq-b-2'], '已写过的跳过')
eq(pendingCards(st, ['sq-b']).map(t => t.card_slug), ['sky-mobi-sec-f1', 'sq-b-2', 'sq-b-3'],
   '派生 slug 撞上已写过的要让路,不能覆盖')

eq(cardPath('sky-mobi', 'sq-b'), 'vault/topics/sky-mobi/cards/sq-b.md', 'card 路径')
console.log('OK')
"""
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_webcard_agent_contract_forbids_invention_and_owns_one_card():
    """圈外通道的失败模式是幻觉:一张编造的机型卡会被 synth 当证据引用,比没有卡更坏。
    合同必须挡住三件事 —— 用训练知识补完、写 cards/ 以外的文件、抓不到也硬写一张空卡。"""
    card = (PLUGIN_ROOT / "agents" / "webcard-agent.md").read_text(encoding="utf-8")

    assert "name: webcard-agent" in card
    assert "kind: card" in card and "cards/{card-slug}.md" in card, "产物路径与 schema kind"
    assert "不许" in card and "训练知识" in card, "抓不到不许凭训练知识补完"
    assert "WebFetch" in card and "quasi-search kagi" in card, "检索 + 一手来源抓取两件工具"
    assert "confirmed" in card and "single-source" in card and "disputed" in card, "证据等级三档"
    assert "缺口/存疑" in card, "卡必须自陈缺口,无缺口的圈外卡多半没核验"
    assert "不进语料表" in card, "卡不是 vault 分析件"
    assert '"empty"' in card, "抓不到就不写文件,不留空卡"
    assert "品类合集" in card and "拆成多个文件" in card, "按品类汇总的卡仍是一张卡,不拆成单机文件"
