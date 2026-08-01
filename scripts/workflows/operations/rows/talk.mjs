import { TALK_ARTIFACT_CONTRACT } from "../../artifact-contracts/generated.mjs";
import { validText } from "../../runtime.mjs";
import { defineOperation } from "../define.mjs";

const HASH_PATTERN = "^[a-f0-9]{64}$";

const observationSchema = (path) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: ["path", "sha256"],
  properties: {
    path: { const: path },
    sha256: { type: "string", pattern: HASH_PATTERN },
  },
});

const generationSchema = (manifest) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: ["manifest_path", "request_fingerprint"],
  properties: {
    manifest_path: { const: manifest },
    request_fingerprint: { type: "string", pattern: HASH_PATTERN },
  },
});

const artifactSchema = {
  type: "object",
  additionalProperties: false,
  required: ["role", "path", "sha256", "size"],
  properties: {
    role: {
      type: "string",
      enum: [
        "prepared_media",
        "transcript",
        "subtitle",
        "engine_transcript",
        "canonical",
      ],
    },
    path: { type: "string" },
    sha256: { type: "string", pattern: HASH_PATTERN },
    size: { type: "integer", minimum: 1 },
  },
};

const PREPARE_STEP_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["capability", "outcome", "summary"],
  properties: {
    capability: { type: "string", minLength: 1, maxLength: 100 },
    outcome: {
      type: "string",
      enum: ["observed", "created", "reused", "replaced", "failed"],
    },
    summary: { type: "string", minLength: 1, maxLength: 2000 },
  },
};

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

export const TALK_EVIDENCE_RULES = [
  "inputs[0] 是 committed primary transcript，其余 inputs 是同一 generation 的 per-engine SRT evidence",
  "对照时间戳、人名、同音词和专业术语；优先采用多引擎一致且符合实际语境的内容",
  "引文、人物、著作和时间脉络必须能在 transcript evidence 中定位",
];

