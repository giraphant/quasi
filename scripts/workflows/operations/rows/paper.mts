import { PAPER_ARTIFACT_CONTRACT } from "../../artifact-contracts/generated.mjs";
import { InputContractError } from "../../context-base.mts";
import { parsePaperSourceCandidate } from "../../contracts/paper.mts";
import { makeOcrGenerationRow } from "./ocr-generation.mts";
import {
  ATTEMPT_SCHEMA,
  PREPARE_STEP_SCHEMA,
  actionPayloads,
  issueSchema,
  makeAuditRow,
  posixSingleQuote,
} from "../shared.mts";
import type { OperationRow } from "../../artifact-contracts/generated.mjs";

type AnyFunction = (...args: any[]) => any;

const preparedArtifactSchema: AnyFunction = (paths) => ({
  type: "array",
  minItems: 1,
  maxItems: paths.length,
  uniqueItems: true,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["role", "path", "exists", "usable"],
    properties: {
      role: { const: "normalized_text" },
      path: { type: "string", enum: paths },
      exists: { type: "boolean" },
      usable: { type: ["boolean", "null"] },
    },
  },
});

const generationTextPath = (slug: string, generationKey: string): string =>
  `processing/papers/${slug}/ocr-generations/${generationKey}/ocr.txt`;

const paperPrepareContext: AnyFunction = (rawContext, base) => {
  const source = rawContext.source;
  const input = rawContext.input ?? source;
  const sourceCandidate = parsePaperSourceCandidate(rawContext.sourceCandidate);
  const sourcePdf = `sources/${base.slug}.pdf`;
  const sourceText = `sources/${base.slug}.txt`;
  if (![sourcePdf, sourceText].includes(source))
    throw new InputContractError(
      "paper.prepare source must be one declared Paper source",
    );
  if (
    sourceCandidate === null ||
    sourceCandidate.path !== source ||
    sourceCandidate.format !== (source === sourcePdf ? "pdf" : "txt")
  )
    throw new InputContractError(
      "paper.prepare source candidate must bind the exact observed source",
    );
  if (input === source)
    return {
      ...base,
      source,
      sourceCandidate,
      input,
      inputKind: source === sourcePdf ? "source_pdf" : "source_text",
      generationKey: null,
    };
  const generationKey = rawContext.generationKey;
  if (
    source !== sourcePdf ||
    typeof generationKey !== "string" ||
    !/^[0-9a-f]{64}$/.test(generationKey) ||
    input !== generationTextPath(base.slug, generationKey)
  )
    throw new InputContractError(
      "paper.prepare generation input must be the exact committed OCR text",
    );
  return {
    ...base,
    source,
    sourceCandidate,
    input,
    inputKind: "generation_text",
    generationKey,
  };
};

const quoteOrNull: AnyFunction = (value) =>
  value == null || value === "" ? null : posixSingleQuote(value);

