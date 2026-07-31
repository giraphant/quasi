import { exactKeys, validText } from "../runtime.mjs";

const operationFailureSchema = (
  operationKey,
  retryable,
  codes = null,
) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "code",
    "operation_key",
    "outcome",
    "retryable",
  ],
  properties: {
    code: codes ? { type: "string", enum: codes } : { type: "string" },
    operation_key: { const: operationKey },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: retryable },
    message: { type: "string" },
  },
});

export const posixSingleQuote = (value) =>
  `'${String(value).split("'").join("'\"'\"'")}'`;

export const TEXT_EXTRACT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.document.extract-text.receipt/0.1",
    },
    key: { const: "document.extract-text" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "normalized_text" },
    },
    exit: { type: "integer" },
    exists: { type: "boolean" },
    size: { type: "integer", minimum: 0 },
    chars: { type: "integer", minimum: 0 },
    non_whitespace_chars: { type: "integer", minimum: 0 },
    pages: { type: "integer", minimum: 0 },
    text_pages: { type: "integer", minimum: 0 },
    failure: operationFailureSchema(
      "document.extract-text",
      false,
    ),
  },
};

export const READABILITY_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.document.assess-readability.receipt/0.1",
    },
    key: { const: "document.assess-readability" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "normalized_text" },
    },
    signal: {
      type: ["string", "null"],
      enum: ["readable", "needs_ocr", "invalid_source", null],
    },
    diagnostics: {
      type: "array",
      items: { type: "string", maxLength: 4000 },
    },
    failure: operationFailureSchema(
      "document.assess-readability",
      true,
    ),
  },
};

export const documentOcrSchema = (failureNamespace) => {
  if (failureNamespace !== "paper" && failureNamespace !== "book")
    throw new Error(`unsupported OCR failure namespace: ${failureNamespace}`);

  return {
    type: "object",
    additionalProperties: false,
    required: [
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
    ],
    properties: {
      schema_version: {
        const: "quasi.operation.document.ocr.receipt/0.1",
      },
      key: { const: "document.ocr" },
      effect: { const: "writer" },
      status: {
        type: "string",
        enum: ["succeeded", "failed", "blocked"],
      },
      attempt: { type: "integer", const: 1 },
      input_path: { type: "string" },
      output_path: { type: "string" },
      artifact_roles: {
        type: "array",
        minItems: 1,
        maxItems: 1,
        items: { const: "recovery_source" },
      },
      exit: { type: "integer" },
      exists: { type: "boolean" },
      size: { type: "integer", minimum: 0 },
      failure: operationFailureSchema("document.ocr", false, [
        `${failureNamespace}.ocr_failed`,
        "output_exists_requires_reconcile",
        `${failureNamespace}.writer_receipt_mismatch`,
      ]),
    },
  };
};

export const DOCUMENT_OCR_SCHEMA = documentOcrSchema("paper");
export const BOOK_DOCUMENT_OCR_SCHEMA = documentOcrSchema("book");

// Composed operation schemas: the status invariants and exact-path echoes ride
// the host-facing schema as anyOf branches and const properties, so the
// StructuredOutput layer bounces an invalid receipt back to the still-running
// agent — the only place a retry is safe. The runtime backstop validates the
// same object, so weaker harnesses converge on the same verdict. Contracts
// keep only what a JSON Schema cannot express.

export const composedSchema = (base, overrides, branches) => ({
  ...base,
  properties: { ...base.properties, ...overrides },
  anyOf: Object.values(branches),
});

const knownFailureBranch = (extra = {}) => ({
  type: "object",
  required: ["outcome"],
  properties: { outcome: { const: "known" }, ...extra },
});

const unknownFailureBranch = (extra = {}) => ({
  type: "object",
  required: ["outcome"],
  properties: { outcome: { const: "unknown" }, ...extra },
});

const TEXT_EXTRACT_BRANCHES = {
  succeeded: {
    properties: {
      status: { const: "succeeded" },
      failure: { type: "null" },
      exit: { const: 0 },
      exists: { const: true },
    },
  },
  failed: {
    properties: {
      status: { const: "failed" },
      failure: knownFailureBranch(),
    },
  },
  blocked: {
    properties: {
      status: { const: "blocked" },
      failure: unknownFailureBranch(),
    },
  },
};

