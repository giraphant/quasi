import {
  stageContract,
  stageReceiptSchema,
} from "../stage.mjs";

const TALK_HASH_PATTERN = "^[a-f0-9]{64}$";

const artifactObservationSchema = (path) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: ["path", "sha256"],
  properties: {
    path: { const: path },
    sha256: { type: "string", pattern: TALK_HASH_PATTERN },
  },
});

const generationObservationSchema = (manifest) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: ["manifest_path", "request_fingerprint"],
  properties: {
    manifest_path: { const: manifest },
    request_fingerprint: {
      type: "string",
      pattern: TALK_HASH_PATTERN,
    },
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
    sha256: { type: "string", pattern: TALK_HASH_PATTERN },
    size: { type: "integer", minimum: 1 },
  },
};

const TALK_PREPARE_STEP_SCHEMA = {
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

export const talkPrepareStageSchema = ({
  materialKey,
  slug,
  media,
  processingDir,
  manifest,
  prepared,
  transcript,
  subtitle,
  canonical,
}) =>
  stageReceiptSchema({
    operation: "talk.prepare",
    stage: "Prepare",
    materialKey,
    effect: "writer",
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
      source_observation:
        artifactObservationSchema(media),
      generation_observation:
        generationObservationSchema(manifest),
      classification: {
        type: "string",
        enum: ["live", "dead", "empty", "unclassified"],
      },
      transcript_changed: { type: "boolean" },
      canonical_observation:
        artifactObservationSchema(canonical),
      canonical_action: {
        type: ["string", "null"],
        enum: ["create", "repair", "reconciled", null],
      },
      artifacts: {
        type: "array",
        maxItems: 8,
        items: artifactSchema,
      },
      steps: {
        type: "array",
        maxItems: 32,
        items: TALK_PREPARE_STEP_SCHEMA,
      },
      diagnostics: {
        type: "array",
        maxItems: 32,
        items: { type: "string", maxLength: 4000 },
      },
    },
  });

export const TALK_PREPARE_STAGE_CONTRACT = stageContract({
  schema: talkPrepareStageSchema({
    materialKey: "talk:placeholder",
    slug: "placeholder",
    media: "input.wav",
    processingDir: "processing/talks/placeholder",
    manifest: "processing/talks/placeholder/manifest.json",
    prepared: "vault/talks/placeholder/recording.mp4",
    transcript: "vault/talks/placeholder/transcript.md",
    subtitle: "vault/talks/placeholder/recording.srt",
    canonical: "vault/talks/placeholder/talk.md",
  }),
  complete: (receipt, context) => {
    const allowed = new Set([
      context.prepared,
      context.transcript,
      context.subtitle,
      context.canonical,
      ...context.engines.map(
        (engine) =>
          `${context.processingDir}/transcript.${engine}.srt`,
      ),
    ]);
    return (
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
});

export function talkPrepareStagePrompt(state, repairDiagnostics = []) {
  return JSON.stringify(
    {
      schema_version: "quasi.stage.talk-prepare.request/0.1",
      operation: "talk.prepare",
      stage: "Prepare",
      material_key: state.materialKey,
      effect: "writer",
      objective:
        "Produce, reconcile, and classify the exact transcript generation needed by this Talk.",
      identity: {
        slug: state.slug,
        title: state.title,
        date: state.date,
        language: state.lang,
      },
      refs: {
        media: state.media,
        prepared_media: state.prepared,
        processing_dir: state.processingDir,
        manifest: state.manifest,
        transcript: state.transcript,
        subtitle: state.subtitle,
        canonical: state.canonical,
      },
      engines: state.engines,
      prepare_media: state.prepareMedia,
      capabilities: [
        "quasi-transcribe observe ... --json",
        "quasi-transcribe prepare-media ... --json",
        "quasi-transcribe run ... --json",
        "quasi-transcribe classify ... --json",
        "quasi-transcribe silent ... --json",
        "Read exact transcript artifacts",
      ],
      canonical_policy: {
        live:
          "Observe the exact canonical only. Analyse owns creation or refresh.",
        dead_or_empty:
          "Use quasi-transcribe silent to create, reconcile, or repair the exact canonical before completing Prepare.",
      },
      repair_diagnostics: repairDiagnostics,
    },
    null,
    2,
  );
}
