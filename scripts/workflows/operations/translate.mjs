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
  return `Execute exactly one read-only translation.reconcile command-relay operation.
Run exact_command once and return only its one strict JSON receipt. The command may inspect
the exact source, manifest, and translated PDF, but it must not translate, OCR, repair, or
choose a graph edge. Never add --backend: the configured backend owns that choice.
Copy every stdout field and value exactly. A CLI JSON null must remain the literal JSON
null token, never the string "null" or an empty string; this applies in particular to
requested_source, source_path, toc_json, signal, hashes, coverage, fingerprints, gate,
failure, and nested nullable scalar fields.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one translation.run command-relay operation from this JSON request.
Run exact_command once. Do not add or change --backend, retry, OCR, inspect another source,
or choose a graph edge. The CLI owns locking, staging, coverage, ToUnicode repair, and
manifest-last publication. Return only its strict one-object JSON receipt.
Copy every stdout field and value exactly. A CLI JSON null must remain the literal JSON
null token, never the string "null" or an empty string; this applies in particular to
toc_json, hashes, coverage, disposition, gate, failure, and nested nullable scalar fields.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one translation.reocr command-relay operation from this JSON request.
Run exact_command once and copy its one JSON stdout object exactly, without adding operation
envelope fields. A CLI JSON null must remain the literal JSON null token, never the string "null" or an empty string.
Never overwrite an existing
recovery output, retry OCR, translate, or select the next graph edge.
${JSON.stringify(request, null, 2)}`;
}