export const textExtractSchema = ({ input, output }) =>
  composedSchema(
    TEXT_EXTRACT_SCHEMA,
    {
      input_path: { const: input },
      output_path: { const: output },
    },
    TEXT_EXTRACT_BRANCHES,
  );

export const TEXT_EXTRACT_CONTRACT = {
  schema: TEXT_EXTRACT_SCHEMA,
};

const READABILITY_BRANCHES = {
  succeeded: {
    properties: {
      status: { const: "succeeded" },
      failure: { type: "null" },
      signal: {
        enum: ["readable", "needs_ocr", "invalid_source"],
      },
    },
  },
  failed: {
    properties: {
      status: { const: "failed" },
      signal: { type: "null" },
      failure: knownFailureBranch(),
    },
  },
  blocked: {
    properties: {
      status: { const: "blocked" },
      signal: { type: "null" },
      failure: unknownFailureBranch(),
    },
  },
};

export const readabilitySchema = ({ input }) =>
  composedSchema(
    READABILITY_SCHEMA,
    { input_path: { const: input } },
    READABILITY_BRANCHES,
  );

export const READABILITY_CONTRACT = {
  schema: READABILITY_SCHEMA,
};

const documentOcrBranches = (failureNamespace) => ({
  succeeded: {
    properties: {
      status: { const: "succeeded" },
      failure: { type: "null" },
      exit: { const: 0 },
      exists: { const: true },
      size: { minimum: 1 },
    },
  },
  failed: {
    properties: {
      status: { const: "failed" },
      failure: knownFailureBranch({
        code: { const: `${failureNamespace}.ocr_failed` },
      }),
    },
  },
  blocked_mismatch: {
    properties: {
      status: { const: "blocked" },
      failure: unknownFailureBranch({
        code: {
          const: `${failureNamespace}.writer_receipt_mismatch`,
        },
      }),
    },
  },
  blocked_reconcile: {
    properties: {
      status: { const: "blocked" },
      exit: { const: 0 },
      exists: { const: true },
      size: { minimum: 1 },
      failure: unknownFailureBranch({
        code: { const: "output_exists_requires_reconcile" },
      }),
    },
  },
});

export const documentOcrOperationSchema = (
  failureNamespace,
  { input, output },
) =>
  composedSchema(
    documentOcrSchema(failureNamespace),
    {
      input_path: { const: input },
      output_path: { const: output },
    },
    documentOcrBranches(failureNamespace),
  );

export const documentOcrContract = (failureNamespace) => ({
  schema: documentOcrSchema(failureNamespace),
  reconcile: (receipt) =>
    receipt.status === "blocked" &&
    receipt.failure.code === "output_exists_requires_reconcile",
});

export const DOCUMENT_OCR_CONTRACT = documentOcrContract("paper");
export const BOOK_DOCUMENT_OCR_CONTRACT = documentOcrContract("book");


const chapterRefSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "slot",
    "title",
    "filename",
    "slug",
    "word_count",
    "start_page",
    "end_page",
  ],
  properties: {
    slot: { type: "string" },
    title: { type: "string" },
    filename: { type: "string" },
    slug: { type: "string" },
    word_count: { type: "integer", minimum: 0 },
    start_page: { type: ["integer", "null"], minimum: 1 },
    end_page: { type: ["integer", "null"], minimum: 1 },
  },
};

const chapterDiagnosticSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "path",
    "kind",
    "reason",
    "slot",
    "title",
    "start_page",
    "end_page",
  ],
  properties: {
    path: { type: "string" },
    kind: { type: "string" },
    reason: { type: "string" },
    slot: { type: ["string", "null"] },
    title: { type: ["string", "null"] },
    start_page: { type: ["integer", "null"], minimum: 1 },
    end_page: { type: ["integer", "null"], minimum: 1 },
  },
};

export const CHAPTER_PLAN_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.chapter.plan.receipt/0.1",
    },
    key: { const: "chapter.plan" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    normalized_path: { type: ["string", "null"] },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "chapter_plan" },
    },
    mode: {
      type: ["string", "null"],
      enum: ["toc", "pattern", "manual", null],
    },
    chapters: {
      type: "array",
      maxItems: 150,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "start", "end"],
        properties: {
          title: { type: "string" },
          start: { type: "integer", minimum: 1 },
          end: { type: "integer", minimum: 1 },
        },
      },
    },
    diagnostics: {
      type: "array",
      items: { type: "string", maxLength: 4000 },
    },
    failure: operationFailureSchema("chapter.plan", true),
  },
};

