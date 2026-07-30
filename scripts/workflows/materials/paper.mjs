import {
  PAPER_ACQUIRE_SCHEMA,
  paperAcquirePrompt,
} from "../operations/acquire.mjs";
import {
  PAPER_ANALYSE_SCHEMA,
  paperAnalyseOperationPrompt,
} from "../operations/analyse.mjs";
import {
  PAPER_AUDIT_SCHEMA,
  paperAuditPrompt,
} from "../operations/audit.mjs";
import {
  DOCUMENT_OCR_SCHEMA,
  READABILITY_SCHEMA,
  TEXT_EXTRACT_SCHEMA,
  documentOcrOperationPrompt,
  extractTextOperationPrompt,
  readabilityOperationPrompt,
} from "../operations/extract.mjs";

const MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1";
const OPERATION_RECEIPT_VERSION = {
  extract: "quasi.operation.document.extract-text.receipt/0.1",
  assess:
    "quasi.operation.document.assess-readability.receipt/0.1",
  ocr: "quasi.operation.document.ocr.receipt/0.1",
  analyse: "quasi.operation.paper.analyse.receipt/0.1",
};
const PAPER_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;

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

const validOperationFailure = (
  failure,
  operationKey,
  retryable,
  allowMessage = false,
) => {
  if (
    !failure ||
    typeof failure !== "object" ||
    Array.isArray(failure)
  )
    return false;
  const keys = Object.keys(failure);
  const allowed = [
    "code",
    "operation_key",
    "outcome",
    "retryable",
    ...(allowMessage ? ["message"] : []),
  ];
  if (
    !["code", "operation_key", "outcome", "retryable"].every(
      (key) => keys.includes(key),
    ) ||
    keys.some((key) => !allowed.includes(key))
  )
    return false;
  return (
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    ["known", "unknown"].includes(failure.outcome) &&
    failure.retryable === retryable &&
    (failure.message === undefined ||
      validText(failure.message, 1, 4000))
  );
};

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const optionalText = (value, max) =>
  value == null || value === "" || validText(value, 1, max);

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

const hasExactRole = (receipt, role) =>
  Array.isArray(receipt && receipt.artifact_roles) &&
  receipt.artifact_roles.length === 1 &&
  receipt.artifact_roles[0] === role;

const isUnknownWriter = (receipt) =>
  !!(
    receipt &&
    (receipt.status === "blocked" ||
      (receipt.failure && receipt.failure.outcome === "unknown"))
  );

function exactOperation(
  receipt,
  {
    version,
    key,
    effect,
    input,
    output,
    role,
  },
) {
  return !!(
    receipt &&
    receipt.schema_version === version &&
    receipt.key === key &&
    receipt.effect === effect &&
    receipt.attempt === 1 &&
    receipt.input_path === input &&
    (output === undefined || receipt.output_path === output) &&
    hasExactRole(receipt, role)
  );
}

function strictAnalyseReceipt(receipt, mode) {
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
      "failure",
    ]) ||
    !["succeeded", "failed", "blocked"].includes(
      receipt.status,
    ) ||
    !["create", "repair", "reconciled"].includes(
      receipt.action,
    ) ||
    !["create", "repair"].includes(mode)
  )
    return false;
  if (receipt.status === "succeeded") {
    if (receipt.failure !== null) return false;
    return mode === "create"
      ? receipt.action === "create"
      : ["repair", "reconciled"].includes(receipt.action);
  }
  if (
    !validOperationFailure(
      receipt.failure,
      "paper.analyse",
      false,
    )
  )
    return false;
  if (
    receipt.status === "failed" &&
    (receipt.failure.outcome !== "known" ||
      receipt.action !== mode)
  )
    return false;
  if (
    receipt.status === "blocked" &&
    receipt.failure.outcome !== "unknown"
  )
    return false;
  if (
    mode === "create" &&
    receipt.action === "reconciled"
  )
    return (
      receipt.status === "blocked" &&
      receipt.failure.code ===
        "output_exists_requires_reconcile"
    );
  if (
    receipt.failure.code ===
    "output_exists_requires_reconcile"
  )
    return false;
  return receipt.action === mode;
}

