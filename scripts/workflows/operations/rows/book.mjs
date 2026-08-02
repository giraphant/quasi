import {
  BOOK_ARTIFACT_CONTRACT,
  CHAPTER_ARTIFACT_CONTRACT,
} from "../../artifact-contracts/generated.mjs";
import { sameClosedValue, validText } from "../../runtime.mjs";
import { BOOK_TEMP_PATH, validYearEvidence } from "../book-year-evidence.mjs";
import { posixSingleQuote } from "../shared.mjs";

const ATTEMPT_SCHEMA = {
  type: "array",
  maxItems: 64,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["source", "status", "error"],
    properties: {
      source: { type: "string", minLength: 1, maxLength: 200 },
      status: { type: "string", minLength: 1, maxLength: 100 },
      error: { type: ["string", "null"], maxLength: 4000 },
    },
  },
};

const issueSchema = (codes, { questionRequired = false } = {}) => ({
  type: "object",
  additionalProperties: false,
  required: [
    "code",
    "operation",
    "summary",
    "user_question",
    "retryable",
  ],
  properties: {
    code: { type: "string", enum: codes },
    operation: { const: "book.acquire" },
    summary: { type: "string", minLength: 1, maxLength: 4000 },
    user_question: {
      type: questionRequired ? "string" : ["string", "null"],
      ...(questionRequired ? { minLength: 1 } : {}),
      maxLength: 4000,
    },
    retryable: { type: "boolean" },
  },
});

const PREPARE_STEP_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["capability", "outcome", "summary"],
  properties: {
    capability: { type: "string", minLength: 1, maxLength: 100 },
    outcome: {
      type: "string",
      enum: ["observed", "created", "reused", "repaired", "failed"],
    },
    summary: { type: "string", minLength: 1, maxLength: 2000 },
  },
};

const preparedArtifactSchema = {
  type: "array",
  maxItems: 256,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["role", "path", "exists", "usable"],
    properties: {
      role: {
        type: "string",
        enum: [
          "normalized_document",
          "recovery_source",
          "chapter_manifest",
          "normalized_chapter",
        ],
      },
      path: { type: "string" },
      exists: { type: "boolean" },
      usable: { type: ["boolean", "null"] },
    },
  },
};

const CHAPTER_SLOT_PATTERN = "^\\d{2,3}[a-z]{0,2}$";
const CHAPTER_SLUG_PATTERN = "^[a-z0-9][a-z0-9-]{0,79}$";
const CHAPTER_TITLE_PATTERN = "^[^\\u0000-\\u001f\\u007f-\\u009f]+$";
const CHAPTER_SLOT = new RegExp(CHAPTER_SLOT_PATTERN);
const CHAPTER_SLUG = new RegExp(CHAPTER_SLUG_PATTERN);

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
    slot: { type: "string", pattern: CHAPTER_SLOT_PATTERN },
    title: {
      type: "string",
      minLength: 1,
      maxLength: 500,
      pattern: CHAPTER_TITLE_PATTERN,
    },
    filename: { type: "string" },
    slug: { type: "string", pattern: CHAPTER_SLUG_PATTERN },
    word_count: { type: "integer", minimum: 0 },
    start_page: { type: ["integer", "null"], minimum: 1 },
    end_page: { type: ["integer", "null"], minimum: 1 },
  },
};

export const validChapterSlot = (value) =>
  typeof value === "string" && CHAPTER_SLOT.test(value);

const validChapterRef = (chapter) => {
  const filenameIsSafe =
    validText(chapter && chapter.filename, 1, 128) &&
    chapter.filename.startsWith(`${chapter.slot}_`) &&
    chapter.filename.endsWith(".txt") &&
    !chapter.filename.includes("/") &&
    !chapter.filename.includes("\\") &&
    !chapter.filename.includes("..");
  if (
    !chapter ||
    !validChapterSlot(chapter.slot) ||
    !CHAPTER_SLUG.test(chapter.slug) ||
    !filenameIsSafe ||
    !validText(chapter.title, 1, 500)
  )
    return false;
  const noPages = chapter.start_page === null && chapter.end_page === null;
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
  if (!chapters.length || chapters.some((chapter) => !validChapterRef(chapter)))
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

const actionPayloads = ({ mode, writeState = false }) => ({
  complete: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: {
        type: "string",
        enum:
          mode === "create"
            ? ["create", "reconciled"]
            : ["repair", "reconciled"],
      },
      ...(writeState
        ? {
            write_state: {
              type: "string",
              enum: ["written", "not_written"],
            },
          }
        : {}),
    },
  },
  failed: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState ? { write_state: { const: "not_written" } } : {}),
    },
  },
  blocked: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState ? { write_state: { const: "unknown" } } : {}),
    },
  },
});

