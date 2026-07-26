from __future__ import annotations

from pathlib import Path
import re


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
                   "AN_SCHEMA", "SY_SCHEMA", "OCR_SCHEMA", "REFS_SCHEMA", "RECALL_SCHEMA"):
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
    assert "## 文献人物" in text, "snowball must read the talk page's citation section"
    # The probe hands back vault_slugs; `seen` only guards candidate slugs, so a recalled work
    # rediscovered online re-enters `ok` and the synth contract carries duplicate paths
    # (0.48.2 E2E: 2 of 16 analysis_paths were duplicates). Corpus conformance is the graph's job.
    assert ".filter(i => !ok.some(o => o.slug === i.slug))" in body, "ok must stay duplicate-free"


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