function strictOcrReceipt(receipt) {
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
    receipt.schema_version !== OPERATION_RECEIPT_VERSION.ocr ||
    receipt.key !== "document.ocr" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    !hasExactRole(receipt, "recovery_source") ||
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
    !validOperationFailure(
      receipt.failure,
      "document.ocr",
      false,
      true,
    )
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.failure.outcome === "known" &&
      receipt.failure.code === "paper.ocr_failed"
    );
  if (receipt.failure.outcome !== "unknown") return false;
  if (receipt.failure.code === "paper.writer_receipt_mismatch")
    return true;
  return (
    receipt.failure.code ===
      "output_exists_requires_reconcile" &&
    receipt.exit === 0 &&
    receipt.exists === true &&
    receipt.size > 0
  );
}

function strictExtractReceipt(receipt) {
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
      "chars",
      "non_whitespace_chars",
      "pages",
      "text_pages",
      "failure",
    ]) ||
    receipt.schema_version !== OPERATION_RECEIPT_VERSION.extract ||
    receipt.key !== "document.extract-text" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    !hasExactRole(receipt, "normalized_text") ||
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
  if (
    !validOperationFailure(
      receipt.failure,
      "document.extract-text",
      false,
      true,
    )
  )
    return false;
  return receipt.status === "failed"
    ? receipt.failure.outcome === "known"
    : receipt.failure.outcome === "unknown";
}

function strictReadabilityReceipt(receipt) {
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
    receipt.schema_version !== OPERATION_RECEIPT_VERSION.assess ||
    receipt.key !== "document.assess-readability" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    !hasExactRole(receipt, "normalized_text") ||
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
  if (
    receipt.signal !== null ||
    !validOperationFailure(
      receipt.failure,
      "document.assess-readability",
      true,
      true,
    )
  )
    return false;
  return receipt.status === "failed"
    ? receipt.failure.outcome === "known"
    : receipt.failure.outcome === "unknown";
}

function strictAuditReceipt(receipt) {
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.paper.audit.agent-receipt/0.1" ||
    receipt.key !== "paper.audit" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    !["clean", "partial", "error"].includes(receipt.status) ||
    !Number.isInteger(receipt.remaining_violations) ||
    receipt.remaining_violations < 0 ||
    !Array.isArray(receipt.escalated) ||
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
      receipt.escalated.length > 0 &&
      receipt.remaining_violations === receipt.escalated.length
    );
  return receipt.status === "error";
}

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

function strictDownloadAttempt(attempt) {
  return !!(
    exactKeys(attempt, ["source", "status", "error"]) &&
    validText(attempt.source, 1, 200) &&
    validText(attempt.status, 1, 200) &&
    (attempt.error === null ||
      validText(attempt.error, 1, 4000))
  );
}