export const CHAPTER_EXTRACT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.chapter.extract.receipt/0.1",
    },
    key: { const: "chapter.extract" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    output_path: { type: "string" },
    manifest_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 2,
      maxItems: 2,
      items: {
        type: "string",
        enum: ["chapter_manifest", "normalized_chapter"],
      },
    },
    mode: {
      type: "string",
      enum: ["epub", "toc", "pattern", "manual", "repair"],
    },
    disposition: {
      type: ["string", "null"],
      enum: ["created", "reused", "replaced", "repaired", null],
    },
    exit: { type: "integer" },
    manifest_exists: { type: "boolean" },
    request_fingerprint: { type: ["string", "null"] },
    manifest_fingerprint: { type: ["string", "null"] },
    chapter_count: { type: "integer", minimum: 0 },
    chapters: {
      type: "array",
      maxItems: 150,
      items: chapterRefSchema,
    },
    skipped: { type: "array", items: { type: "object" } },
    removed_files: { type: "array", items: { type: "string" } },
    limit: {
      type: "object",
      additionalProperties: false,
      required: ["max_chapters", "exceeded"],
      properties: {
        max_chapters: { type: "integer", minimum: 1 },
        exceeded: { type: "boolean" },
      },
    },
    previous_manifest_preserved: { type: "boolean" },
    failure: operationFailureSchema("chapter.extract", false),
  },
};

export const CHAPTER_ASSESS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.chapter.assess-boundaries.receipt/0.1",
    },
    key: { const: "chapter.assess-boundaries" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    manifest_path: { type: "string" },
    input_paths: {
      type: "array",
      minItems: 1,
      maxItems: 150,
      items: { type: "string" },
    },
    artifact_roles: {
      type: "array",
      minItems: 2,
      maxItems: 2,
      items: {
        type: "string",
        enum: ["chapter_manifest", "normalized_chapter"],
      },
    },
    signal: {
      type: ["string", "null"],
      enum: [
        "ready",
        "needs_replan",
        "needs_repair",
        "needs_ocr",
        "invalid_source",
        null,
      ],
    },
    diagnostics: {
      type: "array",
      items: chapterDiagnosticSchema,
    },
    failure: operationFailureSchema(
      "chapter.assess-boundaries",
      true,
    ),
  },
};

const CHAPTER_SLOT = /^\d{2,3}[a-z]{0,2}$/;
const CHAPTER_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

