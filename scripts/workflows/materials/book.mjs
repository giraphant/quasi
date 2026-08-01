import { BOOK_TEMP_PATH, validYearEvidence } from "../operations/book-year-evidence.mjs";
import { bookAcquire, bookAudit, bookPrepare, bookSynthesise, chapterAnalyse } from "../operations/rows/book.mjs";
import { exactKeys, optionalText, validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { runMaterialLoop } from "./interpreter.mjs";
import { assembleMaterialReceipt, stageUserGate } from "./receipt.mjs";

const BOOK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CATEGORIES = new Set(["monograph", "edited-volume", "handbook", "other"]);

const operationFailure = (code, operationKey, outcome = "known", retryable = false, message = null) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable,
  ...(message ? { message } : {}),
});

function validateBookIdentity(slug, meta) {
  if (typeof slug !== "string" || !BOOK_SLUG.test(slug))
    return { ok: false, code: "book.slug_invalid", message: "book slug is not canonical", canonicalSlug: null };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return { ok: false, code: "book.identity_invalid", message: "book metadata must be an object", canonicalSlug: slug };
  if (!validText(meta.title, 1, 500))
    return { ok: false, code: "book.identity_invalid", message: "title is missing or invalid", canonicalSlug: slug };
  if (!Array.isArray(meta.authors) || meta.authors.length < 1 || meta.authors.length > 32 || meta.authors.some((author) => !validText(author, 1, 200)))
    return { ok: false, code: "book.identity_invalid", message: "authors must be a bounded non-empty string array", canonicalSlug: slug };
  if (!Number.isInteger(meta.year) || meta.year < 1500 || meta.year > 2030)
    return { ok: false, code: "book.identity_invalid", message: "year must be an integer in the supported range", canonicalSlug: slug };
  if (!validText(meta.publisher, 2, 500))
    return { ok: false, code: "book.identity_invalid", message: "publisher is required for canonical synthesis", canonicalSlug: slug };
  const category = meta.category || "other";
  if (!CATEGORIES.has(category))
    return { ok: false, code: "book.identity_invalid", message: "category is invalid", canonicalSlug: slug };
  if (!optionalText(meta.isbn, 100) || (meta.format != null && !["pdf", "epub"].includes(meta.format)) || (meta.confidence !== undefined && !["provided", "verified"].includes(meta.confidence)))
    return { ok: false, code: "book.identity_invalid", message: "optional identity fields are invalid", canonicalSlug: slug };
  const normalized = {
    title: meta.title,
    authors: [...meta.authors],
    year: meta.year,
    publisher: meta.publisher,
    isbn: meta.isbn || null,
    category,
    format: meta.format || null,
    confidence: meta.confidence === "verified" ? "verified" : "provided",
  };
  return { ok: true, canonicalSlug: slug, meta: normalized, fingerprint: JSON.stringify(normalized) };
}

function validateYearDecision(decision, slug, meta) {
  if (decision == null) return { ok: true, value: null };
  if (!exactKeys(decision, ["action", "tmp_path", "year_evidence"]) || !["accept-current", "use-recommended-year"].includes(decision.action) || typeof decision.tmp_path !== "string" || !BOOK_TEMP_PATH.test(decision.tmp_path) || !validYearEvidence(decision.year_evidence, decision.year_evidence && decision.year_evidence.slug_year) || !["MISMATCH", "AMBIGUOUS"].includes(decision.year_evidence.verdict) || (meta.format != null && !decision.tmp_path.endsWith(`.${meta.format}`)))
    return { ok: false, code: "book.year_decision_invalid", message: "year_decision must exactly identify a prior year gate and temp artifact" };
  if (decision.action === "accept-current" && meta.year !== decision.year_evidence.slug_year)
    return { ok: false, code: "book.year_decision_invalid", message: "accept-current requires the unchanged prior canonical year" };
  if (decision.action === "use-recommended-year" && (decision.year_evidence.verdict !== "MISMATCH" || decision.year_evidence.recommended_year === null || meta.year !== decision.year_evidence.recommended_year || meta.year === decision.year_evidence.slug_year || !slug.endsWith(`-${meta.year}`)))
    return { ok: false, code: "book.year_decision_invalid", message: "use-recommended-year requires an updated canonical slug and metadata year" };
  return { ok: true, value: decision };
}

