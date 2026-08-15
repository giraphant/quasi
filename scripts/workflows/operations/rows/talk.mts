import { TALK_ARTIFACT_CONTRACT } from "../../artifact-contracts/generated.mjs";
import { actionPayloads, makeAuditRow } from "../shared.mts";
import type { OperationRow } from "../../artifact-contracts/generated.mjs";

type AnyFunction = (...args: any[]) => any;

const HASH_PATTERN = "^[a-f0-9]{64}$";

const observationSchema: AnyFunction = (path) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: ["path", "sha256"],
  properties: {
    path: { const: path },
    sha256: { type: "string", pattern: HASH_PATTERN },
  },
});

const generationSchema: AnyFunction = (manifest) => ({
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

export const TALK_EVIDENCE_RULES = [
  "inputs[0] 是 committed primary transcript，其余 inputs 是同一 generation 的 per-engine SRT evidence",
  "对照时间戳、人名、同音词和专业术语；优先采用多引擎一致且符合实际语境的内容",
  "引文、人物和著作必须能在 transcript evidence 中定位",
  "分节摘要的每组起止时间与时间脉络的每个时间点必须逐项对照 transcript evidence 定位，不得用相邻分节边界作未核对的推算",
];

export const talkOperationRows: OperationRow[] = [
  {
    operation: "talk.prepare",
    context: (_rawContext, base) => ({
      ...base,
      title: base.meta.title,
      date: base.meta.date,
      language: base.meta.language || "auto",
      engines: base.meta.engines || ["soniox", "apple", "parakeet"],
      media: base.meta.media,
      prepareMedia: Boolean(base.meta.prepareMedia),
      repairDiagnostics: base.diagnostics,
      repair: base.mode === "repair",
    }),
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
    writeTargets: (
      { processingDir, manifest, prepared, transcript, subtitle, canonical },
      { engines },
    ) => [
      { scope: "exact", path: manifest },
      { scope: "exact", path: prepared },
      { scope: "exact", path: transcript },
      { scope: "exact", path: subtitle },
      { scope: "exact", path: canonical },
      ...engines.map((engine: any) => ({
        scope: "exact" as const,
        path: `${processingDir}/transcript.${engine}.srt`,
      })),
    ],
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
      const engineTranscripts = new Set<string>(
        context.engines.map(
          (engine: any): string =>
            `${context.processingDir}/transcript.${engine}.srt`,
        ),
      );
      const rolePaths: Record<string, Set<string>> = {
        prepared_media: new Set([context.prepared]),
        transcript: new Set([context.transcript]),
        subtitle: new Set([context.subtitle]),
        engine_transcript: engineTranscripts,
        canonical: new Set([context.canonical]),
      };
      const artifactPaths = receipt.artifacts.map((row: any) => row.path);
      return (
        receipt.source_observation !== null &&
        receipt.source_observation.path === context.media &&
        receipt.generation_observation !== null &&
        receipt.generation_observation.manifest_path === context.manifest &&
        ["live", "dead", "empty"].includes(receipt.classification) &&
        (receipt.canonical_observation === null ||
          (receipt.canonical_observation.path === context.canonical &&
            receipt.canonical_observation.sha256 !== "0".repeat(64))) &&
        new Set(artifactPaths).size === artifactPaths.length &&
        receipt.artifacts.every((row: any) =>
          rolePaths[row.role]?.has(row.path),
        ) &&
        receipt.artifacts.some(
          (row: any) =>
            row.role === "transcript" && row.path === context.transcript,
        ) &&
        receipt.artifacts.some(
          (row: any) =>
            row.role === "engine_transcript" &&
            engineTranscripts.has(row.path),
        ) &&
        (receipt.classification === "live"
          ? receipt.canonical_action === null &&
            !receipt.artifacts.some(
              (row: any) => row.role === "canonical",
            )
          : receipt.canonical_observation !== null &&
            ["create", "repair", "reconciled"].includes(
              receipt.canonical_action,
            ) &&
            receipt.artifacts.some(
              (row: any) =>
                row.role === "canonical" &&
                row.path === context.canonical &&
                row.sha256 === receipt.canonical_observation.sha256,
            )) &&
        (!context.repair ||
          (receipt.classification === "live"
            ? receipt.canonical_action === null
            : receipt.canonical_action === "repair"))
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
      schema_version: "quasi.stage.request/0.2",
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
    context: (rawContext, base) => ({
      ...base,
      title: base.meta.title,
      date: base.meta.date,
      media: base.meta.media,
      inputs: rawContext.inputs || [],
    }),
    refs: ({ inputs, output, mode }) => ({ inputs, output, mode }),
    writeTargets: ({ output }) => [{ scope: "exact", path: output }],
    payloadProperties: ({ inputs, output }) => ({
      required: [
        "input_paths",
        "input_sha256s",
        "output_path",
        "artifact_roles",
      ],
      properties: {
        input_paths: {
          const: inputs.map((input: any) => input.path),
        },
        input_sha256s: {
          const: inputs.map((input: any) => input.sha256),
        },
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
    envelope: (
      { materialKey, title, date, media, diagnostics },
      { inputs, output, mode },
    ) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "talk.analyse",
      stage: "Analyse",
      material_key: materialKey,
      inputs: inputs.map((input: any) => ({
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
  makeAuditRow({
    operation: "talk.audit",
    refs: ({ target, pass }) => ({ target, pass }),
    artifactRoles: ["canonical"],
    targetRole: "canonical",
    targetScope: "exact",
    exactPaths: true,
    envelopeExtras: (_context, { target }) => ({
      afterTarget: { exact_output: target, composite_debt: true },
    }),
  }),
];
