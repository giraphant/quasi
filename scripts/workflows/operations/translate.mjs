import {
  stageContract,
  stageReceiptSchema,
} from "../stage.mjs";

const HASH = /^[0-9a-f]{64}$/;

export const validTranslationHash = (value) =>
  typeof value === "string" && HASH.test(value);

export function normalizeLanguage(value) {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,2}$/.test(value)
  )
    return null;
  return value
    .split("-")
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
    minimum_median: nullableNumberSchema({ minimum: 0 }),
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
    sha256: { type: "string", pattern: "^[0-9a-f]{64}$" },
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
    candidates_fingerprint: nullableStringSchema({
      pattern: "^[0-9a-f]{64}$",
    }),
  },
};

function validCoverage(value) {
  if (!value || typeof value !== "object") return false;
  if (value.signal === "pass")
    return (
      typeof value.median === "number" &&
      typeof value.minimum_median === "number" &&
      value.median >= value.minimum_median
    );
  if (value.signal === "not_applicable")
    return value.median === null && value.minimum_median === null;
  if (value.signal === "insufficient_evidence")
    return value.measured_pages >= 0;
  return false;
}

const TRANSLATION_STAGE_STEP_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["capability", "outcome", "summary"],
  properties: {
    capability: { type: "string", minLength: 1, maxLength: 100 },
    outcome: {
      type: "string",
      enum: ["observed", "created", "reused", "recovered", "failed"],
    },
    summary: { type: "string", minLength: 1, maxLength: 2000 },
  },
};

const TRANSLATION_STAGE_SOURCE_SCHEMA = {
  type: ["object", "null"],
  additionalProperties: false,
  required: ["path", "sha256", "size", "pages"],
  properties: {
    path: { type: "string", pattern: "\\.pdf$" },
    sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    size: { type: "integer", minimum: 1 },
    pages: { type: "integer", minimum: 1 },
  },
};

const TRANSLATION_STAGE_VALIDATION_SCHEMA = {
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "output_sha256",
    "manifest_sha256",
    "output_size",
    "source_pages",
    "output_pages",
    "toc_entries",
    "coverage",
  ],
  properties: {
    output_sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    manifest_sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    output_size: { type: "integer", minimum: 1 },
    source_pages: { type: "integer", minimum: 1 },
    output_pages: { type: "integer", minimum: 1 },
    toc_entries: { type: "integer", minimum: 0 },
    coverage: coverageSchema,
  },
};

export const translationPrepareStageSchema = ({
  derivativeKey,
  slug,
  targetLanguage,
  output,
  manifest,
}) =>
  stageReceiptSchema({
    operation: "translation.prepare",
    stage: "Prepare",
    materialKey: derivativeKey,
    effect: "writer",
    required: [
      "slug",
      "target_language",
      "backend",
      "source",
      "output_path",
      "manifest_path",
      "disposition",
      "recovered",
      "validation",
      "gate",
      "steps",
      "diagnostics",
    ],
    properties: {
      slug: { const: slug },
      target_language: { const: targetLanguage },
      backend: {
        type: ["string", "null"],
        enum: ["immersive", "pdf2zh", null],
      },
      source: TRANSLATION_STAGE_SOURCE_SCHEMA,
      output_path: { const: output },
      manifest_path: { const: manifest },
      disposition: {
        type: ["string", "null"],
        enum: ["created", "reused", "recovered", null],
      },
      recovered: { type: "boolean" },
      validation: TRANSLATION_STAGE_VALIDATION_SCHEMA,
      gate: gateSchema,
      steps: {
        type: "array",
        maxItems: 48,
        items: TRANSLATION_STAGE_STEP_SCHEMA,
      },
      diagnostics: {
        type: "array",
        maxItems: 48,
        items: { type: "string", maxLength: 4000 },
      },
    },
  });

export const TRANSLATION_PREPARE_STAGE_CONTRACT = stageContract({
  schema: translationPrepareStageSchema({
    derivativeKey: "translation:paper:placeholder:zh-CN",
    slug: "placeholder",
    targetLanguage: "zh-CN",
    output: "processing/translations/placeholder-zh-cn.pdf",
    manifest: "processing/translations/placeholder-zh-cn.manifest.json",
  }),
  complete: (receipt, context) =>
    !!receipt.source &&
    !!receipt.validation &&
    receipt.backend !== null &&
    ["created", "reused", "recovered"].includes(receipt.disposition) &&
    receipt.gate === null &&
    receipt.output_path === context.output &&
    receipt.manifest_path === context.manifest &&
    validRequestedSource(
      receipt.source.path,
      context.slug,
      context.targetLanguage,
    ) &&
    (context.requestedSource === null ||
      receipt.source.path === context.requestedSource ||
      receipt.source.path === context.recoverySource) &&
    receipt.recovered ===
      (receipt.source.path === context.recoverySource) &&
    receipt.validation.source_pages === receipt.source.pages &&
    receipt.validation.output_pages === receipt.source.pages * 2 &&
    validCoverage(receipt.validation.coverage) &&
    ["pass", "not_applicable", "insufficient_evidence"].includes(
      receipt.validation.coverage.signal,
    ),
});

export function translationPrepareStagePrompt(state) {
  return JSON.stringify(
    {
      schema_version: "quasi.stage.translation-prepare.request/0.1",
      operation: "translation.prepare",
      stage: "Prepare",
      material_key: state.translationKey,
      effect: "writer",
      objective:
        "Select or reconcile the exact source and produce one validated translated PDF generation.",
      identity: {
        slug: state.slug,
        target_language: state.targetLanguage,
      },
      source_request: {
        path: state.requestedSource,
        decision: state.sourceDecision,
      },
      refs: {
        output: state.output,
        manifest: state.manifest,
        recovery_source: state.recoverySource,
        toc_json: state.tocJson,
        toc_page_side: state.tocPageSide,
      },
      capabilities: [
        "quasi-translate observe ... --json",
        "quasi-translate run ... --json",
        "quasi-extract ocr INPUT OUTPUT --layout --no-clobber --json",
        "Read exact validation receipts and translated PDF text observations",
      ],
      backend_policy:
        "The configured backend reported by quasi-translate is authoritative.",
    },
    null,
    2,
  );
}
