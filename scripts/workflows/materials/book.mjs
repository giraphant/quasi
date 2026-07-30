import {
  BOOK_ACQUIRE_SCHEMA,
  bookAcquirePrompt,
} from "../operations/acquire.mjs";
import {
  CHAPTER_ANALYSE_SCHEMA,
  chapterAnalyseOperationPrompt,
} from "../operations/analyse.mjs";
import {
  BOOK_AUDIT_SCHEMA,
  bookAuditPrompt,
} from "../operations/audit.mjs";
import {
  CHAPTER_ASSESS_SCHEMA,
  CHAPTER_EXTRACT_SCHEMA,
  CHAPTER_PLAN_SCHEMA,
  BOOK_DOCUMENT_OCR_SCHEMA,
  READABILITY_SCHEMA,
  TEXT_EXTRACT_SCHEMA,
  chapterAssessOperationPrompt,
  chapterExtractOperationPrompt,
  chapterPlanOperationPrompt,
  documentOcrOperationPrompt,
  extractTextOperationPrompt,
  readabilityOperationPrompt,
} from "../operations/extract.mjs";
import {
  BOOK_SYNTHESISE_SCHEMA,
  bookSynthesiseOperationPrompt,
} from "../operations/synthesise.mjs";

const MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1";
const BOOK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CHAPTER_SLOT = /^\d{2,3}[a-z]{0,2}$/;
const BOOK_TEMP_PATH =
  /^\.quasi\/temp\/downloads\/[A-Za-z0-9][A-Za-z0-9._-]{0,220}\.(?:epub|pdf)$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const CATEGORIES = new Set([
  "monograph",
  "edited-volume",
  "handbook",
  "other",
]);

const exactKeys = (value, keys) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

function sameClosedValue(left, right) {
  if (Array.isArray(left) || Array.isArray(right))
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) =>
        sameClosedValue(value, right[index]),
      )
    );
  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(right, key) &&
          sameClosedValue(left[key], right[key]),
      )
    );
  }
  return Object.is(left, right);
}

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const optionalText = (value, max) =>
  value == null || value === "" || validText(value, 1, max);

const operationFailure = (
  code,
  operationKey,
  outcome = "known",
  retryable = false,
  message = null,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable,
  ...(message ? { message } : {}),
});

function validFailure(
  failure,
  operationKey,
  { retryable = null, allowMessage = true } = {},
) {
  if (
    !failure ||
    typeof failure !== "object" ||
    Array.isArray(failure)
  )
    return false;
  const allowed = [
    "code",
    "operation_key",
    "outcome",
    "retryable",
    ...(allowMessage ? ["message"] : []),
  ];
  const keys = Object.keys(failure);
  return (
    ["code", "operation_key", "outcome", "retryable"].every(
      (key) => keys.includes(key),
    ) &&
    keys.every((key) => allowed.includes(key)) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    ["known", "unknown"].includes(failure.outcome) &&
    typeof failure.retryable === "boolean" &&
    (retryable === null || failure.retryable === retryable) &&
    (failure.message === undefined ||
      validText(failure.message, 1, 4000))
  );
}

const exactRoles = (receipt, roles) =>
  Array.isArray(receipt && receipt.artifact_roles) &&
  receipt.artifact_roles.length === roles.length &&
  roles.every((role, index) => receipt.artifact_roles[index] === role);

const runtimeUnknown = (receipt) =>
  !!(
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    receipt.status === "blocked" &&
    receipt.failure &&
    receipt.failure.outcome === "unknown"
  );

function validateBookIdentity(slug, meta) {
  if (typeof slug !== "string" || !BOOK_SLUG.test(slug))
    return {
      ok: false,
      code: "book.slug_invalid",
      message: "book slug is not canonical",
      canonicalSlug: null,
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "book metadata must be an object",
      canonicalSlug: slug,
    };
  if (!validText(meta.title, 1, 500))
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "title is missing or invalid",
      canonicalSlug: slug,
    };
  if (
    !Array.isArray(meta.authors) ||
    meta.authors.length < 1 ||
    meta.authors.length > 32 ||
    meta.authors.some((author) => !validText(author, 1, 200))
  )
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "authors must be a bounded non-empty string array",
      canonicalSlug: slug,
    };
  if (
    !Number.isInteger(meta.year) ||
    meta.year < 1500 ||
    meta.year > 2030
  )
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "year must be an integer in the supported range",
      canonicalSlug: slug,
    };
  if (!validText(meta.publisher, 2, 500))
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "publisher is required for canonical synthesis",
      canonicalSlug: slug,
    };
  const category = meta.category || "other";
  if (!CATEGORIES.has(category))
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "category is invalid",
      canonicalSlug: slug,
    };
  if (
    !optionalText(meta.isbn, 100) ||
    (meta.format != null &&
      !["pdf", "epub"].includes(meta.format)) ||
    (meta.confidence !== undefined &&
      !["provided", "verified"].includes(meta.confidence))
  )
    return {
      ok: false,
      code: "book.identity_invalid",
      message: "optional identity fields are invalid",
      canonicalSlug: slug,
    };
  const normalized = {
    title: meta.title,
    authors: [...meta.authors],
    year: meta.year,
    publisher: meta.publisher,
    isbn: meta.isbn || null,
    category,
    format: meta.format || null,
    confidence:
      meta.confidence === "verified" ? "verified" : "provided",
  };
  return {
    ok: true,
    canonicalSlug: slug,
    meta: normalized,
    fingerprint: JSON.stringify(normalized),
  };
}

function createBookState(slug, meta) {
  const root = `processing/chapters/${slug}`;
  const allowedFormats = meta.format
    ? [meta.format]
    : ["epub", "pdf"];
  return {
    slug,
    meta,
    materialKey: `book:${slug}`,
    source: null,
    allowedSources: allowedFormats.map((format) => ({
      format,
      path: `sources/${slug}.${format}`,
    })),
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
    yearEvidence: null,
    budgets: {
      ocr: { used: 0, limit: 1 },
      planRecovery: { used: 0, limit: 1 },
      refill: { used: 0, limit: 1 },
      auditRepair: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 2 },
    },
  };
}

function materialReceipt(
  state,
  { status, stage, failure = null, disposition = null },
) {
  const inventory = state.chapterInventory;
  return {
    schema_version: MATERIAL_RECEIPT_VERSION,
    material_key: state.materialKey,
    kind: "book",
    id: state.slug,
    status,
    disposition:
      disposition ||
      (status === "complete"
        ? state.repaired
          ? "repaired"
          : state.disposition || "created"
        : null),
    stage,
    artifacts: state.artifacts,
    operations: state.operations,
    audit: state.audit,
    freshness: {
      observation: "unknown",
      basis: "operation-receipts-and-final-audit",
    },
    warnings: state.warnings,
    failure,
    ...(inventory
      ? {
          expected_slots: [...inventory.expected_slots],
          present_slots: [...inventory.present_slots],
          missing_slots: [...inventory.missing_slots],
        }
      : {}),
    resume:
      status === "blocked"
        ? failure && failure.outcome === "unknown"
          ? { operation_key: "book.reconcile" }
          : {
              operation_key: "book.user-gate",
              stage,
              policy:
                stage === "download"
                  ? "human-year-decision-or-correct-request"
                  : "caller-correct-request",
            }
        : null,
  };
}

function result(
  state,
  publicStatus,
  stage,
  extra = {},
  failure = null,
  terminalOverride = null,
) {
  const terminal =
    terminalOverride ||
    (publicStatus === "ok"
      ? "complete"
      : publicStatus === "blocked" ||
          publicStatus === "year_mismatch" ||
          publicStatus === "year_ambiguous"
        ? "blocked"
        : "failed");
  return {
    slug: state.slug,
    status: publicStatus,
    ...extra,
    material_receipt: materialReceipt(state, {
      status: terminal,
      stage,
      failure,
    }),
  };
}

function rejectedBookResult(slug, validation, code = null) {
  const canonical =
    typeof slug === "string" && BOOK_SLUG.test(slug);
  const failure = operationFailure(
    code || validation.code,
    "book.identity",
    "known",
    false,
    validation.message || "conflicting book identity",
  );
  const state = {
    slug: typeof slug === "string" ? slug : null,
    materialKey: canonical ? `book:${slug}` : null,
    operations: [],
    artifacts: [],
    audit: [],
    warnings: [],
    disposition: null,
    repaired: false,
  };
  return {
    slug: state.slug,
    status: "blocked",
    material_receipt: materialReceipt(state, {
      status: "blocked",
      stage: "identity",
      failure,
    }),
  };
}

