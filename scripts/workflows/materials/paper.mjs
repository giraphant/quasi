import {
  PAPER_ACQUIRE_CONTRACT,
  paperAcquirePrompt,
  paperAcquireSchema,
} from "../operations/acquire.mjs";
import {
  PAPER_ANALYSE_CONTRACT,
  paperAnalyseOperationPrompt,
  paperAnalyseSchema,
} from "../operations/analyse.mjs";
import {
  PAPER_AUDIT_CONTRACT,
  paperAuditPrompt,
  paperAuditSchema,
} from "../operations/audit.mjs";
import {
  DOCUMENT_OCR_CONTRACT,
  READABILITY_CONTRACT,
  TEXT_EXTRACT_CONTRACT,
  documentOcrOperationPrompt,
  documentOcrOperationSchema,
  extractTextOperationPrompt,
  readabilitySchema,
  textExtractSchema,
} from "../operations/extract.mjs";
import { readabilityOperationPrompt } from "../operations/extract.mjs";
import { optionalText, validText } from "../runtime.mjs";

const MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1";
const PAPER_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

function validatePaperIdentity(slug, meta) {
  if (typeof slug !== "string" || !PAPER_SLUG.test(slug))
    return {
      ok: false,
      code: "paper.slug_invalid",
      message: "paper slug is not canonical",
      canonicalSlug: null,
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "paper metadata must be an object",
      canonicalSlug: slug,
    };
  if (!validText(meta.title, 1, 500))
    return {
      ok: false,
      code: "paper.identity_invalid",
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
      code: "paper.identity_invalid",
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
      code: "paper.identity_invalid",
      message: "year must be an integer in the supported range",
      canonicalSlug: slug,
    };
  if (!validText(meta.journal, 1, 500))
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "journal is missing or invalid",
      canonicalSlug: slug,
    };
  if (
    !optionalText(meta.doi, 300) ||
    !optionalText(meta.oa_url, 2048) ||
    !optionalText(meta.url, 2048) ||
    (meta.confidence !== undefined &&
      !["provided", "verified"].includes(meta.confidence))
  )
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "optional identity fields are invalid",
      canonicalSlug: slug,
    };
  const normalized = {
    title: meta.title,
    authors: [...meta.authors],
    year: meta.year,
    journal: meta.journal,
    doi: meta.doi || null,
    oa_url: meta.oa_url || null,
    url: meta.url || null,
    confidence:
      meta.confidence === "verified" ? "verified" : "provided",
  };
  return {
    ok: true,
    canonicalSlug: slug,
    meta: normalized,
    fingerprint: JSON.stringify({
      title: normalized.title,
      authors: normalized.authors,
      year: normalized.year,
      journal: normalized.journal,
      doi: normalized.doi,
    }),
  };
}

const operationFailure = (
  code,
  operationKey,
  outcome = "known",
  message = null,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable: false,
  ...(message ? { message } : {}),
});

function auditOperation(receipt, output, pass) {
  const escalated = Array.isArray(receipt && receipt.escalated)
    ? receipt.escalated
    : [];
  const clean =
    receipt.status === "clean" &&
    escalated.length === 0 &&
    receipt.remaining_violations === 0;
  return {
    schema_version: "quasi.operation.paper.audit.receipt/0.1",
    key: "paper.audit",
    effect: "writer",
    status: receipt.status === "error" ? "failed" : "succeeded",
    attempt: 1,
    input_path: output,
    output_path: output,
    artifact_roles: ["canonical"],
    signal: clean ? "clean" : "escalated",
    pass,
    failure:
      receipt.status === "error"
        ? operationFailure(
          "paper.audit_failed",
          "paper.audit",
        )
        : null,
  };
}

function downloadOperation(item, output) {
  const succeeded = item && item.status === "ok";
  const blockedOutcome = item && item.status === "blocked";
  return {
    schema_version:
      "quasi.operation.paper.acquire.receipt/0.1",
    key: "paper.acquire",
    effect: "writer",
    status: succeeded
      ? "succeeded"
      : blockedOutcome
        ? "blocked"
        : "failed",
    attempt: 1,
    output_path: (item && item.path) || output,
    artifact_roles: ["source"],
    disposition: (item && item.disposition) || null,
    identity_verified:
      (item && item.identity_verified) || false,
    doi: (item && item.doi) || null,
    source: (item && item.source) || null,
    failure_reason:
      (item && (item.failure_reason || item.verdict_note)) || null,
    attempts:
      item && Array.isArray(item.attempts) ? item.attempts : [],
    failure: succeeded
      ? null
      : operationFailure(
          `paper.${(item && item.status) || "download_failed"}`,
          "paper.acquire",
          blockedOutcome ? "unknown" : "known",
        ),
  };
}

