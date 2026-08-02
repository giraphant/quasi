import { PAPER_ARTIFACT_CONTRACT } from "../../artifact-contracts/generated.mjs";
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

const issueSchema = (operation, code) => ({
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
    code: { const: code },
    operation: { const: operation },
    summary: { type: "string", minLength: 1, maxLength: 4000 },
    user_question: { type: ["string", "null"], maxLength: 4000 },
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

const preparedArtifactSchema = (paths) => ({
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

const actionPayloads = ({ mode }) => ({
  complete: {
    required: ["action"],
    properties: {
      action: {
        type: "string",
        enum:
          mode === "create"
            ? ["create", "reconciled"]
            : ["repair", "reconciled"],
      },
    },
  },
  failed: {
    required: ["action"],
    properties: { action: { const: mode } },
  },
  blocked: {
    required: ["action"],
    properties: { action: { const: mode } },
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

export const paperOperationRows = [
  {
    operation: "paper.acquire",
    stage: "Acquire",
    effect: "writer",
    agentType: "quasi:download-agent",
    refs: ({ output, doi }) => ({ output, doi }),
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
      ((receipt.terminal.disposition === "created" &&
        receipt.write_state === "written") ||
        (receipt.terminal.disposition === "reused" &&
          receipt.write_state === "not_written")),
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
        "Read the exact output only to verify title, authors, and DOI evidence",
      ],
      output_path_rule:
        "Echo exact_output byte-for-byte as output_path in every terminal; a resolved or absolute CLI path is observation evidence only.",
    }),
  },
  {
    operation: "paper.prepare",
    stage: "Prepare",
    effect: "writer",
    agentType: "quasi:extract-agent",
    refs: ({ source, normalized, recoverySource, recoveryText }) => ({
      source,
      normalized,
      recoverySource,
      recoveryText,
    }),
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
          items: { const: "canonical" },
        },
      },
    }),
    terminalPayloads: actionPayloads,
    complete: (receipt, context) =>
      [
        ...(context.mode === "create" ? ["create"] : ["repair"]),
        "reconciled",
      ].includes(receipt.terminal.action),
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
  {
    operation: "paper.audit",
    stage: "Audit",
    effect: "writer",
    agentType: "quasi:audit-agent",
    refs: ({ target, pass }) => ({ target, pass }),
    payloadProperties: ({ target, pass }) => ({
      required: [
        "target_path",
        "pass",
        "artifact_roles",
        "remaining_violations",
        "escalated",
        "mutated_paths",
      ],
      properties: {
        target_path: { const: target },
        pass: { const: pass },
        artifact_roles: { const: ["canonical"] },
        remaining_violations: { type: "integer", minimum: 0 },
        escalated: {
          type: "array",
          items: AUDIT_DIAGNOSTIC_SCHEMA,
        },
        mutated_paths: {
          type: "array",
          uniqueItems: true,
          items: { type: "string" },
        },
      },
    }),
    complete: (receipt) =>
      receipt.remaining_violations === 0
        ? receipt.escalated.length === 0
        : receipt.remaining_violations === receipt.escalated.length,
    envelope: ({ materialKey }, { target, pass }) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "paper.audit",
      stage: "Audit",
      material_key: materialKey,
      effect: "writer",
      pass,
      mode: pass === 1 ? "audit" : "re-audit",
      target: { role: "canonical", path: target },
    }),
  },
];