export const paperOperationRows: OperationRow[] = [
  {
    operation: "paper.acquire",
    refs: ({ outputPdf, outputText, meta }) => ({
      outputPdf,
      outputText,
      doi: meta.doi || null,
    }),
    writeTargets: ({ outputPdf, outputText }) => [
      { scope: "exact", path: outputPdf },
      { scope: "exact", path: outputText },
    ],
    payloadProperties: ({ outputPdf, outputText, doi }) => ({
      required: [
        "output_path",
        "doi",
        "write_state",
        "identity_verified",
        "attempts",
      ],
      properties: {
        output_path: { type: "string", enum: [outputPdf, outputText] },
        doi: { const: doi },
        write_state: {
          type: "string",
          enum: ["written", "not_written", "unknown"],
        },
        identity_verified: { type: "boolean" },
        attempts: ATTEMPT_SCHEMA,
      },
    }),
    // source identifies the accepted source only on a complete terminal.
    terminalPayloads: () => ({
      complete: {
        required: ["source"],
        properties: {
          source: { type: "string", minLength: 1, maxLength: 200 },
        },
      },
      failed: {
        properties: {
          attempts: { ...ATTEMPT_SCHEMA, minItems: 1 },
          issue: issueSchema("paper.acquire", "paper.download_failed"),
        },
      },
      blocked: {
        properties: {
          issue: issueSchema("paper.acquire", "paper.acquire_blocked"),
        },
      },
    }),
    complete: (receipt) =>
      receipt.identity_verified === true &&
      (receipt.write_state === "written" ||
        receipt.write_state === "not_written"),
    envelope: ({ slug, meta, materialKey }, { outputPdf, outputText }) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "paper.acquire",
      stage: "Acquire",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Reconcile or obtain one identity-verified Paper source at exactly one allowed output path.",
      allowed_outputs: [
        { format: "pdf", path: outputPdf },
        { format: "txt", path: outputText },
      ],
      refs: { output_pdf: outputPdf, output_text: outputText },
      identity: {
        slug,
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
        journal: meta.journal,
        doi: meta.doi || null,
        oa_url: meta.oa_url || null,
        url: meta.url || null,
        confidence:
          meta.confidence === "verified" ? "verified" : "provided",
      },
      identity_contract: PAPER_ARTIFACT_CONTRACT.identity,
      shell_argv: {
        slug: posixSingleQuote(slug),
        exact_output_pdf: posixSingleQuote(outputPdf),
        exact_output_text: posixSingleQuote(outputText),
        expected_title: posixSingleQuote(meta.title),
        expected_author: posixSingleQuote(meta.authors[0]),
        doi: quoteOrNull(meta.doi),
        oa_url: quoteOrNull(meta.oa_url),
        url: quoteOrNull(meta.url),
      },
      capabilities: [
        "quasi-download paper fetch --slug SLUG (--doi DOI | --url URL ...) [--title TITLE] [--author AUTHOR] [--temp-dir DIR] [--budget-seconds 30..540] --json",
        "quasi-download paper diagnose --url URL [--via-ezproxy] [--timeout SECONDS] --json",
        "quasi-search kagi ...",
        "quasi-download accept --path INPUT --slug SLUG --kind paper --json",
        "Use available deterministic local tools to inspect or normalize fetched content into one allowed PDF or UTF-8 text output format in the same temporary directory",
        "paper fetch may return identity_uncertain candidates; review each exact temp_path and inspect evidence, accept at most one, and remove the rejected returned temp paths",
        "Read the exact output only to verify title, authors, and DOI evidence",
      ],
      output_path_rule:
        "Echo one allowed_outputs[].path byte-for-byte as output_path in every terminal; a resolved or absolute CLI path is observation evidence only.",
    }),
  },
  {
    operation: "paper.prepare",
    context: paperPrepareContext,
    refs: ({
      source,
      sourceCandidate,
      input,
      inputKind,
      generationKey,
      sourcePdf,
      sourceText,
      normalized,
      legacyRecoverySource,
      legacyRecoveryText,
    }) => {
      const expectedInput =
        inputKind === "generation_text"
          ? generationTextPath(
              sourcePdf.slice("sources/".length, -".pdf".length),
              generationKey,
            )
          : source;
      if (input !== expectedInput)
        throw new InputContractError(
          "paper.prepare input does not match its declared role",
        );
      return {
        source,
        sourceCandidate,
        input,
        inputKind,
        generationKey,
        sourcePdf,
        sourceText,
        normalized,
        legacyRecoverySource,
        legacyRecoveryText,
      };
    },
    writeTargets: ({ normalized }) => [
      { scope: "exact", path: normalized },
    ],
    payloadProperties: (refs) => {
      const selected =
        refs.inputKind === "generation_text" ? refs.input : refs.normalized;
      return {
        required: [
          "source_path",
          "input_path",
          "input_kind",
          "selected_input",
          "artifacts",
          "steps",
          "diagnostics",
        ],
        properties: {
          source_path: { const: refs.source },
          input_path: { const: refs.input },
          input_kind: { const: refs.inputKind },
          selected_input: {
            type: ["string", "null"],
            enum: [selected, null],
          },
          artifacts: preparedArtifactSchema(
            refs.inputKind === "generation_text"
              ? [refs.input]
              : [refs.normalized],
          ),
          steps: { type: "array", maxItems: 64, items: PREPARE_STEP_SCHEMA },
          diagnostics: {
            type: "array",
            maxItems: 64,
            items: { type: "string", maxLength: 4000 },
          },
        },
      };
    },
    terminalPayloads: (refs) => ({
      complete: {
        required: ["disposition"],
        properties: {
          disposition: {
            type: "string",
            enum: ["full_text_prepared", "ocr_required"],
          },
        },
      },
      failed: {
        properties: {
          issue: issueSchema(
            "paper.prepare",
            refs.inputKind === "generation_text"
              ? "paper.ocr_unreadable"
              : refs.inputKind === "source_text"
                ? "paper.source_incomplete"
                : "paper.prepare_failed",
          ),
        },
      },
      blocked: {
        properties: {
          issue: issueSchema("paper.prepare", "paper.prepare_blocked"),
        },
      },
    }),
    complete: (receipt, context) => {
      const disposition = receipt.terminal.disposition;
      const selected =
        context.inputKind === "generation_text"
          ? context.input
          : context.normalized;
      const allowed = new Set(
        context.inputKind === "generation_text"
          ? [context.input]
          : [context.normalized],
      );
      const artifactsAreBound = receipt.artifacts.every((artifact: any) =>
        allowed.has(artifact.path),
      );
      if (disposition === "full_text_prepared")
        return (
          receipt.selected_input === selected &&
          artifactsAreBound &&
          receipt.artifacts.some(
            (artifact: any) =>
              artifact.role === "normalized_text" &&
              artifact.path === selected &&
              artifact.exists === true &&
              artifact.usable === true,
          )
        );
      return (
        disposition === "ocr_required" &&
        context.inputKind === "source_pdf" &&
        receipt.selected_input === null &&
        artifactsAreBound &&
        receipt.artifacts.some(
          (artifact: any) =>
            artifact.role === "normalized_text" &&
            artifact.path === context.normalized &&
            artifact.exists === true &&
            artifact.usable === false,
        ) &&
        receipt.artifacts.every(
          (artifact: any) => artifact.usable !== true,
        )
      );
    },
    envelope: ({ materialKey }, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "paper.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        refs.inputKind === "generation_text"
          ? "Semantically verify the exact committed Paper OCR generation text."
          : "Extract and semantically verify readable text from the exact accepted Paper source.",
      source: refs.sourceCandidate,
      input: { role: refs.inputKind, path: refs.input },
      refs: {
        normalized: refs.normalized,
        legacy_recovery_source: refs.legacyRecoverySource,
        legacy_recovery_text: refs.legacyRecoveryText,
      },
      capabilities:
        refs.inputKind === "generation_text"
          ? [
              "Read only the exact generation_text input named by this request; do not read or compare the fixed normalized or legacy recovery refs.",
            ]
          : [
              `quasi-extract text ${posixSingleQuote(refs.input)} ${posixSingleQuote(refs.normalized)} --json`,
              "Read the exact input and normalized text artifacts named by this request",
            ],
      legacy_recovery_rule:
        "The fixed legacy recovery refs are read-only evidence. Never write, replace, delete, rename, link, or select them.",
      disposition_contract: {
        full_text_prepared:
          "Return only after selected_input was actually read and contains the complete substantive Paper, not a landing page, abstract, preview, or metadata shell.",
        ocr_required:
          "Allowed only for a direct PDF input whose extracted normalized text exists but is semantically unusable.",
      },
      artifact_roles: ["normalized_text"],
    }),
  },
  makeOcrGenerationRow({ operation: "paper.ocr", kind: "paper", validationPolicy: "paper-text-v1" }),
  {
    operation: "paper.analyse",
    context: (rawContext, base) => ({
      ...base,
      input: rawContext.input,
    }),
    refs: ({ input, output, mode }) => ({ input, output, mode }),
    writeTargets: ({ output }) => [{ scope: "exact", path: output }],
    payloadProperties: ({ input, output }) => ({
      required: ["input_path", "output_path", "artifact_roles"],
      properties: {
        input_path: { const: input },
        output_path: { const: output },
        artifact_roles: {
          type: "array",
          minItems: 1,
          maxItems: 1,
          items: { const: "canonical" },
        },
      },
    }),
    terminalPayloads: actionPayloads,
    complete: (receipt, context) =>
      [
        ...(context.mode === "create" ? ["create"] : ["repair"]),
        "reconciled",
      ].includes(receipt.terminal.action as string),
    envelope: ({ meta, materialKey, diagnostics }, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "paper.analyse",
      stage: "Analyse",
      material_key: materialKey,
      input: { role: "normalized_text", path: refs.input },
      output: { role: "canonical", path: refs.output },
      identity: {
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
        doi: meta.doi || null,
        journal: meta.journal,
        confidence:
          meta.confidence === "verified" ? "verified" : "provided",
      },
      artifact_contract: PAPER_ARTIFACT_CONTRACT,
      frontmatter_seed: {
        type: "paper",
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
        journal: meta.journal,
        doi: meta.doi || null,
      },
      mode: refs.mode,
      overwrite: refs.mode === "repair",
      repair_diagnostics:
        refs.mode === "repair" ? diagnostics : [],
    }),
    promptText: (request) =>
      `Execute exactly one paper.analyse operation using this self-contained JSON request.
Do not reinterpret it as another operation and do not read project instruction files.
${JSON.stringify(request, null, 2)}`,
  },
  makeAuditRow({
    operation: "paper.audit",
    refs: ({ target, pass }) => ({ target, pass }),
    artifactRoles: ["canonical"],
    targetRole: "canonical",
    targetScope: "exact",
    exactPaths: true,
  }),
];
