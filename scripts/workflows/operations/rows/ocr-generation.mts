import { InputContractError } from "../../context-base.mts";
import {
  parseOcrGenerationObservation,
  type OcrGenerationObservation,
  type OcrMaterialKind,
} from "../../contracts/ocr-generation.mts";
import { posixSingleQuote } from "../shared.mts";
import type { OperationRow } from "../../artifact-contracts/generated.mjs";

type AnyFunction = (...args: any[]) => any;
const SHA256_PATTERN = "^[0-9a-f]{64}$";

const progressSchema = {
  anyOf: [
    { type: "null" },
    {
      type: "object",
      additionalProperties: false,
      required: ["completed_pages", "total_pages", "next_page", "ranges"],
      properties: {
        completed_pages: { type: "integer", minimum: 0 },
        total_pages: { type: "integer", minimum: 1 },
        next_page: { type: ["integer", "null"], minimum: 1 },
        ranges: {
          type: "array",
          maxItems: 10000,
          items: {
            type: "object",
            additionalProperties: false,
            required: ["start_page", "end_page", "engine", "path", "sha256", "pages"],
            properties: {
              start_page: { type: "integer", minimum: 1 },
              end_page: { type: "integer", minimum: 1 },
              engine: { type: "string", enum: ["dsocr2", "tesseract"] },
              path: { type: "string", minLength: 1, maxLength: 2048 },
              sha256: { type: "string", pattern: SHA256_PATTERN },
              pages: { type: "integer", minimum: 1 },
            },
          },
        },
      },
    },
  ],
};

const fileFactSchema: AnyFunction = (path, kind) => {
  const extra = kind === "pdf"
    ? { pages: { type: "integer", minimum: 0 } }
    : kind === "text"
      ? {
          utf8: { type: ["boolean", "null"] },
          chars: { type: "integer", minimum: 0 },
          non_whitespace_chars: { type: "integer", minimum: 0 },
        }
      : {};
  return {
    type: "object",
    additionalProperties: false,
    required: ["path", "exists", "regular", "sha256", "size", ...Object.keys(extra)],
    properties: {
      path: { const: path },
      exists: { type: "boolean" },
      regular: { type: ["boolean", "null"] },
      sha256: { type: ["string", "null"], pattern: SHA256_PATTERN },
      size: { type: "integer", minimum: 0 },
      ...extra,
    },
  };
};

const artifactsSchema: AnyFunction = (refs) => ({
  type: "array",
  minItems: 3,
  maxItems: 3,
  uniqueItems: true,
  items: {
    anyOf: [
      fileFactSchema(refs.recoveryPdf, "pdf"),
      fileFactSchema(refs.recoveryText, "text"),
      fileFactSchema(refs.manifest, "json"),
    ],
  },
});

const failureSchema = {
  anyOf: [
    { type: "null" },
    {
      type: "object",
      additionalProperties: false,
      required: ["code", "outcome", "retryable", "message"],
      properties: {
        code: { type: "string", minLength: 1, maxLength: 200 },
        outcome: { type: "string", enum: ["known", "unknown"] },
        retryable: { type: "boolean" },
        message: { type: "string", minLength: 1, maxLength: 4000 },
      },
    },
  ],
};