function blocked(state, stage, operationKey, receipt = null) {
  const failure =
    (receipt && receipt.failure) ||
    operationFailure(
      "material.writer_outcome_unknown",
      operationKey,
      "unknown",
    );
  return result(state, "blocked", stage, {}, failure);
}

function mismatchBlocked(state, stage, operationKey) {
  return result(
    state,
    "blocked",
    stage,
    {},
    operationFailure(
      "book.writer_receipt_mismatch",
      operationKey,
      "unknown",
      false,
      "writer receipt did not prove the exact contract",
    ),
  );
}

function strictAttempt(attempt) {
  return (
    exactKeys(attempt, ["source", "status", "error"]) &&
    validText(attempt.source, 1, 200) &&
    validText(attempt.status, 1, 200) &&
    (attempt.error === null ||
      validText(attempt.error, 1, 4000))
  );
}

const nullableYear = (value) =>
  value === null ||
  (Number.isInteger(value) && value >= 1000 && value <= 2500);

function strictYearEvidence(evidence, expectedYear) {
  if (
    !exactKeys(evidence, [
      "slug_year",
      "source_years",
      "pdf_signals",
      "recommended_year",
      "recommendation_reason",
      "verdict",
    ]) ||
    evidence.slug_year !== expectedYear ||
    !evidence.source_years ||
    typeof evidence.source_years !== "object" ||
    Array.isArray(evidence.source_years) ||
    Object.keys(evidence.source_years).length > 64 ||
    Object.entries(evidence.source_years).some(
      ([source, year]) =>
        !validText(source, 1, 200) || !nullableYear(year) || year === null,
    ) ||
    !exactKeys(evidence.pdf_signals, [
      "first_published",
      "copyright_year",
      "original_year",
      "other_years",
    ]) ||
    !nullableYear(evidence.pdf_signals.first_published) ||
    !nullableYear(evidence.pdf_signals.copyright_year) ||
    !nullableYear(evidence.pdf_signals.original_year) ||
    !Array.isArray(evidence.pdf_signals.other_years) ||
    evidence.pdf_signals.other_years.length > 64 ||
    evidence.pdf_signals.other_years.some(
      (year) => !nullableYear(year) || year === null,
    ) ||
    !nullableYear(evidence.recommended_year) ||
    !validText(evidence.recommendation_reason, 1, 4000) ||
    !["MATCH", "MISMATCH", "AMBIGUOUS"].includes(evidence.verdict)
  )
    return false;
  if (evidence.verdict === "MATCH") {
    const support = [
      ...Object.values(evidence.source_years),
      evidence.pdf_signals.first_published,
      evidence.pdf_signals.copyright_year,
      ...evidence.pdf_signals.other_years,
    ].filter((year) => year === evidence.recommended_year).length;
    return (
      evidence.recommended_year === expectedYear &&
      support >= 2
    );
  }
  if (evidence.verdict === "MISMATCH")
    return (
      evidence.recommended_year !== null &&
      evidence.recommended_year !== expectedYear
    );
  return evidence.recommended_year === null;
}

function validateYearDecision(decision, slug, meta) {
  if (decision == null) return { ok: true, value: null };
  if (
    !exactKeys(decision, [
      "action",
      "tmp_path",
      "year_evidence",
    ]) ||
    !["accept-current", "use-recommended-year"].includes(
      decision.action,
    ) ||
    typeof decision.tmp_path !== "string" ||
    !BOOK_TEMP_PATH.test(decision.tmp_path) ||
    !strictYearEvidence(
      decision.year_evidence,
      decision.year_evidence &&
        decision.year_evidence.slug_year,
    ) ||
    !["MISMATCH", "AMBIGUOUS"].includes(
      decision.year_evidence.verdict,
    ) ||
    (meta.format != null &&
      !decision.tmp_path.endsWith(`.${meta.format}`))
  )
    return {
      ok: false,
      code: "book.year_decision_invalid",
      message:
        "year_decision must exactly identify a prior year gate and temp artifact",
    };
  if (
    decision.action === "accept-current" &&
    meta.year !== decision.year_evidence.slug_year
  )
    return {
      ok: false,
      code: "book.year_decision_invalid",
      message:
        "accept-current requires the unchanged prior canonical year",
    };
  if (
    decision.action === "use-recommended-year" &&
    (decision.year_evidence.verdict !== "MISMATCH" ||
      decision.year_evidence.recommended_year === null ||
      meta.year !== decision.year_evidence.recommended_year ||
      meta.year === decision.year_evidence.slug_year ||
      !slug.endsWith(`-${meta.year}`))
  )
    return {
      ok: false,
      code: "book.year_decision_invalid",
      message:
        "use-recommended-year requires an updated canonical slug and metadata year",
    };
  return { ok: true, value: decision };
}

function strictBookDownloadReceipt(
  receipt,
  slug,
  allowedSources,
  expectedYear,
  batchAcceptYear,
  yearDecision,
) {
  if (
    !exactKeys(receipt, ["acquired", "failed", "per_item"]) ||
    !Number.isInteger(receipt.acquired) ||
    receipt.acquired < 0 ||
    !Number.isInteger(receipt.failed) ||
    receipt.failed < 0 ||
    !Array.isArray(receipt.per_item) ||
    receipt.per_item.length !== 1
  )
    return false;
  const item = receipt.per_item[0];
  const required = [
    "kind",
    "slug",
    "status",
    "disposition",
    "identity_verified",
    "format",
    "attempts",
  ];
  const allowed = [
    ...required,
    "path",
    "tmp_path",
    "source",
    "isbn",
    "verdict_note",
    "failure_reason",
    "year_evidence",
  ];
  if (
    !item ||
    typeof item !== "object" ||
    Array.isArray(item) ||
    !required.every((key) =>
      Object.prototype.hasOwnProperty.call(item, key),
    ) ||
    Object.keys(item).some((key) => !allowed.includes(key)) ||
    item.kind !== "book" ||
    item.slug !== slug ||
    ![
      "ok",
      "year_mismatch",
      "year_ambiguous",
      "download_failed",
      "blocked",
    ].includes(item.status) ||
    ![null, "created", "reused"].includes(item.disposition) ||
    typeof item.identity_verified !== "boolean" ||
    !["epub", "pdf", null].includes(item.format) ||
    !Array.isArray(item.attempts) ||
    item.attempts.some((attempt) => !strictAttempt(attempt)) ||
    (item.isbn !== undefined &&
      item.isbn !== null &&
      !validText(item.isbn, 1, 100)) ||
    (item.verdict_note !== undefined &&
      !validText(item.verdict_note, 1, 4000))
  )
    return false;
  if (item.status === "ok")
    return (
      receipt.acquired === 1 &&
      receipt.failed === 0 &&
      ["created", "reused"].includes(item.disposition) &&
      (!yearDecision ||
        (item.disposition === "created" &&
          item.attempts.length > 0)) &&
      item.identity_verified === true &&
      allowedSources.some(
        ({ format, path }) =>
          item.format === format && item.path === path,
      ) &&
      validText(item.source, 1, 200) &&
      item.tmp_path === undefined &&
      item.failure_reason === undefined &&
      (yearDecision
        ? strictYearEvidence(
            item.year_evidence,
            yearDecision.year_evidence.slug_year,
          ) &&
          sameClosedValue(
            item.year_evidence,
            yearDecision.year_evidence,
          )
        : strictYearEvidence(
            item.year_evidence,
            expectedYear,
          ) &&
          (item.year_evidence.verdict === "MATCH" ||
            batchAcceptYear === true))
    );
  if (item.status === "year_mismatch" || item.status === "year_ambiguous")
    return (
      receipt.acquired === 0 &&
      receipt.failed === 1 &&
      item.disposition === null &&
      item.identity_verified === true &&
      item.format === null &&
      item.path === undefined &&
      item.source === undefined &&
      item.failure_reason === undefined &&
      typeof item.tmp_path === "string" &&
      BOOK_TEMP_PATH.test(item.tmp_path) &&
      allowedSources.some(({ format }) =>
        item.tmp_path.endsWith(`.${format}`),
      ) &&
      strictYearEvidence(item.year_evidence, expectedYear) &&
      item.year_evidence.verdict ===
        (item.status === "year_mismatch"
          ? "MISMATCH"
          : "AMBIGUOUS")
    );
  if (
    item.disposition !== null ||
    item.identity_verified !== false ||
    item.format !== null ||
    item.path !== undefined ||
    item.tmp_path !== undefined ||
    item.source !== undefined ||
    item.isbn !== undefined ||
    item.verdict_note !== undefined ||
    item.year_evidence !== undefined ||
    !validText(item.failure_reason, 1, 4000)
  )
    return false;
  if (item.status === "download_failed")
    return (
      receipt.acquired === 0 &&
      receipt.failed === 1 &&
      item.attempts.length > 0
    );
  return receipt.acquired === 0 && receipt.failed === 0;
}