const AUDIT_DIAGNOSTIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["path", "kind", "reason"],
  properties: {
    path: { type: "string" },
    kind: { type: "string" },
    reason: { type: "string" },
  },
};

const quoteOrNull = (value) =>
  value == null || value === "" ? null : posixSingleQuote(value);

export const bookOperationRows = [
  {
    operation: "book.acquire",
    stage: "Acquire",
    effect: "writer",
    agentType: "quasi:download-agent",
    refs: ({ allowedSources, yearDecision }) => ({
      allowedSources,
      yearDecision,
    }),
    payloadProperties: ({ allowedSources }) => ({
      required: [
        "output_path",
        "format",
        "allowed_output_paths",
        "write_state",
        "identity_verified",
        "isbn",
        "attempts",
        "year_evidence",
        "tmp_path",
      ],
      properties: {
        output_path: {
          type: ["string", "null"],
          enum: [...allowedSources.map(({ path }) => path), null],
        },
        format: { type: ["string", "null"], enum: ["epub", "pdf", null] },
        allowed_output_paths: {
          const: allowedSources.map(({ path }) => path),
        },
        write_state: {
          type: "string",
          enum: ["written", "not_written", "unknown"],
        },
        identity_verified: { type: "boolean" },
        isbn: { type: ["string", "null"], maxLength: 100 },
        attempts: ATTEMPT_SCHEMA,
        year_evidence: { type: ["object", "null"] },
        tmp_path: { type: ["string", "null"], pattern: BOOK_TEMP_PATH.source },
      },
    }),
    // disposition/source describe an accepted write, so they exist only in
    // the complete terminal; a failed run cannot echo "created" out of habit.
    terminalPayloads: () => ({
      complete: {
        required: ["disposition", "source"],
        properties: {
          disposition: { type: "string", enum: ["created", "reused"] },
          source: { type: "string", minLength: 1, maxLength: 200 },
        },
      },
      failed: {
        properties: {
          issue: issueSchema(["book.download_failed"]),
          attempts: { ...ATTEMPT_SCHEMA, minItems: 1 },
        },
      },
      blocked: {
        properties: { issue: issueSchema(["book.acquire_blocked"]) },
      },
      needs_input: {
        required: ["year_evidence", "tmp_path", "proposed_actions"],
        properties: {
          issue: issueSchema(
            ["book.year_mismatch", "book.year_ambiguous"],
            { questionRequired: true },
          ),
          year_evidence: { type: "object" },
          tmp_path: { type: "string", pattern: BOOK_TEMP_PATH.source },
          proposed_actions: {
            anyOf: [
              { const: ["accept-current"] },
              { const: ["accept-current", "use-recommended-year"] },
            ],
          },
        },
      },
    }),
    complete: (receipt, context) => {
      const output = context.allowedSources.find(
        ({ path, format }) =>
          receipt.output_path === path && receipt.format === format,
      );
      const dispositionCoherent =
        (receipt.terminal.disposition === "created" &&
          receipt.write_state === "written") ||
        (receipt.terminal.disposition === "reused" &&
          receipt.write_state === "not_written");
      const expectedYear = context.yearDecision
        ? context.yearDecision.year_evidence.slug_year
        : context.expectedYear;
      const decisionEcho =
        !context.yearDecision ||
        (receipt.tmp_path === context.yearDecision.tmp_path &&
          sameClosedValue(
            receipt.year_evidence,
            context.yearDecision.year_evidence,
          ));
      const yearAccepted =
        receipt.year_evidence &&
        validYearEvidence(receipt.year_evidence, expectedYear) &&
        (receipt.year_evidence.verdict === "MATCH" ||
          context.batchAcceptYear === true ||
          context.yearDecision);
      return !!(
        output &&
        receipt.identity_verified === true &&
        dispositionCoherent &&
        decisionEcho &&
        yearAccepted
      );
    },
    envelope: (
      { slug, meta, materialKey, batchAcceptYear },
      { allowedSources, yearDecision },
    ) => {
      const formats = allowedSources.map(({ format }) => format);
      return {
        schema_version: "quasi.stage.request/0.2",
        operation: "book.acquire",
        stage: "Acquire",
        material_key: materialKey,
        effect: "writer",
        objective:
          "Reconcile or obtain one identity-verified Book source at an allowed output path.",
        allowed_formats: formats,
        allowed_outputs: allowedSources,
        refs: { allowed_outputs: allowedSources },
        identity: {
          title: meta.title,
          authors: meta.authors,
          year: meta.year,
          isbn: meta.isbn || null,
          publisher: meta.publisher,
          category: meta.category,
          confidence: meta.confidence === "verified" ? "verified" : "provided",
        },
        identity_contract: BOOK_ARTIFACT_CONTRACT.identity,
        batch_accept_year: Boolean(batchAcceptYear),
        year_decision: yearDecision,
        resource_bounds: { fetch_budget_per_candidate: 1, accept_budget: 1 },
        shell_argv: {
          slug: posixSingleQuote(slug),
          allowed_outputs: allowedSources.map(({ path }) =>
            posixSingleQuote(path),
          ),
          expected_title: posixSingleQuote(meta.title),
          expected_author: posixSingleQuote(meta.authors[0]),
          year: posixSingleQuote(meta.year),
          isbn: quoteOrNull(meta.isbn),
          format_preference: formats.map((format) => posixSingleQuote(format)),
          year_decision_tmp_path: yearDecision
            ? posixSingleQuote(yearDecision.tmp_path)
            : null,
        },
        capabilities: [
          "quasi-download book candidates --title TITLE --author AUTHOR --json",
          "quasi-download book fetch --candidate-json CANDIDATE --output OUTPUT --json",
          "quasi-download accept --path INPUT --slug SLUG --kind book --json",
          "Read exact candidate, output, and temporary paths to verify identity and year evidence",
        ],
        output_path_rule:
          "For complete, echo one request.allowed_outputs[].path byte-for-byte as output_path. A resolved or absolute CLI path is observation evidence only.",
      };
    },
  },
  {
    operation: "book.prepare",
    stage: "Prepare",
    effect: "writer",
    agentType: "quasi:extract-agent",
    refs: (
      {
        source,
        format,
        normalized,
        recoverySource,
        recoveryText,
        outputDir,
        manifest,
      },
    ) => ({
      source,
      format,
      normalized,
      recoverySource,
      recoveryText,
      outputDir,
      manifest,
    }),
    payloadProperties: (refs) => ({
      required: [
        "format",
        "output_dir",
        "selected_source",
        "normalized_path",
        "manifest_path",
        "manifest_fingerprint",
        "mode",
        "disposition",
        "chapter_count",
        "chapters",
        "artifacts",
        "steps",
        "diagnostics",
      ],
      properties: {
        format: { const: refs.format },
        output_dir: { const: refs.outputDir },
        selected_source: {
          type: ["string", "null"],
          enum: [refs.source, refs.recoverySource, null],
        },
        normalized_path: {
          type: ["string", "null"],
          enum: [refs.normalized, refs.recoveryText, null],
        },
        manifest_path: { const: refs.manifest },
        manifest_fingerprint: {
          type: ["string", "null"],
          pattern: "^[a-f0-9]{64}$",
        },
        mode: {
          type: ["string", "null"],
          enum: ["epub", "toc", "pattern", "manual", "repair", null],
        },
        disposition: {
          type: ["string", "null"],
          enum: ["created", "reused", "replaced", "repaired", null],
        },
        chapter_count: { type: "integer", minimum: 0, maximum: 150 },
        chapters: { type: "array", maxItems: 150, items: chapterRefSchema },
        artifacts: preparedArtifactSchema,
        steps: { type: "array", maxItems: 96, items: PREPARE_STEP_SCHEMA },
        diagnostics: {
          type: "array",
          maxItems: 96,
          items: { type: "string", maxLength: 4000 },
        },
      },
    }),
    complete: (receipt, context) => {
      const chapterPaths = receipt.chapters.map(
        (chapter) => `${context.outputDir}/${chapter.filename}`,
      );
      const allowed = new Set([
        context.normalized,
        context.recoverySource,
        context.recoveryText,
        context.manifest,
        ...chapterPaths,
      ]);
      const listedChapters = new Set(
        receipt.artifacts
          .filter(
            (artifact) =>
              artifact.role === "normalized_chapter" &&
              artifact.exists === true &&
              artifact.usable === true,
          )
          .map((artifact) => artifact.path),
      );
      return (
        typeof receipt.selected_source === "string" &&
        typeof receipt.manifest_fingerprint === "string" &&
        typeof receipt.mode === "string" &&
        typeof receipt.disposition === "string" &&
        receipt.chapter_count === receipt.chapters.length &&
        uniqueChapters(receipt.chapters) &&
        receipt.artifacts.every((artifact) => allowed.has(artifact.path)) &&
        chapterPaths.every((path) => listedChapters.has(path)) &&
        receipt.artifacts.some(
          (artifact) =>
            artifact.role === "chapter_manifest" &&
            artifact.path === receipt.manifest_path &&
            artifact.exists === true &&
            artifact.usable === true,
        )
      );
    },
    envelope: ({ materialKey, identity }, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "book.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Produce and semantically verify one coherent chapter set for the exact accepted Book source.",
      identity,
      refs: {
        source: refs.source,
        format: refs.format,
        normalized_document: refs.normalized,
        recovery_source: refs.recoverySource,
        recovery_text: refs.recoveryText,
        output_dir: refs.outputDir,
        manifest: refs.manifest,
      },
      capabilities: [
        "quasi-extract text INPUT OUTPUT --json",
        "quasi-extract ocr INPUT OUTPUT --no-clobber --json",
        "quasi-extract epub INPUT OUTPUT_DIR --json",
        "quasi-extract split INPUT --output-dir OUTPUT_DIR --method toc|pattern --json",
        "quasi-extract split INPUT --output-dir OUTPUT_DIR --chapters JSON --json",
        "quasi-extract split INPUT --output-dir OUTPUT_DIR --pages START-END --title TITLE --slot SLOT --expected-manifest-fingerprint SHA --json",
        "Read the exact source, manifest, normalized document, and manifest-listed chapter texts",
      ],
      artifact_roles: [
        "normalized_document",
        "recovery_source",
        "chapter_manifest",
        "normalized_chapter",
      ],
      output_limit: { max_chapters: 150 },
    }),
  },
  {
    operation: "chapter.analyse",
    stage: "Analyse",
    effect: "writer",
    agentType: "quasi:analyse-agent",
    refs: ({ input, output, mode }) => ({ input, output, mode }),
    payloadProperties: ({ input, output }) => ({
      required: ["input_path", "output_path", "artifact_roles"],
      properties: {
        input_path: { const: input },
        output_path: { const: output },
        artifact_roles: {
          type: "array",
          minItems: 1,
          maxItems: 1,
          items: { const: "chapter_canonical" },
        },
      },
    }),
    terminalPayloads: ({ mode }) => actionPayloads({ mode, writeState: true }),
    complete: (receipt, context) => {
      const { action, write_state: writeState } = receipt.terminal;
      return (
        [
          ...(context.mode === "create" ? ["create"] : ["repair"]),
          "reconciled",
        ].includes(action) &&
        writeState === (action === "reconciled" ? "not_written" : "written")
      );
    },
    envelope: ({ bookSlug, meta, chapter, materialKey, diagnostics }, refs) => {
      const chapterLabel =
        chapter.chapter_label || chapter.label || `第${chapter.slot}章`;
      const chapterTitle = String(chapter.title || "").trim();
      const canonicalTitle = chapterTitle.startsWith(chapterLabel)
        ? chapterTitle
        : `${chapterLabel} ${chapterTitle}`.trim();
      const authors =
        Array.isArray(chapter.authors) && chapter.authors.length
          ? chapter.authors
          : meta.authors;
      return {
        schema_version: "quasi.stage.request/0.2",
        operation: "chapter.analyse",
        stage: "Analyse",
        material_key: materialKey,
        input: { role: "normalized_chapter", path: refs.input },
        output: { role: "chapter_canonical", path: refs.output },
        identity: {
          book_slug: bookSlug,
          book_title: meta.title,
          chapter_slot: chapter.slot,
          chapter_slug: chapter.slug,
          chapter_label: chapterLabel,
          chapter_title: chapter.title,
          authors,
          year: meta.year,
          confidence: meta.confidence === "verified" ? "verified" : "provided",
        },
        artifact_contract: CHAPTER_ARTIFACT_CONTRACT,
        frontmatter_seed: {
          type: "chapter",
          title: canonicalTitle,
          authors,
          year: meta.year,
          book: bookSlug,
        },
        mode: refs.mode,
        overwrite: refs.mode === "repair",
        repair_diagnostics: refs.mode === "repair" ? diagnostics : [],
      };
    },
    promptText: (request) =>
      `Execute exactly one chapter.analyse operation using this self-contained JSON request.\nDo not reinterpret it as another operation and do not read project instruction files.\n${JSON.stringify(request, null, 2)}`,
  },
  {
    operation: "book.synthesise",
    stage: "Synthesise",
    effect: "writer",
    agentType: "quasi:synthesis-agent",
    refs: ({ inputPaths, output, mode }) => ({ inputPaths, output, mode }),
    payloadProperties: ({ inputPaths, output }) => ({
      required: [
        "input_paths",
        "output_path",
        "artifact_roles",
        "chapters_analyzed",
      ],
      properties: {
        input_paths: { const: inputPaths },
        output_path: { const: output },
        artifact_roles: {
          type: "array",
          minItems: 1,
          maxItems: 1,
          items: { const: "canonical" },
        },
        chapters_analyzed: { const: inputPaths.length },
      },
    }),
    terminalPayloads: ({ mode }) => actionPayloads({ mode }),
    complete: (receipt, context) =>
      [
        ...(context.mode === "create" ? ["create"] : ["repair"]),
        "reconciled",
      ].includes(receipt.terminal.action),
    envelope: ({ slug, meta, materialKey, diagnostics }, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "book.synthesise",
      stage: "Synthesise",
      material_key: materialKey,
      inputs: refs.inputPaths.map((path) => ({
        role: "chapter_canonical",
        path,
      })),
      output: { role: "canonical", path: refs.output },
      identity: {
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
        publisher: meta.publisher,
        isbn: meta.isbn || null,
        category: meta.category,
        confidence: meta.confidence === "verified" ? "verified" : "provided",
      },
      artifact_contract: BOOK_ARTIFACT_CONTRACT,
      frontmatter_seed: {
        type: "book",
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
        publisher: meta.publisher,
        isbn: meta.isbn || null,
        category: meta.category,
      },
      mode: refs.mode,
      overwrite: refs.mode === "repair",
      repair_diagnostics: refs.mode === "repair" ? diagnostics : [],
    }),
  },
  {
    operation: "book.audit",
    stage: "Audit",
    effect: "writer",
    agentType: "quasi:audit-agent",
    refs: ({ target, pass }) => ({ target, pass }),
    payloadProperties: ({ target, pass }) => ({
      required: [
        "target_path",
        "pass",
        "remaining_violations",
        "escalated",
        "mutated_paths",
      ],
      properties: {
        target_path: { const: target },
        pass: { const: pass },
        remaining_violations: { type: "integer", minimum: 0 },
        escalated: { type: "array", items: AUDIT_DIAGNOSTIC_SCHEMA },
        mutated_paths: {
          type: "array",
          uniqueItems: true,
          items: { type: "string" },
        },
      },
    }),
    complete: (receipt) =>
      receipt.mutated_paths.every((path) => validText(path, 1, 2048)) &&
      receipt.escalated.every(
        (diagnostic) =>
          validText(diagnostic.path, 1, 2048) &&
          validText(diagnostic.kind, 1, 200) &&
          validText(diagnostic.reason, 1, 4000),
      ) &&
      (receipt.remaining_violations === 0
        ? receipt.escalated.length === 0
        : receipt.remaining_violations === receipt.escalated.length),
    envelope: ({ materialKey }, { target, pass }) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "book.audit",
      stage: "Audit",
      material_key: materialKey,
      effect: "writer",
      pass,
      mode: pass === 1 ? "audit" : "re-audit",
      target: { role: "canonical_scope", path: target },
    }),
  },
];