export const talkOperationRows = [
  {
    operation: "talk.prepare",
    stage: "Prepare",
    effect: "writer",
    agentType: "quasi:transcribe-agent",
    refs: (
      {
        slug,
        media,
        processingDir,
        manifest,
        prepared,
        transcript,
        subtitle,
        canonical,
      },
    ) => ({
      slug,
      media,
      processingDir,
      manifest,
      prepared,
      transcript,
      subtitle,
      canonical,
    }),
    payloadProperties: ({ slug, media, manifest, canonical }) => ({
      required: [
        "slug",
        "source_observation",
        "generation_observation",
        "classification",
        "transcript_changed",
        "canonical_observation",
        "canonical_action",
        "artifacts",
        "steps",
        "diagnostics",
      ],
      properties: {
        slug: { const: slug },
        source_observation: observationSchema(media),
        generation_observation: generationSchema(manifest),
        classification: {
          type: "string",
          enum: ["live", "dead", "empty", "unclassified"],
        },
        transcript_changed: { type: "boolean" },
        canonical_observation: observationSchema(canonical),
        canonical_action: {
          type: ["string", "null"],
          enum: ["create", "repair", "reconciled", null],
        },
        artifacts: { type: "array", maxItems: 8, items: artifactSchema },
        steps: { type: "array", maxItems: 32, items: PREPARE_STEP_SCHEMA },
        diagnostics: {
          type: "array",
          maxItems: 32,
          items: { type: "string", maxLength: 4000 },
        },
      },
    }),
    complete: (receipt, context) => {
      const allowed = new Set([
        context.prepared,
        context.transcript,
        context.subtitle,
        context.canonical,
        ...context.engines.map(
          (engine) => `${context.processingDir}/transcript.${engine}.srt`,
        ),
      ]);
      return (
        receipt.slug === context.slug &&
        receipt.source_observation !== null &&
        receipt.source_observation.path === context.media &&
        receipt.generation_observation !== null &&
        receipt.generation_observation.manifest_path === context.manifest &&
        ["live", "dead", "empty"].includes(receipt.classification) &&
        (receipt.canonical_observation === null ||
          (receipt.canonical_observation.path === context.canonical &&
            receipt.canonical_observation.sha256 !== "0".repeat(64))) &&
        receipt.artifacts.every((row) => allowed.has(row.path)) &&
        receipt.artifacts.some(
          (row) => row.role === "transcript" && row.path === context.transcript,
        ) &&
        (receipt.classification === "live"
          ? receipt.canonical_action === null &&
            !receipt.artifacts.some((row) => row.role === "canonical")
          : receipt.canonical_observation !== null &&
            ["create", "repair", "reconciled"].includes(
              receipt.canonical_action,
            ) &&
            receipt.artifacts.some(
              (row) =>
                row.role === "canonical" &&
                row.path === context.canonical &&
                row.sha256 === receipt.canonical_observation.sha256,
            )) &&
        (!context.repair || receipt.canonical_action === "repair")
      );
    },
    envelope: (
      {
        materialKey,
        slug,
        title,
        date,
        language,
        engines,
        prepareMedia,
        repairDiagnostics,
      },
      refs,
    ) => ({
      schema_version: "quasi.stage.talk-prepare.request/0.1",
      operation: "talk.prepare",
      stage: "Prepare",
      material_key: materialKey,
      effect: "writer",
      objective:
        "Produce, reconcile, and classify the exact transcript generation needed by this Talk.",
      identity: { slug, title, date, language },
      refs: {
        media: refs.media,
        prepared_media: refs.prepared,
        processing_dir: refs.processingDir,
        manifest: refs.manifest,
        transcript: refs.transcript,
        subtitle: refs.subtitle,
        canonical: refs.canonical,
      },
      engines,
      prepare_media: prepareMedia,
      capabilities: [
        "quasi-transcribe observe ... --json",
        "quasi-transcribe prepare-media ... --json",
        "quasi-transcribe run ... --json",
        "quasi-transcribe classify ... --json",
        "quasi-transcribe silent ... --json",
        "Read exact transcript artifacts",
      ],
      canonical_policy: {
        live: "Observe the exact canonical only. Analyse owns creation or refresh.",
        dead_or_empty:
          "Use quasi-transcribe silent to create, reconcile, or repair the exact canonical before completing Prepare.",
      },
      repair_diagnostics: repairDiagnostics,
    }),
  },
  {
    operation: "talk.analyse",
    stage: "Analyse",
    effect: "writer",
    agentType: "quasi:analyse-agent",
    refs: ({ inputs, output, mode }) => ({ inputs, output, mode }),
    payloadProperties: ({ inputs, output }) => ({
      required: [
        "input_paths",
        "input_sha256s",
        "output_path",
        "artifact_roles",
      ],
      properties: {
        input_paths: { const: inputs.map((input) => input.path) },
        input_sha256s: { const: inputs.map((input) => input.sha256) },
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
    envelope: (
      { materialKey, title, date, media, diagnostics },
      { inputs, output, mode },
    ) => ({
      schema_version: "quasi.operation.talk.analyse.request/0.1",
      operation: "talk.analyse",
      stage: "Analyse",
      material_key: materialKey,
      inputs: inputs.map((input) => ({
        role: input.role,
        path: input.path,
        sha256: input.sha256,
        size: input.size,
      })),
      output: { role: "canonical", path: output },
      identity: { title, date, media },
      artifact_contract: TALK_ARTIFACT_CONTRACT,
      frontmatter_seed: { type: "talk", title, date, media },
      evidence_rules: TALK_EVIDENCE_RULES,
      mode,
      overwrite: mode === "repair",
      repair_diagnostics: mode === "repair" ? diagnostics : [],
    }),
    promptText: (request) =>
      `Execute exactly one talk.analyse operation from this self-contained JSON request.\nDo not reinterpret it as another operation or read project instruction files.\n${JSON.stringify(request, null, 2)}`,
  },
  {
    operation: "talk.audit",
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
        escalated: { type: "array", items: AUDIT_DIAGNOSTIC_SCHEMA },
        mutated_paths: {
          type: "array",
          uniqueItems: true,
          items: { type: "string" },
        },
      },
    }),
    complete: (receipt) =>
      receipt.escalated.every(
        (item) =>
          validText(item.path, 1, 2048) &&
          validText(item.kind, 1, 200) &&
          validText(item.reason, 1, 4000),
      ) &&
      receipt.mutated_paths.every((path) => validText(path, 1, 2048)) &&
      (receipt.remaining_violations === 0
        ? receipt.escalated.length === 0
        : receipt.remaining_violations === receipt.escalated.length),
    envelope: ({ materialKey }, { target, pass }) => ({
      schema_version: "quasi.operation.talk.audit.request/0.1",
      operation: "talk.audit",
      stage: "Audit",
      material_key: materialKey,
      effect: "writer",
      pass,
      mode: pass === 1 ? "audit" : "re-audit",
      target: { role: "canonical", path: target },
      exact_output: target,
      composite_debt: true,
    }),
  },
];

export const talkOperations = Object.fromEntries(
  talkOperationRows.map((row) => [row.operation, defineOperation(row)]),
);

export const talkPrepare = talkOperations["talk.prepare"];
export const talkAnalyse = talkOperations["talk.analyse"];
export const talkAudit = talkOperations["talk.audit"];