function downloadOperation(item, allowedSources) {
  const succeeded = item.status === "ok";
  const unknown = item.status === "blocked";
  return {
    schema_version:
      "quasi.operation.book.acquire.receipt/0.1",
    key: "book.acquire",
    effect: "writer",
    status: succeeded
      ? "succeeded"
      : unknown
        ? "blocked"
        : "failed",
    attempt: 1,
    output_path: item.path || null,
    allowed_output_paths: allowedSources.map(({ path }) => path),
    format: item.format,
    artifact_roles: ["source"],
    disposition: item.disposition,
    identity_verified: item.identity_verified,
    source: item.source || null,
    isbn: item.isbn || null,
    year_evidence: item.year_evidence || null,
    failure_reason:
      item.failure_reason || item.verdict_note || null,
    attempts: item.attempts,
    failure: succeeded
      ? null
      : operationFailure(
          `book.${item.status}`,
          "book.acquire",
          unknown ? "unknown" : "known",
        ),
  };
}

function strictExtractText(receipt, input, output) {
  const keys = [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_path",
    "output_path",
    "artifact_roles",
    "exit",
    "exists",
    "size",
    "chars",
    "non_whitespace_chars",
    "pages",
    "text_pages",
    "failure",
  ];
  if (
    !exactKeys(receipt, keys) ||
    receipt.schema_version !==
      "quasi.operation.document.extract-text.receipt/0.1" ||
    receipt.key !== "document.extract-text" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    receipt.output_path !== output ||
    !exactRoles(receipt, ["normalized_text"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !["exit", "size", "chars", "non_whitespace_chars", "pages", "text_pages"].every(
      (key) =>
        Number.isInteger(receipt[key]) &&
        (key === "exit" || receipt[key] >= 0),
    ) ||
    typeof receipt.exists !== "boolean"
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      receipt.exit === 0 &&
      receipt.exists === true
    );
  return (
    validFailure(receipt.failure, "document.extract-text", {
      retryable: false,
    }) &&
    receipt.failure.outcome ===
      (receipt.status === "failed" ? "known" : "unknown")
  );
}

function strictReadability(receipt, input) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_path",
      "artifact_roles",
      "signal",
      "diagnostics",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.document.assess-readability.receipt/0.1" ||
    receipt.key !== "document.assess-readability" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    !exactRoles(receipt, ["normalized_text"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !Array.isArray(receipt.diagnostics) ||
    receipt.diagnostics.some(
      (diagnostic) => !validText(diagnostic, 1, 4000),
    )
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      ["readable", "needs_ocr", "invalid_source"].includes(
        receipt.signal,
      )
    );
  return (
    receipt.signal === null &&
    validFailure(
      receipt.failure,
      "document.assess-readability",
      { retryable: true },
    ) &&
    receipt.failure.outcome ===
      (receipt.status === "failed" ? "known" : "unknown")
  );
}

function strictOcr(receipt, input, output) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_path",
      "output_path",
      "artifact_roles",
      "exit",
      "exists",
      "size",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.document.ocr.receipt/0.1" ||
    receipt.key !== "document.ocr" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    receipt.output_path !== output ||
    !exactRoles(receipt, ["recovery_source"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !Number.isInteger(receipt.exit) ||
    typeof receipt.exists !== "boolean" ||
    !Number.isInteger(receipt.size) ||
    receipt.size < 0
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      receipt.exit === 0 &&
      receipt.exists === true &&
      receipt.size > 0
    );
  if (
    !validFailure(receipt.failure, "document.ocr", {
      retryable: false,
    })
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.failure.outcome === "known" &&
      receipt.failure.code === "book.ocr_failed"
    );
  if (receipt.failure.outcome !== "unknown") return false;
  if (receipt.failure.code === "book.writer_receipt_mismatch")
    return true;
  return (
    receipt.failure.code === "output_exists_requires_reconcile" &&
    receipt.exit === 0 &&
    receipt.exists === true &&
    receipt.size > 0
  );
}

function strictPlan(receipt, input, normalized) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_path",
      "normalized_path",
      "artifact_roles",
      "mode",
      "chapters",
      "diagnostics",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.chapter.plan.receipt/0.1" ||
    receipt.key !== "chapter.plan" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    receipt.normalized_path !== normalized ||
    !exactRoles(receipt, ["chapter_plan"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !Array.isArray(receipt.chapters) ||
    receipt.chapters.length > 150 ||
    !Array.isArray(receipt.diagnostics) ||
    receipt.diagnostics.some(
      (diagnostic) => !validText(diagnostic, 1, 4000),
    )
  )
    return false;
  if (receipt.status === "succeeded") {
    if (
      receipt.failure !== null ||
      !["toc", "pattern", "manual"].includes(receipt.mode)
    )
      return false;
    if (receipt.mode !== "manual") return receipt.chapters.length === 0;
    if (!receipt.chapters.length) return false;
    let lastEnd = 0;
    return receipt.chapters.every((chapter) => {
      if (
        !exactKeys(chapter, ["title", "start", "end"]) ||
        !validText(chapter.title, 1, 500) ||
        !Number.isInteger(chapter.start) ||
        !Number.isInteger(chapter.end) ||
        chapter.start < 1 ||
        chapter.end < chapter.start ||
        chapter.start <= lastEnd
      )
        return false;
      lastEnd = chapter.end;
      return true;
    });
  }
  return (
    receipt.mode === null &&
    receipt.chapters.length === 0 &&
    validFailure(receipt.failure, "chapter.plan", {
      retryable: true,
    }) &&
    receipt.failure.outcome ===
      (receipt.status === "failed" ? "known" : "unknown")
  );
}

function validChapterRef(chapter) {
  const filenameIsSafe =
    validText(chapter?.filename, 1, 128) &&
    chapter.filename.startsWith(`${chapter.slot}_`) &&
    chapter.filename.endsWith(".txt") &&
    !chapter.filename.includes("/") &&
    !chapter.filename.includes("\\") &&
    !chapter.filename.includes("..");
  if (
    !exactKeys(chapter, [
      "slot",
      "title",
      "filename",
      "slug",
      "word_count",
      "start_page",
      "end_page",
    ]) ||
    !CHAPTER_SLOT.test(chapter.slot) ||
    !BOOK_SLUG.test(chapter.slug) ||
    !filenameIsSafe ||
    !validText(chapter.title, 1, 500) ||
    !Number.isInteger(chapter.word_count) ||
    chapter.word_count < 0
  )
    return false;
  const noPages =
    chapter.start_page === null && chapter.end_page === null;
  const startOnly =
    Number.isInteger(chapter.start_page) &&
    chapter.start_page >= 1 &&
    chapter.end_page === null;
  const pages =
    Number.isInteger(chapter.start_page) &&
    Number.isInteger(chapter.end_page) &&
    chapter.start_page >= 1 &&
    chapter.end_page >= chapter.start_page;
  return noPages || startOnly || pages;
}

function uniqueChapters(chapters) {
  if (
    !Array.isArray(chapters) ||
    !chapters.length ||
    chapters.length > 150 ||
    chapters.some((chapter) => !validChapterRef(chapter))
  )
    return false;
  const slots = new Set();
  const filenames = new Set();
  const slugs = new Set();
  return chapters.every((chapter) => {
    if (
      slots.has(chapter.slot) ||
      filenames.has(chapter.filename) ||
      slugs.has(chapter.slug)
    )
      return false;
    slots.add(chapter.slot);
    filenames.add(chapter.filename);
    slugs.add(chapter.slug);
    return true;
  });
}

function strictChapterExtract(
  receipt,
  state,
  input,
  expectedMode,
) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_path",
      "output_path",
      "manifest_path",
      "artifact_roles",
      "mode",
      "disposition",
      "exit",
      "manifest_exists",
      "request_fingerprint",
      "manifest_fingerprint",
      "chapter_count",
      "chapters",
      "skipped",
      "removed_files",
      "limit",
      "previous_manifest_preserved",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.chapter.extract.receipt/0.1" ||
    receipt.key !== "chapter.extract" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    receipt.output_path !== state.chaptersDir ||
    receipt.manifest_path !== state.manifest ||
    !exactRoles(receipt, [
      "chapter_manifest",
      "normalized_chapter",
    ]) ||
    receipt.mode !== expectedMode ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !["created", "reused", "replaced", "repaired", null].includes(
      receipt.disposition,
    ) ||
    !Number.isInteger(receipt.exit) ||
    typeof receipt.manifest_exists !== "boolean" ||
    (receipt.request_fingerprint !== null &&
      !validText(receipt.request_fingerprint, 1, 512)) ||
    (receipt.manifest_fingerprint !== null &&
      !validText(receipt.manifest_fingerprint, 1, 512)) ||
    !Number.isInteger(receipt.chapter_count) ||
    receipt.chapter_count < 0 ||
    !Array.isArray(receipt.chapters) ||
    !Array.isArray(receipt.skipped) ||
    !Array.isArray(receipt.removed_files) ||
    receipt.removed_files.some(
      (path) => !validText(path, 1, 2048),
    ) ||
    !exactKeys(receipt.limit, ["max_chapters", "exceeded"]) ||
    !Number.isInteger(receipt.limit.max_chapters) ||
    receipt.limit.max_chapters < 1 ||
    typeof receipt.limit.exceeded !== "boolean" ||
    typeof receipt.previous_manifest_preserved !== "boolean"
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      receipt.exit === 0 &&
      receipt.manifest_exists === true &&
      receipt.chapter_count === receipt.chapters.length &&
      (receipt.chapter_count === 0 ||
        uniqueChapters(receipt.chapters)) &&
      receipt.request_fingerprint !== null &&
      receipt.manifest_fingerprint !== null &&
      receipt.disposition !== null
    );
  return (
    receipt.chapter_count === receipt.chapters.length &&
    validFailure(receipt.failure, "chapter.extract", {
      retryable: false,
    }) &&
    receipt.failure.outcome ===
      (receipt.status === "failed" ? "known" : "unknown")
  );
}

