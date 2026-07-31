import {
  BOOK_ACQUIRE_CONTRACT,
  BOOK_TEMP_PATH,
  bookAcquirePrompt,
  bookAcquireSchema,
  validYearEvidence,
} from "../operations/acquire.mjs";
import {
  CHAPTER_ANALYSE_CONTRACT,
  chapterAnalyseOperationPrompt,
  chapterAnalyseSchema,
} from "../operations/analyse.mjs";
import {
  BOOK_AUDIT_CONTRACT,
  bookAuditPrompt,
  bookAuditSchema,
} from "../operations/audit.mjs";
import {
  BOOK_DOCUMENT_OCR_CONTRACT,
  CHAPTER_ASSESS_CONTRACT,
  CHAPTER_ASSESS_SCHEMA,
  CHAPTER_EXTRACT_CONTRACT,
  CHAPTER_PLAN_CONTRACT,
  CHAPTER_PLAN_SCHEMA,
  READABILITY_CONTRACT,
  TEXT_EXTRACT_CONTRACT,
  chapterAssessOperationPrompt,
  chapterExtractOperationPrompt,
  chapterExtractSchema,
  chapterPlanOperationPrompt,
  documentOcrOperationPrompt,
  documentOcrOperationSchema,
  extractTextOperationPrompt,
  readabilityOperationPrompt,
  readabilitySchema,
  textExtractSchema,
} from "../operations/extract.mjs";
import {
  BOOK_SYNTHESISE_CONTRACT,
  bookSynthesiseOperationPrompt,
  bookSynthesiseSchema,
} from "../operations/synthesise.mjs";
import {
  classifyReceipt,
  exactKeys,
  optionalText,
  validText,
} from "../runtime.mjs";

const MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1";
const BOOK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CATEGORIES = new Set([
  "monograph",
  "edited-volume",
  "handbook",
  "other",
]);

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
    !validYearEvidence(
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

function normaliseBookDownloadReceipt(receipt) {
  if (
    !receipt ||
    typeof receipt !== "object" ||
    Array.isArray(receipt) ||
    !Array.isArray(receipt.per_item) ||
    receipt.per_item.length !== 1
  )
    return receipt;
  const item = receipt.per_item[0];
  if (
    !item ||
    typeof item !== "object" ||
    Array.isArray(item) ||
    item.status !== "ok" ||
    !Object.prototype.hasOwnProperty.call(item, "tmp_path")
  )
    return receipt;
  const { tmp_path: _acceptedTempPath, ...accepted } = item;
  return { ...receipt, per_item: [accepted] };
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

const chapterInputPath = (state, chapter) =>
  `${state.chaptersDir}/${chapter.filename}`;
const chapterOutputPath = (state, chapter) =>
  `vault/books/${state.slug}/ch${chapter.slot}-${chapter.slug}.md`;

async function extractAndAssess(runtime, state, input, output) {
  const extraction = await runtime.operate(
    extractTextOperationPrompt(state.materialKey, input, output),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:extract-text`,
      schema: textExtractSchema({ input, output }),
    },
    {
      key: "document.extract-text",
      effect: "writer",
      retry: "forbidden",
      replay: "idempotent",
      artifactRoles: ["normalized_text"],
      unknownFailureCode: "document.writer_outcome_unknown",
      contract: TEXT_EXTRACT_CONTRACT,
      context: { input, output },
    },
  );
  state.operations.push(extraction.receipt);
  if (
    extraction.edge === "unknown" ||
    extraction.edge === "blocked"
  )
    return {
      terminal: blocked(
        state,
        "extract-text",
        "document.extract-text",
        extraction.receipt,
      ),
    };
  if (extraction.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "extract-text",
        "document.extract-text",
      ),
    };
  if (extraction.edge !== "ok")
    return { failure: extraction.receipt.failure };
  state.artifacts.push({
    role: "normalized_document",
    path: output,
    exists: true,
    usable: null,
    producer: "document.extract-text",
  });

  const assessment = await runtime.operate(
    readabilityOperationPrompt(
      state.materialKey,
      output,
      extraction.receipt,
    ),
    {
      phase: "Prepare",
      agentType: "general-purpose",
      label: `${state.slug}:assess-readability`,
      schema: readabilitySchema({ input: output }),
    },
    {
      key: "document.assess-readability",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: ["normalized_text"],
      unknownFailureCode: "document.readonly_outcome_unknown",
      contract: READABILITY_CONTRACT,
      context: { input: output },
    },
  );
  state.operations.push(assessment.receipt);
  if (assessment.edge === "mismatch")
    return {
      failure:
        (assessment.receipt.failure &&
          assessment.receipt.failure.outcome === "unknown" &&
          assessment.receipt.failure) ||
        operationFailure(
          "document.assess_readability_failed",
          "document.assess-readability",
        ),
    };
  if (assessment.edge !== "ok")
    return { failure: assessment.receipt.failure };
  state.artifacts[state.artifacts.length - 1].usable =
    assessment.receipt.signal === "readable";
  return { signal: assessment.receipt.signal, input: output };
}

async function runOcr(runtime, state) {
  state.budgets.ocr.used += 1;
  const ocr = await runtime.operate(
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
      schema: documentOcrOperationSchema("book", {
        input: state.source,
        output: state.ocrSource,
      }),
    },
    {
      key: "document.ocr",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["recovery_source"],
      unknownFailureCode: "document.writer_outcome_unknown",
      contract: BOOK_DOCUMENT_OCR_CONTRACT,
      context: { input: state.source, output: state.ocrSource },
    },
  );
  state.operations.push(ocr.receipt);
  if (ocr.edge === "unknown" || ocr.edge === "blocked")
    return {
      terminal: blocked(
        state,
        "ocr",
        "document.ocr",
        ocr.receipt,
      ),
    };
  if (ocr.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "ocr",
        "document.ocr",
      ),
    };
  if (ocr.edge !== "ok" && ocr.edge !== "reconcile")
    return { failure: ocr.receipt.failure };
  const existing = ocr.edge === "reconcile";
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
  const plan = await runtime.operate(
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
      contract: CHAPTER_PLAN_CONTRACT,
      context: { input, normalized },
    },
  );
  state.operations.push(plan.receipt);
  if (plan.edge === "unknown" || plan.edge === "mismatch")
    return {
      failure: operationFailure(
        "chapter.plan_receipt_invalid",
        "chapter.plan",
      ),
    };
  if (plan.edge !== "ok")
    return { failure: plan.receipt.failure };
  return { receipt: plan.receipt };
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
  const extraction = await runtime.operate(
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
      schema: chapterExtractSchema({
        input,
        outputDir: state.chaptersDir,
        manifest: state.manifest,
        mode,
      }),
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
      contract: CHAPTER_EXTRACT_CONTRACT,
      context: {
        input,
        outputDir: state.chaptersDir,
        manifest: state.manifest,
        mode,
      },
    },
  );
  state.operations.push(extraction.receipt);
  if (
    extraction.edge === "unknown" ||
    extraction.edge === "blocked"
  )
    return {
      terminal: blocked(
        state,
        "chapter-extract",
        "chapter.extract",
        extraction.receipt,
      ),
    };
  if (extraction.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "chapter-extract",
        "chapter.extract",
      ),
    };
  if (extraction.edge !== "ok")
    return { failure: extraction.receipt.failure };
  const receipt = extraction.receipt;
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
  const assessment = await runtime.operate(
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
      contract: CHAPTER_ASSESS_CONTRACT,
      context: {
        manifest: state.manifest,
        chapters: extraction.chapters.map((chapter) => ({
          slot: chapter.slot,
          path: chapterInputPath(state, chapter),
        })),
      },
    },
  );
  state.operations.push(assessment.receipt);
  if (
    assessment.edge === "unknown" ||
    assessment.edge === "mismatch"
  )
    return {
      failure: operationFailure(
        "chapter.assessment_receipt_invalid",
        "chapter.assess-boundaries",
      ),
    };
  if (assessment.edge !== "ok")
    return { failure: assessment.receipt.failure };
  return { receipt: assessment.receipt };
}

async function analyseChapter(
  runtime,
  state,
  chapter,
  mode = "create",
  diagnostics = [],
  label = null,
) {
  const input = chapterInputPath(state, chapter);
  const output = chapterOutputPath(state, chapter);
  const analysis = await runtime.operate(
    chapterAnalyseOperationPrompt(
      state.slug,
      state.meta,
      chapter,
      input,
      output,
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
      schema: chapterAnalyseSchema({ mode, input, output }),
    },
    {
      key: "chapter.analyse",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["chapter_canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: CHAPTER_ANALYSE_CONTRACT,
      context: { mode, input, output },
    },
  );
  state.operations.push(analysis.receipt);
  if (
    analysis.edge === "unknown" ||
    analysis.edge === "blocked"
  )
    return {
      terminal: blocked(
        state,
        "chapter-analyse",
        "chapter.analyse",
        analysis.receipt,
      ),
    };
  if (analysis.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "chapter-analyse",
        "chapter.analyse",
      ),
    };
  return {
    receipt: analysis.receipt,
    present:
      analysis.edge === "ok" || analysis.edge === "reconcile",
  };
}

async function synthesise(
  runtime,
  state,
  inputPaths,
  mode = "create",
  diagnostics = [],
) {
  const synthesis = await runtime.operate(
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
      schema: bookSynthesiseSchema({
        inputPaths,
        mode,
        output: state.canonical,
      }),
    },
    {
      key: "book.synthesise",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: BOOK_SYNTHESISE_CONTRACT,
      context: { mode, inputPaths, output: state.canonical },
    },
  );
  const receipt = synthesis.receipt;
  state.operations.push(receipt);
  if (
    synthesis.edge === "unknown" ||
    synthesis.edge === "blocked"
  )
    return {
      terminal: blocked(
        state,
        "synthesise",
        "book.synthesise",
        receipt,
      ),
    };
  if (synthesis.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "synthesise",
        "book.synthesise",
      ),
    };
  if (synthesis.edge === "failed")
    return {
      terminal: result(
        state,
        "synth_failed",
        "synthesise",
        { notes: receipt.failure.code },
        receipt.failure,
      ),
    };
  const createCollision = synthesis.edge === "reconcile";
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
  const auditRun = await runtime.operate(
    bookAuditPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit${pass === 1 ? "" : `-${pass}`}`,
      schema: bookAuditSchema({
        target: `vault/books/${state.slug}`,
      }),
    },
    {
      key: "book.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: BOOK_AUDIT_CONTRACT,
      context: { target: `vault/books/${state.slug}` },
    },
  );
  const receipt = auditRun.receipt;
  state.operations.push(receipt);
  if (auditRun.edge === "unknown")
    return {
      terminal: blocked(
        state,
        "audit",
        "book.audit",
        receipt,
      ),
    };
  if (auditRun.edge === "mismatch")
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
  if (auditRun.edge === "failed")
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

  const acquireSchema = bookAcquireSchema({
    slug,
    allowedSources: state.allowedSources,
  });
  const rawDownload = await runOperation(
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
      schema: acquireSchema,
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
  const download = classifyReceipt(
    normaliseBookDownloadReceipt(rawDownload),
    BOOK_ACQUIRE_CONTRACT,
    {
      slug,
      allowedSources: state.allowedSources,
      expectedYear: meta.year,
      batchAcceptYear: opts.batchYear === true,
      yearDecision: opts.yearDecision,
    },
    acquireSchema,
  );
  if (download.edge === "unknown") {
    state.operations.push(download.receipt);
    return blocked(
      state,
      "download",
      "book.acquire",
      download.receipt,
    );
  }
  if (download.edge === "mismatch") {
    state.operations.push(download.receipt);
    return mismatchBlocked(
      state,
      "download",
      "book.acquire",
    );
  }
  const item = download.receipt.per_item[0];
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
    const entry = firstPass[index];
    if (entry.present) {
      presentSlots.add(chapter.slot);
      continue;
    }
    const receipt = entry.receipt;
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
      if (entry.present)
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
