import {
  InputContractError,
  contextValue,
} from "../../context-base.mts";
import { issueSchema } from "../shared.mts";
import type { OperationRow } from "../../artifact-contracts/generated.mjs";

type AnyFunction = (...args: any[]) => any;

const HASH = /^[0-9a-f]{64}$/;

export const validTranslationHash = (value: unknown): value is string =>
  typeof value === "string" && HASH.test(value);

export function normalizeLanguage(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$/.test(value)
  )
    return null;
  return value
    .split("-")
    .map((part, index) => {
      if (index === 0) return part.toLowerCase();
      if (/^[A-Za-z]{2}$/.test(part)) return part.toUpperCase();
      return part.toLowerCase();
    })
    .join("-");
}

export function sourceRoles(slug: string, targetLanguage: string) {
  const langTag = targetLanguage.toLowerCase();
  return {
    canonical: `sources/${slug}.pdf`,
    paperOcr: `processing/papers/${slug}/ocr.pdf`,
    derivativeRecovery: `processing/translations/${slug}-${langTag}-reocr.pdf`,
  };
}

export function validRequestedSource(
  path: string,
  slug: string,
  targetLanguage: string,
) {
  const roles = sourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr, roles.derivativeRecovery].includes(
    path,
  );
}

export function validSelectableSource(
  path: string,
  slug: string,
  targetLanguage: string,
) {
  const roles = sourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr].includes(path);
}

const nullableStringSchema: AnyFunction = (properties = {}) => ({
  anyOf: [{ type: "null" }, { type: "string", ...properties }],
});

const nullableNumberSchema: AnyFunction = (properties = {}) => ({
  anyOf: [{ type: "null" }, { type: "number", ...properties }],
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
  anyOf: [
    {
      type: "object",
      additionalProperties: false,
      required: [
        "kind",
        "missing_fields",
        "candidates",
        "candidates_fingerprint",
      ],
      properties: {
        kind: { const: "source_selection" },
        missing_fields: { const: [] },
        candidates: {
          type: "array",
          minItems: 2,
          maxItems: 32,
          items: candidateSchema,
        },
        candidates_fingerprint: {
          type: "string",
          pattern: "^[0-9a-f]{64}$",
        },
      },
    },
    {
      type: "object",
      additionalProperties: false,
      required: [
        "kind",
        "missing_fields",
        "candidates",
        "candidates_fingerprint",
      ],
      properties: {
        kind: { const: "configuration_required" },
        missing_fields: {
          type: "array",
          minItems: 1,
          maxItems: 8,
          uniqueItems: true,
          items: { type: "string", minLength: 1 },
        },
        candidates: { const: [] },
        candidates_fingerprint: { type: "null" },
      },
    },
  ],
};

const validCoverage: AnyFunction = (value) => {
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
};

const STEP_SCHEMA = {
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

const SOURCE_SCHEMA = {
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

const VALIDATION_SCHEMA = {
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

export const translationOperationRows: OperationRow[] = [
  {
    operation: "translation.prepare",
    context: (rawContext, base) => {
      const targetLanguage = normalizeLanguage(rawContext.target_language);
      if (targetLanguage === null)
        throw new InputContractError(
          "translation.prepare requires a valid target language",
        );
      const target = targetLanguage.toLowerCase();
      const stem = `${base.slug}-${target}`;
      return {
        ...base,
        materialKey:
          contextValue(rawContext, "materialKey", "material_key") ||
          `translation:paper:${base.slug}:${targetLanguage}`,
        targetLanguage,
        target,
        stem,
        requestedSource:
          contextValue(
            rawContext,
            "requestedSource",
            "requested_source",
          ) ||
          rawContext.source_file ||
          null,
        sourceDecision:
          contextValue(
            rawContext,
            "sourceDecision",
            "source_decision",
          ) || null,
        tocJson:
          contextValue(rawContext, "tocJson", "toc_json") || null,
        tocPageSide:
          contextValue(rawContext, "tocPageSide", "toc_page_side") ||
          "original",
      };
    },
    refs: (
      {
        slug,
        targetLanguage,
        output,
        manifest,
        recoverySource,
        tocJson,
        tocPageSide,
      },
    ) => ({
      slug,
      targetLanguage,
      output,
      manifest,
      recoverySource,
      tocJson,
      tocPageSide,
    }),
    writeTargets: ({ output, manifest, recoverySource }) => [
      { scope: "exact", path: output },
      { scope: "exact", path: manifest },
      { scope: "exact", path: recoverySource },
    ],
    payloadProperties: ({ slug, targetLanguage, output, manifest }) => ({
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
        source: SOURCE_SCHEMA,
        output_path: { const: output },
        manifest_path: { const: manifest },
        disposition: {
          type: ["string", "null"],
          enum: ["created", "reused", "recovered", null],
        },
        recovered: { type: "boolean" },
        validation: VALIDATION_SCHEMA,
        steps: { type: "array", maxItems: 48, items: STEP_SCHEMA },
        diagnostics: {
          type: "array",
          maxItems: 48,
          items: { type: "string", maxLength: 4000 },
        },
      },
    }),
    terminalPayloads: () => ({
      needs_input: {
        required: ["gate"],
        properties: {
          issue: issueSchema(
            "translation.prepare",
            [
              "translation.source_selection_required",
              "translation.configuration_required",
            ],
            { questionRequired: true },
          ),
          gate: gateSchema,
        },
      },
    }),
    complete: (receipt, context) =>
      !!receipt.source &&
      !!receipt.validation &&
      receipt.backend !== null &&
      ["created", "reused", "recovered"].includes(receipt.disposition) &&
      validRequestedSource(
        receipt.source.path,
        context.slug,
        context.targetLanguage,
      ) &&
      (context.requestedSource === null ||
        receipt.source.path === context.requestedSource ||
        receipt.source.path === context.recoverySource) &&
      receipt.recovered === (receipt.source.path === context.recoverySource) &&
      receipt.validation.source_pages === receipt.source.pages &&
      receipt.validation.output_pages === receipt.source.pages * 2 &&
      validCoverage(receipt.validation.coverage) &&
      ["pass", "not_applicable", "insufficient_evidence"].includes(
        receipt.validation.coverage.signal,
      ),
    envelope: (
      { materialKey, requestedSource, sourceDecision },
      refs,
    ) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "translation.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Select or reconcile the exact source and produce one validated translated PDF generation.",
      identity: {
        slug: refs.slug,
        target_language: refs.targetLanguage,
      },
      source_request: { path: requestedSource, decision: sourceDecision },
      refs: {
        output: refs.output,
        manifest: refs.manifest,
        recovery_source: refs.recoverySource,
        toc_json: refs.tocJson,
        toc_page_side: refs.tocPageSide,
      },
      capabilities: [
        "quasi-translate observe ... --json",
        "quasi-translate run ... --json",
        "quasi-extract ocr INPUT OUTPUT --layout --no-clobber --json",
        "Read exact validation receipts and translated PDF text observations",
      ],
      backend_policy:
        "The configured backend reported by quasi-translate is authoritative.",
    }),
  },
];