export const makeOcrGenerationRow = (config: {
  operation: "paper.ocr" | "book.ocr";
  kind: OcrMaterialKind;
  validationPolicy: "paper-text-v1" | "book-pdf-v1";
}): OperationRow => ({
  operation: config.operation,
  context: (rawContext: any, base: any) => {
    const generation = rawContext.ocrGeneration;
    if (
      !generation || typeof generation !== "object" ||
      typeof generation.generation_key !== "string" ||
      !/^[0-9a-f]{64}$/.test(generation.generation_key)
    ) throw new InputContractError(`${config.operation} requires one current OCR generation`);
    return { ...base, ocrGeneration: generation, generationKey: generation.generation_key };
  },
  refs: ({
    slug, materialKey, ocrGeneration, source, lock, workDir, progress,
    generationDir, recoveryPdf, recoveryText, manifest,
  }: any) => {
    const generation = parseOcrGenerationObservation(ocrGeneration, {
      kind: config.kind,
      slug,
      source: ocrGeneration?.source,
    });
    if (
      generation === null || generation.material_key !== materialKey ||
      !["missing", "in_progress"].includes(generation.state) ||
      generation.profile.validation_policy !== config.validationPolicy ||
      generation.source.path !== source || generation.source.pages < 1 ||
      generation.paths.lock !== lock || generation.paths.work_dir !== workDir ||
      generation.paths.progress !== progress || generation.paths.generation_dir !== generationDir ||
      generation.paths.pdf !== recoveryPdf || generation.paths.text !== recoveryText ||
      generation.paths.manifest !== manifest || generation.failure !== null
    ) throw new InputContractError(
      `${config.operation} generation does not match the safe status projection`,
    );
    return {
      slug, materialKey, generationKey: generation.generation_key,
      configFingerprint: generation.config_fingerprint, profile: generation.profile,
      source, sourceFact: generation.source, pathsFact: generation.paths,
      expectedState: generation.state, expectedProgress: generation.progress,
      lock, workDir, progress, generationDir, recoveryPdf, recoveryText, manifest,
      ocrGeneration: generation,
    };
  },
  writeTargets: ({ lock, workDir, generationDir }: any) => [
    { scope: "exact", path: lock },
    { scope: "subtree", path: workDir },
    { scope: "subtree", path: generationDir },
  ],
  payloadProperties: (refs: any) => ({
    required: [
      "generation_key", "profile", "config_fingerprint", "source", "paths",
      "state", "progress", "artifacts", "failure",
    ],
    properties: {
      generation_key: { const: refs.generationKey },
      profile: { const: refs.profile },
      config_fingerprint: { const: refs.configFingerprint },
      source: { const: refs.sourceFact },
      paths: { const: refs.pathsFact },
      state: { type: "string", enum: ["in_progress", "committed", "invalid", "unknown"] },
      progress: progressSchema,
      artifacts: artifactsSchema(refs),
      failure: failureSchema,
    },
  }),
  terminalPayloads: () => ({
    complete: {
      required: ["disposition"],
      properties: {
        disposition: { type: "string", enum: ["partial", "created", "reconciled"] },
      },
    },
  }),
  complete: (receipt: any, context: any) => {
    if (receipt.failure !== null || receipt.artifacts.length !== 3) return false;
    const artifacts = new Map(receipt.artifacts.map((item: any) => [item.path, item]));
    if (
      artifacts.size !== 3 || !artifacts.has(context.recoveryPdf) ||
      !artifacts.has(context.recoveryText) || !artifacts.has(context.manifest)
    ) return false;
    if (receipt.terminal.disposition === "partial") {
      const previous = context.ocrGeneration.progress?.completed_pages ?? 0;
      const progress = receipt.progress;
      const chunk = context.ocrGeneration.profile.chunk_pages;
      return (
        receipt.state === "in_progress" && progress !== null &&
        progress.total_pages === context.ocrGeneration.source.pages &&
        progress.completed_pages > previous &&
        progress.completed_pages <= Math.min(previous + chunk, progress.total_pages) &&
        progress.next_page === progress.completed_pages + 1 &&
        receipt.artifacts.every((item: any) => !item.exists && item.regular === null)
      );
    }
    const pdf = artifacts.get(context.recoveryPdf) as any;
    const text = artifacts.get(context.recoveryText) as any;
    const manifest = artifacts.get(context.manifest) as any;
    return (
      ["created", "reconciled"].includes(receipt.terminal.disposition) &&
      receipt.state === "committed" && receipt.progress === null &&
      pdf.exists && pdf.regular === true && pdf.pages === context.ocrGeneration.source.pages &&
      text.exists && text.regular === true && text.utf8 === true && text.size > 0 &&
      (config.kind === "book" || text.non_whitespace_chars > 0) &&
      manifest.exists && manifest.regular === true && manifest.size > 0
    );
  },
  envelope: ({ materialKey }: any, refs: any) => ({
    schema_version: "quasi.stage.request/0.2",
    operation: config.operation,
    stage: "Prepare",
    material_key: materialKey,
    effect: "writer",
    objective: "Advance at most one range of the exact shared OCR generation.",
    source: refs.sourceFact,
    generation: {
      generation_key: refs.generationKey,
      profile: refs.profile,
      config_fingerprint: refs.configFingerprint,
      expected_state: refs.expectedState,
      expected_progress: refs.expectedProgress,
    },
    refs: refs.pathsFact,
    capabilities: [
      `quasi-extract ocr-generation --kind ${config.kind} --slug ${posixSingleQuote(refs.slug)} --source-file ${posixSingleQuote(refs.source)} --expected-source-sha256 ${posixSingleQuote(refs.sourceFact.sha256)} --generation-key ${posixSingleQuote(refs.generationKey)} --profile ${posixSingleQuote(refs.profile.name)} --json`,
    ],
    execution_contract: [
      "Run the exact ocr-generation capability at most once in this invocation.",
      "Do not background the process, run generic new-work OCR, or write fixed legacy paths.",
      "Preserve the CLI receipt exactly; if the outcome is unclear, stop without replay.",
    ],
  }),
});