const chapterInputPath = (state, chapter) =>
  `${state.chaptersDir}/${chapter.filename}`;
const chapterOutputPath = (state, chapter) =>
  `vault/books/${state.slug}/ch${chapter.slot}-${chapter.slug}.md`;

function strictBoundaryAssessment(
  receipt,
  state,
  chapters,
) {
  const inputPaths = chapters.map((chapter) =>
    chapterInputPath(state, chapter),
  );
  const allowedPaths = new Set([state.manifest, ...inputPaths]);
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "manifest_path",
      "input_paths",
      "artifact_roles",
      "signal",
      "diagnostics",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.chapter.assess-boundaries.receipt/0.1" ||
    receipt.key !== "chapter.assess-boundaries" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.manifest_path !== state.manifest ||
    JSON.stringify(receipt.input_paths) !== JSON.stringify(inputPaths) ||
    !exactRoles(receipt, [
      "chapter_manifest",
      "normalized_chapter",
    ]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !Array.isArray(receipt.diagnostics)
  )
    return false;
  const validDiagnostic = (diagnostic) => {
    if (
      !exactKeys(diagnostic, [
        "path",
        "kind",
        "reason",
        "slot",
        "title",
        "start_page",
        "end_page",
      ]) ||
      !allowedPaths.has(diagnostic.path) ||
      !validText(diagnostic.kind, 1, 200) ||
      !validText(diagnostic.reason, 1, 4000) ||
      (diagnostic.slot !== null &&
        !CHAPTER_SLOT.test(diagnostic.slot)) ||
      (diagnostic.title !== null &&
        !validText(diagnostic.title, 1, 500))
    )
      return false;
    const noPages =
      diagnostic.start_page === null &&
      diagnostic.end_page === null;
    const pages =
      Number.isInteger(diagnostic.start_page) &&
      Number.isInteger(diagnostic.end_page) &&
      diagnostic.start_page >= 1 &&
      diagnostic.end_page >= diagnostic.start_page;
    return noPages || pages;
  };
  if (receipt.diagnostics.some((item) => !validDiagnostic(item)))
    return false;
  if (receipt.status === "succeeded") {
    if (
      receipt.failure !== null ||
      ![
        "ready",
        "needs_replan",
        "needs_repair",
        "needs_ocr",
        "invalid_source",
      ].includes(receipt.signal)
    )
      return false;
    if (receipt.signal === "ready")
      return receipt.diagnostics.length === 0;
    if (!receipt.diagnostics.length) return false;
    if (receipt.signal !== "needs_repair") return true;
    const targets = new Set();
    return receipt.diagnostics.every((diagnostic) => {
      const chapter = chapters.find(
        (candidate) =>
          diagnostic.path === chapterInputPath(state, candidate),
      );
      const valid =
        chapter &&
        diagnostic.slot === chapter.slot &&
        validText(diagnostic.title, 1, 500) &&
        Number.isInteger(diagnostic.start_page) &&
        Number.isInteger(diagnostic.end_page) &&
        !targets.has(diagnostic.path);
      targets.add(diagnostic.path);
      return valid;
    });
  }
  return (
    receipt.signal === null &&
    validFailure(
      receipt.failure,
      "chapter.assess-boundaries",
      { retryable: true },
    ) &&
    receipt.failure.outcome ===
      (receipt.status === "failed" ? "known" : "unknown")
  );
}

function strictChapterAnalyse(
  receipt,
  state,
  chapter,
  mode,
) {
  const input = chapterInputPath(state, chapter);
  const output = chapterOutputPath(state, chapter);
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_path",
      "output_path",
      "artifact_roles",
      "action",
      "write_state",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.chapter.analyse.receipt/0.1" ||
    receipt.key !== "chapter.analyse" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.input_path !== input ||
    receipt.output_path !== output ||
    !exactRoles(receipt, ["chapter_canonical"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !["create", "repair", "reconciled"].includes(receipt.action) ||
    !["written", "not_written", "unknown"].includes(
      receipt.write_state,
    )
  )
    return false;
  if (receipt.status === "succeeded") {
    if (receipt.failure !== null) return false;
    if (receipt.action === "reconciled")
      return mode === "repair" && receipt.write_state === "not_written";
    return (
      receipt.action === mode && receipt.write_state === "written"
    );
  }
  if (!validFailure(receipt.failure, "chapter.analyse"))
    return false;
  if (receipt.status === "failed")
    return (
      receipt.failure.outcome === "known" &&
      receipt.action === mode &&
      receipt.write_state === "not_written"
    );
  if (
    mode === "create" &&
    receipt.action === "reconciled" &&
    receipt.failure.code ===
      "output_exists_requires_reconcile"
  )
    return (
      receipt.failure.outcome === "unknown" &&
      receipt.write_state === "not_written"
    );
  return (
    receipt.failure.outcome === "unknown" &&
    receipt.write_state === "unknown" &&
    receipt.action === mode &&
    receipt.failure.code !==
      "output_exists_requires_reconcile"
  );
}

function chapterPresent(receipt, mode) {
  return (
    receipt.status === "succeeded" ||
    (mode === "create" &&
      receipt.status === "blocked" &&
      receipt.action === "reconciled" &&
      receipt.failure.code ===
        "output_exists_requires_reconcile")
  );
}

function strictSynthesis(receipt, state, inputPaths, mode) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_paths",
      "output_path",
      "artifact_roles",
      "action",
      "chapters_analyzed",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.book.synthesise.receipt/0.1" ||
    receipt.key !== "book.synthesise" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    JSON.stringify(receipt.input_paths) !== JSON.stringify(inputPaths) ||
    receipt.output_path !== state.canonical ||
    !exactRoles(receipt, ["canonical"]) ||
    !["succeeded", "failed", "blocked"].includes(receipt.status) ||
    !["create", "repair", "reconciled"].includes(receipt.action) ||
    !Number.isInteger(receipt.chapters_analyzed) ||
    receipt.chapters_analyzed < 0
  )
    return false;
  if (receipt.status === "succeeded") {
    if (
      receipt.failure !== null ||
      receipt.chapters_analyzed !== inputPaths.length
    )
      return false;
    return mode === "create"
      ? receipt.action === "create"
      : ["repair", "reconciled"].includes(receipt.action);
  }
  if (
    !validFailure(receipt.failure, "book.synthesise", {
      retryable: false,
    })
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.failure.outcome === "known" &&
      receipt.action === mode
    );
  if (receipt.failure.outcome !== "unknown") return false;
  if (
    mode === "create" &&
    receipt.action === "reconciled"
  )
    return (
      receipt.failure.code ===
      "output_exists_requires_reconcile"
    );
  return (
    receipt.action === mode &&
    receipt.failure.code !==
      "output_exists_requires_reconcile"
  );
}