function normalizeBookOptions(slug, meta, opts) {
  const yearDecision = validateYearDecision(opts.yearDecision, slug, meta);
  if (!yearDecision.ok || (yearDecision.value && opts.batchYear === true))
    return { ok: false, code: "book.year_decision_invalid", message: yearDecision.message || "year_decision is not an Author batch policy" };
  return { ok: true, value: { ...opts, yearDecision: yearDecision.value } };
}

function createBookState(slug, meta) {
  const root = `processing/chapters/${slug}`;
  const allowedFormats = meta.format ? [meta.format] : ["epub", "pdf"];
  return {
    slug,
    meta,
    materialKey: `book:${slug}`,
    source: null,
    allowedSources: allowedFormats.map((format) => ({ format, path: `sources/${slug}.${format}` })),
    sourceText: `${root}/source.txt`,
    ocrSource: `${root}/ocr.pdf`,
    ocrText: `${root}/ocr.txt`,
    chaptersDir: root,
    manifest: `${root}/manifest.json`,
    canonical: `vault/books/${slug}/00-overview.md`,
    operations: [],
    artifacts: [],
    audit: [],
    warnings: [],
    disposition: null,
    repaired: false,
    chapterInventory: null,
    chapters: [],
    chapterOutputs: [],
    owners: null,
    refillPresent: new Set(),
    chapterChanged: false,
    yearEvidence: null,
    userGate: null,
    budgets: { refill: { used: 0, limit: 1 }, auditRepair: { used: 0, limit: 1 }, auditPasses: { used: 0, limit: 2 } },
  };
}

function bookReceipt(state, status, stage, failure = null) {
  const inventory = state.chapterInventory;
  return assembleMaterialReceipt(state, {
    kind: "book",
    status,
    stage,
    failure,
    fields: inventory ? { expected_slots: [...inventory.expected_slots], present_slots: [...inventory.present_slots], missing_slots: [...inventory.missing_slots] } : {},
    resume:
      status === "blocked"
        ? failure && failure.outcome === "unknown"
          ? { operation_key: "book.reconcile" }
          : { operation_key: "book.user-gate", stage, policy: stage === "download" ? "human-year-decision-or-correct-request" : "caller-correct-request" }
        : status === "needs_input"
          ? { operation_key: "book.user-gate", stage, policy: stage === "download" ? "human-year-decision-or-correct-request" : "answer-the-stage-question" }
          : null,
  });
}

function bookResult(state, publicStatus, stage, extra = {}, failure = null, terminalOverride = null) {
  const status = terminalOverride || (publicStatus === "ok" ? "complete" : publicStatus === "needs_input" ? "needs_input" : publicStatus === "blocked" ? "blocked" : "failed");
  return { slug: state.slug, status: publicStatus, ...extra, material_receipt: bookReceipt(state, status, stage, failure) };
}

function rejectedBookResult(slug, validation) {
  const safe = typeof slug === "string" ? slug : null;
  const state = createBookState(safe, { format: null });
  state.materialKey = typeof slug === "string" && BOOK_SLUG.test(slug) ? `book:${slug}` : null;
  return bookResult(state, "blocked", "identity", {}, operationFailure(validation.code, "book.identity", "known", false, validation.message || "conflicting book identity"));
}

