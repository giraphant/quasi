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
  return `Execute one readonly chapter.plan judgement. Read only the exact source path and,
when normalized.path is non-null, that exact normalized document path. A null normalized
path is intentional for an EPUB replan: do not invent or discover another path. Do not run
Bash, Glob, quasi-extract, OCR, search, or write files. Select exactly one mode: toc when
the source has a trustworthy embedded TOC, pattern
when real chapter headings are semantically regular, or manual when explicit page ranges are
required. Manual mode must return non-overlapping, ordered, inclusive page ranges with titles;
toc/pattern return chapters=[]. A chapter count or length is only machine evidence, never the
semantic verdict. Diagnostics are evidence for this one replan, not permission to loop.

Request:
${JSON.stringify(request, null, 2)}

Return exactly one quasi.operation.chapter.plan.receipt/0.1 object with key=chapter.plan,
effect=readonly, attempt=1, input_path and nullable normalized_path echoed byte-for-byte,
artifact_roles=["chapter_plan"], status succeeded|failed, mode toc|pattern|manual or null,
chapters, diagnostics, and failure. succeeded requires one mode and failure=null. failed
requires mode=null and failure
{"code":"chapter.plan_failed","operation_key":"chapter.plan","outcome":"known","retryable":true}.`;
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
  return `Execute one readonly semantic assessment of an extracted chapter set. Read the exact
manifest and only the exact manifest-listed chapter paths in this request. Inspect actual
chapter openings/endings and enough body prose to judge coherence, truncation, crossed
boundaries, headers-only/garbled extraction, or a scan. Do not run Bash, Glob, OCR, extract,
search, or write. Counts, sizes and limit.exceeded are evidence only; never turn a character
or chapter-count threshold into the semantic verdict.

Return exactly one quasi.operation.chapter.assess-boundaries.receipt/0.1 object with
key=chapter.assess-boundaries, effect=readonly, attempt=1, exact manifest_path and ordered
input_paths. input_paths must equal Request.chapters[].path in that exact order and must not
include manifest_path. artifact_roles=["chapter_manifest","normalized_chapter"], status,
signal, diagnostics and failure. A succeeded signal is exactly ready|needs_replan|needs_repair|
needs_ocr|invalid_source. Every diagnostic is exactly
{path,kind,reason,slot,title,start_page,end_page}; path must equal the manifest path or one
listed chapter path. needs_repair diagnostics must identify one listed chapter plus exact
slot/title/inclusive page range. Free prose never controls the next edge.

Request:
${JSON.stringify(request, null, 2)}`;
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