function strictAudit(receipt, state) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "target_path",
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.book.audit.receipt/0.1" ||
    receipt.key !== "book.audit" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.target_path !== `vault/books/${state.slug}` ||
    !["clean", "partial", "error"].includes(receipt.status) ||
    !Number.isInteger(receipt.remaining_violations) ||
    receipt.remaining_violations < 0 ||
    !Array.isArray(receipt.escalated) ||
    !Array.isArray(receipt.mutated_paths) ||
    new Set(receipt.mutated_paths).size !==
      receipt.mutated_paths.length ||
    receipt.mutated_paths.some(
      (path) => !validText(path, 1, 2048),
    ) ||
    receipt.escalated.some(
      (diagnostic) =>
        !exactKeys(diagnostic, ["path", "kind", "reason"]) ||
        !validText(diagnostic.path, 1, 2048) ||
        !validText(diagnostic.kind, 1, 200) ||
        !validText(diagnostic.reason, 1, 4000),
    )
  )
    return false;
  if (receipt.status === "clean")
    return (
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0
    );
  if (receipt.status === "partial")
    return (
      receipt.remaining_violations > 0 &&
      receipt.escalated.length === receipt.remaining_violations
    );
  return true;
}

async function extractAndAssess(runtime, state, input, output) {
  const extraction = await runtime.runOperation(
    extractTextOperationPrompt(state.materialKey, input, output),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:extract-text`,
      schema: TEXT_EXTRACT_SCHEMA,
    },
    {
      key: "document.extract-text",
      effect: "writer",
      retry: "forbidden",
      replay: "idempotent",
      artifactRoles: ["normalized_text"],
      unknownFailureCode: "document.writer_outcome_unknown",
    },
  );
  state.operations.push(extraction);
  if (runtimeUnknown(extraction))
    return {
      terminal: blocked(
        state,
        "extract-text",
        "document.extract-text",
        extraction,
      ),
    };
  if (!strictExtractText(extraction, input, output))
    return {
      terminal: mismatchBlocked(
        state,
        "extract-text",
        "document.extract-text",
      ),
    };
  if (extraction.status === "blocked")
    return {
      terminal: blocked(
        state,
        "extract-text",
        "document.extract-text",
        extraction,
      ),
    };
  if (extraction.status !== "succeeded")
    return { failure: extraction.failure };
  state.artifacts.push({
    role: "normalized_document",
    path: output,
    exists: true,
    usable: null,
    producer: "document.extract-text",
  });

  const assessment = await runtime.runOperation(
    readabilityOperationPrompt(
      state.materialKey,
      output,
      extraction,
    ),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:assess-readability`,
      schema: READABILITY_SCHEMA,
    },
    {
      key: "document.assess-readability",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: ["normalized_text"],
      unknownFailureCode: "document.readonly_outcome_unknown",
    },
  );
  state.operations.push(assessment);
  if (!strictReadability(assessment, output))
    return {
      failure:
        (assessment &&
          assessment.failure &&
          assessment.failure.outcome === "unknown" &&
          assessment.failure) ||
        operationFailure(
          "document.assess_readability_failed",
          "document.assess-readability",
        ),
    };
  if (assessment.status !== "succeeded")
    return { failure: assessment.failure };
  state.artifacts[state.artifacts.length - 1].usable =
    assessment.signal === "readable";
  return { signal: assessment.signal, input: output };
}

async function runOcr(runtime, state) {
  state.budgets.ocr.used += 1;
  const receipt = await runtime.runOperation(
    documentOcrOperationPrompt(
      state.materialKey,
      state.source,
      state.ocrSource,
      "book",
    ),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:ocr`,
      schema: BOOK_DOCUMENT_OCR_SCHEMA,
    },
    {
      key: "document.ocr",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["recovery_source"],
      unknownFailureCode: "document.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt))
    return {
      terminal: blocked(
        state,
        "ocr",
        "document.ocr",
        receipt,
      ),
    };
  if (!strictOcr(receipt, state.source, state.ocrSource))
    return {
      terminal: mismatchBlocked(
        state,
        "ocr",
        "document.ocr",
      ),
    };
  const existing =
    receipt.status === "blocked" &&
    receipt.failure.code ===
      "output_exists_requires_reconcile" &&
    receipt.exists === true &&
    receipt.size > 0;
  if (receipt.status === "blocked" && !existing)
    return {
      terminal: blocked(
        state,
        "ocr",
        "document.ocr",
        receipt,
      ),
    };
  if (receipt.status === "failed")
    return { failure: receipt.failure };
  state.artifacts.push({
    role: "recovery_source",
    path: state.ocrSource,
    exists: true,
    usable: null,
    producer: existing
      ? "document.ocr:reconciled"
      : "document.ocr",
  });
  return { input: state.ocrSource };
}

async function runPlan(
  runtime,
  state,
  input,
  normalized,
  diagnostics = [],
) {
  const receipt = await runtime.runOperation(
    chapterPlanOperationPrompt(
      state.materialKey,
      input,
      normalized,
      diagnostics,
    ),
    {
      phase: "Prepare",
      agentType: "quasi:extract-agent",
      label: `${state.slug}:plan-chapters`,
      schema: CHAPTER_PLAN_SCHEMA,
    },
    {
      key: "chapter.plan",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: ["chapter_plan"],
      unknownFailureCode: "document.readonly_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (!strictPlan(receipt, input, normalized))
    return {
      failure: operationFailure(
        "chapter.plan_receipt_invalid",
        "chapter.plan",
      ),
    };
  if (receipt.status !== "succeeded")
    return { failure: receipt.failure };
  return { receipt };
}

async function runChapterExtract(
  runtime,
  state,
  {
    input,
    mode,
    plan = [],
    expectedManifestFingerprint = null,
    repair = null,
    label = "extract",
  },
) {
  const receipt = await runtime.runOperation(
    chapterExtractOperationPrompt({
      materialKey: state.materialKey,
      input,
      outputDir: state.chaptersDir,
      mode,
      plan,
      expectedManifestFingerprint,
      repair,
    }),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:${label}`,
      schema: CHAPTER_EXTRACT_SCHEMA,
    },
    {
      key: "chapter.extract",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "chapter_manifest",
        "normalized_chapter",
      ],
      unknownFailureCode: "document.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt))
    return {
      terminal: blocked(
        state,
        "chapter-extract",
        "chapter.extract",
        receipt,
      ),
    };
  if (!strictChapterExtract(receipt, state, input, mode))
    return {
      terminal: mismatchBlocked(
        state,
        "chapter-extract",
        "chapter.extract",
      ),
    };
  if (receipt.status === "blocked")
    return {
      terminal: blocked(
        state,
        "chapter-extract",
        "chapter.extract",
        receipt,
      ),
    };
  if (receipt.status !== "succeeded")
    return { failure: receipt.failure };
  state.artifacts = state.artifacts.filter(
    (artifact) =>
      !["chapter_manifest", "normalized_chapter"].includes(
        artifact.role,
      ),
  );
  state.artifacts.push({
    role: "chapter_manifest",
    path: state.manifest,
    exists: true,
    usable: null,
    producer: `chapter.extract:${receipt.disposition}`,
  });
  for (const chapter of receipt.chapters)
    state.artifacts.push({
      role: "normalized_chapter",
      path: chapterInputPath(state, chapter),
      exists: true,
      usable: null,
      producer: "chapter.extract",
    });
  return { receipt };
}