const stageFailure = (fallback, operationKey) => (receipt, outcome = "known") => {
  const issue = stageIssue(receipt);
  return operationFailure((issue && issue.code) || fallback, operationKey, outcome, !!(issue && issue.retryable), (issue && issue.summary) || `${operationKey} did not complete`);
};
const acquireFailure = stageFailure("book.acquire_failed", "book.acquire");
const prepareFailure = stageFailure("book.prepare_failed", "book.prepare");
const analyseFailure = stageFailure("book.chapter_analysis_failed", "chapter.analyse");
const synthesiseFailure = stageFailure("book.synthesise_failed", "book.synthesise");
const auditFailure = stageFailure("book.audit_failed", "book.audit");

const chapterInputPath = (state, chapter) => `${state.chaptersDir}/${chapter.filename}`;
const chapterOutputPath = (state, chapter) => `vault/books/${state.slug}/ch${chapter.slot}-${chapter.slug}.md`;

function chapterOwners(state) {
  const owners = new Map([[state.canonical, { key: "book.synthesise", chapter: null }]]);
  for (const chapter of state.chapters)
    owners.set(chapterOutputPath(state, chapter), { key: "chapter.analyse", chapter });
  return owners;
}

function addPreparedBook(state, receipt, _meta, _opts, _call, _context, runtime) {
  state.artifacts = state.artifacts.filter((artifact) => !["normalized_document", "recovery_source", "chapter_manifest", "normalized_chapter"].includes(artifact.role));
  for (const artifact of receipt.artifacts) state.artifacts.push({ ...artifact, producer: "book.prepare" });
  state.chapters = receipt.chapters;
  runtime.log(`${state.slug}: validated ${state.chapters.length} exact chapters`);
  return { receipt };
}

function joinChapters(state, values, items, _meta, _opts, call) {
  if (call.mode === "repair") {
    for (const entry of values) {
      if (entry.receipt.terminal.status !== "complete")
        return { terminal: bookResult(state, "audit_escalated", "repair", { escalated: call.auditEscalated || [] }, analyseFailure(entry.receipt)) };
      if (entry.receipt.terminal.action === "repair") state.chapterChanged = true;
    }
    if (state.chapterChanged) state.repaired = true;
    return { repaired: values };
  }
  const present = new Set(state.refillPresent);
  values.forEach((entry, index) => { if (entry.present) present.add(items[index].slot); });
  const expectedSlots = items.map((chapter) => chapter.slot);
  const missing = items.filter((chapter) => !present.has(chapter.slot));
  state.chapterInventory = {
    expected_slots: expectedSlots,
    present_slots: expectedSlots.filter((slot) => present.has(slot)),
    missing_slots: missing.map((chapter) => chapter.slot),
  };
  if (missing.length)
    return { terminal: bookResult(state, "chapters_incomplete", "chapter-join", { analysed: items.length - missing.length, expected: items.length, expected_slots: [...state.chapterInventory.expected_slots], present_slots: [...state.chapterInventory.present_slots], missing_slots: [...state.chapterInventory.missing_slots] }, operationFailure("book.chapters_incomplete", "book.join")) };
  state.chapterOutputs = items.map((chapter) => chapterOutputPath(state, chapter));
  state.artifacts = state.artifacts.filter((artifact) => artifact.role !== "chapter_canonical");
  for (const path of state.chapterOutputs)
    state.artifacts.push({ role: "chapter_canonical", path, exists: true, usable: null, producer: "chapter.analyse" });
  state.owners = chapterOwners(state);
  return { chapters: values };
}

