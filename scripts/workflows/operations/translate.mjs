const nullableStringSchema = (properties = {}) => ({
  anyOf: [
    { type: "null" },
    { type: "string", ...properties },
  ],
});

const nullableNumberSchema = (properties = {}) => ({
  anyOf: [
    { type: "null" },
    { type: "number", ...properties },
  ],
});

const failureSchema = (operationKey) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "code",
    "operation_key",
    "outcome",
    "retryable",
    "message",
  ],
  properties: {
    code: { type: "string" },
    operation_key: { const: operationKey },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: false },
    message: nullableStringSchema(),
  },
});

const nullablePdfPathSchema = nullableStringSchema({
  pattern: "\\.pdf$",
});

const nullableJsonPathSchema = nullableStringSchema({
  pattern: "\\.json$",
});

const nullableHashSchema = nullableStringSchema({
  pattern: "^[0-9a-f]{64}$",
});

const coverageSchema = {
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "signal",
    "median",
    "measured_pages",
    "minimum_median",
    "weakest",
    "detail",
  ],
  properties: {
    signal: {
      type: "string",
      enum: [
        "pending",
        "not_applicable",
        "insufficient_evidence",
        "pass",
        "under_translated",
      ],
    },
    median: nullableNumberSchema({ minimum: 0 }),
    measured_pages: { type: "integer", minimum: 0 },
    minimum_median: nullableNumberSchema({
      minimum: 0,
    }),
    weakest: {
      type: "array",
      maxItems: 32,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["page", "ratio"],
        properties: {
          page: { type: "integer", minimum: 1 },
          ratio: { type: "number", minimum: 0 },
        },
      },
    },
    detail: nullableStringSchema(),
  },
};

const candidateSchema = {
  type: "object",
  additionalProperties: false,
  required: ["path", "sha256", "size", "pages"],
  properties: {
    path: { type: "string" },
    sha256: { type: "string" },
    size: { type: "integer", minimum: 1 },
    pages: { type: "integer", minimum: 1 },
  },
};

const gateSchema = {
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "kind",
    "missing_fields",
    "candidates",
    "candidates_fingerprint",
  ],
  properties: {
    kind: {
      type: "string",
      enum: ["source_selection", "configuration_required"],
    },
    missing_fields: {
      type: "array",
      maxItems: 8,
      items: { type: "string" },
    },
    candidates: {
      type: "array",
      maxItems: 32,
      items: candidateSchema,
    },
    candidates_fingerprint: nullableHashSchema,
  },
};

export const TRANSLATION_RECONCILE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.translation.reconcile.receipt/0.1",
    },
    key: { const: "translation.reconcile" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    generation_attempt: {
      type: "integer",
      minimum: 0,
      maximum: 2,
    },
    derivative_key: { type: "string" },
    slug: { type: "string" },
    mode: {
      type: "string",
      enum: ["initial", "recovery", "final"],
    },
    requested_source: nullablePdfPathSchema,
    source_path: nullablePdfPathSchema,
    output_path: { type: "string" },
    manifest_path: { type: "string" },
    target_language: { type: "string" },
    toc_json: nullableJsonPathSchema,
    toc_page_side: {
      type: "string",
      enum: ["original", "translated"],
    },
    backend: {
      type: "string",
      enum: ["immersive", "pdf2zh"],
    },
    signal: {
      anyOf: [
        { type: "null" },
        {
          type: "string",
          enum: [
            "missing",
            "reused",
            "configuration_required",
            "source_selection",
          ],
        },
      ],
    },
    request_fingerprint: nullableHashSchema,
    source_sha256: nullableHashSchema,
    source_size: { type: "integer", minimum: 0 },
    source_pages: { type: "integer", minimum: 0 },
    output_sha256: nullableHashSchema,
    manifest_sha256: nullableHashSchema,
    output_size: { type: "integer", minimum: 0 },
    output_pages: { type: "integer", minimum: 0 },
    toc_entries: { type: "integer", minimum: 0 },
    coverage: coverageSchema,
    candidates: {
      type: "array",
      maxItems: 32,
      items: candidateSchema,
    },
    candidates_fingerprint: nullableHashSchema,
    gate: gateSchema,
    failure: failureSchema("translation.reconcile"),
  },
};