async function assessBoundaries(runtime, state, extraction) {
  const receipt = await runtime.runOperation(
    chapterAssessOperationPrompt(
      state.materialKey,
      state.manifest,
      extraction.chapters,
      {
        chapter_count: extraction.chapter_count,
        skipped: extraction.skipped,
        removed_files: extraction.removed_files,
        limit: extraction.limit,
        disposition: extraction.disposition,
      },
    ),
    {
      phase: "Prepare",
      agentType: "quasi:extract-agent",
      label: `${state.slug}:assess-chapters`,
      schema: CHAPTER_ASSESS_SCHEMA,
    },
    {
      key: "chapter.assess-boundaries",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: [
        "chapter_manifest",
        "normalized_chapter",
      ],
      unknownFailureCode: "document.readonly_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (!strictBoundaryAssessment(receipt, state, extraction.chapters))
    return {
      failure: operationFailure(
        "chapter.assessment_receipt_invalid",
        "chapter.assess-boundaries",
      ),
    };
  if (receipt.status !== "succeeded")
    return { failure: receipt.failure };
  return { receipt };
}

async function analyseChapter(
  runtime,
  state,
  chapter,
  mode = "create",
  diagnostics = [],
  label = null,
) {
  const receipt = await runtime.runOperation(
    chapterAnalyseOperationPrompt(
      state.slug,
      state.meta,
      chapter,
      chapterInputPath(state, chapter),
      chapterOutputPath(state, chapter),
      mode,
      diagnostics,
    ),
    {
      phase: "Analyse",
      agentType: "quasi:analyse-agent",
      label: `${state.slug}:${
        label ||
        `ch${chapter.slot}:${mode === "repair" ? "repair" : "analyse"}`
      }`,
      schema: CHAPTER_ANALYSE_SCHEMA,
    },
    {
      key: "chapter.analyse",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["chapter_canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt))
    return {
      terminal: blocked(
        state,
        "chapter-analyse",
        "chapter.analyse",
        receipt,
      ),
    };
  if (!strictChapterAnalyse(receipt, state, chapter, mode))
    return {
      terminal: mismatchBlocked(
        state,
        "chapter-analyse",
        "chapter.analyse",
      ),
    };
  if (
    receipt.status === "blocked" &&
    !chapterPresent(receipt, mode)
  )
    return {
      terminal: blocked(
        state,
        "chapter-analyse",
        "chapter.analyse",
        receipt,
      ),
    };
  return { receipt };
}

async function synthesise(
  runtime,
  state,
  inputPaths,
  mode = "create",
  diagnostics = [],
) {
  const receipt = await runtime.runOperation(
    bookSynthesiseOperationPrompt(
      state.slug,
      state.meta,
      inputPaths,
      mode,
      diagnostics,
    ),
    {
      phase: "Synthesise",
      agentType: "quasi:synthesis-agent",
      label: `${state.slug}:${
        mode === "repair" ? "synthesise-repair" : "synthesise"
      }`,
      schema: BOOK_SYNTHESISE_SCHEMA,
    },
    {
      key: "book.synthesise",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt))
    return {
      terminal: blocked(
        state,
        "synthesise",
        "book.synthesise",
        receipt,
      ),
    };
  if (!strictSynthesis(receipt, state, inputPaths, mode))
    return {
      terminal: mismatchBlocked(
        state,
        "synthesise",
        "book.synthesise",
      ),
    };
  const createCollision =
    mode === "create" &&
    receipt.status === "blocked" &&
    receipt.action === "reconciled";
  if (receipt.status === "blocked" && !createCollision)
    return {
      terminal: blocked(
        state,
        "synthesise",
        "book.synthesise",
        receipt,
      ),
    };
  if (receipt.status === "failed")
    return {
      terminal: result(
        state,
        "synth_failed",
        "synthesise",
        { notes: receipt.failure.code },
        receipt.failure,
      ),
    };
  state.artifacts = state.artifacts.filter(
    (artifact) => artifact.role !== "canonical",
  );
  state.artifacts.push({
    role: "canonical",
    path: state.canonical,
    exists: true,
    usable: null,
    producer: createCollision
      ? "book.synthesise:reconciled"
      : "book.synthesise",
  });
  if (mode === "repair" && receipt.action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (
    mode === "repair" &&
    receipt.action === "reconciled"
  ) {
    state.disposition = state.disposition || "reused";
  } else if (createCollision) {
    state.disposition = "reused";
  } else {
    state.disposition = "created";
  }
  return { receipt, reconciled: createCollision };
}

async function audit(runtime, state, pass, owners) {
  state.budgets.auditPasses.used += 1;
  const receipt = await runtime.runOperation(
    bookAuditPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit${pass === 1 ? "" : `-${pass}`}`,
      schema: BOOK_AUDIT_SCHEMA,
    },
    {
      key: "book.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt))
    return {
      terminal: blocked(
        state,
        "audit",
        "book.audit",
        receipt,
      ),
    };
  if (!strictAudit(receipt, state))
    return {
      terminal: mismatchBlocked(
        state,
        "audit",
        "book.audit",
      ),
    };
  state.audit.push(receipt);
  const unknownPath = [
    ...receipt.escalated.map((diagnostic) => diagnostic.path),
    ...receipt.mutated_paths,
  ].find((path) => !owners.has(path));
  if (unknownPath)
    return {
      terminal: result(
        state,
        "audit_escalated",
        "audit",
        {
          escalated: receipt.escalated.some(
            (diagnostic) => diagnostic.path === unknownPath,
          )
            ? receipt.escalated
            : [
                ...receipt.escalated,
                {
                  path: unknownPath,
                  kind: "mutation_owner_unknown",
                  reason:
                    "audit mutated a path with no exact Book producer owner",
                },
              ],
        },
        operationFailure(
          "book.repair_owner_unknown",
          "book.audit",
        ),
      ),
    };
  if (receipt.status === "error")
    return {
      terminal: result(
        state,
        "audit_escalated",
        "audit",
        { escalated: receipt.escalated },
        operationFailure(
          "book.audit_failed",
          "book.audit",
        ),
      ),
    };
  return {
    receipt,
    clean:
      receipt.status === "clean" &&
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0,
  };
}

function ownerMap(state, chapters) {
  const owners = new Map([
    [
      state.canonical,
      { key: "book.synthesise", chapter: null },
    ],
  ]);
  for (const chapter of chapters)
    owners.set(chapterOutputPath(state, chapter), {
      key: "chapter.analyse",
      chapter,
    });
  return owners;
}

async function processValidatedBook(runtime, slug, meta, opts) {
  const { log, parallel, phase, runOperation } = runtime;
  phase("Acquire");
  const state = createBookState(slug, meta);

  const download = await runOperation(
    bookAcquirePrompt(
      slug,
      meta,
      opts.batchYear,
      opts.yearDecision,
    ),
    {
      phase: "Acquire",
      agentType: "quasi:download-agent",
      label: `${slug}:acquire`,
      schema: BOOK_ACQUIRE_SCHEMA,
    },
    {
      key: "book.acquire",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["source"],
      unknownFailureCode: "material.writer_outcome_unknown",
    },
  );
  if (runtimeUnknown(download)) {
    state.operations.push(download);
    return blocked(
      state,
      "download",
      "book.acquire",
      download,
    );
  }
  if (
    !strictBookDownloadReceipt(
      download,
      slug,
      state.allowedSources,
      meta.year,
      opts.batchYear === true,
      opts.yearDecision,
    )
  ) {
    state.operations.push(download);
    return mismatchBlocked(
      state,
      "download",
      "book.acquire",
    );
  }
  const item = download.per_item[0];
  const downloadReceipt = downloadOperation(
    item,
    state.allowedSources,
  );
  state.operations.push(downloadReceipt);
  state.yearEvidence = item.year_evidence || null;
  if (item.status === "blocked")
    return blocked(
      state,
      "download",
      "book.acquire",
      downloadReceipt,
    );
  if (
    item.status === "year_mismatch" ||
    item.status === "year_ambiguous"
  )
    return result(
      state,
      item.status,
      "download",
      {
        year_evidence: item.year_evidence,
        tmp_path: item.tmp_path,
      },
      downloadReceipt.failure,
    );
  if (item.status === "download_failed")
    return result(
      state,
      "download_failed",
      "download",
      {
        failure_reason: item.failure_reason,
        attempts: item.attempts,
      },
      downloadReceipt.failure,
    );
  state.source = item.path;
  meta = { ...meta, format: item.format };
  state.meta = meta;
  state.artifacts.push({
    role: "source",
    path: state.source,
    exists: true,
    usable: null,
    producer:
      item.disposition === "reused"
        ? "book.acquire:reconciled"
        : "book.acquire",
  });

  let selectedSource = state.source;
  let normalizedPath = null;
  if (meta.format === "pdf") {
    let normalized = await extractAndAssess(
      runtime,
      state,
      state.source,
      state.sourceText,
    );
    if (normalized.terminal) return normalized.terminal;
    if (normalized.failure)
      return result(
        state,
        "extract_failed",
        "extract-text",
        { problems: [normalized.failure.code] },
        normalized.failure,
      );
    if (normalized.signal === "invalid_source")
      return result(
        state,
        "extract_failed",
        "assess-readability",
        { problems: ["book.invalid_source"] },
        operationFailure(
          "book.invalid_source",
          "document.assess-readability",
        ),
      );
    if (normalized.signal === "needs_ocr") {
      const ocr = await runOcr(runtime, state);
      if (ocr.terminal) return ocr.terminal;
      if (ocr.failure)
        return result(
          state,
          "extract_failed",
          "ocr",
          { problems: [ocr.failure.code] },
          ocr.failure,
        );
      selectedSource = state.ocrSource;
      normalized = await extractAndAssess(
        runtime,
        state,
        state.ocrSource,
        state.ocrText,
      );
      if (normalized.terminal) return normalized.terminal;
      if (
        normalized.failure ||
        normalized.signal !== "readable"
      )
        return result(
          state,
          "extract_failed",
          "assess-readability",
          {
            problems: [
              normalized.failure
                ? normalized.failure.code
                : "book.ocr_insufficient",
            ],
          },
          normalized.failure ||
            operationFailure(
              "book.ocr_insufficient",
              "document.assess-readability",
            ),
        );
    }
    normalizedPath = normalized.input;
  }

  let plan = null;
  if (meta.format === "pdf") {
    const planned = await runPlan(
      runtime,
      state,
      selectedSource,
      normalizedPath,
    );
    if (planned.failure)
      return result(
        state,
        "extract_failed",
        "chapter-plan",
        { problems: [planned.failure.code] },
        planned.failure,
      );
    plan = planned.receipt;
  }

  let extractionResult = await runChapterExtract(runtime, state, {
    input: selectedSource,
    mode: meta.format === "epub" ? "epub" : plan.mode,
    plan: plan ? plan.chapters : [],
    label: "extract",
  });
  if (extractionResult.terminal) return extractionResult.terminal;
  if (extractionResult.failure)
    return result(
      state,
      "extract_failed",
      "chapter-extract",
      { problems: [extractionResult.failure.code] },
      extractionResult.failure,
    );
  let extraction = extractionResult.receipt;
  if (!extraction.chapters.length)
    return result(
      state,
      "no_chapters",
      "chapter-extract",
      { problems: ["book.no_chapters"] },
      operationFailure("book.no_chapters", "chapter.extract"),
    );

  let assessed = await assessBoundaries(runtime, state, extraction);
  if (assessed.failure)
    return result(
      state,
      "extract_failed",
      "chapter-assess",
      { problems: [assessed.failure.code] },
      assessed.failure,
    );
  let boundary = assessed.receipt;
  if (boundary.signal !== "ready") {
    if (
      boundary.signal === "invalid_source" ||
      (boundary.signal === "needs_ocr" &&
        (meta.format === "epub" ||
          state.budgets.ocr.used >= state.budgets.ocr.limit))
    )
      return result(
        state,
        "extract_failed",
        "chapter-assess",
        { problems: boundary.diagnostics },
        operationFailure(
          boundary.signal === "needs_ocr"
            ? "book.ocr_insufficient"
            : "book.invalid_source",
          "chapter.assess-boundaries",
        ),
      );
    if (
      state.budgets.planRecovery.used >=
      state.budgets.planRecovery.limit
    )
      return result(
        state,
        "extract_failed",
        "chapter-recovery",
        { problems: boundary.diagnostics },
        operationFailure(
          "book.chapter_recovery_exhausted",
          "chapter.assess-boundaries",
        ),
      );
    state.budgets.planRecovery.used += 1;

    if (boundary.signal === "needs_ocr") {
      const ocr = await runOcr(runtime, state);
      if (ocr.terminal) return ocr.terminal;
      if (ocr.failure)
        return result(
          state,
          "extract_failed",
          "ocr",
          { problems: [ocr.failure.code] },
          ocr.failure,
        );
      selectedSource = state.ocrSource;
      const normalized = await extractAndAssess(
        runtime,
        state,
        state.ocrSource,
        state.ocrText,
      );
      if (normalized.terminal) return normalized.terminal;
      if (
        normalized.failure ||
        normalized.signal !== "readable"
      )
        return result(
          state,
          "extract_failed",
          "assess-readability",
          {
            problems: [
              normalized.failure
                ? normalized.failure.code
                : "book.ocr_insufficient",
            ],
          },
          normalized.failure ||
            operationFailure(
              "book.ocr_insufficient",
              "document.assess-readability",
            ),
        );
      normalizedPath = normalized.input;
    }

    if (
      boundary.signal === "needs_replan" ||
      boundary.signal === "needs_ocr"
    ) {
      const replanned = await runPlan(
        runtime,
        state,
        selectedSource,
        normalizedPath,
        boundary.diagnostics.map(
          (diagnostic) =>
            `${diagnostic.path}: ${diagnostic.kind}: ${diagnostic.reason}`,
        ),
      );
      if (replanned.failure)
        return result(
          state,
          "extract_failed",
          "chapter-plan",
          { problems: [replanned.failure.code] },
          replanned.failure,
        );
      plan = replanned.receipt;
      extractionResult = await runChapterExtract(runtime, state, {
        input: selectedSource,
        mode: plan.mode,
        plan: plan.chapters,
        expectedManifestFingerprint:
          extraction.manifest_fingerprint,
        label: "replan",
      });
      if (extractionResult.terminal) return extractionResult.terminal;
      if (extractionResult.failure)
        return result(
          state,
          "extract_failed",
          "chapter-replan",
          { problems: [extractionResult.failure.code] },
          extractionResult.failure,
        );
      extraction = extractionResult.receipt;
    } else if (boundary.signal === "needs_repair") {
      for (const diagnostic of boundary.diagnostics) {
        extractionResult = await runChapterExtract(runtime, state, {
          input: selectedSource,
          mode: "repair",
          expectedManifestFingerprint:
            extraction.manifest_fingerprint,
          repair: diagnostic,
          label: `repair-extract-${diagnostic.slot}`,
        });
        if (extractionResult.terminal)
          return extractionResult.terminal;
        if (extractionResult.failure)
          return result(
            state,
            "extract_failed",
            "chapter-repair",
            { problems: [extractionResult.failure.code] },
            extractionResult.failure,
          );
        extraction = extractionResult.receipt;
      }
    } else {
      return result(
        state,
        "extract_failed",
        "chapter-assess",
        { problems: boundary.diagnostics },
        operationFailure(
          "book.chapter_assessment_failed",
          "chapter.assess-boundaries",
        ),
      );
    }

    assessed = await assessBoundaries(runtime, state, extraction);
    if (assessed.failure)
      return result(
        state,
        "extract_failed",
        "chapter-assess",
        { problems: [assessed.failure.code] },
        assessed.failure,
      );
    boundary = assessed.receipt;
    if (boundary.signal !== "ready")
      return result(
        state,
        "extract_failed",
        "chapter-recovery",
        { problems: boundary.diagnostics },
        operationFailure(
          "book.chapter_recovery_exhausted",
          "chapter.assess-boundaries",
        ),
      );
  }

  const chapters = extraction.chapters;
  log(`${slug}: validated ${chapters.length} exact chapters`);
  const firstPass = await parallel(
    chapters.map(
      (chapter) => () =>
        analyseChapter(runtime, state, chapter),
    ),
  );
  for (const entry of firstPass)
    if (entry.terminal) return entry.terminal;

  let refill = [];
  const presentSlots = new Set();
  for (let index = 0; index < chapters.length; index += 1) {
    const chapter = chapters[index];
    const receipt = firstPass[index].receipt;
    if (chapterPresent(receipt, "create")) {
      presentSlots.add(chapter.slot);
      continue;
    }
    if (
      receipt.status === "failed" &&
      receipt.failure.outcome === "known" &&
      receipt.failure.retryable === true &&
      receipt.write_state === "not_written"
    )
      refill.push(chapter);
  }
  if (refill.length) {
    state.budgets.refill.used += 1;
    const refillResults = await parallel(
      refill.map(
        (chapter) => () =>
          analyseChapter(
            runtime,
            state,
            chapter,
            "create",
            [],
            `ch${chapter.slot}:refill`,
          ),
      ),
    );
    for (let index = 0; index < refillResults.length; index += 1) {
      const entry = refillResults[index];
      if (entry.terminal) return entry.terminal;
      if (chapterPresent(entry.receipt, "create"))
        presentSlots.add(refill[index].slot);
    }
  }
  const expectedSlots = chapters.map((chapter) => chapter.slot);
  const presentSlotsOrdered = expectedSlots.filter((slot) =>
    presentSlots.has(slot),
  );
  const missing = chapters.filter(
    (chapter) => !presentSlots.has(chapter.slot),
  );
  if (missing.length)
    state.chapterInventory = {
      expected_slots: expectedSlots,
      present_slots: presentSlotsOrdered,
      missing_slots: missing.map((chapter) => chapter.slot),
    };
  if (missing.length)
    return result(
      state,
      "chapters_incomplete",
      "chapter-join",
      {
        analysed: chapters.length - missing.length,
        expected: chapters.length,
        expected_slots: [...state.chapterInventory.expected_slots],
        present_slots: [...state.chapterInventory.present_slots],
        missing_slots: [...state.chapterInventory.missing_slots],
      },
      operationFailure(
        "book.chapters_incomplete",
        "book.join",
      ),
    );

  const chapterOutputs = chapters.map((chapter) =>
    chapterOutputPath(state, chapter),
  );
  state.artifacts = state.artifacts.filter(
    (artifact) => artifact.role !== "chapter_canonical",
  );
  for (const path of chapterOutputs)
    state.artifacts.push({
      role: "chapter_canonical",
      path,
      exists: true,
      usable: null,
      producer: "chapter.analyse",
    });

  const synthesis = await synthesise(
    runtime,
    state,
    chapterOutputs,
  );
  if (synthesis.terminal) return synthesis.terminal;

  const owners = ownerMap(state, chapters);
  let audited = await audit(runtime, state, 1, owners);
  if (audited.terminal) return audited.terminal;
  if (audited.receipt.mutated_paths.length)
    state.repaired = true;
  if (
    audited.clean &&
    audited.receipt.mutated_paths.length === 0
  )
    return result(state, "ok", "audit", {
      year_warning:
        state.yearEvidence &&
        state.yearEvidence.verdict !== "MATCH"
          ? state.yearEvidence
          : null,
    });

  state.budgets.auditRepair.used += 1;
  const byTarget = new Map();
  for (const diagnostic of audited.receipt.escalated) {
    const entries = byTarget.get(diagnostic.path) || [];
    if (
      !entries.some(
        (entry) =>
          entry.kind === diagnostic.kind &&
          entry.reason === diagnostic.reason,
      )
    )
      entries.push(diagnostic);
    byTarget.set(diagnostic.path, entries);
  }
  const chapterRepairs = chapters
    .map((chapter) => ({
      chapter,
      diagnostics:
        byTarget.get(chapterOutputPath(state, chapter)) || [],
    }))
    .filter((entry) => entry.diagnostics.length);
  let chapterChanged = false;
  if (chapterRepairs.length) {
    const repaired = await parallel(
      chapterRepairs.map(
        ({ chapter, diagnostics }) => () =>
          analyseChapter(
            runtime,
            state,
            chapter,
            "repair",
            diagnostics,
            `ch${chapter.slot}:repair`,
          ),
      ),
    );
    for (const entry of repaired) {
      if (entry.terminal) return entry.terminal;
      if (entry.receipt.status !== "succeeded")
        return result(
          state,
          "audit_escalated",
          "repair",
          { escalated: audited.receipt.escalated },
          entry.receipt.failure,
        );
      if (entry.receipt.action === "repair")
        chapterChanged = true;
    }
    if (chapterChanged) state.repaired = true;
  }

  const overviewDiagnostics =
    byTarget.get(state.canonical) || [];
  const chapterMutatedByAudit =
    audited.receipt.mutated_paths.some(
      (path) =>
        owners.get(path) &&
        owners.get(path).key === "chapter.analyse",
    );
  const dependencyChanged =
    chapterChanged ||
    chapterMutatedByAudit;
  if (dependencyChanged || overviewDiagnostics.length) {
    const diagnostics = overviewDiagnostics.length
      ? overviewDiagnostics
      : [
          {
            path: state.canonical,
            kind: "chapter_dependency_changed",
            reason:
              "an audited chapter or overview changed after synthesis",
          },
        ];
    const repairedSynthesis = await synthesise(
      runtime,
      state,
      chapterOutputs,
      "repair",
      diagnostics,
    );
    if (repairedSynthesis.terminal)
      return repairedSynthesis.terminal;
    if (repairedSynthesis.receipt.status !== "succeeded")
      return result(
        state,
        "audit_escalated",
        "repair",
        { escalated: audited.receipt.escalated },
        repairedSynthesis.receipt.failure,
      );
  }

  audited = await audit(runtime, state, 2, owners);
  if (audited.terminal) return audited.terminal;
  if (audited.receipt.mutated_paths.length)
    state.repaired = true;
  const staleAfterSecondAudit =
    audited.receipt.mutated_paths.some(
      (path) => path !== state.canonical,
    );
  if (!audited.clean || staleAfterSecondAudit) {
    const exhaustedDiagnostics = [
      ...audited.receipt.escalated,
    ];
    for (const path of audited.receipt.mutated_paths)
      if (
        path !== state.canonical &&
        !exhaustedDiagnostics.some(
          (diagnostic) =>
            diagnostic.path === path &&
            diagnostic.kind === "mutation_after_repair_budget",
        )
      )
        exhaustedDiagnostics.push({
          path,
          kind: "mutation_after_repair_budget",
          reason:
            "re-audit changed a chapter after the single synthesis repair budget",
        });
    return result(
      state,
      "audit_escalated",
      "audit",
      { escalated: exhaustedDiagnostics },
      operationFailure(
        "book.repair_exhausted",
        "book.audit",
      ),
    );
  }

  return result(state, "ok", "audit", {
    year_warning:
      state.yearEvidence &&
      state.yearEvidence.verdict !== "MATCH"
        ? state.yearEvidence
        : null,
  });
}

export async function processBook(runtime, slug, meta, opts = {}) {
  const validation = validateBookIdentity(slug, meta);
  if (!validation.ok)
    return rejectedBookResult(slug, validation);
  const yearDecision = validateYearDecision(
    opts.yearDecision,
    slug,
    validation.meta,
  );
  if (!yearDecision.ok || (yearDecision.value && opts.batchYear === true))
    return rejectedBookResult(slug, {
      code: "book.year_decision_invalid",
      message: yearDecision.message ||
        "year_decision is not an Author batch policy",
    });
  const normalizedOpts = {
    ...opts,
    yearDecision: yearDecision.value,
  };
  return runtime.coalesce(
    `book:${slug}`,
    validation.fingerprint,
    () =>
      processValidatedBook(
        runtime,
        slug,
        validation.meta,
        normalizedOpts,
      ),
    () =>
      rejectedBookResult(
        slug,
        {
          code: "book.identity_conflict",
          message:
            "same-run requests disagree on the book identity",
        },
        "book.identity_conflict",
      ),
  );
}