function strictPaperDownloadReceipt(receipt, slug, output) {
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
    "attempts",
  ];
  const allowed = [
    ...required,
    "path",
    "source",
    "doi",
    "verdict_note",
    "failure_reason",
  ];
  if (
    !item ||
    typeof item !== "object" ||
    Array.isArray(item) ||
    !required.every((key) =>
      Object.prototype.hasOwnProperty.call(item, key),
    ) ||
    Object.keys(item).some((key) => !allowed.includes(key)) ||
    item.kind !== "paper" ||
    item.slug !== slug ||
    !["ok", "download_failed", "blocked"].includes(item.status) ||
    ![null, "created", "reused"].includes(item.disposition) ||
    typeof item.identity_verified !== "boolean" ||
    !Array.isArray(item.attempts) ||
    item.attempts.some((attempt) => !strictDownloadAttempt(attempt)) ||
    (item.doi !== undefined &&
      item.doi !== null &&
      !validText(item.doi, 1, 300)) ||
    (item.verdict_note !== undefined &&
      !validText(item.verdict_note, 1, 4000))
  )
    return false;
  if (item.status === "ok")
    return (
      receipt.acquired === 1 &&
      receipt.failed === 0 &&
      ["created", "reused"].includes(item.disposition) &&
      item.identity_verified === true &&
      item.path === output &&
      validText(item.source, 1, 200) &&
      item.failure_reason === undefined
    );
  if (
    item.disposition !== null ||
    item.identity_verified !== false ||
    item.path !== undefined ||
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
  const extraction = await runtime.runOperation(
    extractTextOperationPrompt(state.materialKey, input, output),
    {
      phase: "Paper",
      agentType: "general-purpose",
      label: `paper.extract-text:${state.slug}`,
      schema: TEXT_EXTRACT_SCHEMA,
    },
    {
      key: "document.extract-text",
      effect: "writer",
      retry: "forbidden",
      replay: "idempotent",
      artifactRoles: ["normalized_text"],
    },
  );
  state.operations.push(extraction);
  if (
    extraction &&
    extraction.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    isUnknownWriter(extraction)
  )
    return {
      terminal: blocked(
        state,
        "extract-text",
        "document.extract-text",
        extraction,
      ),
    };
  if (
    !strictExtractReceipt(extraction) ||
    !exactOperation(extraction, {
      version: OPERATION_RECEIPT_VERSION.extract,
      key: "document.extract-text",
      effect: "writer",
      input,
      output,
      role: "normalized_text",
    })
  )
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
  if (
    extraction.status !== "succeeded" ||
    extraction.exit !== 0 ||
    extraction.exists !== true
  )
    return {
      failure:
        extraction.failure ||
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
  const assessment = await runtime.runOperation(
    readabilityOperationPrompt(state.materialKey, output, extraction),
    {
      phase: "Paper",
      agentType: "general-purpose",
      label: `paper.assess:${state.slug}`,
      schema: READABILITY_SCHEMA,
    },
    {
      key: "document.assess-readability",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: ["normalized_text"],
    },
  );
  state.operations.push(assessment);
  if (
    !strictReadabilityReceipt(assessment) ||
    !exactOperation(assessment, {
      version: OPERATION_RECEIPT_VERSION.assess,
      key: "document.assess-readability",
      effect: "readonly",
      input: output,
      role: "normalized_text",
    })
  )
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

async function analyse(
  runtime,
  state,
  meta,
  input,
  mode = "create",
  diagnostics = [],
) {
  const receipt = await runtime.runOperation(
    paperAnalyseOperationPrompt(
      state.slug,
      meta,
      input,
      mode,
      diagnostics,
    ),
    {
      phase: "Paper",
      agentType: "quasi:analyse-agent",
      label: `paper.analyse:${state.slug}`,
      schema: PAPER_ANALYSE_SCHEMA,
    },
    {
      key: "paper.analyse",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
    },
  );
  state.operations.push(receipt);
  if (
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    isUnknownWriter(receipt)
  )
    return {
      terminal: blocked(
        state,
        "analyse",
        "paper.analyse",
        receipt,
      ),
    };
  if (!strictAnalyseReceipt(receipt, mode))
    return {
      terminal: mismatchBlocked(
        state,
        "analyse",
        "paper.analyse",
      ),
    };
  if (
    !exactOperation(receipt, {
      version: OPERATION_RECEIPT_VERSION.analyse,
      key: "paper.analyse",
      effect: "writer",
      input,
      output: state.canonical,
      role: "canonical",
    })
  )
    return {
      terminal: mismatchBlocked(
        state,
        "analyse",
        "paper.analyse",
      ),
    };
  if (
    mode === "create" &&
    receipt.status === "blocked" &&
    receipt.action === "reconciled" &&
    receipt.failure.code === "output_exists_requires_reconcile"
  )
    return { reconcile: true };
  if (isUnknownWriter(receipt))
    return {
      terminal: blocked(
        state,
        "analyse",
        "paper.analyse",
        receipt,
      ),
    };
  if (receipt.status !== "succeeded")
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
  const receipt = await runtime.runOperation(
    paperAuditPrompt(state.slug, pass),
    {
      phase: "Paper",
      agentType: "quasi:audit-agent",
      label: `paper.audit:${state.slug}`,
      schema: PAPER_AUDIT_SCHEMA,
    },
    {
      key: "paper.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
    },
  );
  if (
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    isUnknownWriter(receipt)
  ) {
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
  if (
    !strictAuditReceipt(receipt) ||
    receipt.target_path !== state.canonical
  ) {
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
  if (receipt.status === "error")
    return {
      terminal: result(
        state,
        "audit_escalated",
        "audit",
        {},
        operation.failure,
      ),
    };
  const escalated = Array.isArray(receipt && receipt.escalated)
    ? receipt.escalated
    : [];
  const clean =
    receipt.status === "clean" &&
    escalated.length === 0 &&
    receipt.remaining_violations === 0;
  return { receipt, escalated, clean };
}

async function processValidatedPaper(runtime, slug, meta) {
  const { log, phase, runOperation } = runtime;
  phase("Paper");
  const state = createPaperState(slug);

  const download = await runOperation(
    paperAcquirePrompt(slug, meta),
    {
      phase: "Paper",
      agentType: "quasi:download-agent",
      label: `paper.acquire:${slug}`,
      schema: PAPER_ACQUIRE_SCHEMA,
    },
    {
      key: "paper.acquire",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["source"],
    },
  );
  if (
    download &&
    download.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    isUnknownWriter(download)
  ) {
    state.operations.push(download);
    return blocked(
      state,
      "download",
      "paper.acquire",
      download,
    );
  }
  if (
    !strictPaperDownloadReceipt(
      download,
      slug,
      state.source,
    )
  ) {
    state.operations.push(download);
    return mismatchBlocked(
      state,
      "download",
      "paper.acquire",
    );
  }
  const item =
    download.per_item[0];
  const downloadReceipt = downloadOperation(item, state.source);
  state.operations.push(downloadReceipt);
  if (item.status === "blocked")
    return blocked(
      state,
      "download",
      "paper.acquire",
      downloadReceipt,
    );
  if (item.status === "download_failed") {
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
    const ocr = await runOperation(
      documentOcrOperationPrompt(
        state.materialKey,
        state.source,
        state.ocrSource,
      ),
      {
        phase: "Paper",
        agentType: "general-purpose",
        label: `paper.ocr:${slug}`,
        schema: DOCUMENT_OCR_SCHEMA,
      },
      {
        key: "document.ocr",
        effect: "writer",
        retry: "forbidden",
        replay: "blocked",
        artifactRoles: ["recovery_source"],
      },
    );
    state.operations.push(ocr);
    const ocrExact = exactOperation(ocr, {
        version: OPERATION_RECEIPT_VERSION.ocr,
        key: "document.ocr",
        effect: "writer",
        input: state.source,
        output: state.ocrSource,
        role: "recovery_source",
      });
    if (
      ocr &&
      ocr.schema_version ===
        "quasi.operation.runtime.receipt/0.1" &&
      isUnknownWriter(ocr)
    )
      return blocked(state, "ocr", "document.ocr", ocr);
    if (!ocrExact || !strictOcrReceipt(ocr))
      return mismatchBlocked(
        state,
        "ocr",
        "document.ocr",
      );
    const existingRecovery =
      ocr.status === "blocked" &&
      ocr.exit === 0 &&
      ocr.exists === true &&
      ocr.size > 0 &&
      ocr.failure.code === "output_exists_requires_reconcile";
    if (isUnknownWriter(ocr) && !existingRecovery)
      return blocked(state, "ocr", "document.ocr", ocr);
    if (
      !existingRecovery &&
      (ocr.status !== "succeeded" ||
        ocr.exit !== 0 ||
        ocr.exists !== true ||
        ocr.size <= 0)
    )
      return result(
        state,
        "ocr_failed",
        "ocr",
        {},
        ocr.failure ||
          operationFailure("paper.ocr_failed", "document.ocr"),
      );
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
