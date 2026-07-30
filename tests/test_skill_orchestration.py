from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_SRC = PLUGIN_ROOT / "scripts/workflows"


def workflow_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOW_SRC.rglob("*.mjs"))
    )


def source_file(relative: str) -> str:
    return (WORKFLOW_SRC / relative).read_text(encoding="utf-8")


def active_skill_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "agents").glob("*.md"))


def frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^description:\s*(?:>\s*)?\n(?P<body>(?:  .*\n)+)", text, re.MULTILINE
    )
    if match:
        return " ".join(line.strip() for line in match.group("body").splitlines())

    match = re.search(r"^description:\s*(?P<body>.+)$", text, re.MULTILINE)
    return match.group("body").strip() if match else ""


def frontmatter_name(path: Path) -> str:
    match = re.search(r"^name:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else ""


def run_card_helpers(js_body: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")

    script = (
        "import { positiveInt } from "
        + repr((WORKFLOW_SRC / "research" / "topic.mjs").as_uri())
        + "\nimport { cardPath, mergeCards, mergeItems, pendingCards, registered } from "
        + repr((WORKFLOW_SRC / "operations" / "steer.mjs").as_uri())
        + """

const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b))
  throw new Error(`${msg}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`) }
"""
        + js_body
        + "\nconsole.log('OK')\n"
    )
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


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
                offenders.append(
                    f"{rel}: runtime skill contains maintainer-only text {forbidden!r}"
                )

    assert offenders == []


def test_skill_names_follow_agent_skills_standard():
    offenders = [
        str(path.relative_to(PLUGIN_ROOT))
        for path in active_skill_files()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", frontmatter_name(path))
    ]

    assert offenders == []


def test_process_material_codex_prefers_visible_native_driver():
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    runtime = (
        PLUGIN_ROOT
        / "skills"
        / "process-material"
        / "references"
        / "codex-native-driver.md"
    ).read_text(encoding="utf-8")

    assert "quasi-codex-driver" in skill
    assert "skills/process-material/references/codex-native-driver.md" in skill
    assert 'protocol="quasi-codex-driver/1"' in skill
    assert 'fork_turns:"none"' in runtime
    assert "spawn_agent" in runtime and "current thread" in runtime
    assert "codex_agent_type" in runtime and "quasi_download" in runtime
    assert "receipt_rejected" in runtime and "followup_task" in runtime
    assert "agent_cancel" in runtime and "interrupt_agent" in runtime
    assert "quasi_agent_1" not in runtime
    assert "label plus its id suffix" in runtime
    assert "quasi-codex-runner" in skill, "headless fallback must remain available"
    assert skill.index("drive_codex_native(") < skill.index(
        "quasi-codex-runner --script"
    )


def test_process_material_title_only_input_requires_metadata_agent():
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    search_agent = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(
        encoding="utf-8"
    )

    assert "title-only metadata 前置搜索" in skill
    assert 'Agent("quasi:search-agent"' in skill
    assert "quasi_search" in skill and 'fork_turns:"none"' in skill
    assert "metadata_{slug}_{id_suffix}" in skill
    assert "不得在主进程改用 WebSearch、WebFetch 或 browser" in skill
    assert skill.index('Agent("quasi:search-agent"') < skill.index(
        "# 该 kind 的主键 + 最终产物路径"
    )
    assert "picked.slug" in skill
    assert "{首列作者姓}-{短题名}-{year}" in search_agent


def test_process_material_step_zero_uses_temp_items_file_not_inline_json():
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "--items-json" not in skill
    assert 'resolve_items = [{"kind": args.kind, "slug": key, **ident}]' in skill
    assert "resolve_items_file = write_temp_json(resolve_items)" in skill
    assert "--items-file '{resolve_items_file}'" in skill
    assert "parse_json(Bash(" in skill
    assert "json([{'kind': args.kind" not in skill
    assert not re.search(r"\bjson\(", skill), (
        "caller metadata JSON must never be interpolated into a Bash command"
    )


def test_search_agent_book_picked_requires_evidence_backed_identity():
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    agent = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(
        encoding="utf-8"
    )

    for field in (
        "slug,title,authors,year,isbn,publisher,category,confidence",
        '"publisher": "Evidence-backed Publisher"',
        '"confidence": "high"',
    ):
        assert field in agent
    assert "monograph|edited-volume|handbook|other" in agent
    assert "没有 publisher 证据时不得猜" in agent
    assert "`picked: null` 和顶层" in agent
    assert '`confidence: "low"`' in agent
    assert 'picked_confidence in ("high", "medium")' in skill
    assert 'if args.kind == "book" and not trusted_picked:' in skill
    assert (
        'report("Book metadata 无可靠 picked/publisher evidence；未启动 Workflow")'
        in skill
    )
    assert "args.meta = merge_non_null(args.meta, picked)" in skill
    assert 'args.meta["confidence"] = "verified"' in skill
    assert 'args.meta["category"] = args.meta.get("category") or "other"' in skill
    assert (
        "Book search 若因 publisher 无证据而返回 `picked=null` / low confidence"
        in skill
    )
    assert 'report("Book publisher 无可靠 metadata evidence；未启动 Workflow")' in skill


def test_process_material_year_gate_builds_exact_graph_decision_envelope():
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    graph = source_file("materials/book.mjs")

    assert "decision.slug" not in skill
    assert 'wf_args["batch_accept_year"]' not in skill
    assert 'prior_tmp_path = result["tmp_path"]' in skill
    assert 'prior_year_evidence = result["year_evidence"]' in skill
    assert 'year_options = ["accept-current", "reject"]' in skill
    assert 'prior_year_evidence.get("verdict") == "MISMATCH"' in skill
    assert 'year_options.insert(1, "use-recommended-year")' in skill
    assert "options=tuple(year_options)" in skill
    assert 'if year_choice == "reject":' in skill
    assert 'if year_choice == "use-recommended-year":' in skill
    assert 'prior_year_evidence.get("recommended_year")' in skill
    assert 'prior_slug.removesuffix(prior_year_suffix) + f"-{recommended_year}"' in skill
    assert 'wf_args["meta"] = {**prior_meta, "year": recommended_year}' in skill
    assert 'wf_args["year_decision"] = {' in skill
    assert '"action": year_choice' in skill
    assert '"tmp_path": prior_tmp_path' in skill
    assert '"year_evidence": prior_year_evidence' in skill
    gate = skill[
        skill.index('if result.status in ("year_mismatch", "year_ambiguous"):')
        : skill.index("# Strict Paper/Book/Author writer")
    ]
    assert gate.count('wf_args["slug"] =') == 1
    assert gate.count('wf_args["meta"] =') == 1
    assert "accept-current 有意保持 wf_args.slug 与 wf_args.meta" in gate
    assert '"action",\n      "tmp_path",\n      "year_evidence"' in graph
    assert '"accept-current", "use-recommended-year"' in graph
    assert 'decision.year_evidence.verdict !== "MISMATCH"' in graph


def test_download_failure_keeps_actionable_evidence():
    agent = (PLUGIN_ROOT / "agents" / "download-agent.md").read_text(
        encoding="utf-8"
    )
    workflow = workflow_source()

    assert "`failure_reason`" in agent and "`attempts`" in agent
    assert re.search(r"failure_reason:\s*\{\s*type:\s*['\"]string['\"]", workflow)
    assert re.search(r"attempts:\s*\{\s*type:\s*['\"]array['\"]", workflow)
    assert "failure_reason: item.failure_reason || item.verdict_note" in workflow


def test_book_download_match_requires_two_distinct_observed_year_signals():
    agent = (PLUGIN_ROOT / "agents" / "download-agent.md").read_text(
        encoding="utf-8"
    )
    acquire = source_file("operations/acquire.mjs")

    assert "min_independent_supports: 2" in acquire
    assert "count_one_observation_once: true" in acquire
    assert "BOOK_ACQUISITION_POLICY" in acquire
    assert "operation_policy: BOOK_ACQUISITION_POLICY" in acquire
    assert "dc:date" not in agent


def test_download_agent_quotes_every_dynamic_candidates_argument():
    agent = (PLUGIN_ROOT / "agents" / "download-agent.md").read_text(
        encoding="utf-8"
    )

    assert "Title、author、identifier、URL、slug、path、format" in agent
    assert "POSIX single-quote" in agent
    assert "`shell_argv` token 逐字用于 Bash" in agent
    for unsafe in ("`eval`", "`sh -c`", "command substitution", "反引号"):
        assert unsafe in agent


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


def test_search_agent_does_not_hide_catalog_rescue_or_retry():
    text = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(encoding="utf-8")

    assert "一个 invocation 只运行 caller 要求的一次" in text
    assert "不得自行改 query" in text
    assert "隐藏重试" in text
    assert "启动 Kagi rescue" in text
    assert "重试、中文补强和人闸均由 Skill/Graph" in text
    assert "最多 5 次" not in text
    assert "site:books.com.tw" not in text


def test_audit_agent_escalates_external_metadata_instead_of_searching():
    text = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(encoding="utf-8")

    assert "其它 remaining diagnostics 投影为" in text
    assert "`{path,kind,reason}` escalation" in text
    assert "quasi-search book" not in text
    assert "quasi-search paper" not in text


def test_audit_agent_runs_at_most_one_local_fix_validation():
    text = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(encoding="utf-8")

    assert "对 exact target 运行一次 `quasi-audit --path`" in text
    assert "发生 Edit 时" in text
    assert "再运行一次 `quasi-audit --path` 作为 final validation" in text
    assert "未 Edit 时，第一次结果就是 final" in text


def test_old_shell_noop_helper_is_removed_from_strict_material_graph():
    text = workflow_source()

    assert "no-op 返回 success" not in text
    assert "noopIfExists" not in text
    assert "analyseChapterPrompt" not in text
    assert "output_exists_requires_reconcile" in text


def test_orchestrate_reads_every_receipt_it_branches_on():
    """A receipt without a schema comes back as prose, so its fields read as undefined and the
    branch silently takes the wrong path (0.43.0 shipped that way for download/extract/audit).
    Chapter completeness now branches on synth's chapters_analyzed and paper OCR fallback on
    analyse's status/notes, so those two receipts need schemas too."""
    text = workflow_source()

    for schema in (
        "AU_SCHEMA",
        "PROBE_SCHEMA",
        "SY_SCHEMA",
        "STEER_SCHEMA",
        "RECALL_SCHEMA",
        "TEXT_EXTRACT_SCHEMA",
        "READABILITY_SCHEMA",
        "DOCUMENT_OCR_SCHEMA",
        "PAPER_ANALYSE_SCHEMA",
        "PAPER_AUDIT_SCHEMA",
        "BOOK_ACQUIRE_SCHEMA",
        "CHAPTER_PLAN_SCHEMA",
        "CHAPTER_EXTRACT_SCHEMA",
        "CHAPTER_ASSESS_SCHEMA",
        "CHAPTER_ANALYSE_SCHEMA",
        "BOOK_SYNTHESISE_SCHEMA",
        "BOOK_AUDIT_SCHEMA",
        "AUTHOR_DISCOVER_BOOKS_SCHEMA",
        "AUTHOR_DISCOVER_PAPERS_SCHEMA",
        "AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA",
        "AUTHOR_SYNTHESISE_SCHEMA",
        "AUTHOR_AUDIT_SCHEMA",
    ):
        assert re.search(
            rf"(?:export\s+)?const\s+{schema}\s*=", text
        ), f"{schema} must be defined"
        assert re.search(rf"schema:\s*{schema}\b", text), (
            f"{schema} is defined but never attached to an agent() call"
        )


def test_orchestrate_book_reconciles_exact_chapter_receipts_before_reporting_ok():
    """Bowker 2005: 9 chapter agents all reported success, 2 files landed, synth honestly said
    chapters_analyzed: 2, and the graph still returned book_failures: 0. Silent truncation."""
    text = source_file("materials/book.mjs")

    assert "chapterPresent(receipt, \"create\")" in text
    assert "receipt.chapters_analyzed !== inputPaths.length" in text
    assert (
        "JSON.stringify(receipt.input_paths) !== JSON.stringify(inputPaths)" in text
    ), "synthesis must echo the exact ordered chapter owner list"
    assert "chapters_incomplete" in text, "an unreconciled book must not report ok"
    for inventory in ("expected_slots", "present_slots", "missing_slots"):
        assert text.count(inventory) >= 3, (
            f"{inventory} must reach both legacy result and material receipt"
        )
    assert "presentSlots.add" in text, (
        "present inventory must come from exact proved writer receipts"
    )
    assert "retryNull(" not in text, (
        "strict Book writers must not be automatically replayed after unknown outcomes"
    )


def test_book_ingress_requires_publisher_enrichment_even_with_isbn():
    skill = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    acquire = source_file("operations/acquire.mjs")

    assert 'args.kind == "book" and not args.meta.get("publisher")' in skill
    assert 'report("Book publisher 无可靠 metadata evidence；未启动 Workflow")' in skill
    assert "publisher: { type: \"string\" }" in acquire
    assert "publisher 不可核验的书不要列入 candidates" in acquire


def test_book_strict_slice_uses_typed_operations_and_neutral_unknown_codes():
    book = source_file("materials/book.mjs")
    runtime = source_file("runtime.mjs")
    operations = "\n".join(
        source_file(f"operations/{name}.mjs")
        for name in ("acquire", "extract", "analyse", "synthesise", "audit")
    )

    for key in (
        "book.acquire",
        "document.extract-text",
        "document.assess-readability",
        "document.ocr",
        "chapter.plan",
        "chapter.extract",
        "chapter.assess-boundaries",
        "chapter.analyse",
        "book.synthesise",
        "book.audit",
    ):
        assert key in book and key in operations
    assert 'unknownFailureCode: "document.writer_outcome_unknown"' in book
    assert 'unknownFailureCode: "material.writer_outcome_unknown"' in book
    assert 'meta.format === "epub"' in book
    assert '"book.epub_boundary_invalid"' not in book, (
        "EPUB may use the bounded replan/repair edge; only OCR is inapplicable"
    )
    assert 'meta.format === "epub" ||' in book
    assert 'normalized_path: { type: ["string", "null"] }' in operations
    assert "spec.unknownFailureCode" in runtime
    assert "paper.writer_outcome_unknown" in runtime, (
        "runtime defaults preserve the existing Paper validator contract"
    )
    assert "paper." not in book, "Book terminal failures must never inherit Paper codes"
    for legacy in (
        "analyseChapterPrompt(",
        "bookSynthPrompt(",
        "extractPrompt(",
        "type: A",
        "type: B",
        "preamble",
        "paperAnalysePrompt",
    ):
        assert legacy not in book, f"strict Book path leaked legacy prompt: {legacy}"


def test_book_auto_format_handoff_is_finite_and_never_defaults_to_pdf():
    book = source_file("materials/book.mjs")
    acquire = source_file("operations/acquire.mjs")
    skill = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "format: meta.format || null" in book
    assert ': ["epub", "pdf"]' in book
    assert "allowed_outputs: allowedOutputs" in acquire
    assert "format_preference: formats" in acquire
    assert "item.format === format && item.path === path" in book
    assert 'multiple: "blocked"' in acquire
    assert "format 缺失保持 null/auto" in skill
    assert 'args.meta["format"] = "pdf"' not in skill


def test_book_unknown_resume_never_points_back_at_writer():
    book = source_file("materials/book.mjs")

    assert 'failure && failure.outcome === "unknown"' in book
    assert '? { operation_key: "book.reconcile" }' in book
    assert "failed_operation_key:" not in book


def test_book_reconciled_actions_do_not_mark_repaired_or_downgrade_repairs():
    book = source_file("materials/book.mjs")

    assert 'mode === "repair" && receipt.action === "repair"' in book
    assert "state.repaired = true" in book
    assert "state.repaired" in book and '? "repaired"' in book
    assert (
        'mode === "repair" &&\n    receipt.action === "reconciled"'
        in book
    )


def test_book_canonical_only_audit_mutation_does_not_refresh_synthesis():
    book = source_file("materials/book.mjs")

    assert "chapterMutatedByAudit" in book
    assert "owners.get(path).key === \"chapter.analyse\"" in book
    assert "const dependencyChanged =" in book
    assert "if (audited.receipt.mutated_paths.length)" in book
    assert "dependencyChanged || overviewDiagnostics.length" in book


def test_material_and_author_operation_schemas_are_single_top_level_objects():
    operation_text = {
        name: source_file(f"operations/{name}.mjs")
        for name in ("acquire", "extract", "analyse", "synthesise", "audit")
    }
    schema_names = {
        "acquire": (
            "BOOK_ACQUIRE_SCHEMA",
            "AUTHOR_DISCOVER_BOOKS_SCHEMA",
            "AUTHOR_DISCOVER_PAPERS_SCHEMA",
            "AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA",
        ),
        "extract": (
            "CHAPTER_PLAN_SCHEMA",
            "CHAPTER_EXTRACT_SCHEMA",
            "CHAPTER_ASSESS_SCHEMA",
        ),
        "analyse": ("CHAPTER_ANALYSE_SCHEMA",),
        "synthesise": (
            "BOOK_SYNTHESISE_SCHEMA",
            "AUTHOR_SYNTHESISE_SCHEMA",
        ),
        "audit": ("BOOK_AUDIT_SCHEMA", "AUTHOR_AUDIT_SCHEMA"),
    }
    for module, names in schema_names.items():
        text = operation_text[module]
        for name in names:
            start = text.index(f"export const {name} =")
            fragment = text[start : start + 220]
            assert 'type: "object"' in fragment
            assert not re.search(r"\b(?:oneOf|allOf|anyOf|if|then)\s*:", fragment), (
                f"{name} must support Claude Code 2.1.211 structured output"
            )


def test_author_collection_uses_strict_operations_and_shared_agent_contracts():
    author = source_file("collections/author.mjs")
    search = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(
        encoding="utf-8"
    )
    synthesis = (
        PLUGIN_ROOT / "agents" / "synthesis-agent.md"
    ).read_text(encoding="utf-8")
    audit = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(
        encoding="utf-8"
    )
    skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for key in (
        "author.discover-books",
        "author.discover-papers",
        "author.resolve-membership",
        "author.synthesise",
        "author.audit.legacy",
    ):
        assert key in author
    assert "runtime.runOperation" in author
    assert "runtime.coalesce" in author
    assert "retryNull" not in author
    assert "OVERWRITE" not in author
    assert "author.discover-books" in search
    assert "author.discover-papers" in search
    assert "author.synthesise" in synthesis
    assert "通用 audit transaction" in audit
    assert "Book chapter Read" in synthesis
    assert 'result.status == "synth_failed"' not in skill
    assert "author.reconcile" in skill


def test_book_boundary_receipt_does_not_duplicate_manifest_in_input_paths():
    extract = source_file("operations/extract.mjs")

    assert (
        "input_paths must equal Request.chapters[].path in that exact order"
        in extract
    )
    assert "must not\ninclude manifest_path" in extract


def test_process_material_reports_any_status_that_is_not_ok():
    """The entry skill must enumerate the SUCCESS status, not the failure ones. processBook
    re-raises download-agent's status verbatim, so the failure set grows outside this file:
    `year_mismatch` fell through an `endswith("_failed") or status in (...)` list straight into
    the success report, exactly as `chapters_incomplete` did before 0.47.1. Missing a name there
    means silently reporting a failed run as done."""
    text = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert 'result.status != "ok"' in text, "unhandled statuses must fail closed"
    assert 'endswith("_failed")' not in text, (
        "do not enumerate failure statuses; enumerate ok"
    )
    # year_mismatch keeps the file at tmp_path awaiting a human call, same as year_ambiguous.
    assert '("year_mismatch", "year_ambiguous")' in text


def test_orchestrate_paper_ocr_fallback_reads_a_structured_flag():
    """0.48.0 topic E2E: both Star papers were scans; analyse-agent put "需 OCR" in the receipt's
    `output` and paraphrased `notes`, so a regex over `notes` alone matched nothing, no ocr agent
    ever spawned, and both papers were silently dropped. Free text is not a control signal."""
    text = (
        source_file("operations/extract.mjs")
        + source_file("operations/analyse.mjs")
        + source_file("materials/paper.mjs")
    )

    assert re.search(
        r"enum:\s*\[\s*['\"]readable['\"],\s*['\"]needs_ocr['\"],\s*['\"]invalid_source['\"]",
        text,
    ), (
        "READABILITY_SCHEMA must carry the typed control enum"
    )
    assert 'normalized.signal === "needs_ocr"' in text, (
        "the OCR gate must branch on the readability signal, not on prose"
    )
    assert not re.search(r"/OCR\|扫描\|图像\|scan/i", text), (
        "free-text OCR regex is a control-flow bug"
    )

    contract = (PLUGIN_ROOT / "agents" / "analyse-agent.md").read_text(encoding="utf-8")
    assert "needs_ocr" not in contract, (
        "readability control belongs to document.assess-readability, not analyse-agent"
    )


def topic_body(_text: str | None = None) -> str:
    return source_file("research/topic.mjs")


def test_orchestrate_topic_recurses_through_router():
    """The whole point of the graph is that a topic item IS a book/paper node. Re-implementing
    the book subflow inside processTopic is exactly the duplication old process-author carried
    ("keep naming in sync with process-book" as a prose contract). And a batch-dispatched book
    must carry batchYear, or one year-ambiguous book stalls the entire topic run at a gate."""
    text = workflow_source()
    body = topic_body(text)

    assert re.search(
        r"case\s+['\"]topic['\"]:\s*return\s+processTopic\(", text
    ), "router must dispatch topic"
    assert "router(" in body, (
        "topic items must go through router, not an inlined subflow"
    )
    assert "{ batchYear: true }" in body, (
        "a batch must not stop on one book's year ambiguity"
    )
    for inlined in (
        "processBook(",
        "processPaper(",
        "extractPrompt(",
        "analysePrompt(",
    ):
        assert inlined not in body, (
            f"processTopic re-implements {inlined} instead of recursing"
        )


def test_orchestrate_topic_recalls_the_vault_before_it_searches_online():
    """0.48.1 topic E2E (Bowker infrastructure): 6 strongly-relevant works were already analysed in
    the vault, online discovery surfaced 1 of them, and the finished overview carried zero
    [[wikilink]]s back into the vault. The probe can only skip works discovery *found* — anything
    it misses is invisible, so a topic's main corpus (the library the user already built on that
    topic) never enters the run. Recall must be its own step, and must feed round 1's snowball:
    those in-vault works are usually the most cited ones in the topic's citation network."""
    text = workflow_source()
    body = topic_body(text)

    assert "vaultRecallPrompt(" in body, (
        "topic must recall in-vault works, not only search online"
    )
    assert "function vaultRecallPrompt(" in text, "the recall prompt builder must exist"
    assert "rg -il" in text, "recall needs an observable signal; rg -il prints the hits"
    assert "await parallel([" in body, (
        "recall and discovery are independent; do not serialise them"
    )
    assert "[...local, ...roundOk]" in body, (
        "recalled works must seed round 1's snowball"
    )
    assert "ok = [...local]" in body, (
        "recalled works are already analysed — they are corpus"
    )

    # Talks can ONLY come from recall — online discovery can never surface a recording the user
    # made, so a recall that skips vault/talks makes every talk permanently invisible to topics.
    # Talk pages carry their citations under `## 文献人物`, not `## 核心引用`.
    assert "vault/books vault/papers vault/talks" in text, "recall must sweep talks too"
    assert re.search(r"vault/talks/\$\{\w+\.slug\}/talk\.md", text), (
        "itemPath must resolve talk corpus entries"
    )
    steer_contract = (PLUGIN_ROOT / "agents" / "steer-agent.md").read_text(
        encoding="utf-8"
    )
    assert "## 文献人物" in steer_contract, (
        "steer must read the talk page's citation section"
    )
    # The probe hands back vault_slugs; `seen` only guards candidate slugs, so a recalled work
    # rediscovered online re-enters `ok` and the synth contract carries duplicate paths
    # (0.48.2 E2E: 2 of 16 analysis_paths were duplicates). Corpus conformance is the graph's job.
    assert re.search(
        r"\.filter\(\s*\(item\) => !ok\.some\(\(existing\) => existing\.slug === item\.slug\)",
        body,
    ), (
        "ok must stay duplicate-free"
    )


def test_orchestrate_topic_steers_by_outline():
    """0.49.x 的平面滚雪球在书为主的库里向社科经典回退(Kopytoff/Thompson/Gereffi 进了
    手机形态主题),且综述每轮重织结构。闭环:steer-agent 掌舵、outline 持久、synth 分页。"""
    graph = workflow_source()
    body = topic_body(graph)

    assert "quasi:steer-agent" in body, "掌舵 agent 必须在图里"
    assert "02-outline.md" in graph, "outline 路径由图指定"
    assert "topicSearchPrompt" not in graph, "topic 首搜已被 steer 种子轮吞掉"
    assert "snowballPrompt" not in graph, "平面滚雪球已被 steer 吞掉"
    assert "steer:${slug}:r0" in graph and "steer:${slug}:r${round}" in graph, (
        "种子轮与滚动轮 label 可区分"
    )
    assert "STEER_SCHEMA" in graph, "掌舵回执必须有 schema,散文读不到字段"
    assert re.search(
        r"required:\s*\[\s*['\"]subq['\"],\s*['\"]query['\"],\s*['\"]card_slug['\"]",
        graph,
    ), (
        "图不能替 steer 发明卡文件名"
    )
    assert re.search(
        r"required:\s*\[\s*['\"]slug['\"],\s*['\"]subq['\"],\s*['\"]role['\"]",
        graph,
    ), (
        "候选的定向决定必须是结构化必填字段"
    )
    assert re.search(
        r"required:\s*\[\s*['\"]id['\"],\s*['\"]coverage['\"],\s*['\"]items['\"],\s*['\"]cards['\"]",
        graph,
    ), (
        "子问题回执必须带全量两张表"
    )
    assert "page: dossier" in graph and "page: spine" in graph, "synth 分页派发"
    assert "synth-dossier" in body and "synth-topic:${slug}" in body
    assert "dirty" in body, "只重写脏专章"
    assert "saturated" in body, "掌舵可在轮数用尽前收口"
    assert "subq" in graph and "role" in graph, "候选带子问题与角色标签"
    assert re.search(
        r"new Set\(\s*\(initialSteer && initialSteer\.dirty\) \|\| \[\]",
        body,
    ), (
        "种子轮回执的 dirty/建议词必须入账"
    )
    assert "steerReceipts" in body, "收到过活回执才不全量重写手写老专章"
    assert "r1-close" in body, "recall-only 主题补一次收口掌舵"
    assert "snowball_members:" in graph, "已定向候选的 subq/role 必须跨采集保留"
    assert re.search(
        r"roundOk\.forEach\(\s*\(item\) => item\.subq && dirty\.add\(item\.subq\)",
        body,
    ), (
        "掌舵失败也不能丢掉本轮语料的脏页账"
    )


def test_orchestrate_topic_runs_the_webcard_channel_on_its_own_track():
    """sky-mobi 类主题的证据在 SEC 文件/工信部规章/SDK 遗存/口述里,学术传感器全程失明:
    `queue` 恒空,只看它循环一轮都滚不起来。圈外通道必须能独立驱动循环,且证据卡**不进**
    ok 语料表 —— 卡不是 vault 分析件,itemPath() 会把它解析成一条读不到的 vault/papers 路径。"""
    graph = workflow_source()
    body = topic_body(graph)

    assert "quasi:webcard-agent" in body, "证据卡 agent 必须在图里"
    assert "CARD_SCHEMA" in graph, "卡回执要 schema,散文读不到 status"
    assert re.search(r"while\s*\(\s*\(queue\.length \|\| webTasks\.length\)", body), (
        "web_tasks 单独也要能驱动循环"
    )
    assert re.search(
        r"!queue\.length\s*&&\s*!local\.length\s*&&\s*!webTasks\.length", body
    ), (
        "只有三条通道全空才是 no_works"
    )
    # 卡与语料两条账:cards[] 独立累计,ok 里永远只有 book/paper/talk。
    for declaration in (
        "const cards = []",
        "const cardSlugs = new Set()",
        "const cardAttempts = new Set()",
        "const availableCards = new Set()",
    ):
        assert declaration in body
    assert "ok.push(...roundOk)" in body and "cards.push(card)" in body
    assert "ok.length + cardCount" in body, (
        "死胡同卡点按证据总量判,纯圈外主题不能被误判成没找到东西"
    )
    # webcard 先启动,与学术探针/router 并行;结果仍保留 null index,并经另一 agent 验文件。
    assert body.index("const cardWork = parallel(") < body.index("const probe ="), (
        "两个独立通道不得串行"
    )
    assert "const cardResults = await cardWork" in body, (
        "卡回执不得 filter(Boolean),会错位 index"
    )
    assert re.search(
        r"cardExistencePrompt\(\s*slug,\s*claimedFiles\.map", body
    ), (
        "agent 自报 ok 不足以入账"
    )
    assert re.search(
        r"roundCards\s*\.filter\(\(card\) => card\.status === ['\"]ok['\"]\)",
        body,
    ), "unchanged 卡不重写专章"
    assert re.search(r"kind:\s*['\"]card['\"]", body) and "failures.push" in body, (
        "empty/error/missing 要进入失败账"
    )
    # 卡路径是独立解析器,不并进 itemPath —— 共用会让任何手滑静默变成死链。
    assert re.search(
        r"(?:export\s+)?const cardPath = \(topicSlug, cardSlug\) =>", graph
    )
    assert "cards/${cardSlug}.md" in graph
    assert "card_paths:" in graph, "两种 synth 页都要收到卡通道"
    assert "new_cards:" in graph, "掌舵要收到本轮新卡,登记进 outline 的 cards"


def test_topic_caps_are_positive_and_audit_only_touches_current_outputs():
    graph = workflow_source()
    body = topic_body(graph)

    assert re.search(r"(?:export\s+)?const positiveInt\s*=", graph)
    assert "Number(meta.maxCardsPerRound) || 3" not in body, (
        "负数不能让 slice 放开几乎整队任务"
    )
    assert "positiveInt(meta.maxCardsPerRound, 3)" in body
    assert re.search(r"minLength:\s*2,\s*maxLength:\s*80", graph), (
        "Workflow slug schema 必须与持久 schema 同界"
    )
    assert "const auditPaths =" in body and "path: vault/topics/${slug}`" not in body, (
        "增量跑只审本轮写过的 spine/outline/dossier/card"
    )
    for owner in ("regen-outline:", "regen-dossier:", "regen-card:", "regen-topic:"):
        assert owner in body, f"audit escalation 必须回到对应 writer: {owner}"

    run_card_helpers("""
eq(positiveInt(0.5, 3), 3, '正小数 floor 后为 0,必须回退')
eq(positiveInt(1.9, 3), 1, '正配额向下取整')
eq(positiveInt(-2, 3), 3, '负配额回退')
""")


def test_organise_topic_gates_dead_end_back_to_the_user():
    """Snowball runs dry long before the corpus is useful; the graph can only report that, the
    seeds decision is the user's. Dropping the gate turns a 2-item topic into a silent `ok`."""
    text = (PLUGIN_ROOT / "skills" / "organise-topic" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "needs_seeds" in text, "the dead-end status must reach a human gate"
    assert "suggested_queries" in text, (
        "the widening hints must be shown, not swallowed"
    )
    assert '"已收证据卡": result.cards' in text, (
        "human gate must not report 0 when web evidence exists"
    )


def test_public_skills_carry_material_and_topic_post_steps():
    """0.49.0 retired the per-kind process-* skills; the two post-processing contracts they owned
    must survive in process-material or they silently vanish: process-paper's opt-in translation
    (shared Workflow Translation derivative) and process-author's LOCALISE loop
    over the books it landed (which needs the graph to report WHICH books — counts can't drive
    a loop)."""
    skill = (PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    topic_skill = (
        PLUGIN_ROOT / "skills" / "organise-topic" / "SKILL.md"
    ).read_text(encoding="utf-8")
    graph = workflow_source()

    assert re.search(
        r"book_slugs:\s*books\.map\(\(member\) => member\.id\)", graph
    ), (
        "author receipt must name the landed books, not just count them"
    )
    assert 'result.get("book_slugs")' in skill, (
        "the author LOCALISE loop must read the graph's book list"
    )
    assert 'result.get("book_slugs")' in topic_skill, (
        "the topic LOCALISE loop must read the graph's book list"
    )
    assert 'wf_args["translate"] = True' in skill, (
        "paper translation intent must enter the same shared Workflow run"
    )
    assert '"kind": "translate"' in skill, (
        "a direct Translation derivative must use the shared bundle"
    )
    assert "translation_receipt" in skill
    assert 'Agent("quasi:translate-agent"' not in skill
    assert "not exists(f\"processing/translations/" not in skill
    assert "实验" not in skill, (
        "the skill is no longer experimental; stale framing misroutes the model"
    )

    # 0.49.1: the same duplicate-vault_slug account settled in topic (0.48.3) applies to author —
    # two candidate slugs can resolve to one material key; and topic-landed books need the
    # LOCALISE list too. Strict Author writer failures are never automatically resubmitted.
    assert "const byKey = new Map()" in graph, (
        "author book corpus must be duplicate-free"
    )
    assert "byKey.set(materialKey, demand)" in graph, (
        "author paper corpus must be duplicate-free"
    )
    assert "synth_failed 自动重投一次" not in skill
    assert re.search(
        r"ok\s*\.filter\(\(item\) => item\.kind === ['\"]book['\"]\)", graph
    ), (
        "topic receipt must carry landed book slugs"
    )
    assert 'result.status == "synth_failed"' not in skill, (
        "strict Paper/Book/Author writers must never auto-resubmit"
    )
    assert 'result.status == "synth_failed"' in topic_skill, (
        "the still-legacy Topic synthesis compatibility retry remains explicit"
    )


def test_material_and_topic_have_distinct_public_routing_hints():
    material = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    topic = (
        PLUGIN_ROOT / "skills" / "organise-topic" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "topic review" not in frontmatter_description(
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    )
    assert "organise a topic" in frontmatter_description(
        PLUGIN_ROOT / "skills" / "organise-topic" / "SKILL.md"
    )
    assert 'args.kind not in ("book", "paper", "author", "talk", "translate")' in material
    assert 'follow_reference("references/talk.md")' in material
    assert '{"kind": "topic"' in topic


def test_extract_agent_is_readonly_and_graph_receipt_owns_chapter_inventory():
    ex = (PLUGIN_ROOT / "agents" / "extract-agent.md").read_text(encoding="utf-8")
    operation = source_file("operations/extract.mjs")
    book = source_file("materials/book.mjs")

    assert "tools: Read" in ex
    assert "提取、OCR、\n事务提交" in ex
    assert "不写文件" in ex
    assert "旧“提取→验证→修复”prompt" in ex
    assert "export const CHAPTER_EXTRACT_SCHEMA" in operation
    assert "chapters:" in operation
    assert "chapterInventory" in book
    assert "receipt.chapters" in book


def test_book_graph_consumes_cli_manifest_filenames_without_reinventing_them():
    book = source_file("materials/book.mjs")

    assert "const CHAPTER_SLOT = /^\\d{2,3}[a-z]{0,2}$/;" in book
    assert 'chapter.filename.startsWith(`${chapter.slot}_`)' in book
    assert 'chapter.filename.endsWith(".txt")' in book
    assert "`ch${chapter.slot}-${chapter.slug}.txt`" not in book


def test_synthesis_agent_consumes_only_graph_supplied_members():
    text = (PLUGIN_ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")

    assert "单产物综合 worker" in text
    assert "有序、互异" in text
    assert "禁止 Glob 发现成员" in text
    assert "目录扫描" in text
    assert "Book chapter Read" in text
    assert "mode: book" not in text
    assert "mode: author" not in text


def test_orchestrate_agents_carry_explicit_phase_and_distinguishable_labels():
    """A real Agre author run rendered 19 chapter agents as identical `analyse:agre-reinventing-tec…`
    rows filed under the *Paper* phase — read as "60+ runaway papers" when every cap had held.
    Two display defects, both real: `phase()` is global state and races under parallel recursion
    (opts.phase is the documented fix), and the chapter slot sat past the label truncation point."""
    text = workflow_source()
    body = "\n".join(
        source_file(path)
        for path in (
            "materials/book.mjs",
            "materials/paper.mjs",
            "collections/author.mjs",
            "research/topic.mjs",
        )
    )

    assert not re.search(r"\{\s*agentType:", body), (
        "every agent call must pin its node's phase explicitly"
    )
    assert len(re.findall(r"phase:\s*['\"]", body)) >= 30, (
        "opts.phase belongs on every call site, not a sample"
    )
    assert "`${mode === \"repair\" ? \"regen\" : \"analyse\"}-ch${chapter.slot}:${state.slug}`" in text, (
        "the chapter slot must survive truncation"
    )
    assert "`refill-ch${chapter.slot}:${slug}`" in text
    assert '"regen-synth"' in text


def test_orchestrate_retries_every_receipt_reading_agent():
    """agent() returns null when the subagent dies on a terminal API error, and every call site
    used to read that null as a content answer: a dead probe re-processes the whole author batch
    (destructive re-extract), a dead audit reads as clean, a dead chapter leaves the book at 8/9
    (Bowker 2005 — ch04 and ch07 both died, one refill round could only save one)."""
    text = (PLUGIN_ROOT / "workflows" / "process-material.mjs").read_text(
        encoding="utf-8"
    )

    # 0.49.9: agent() is wrapped in guard() (timeout → null), so retryNull re-dispatches on guard's null.
    assert "?? guard(" in text, "retryNull must re-dispatch on a null receipt"
    # A receipt with a schema is one the script branches on, so it must go through retryNull.
    lines = text.splitlines()
    bare = []
    for i, line in enumerate(lines):
        if "await agent(" not in line:
            continue
        call = []  # the call's own lines, up to the `})` that closes its opts
        for nxt in lines[i : i + 6]:
            call.append(nxt)
            if "})" in nxt:
                break
        if any("schema:" in c for c in call):
            bare.append(i + 1)
    assert bare == [], (
        f"receipt-reading agent() calls must use retryNull; bare at lines {bare}"
    )


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
    assert "孤儿卡" in steer and "文件缺失" in steer, (
        "卡写成后掌舵失败与手工删除都要在下轮对账"
    )
    assert "即使为空也必须显式返回 `[]`" in steer, "图依赖全量 items/cards 表"


def test_synthesis_topic_mode_is_outline_pinned_and_paged():
    """54 条平铺语料整篇重织是 0.49.x 综述'越滚越乱'的一半病根(另一半在采集)。§T 拆页:
    dossier 每页只读本聚类语料(读预算结构性受控),spine 恒薄且聚类结构照抄 outline,
    不再每次即兴。outline 页本身由 steer-agent 写,synth 不碰。"""
    synth = (PLUGIN_ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")

    assert "page: spine" in synth and "page: dossier" in synth
    assert "kind: dossier" in synth
    assert "kind(overview|resources|dossier)" in synth, (
        "outline 不在 synth 的可写 kind 里"
    )
    assert "inline_clusters" in synth and "dossier_pages" in synth
    assert "照抄" in synth, "聚类 id/标题/顺序来自 outline,不许重排"
    assert "子问题地图" in synth, "00 新模板围绕子问题"
    # 卡是一手证据不是同行评议结论;两页都收 card_paths,但 synth 永远不写 cards/。
    assert synth.count("card_paths") >= 2, "dossier 与 spine 两页都要收卡通道"
    assert "kind: card 归 webcard-agent" in synth
    assert "永远不写" in synth


def test_pending_cards_requires_stable_slugs_and_applies_the_cap_early():
    """card_slug 是 steer 的稳定身份合同:缺失/坏值/重名直接不派,图不另造文件名。
    cap 在遍历中生效,避免先处理整张任务表再把尾部丢掉。"""
    run_card_helpers("""
const st = { web_tasks: [
  { subq: 'sq-a', query: 'Sky-mobi SEC F-1 filing', note: 'n', card_slug: 'sky-mobi-sec-f1' },
  { subq: 'sq-b', query: '工信部入网许可', note: 'n', card_slug: 'miit-license' },
  { subq: 'sq-b', query: '摩豆平台遗存', note: 'n', card_slug: 'moduo-sdk' },
  { subq: 'sq-a', query: 'duplicate', note: 'n', card_slug: 'sky-mobi-sec-f1' },
  { subq: 'sq-c', query: 'missing slug' },
  { subq: 'sq-c', query: 'bad slug', card_slug: '../escape' },
  { subq: 'sq-c', query: 'short slug', card_slug: 'a' },
  { subq: 'sq-c', query: 'long slug', card_slug: 'a'.repeat(81) },
] }
const out = pendingCards(st, [], 2)
eq(out.tasks.map(t => t.card_slug), ['sky-mobi-sec-f1', 'miit-license'], '只派前两条有效任务')
eq(out.dropped, 1, '只报告被 cap 截掉的有效任务')
eq(pendingCards(st, ['sky-mobi-sec-f1'], 3).tasks.map(t => t.card_slug),
   ['miit-license', 'moduo-sdk'], '本轮尝试过的 slug 不重抓')
eq(cardPath('sky-mobi', 'sq-b'), 'vault/topics/sky-mobi/cards/sq-b.md', 'card 路径')
""")


def test_existing_outline_cards_need_disk_proof_and_never_become_corpus():
    """既有卡只有 test -s 成功才算证据;坏 slug 不进路径。本轮新卡同时合进子问题,
    即使掌舵随后失败也不会在当前 synth 里变成未归类。"""
    src = workflow_source()
    body = topic_body(src)

    assert "cardExistencePrompt(slug, priorCards)" in body, (
        "outline 卡必须经独立磁盘探针"
    )
    assert "!availableCards.size" in body, "只有真实存在的卡才能阻止 no_works"
    assert re.search(
        r"const liveRegistered = registered\(steer\)\.filter\(\(card\) =>\s*availableCards\.has\(card\)",
        body,
    )
    assert re.search(
        r"const cardCount = new Set\(\[\s*\.\.\.liveRegistered,\s*\.\.\.cardSlugs",
        body,
    )
    assert "const evidence = ok.length + cardCount" in body, (
        "证据 = 学术语料 + 已验证卡"
    )
    assert "cards: cardCount" in body, "回执报的卡数也要含既有卡"
    assert "ok = [...local]" in body, "既有卡不进学术语料表"
    assert re.search(
        r"const subquestions = mergeCards\(\s*mergeItems\(persistedSubquestions, ok\),\s*cards",
        body,
    ), (
        "掌舵失败时本轮语料与卡都要立即归入子问题"
    )

    run_card_helpers("""
const steer = {
  subquestions: [
    { id: 'sq-a', cards: ['sky-mobi-sec-f1', 'moduo-sdk', '../escape'] },
    { id: 'sq-b', cards: ['miit-license'] },
    { id: 'sq-c', cards: [] },
  ],
  web_tasks: [{ subq: 'sq-a', query: 'Sky-mobi F-1 amendment', card_slug: 'sky-mobi-sec-f1' }],
}
eq(registered(steer).sort(), ['miit-license', 'moduo-sdk', 'sky-mobi-sec-f1'], '坏 slug 被边界挡住')
eq(pendingCards(steer, [], 3).tasks.map(t => t.card_slug), ['sky-mobi-sec-f1'], '既有卡可显式刷新')
eq(pendingCards(steer, ['sky-mobi-sec-f1'], 3).tasks, [], '本轮尝试过的不重抓')
const mergedItems = mergeItems(steer.subquestions, [
  { kind: 'paper', slug: 'new-paper', subq: 'sq-b', role: 'evidence' },
  { kind: 'author', slug: 'not-an-outline-item', subq: 'sq-b', role: 'context' },
])
eq(mergedItems.find(s => s.id === 'sq-b').items,
   [{ kind: 'paper', slug: 'new-paper', role: 'evidence' }],
   '掌舵失败时仍按原 subq/role 收编学术成员,author 不混入 outline items')
const merged = mergeCards(mergedItems, [
  { subq: 'sq-b', card_slug: 'new-card' }, { subq: 'sq-b', card_slug: 'miit-license' },
])
eq(merged.find(s => s.id === 'sq-b').cards, ['miit-license', 'new-card'], '新卡归入子问题且去重')
""")


def test_webcard_agent_contract_forbids_invention_and_owns_one_card():
    """圈外通道的失败模式是幻觉:一张编造的机型卡会被 synth 当证据引用,比没有卡更坏。
    合同必须挡住三件事 —— 用训练知识补完、写 cards/ 以外的文件、抓不到也硬写一张空卡。"""
    card = (PLUGIN_ROOT / "agents" / "webcard-agent.md").read_text(encoding="utf-8")

    assert "name: webcard-agent" in card
    assert "kind: card" in card and "cards/{card-slug}.md" in card, (
        "产物路径与 schema kind"
    )
    assert "不许" in card and "训练知识" in card, "抓不到不许凭训练知识补完"
    assert "WebFetch" in card and "quasi-search kagi" in card, (
        "检索 + 一手来源抓取两件工具"
    )
    assert "confirmed" in card and "single-source" in card and "disputed" in card, (
        "证据等级三档"
    )
    assert "缺口/存疑" in card, "卡必须自陈缺口,无缺口的圈外卡多半没核验"
    assert "不进语料表" in card, "卡不是 vault 分析件"
    assert '"empty"' in card, "抓不到就不写文件,不留空卡"
    assert '"unchanged"' in card and "只用 Edit" in card, (
        "刷新无变化不重写,旧元数据不靠 LLM 重抄"
    )
    assert "品类合集" in card and "拆成多个文件" in card, (
        "按品类汇总的卡仍是一张卡,不拆成单机文件"
    )
    guide = (PLUGIN_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "sole remote-tool exception is `webcard-agent`" in guide, (
        "WebFetch 例外必须写进层级合同"
    )


def test_talk_reference_is_a_single_shared_workflow_ingress():
    """Talk 的 compress/transcribe/classify/analyse/audit 控制边属于同一张 graph。

    这是静态 Skill/Agent 边界检查，不是 native Claude Workflow E2E。
    """
    material_skill = (
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    ).read_text(encoding="utf-8")
    skill = (
        PLUGIN_ROOT
        / "skills"
        / "process-material"
        / "references"
        / "talk.md"
    ).read_text(encoding="utf-8")
    transcribe = (PLUGIN_ROOT / "agents" / "transcribe-agent.md").read_text(
        encoding="utf-8"
    )
    analyse = (PLUGIN_ROOT / "agents" / "analyse-agent.md").read_text(
        encoding="utf-8"
    )
    audit = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(
        encoding="utf-8"
    )

    assert not (PLUGIN_ROOT / "skills" / "process-talk").exists()
    assert "references/talk.md" in material_skill
    assert "meeting" in frontmatter_description(
        PLUGIN_ROOT / "skills" / "process-material" / "SKILL.md"
    )
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    assert '"kind": "talk"' in skill
    assert skill.count("return Workflow(") == 1
    assert "material_receipt" in skill
    assert "talk.reconcile" in skill
    assert "不得在 Skill 内复制" in skill
    assert 'Agent("quasi:analyse-agent"' not in skill
    assert 'Agent("quasi:audit-agent"' not in skill
    assert "Step 1a COMPRESS_MEDIA" not in skill
    assert "Step 3  SUMMARISE" not in skill
    assert "Step 4  AUDIT" not in skill

    for key in (
        "talk.observe",
        "talk.prepare-media",
        "talk.transcribe",
        "talk.classify",
        "talk.render-silent",
    ):
        assert key in transcribe
    assert "完整的 operation envelope" in analyse
    assert "talk.analyse" not in analyse
    assert "唯一 target ref" in audit
    assert "通用 audit transaction" in audit