export const TRANSLATION_RUN_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.translation.run.receipt/0.1",
    },
    key: { const: "translation.run" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", minimum: 1, maximum: 2 },
    derivative_key: { type: "string" },
    slug: { type: "string" },
    backend: {
      type: "string",
      enum: ["immersive", "pdf2zh"],
    },
    input_path: { type: "string" },
    output_path: { type: "string" },
    manifest_path: { type: "string" },
    target_language: { type: "string" },
    toc_json: nullableJsonPathSchema,
    toc_page_side: {
      type: "string",
      enum: ["original", "translated"],
    },
    request_fingerprint: { type: "string" },
    source_sha256: { type: "string" },
    output_sha256: nullableHashSchema,
    manifest_sha256: nullableHashSchema,
    output_size: { type: "integer", minimum: 0 },
    source_pages: { type: "integer", minimum: 0 },
    output_pages: { type: "integer", minimum: 0 },
    toc_entries: { type: "integer", minimum: 0 },
    coverage: coverageSchema,
    disposition: {
      anyOf: [
        { type: "null" },
        {
          type: "string",
          enum: ["created", "replaced", "reconciled"],
        },
      ],
    },
    canonical_committed: { type: "boolean" },
    previous_manifest_preserved: { type: "boolean" },
    gate: gateSchema,
    failure: failureSchema("translation.run"),
  },
};

export const TRANSLATION_REOCR_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "status",
    "input",
    "output",
    "exit",
    "exists",
    "size",
    "failure",
  ],
  properties: {
    status: {
      type: "string",
      enum: ["ok", "failed", "existing"],
    },
    input: { type: "string" },
    output: { type: "string" },
    exit: { type: "integer" },
    exists: { type: "boolean" },
    size: { type: "integer", minimum: 0 },
    failure: {
      type: ["object", "null"],
      additionalProperties: false,
      required: ["code", "message"],
      properties: {
        code: { type: "string" },
        message: { type: "string" },
      },
    },
  },
};

const posixSingleQuote = (value) =>
  `'${String(value).replace(/'/g, `'"'"'`)}'`;

function command(tokens) {
  return tokens.map(posixSingleQuote).join(" ");
}

function commonRequest(operation, state) {
  return {
    schema_version: `quasi.operation.${operation}.request/0.1`,
    operation,
    derivative_key: state.translationKey,
    identity: {
      slug: state.slug,
      target_language: state.targetLanguage,
    },
    paths: {
      requested_source: state.requestedSource,
      source: state.sourcePath,
      recovery_source: state.recoverySource,
      output: state.output,
      manifest: state.manifest,
      toc_json: state.tocJson,
    },
    source_decision: state.sourceDecision,
    toc_page_side: state.tocPageSide,
  };
}

export function translationReconcilePrompt(state, mode) {
  const requestedSource =
    mode === "initial" ? state.requestedSource : state.activeInput;
  const tokens = [
    "quasi-translate",
    "observe",
    state.slug,
  ];
  if (requestedSource)
    tokens.push("--source-file", requestedSource);
  if (mode === "initial" && state.sourceDecision)
    tokens.push(
      "--decision-path",
      state.sourceDecision.path,
      "--decision-sha256",
      state.sourceDecision.sha256,
      "--candidates-fingerprint",
      state.sourceDecision.candidates_fingerprint,
    );
  const generationAttempt =
    mode === "recovery"
      ? 2
      : mode === "final" && state.expectedGeneration
        ? state.expectedGeneration.attempt
        : 1;
  tokens.push(
    "--target-language",
    state.targetLanguage,
    "--toc-page-side",
    state.tocPageSide,
  );
  if (state.tocJson) tokens.push("--toc-json", state.tocJson);
  tokens.push(
    "--mode",
    mode,
    "--json",
  );
  const request = {
    ...commonRequest("translation.reconcile", state),
    requested_source: requestedSource,
    mode,
    generation_attempt: generationAttempt,
    backend:
      mode === "initial" ? null : state.backend,
    request_fingerprint:
      mode === "final" ? state.requestFingerprint : null,
    exact_command: command(tokens),
  };
  return JSON.stringify(request, null, 2);
}

