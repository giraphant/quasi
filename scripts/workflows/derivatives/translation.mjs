import {
  TRANSLATION_RECONCILE_SCHEMA,
  TRANSLATION_REOCR_SCHEMA,
  TRANSLATION_RUN_SCHEMA,
  translationReconcilePrompt,
  translationReocrPrompt,
  translationRunPrompt,
} from "../operations/translate.mjs";

const RECEIPT_VERSION =
  "quasi.derivative.translation.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const HASH = /^[a-f0-9]{64}$/;
const LANGUAGE =
  /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const BACKENDS = new Set(["immersive", "pdf2zh"]);
const SIGNALS = new Set([
  "missing",
  "reused",
  "configuration_required",
  "source_selection",
  null,
]);
const RECONCILE_KEYS = [
  "schema_version",
  "key",
  "effect",
  "status",
  "attempt",
  "generation_attempt",
  "derivative_key",
  "slug",
  "mode",
  "requested_source",
  "source_path",
  "output_path",
  "manifest_path",
  "target_language",
  "toc_json",
  "toc_page_side",
  "backend",
  "signal",
  "request_fingerprint",
  "source_sha256",
  "source_size",
  "source_pages",
  "output_sha256",
  "manifest_sha256",
  "output_size",
  "output_pages",
  "toc_entries",
  "coverage",
  "candidates",
  "candidates_fingerprint",
  "gate",
  "failure",
];
const RUN_KEYS = [
  "schema_version",
  "key",
  "effect",
  "status",
  "attempt",
  "derivative_key",
  "slug",
  "backend",
  "input_path",
  "output_path",
  "manifest_path",
  "target_language",
  "toc_json",
  "toc_page_side",
  "request_fingerprint",
  "source_sha256",
  "output_sha256",
  "manifest_sha256",
  "output_size",
  "source_pages",
  "output_pages",
  "toc_entries",
  "coverage",
  "disposition",
  "canonical_committed",
  "previous_manifest_preserved",
  "gate",
  "failure",
];
const REOCR_KEYS = [
  "status",
  "input",
  "output",
  "exit",
  "exists",
  "size",
  "failure",
];

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

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const validHash = (value) =>
  typeof value === "string" && HASH.test(value);

function validRelativePath(value, suffix) {
  if (
    !validText(value, 1, 2048) ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.split("/").includes("..") ||
    !value.toLowerCase().endsWith(suffix)
  )
    return false;
  return (
    value.startsWith("sources/") ||
    value.startsWith("processing/translations/") ||
    value.startsWith(".quasi/")
  );
}

function normalizeLanguage(value) {
  if (!validText(value, 2, 35) || !LANGUAGE.test(value))
    return null;
  const parts = value.split("-");
  return parts
    .map((part, index) => {
      if (index === 0) return part.toLowerCase();
      if (part.length === 2) return part.toUpperCase();
      return part.toLowerCase();
    })
    .join("-");
}

function sourceRoles(slug, targetLanguage) {
  const langTag = targetLanguage.toLowerCase();
  return {
    canonical: `sources/${slug}.pdf`,
    paperOcr: `processing/papers/${slug}/ocr.pdf`,
    derivativeRecovery:
      `processing/translations/${slug}-${langTag}-reocr.pdf`,
  };
}

function validRequestedSource(path, slug, targetLanguage) {
  const roles = sourceRoles(slug, targetLanguage);
  return [
    roles.canonical,
    roles.paperOcr,
    roles.derivativeRecovery,
  ].includes(path);
}

function validSelectableSource(path, slug, targetLanguage) {
  const roles = sourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr].includes(path);
}

function validateIdentity(slug, rawMeta) {
  if (typeof slug !== "string" || !SLUG.test(slug))
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "translation slug is not canonical ASCII kebab",
    };
  if (
    !rawMeta ||
    typeof rawMeta !== "object" ||
    Array.isArray(rawMeta)
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "translation metadata must be an object",
    };
  const targetLanguage = normalizeLanguage(
    rawMeta.target_language || "zh-CN",
  );
  if (!targetLanguage)
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "target_language is not a bounded language tag",
    };
  let requestedSource =
    rawMeta.source_file === undefined ||
    rawMeta.source_file === null
      ? null
      : rawMeta.source_file;
  if (
    requestedSource !== null &&
    !validRequestedSource(
      requestedSource,
      slug,
      targetLanguage,
    )
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message:
        "source_file must be an exact project-relative PDF path",
    };
  const sourceDecision =
    rawMeta.source_decision === undefined ||
    rawMeta.source_decision === null
      ? null
      : rawMeta.source_decision;
  if (
    sourceDecision !== null &&
    (!exactKeys(sourceDecision, [
      "path",
      "sha256",
      "candidates_fingerprint",
    ]) ||
      !validSelectableSource(
        sourceDecision.path,
        slug,
        targetLanguage,
      ) ||
      !validHash(sourceDecision.sha256) ||
      !validHash(sourceDecision.candidates_fingerprint) ||
      (requestedSource !== null &&
        requestedSource !== sourceDecision.path))
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message:
        "source_decision must be exact closed source evidence",
    };
  if (sourceDecision !== null)
    requestedSource = sourceDecision.path;
  const tocJson =
    rawMeta.toc_json === undefined ||
    rawMeta.toc_json === null
      ? null
      : rawMeta.toc_json;
  if (
    tocJson !== null &&
    !validRelativePath(tocJson, ".json")
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "toc_json must be an exact project-relative JSON path",
    };
  const tocPageSide =
    rawMeta.toc_page_side === undefined
      ? "original"
      : rawMeta.toc_page_side;
  if (!["original", "translated"].includes(tocPageSide))
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "toc_page_side must be original or translated",
    };
  const meta = {
    requestedSource,
    sourceDecision:
      sourceDecision === null
        ? null
        : {
            path: sourceDecision.path,
            sha256: sourceDecision.sha256,
            candidates_fingerprint:
              sourceDecision.candidates_fingerprint,
          },
    targetLanguage,
    tocJson,
    tocPageSide,
  };
  return {
    ok: true,
    meta,
    fingerprint: JSON.stringify(meta),
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
  message,
});