function createPaperState(slug) {
  return {
    slug,
    materialKey: `paper:${slug}`,
    source: `sources/${slug}.pdf`,
    sourceText: `processing/papers/${slug}/source.txt`,
    ocrSource: `processing/papers/${slug}/ocr.pdf`,
    ocrText: `processing/papers/${slug}/ocr.txt`,
    canonical: `vault/papers/${slug}.md`,
    operations: [],
    artifacts: [],
    audit: null,
    warnings: [],
    repaired: false,
    disposition: null,
  };
}

function materialReceipt(
  state,
  {
    status,
    stage,
    failure = null,
    disposition = null,
  },
) {
  return {
    schema_version: MATERIAL_RECEIPT_VERSION,
    material_key: state.materialKey,
    kind: "paper",
    id: state.slug,
    status,
    disposition:
      disposition ||
      (status === "complete"
        ? state.disposition ||
          (state.repaired ? "repaired" : "created")
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
    resume:
      status === "blocked"
        ? { operation_key: "paper.reconcile" }
        : null,
  };
}

function rejectedPaperResult(slug, validation, code = null) {
  const canonical =
    typeof slug === "string" && PAPER_SLUG.test(slug);
  const failure = operationFailure(
    code || validation.code,
    "paper.identity",
    "known",
    validation.message ||
      "conflicting paper identity for one material key",
  );
  return {
    slug: typeof slug === "string" ? slug : null,
    status: "blocked",
    material_receipt: {
      schema_version: MATERIAL_RECEIPT_VERSION,
      material_key: canonical ? `paper:${slug}` : null,
      kind: "paper",
      id: typeof slug === "string" ? slug : null,
      status: "blocked",
      disposition: null,
      stage: "identity",
      artifacts: [],
      operations: [],
      audit: null,
      freshness: {
        observation: "unknown",
        basis: "identity-validation",
      },
      warnings: [],
      failure,
      resume: null,
    },
  };
}

function result(state, status, stage, extra = {}, failure = null) {
  const terminal =
    status === "ok" ? "complete" : status === "blocked" ? "blocked" : "failed";
  return {
    slug: state.slug,
    status,
    ...extra,
    material_receipt: materialReceipt(state, {
      status: terminal,
      stage,
      failure,
    }),
  };
}

function blocked(state, stage, operationKey, receipt) {
  const failure =
    (receipt && receipt.failure) ||
    operationFailure(
      "paper.writer_outcome_unknown",
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
      "paper.writer_receipt_mismatch",
      operationKey,
      "unknown",
      "writer receipt did not prove the exact input/output contract",
    ),
  );
}

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
      contract: TEXT_EXTRACT_CONTRACT,
      context: { input, output },
    },
  );
  state.operations.push(extraction.receipt);
  if (extraction.edge === "unknown" || extraction.edge === "blocked")
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
    return {
      failure:
        extraction.receipt.failure ||
        operationFailure(
          "document.extract_text_failed",
          "document.extract-text",
        ),
    };

  state.artifacts.push({
    role: "normalized_text",
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

async function analyse(
  runtime,
  state,
  meta,
  input,
  mode = "create",
  diagnostics = [],
) {
  const analysis = await runtime.operate(
    paperAnalyseOperationPrompt(
      state.slug,
      meta,
      input,
      mode,
      diagnostics,
    ),
    {
      phase: "Analyse",
      agentType: "quasi:analyse-agent",
      label: `${state.slug}:analyse`,
      schema: paperAnalyseSchema({
        mode,
        input,
        output: state.canonical,
      }),
    },
    {
      key: "paper.analyse",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
      contract: PAPER_ANALYSE_CONTRACT,
      context: { mode, input, output: state.canonical },
    },
  );
  const receipt = analysis.receipt;
  state.operations.push(receipt);
  if (analysis.edge === "unknown" || analysis.edge === "blocked")
    return {
      terminal: blocked(
        state,
        "analyse",
        "paper.analyse",
        receipt,
      ),
    };
  if (analysis.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "analyse",
        "paper.analyse",
      ),
    };
  if (analysis.edge === "reconcile") return { reconcile: true };
  if (analysis.edge !== "ok")
    return {
      terminal: result(
        state,
        "analyse_failed",
        "analyse",
        {
          notes: receipt.failure && receipt.failure.code,
        },
        receipt.failure ||
          operationFailure("paper.analysis_failed", "paper.analyse"),
      ),
    };
  state.artifacts = state.artifacts.filter(
    (artifact) => artifact.role !== "canonical",
  );
  state.artifacts.push({
    role: "canonical",
    path: state.canonical,
    exists: true,
    usable: true,
    producer: "paper.analyse",
  });
  if (mode === "repair") {
    if (receipt.action === "repair") {
      state.repaired = true;
      state.disposition = "repaired";
    } else {
      state.repaired = false;
      state.disposition = "reused";
    }
  } else {
    state.disposition = "created";
  }
  return { action: receipt.action };
}

async function audit(runtime, state, pass) {
  const auditRun = await runtime.operate(
    paperAuditPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit`,
      schema: paperAuditSchema({ target: state.canonical }),
    },
    {
      key: "paper.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
      contract: PAPER_AUDIT_CONTRACT,
      context: { target: state.canonical },
    },
  );
  const receipt = auditRun.receipt;
  if (auditRun.edge === "unknown") {
    state.operations.push(receipt);
    return {
      terminal: blocked(
        state,
        "audit",
        "paper.audit",
        receipt,
      ),
    };
  }
  if (auditRun.edge === "mismatch") {
    state.operations.push(receipt);
    state.audit = receipt || null;
    return {
      terminal: mismatchBlocked(
        state,
        "audit",
        "paper.audit",
      ),
    };
  }
  const operation = auditOperation(receipt, state.canonical, pass);
  state.operations.push(operation);
  state.audit = receipt;
  if (auditRun.edge !== "ok")
    return {
      terminal: result(
        state,
        "audit_escalated",
        "audit",
        {},
        operation.failure,
      ),
    };
  const escalated = receipt.escalated;
  const clean =
    receipt.status === "clean" &&
    escalated.length === 0 &&
    receipt.remaining_violations === 0;
  return { receipt, escalated, clean };
}

async function processValidatedPaper(runtime, slug, meta) {
  const { log, phase } = runtime;
  phase("Acquire");
  const state = createPaperState(slug);

  const download = await runtime.operate(
    paperAcquirePrompt(slug, meta),
    {
      phase: "Acquire",
      agentType: "quasi:download-agent",
      label: `${slug}:acquire`,
      schema: paperAcquireSchema({
        slug,
        output: state.source,
      }),
    },
    {
      key: "paper.acquire",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["source"],
      contract: PAPER_ACQUIRE_CONTRACT,
      context: { slug, output: state.source },
    },
  );
  if (download.edge === "unknown") {
    state.operations.push(download.receipt);
    return blocked(
      state,
      "download",
      "paper.acquire",
      download.receipt,
    );
  }
  if (download.edge === "mismatch") {
    state.operations.push(download.receipt);
    return mismatchBlocked(
      state,
      "download",
      "paper.acquire",
    );
  }
  const item = download.receipt.per_item[0];
  const downloadReceipt = downloadOperation(item, state.source);
  state.operations.push(downloadReceipt);
  if (download.edge === "blocked")
    return blocked(
      state,
      "download",
      "paper.acquire",
      downloadReceipt,
    );
  if (download.edge !== "ok") {
    return result(
      state,
      "download_failed",
      "download",
      {
        doi: item.doi || meta.doi || null,
        source: item.source || null,
        failure_reason: item.failure_reason || item.verdict_note,
        attempts: item.attempts || [],
      },
      downloadReceipt.failure,
    );
  }
  state.artifacts.push({
    role: "source",
    path: state.source,
    exists: true,
    usable: null,
    producer:
      item.disposition === "reused"
        ? "paper.acquire:reconciled"
        : "paper.acquire",
  });

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
      "analyse_failed",
      "extract-text",
      {},
      normalized.failure,
    );
  if (normalized.signal === "invalid_source")
    return result(
      state,
      "analyse_failed",
      "assess-readability",
      {},
      operationFailure(
        "paper.invalid_source",
        "document.assess-readability",
      ),
    );

  if (normalized.signal === "needs_ocr") {
    log(`${slug}: typed readability signal requests one OCR recovery`);
    const ocr = await runtime.operate(
      documentOcrOperationPrompt(
        state.materialKey,
        state.source,
        state.ocrSource,
      ),
      {
        phase: "Prepare",
        agentType: "general-purpose",
        label: `${slug}:ocr`,
        schema: documentOcrOperationSchema("paper", {
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
        contract: DOCUMENT_OCR_CONTRACT,
        context: { input: state.source, output: state.ocrSource },
      },
    );
    state.operations.push(ocr.receipt);
    if (ocr.edge === "unknown" || ocr.edge === "blocked")
      return blocked(state, "ocr", "document.ocr", ocr.receipt);
    if (ocr.edge === "mismatch")
      return mismatchBlocked(
        state,
        "ocr",
        "document.ocr",
      );
    if (ocr.edge !== "ok" && ocr.edge !== "reconcile")
      return result(
        state,
        "ocr_failed",
        "ocr",
        {},
        ocr.receipt.failure ||
          operationFailure("paper.ocr_failed", "document.ocr"),
      );
    const existingRecovery = ocr.edge === "reconcile";
    if (existingRecovery)
      state.warnings.push(
        "existing OCR output was recovered through extract and typed readability assessment",
      );
    state.artifacts.push({
      role: "recovery_source",
      path: state.ocrSource,
      exists: true,
      usable: null,
      producer: existingRecovery
        ? "document.ocr:reconciled"
        : "document.ocr",
    });

    normalized = await extractAndAssess(
      runtime,
      state,
      state.ocrSource,
      state.ocrText,
    );
    if (normalized.terminal) return normalized.terminal;
    if (normalized.failure)
      return result(
        state,
        "ocr_failed",
        "extract-text",
        {},
        normalized.failure,
      );
    if (normalized.signal !== "readable")
      return result(
        state,
        "ocr_failed",
        "assess-readability",
        {},
        operationFailure(
          normalized.signal === "needs_ocr"
            ? "paper.ocr_insufficient"
            : "paper.invalid_recovery_source",
          "document.assess-readability",
        ),
      );
  }

  const analysisResult = await analyse(
    runtime,
    state,
    meta,
    normalized.input,
  );
  if (analysisResult.terminal) return analysisResult.terminal;
  if (analysisResult.reconcile) {
    state.disposition = "reused";
    state.artifacts = state.artifacts.filter(
      (artifact) => artifact.role !== "canonical",
    );
    state.artifacts.push({
      role: "canonical",
      path: state.canonical,
      exists: true,
      usable: null,
      producer: "paper.analyse:reconciled",
    });
  }

  let auditResult = await audit(runtime, state, 1);
  if (auditResult.terminal) return auditResult.terminal;
  if (!auditResult.clean) {
    const exactDiagnostics = auditResult.escalated
      .filter(
        (diagnostic) =>
          diagnostic &&
          diagnostic.path === state.canonical &&
          diagnostic.kind &&
          diagnostic.reason,
      )
      .map(({ path, kind, reason }) => ({
        path,
        kind,
        reason,
      }));
    if (
      !exactDiagnostics.length ||
      exactDiagnostics.length !== auditResult.escalated.length
    )
      return result(
        state,
        "audit_escalated",
        "audit",
        { escalated: auditResult.escalated },
        operationFailure(
          "paper.repair_owner_unknown",
          "paper.audit",
        ),
      );

    const repairResult = await analyse(
      runtime,
      state,
      meta,
      normalized.input,
      "repair",
      exactDiagnostics,
    );
    if (repairResult.terminal) return repairResult.terminal;
    auditResult = await audit(runtime, state, 2);
    if (auditResult.terminal) return auditResult.terminal;
    if (!auditResult.clean)
      return result(
        state,
        "audit_escalated",
        "audit",
        { escalated: auditResult.escalated },
        operationFailure(
          "paper.repair_exhausted",
          "paper.audit",
        ),
      );
  }

  return result(state, "ok", "audit");
}

export async function processPaper(runtime, slug, meta) {
  const validation = validatePaperIdentity(slug, meta);
  if (!validation.ok)
    return rejectedPaperResult(slug, validation);
  return runtime.coalesce(
    `paper:${slug}`,
    validation.fingerprint,
    () =>
      processValidatedPaper(
        runtime,
        slug,
        validation.meta,
      ),
    () =>
      rejectedPaperResult(
        slug,
        {
          code: "paper.identity_conflict",
          message:
            "same-run requests disagree on the paper identity",
        },
        "paper.identity_conflict",
      ),
  );
}
