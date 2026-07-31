import {
  stageContract,
  stageReceiptSchema,
} from "../stage.mjs";
import {
  composedSchema,
  posixSingleQuote,
} from "./shared.mjs";

const TALK_HASH_PATTERN = "^[a-f0-9]{64}$";

// Claude StructuredOutput may apply a sibling `pattern` to the null arm of a
// type union. Keep absence and a verified digest in separate schema branches.
const nullableHashSchema = {
  anyOf: [
    { type: "null" },
    { type: "string", pattern: TALK_HASH_PATTERN },
  ],
};

const failureSchema = (operationKey) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "code",
    "operation_key",
    "outcome",
    "retryable",
    "message",
  ],
  properties: {
    code: { type: "string" },
    operation_key: { const: operationKey },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: false },
    message: { type: ["string", "null"] },
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

export const TALK_RENDER_SILENT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "material_key",
    "input_path",
    "output_path",
    "artifact_roles",
    "classification_signal",
    "action",
    "output_sha256",
    "size",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.render-silent.receipt/0.1",
    },
    key: { const: "talk.render-silent" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    material_key: { type: "string" },
    input_path: { type: "string" },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "canonical" },
    },
    classification_signal: {
      type: "string",
      enum: ["dead", "empty"],
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    output_sha256: { type: ["string", "null"] },
    size: { type: "integer", minimum: 0 },
    failure: failureSchema("talk.render-silent"),
  },
};

const failureBranch = (outcome) => ({
  type: "object",
  required: ["outcome"],
  properties: { outcome: { const: outcome } },
});

export const talkRenderSilentSchema = ({
  materialKey,
  input,
  output,
  signal,
  mode,
}) =>
  composedSchema(
    TALK_RENDER_SILENT_SCHEMA,
    {
      material_key: { const: materialKey },
      input_path: { const: input },
      output_path: { const: output },
      classification_signal: { const: signal },
    },
    {
      succeeded: {
        properties: {
          status: { const: "succeeded" },
          failure: { type: "null" },
          output_sha256: {
            type: "string",
            pattern: TALK_HASH_PATTERN,
          },
          size: { minimum: 1 },
          action:
            mode === "create"
              ? { const: "create" }
              : { enum: ["repair", "reconciled"] },
        },
      },
      failed: {
        properties: {
          status: { const: "failed" },
          output_sha256: { type: "null" },
          action: { const: mode },
          failure: failureBranch("known"),
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          output_sha256: { type: "null" },
          action: { const: mode },
          failure: failureBranch("unknown"),
        },
      },
    },
  );

export const TALK_RENDER_SILENT_CONTRACT = {
  schema: TALK_RENDER_SILENT_SCHEMA,
};

const command = (tokens) => tokens.map(posixSingleQuote).join(" ");

export function talkRenderSilentPrompt(
  state,
  transcriptPath,
  signal,
  mode = "create",
  diagnostics = [],
) {
  return JSON.stringify(
    {
      schema_version: "quasi.operation.talk.render-silent.request/0.1",
      operation: "talk.render-silent",
      material_key: state.materialKey,
      identity: {
        slug: state.slug,
        title: state.title,
        date: state.date,
        media: state.media,
      },
      input: { role: "transcript", path: transcriptPath },
      classification: { signal },
      output: { role: "canonical", path: state.canonical },
      mode,
      overwrite: mode === "repair",
      repair_diagnostics: mode === "repair" ? diagnostics : [],
      exact_command: command([
        "quasi-transcribe",
        "silent",
        "--slug",
        state.slug,
        "--title",
        state.title,
        "--date",
        state.date,
        "--media",
        state.media,
        "--transcript",
        transcriptPath,
        "--state",
        signal,
        "--mode",
        mode,
        "--output",
        state.canonical,
        "--json",
      ]),
    },
    null,
    2,
  );
}

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
      "source_path",
      "source_sha256",
      "request_fingerprint",
      "manifest_path",
      "classification",
      "transcript_changed",
      "canonical_exists",
      "canonical_sha256",
      "artifacts",
      "steps",
      "diagnostics",
    ],
    properties: {
      slug: { const: slug },
      source_path: { const: media },
      source_sha256: nullableHashSchema,
      request_fingerprint: nullableHashSchema,
      manifest_path: { const: manifest },
      classification: {
        type: ["string", "null"],
        enum: ["live", "dead", "empty", null],
      },
      transcript_changed: { type: "boolean" },
      canonical_exists: { type: "boolean" },
      canonical_sha256: nullableHashSchema,
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
      ...context.engines.map(
        (engine) =>
          `${context.processingDir}/transcript.${engine}.srt`,
      ),
    ]);
    return (
      typeof receipt.source_sha256 === "string" &&
      typeof receipt.request_fingerprint === "string" &&
      ["live", "dead", "empty"].includes(receipt.classification) &&
      receipt.canonical_exists === (receipt.canonical_sha256 !== null) &&
      receipt.artifacts.every((row) => allowed.has(row.path)) &&
      receipt.artifacts.some(
        (row) => row.role === "transcript" && row.path === context.transcript,
      )
    );
  },
});

export function talkPrepareStagePrompt(state) {
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
        "Read exact transcript artifacts",
      ],
    },
    null,
    2,
  );
}