function validFailure(failure, operationKey, outcome = null) {
  return !!(
    exactKeys(failure, [
      "code",
      "operation_key",
      "outcome",
      "retryable",
      "message",
    ]) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    ["known", "unknown"].includes(failure.outcome) &&
    (outcome === null || failure.outcome === outcome) &&
    failure.retryable === false &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

function validCoverage(value) {
  if (
    !exactKeys(value, [
      "signal",
      "median",
      "measured_pages",
      "minimum_median",
      "weakest",
      "detail",
    ]) ||
    ![
      "pending",
      "not_applicable",
      "insufficient_evidence",
      "pass",
      "under_translated",
    ].includes(value.signal) ||
    !Number.isInteger(value.measured_pages) ||
    value.measured_pages < 0 ||
    (value.minimum_median !== null &&
      (typeof value.minimum_median !== "number" ||
        value.minimum_median < 0)) ||
    (value.median !== null &&
      (typeof value.median !== "number" ||
        value.median < 0)) ||
    !Array.isArray(value.weakest) ||
    value.weakest.length > 32 ||
    value.weakest.some(
      (row) =>
        !exactKeys(row, ["page", "ratio"]) ||
        !Number.isInteger(row.page) ||
        row.page < 1 ||
        typeof row.ratio !== "number" ||
        row.ratio < 0,
    ) ||
    (value.detail !== null &&
      !validText(value.detail, 1, 4000))
  )
    return false;
  if (value.signal === "pass")
    return (
      typeof value.median === "number" &&
      typeof value.minimum_median === "number" &&
      value.median >= value.minimum_median
    );
  if (value.signal === "under_translated")
    return (
      typeof value.median === "number" &&
      typeof value.minimum_median === "number" &&
      value.median < value.minimum_median
    );
  if (value.signal === "pending")
    return (
      value.median === null &&
      value.measured_pages === 0 &&
      value.minimum_median === null
    );
  return (
    value.median === null &&
    typeof value.minimum_median === "number"
  );
}

function sameCoverage(left, right) {
  return !!(
    validCoverage(left) &&
    validCoverage(right) &&
    left.signal === right.signal &&
    left.median === right.median &&
    left.measured_pages === right.measured_pages &&
    left.minimum_median === right.minimum_median &&
    left.detail === right.detail &&
    left.weakest.length === right.weakest.length &&
    left.weakest.every(
      (row, index) =>
        row.page === right.weakest[index].page &&
        row.ratio === right.weakest[index].ratio,
    )
  );
}

function validCandidate(value, state) {
  return !!(
    exactKeys(value, ["path", "sha256", "size", "pages"]) &&
    validSelectableSource(
      value.path,
      state.slug,
      state.targetLanguage,
    ) &&
    validHash(value.sha256) &&
    Number.isInteger(value.size) &&
    value.size > 0 &&
    Number.isInteger(value.pages) &&
    value.pages > 0
  );
}

function validGate(value, kind = null, state = null) {
  if (
    !exactKeys(value, [
      "kind",
      "missing_fields",
      "candidates",
      "candidates_fingerprint",
    ]) ||
    !["source_selection", "configuration_required"].includes(
      value.kind,
    ) ||
    (kind !== null && value.kind !== kind) ||
    !Array.isArray(value.missing_fields) ||
    value.missing_fields.length > 8 ||
    value.missing_fields.some(
      (field) => !validText(field, 1, 100),
    ) ||
    !Array.isArray(value.candidates) ||
    value.candidates.length > 32 ||
    (state !== null &&
      value.candidates.some(
        (candidate) => !validCandidate(candidate, state),
      )) ||
    (value.candidates_fingerprint !== null &&
      !validHash(value.candidates_fingerprint))
  )
    return false;
  if (value.kind === "configuration_required")
    return (
      value.missing_fields.length > 0 &&
      value.candidates.length === 0 &&
      value.candidates_fingerprint === null
    );
  return (
    value.missing_fields.length === 0 &&
    value.candidates.length > 1 &&
    new Set(value.candidates.map((row) => row.path)).size ===
      value.candidates.length &&
    validHash(value.candidates_fingerprint)
  );
}

function createState(slug, meta) {
  const langTag = meta.targetLanguage.toLowerCase();
  return {
    slug,
    translationKey: `translation:paper:${slug}:${meta.targetLanguage}`,
    targetLanguage: meta.targetLanguage,
    requestedSource: meta.requestedSource,
    sourceDecision: meta.sourceDecision,
    sourcePath: null,
    activeInput: null,
    tocJson: meta.tocJson,
    tocPageSide: meta.tocPageSide,
    output: `processing/translations/${slug}-${langTag}.pdf`,
    manifest: `processing/translations/${slug}-${langTag}.manifest.json`,
    recoverySource:
      `processing/translations/${slug}-${langTag}-reocr.pdf`,
    backend: null,
    requestFingerprint: null,
    sourceSha256: null,
    sourceSize: 0,
    sourcePages: 0,
    activeInputSha256: null,
    artifacts: [],
    operations: [],
    validation: null,
    gate: null,
    failure: null,
    disposition: null,
    recovered: false,
    pendingReocr: null,
    expectedGeneration: null,
    budgets: {
      reocr: { limit: 1, used: 0 },
      translation_runs: { limit: 2, used: 0 },
    },
  };
}

function artifact(
  role,
  path,
  producer,
  sha256,
  size,
  pages,
) {
  return {
    role,
    path,
    producer,
    sha256,
    size,
    pages,
  };
}

function setSourceArtifact(state) {
  state.artifacts = state.artifacts.filter(
    (row) => row.role !== "source",
  );
  state.artifacts.push(
    artifact(
      "source",
      state.sourcePath,
      "translation.reconcile",
      state.sourceSha256,
      state.sourceSize,
      state.sourcePages,
    ),
  );
}

function setFinalArtifacts(state, receipt, producer) {
  state.artifacts = state.artifacts.filter(
    (row) =>
      row.role !== "translated_pdf" &&
      row.role !== "translation_manifest",
  );
  state.artifacts.push(
    artifact(
      "translated_pdf",
      state.output,
      producer,
      receipt.output_sha256,
      receipt.output_size,
      receipt.output_pages,
    ),
    artifact(
      "translation_manifest",
      state.manifest,
      producer,
      receipt.manifest_sha256,
      null,
      null,
    ),
  );
}

function receipt(state, status, stage, failure = null) {
  return {
    schema_version: RECEIPT_VERSION,
    derivative_key: state.translationKey,
    kind: "translate",
    id: state.slug,
    slug: state.slug,
    target_language: state.targetLanguage,
    backend: state.backend,
    status,
    disposition:
      status === "complete" ? state.disposition : null,
    stage,
    source:
      state.sourcePath === null
        ? null
        : {
            path: state.sourcePath,
            sha256: state.sourceSha256,
            size: state.sourceSize,
            pages: state.sourcePages,
          },
    artifacts: state.artifacts,
    operations: state.operations,
    validation: state.validation,
    budgets: state.budgets,
    gate: state.gate,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "translation.reconcile" }
        : null,
  };
}

function legacyStatus(status, gate) {
  if (status === "complete") return "success";
  if (status === "failed") return "error";
  if (gate && gate.kind === "configuration_required")
    return "needs_auth";
  if (gate && gate.kind === "source_selection")
    return "needs_source_selection";
  return "blocked";
}

function terminal(state, status, stage, failure = null) {
  const translationReceipt = receipt(
    state,
    status,
    stage,
    failure,
  );
  return {
    slug: state.slug,
    status: legacyStatus(status, state.gate),
    translation_status: legacyStatus(status, state.gate),
    final_pdf:
      status === "complete" ? state.output : null,
    toc_entries:
      status === "complete" &&
      state.validation
        ? state.validation.toc_entries
        : null,
    translation_receipt: translationReceipt,
  };
}

function rejectedResult(slug, validation, conflict = false) {
  const canonical =
    typeof slug === "string" && SLUG.test(slug);
  const state = createState(
    canonical ? slug : "invalid",
    {
      requestedSource: null,
      sourceDecision: null,
      targetLanguage: "zh-CN",
      tocJson: null,
      tocPageSide: "original",
    },
  );
  if (!canonical) {
    state.slug =
      typeof slug === "string" ? slug : null;
    state.translationKey = null;
  }
  const failure = operationFailure(
    conflict
      ? "translation.identity_conflict"
      : validation.code,
    "translation.identity",
    "known",
    validation.message,
  );
  const result = terminal(
    state,
    conflict ? "blocked" : "failed",
    "identity",
    failure,
  );
  if (conflict)
    result.translation_receipt.resume = null;
  return result;
}

function runtimeUnknown(receipt, operationKey) {
  return !!(
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    receipt.key === operationKey &&
    receipt.status === "blocked" &&
    receipt.failure &&
    receipt.failure.outcome === "unknown"
  );
}

function writerMismatch(state, stage, operationKey) {
  return terminal(
    state,
    "blocked",
    stage,
    operationFailure(
      "translation.writer_receipt_mismatch",
      operationKey,
      "unknown",
      "writer receipt did not prove the exact translation contract",
    ),
  );
}

function reconcileMismatch(state, mode) {
  return terminal(
    state,
    "blocked",
    mode === "initial" ? "reconcile" : "validation",
    operationFailure(
      "translation.reconcile_receipt_invalid",
      "translation.reconcile",
      "unknown",
      "reconcile receipt did not prove the exact generation",
    ),
  );
}

function commonReconcileExact(receipt, state, mode) {
  const requestedSource =
    mode === "initial" ? state.requestedSource : state.activeInput;
  return !!(
    exactKeys(receipt, RECONCILE_KEYS) &&
    receipt.schema_version ===
      "quasi.operation.translation.reconcile.receipt/0.1" &&
    receipt.key === "translation.reconcile" &&
    receipt.effect === "readonly" &&
    receipt.attempt === 1 &&
    Number.isInteger(receipt.generation_attempt) &&
    receipt.generation_attempt >= 0 &&
    receipt.generation_attempt <= 2 &&
    receipt.derivative_key === state.translationKey &&
    receipt.slug === state.slug &&
    ["initial", "recovery", "final"].includes(receipt.mode) &&
    receipt.mode === mode &&
    receipt.requested_source === requestedSource &&
    receipt.output_path === state.output &&
    receipt.manifest_path === state.manifest &&
    receipt.target_language === state.targetLanguage &&
    receipt.toc_json === state.tocJson &&
    receipt.toc_page_side === state.tocPageSide &&
    BACKENDS.has(receipt.backend) &&
    SIGNALS.has(receipt.signal) &&
    Number.isInteger(receipt.source_size) &&
    receipt.source_size >= 0 &&
    Number.isInteger(receipt.source_pages) &&
    receipt.source_pages >= 0 &&
    Number.isInteger(receipt.output_size) &&
    receipt.output_size >= 0 &&
    Number.isInteger(receipt.output_pages) &&
    receipt.output_pages >= 0 &&
    Number.isInteger(receipt.toc_entries) &&
    receipt.toc_entries >= 0 &&
    Array.isArray(receipt.candidates) &&
    receipt.candidates.length <= 32 &&
    (receipt.candidates_fingerprint === null ||
      validHash(receipt.candidates_fingerprint))
  );
}

function strictReconcileReceipt(receipt, state, mode) {
  if (!commonReconcileExact(receipt, state, mode))
    return false;
  if (
    mode !== "initial" &&
    (receipt.backend !== state.backend ||
      receipt.source_path !== state.activeInput)
  )
    return false;
  if (
    mode === "final" &&
    (receipt.request_fingerprint !== state.requestFingerprint ||
      state.expectedGeneration === null ||
      receipt.output_sha256 !==
        state.expectedGeneration.outputSha256 ||
      receipt.manifest_sha256 !==
        state.expectedGeneration.manifestSha256 ||
      receipt.output_size !==
        state.expectedGeneration.outputSize ||
      receipt.source_pages !==
        state.expectedGeneration.sourcePages ||
      receipt.output_pages !==
        state.expectedGeneration.outputPages ||
      receipt.toc_entries !==
        state.expectedGeneration.tocEntries ||
      !sameCoverage(
        receipt.coverage,
        state.expectedGeneration.coverage,
      ))
  )
    return false;
  if (receipt.signal === "missing")
    return !!(
      ["initial", "recovery"].includes(mode) &&
      receipt.generation_attempt ===
        (mode === "initial" ? 1 : 2) &&
      receipt.status === "succeeded" &&
      validRequestedSource(
        receipt.source_path,
        state.slug,
        state.targetLanguage,
      ) &&
      (mode !== "initial" ||
        state.requestedSource !== null ||
        validSelectableSource(
          receipt.source_path,
          state.slug,
          state.targetLanguage,
        )) &&
      (mode === "initial"
        ? state.requestedSource === null ||
          receipt.source_path === state.requestedSource
        : receipt.source_path === state.activeInput &&
          (state.activeInputSha256 === null ||
            receipt.source_sha256 === state.activeInputSha256) &&
          receipt.request_fingerprint !== state.requestFingerprint) &&
      validHash(receipt.request_fingerprint) &&
      validHash(receipt.source_sha256) &&
      receipt.source_size > 0 &&
      receipt.source_pages > 0 &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.toc_entries === 0 &&
      receipt.coverage === null &&
      receipt.candidates.length === 0 &&
      (state.sourceDecision === null
        ? receipt.candidates_fingerprint === null
        : receipt.candidates_fingerprint ===
            state.sourceDecision.candidates_fingerprint &&
          receipt.source_sha256 ===
            state.sourceDecision.sha256) &&
      receipt.gate === null &&
      receipt.failure === null
    );
  if (receipt.signal === "reused")
    return !!(
      receipt.status === "succeeded" &&
      [1, 2].includes(receipt.generation_attempt) &&
      (mode !== "final" ||
        receipt.generation_attempt ===
          state.expectedGeneration.attempt) &&
      validRequestedSource(
        receipt.source_path,
        state.slug,
        state.targetLanguage,
      ) &&
      (requestedSourceMatches(receipt, state, mode)) &&
      validHash(receipt.request_fingerprint) &&
      validHash(receipt.source_sha256) &&
      receipt.source_size > 0 &&
      receipt.source_pages > 0 &&
      validHash(receipt.output_sha256) &&
      validHash(receipt.manifest_sha256) &&
      receipt.output_size > 0 &&
      receipt.output_pages === receipt.source_pages * 2 &&
      validCoverage(receipt.coverage) &&
      ["pass", "not_applicable", "insufficient_evidence"].includes(
        receipt.coverage.signal,
      ) &&
      receipt.candidates.length === 0 &&
      (mode === "initial" && state.sourceDecision !== null
        ? receipt.candidates_fingerprint ===
            state.sourceDecision.candidates_fingerprint &&
          receipt.source_sha256 ===
            state.sourceDecision.sha256
        : receipt.candidates_fingerprint === null) &&
      receipt.gate === null &&
      receipt.failure === null
    );
  if (receipt.signal === "configuration_required")
    return !!(
      mode === "initial" &&
      receipt.generation_attempt === 0 &&
      receipt.status === "blocked" &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.coverage === null &&
      receipt.candidates.length === 0 &&
      receipt.candidates_fingerprint === null &&
      validGate(
        receipt.gate,
        "configuration_required",
        state,
      ) &&
      validFailure(
        receipt.failure,
        "translation.reconcile",
        "known",
      ) &&
      receipt.failure.code ===
        "translation.configuration_required"
    );
  if (receipt.signal === "source_selection")
    return !!(
      mode === "initial" &&
      receipt.generation_attempt === 0 &&
      state.requestedSource === null &&
      receipt.status === "blocked" &&
      receipt.source_path === null &&
      receipt.request_fingerprint === null &&
      receipt.source_sha256 === null &&
      receipt.source_size === 0 &&
      receipt.source_pages === 0 &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.coverage === null &&
      receipt.candidates.length > 1 &&
      new Set(receipt.candidates.map((row) => row.path)).size ===
        receipt.candidates.length &&
      receipt.candidates.every(
        (candidate) => validCandidate(candidate, state),
      ) &&
      validHash(receipt.candidates_fingerprint) &&
      validGate(
        receipt.gate,
        "source_selection",
        state,
      ) &&
      receipt.gate.candidates.length ===
        receipt.candidates.length &&
      receipt.gate.candidates.every(
        (candidate, index) =>
          candidate.path === receipt.candidates[index].path &&
          candidate.sha256 === receipt.candidates[index].sha256 &&
          candidate.size === receipt.candidates[index].size &&
          candidate.pages === receipt.candidates[index].pages,
      ) &&
      receipt.gate.candidates_fingerprint ===
        receipt.candidates_fingerprint &&
      validFailure(
        receipt.failure,
        "translation.reconcile",
        "known",
      ) &&
      receipt.failure.code ===
        "translation.source_selection_required"
    );
  if (receipt.signal === null)
    return !!(
      mode === "initial" &&
      state.requestedSource === null &&
      receipt.generation_attempt === 0 &&
      receipt.status === "failed" &&
      receipt.source_path === null &&
      receipt.request_fingerprint === null &&
      receipt.source_sha256 === null &&
      receipt.source_size === 0 &&
      receipt.source_pages === 0 &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.toc_entries === 0 &&
      receipt.coverage === null &&
      receipt.candidates.length === 0 &&
      receipt.candidates_fingerprint === null &&
      receipt.gate === null &&
      validFailure(
        receipt.failure,
        "translation.reconcile",
        "known",
      ) &&
      receipt.failure.code === "translation.source_missing"
    );
  return false;
}

function requestedSourceMatches(receipt, state, mode) {
  const expected =
    mode === "initial" ? state.requestedSource : state.activeInput;
  return (
    expected === null ||
    receipt.source_path === expected
  );
}

function adoptReconcile(state, receipt) {
  if (state.sourcePath === null) {
    state.sourcePath = receipt.source_path;
    state.sourceSha256 = receipt.source_sha256;
    state.sourceSize = receipt.source_size;
    state.sourcePages = receipt.source_pages;
    setSourceArtifact(state);
  }
  state.backend = receipt.backend;
  state.requestFingerprint = receipt.request_fingerprint;
  state.activeInput = receipt.source_path;
  state.activeInputSha256 = receipt.source_sha256;
}

function adoptValidation(state, receipt, producer) {
  state.validation = {
    status: "clean",
    backend: receipt.backend,
    input_path: receipt.source_path,
    input_sha256: receipt.source_sha256,
    output_path: state.output,
    output_sha256: receipt.output_sha256,
    manifest_path: state.manifest,
    manifest_sha256: receipt.manifest_sha256,
    source_pages: receipt.source_pages,
    output_pages: receipt.output_pages,
    toc_entries: receipt.toc_entries,
    coverage: receipt.coverage,
  };
  setFinalArtifacts(state, receipt, producer);
}

function rawReocrFailure(value) {
  return !!(
    exactKeys(value, ["code", "message"]) &&
    validText(value.code, 1, 100) &&
    validText(value.message, 1, 1000)
  );
}

function reocrEnvelope(
  state,
  raw,
  status,
  sha256,
  failure,
) {
  return {
    schema_version:
      "quasi.operation.translation.reocr.receipt/0.1",
    key: "translation.reocr",
    effect: "writer",
    status,
    attempt: 1,
    derivative_key: state.translationKey,
    input_path: state.sourcePath,
    output_path: state.recoverySource,
    artifact_roles: ["recovery_source"],
    exit: Number.isInteger(raw?.exit) ? raw.exit : null,
    exists:
      typeof raw?.exists === "boolean"
        ? raw.exists
        : false,
    size:
      Number.isInteger(raw?.size) && raw.size >= 0
        ? raw.size
        : 0,
    sha256,
    action: status === "succeeded" ? "created" : null,
    failure,
  };
}

function recordPendingReocr(state, reconcileReceipt) {
  if (!state.pendingReocr) return;
  const raw = state.pendingReocr;
  state.operations.push(
    reocrEnvelope(
      state,
      raw,
      "succeeded",
      reconcileReceipt.source_sha256,
      null,
    ),
  );
  state.artifacts.push(
    artifact(
      "recovery_source",
      state.recoverySource,
      "translation.reocr:reconciled",
      reconcileReceipt.source_sha256,
      reconcileReceipt.source_size,
      reconcileReceipt.source_pages,
    ),
  );
  state.pendingReocr = null;
}

async function reconcile(runtime, state, mode) {
  const receipt = await runtime.runOperation(
    translationReconcilePrompt(state, mode),
    {
      phase:
        mode === "initial"
          ? "Recall"
          : mode === "final"
            ? "Audit"
            : "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:reconcile-${mode}`,
      schema: TRANSLATION_RECONCILE_SCHEMA,
    },
    {
      key: "translation.reconcile",
      effect: "readonly",
      retry: "safe",
      replay: "idempotent",
      artifactRoles: [],
      unknownFailureCode:
        "translation.reconcile_outcome_unknown",
    },
  );
  const pendingRecovery =
    mode === "recovery" && state.pendingReocr !== null;
  if (!strictReconcileReceipt(receipt, state, mode)) {
    if (pendingRecovery) {
      state.operations.push(
        reocrEnvelope(
          state,
          state.pendingReocr,
          "blocked",
          null,
          operationFailure(
            "translation.recovery_reconcile_failed",
            "translation.reocr",
            "unknown",
            "layout OCR output could not be reconciled",
          ),
        ),
      );
      state.pendingReocr = null;
    }
    state.operations.push(receipt);
    return { terminal: reconcileMismatch(state, mode) };
  }
  if (pendingRecovery) recordPendingReocr(state, receipt);
  state.operations.push(receipt);
  if (
    receipt.signal === "configuration_required" ||
    receipt.signal === "source_selection"
  ) {
    state.backend = receipt.backend;
    state.gate = receipt.gate;
    return {
      terminal: terminal(
        state,
        "blocked",
        "reconcile",
        receipt.failure,
      ),
    };
  }
  if (receipt.signal === null)
    return {
      terminal: terminal(
        state,
        "failed",
        "reconcile",
        receipt.failure,
      ),
    };
  adoptReconcile(state, receipt);
  if (receipt.signal === "reused") {
    adoptValidation(
      state,
      receipt,
      mode === "initial"
        ? "translation.reconcile:reused"
        : "translation.run",
    );
    return { reused: true };
  }
  return { missing: true };
}

function commonRunExact(receipt, state, inputPath, attempt) {
  return !!(
    exactKeys(receipt, RUN_KEYS) &&
    receipt.schema_version ===
      "quasi.operation.translation.run.receipt/0.1" &&
    receipt.key === "translation.run" &&
    receipt.effect === "writer" &&
    receipt.attempt === attempt &&
    receipt.derivative_key === state.translationKey &&
    receipt.slug === state.slug &&
    receipt.backend === state.backend &&
    receipt.input_path === inputPath &&
    receipt.output_path === state.output &&
    receipt.manifest_path === state.manifest &&
    receipt.target_language === state.targetLanguage &&
    receipt.toc_json === state.tocJson &&
    receipt.toc_page_side === state.tocPageSide &&
    receipt.request_fingerprint ===
      state.requestFingerprint &&
    receipt.source_sha256 ===
      state.activeInputSha256 &&
    Number.isInteger(receipt.output_size) &&
    receipt.output_size >= 0 &&
    Number.isInteger(receipt.source_pages) &&
    receipt.source_pages > 0 &&
    Number.isInteger(receipt.output_pages) &&
    receipt.output_pages >= 0 &&
    Number.isInteger(receipt.toc_entries) &&
    receipt.toc_entries >= 0 &&
    typeof receipt.canonical_committed === "boolean" &&
    typeof receipt.previous_manifest_preserved === "boolean"
  );
}

function strictRunReceipt(receipt, state, inputPath, attempt) {
  if (!commonRunExact(receipt, state, inputPath, attempt))
    return false;
  if (receipt.status === "succeeded")
    return !!(
      ["created", "replaced", "reconciled"].includes(
        receipt.disposition,
      ) &&
      receipt.canonical_committed === true &&
      validHash(receipt.output_sha256) &&
      validHash(receipt.manifest_sha256) &&
      receipt.output_size > 0 &&
      receipt.output_pages === receipt.source_pages * 2 &&
      validCoverage(receipt.coverage) &&
      ["pass", "not_applicable", "insufficient_evidence"].includes(
        receipt.coverage.signal,
      ) &&
      receipt.gate === null &&
      receipt.failure === null
    );
  if (
    receipt.status === "failed" &&
    receipt.failure &&
    receipt.failure.code ===
      "translation.under_translated"
  )
    return !!(
      validFailure(
        receipt.failure,
        "translation.run",
        "known",
      ) &&
      receipt.disposition === null &&
      receipt.canonical_committed === false &&
      receipt.previous_manifest_preserved === true &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      validCoverage(receipt.coverage) &&
      receipt.coverage.signal === "under_translated" &&
      receipt.gate === null
    );
  if (
    receipt.failure &&
    receipt.failure.code ===
      "translation.configuration_required"
  )
    return !!(
      receipt.status === "blocked" &&
      validFailure(
        receipt.failure,
        "translation.run",
        "known",
      ) &&
      receipt.disposition === null &&
      receipt.canonical_committed === false &&
      receipt.previous_manifest_preserved === true &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.coverage === null &&
      validGate(
        receipt.gate,
        "configuration_required",
        state,
      )
    );
  if (receipt.status === "failed")
    return !!(
      validFailure(
        receipt.failure,
        "translation.run",
        "known",
      ) &&
      receipt.disposition === null &&
      receipt.canonical_committed === false &&
      receipt.previous_manifest_preserved === true &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.gate === null
    );
  if (receipt.status === "blocked")
    return !!(
      validFailure(
        receipt.failure,
        "translation.run",
        "unknown",
      ) &&
      receipt.disposition === null &&
      receipt.canonical_committed === false &&
      receipt.output_sha256 === null &&
      receipt.manifest_sha256 === null &&
      receipt.output_size === 0 &&
      receipt.output_pages === 0 &&
      receipt.gate === null
    );
  return false;
}

async function runTranslation(runtime, state, inputPath, attempt) {
  state.budgets.translation_runs.used += 1;
  const receipt = await runtime.runOperation(
    translationRunPrompt(state, inputPath, attempt),
    {
      phase: "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:translate-${attempt}`,
      schema: TRANSLATION_RUN_SCHEMA,
    },
    {
      key: "translation.run",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "translated_pdf",
        "translation_manifest",
      ],
      unknownFailureCode:
        "translation.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (runtimeUnknown(receipt, "translation.run"))
    return {
      terminal: terminal(
        state,
        "blocked",
        "translate",
        operationFailure(
          "translation.writer_outcome_unknown",
          "translation.run",
          "unknown",
          "translation writer outcome is unknown",
        ),
      ),
    };
  if (
    !strictRunReceipt(
      receipt,
      state,
      inputPath,
      attempt,
    )
  )
    return {
      terminal: writerMismatch(
        state,
        "translate",
        "translation.run",
      ),
    };
  if (receipt.status === "blocked") {
    if (receipt.gate) state.gate = receipt.gate;
    return {
      terminal: terminal(
        state,
        "blocked",
        "translate",
        receipt.failure,
      ),
    };
  }
  if (receipt.status === "failed")
    return {
      underTranslated:
        receipt.failure.code ===
        "translation.under_translated",
      terminal:
        receipt.failure.code ===
        "translation.under_translated"
          ? null
          : terminal(
              state,
              "failed",
              "translate",
              receipt.failure,
            ),
      receipt,
    };
  state.disposition =
    receipt.disposition === "reconciled"
      ? "reused"
      : "created";
  state.expectedGeneration = {
    attempt,
    outputSha256: receipt.output_sha256,
    manifestSha256: receipt.manifest_sha256,
    outputSize: receipt.output_size,
    sourcePages: receipt.source_pages,
    outputPages: receipt.output_pages,
    tocEntries: receipt.toc_entries,
    coverage: receipt.coverage,
  };
  return { succeeded: true, receipt };
}

function strictReocrReceipt(receipt, state) {
  if (
    !exactKeys(receipt, REOCR_KEYS) ||
    receipt.input !== state.sourcePath ||
    receipt.output !== state.recoverySource ||
    !Number.isInteger(receipt.exit) ||
    typeof receipt.exists !== "boolean" ||
    !Number.isInteger(receipt.size) ||
    receipt.size < 0
  )
    return false;
  if (receipt.status === "ok")
    return !!(
      receipt.exit === 0 &&
      receipt.exists === true &&
      receipt.size > 0 &&
      receipt.failure === null
    );
  if (receipt.status === "failed")
    return !!(
      receipt.exists === false &&
      receipt.size === 0 &&
      rawReocrFailure(receipt.failure)
    );
  if (receipt.status === "existing")
    return !!(
      receipt.exit === 0 &&
      receipt.exists === true &&
      receipt.size > 0 &&
      receipt.failure === null
    );
  return false;
}

async function reocr(runtime, state) {
  state.budgets.reocr.used = 1;
  const receipt = await runtime.runOperation(
    translationReocrPrompt(state),
    {
      phase: "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:reocr`,
      schema: TRANSLATION_REOCR_SCHEMA,
    },
    {
      key: "translation.reocr",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["recovery_source"],
      unknownFailureCode:
        "translation.writer_outcome_unknown",
    },
  );
  if (runtimeUnknown(receipt, "translation.reocr")) {
    state.operations.push(receipt);
    return {
      terminal: terminal(
        state,
        "blocked",
        "reocr",
        operationFailure(
          "translation.writer_outcome_unknown",
          "translation.reocr",
          "unknown",
          "layout OCR writer outcome is unknown",
        ),
      ),
    };
  }
  if (!strictReocrReceipt(receipt, state)) {
    state.operations.push(
      reocrEnvelope(
        state,
        receipt,
        "blocked",
        null,
        operationFailure(
          "translation.writer_receipt_mismatch",
          "translation.reocr",
          "unknown",
          "raw layout OCR receipt did not prove the exact output",
        ),
      ),
    );
    return {
      terminal: writerMismatch(
        state,
        "reocr",
        "translation.reocr",
      ),
    };
  }
  if (receipt.status === "existing") {
    const failure = operationFailure(
      "translation.recovery_source_exists",
      "translation.reocr",
      "unknown",
      "existing recovery source has no provenance for this request",
    );
    state.operations.push(
      reocrEnvelope(
        state,
        receipt,
        "blocked",
        null,
        failure,
      ),
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "reocr",
        failure,
      ),
    };
  }
  if (receipt.status === "failed") {
    const failure = operationFailure(
      "translation.reocr_failed",
      "translation.reocr",
      "known",
      `${receipt.failure.code}: ${receipt.failure.message}`,
    );
    state.operations.push(
      reocrEnvelope(
        state,
        receipt,
        "failed",
        null,
        failure,
      ),
    );
    return {
      terminal: terminal(
        state,
        "failed",
        "reocr",
        failure,
      ),
    };
  }
  state.activeInput = state.recoverySource;
  state.activeInputSha256 = null;
  state.recovered = true;
  state.pendingReocr = receipt;
  return { succeeded: true };
}

async function processStrict(runtime, state) {
  runtime.phase("Recall");
  const observed = await reconcile(runtime, state, "initial");
  if (observed.terminal) return observed.terminal;
  if (observed.reused) {
    state.disposition = "reused";
    return terminal(state, "complete", "validation");
  }

  let translated = await runTranslation(
    runtime,
    state,
    state.sourcePath,
    1,
  );
  if (translated.terminal) return translated.terminal;
  if (translated.underTranslated) {
    const recovered = await reocr(runtime, state);
    if (recovered.terminal) return recovered.terminal;
    const recoveryObserved = await reconcile(
      runtime,
      state,
      "recovery",
    );
    if (recoveryObserved.terminal)
      return recoveryObserved.terminal;
    if (!recoveryObserved.missing)
      return reconcileMismatch(state, "recovery");
    translated = await runTranslation(
      runtime,
      state,
      state.recoverySource,
      2,
    );
    if (translated.terminal) return translated.terminal;
    if (translated.underTranslated)
      return terminal(
        state,
        "failed",
        "translate",
        operationFailure(
          "translation.recovery_exhausted",
          "translation.run",
          "known",
          "translation remained under-translated after one layout OCR recovery",
        ),
      );
  }

  const verified = await reconcile(runtime, state, "final");
  if (verified.terminal) return verified.terminal;
  if (!verified.reused)
    return reconcileMismatch(state, "final");
  state.disposition = state.recovered
    ? "recovered"
    : state.disposition || "created";
  return terminal(state, "complete", "validation");
}

export function translationDependencyFailure(
  slug,
  rawMeta,
  code,
  message,
) {
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  const state = createState(slug, validation.meta);
  return terminal(
    state,
    "failed",
    "dependency",
    operationFailure(
      code,
      "translation.dependency",
      "known",
      message,
    ),
  );
}

export async function processTranslation(
  runtime,
  slug,
  rawMeta,
) {
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  return runtime.coalesce(
    `translation:paper:${slug}:${validation.meta.targetLanguage}`,
    validation.fingerprint,
    () =>
      processStrict(
        runtime,
        createState(slug, validation.meta),
      ),
    () =>
      rejectedResult(
        slug,
        {
          code: "translation.identity_conflict",
          message:
            "conflicting translation source, language, or TOC for one derivative key",
        },
        true,
      ),
  );
}