function applySynthesis(state, receipt, _meta, _opts, call) {
  const { action } = receipt.terminal;
  const reconciled = action === "reconciled";
  state.artifacts = state.artifacts.filter((artifact) => artifact.role !== "canonical");
  state.artifacts.push({ role: "canonical", path: state.canonical, exists: true, usable: null, producer: reconciled ? "book.synthesise:reconciled" : "book.synthesise" });
  if (call.mode === "repair" && action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (call.mode === "repair" && reconciled) state.disposition = state.disposition || "reused";
  else if (reconciled) state.disposition = "reused";
  else state.disposition = "created";
  return { receipt, reconciled };
}

function unknownAuditPath(receipt, state) {
  return [...receipt.escalated.map((item) => item.path), ...receipt.mutated_paths].find((path) => !state.owners.has(path));
}

function auditEscalations(receipt, state) {
  const path = unknownAuditPath(receipt, state);
  return path && !receipt.escalated.some((item) => item.path === path)
    ? [...receipt.escalated, { path, kind: "mutation_owner_unknown", reason: "audit mutated a path with no exact Book producer owner" }]
    : receipt.escalated;
}

function applyBookAudit(state, receipt) {
  if (unknownAuditPath(receipt, state))
    return { terminal: bookResult(state, "audit_escalated", "audit", { escalated: auditEscalations(receipt, state) }, operationFailure("book.repair_owner_unknown", "book.audit")) };
  return { receipt, clean: receipt.terminal.status === "complete" && receipt.remaining_violations === 0 && receipt.escalated.length === 0 };
}

function bookRepairInput(state, audited) {
  if (audited.receipt.mutated_paths.length) state.repaired = true;
  if (audited.clean && audited.receipt.mutated_paths.length === 0) return null;
  state.budgets.auditRepair.used += 1;
  const byTarget = new Map();
  for (const diagnostic of audited.receipt.escalated) {
    const entries = byTarget.get(diagnostic.path) || [];
    if (!entries.some((entry) => entry.kind === diagnostic.kind && entry.reason === diagnostic.reason)) entries.push(diagnostic);
    byTarget.set(diagnostic.path, entries);
  }
  const chapterRepairs = state.chapters
    .map((chapter) => ({ chapter, diagnostics: byTarget.get(chapterOutputPath(state, chapter)) || [] }))
    .filter((entry) => entry.diagnostics.length);
  const overviewDiagnostics = byTarget.get(state.canonical) || [];
  const chapterMutatedByAudit = audited.receipt.mutated_paths.some((path) => state.owners.get(path) && state.owners.get(path).key === "chapter.analyse");
  return { audit: audited.receipt, chapterRepairs, overviewDiagnostics, chapterMutatedByAudit };
}

function bookRepairTargets(state, plan) {
  const diagnostics = plan.overviewDiagnostics.length
    ? plan.overviewDiagnostics
    : [{ path: state.canonical, kind: "chapter_dependency_changed", reason: "an audited chapter or overview changed after synthesis" }];
  return [
    { stage: "Analyse", when: () => plan.chapterRepairs.length > 0, call: { items: plan.chapterRepairs, auditEscalated: plan.audit.escalated } },
    { stage: "Synthesise", when: (state) => state.chapterChanged || plan.chapterMutatedByAudit || plan.overviewDiagnostics.length > 0, diagnostics },
  ];
}

function exhaustedBookRepair(state, audited) {
  if (audited.receipt.mutated_paths.length) state.repaired = true;
  const stale = audited.receipt.mutated_paths.some((path) => path !== state.canonical);
  if (audited.clean && !stale) return null;
  const diagnostics = [...audited.receipt.escalated];
  for (const path of audited.receipt.mutated_paths)
    if (path !== state.canonical && !diagnostics.some((item) => item.path === path && item.kind === "mutation_after_repair_budget"))
      diagnostics.push({ path, kind: "mutation_after_repair_budget", reason: "re-audit changed a chapter after the single synthesis repair budget" });
  return bookResult(state, "audit_escalated", "audit", { escalated: diagnostics }, operationFailure("book.repair_exhausted", "book.audit"));
}

const bookTable = {
  kind: "book",
  identity: {
    pattern: BOOK_SLUG,
    validate: validateBookIdentity,
    key: (slug) => `book:${slug}`,
    fingerprint: (_slug, meta) => JSON.stringify(meta),
    conflict: () => ({ code: "book.identity_conflict", message: "same-run requests disagree on the book identity" }),
  },
  options: normalizeBookOptions,
  state: createBookState,
  receipt: bookReceipt,
  reject: rejectedBookResult,
  emit: (state, { status, receiptStatus, stage, extra, failure }) => bookResult(state, status, stage, extra, failure, receiptStatus || null),
  unknown: (state, descriptor, receipt) => bookResult(state, "blocked", descriptor.receiptStage, {}, (receipt && receipt.failure) || operationFailure("material.writer_outcome_unknown", descriptor.operationKey, "unknown")),
  mismatch: (state, descriptor) => bookResult(state, "blocked", descriptor.receiptStage, {}, operationFailure("book.writer_receipt_mismatch", descriptor.operationKey, "unknown", false, "writer receipt did not prove the exact contract")),
  stages: [
    {
      stage: "Acquire", receiptStage: "download", operationKey: "book.acquire", row: bookAcquire,
      label: (state) => `${state.slug}:acquire`,
      context: (state, _meta, opts) => ({ materialKey: state.materialKey, slug: state.slug, meta: state.meta, allowedSources: state.allowedSources, expectedYear: state.meta.year, batchAcceptYear: opts.batchYear === true, yearDecision: opts.yearDecision, artifactRoles: ["source"] }),
      routeOptions: (state) => ({
        failure: acquireFailure,
        onReceipt: (receipt, edge) => { if (edge !== "unknown" && edge !== "mismatch") state.yearEvidence = receipt.year_evidence || null; },
        needsInputGate: (receipt) => { const { year_evidence, tmp_path, proposed_actions } = receipt.terminal; state.yearEvidence = year_evidence; return stageUserGate(receipt, { year_evidence, tmp_path, proposed_actions }); },
        needsInputExtra: (receipt) => ({ question: receipt.terminal.issue.user_question, year_evidence: receipt.terminal.year_evidence, tmp_path: receipt.terminal.tmp_path, proposed_actions: receipt.terminal.proposed_actions }),
        failedStatus: "download_failed",
        failedExtra: (receipt) => ({ failure_reason: receipt.terminal.issue.summary, attempts: receipt.attempts }),
      }),
      apply: (state, receipt) => {
        state.source = receipt.output_path;
        state.meta = { ...state.meta, format: receipt.format };
        state.artifacts.push({ role: "source", path: state.source, exists: true, usable: null, producer: receipt.disposition === "reused" ? "book.acquire:reconciled" : "book.acquire" });
      },
    },
    {
      stage: "Prepare", receiptStage: "prepare", operationKey: "book.prepare", row: bookPrepare,
      label: (state) => `${state.slug}:prepare`,
      context: (state) => ({ materialKey: state.materialKey, identity: state.meta, source: state.source, format: state.meta.format, outputDir: state.chaptersDir, manifest: state.manifest, normalized: state.sourceText, recoverySource: state.ocrSource, recoveryText: state.ocrText, artifactRoles: ["normalized_document", "recovery_source", "chapter_manifest", "normalized_chapter"] }),
      routeOptions: () => ({ failure: prepareFailure, blockedExtra: (receipt) => ({ problems: receipt.diagnostics }), needsInputExtra: (receipt) => ({ question: receipt.terminal.issue.user_question }), failedStatus: "extract_failed", failedExtra: (receipt) => ({ problems: receipt.diagnostics }) }),
      apply: addPreparedBook,
    },
    {
      stage: "Analyse", receiptStage: "chapter-analyse", operationKey: "chapter.analyse", row: chapterAnalyse,
      label: () => "unused",
      context: () => ({}),
      routeOptions: () => ({}),
      apply: () => undefined,
      fanOut: {
        lane: "Analyse",
        items: (state) => state.chapters,
        row: chapterAnalyse,
        label: (state, call) => `${state.slug}:ch${(call.item.chapter || call.item).slot}:${call.refill ? "refill" : call.mode === "repair" ? "repair" : "analyse"}`,
        context: (state, _meta, _opts, call) => {
          const chapter = call.item.chapter || call.item;
          const diagnostics = call.item.diagnostics || call.diagnostics;
          return { materialKey: state.materialKey, bookSlug: state.slug, meta: state.meta, chapter, input: chapterInputPath(state, chapter), output: chapterOutputPath(state, chapter), mode: call.mode, diagnostics, replay: call.mode === "repair" ? "reconciled" : "blocked", artifactRoles: ["chapter_canonical"] };
        },
        routeOptions: () => ({ failure: analyseFailure, blockedFailure: (receipt) => analyseFailure(receipt, "unknown"), onFailed: (receipt) => ({ value: { receipt, present: false } }) }),
        apply: (_state, receipt) => ({ receipt, present: true }),
        retry: {
          items: (_state, values, items, call) => call.mode === "repair" ? [] : items.filter((_item, index) => { const receipt = values[index].receipt; return !values[index].present && receipt.terminal.status === "failed" && receipt.terminal.issue.retryable === true && receipt.terminal.write_state === "not_written"; }),
          before: (state) => { state.budgets.refill.used += 1; },
          apply: (state, values, items) => { values.forEach((entry, index) => { if (entry.present) state.refillPresent.add(items[index].slot); }); },
        },
        join: joinChapters,
      },
    },
    {
      stage: "Synthesise", receiptStage: "synthesise", operationKey: "book.synthesise", row: bookSynthesise,
      label: (state, call) => `${state.slug}:${call.mode === "repair" ? "synthesise-repair" : "synthesise"}`,
      context: (state, _meta, _opts, call) => ({ materialKey: state.materialKey, slug: state.slug, meta: state.meta, inputPaths: state.chapterOutputs, output: state.canonical, mode: call.mode, diagnostics: call.diagnostics, replay: call.mode === "repair" ? "reconciled" : "blocked", artifactRoles: ["canonical"] }),
      routeOptions: () => ({ failure: synthesiseFailure, blockedFailure: (receipt) => synthesiseFailure(receipt, "unknown"), failedStatus: "synth_failed", failedExtra: (receipt) => ({ notes: stageIssue(receipt).code }) }),
      apply: applySynthesis,
    },
    {
      stage: "Audit", receiptStage: "audit", operationKey: "book.audit", row: bookAudit,
      label: (state, call) => `${state.slug}:audit${call.pass === 1 ? "" : `-${call.pass}`}`,
      context: (state, _meta, _opts, call) => { state.budgets.auditPasses.used += 1; return { materialKey: state.materialKey, target: `vault/books/${state.slug}`, pass: call.pass, replay: "reconciled", artifactRoles: ["canonical"] }; },
      routeOptions: (state) => ({
        failure: (receipt, outcome = "known") => unknownAuditPath(receipt, state) ? operationFailure("book.repair_owner_unknown", "book.audit") : auditFailure(receipt, outcome),
        blockedFailure: (receipt) => unknownAuditPath(receipt, state) ? operationFailure("book.repair_owner_unknown", "book.audit") : auditFailure(receipt, "unknown"),
        onReceipt: (receipt, edge) => { if (edge !== "unknown" && edge !== "mismatch") state.audit.push(receipt); },
        failedStatus: "audit_escalated",
        failedExtra: (receipt) => ({ escalated: auditEscalations(receipt, state) }),
      }),
      apply: applyBookAudit,
      repair: { once: true, escalationsFrom: bookRepairInput, target: bookRepairTargets, exhausted: exhaustedBookRepair },
    },
  ],
  complete: (state) => bookResult(state, "ok", "audit", { year_warning: state.yearEvidence && state.yearEvidence.verdict !== "MATCH" ? state.yearEvidence : null }),
};

export async function processBook(runtime, slug, meta, opts = {}) {
  return runMaterialLoop(runtime, bookTable, slug, meta, opts);
}
