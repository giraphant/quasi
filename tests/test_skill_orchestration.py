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


def test_process_book_step0_runs_local_recall_before_search_agent():
    text = (PLUGIN_ROOT / "skills" / "process-book" / "SKILL.md").read_text(encoding="utf-8")

    local_pos = text.index("LOCAL RECALL + METADATA")
    rg_pos = text.index("rg fuzzy recall")
    search_pos = text.index('Agent("quasi:search-agent"')
    download_pos = text.index('Agent("quasi:download-agent"')
    assert local_pos < search_pos
    assert rg_pos < search_pos
    assert rg_pos < download_pos

    required = [
        "overview/source/chapter manifest/chapter outputs",
        "vault/books",
        "processing",
        "sources",
        "high-confidence",
        "do not blindly skip",
        "不要盲目跳过",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


def test_process_paper_accepts_pdf_preferred_text_source_contract():
    text = (PLUGIN_ROOT / "skills" / "process-paper" / "SKILL.md").read_text(encoding="utf-8")

    assert "sources/{slug}.pdf" in text
    assert "sources/{slug}.txt" in text
    assert "source_file" in text
    assert "source_pdf" not in text


def test_process_paper_step0_runs_local_recall_before_search_agent():
    text = (PLUGIN_ROOT / "skills" / "process-paper" / "SKILL.md").read_text(encoding="utf-8")

    local_pos = text.index("LOCAL RECALL + METADATA/SOURCE")
    rg_pos = text.index("rg fuzzy recall")
    search_pos = text.index('Agent("quasi:search-agent"')
    download_pos = text.index('Agent("quasi:download-agent"')
    assert local_pos < search_pos
    assert rg_pos < search_pos
    assert rg_pos < download_pos

    required = [
        "vault/papers/{slug}.md",
        "sources/{slug}.pdf|txt",
        ".quasi/papers/{slug}.search.json",
        "PDF 优先",
        "high-confidence",
        "do not blindly skip",
        "不要盲目跳过",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


def test_process_author_reconciles_local_artifacts_before_search_and_download():
    text = (PLUGIN_ROOT / "skills" / "process-author" / "SKILL.md").read_text(encoding="utf-8")

    local_pos = text.index("LOCAL AUTHOR/WORK RECALL")
    search_pos = text.index('Agent("quasi:search-agent"')
    reconcile_pos = text.index("reconcile_representative_works_with_local_artifacts")
    download_pos = text.index('Agent("quasi:download-agent"')
    assert local_pos < search_pos
    assert reconcile_pos < download_pos

    required = [
        "vault/authors/{author_name}.md",
        ".quasi/authors/{author_name}/manifest.json",
        ".quasi/authors/{author_name}/books.json",
        ".quasi/authors/{author_name}/papers.json",
        "final/source/partial artifacts",
        "completed/partial is inferred",
        "不新增 manifest status",
        "do not blindly skip",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


def test_process_topic_superset_agent_uses_shell_default_contract():
    text = (PLUGIN_ROOT / "skills" / "process-topic" / "SKILL.md").read_text(encoding="utf-8")

    assert '--agent "${QUASI_SUPERSET_AGENT:-copilot}"' in text
    assert "superset_agent = env" not in text
    assert "--agent claude" not in text


def test_process_topic_dispatch_prompts_forbid_worktree_switching():
    text = (PLUGIN_ROOT / "skills" / "process-topic" / "SKILL.md").read_text(encoding="utf-8")

    required = [
        "This is a vault/content processing task, not a software development task.",
        "Do not create, enter, or switch git worktrees or branches.",
        "Do not run git worktree, git switch, or git checkout.",
        "If you believe a separate branch/worktree is needed, stop and report cwd + branch instead.",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


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
                   "AN_SCHEMA", "SY_SCHEMA", "OCR_SCHEMA", "REFS_SCHEMA"):
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


def test_process_material_gates_topic_dead_end_back_to_the_user():
    """Snowball runs dry long before the corpus is useful; the graph can only report that, the
    seeds decision is the user's. Dropping the gate turns a 2-item topic into a silent `ok`."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(encoding="utf-8")

    assert "needs_seeds" in text, "the dead-end status must reach a human gate"
    assert "suggested_queries" in text, "the widening hints must be shown, not swallowed"


def test_orchestrate_retries_every_receipt_reading_agent():
    """agent() returns null when the subagent dies on a terminal API error, and every call site
    used to read that null as a content answer: a dead probe re-processes the whole author batch
    (destructive re-extract), a dead audit reads as clean, a dead chapter leaves the book at 8/9
    (Bowker 2005 — ch04 and ch07 both died, one refill round could only save one)."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")

    assert "?? agent(" in text, "retryNull must re-dispatch on a null receipt"
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
