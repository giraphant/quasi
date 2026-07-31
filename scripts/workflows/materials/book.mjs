import {
  BOOK_ACQUIRE_CONTRACT,
  bookAcquirePrompt,
  bookAcquireSchema,
} from "../operations/acquire.mjs";
import {
  BOOK_TEMP_PATH,
  validYearEvidence,
} from "../operations/book-year-evidence.mjs";
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
  BOOK_PREPARE_STAGE_CONTRACT,
  bookPrepareStagePrompt,
  bookPrepareStageSchema,
} from "../operations/extract.mjs";
import {
  BOOK_SYNTHESISE_CONTRACT,
  bookSynthesiseOperationPrompt,
  bookSynthesiseSchema,
} from "../operations/synthesise.mjs";
import {
  exactKeys,
  optionalText,
  validText,
} from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import {
  MATERIAL_RECEIPT_VERSION,
  bookYearUserGate,
  stageUserGate,
} from "./receipt.mjs";

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
    userGate: null,
    budgets: {
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
    user_gate: state.userGate || null,
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
        : status === "needs_input"
          ? {
              operation_key: "book.user-gate",
              stage,
              policy:
                stage === "download"
                  ? "human-year-decision-or-correct-request"
                  : "answer-the-stage-question",
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
      : publicStatus === "needs_input" ||
          publicStatus === "year_mismatch" ||
          publicStatus === "year_ambiguous"
        ? "needs_input"
      : publicStatus === "blocked"
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
    userGate: null,
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

function prepareFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "book.prepare_failed",
    "book.prepare",
    outcome,
    !!(issue && issue.retryable),
    (issue && issue.summary) || "Book Prepare did not complete",
  );
}

async function prepareBook(runtime, state) {
  const context = {
    outputDir: state.chaptersDir,
    manifest: state.manifest,
    normalized: state.sourceText,
    recoverySource: state.ocrSource,
    recoveryText: state.ocrText,
  };
  const schema = bookPrepareStageSchema({
    materialKey: state.materialKey,
    source: state.source,
    format: state.meta.format,
    normalized: state.sourceText,
    recoverySource: state.ocrSource,
    recoveryText: state.ocrText,
    outputDir: state.chaptersDir,
    manifest: state.manifest,
  });
  const run = await runtime.operate(
    bookPrepareStagePrompt({
      materialKey: state.materialKey,
      identity: state.meta,
      source: state.source,
      format: state.meta.format,
      normalized: state.sourceText,
      recoverySource: state.ocrSource,
      recoveryText: state.ocrText,
      outputDir: state.chaptersDir,
      manifest: state.manifest,
    }),
    {
      phase: "Prepare",
      agentType: "quasi:extract-agent",
      label: `${state.slug}:prepare`,
      schema,
    },
    {
      key: "book.prepare",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "normalized_document",
        "recovery_source",
        "chapter_manifest",
        "normalized_chapter",
      ],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: BOOK_PREPARE_STAGE_CONTRACT,
      context,
    },
  );
  state.operations.push(run.receipt);
  if (run.edge === "unknown")
    return {
      terminal: blocked(
        state,
        "prepare",
        "book.prepare",
        run.receipt,
      ),
    };
  if (run.edge === "blocked")
    return {
      terminal: result(
        state,
        "blocked",
        "prepare",
        { problems: run.receipt.diagnostics },
        prepareFailure(run.receipt, "unknown"),
      ),
    };
  if (run.edge === "mismatch")
    return {
      terminal: mismatchBlocked(state, "prepare", "book.prepare"),
    };
  if (run.edge === "needs_input") {
    state.userGate = stageUserGate(run.receipt);
    return {
      terminal: result(
        state,
        "needs_input",
        "prepare",
        { question: stageIssue(run.receipt).user_question },
        prepareFailure(run.receipt),
      ),
    };
  }
  if (run.edge === "failed")
    return {
      terminal: result(
        state,
        "extract_failed",
        "prepare",
        { problems: run.receipt.diagnostics },
        prepareFailure(run.receipt),
      ),
    };
  state.artifacts = state.artifacts.filter(
    (artifact) =>
      ![
        "normalized_document",
        "recovery_source",
        "chapter_manifest",
        "normalized_chapter",
      ].includes(artifact.role),
  );
  for (const artifact of run.receipt.artifacts)
    state.artifacts.push({
      ...artifact,
      producer: "book.prepare",
    });
  return { receipt: run.receipt };
}

const chapterInputPath = (state, chapter) =>
  `${state.chaptersDir}/${chapter.filename}`;
const chapterOutputPath = (state, chapter) =>
  `vault/books/${state.slug}/ch${chapter.slot}-${chapter.slug}.md`;

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
  const { log, parallel, phase } = runtime;
  phase("Acquire");
  const state = createBookState(slug, meta);

  const acquireSchema = bookAcquireSchema({
    slug,
    allowedSources: state.allowedSources,
  });
  const download = await runtime.operate(
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
      contract: BOOK_ACQUIRE_CONTRACT,
      context: {
        slug,
        allowedSources: state.allowedSources,
        expectedYear: meta.year,
        batchAcceptYear: opts.batchYear === true,
        yearDecision: opts.yearDecision,
      },
    },
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
  const downloadReceipt = download.receipt;
  state.operations.push(downloadReceipt);
  state.yearEvidence = downloadReceipt.year_evidence || null;
  if (downloadReceipt.signal === "blocked")
    return blocked(
      state,
      "download",
      "book.acquire",
      downloadReceipt,
    );
  if (
    downloadReceipt.signal === "year_mismatch" ||
    downloadReceipt.signal === "year_ambiguous"
  ) {
    state.userGate = bookYearUserGate(downloadReceipt);
    return result(
      state,
      downloadReceipt.signal,
      "download",
      {
        year_evidence: downloadReceipt.year_evidence,
        tmp_path: downloadReceipt.tmp_path,
      },
      downloadReceipt.failure,
    );
  }
  if (downloadReceipt.signal === "download_failed")
    return result(
      state,
      "download_failed",
      "download",
      {
        failure_reason: downloadReceipt.failure_reason,
        attempts: downloadReceipt.attempts,
      },
      downloadReceipt.failure,
    );
  state.source = downloadReceipt.output_path;
  meta = { ...meta, format: downloadReceipt.format };
  state.meta = meta;
  state.artifacts.push({
    role: "source",
    path: state.source,
    exists: true,
    usable: null,
    producer:
      downloadReceipt.disposition === "reused"
        ? "book.acquire:reconciled"
        : "book.acquire",
  });

  phase("Prepare");
  const prepared = await prepareBook(runtime, state);
  if (prepared.terminal) return prepared.terminal;
  const chapters = prepared.receipt.chapters;
  log(`${slug}: validated ${chapters.length} exact chapters`);
  phase("Analyse");
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

  phase("Synthesise");
  const synthesis = await synthesise(
    runtime,
    state,
    chapterOutputs,
  );
  if (synthesis.terminal) return synthesis.terminal;

  const owners = ownerMap(state, chapters);
  phase("Audit");
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
    phase("Analyse");
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
    phase("Synthesise");
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

  phase("Audit");
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