const validChapterRef = (chapter) => {
  const filenameIsSafe =
    validText(chapter && chapter.filename, 1, 128) &&
    chapter.filename.startsWith(`${chapter.slot}_`) &&
    chapter.filename.endsWith(".txt") &&
    !chapter.filename.includes("/") &&
    !chapter.filename.includes("\\") &&
    !chapter.filename.includes("..");
  if (
    !CHAPTER_SLOT.test(chapter.slot) ||
    !CHAPTER_SLUG.test(chapter.slug) ||
    !filenameIsSafe ||
    !validText(chapter.title, 1, 500)
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
};

const uniqueChapters = (chapters) => {
  if (
    !chapters.length ||
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
};

const planRefused = (receipt) =>
  receipt.mode === null &&
  receipt.chapters.length === 0 &&
  !!receipt.failure;

export const CHAPTER_PLAN_CONTRACT = {
  schema: CHAPTER_PLAN_SCHEMA,
  echo: (receipt, context) =>
    receipt.input_path === context.input &&
    receipt.normalized_path === context.normalized,
  statuses: {
    succeeded: (receipt) => {
      if (
        receipt.failure !== null ||
        !["toc", "pattern", "manual"].includes(receipt.mode)
      )
        return false;
      if (receipt.mode !== "manual")
        return receipt.chapters.length === 0;
      if (!receipt.chapters.length) return false;
      let lastEnd = 0;
      return receipt.chapters.every((chapter) => {
        if (
          !validText(chapter.title, 1, 500) ||
          chapter.end < chapter.start ||
          chapter.start <= lastEnd
        )
          return false;
        lastEnd = chapter.end;
        return true;
      });
    },
    failed: (receipt) =>
      planRefused(receipt) &&
      receipt.failure.outcome === "known",
    blocked: (receipt) =>
      planRefused(receipt) &&
      receipt.failure.outcome === "unknown",
  },
};

export const chapterExtractSchema = ({
  input,
  outputDir,
  manifest,
  mode,
}) =>
  composedSchema(
    CHAPTER_EXTRACT_SCHEMA,
    {
      input_path: { const: input },
      output_path: { const: outputDir },
      manifest_path: { const: manifest },
      mode: { const: mode },
    },
    {
      succeeded: {
        properties: {
          status: { const: "succeeded" },
          failure: { type: "null" },
          exit: { const: 0 },
          manifest_exists: { const: true },
          request_fingerprint: { type: "string" },
          manifest_fingerprint: { type: "string" },
          disposition: { type: "string" },
        },
      },
      failed: {
        properties: {
          status: { const: "failed" },
          failure: knownFailureBranch(),
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          failure: unknownFailureBranch(),
        },
      },
    },
  );

// Chapter-count arithmetic and cross-item uniqueness stay in the contract.
export const CHAPTER_EXTRACT_CONTRACT = {
  schema: CHAPTER_EXTRACT_SCHEMA,
  statuses: {
    succeeded: (receipt) =>
      receipt.chapter_count === receipt.chapters.length &&
      (receipt.chapter_count === 0 ||
        uniqueChapters(receipt.chapters)),
    failed: (receipt) =>
      receipt.chapter_count === receipt.chapters.length,
    blocked: (receipt) =>
      receipt.chapter_count === receipt.chapters.length,
  },
};

const assessDiagnosticsValid = (receipt, context) => {
  const allowed = new Set([
    context.manifest,
    ...context.chapters.map((chapter) => chapter.path),
  ]);
  return receipt.diagnostics.every((diagnostic) => {
    if (
      !allowed.has(diagnostic.path) ||
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
  });
};

export const CHAPTER_ASSESS_CONTRACT = {
  schema: CHAPTER_ASSESS_SCHEMA,
  echo: (receipt, context) =>
    receipt.manifest_path === context.manifest &&
    JSON.stringify(receipt.input_paths) ===
      JSON.stringify(
        context.chapters.map((chapter) => chapter.path),
      ),
  statuses: {
    succeeded: (receipt, context) => {
      if (!assessDiagnosticsValid(receipt, context)) return false;
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
        const chapter = context.chapters.find(
          (candidate) => diagnostic.path === candidate.path,
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
    },
    failed: (receipt, context) =>
      assessDiagnosticsValid(receipt, context) &&
      receipt.signal === null &&
      !!receipt.failure &&
      receipt.failure.outcome === "known",
    blocked: (receipt, context) =>
      assessDiagnosticsValid(receipt, context) &&
      receipt.signal === null &&
      !!receipt.failure &&
      receipt.failure.outcome === "unknown",
  },
};

export function extractTextOperationPrompt(
  materialKey,
  input,
  output,
) {
  const command = `quasi-extract text ${posixSingleQuote(input)} ${posixSingleQuote(output)} --json`;
  return `You are a narrow command-relay for exactly one writer operation.
material_key: ${materialKey}
operation: document.extract-text
effect: writer
mode: atomic-replace
replay_safe: true
input_path: ${input}
exact_output: ${output}
exact_command: ${command}

Run the exact_command exactly once. Do not add flags, pipes, redirects, tail, a second
business command, semantic judgement, OCR, or recovery. The command itself performs an
atomic deterministic replace, so an identical replay is safe; do not generalise that
property to another writer. Parse its one JSON object and return exactly one typed receipt:
{
  "schema_version": "quasi.operation.document.extract-text.receipt/0.1",
  "key": "document.extract-text",
  "effect": "writer",
  "status": "succeeded|failed",
  "attempt": 1,
  "input_path": "${input}",
  "output_path": "${output}",
  "artifact_roles": ["normalized_text"],
  "exit": 0,
  "exists": true,
  "size": 0,
  "chars": 0,
  "non_whitespace_chars": 0,
  "pages": 0,
  "text_pages": 0,
  "failure": null
}
Copy input/output/exit/exists/size/chars/non_whitespace_chars/pages/text_pages from the
command JSON without changing their meaning. status is succeeded only when command status
is "ok", exit is 0, exists is true, and command output is exactly "${output}"; otherwise
status is failed and failure is
{"code":"document.extract_text_failed","operation_key":"document.extract-text","outcome":"known","retryable":false,"message":"concise command failure"}.
Never claim another output path and never write any path except exact_output.`;
}

export function readabilityOperationPrompt(
  materialKey,
  input,
  signals,
) {
  const request = {
    schema_version:
      "quasi.operation.document.assess-readability.request/0.1",
    operation: "document.assess-readability",
    material_key: materialKey,
    input: {
      role: "normalized_text",
      path: input,
    },
    machine_signals: {
      chars: signals.chars || 0,
      non_whitespace_chars: signals.non_whitespace_chars || 0,
      pages: signals.pages || 0,
      text_pages: signals.text_pages || 0,
      size: signals.size || 0,
    },
    mode: "assess",
  };
  return `You are executing one readonly readability assessment.
Actually Read the one exact normalized text path in this request. Do not run Bash, OCR,
pdftotext, search, or write any file. Machine signals are evidence but not the verdict:
inspect the text for coherent scholarly prose versus empty/sparse/garbled extraction.

Return exactly one typed JSON receipt. status must be "succeeded" when the Read completed
and signal must be exactly one of:
- "readable": coherent body text is available for analysis;
- "needs_ocr": the source appears to be a scan or has an unusable text layer that OCR may recover;
- "invalid_source": the artifact is missing, wrong-format, corrupt, or not the requested material.
Free-text diagnostics may explain the decision but never replace signal.
Echo input_path exactly; do not normalise it.

Request:
${JSON.stringify(request, null, 2)}

Receipt:
{
  "schema_version": "quasi.operation.document.assess-readability.receipt/0.1",
  "key": "document.assess-readability",
  "effect": "readonly",
  "status": "succeeded|failed",
  "attempt": 1,
  "input_path": "${input}",
  "artifact_roles": ["normalized_text"],
  "signal": "readable|needs_ocr|invalid_source",
  "diagnostics": [],
  "failure": null
}
On a known assessment failure, use status "failed", signal null, and failure
{"code":"document.assess_readability_failed","operation_key":"document.assess-readability","outcome":"known","retryable":true}.`;
}

export function chapterPlanOperationPrompt(
  materialKey,
  input,
  normalized,
  diagnostics = [],
) {
  const request = {
    schema_version: "quasi.operation.chapter.plan.request/0.1",
    operation: "chapter.plan",
    material_key: materialKey,
    input: { role: "source", path: input },
    normalized: { role: "normalized_document", path: normalized },
    allowed_modes: ["toc", "pattern", "manual"],
    max_chapters: 150,
    diagnostics,
  };
  return JSON.stringify(request, null, 2);
}

export function chapterExtractOperationPrompt({
  materialKey,
  input,
  outputDir,
  mode,
  plan = [],
  expectedManifestFingerprint = null,
  repair = null,
}) {
  const manifestPath = `${outputDir}/manifest.json`;
  const args =
    mode === "epub"
      ? [
          "quasi-extract",
          "epub",
          posixSingleQuote(input),
          posixSingleQuote(outputDir),
          "--json",
        ]
      : [
          "quasi-extract",
          "split",
          posixSingleQuote(input),
          "--output-dir",
          posixSingleQuote(outputDir),
          ...(mode === "repair"
            ? [
                "--pages",
                posixSingleQuote(
                  `${repair.start_page}-${repair.end_page}`,
                ),
                "--title",
                posixSingleQuote(repair.title),
                "--slot",
                posixSingleQuote(repair.slot),
              ]
            : mode === "manual"
              ? ["--chapters", posixSingleQuote(JSON.stringify(plan))]
              : ["--method", posixSingleQuote(mode)]),
          "--max-chapters",
          "150",
          ...(expectedManifestFingerprint
            ? [
                "--expected-manifest-fingerprint",
                posixSingleQuote(expectedManifestFingerprint),
              ]
            : []),
          "--json",
        ];
  const command = args.join(" ");
  return `You are a narrow command-relay for exactly one chapter.extract writer Operation.
material_key: ${materialKey}
operation: chapter.extract
effect: writer
mode: ${mode}
input_path: ${input}
exact_output_dir: ${outputDir}
exact_manifest_path: ${manifestPath}
exact_command: ${command}

Run exact_command once as the only business command. Do not add flags, redirects, pipes,
preflight probes, rm, a second extract, semantic judgement, OCR, or recovery. Parse exactly
one CLI JSON object with schema_version quasi.extract.chapters.receipt/0.1 and fields
status,input_path,output_dir,mode,disposition,exit,manifest_path,manifest_exists,
request_fingerprint,manifest_fingerprint,chapter_count,chapters,skipped,removed_files,
limit,previous_manifest_preserved,failure. Require CLI input/output/manifest paths to match
the exact request byte-for-byte.

Return one flat quasi.operation.chapter.extract.receipt/0.1 object: key=chapter.extract,
effect=writer, attempt=1, echo input_path/output_path/manifest_path exactly,
artifact_roles=["chapter_manifest","normalized_chapter"], and copy all remaining CLI fields
without reinterpretation. Map CLI ok to succeeded only when exit=0, manifest_exists=true,
chapter_count=chapters.length and paths match. Map CLI existing to succeeded with
disposition=reused so the caller can assess the persisted manifest. Map a well-formed CLI
failed to failed with known failure operation_key=chapter.extract. Map CLI blocked,
malformed JSON, unknown status, or any identity/path mismatch to blocked with
{"code":"book.writer_receipt_mismatch","operation_key":"chapter.extract","outcome":"unknown","retryable":false}.
Never write any other path and never claim success from prose.`;
}

export function chapterAssessOperationPrompt(
  materialKey,
  manifest,
  chapters,
  machineSignals,
) {
  const inputPaths = chapters.map(
    (chapter) => `${manifest.slice(0, -"/manifest.json".length)}/${chapter.filename}`,
  );
  const request = {
    schema_version:
      "quasi.operation.chapter.assess-boundaries.request/0.1",
    operation: "chapter.assess-boundaries",
    material_key: materialKey,
    manifest: { role: "chapter_manifest", path: manifest },
    chapters: chapters.map((chapter, index) => ({
      ...chapter,
      path: inputPaths[index],
    })),
    machine_signals: machineSignals,
  };
  return JSON.stringify(request, null, 2);
}

export function documentOcrOperationPrompt(
  materialKey,
  input,
  output,
  failureNamespace = "paper",
) {
  const failedCode = `${failureNamespace}.ocr_failed`;
  const mismatchCode = `${failureNamespace}.writer_receipt_mismatch`;
  const command = `quasi-extract ocr ${posixSingleQuote(input)} ${posixSingleQuote(output)} --no-clobber --json`;
  return `You are a narrow command-relay for exactly one writer operation.
material_key: ${materialKey}
operation: document.ocr
effect: writer
mode: create
replay: blocked-unless-existing-output-is-reconciled
input_path: ${input}
exact_output: ${output}
exact_command: ${command}

Run exact_command exactly once as the only business command. Do not add flags, shell
operators, wrappers, preflight commands, probes, or a second OCR attempt. Parse only the
single JSON object printed by exact_command; do not infer success from prose or filesystem
guessing. Copy its input, output, exit, exists, and size fields without changing meaning,
and require the JSON output field to equal exact_output byte-for-byte.

Return exactly:
{
  "schema_version": "quasi.operation.document.ocr.receipt/0.1",
  "key": "document.ocr",
  "effect": "writer",
  "status": "succeeded",
  "attempt": 1,
  "input_path": "${input}",
  "output_path": "${output}",
  "artifact_roles": ["recovery_source"],
  "exit": 0,
  "exists": true,
  "size": 0,
  "failure": null
}
Map command status "ok" to succeeded only when exit is 0, exists is true, size is greater
than zero, and both exact paths match. Map command status "existing" to blocked with
failure {"code":"output_exists_requires_reconcile","operation_key":"document.ocr","outcome":"unknown","retryable":false};
this is an observation for caller recovery, not permission to run OCR again. Any other
well-formed command status "failed", nonzero exit, or explicitly reported absent/empty output is
	failed with {"code":"${failedCode}","operation_key":"document.ocr","outcome":"known","retryable":false}.
	Malformed JSON, an unrecognised status, or an input/output path mismatch cannot prove what
	the writer changed: return blocked with
	{"code":"${mismatchCode}","operation_key":"document.ocr","outcome":"unknown","retryable":false}.
	Never write another path.`;
}
