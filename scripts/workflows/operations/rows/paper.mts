import { PAPER_ARTIFACT_CONTRACT } from "../../artifact-contracts/generated.mjs";
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
  maxItems: 256,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["role", "path", "exists", "usable"],
    properties: {
      role: {
        type: "string",
        enum: ["normalized_text", "recovery_source"],
      },
      path: { type: "string", enum: paths },
      exists: { type: "boolean" },
      usable: { type: ["boolean", "null"] },
    },
  },
});

const quoteOrNull: AnyFunction = (value) =>
  value == null || value === "" ? null : posixSingleQuote(value);

export const paperOperationRows: OperationRow[] = [
  {
    operation: "paper.acquire",
    refs: ({ output, meta }) => ({ output, doi: meta.doi || null }),
    writeTargets: ({ output }) => [{ scope: "exact", path: output }],
    payloadProperties: ({ output, doi }) => ({
      required: [
        "output_path",
        "doi",
        "write_state",
        "identity_verified",
        "attempts",
      ],
      properties: {
        output_path: { const: output },
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
    envelope: ({ slug, meta, materialKey }, { output }) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "paper.acquire",
      stage: "Acquire",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Reconcile or obtain one identity-verified Paper source at the exact output path.",
      exact_output: output,
      refs: { output },
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
        exact_output: posixSingleQuote(output),
        expected_title: posixSingleQuote(meta.title),
        expected_author: posixSingleQuote(meta.authors[0]),
        doi: quoteOrNull(meta.doi),
        oa_url: quoteOrNull(meta.oa_url),
        url: quoteOrNull(meta.url),
      },
      capabilities: [
        "quasi-download paper fetch --slug SLUG (--doi DOI | --url URL ...) [--title TITLE] [--author AUTHOR] [--temp-dir DIR] --json",
        "quasi-download paper diagnose --url URL [--via-ezproxy] [--timeout SECONDS] --json",
        "quasi-download accept --path INPUT --slug SLUG --kind paper --json",
        "paper fetch may return identity_uncertain candidates; review each exact temp_path and inspect evidence, accept at most one, and remove the rejected returned temp paths",
        "Read the exact output only to verify title, authors, and DOI evidence",
      ],
      output_path_rule:
        "Echo exact_output byte-for-byte as output_path in every terminal; a resolved or absolute CLI path is observation evidence only.",
    }),
  },
  {
    operation: "paper.prepare",
    refs: ({ source, normalized, recoverySource, recoveryText }) => ({
      source,
      normalized,
      recoverySource,
      recoveryText,
    }),
    writeTargets: ({ normalized, recoverySource, recoveryText }) => [
      { scope: "exact", path: normalized },
      { scope: "exact", path: recoverySource },
      { scope: "exact", path: recoveryText },
    ],
    payloadProperties: (refs) => ({
      required: [
        "source_path",
        "selected_input",
        "artifacts",
        "steps",
        "diagnostics",
      ],
      properties: {
        source_path: { const: refs.source },
        selected_input: {
          type: ["string", "null"],
          enum: [refs.normalized, refs.recoveryText, null],
        },
        artifacts: preparedArtifactSchema([
          refs.normalized,
          refs.recoverySource,
          refs.recoveryText,
        ]),
        steps: { type: "array", maxItems: 64, items: PREPARE_STEP_SCHEMA },
        diagnostics: {
          type: "array",
          maxItems: 64,
          items: { type: "string", maxLength: 4000 },
        },
      },
    }),
    complete: (receipt, context) => {
      const allowed = new Set([
        context.normalized,
        context.recoverySource,
        context.recoveryText,
      ]);
      return (
        typeof receipt.selected_input === "string" &&
        receipt.artifacts.every((artifact: any) =>
          allowed.has(artifact.path),
        ) &&
        receipt.artifacts.some(
          (artifact: any) =>
            artifact.role === "normalized_text" &&
            artifact.path === receipt.selected_input &&
            artifact.exists === true &&
            artifact.usable === true,
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
        "Produce one readable normalized text for the exact accepted Paper source.",
      refs: {
        source: refs.source,
        normalized: refs.normalized,
        recovery_source: refs.recoverySource,
        recovery_text: refs.recoveryText,
      },
      capabilities: [
        "quasi-extract text INPUT OUTPUT --json",
        "quasi-extract ocr INPUT OUTPUT --no-clobber --json",
        "Read exact normalized text artifacts",
      ],
      artifact_roles: ["normalized_text", "recovery_source"],
    }),
  },
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
