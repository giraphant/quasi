import { validText } from "../runtime.mjs";
import {
  stageContract,
  stageReceiptSchema,
} from "../stage.mjs";

// Extract is a Stage boundary, not a transcription of the specialist's
// decision tree.  The schemas below prove only the exact artifacts that the
// next graph stage consumes.  The extract Agent owns readability, OCR and
// chapter-boundary judgement; quasi-extract owns deterministic publication.

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

const preparedArtifactSchema = (paths, roles) => ({
  type: "array",
  maxItems: 256,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["role", "path", "exists", "usable"],
    properties: {
      role: { type: "string", enum: roles },
      path: {
        type: "string",
        ...(paths ? { enum: paths } : {}),
      },
      exists: { type: "boolean" },
      usable: { type: ["boolean", "null"] },
    },
  },
});

const CHAPTER_SLOT_PATTERN = "^\\d{2,3}[a-z]{0,2}$";
const CHAPTER_SLUG_PATTERN = "^[a-z0-9][a-z0-9-]{0,79}$";
const CHAPTER_TITLE_PATTERN = "^[^\\u0000-\\u001f\\u007f-\\u009f]+$";

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
      description:
        "Exact committed chapter title, trimmed and free of tabs, newlines, and other control characters.",
    },
    filename: { type: "string" },
    slug: {
      type: "string",
      pattern: CHAPTER_SLUG_PATTERN,
      description:
        "Exact committed chapter slug in lowercase ASCII kebab-case; underscores, spaces, Unicode, dots, and path separators are invalid.",
    },
    word_count: { type: "integer", minimum: 0 },
    start_page: { type: ["integer", "null"], minimum: 1 },
    end_page: { type: ["integer", "null"], minimum: 1 },
  },
};

const CHAPTER_SLOT = new RegExp(CHAPTER_SLOT_PATTERN);
const CHAPTER_SLUG = new RegExp(CHAPTER_SLUG_PATTERN);

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

export const paperPrepareStageSchema = ({
  materialKey,
  source,
  normalized,
  recoverySource,
  recoveryText,
}) =>
  stageReceiptSchema({
    operation: "paper.prepare",
    stage: "Prepare",
    materialKey,
    effect: "writer",
    required: [
      "source_path",
      "selected_input",
      "artifacts",
      "steps",
      "diagnostics",
    ],
    properties: {
      source_path: { const: source },
      selected_input: {
        type: ["string", "null"],
        enum: [normalized, recoveryText, null],
      },
      artifacts: preparedArtifactSchema(
        [normalized, recoverySource, recoveryText],
        ["normalized_text", "recovery_source"],
      ),
      steps: { type: "array", maxItems: 64, items: PREPARE_STEP_SCHEMA },
      diagnostics: {
        type: "array",
        maxItems: 64,
        items: { type: "string", maxLength: 4000 },
      },
    },
  });

export const PAPER_PREPARE_STAGE_CONTRACT = stageContract({
  schema: paperPrepareStageSchema({
    materialKey: "paper:placeholder",
    source: "sources/placeholder.pdf",
    normalized: "processing/papers/placeholder/source.txt",
    recoverySource: "processing/papers/placeholder/ocr.pdf",
    recoveryText: "processing/papers/placeholder/ocr.txt",
  }),
  complete: (receipt, context) => {
    const allowed = new Set([
      context.normalized,
      context.recoverySource,
      context.recoveryText,
    ]);
    return (
      typeof receipt.selected_input === "string" &&
      receipt.artifacts.every((artifact) => allowed.has(artifact.path)) &&
      receipt.artifacts.some(
        (artifact) =>
          artifact.role === "normalized_text" &&
          artifact.path === receipt.selected_input &&
          artifact.exists === true &&
          artifact.usable === true,
      )
    );
  },
});

export function paperPrepareStagePrompt({
  materialKey,
  source,
  normalized,
  recoverySource,
  recoveryText,
}) {
  return JSON.stringify(
    {
      schema_version: "quasi.stage.paper-prepare.request/0.1",
      operation: "paper.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Produce one readable normalized text for the exact accepted Paper source.",
      refs: {
        source,
        normalized,
        recovery_source: recoverySource,
        recovery_text: recoveryText,
      },
      capabilities: [
        "quasi-extract text INPUT OUTPUT --json",
        "quasi-extract ocr INPUT OUTPUT --no-clobber --json",
        "Read exact normalized text artifacts",
      ],
      artifact_roles: ["normalized_text", "recovery_source"],
    },
    null,
    2,
  );
}

export const bookPrepareStageSchema = ({
  materialKey,
  source,
  format,
  normalized,
  recoverySource,
  recoveryText,
  outputDir,
  manifest,
}) =>
  stageReceiptSchema({
    operation: "book.prepare",
    stage: "Prepare",
    materialKey,
    effect: "writer",
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
      format: { const: format },
      output_dir: { const: outputDir },
      selected_source: {
        type: ["string", "null"],
        enum: [source, recoverySource, null],
      },
      normalized_path: {
        type: ["string", "null"],
        enum: [normalized, recoveryText, null],
      },
      manifest_path: { const: manifest },
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
      chapters: {
        type: "array",
        maxItems: 150,
        items: chapterRefSchema,
      },
      artifacts: preparedArtifactSchema(
        null,
        [
          "normalized_document",
          "recovery_source",
          "chapter_manifest",
          "normalized_chapter",
        ],
      ),
      steps: { type: "array", maxItems: 96, items: PREPARE_STEP_SCHEMA },
      diagnostics: {
        type: "array",
        maxItems: 96,
        items: { type: "string", maxLength: 4000 },
      },
    },
  });

export const BOOK_PREPARE_STAGE_CONTRACT = stageContract({
  schema: bookPrepareStageSchema({
    materialKey: "book:placeholder",
    source: "sources/placeholder.pdf",
    format: "pdf",
    normalized: "processing/chapters/placeholder/source.txt",
    recoverySource: "processing/chapters/placeholder/ocr.pdf",
    recoveryText: "processing/chapters/placeholder/ocr.txt",
    outputDir: "processing/chapters/placeholder",
    manifest: "processing/chapters/placeholder/manifest.json",
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
});

export function bookPrepareStagePrompt({
  materialKey,
  identity,
  source,
  format,
  normalized,
  recoverySource,
  recoveryText,
  outputDir,
  manifest,
}) {
  return JSON.stringify(
    {
      schema_version: "quasi.stage.book-prepare.request/0.1",
      operation: "book.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Produce and semantically verify one coherent chapter set for the exact accepted Book source.",
      identity,
      refs: {
        source,
        format,
        normalized_document: normalized,
        recovery_source: recoverySource,
        recovery_text: recoveryText,
        output_dir: outputDir,
        manifest,
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
    },
    null,
    2,
  );
}