export function translationRunPrompt(state, inputPath, attempt) {
  const tokens = [
    "quasi-translate",
    "run",
    state.slug,
    "--source-file",
    inputPath,
    "--target-language",
    state.targetLanguage,
    "--toc-page-side",
    state.tocPageSide,
  ];
  if (state.tocJson) tokens.push("--toc-json", state.tocJson);
  tokens.push(
    "--expected-source-sha256",
    state.activeInputSha256,
    "--attempt",
    String(attempt),
    "--json",
  );
  const request = {
    ...commonRequest("translation.run", state),
    input: {
      role: attempt === 1 ? "source" : "recovery_source",
      path: inputPath,
    },
    attempt,
    frozen_backend: state.backend,
    expected_request_fingerprint: state.requestFingerprint,
    exact_command: command(tokens),
  };
  return JSON.stringify(request, null, 2);
}

export function translationReocrPrompt(state) {
  const exactCommand = command([
    "quasi-extract",
    "ocr",
    state.sourcePath,
    state.recoverySource,
    "eng",
    "--layout",
    "--no-clobber",
    "--json",
  ]);
  const request = {
    ...commonRequest("translation.reocr", state),
    input: { role: "source", path: state.sourcePath },
    output: {
      role: "recovery_source",
      path: state.recoverySource,
    },
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

// --- Receipt contracts -----------------------------------------------------
// Signal-keyed invariants for the translation loop. The graph passes its
// state via context; the runtime enforces schema, echo, then these once.

import { exactKeys, validText } from "../runtime.mjs";

const TRANSLATION_HASH = /^[a-f0-9]{64}$/;
const TRANSLATION_LANGUAGE =
  /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$/;

export const validTranslationHash = (value) =>
  typeof value === "string" && TRANSLATION_HASH.test(value);

export function normalizeLanguage(value) {
  if (
    !validText(value, 2, 35) ||
    !TRANSLATION_LANGUAGE.test(value)
  )
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

export function sourceRoles(slug, targetLanguage) {
  const langTag = targetLanguage.toLowerCase();
  return {
    canonical: `sources/${slug}.pdf`,
    paperOcr: `processing/papers/${slug}/ocr.pdf`,
    derivativeRecovery:
      `processing/translations/${slug}-${langTag}-reocr.pdf`,
  };
}

export function validRequestedSource(path, slug, targetLanguage) {
  const roles = sourceRoles(slug, targetLanguage);
  return [
    roles.canonical,
    roles.paperOcr,
    roles.derivativeRecovery,
  ].includes(path);
}

export function validSelectableSource(path, slug, targetLanguage) {
  const roles = sourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr].includes(path);
}

const validTranslationFailure = (failure, operationKey, outcome) =>
  !!(
    failure &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    failure.outcome === outcome &&
    failure.retryable === false &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );

function validCoverage(value) {
  if (!value || typeof value !== "object") return false;
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
    validSelectableSource(
      value.path,
      state.slug,
      state.targetLanguage,
    ) &&
    validTranslationHash(value.sha256) &&
    value.size > 0 &&
    value.pages > 0
  );
}

function validGate(value, kind, state) {
  if (!value || value.kind !== kind) return false;
  if (
    value.candidates.some(
      (candidate) => !validCandidate(candidate, state),
    )
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
    validTranslationHash(value.candidates_fingerprint)
  );
}

const requestedSourceMatches = (receipt, state, mode) => {
  const expected =
    mode === "initial" ? state.requestedSource : state.activeInput;
  return expected === null || receipt.source_path === expected;
};

const reconcileMissing = (receipt, context) => {
  const { state, mode } = context;
  return !!(
    ["initial", "recovery"].includes(mode) &&
    receipt.generation_attempt ===
      (mode === "initial" ? 1 : 2) &&
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
    validTranslationHash(receipt.request_fingerprint) &&
    validTranslationHash(receipt.source_sha256) &&
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
};

const reconcileReused = (receipt, context) => {
  const { state, mode } = context;
  return !!(
    [1, 2].includes(receipt.generation_attempt) &&
    (mode !== "final" ||
      receipt.generation_attempt ===
        state.expectedGeneration.attempt) &&
    validRequestedSource(
      receipt.source_path,
      state.slug,
      state.targetLanguage,
    ) &&
    requestedSourceMatches(receipt, state, mode) &&
    validTranslationHash(receipt.request_fingerprint) &&
    validTranslationHash(receipt.source_sha256) &&
    receipt.source_size > 0 &&
    receipt.source_pages > 0 &&
    validTranslationHash(receipt.output_sha256) &&
    validTranslationHash(receipt.manifest_sha256) &&
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
};

const reconcileConfigurationGate = (receipt, context) => {
  const { state, mode } = context;
  return !!(
    mode === "initial" &&
    receipt.generation_attempt === 0 &&
    receipt.output_sha256 === null &&
    receipt.manifest_sha256 === null &&
    receipt.output_size === 0 &&
    receipt.output_pages === 0 &&
    receipt.coverage === null &&
    receipt.candidates.length === 0 &&
    receipt.candidates_fingerprint === null &&
    validGate(receipt.gate, "configuration_required", state) &&
    validTranslationFailure(
      receipt.failure,
      "translation.reconcile",
      "known",
    ) &&
    receipt.failure.code ===
      "translation.configuration_required"
  );
};

const reconcileSourceGate = (receipt, context) => {
  const { state, mode } = context;
  return !!(
    mode === "initial" &&
    receipt.generation_attempt === 0 &&
    state.requestedSource === null &&
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
    validTranslationHash(receipt.candidates_fingerprint) &&
    validGate(receipt.gate, "source_selection", state) &&
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
    validTranslationFailure(
      receipt.failure,
      "translation.reconcile",
      "known",
    ) &&
    receipt.failure.code ===
      "translation.source_selection_required"
  );
};

const reconcileSourceMissing = (receipt, context) => {
  const { state, mode } = context;
  return !!(
    mode === "initial" &&
    state.requestedSource === null &&
    receipt.generation_attempt === 0 &&
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
    validTranslationFailure(
      receipt.failure,
      "translation.reconcile",
      "known",
    ) &&
    receipt.failure.code === "translation.source_missing"
  );
};

export const TRANSLATION_RECONCILE_CONTRACT = {
  schema: TRANSLATION_RECONCILE_SCHEMA,
  echo: (receipt, context) => {
    const { state, mode } = context;
    const requestedSource =
      mode === "initial"
        ? state.requestedSource
        : state.activeInput;
    if (
      receipt.derivative_key !== state.translationKey ||
      receipt.slug !== state.slug ||
      receipt.mode !== mode ||
      receipt.requested_source !== requestedSource ||
      receipt.output_path !== state.output ||
      receipt.manifest_path !== state.manifest ||
      receipt.target_language !== state.targetLanguage ||
      receipt.toc_json !== state.tocJson ||
      receipt.toc_page_side !== state.tocPageSide
    )
      return false;
    if (
      mode !== "initial" &&
      (receipt.backend !== state.backend ||
        receipt.source_path !== state.activeInput)
    )
      return false;
    if (
      mode === "final" &&
      (receipt.request_fingerprint !==
        state.requestFingerprint ||
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
    return true;
  },
  statuses: {
    succeeded: (receipt, context) =>
      receipt.signal === "missing"
        ? reconcileMissing(receipt, context)
        : receipt.signal === "reused"
          ? reconcileReused(receipt, context)
          : false,
    blocked: (receipt, context) =>
      receipt.signal === "configuration_required"
        ? reconcileConfigurationGate(receipt, context)
        : receipt.signal === "source_selection"
          ? reconcileSourceGate(receipt, context)
          : false,
    failed: (receipt, context) =>
      receipt.signal === null &&
      reconcileSourceMissing(receipt, context),
  },
};

export const TRANSLATION_RUN_CONTRACT = {
  schema: TRANSLATION_RUN_SCHEMA,
  echo: (receipt, context) => {
    const { state, inputPath, attempt } = context;
    return (
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
      receipt.source_sha256 === state.activeInputSha256 &&
      receipt.source_pages > 0
    );
  },
  statuses: {
    succeeded: (receipt) =>
      !!(
        ["created", "replaced", "reconciled"].includes(
          receipt.disposition,
        ) &&
        receipt.canonical_committed === true &&
        validTranslationHash(receipt.output_sha256) &&
        validTranslationHash(receipt.manifest_sha256) &&
        receipt.output_size > 0 &&
        receipt.output_pages === receipt.source_pages * 2 &&
        validCoverage(receipt.coverage) &&
        ["pass", "not_applicable", "insufficient_evidence"].includes(
          receipt.coverage.signal,
        ) &&
        receipt.gate === null &&
        receipt.failure === null
      ),
    failed: (receipt) => {
      if (
        !validTranslationFailure(
          receipt.failure,
          "translation.run",
          "known",
        ) ||
        receipt.disposition !== null ||
        receipt.canonical_committed !== false ||
        receipt.previous_manifest_preserved !== true ||
        receipt.output_sha256 !== null ||
        receipt.manifest_sha256 !== null ||
        receipt.output_size !== 0 ||
        receipt.output_pages !== 0
      )
        return false;
      if (
        receipt.failure.code === "translation.under_translated"
      )
        return (
          validCoverage(receipt.coverage) &&
          receipt.coverage.signal === "under_translated" &&
          receipt.gate === null
        );
      return receipt.gate === null;
    },
    blocked: (receipt, context) => {
      if (
        receipt.disposition !== null ||
        receipt.canonical_committed !== false ||
        receipt.output_sha256 !== null ||
        receipt.manifest_sha256 !== null ||
        receipt.output_size !== 0 ||
        receipt.output_pages !== 0
      )
        return false;
      if (
        receipt.failure &&
        receipt.failure.code ===
          "translation.configuration_required"
      )
        return (
          validTranslationFailure(
            receipt.failure,
            "translation.run",
            "known",
          ) &&
          receipt.previous_manifest_preserved === true &&
          receipt.coverage === null &&
          validGate(
            receipt.gate,
            "configuration_required",
            context.state,
          )
        );
      return (
        validTranslationFailure(
          receipt.failure,
          "translation.run",
          "unknown",
        ) &&
        receipt.gate === null
      );
    },
  },
};

const rawReocrFailure = (value) =>
  !!(
    value &&
    validText(value.code, 1, 100) &&
    validText(value.message, 1, 1000)
  );

export const TRANSLATION_REOCR_CONTRACT = {
  schema: TRANSLATION_REOCR_SCHEMA,
  echo: (receipt, context) =>
    receipt.input === context.state.sourcePath &&
    receipt.output === context.state.recoverySource,
  statuses: {
    ok: (receipt) =>
      receipt.exit === 0 &&
      receipt.exists === true &&
      receipt.size > 0 &&
      receipt.failure === null,
    failed: (receipt) =>
      receipt.exists === false &&
      receipt.size === 0 &&
      rawReocrFailure(receipt.failure),
    existing: (receipt) =>
      receipt.exit === 0 &&
      receipt.exists === true &&
      receipt.size > 0 &&
      receipt.failure === null,
  },
  edges: { ok: "ok", failed: "failed", existing: "blocked" },
};
