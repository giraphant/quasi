const failureSchema = (operationKey, retryable) => ({
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
    retryable: { const: retryable },
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
        "canonical",
      ],
    },
    path: { type: "string" },
    sha256: { type: "string" },
    size: { type: "integer", minimum: 1 },
  },
};

export const TALK_OBSERVE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "material_key",
    "slug",
    "input_path",
    "output_dir",
    "manifest_path",
    "manifest_exists",
    "request_fingerprint",
    "source_sha256",
    "source_size",
    "prepared_path",
    "prepared_sha256",
    "transcript_path",
    "subtitle_path",
    "talk_path",
    "talk_exists",
    "talk_sha256",
    "classification",
    "artifacts",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.observe.receipt/0.1",
    },
    key: { const: "talk.observe" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    material_key: { type: "string" },
    slug: { type: "string" },
    input_path: { type: "string" },
    output_dir: { type: "string" },
    manifest_path: { type: "string" },
    manifest_exists: { type: "boolean" },
    request_fingerprint: { type: ["string", "null"] },
    source_sha256: { type: ["string", "null"] },
    source_size: { type: "integer", minimum: 0 },
    prepared_path: { type: ["string", "null"] },
    prepared_sha256: { type: ["string", "null"] },
    transcript_path: { type: ["string", "null"] },
    subtitle_path: { type: ["string", "null"] },
    talk_path: { type: "string" },
    talk_exists: { type: "boolean" },
    talk_sha256: { type: ["string", "null"] },
    classification: {
      type: ["string", "null"],
      enum: ["live", "dead", "empty", null],
    },
    artifacts: {
      type: "array",
      maxItems: 8,
      items: artifactSchema,
    },
    failure: failureSchema("talk.observe", false),
  },
};

export const TALK_PREPARE_MEDIA_SCHEMA = {
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
    "input_sha256",
    "output_sha256",
    "size",
    "action",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.prepare-media.receipt/0.1",
    },
    key: { const: "talk.prepare-media" },
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
      items: { const: "prepared_media" },
    },
    input_sha256: { type: ["string", "null"] },
    output_sha256: { type: ["string", "null"] },
    size: { type: "integer", minimum: 0 },
    action: {
      type: "string",
      enum: ["create", "reconciled"],
    },
    failure: failureSchema("talk.prepare-media", false),
  },
};

export const TALK_TRANSCRIBE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "material_key",
    "slug",
    "input_path",
    "output_dir",
    "talk_dir",
    "manifest_path",
    "manifest_exists",
    "manifest_fingerprint",
    "request_fingerprint",
    "source_sha256",
    "lang",
    "title",
    "engines",
    "primary_engine",
    "transcript_path",
    "subtitle_path",
    "per_engine",
    "artifacts",
    "disposition",
    "previous_manifest_preserved",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.transcribe.receipt/0.1",
    },
    key: { const: "talk.transcribe" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    material_key: { type: "string" },
    slug: { type: "string" },
    input_path: { type: "string" },
    output_dir: { type: "string" },
    talk_dir: { type: "string" },
    manifest_path: { type: "string" },
    manifest_exists: { type: "boolean" },
    manifest_fingerprint: { type: ["string", "null"] },
    request_fingerprint: { type: ["string", "null"] },
    source_sha256: { type: ["string", "null"] },
    lang: { type: "string" },
    title: { type: "string" },
    engines: {
      type: "array",
      minItems: 1,
      maxItems: 4,
      items: { type: "string" },
    },
    primary_engine: { type: ["string", "null"] },
    transcript_path: { type: ["string", "null"] },
    subtitle_path: { type: ["string", "null"] },
    per_engine: {
      type: "array",
      minItems: 1,
      maxItems: 4,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["name", "status", "segments", "path", "sha256"],
        properties: {
          name: { type: "string" },
          status: {
            type: "string",
            enum: ["succeeded", "empty", "unavailable", "failed"],
          },
          segments: { type: "integer", minimum: 0 },
          path: { type: ["string", "null"] },
          sha256: { type: ["string", "null"] },
        },
      },
    },
    artifacts: {
      type: "array",
      maxItems: 8,
      items: artifactSchema,
    },
    disposition: {
      type: ["string", "null"],
      enum: ["created", "replaced", "reconciled", null],
    },
    previous_manifest_preserved: { type: "boolean" },
    failure: failureSchema("talk.transcribe", false),
  },
};

export const TALK_CLASSIFY_SCHEMA = {
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
    "input_sha256",
    "signal",
    "machine_signals",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.classify.receipt/0.1",
    },
    key: { const: "talk.classify" },
    effect: { const: "readonly" },
    status: {
      type: "string",
      enum: ["succeeded", "failed"],
    },
    attempt: { type: "integer", const: 1 },
    material_key: { type: "string" },
    input_path: { type: "string" },
    input_sha256: { type: ["string", "null"] },
    signal: {
      type: ["string", "null"],
      enum: ["live", "dead", "empty", null],
    },
    machine_signals: {
      type: ["object", "null"],
      additionalProperties: false,
      required: [
        "total",
        "uniq_ratio",
        "chars",
        "spam_hits",
        "blank_dominant",
        "reason",
      ],
      properties: {
        total: { type: "integer", minimum: 0 },
        uniq_ratio: { type: "number", minimum: 0, maximum: 1 },
        chars: { type: "integer", minimum: 0 },
        spam_hits: { type: "integer", minimum: 0 },
        blank_dominant: { type: "boolean" },
        reason: { type: "string" },
      },
    },
    failure: failureSchema("talk.classify", false),
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
    failure: failureSchema("talk.render-silent", false),
  },
};

const posixSingleQuote = (value) =>
  `'${String(value).replace(/'/g, `'\"'\"'`)}'`;

function command(tokens) {
  return tokens.map(posixSingleQuote).join(" ");
}

function baseRequest(operation, state) {
  return {
    schema_version: `quasi.operation.${operation}.request/0.1`,
    operation,
    material_key: state.materialKey,
    identity: {
      slug: state.slug,
      title: state.title,
      date: state.date,
      media: state.media,
      engines: state.engines,
      lang: state.lang,
    },
    paths: {
      output_dir: state.processingDir,
      talk_dir: state.talkDir,
      manifest: state.manifest,
      prepared: state.prepared,
      transcript: state.transcript,
      subtitle: state.subtitle,
      talk: state.canonical,
    },
  };
}

export function talkObservePrompt(state) {
  const exactCommand = command([
    "quasi-transcribe",
    "observe",
    "--media",
    state.media,
    "--slug",
    state.slug,
    "--title",
    state.title,
    "--date",
    state.date,
    "--engines",
    state.engines.join(","),
    "--lang",
    state.lang,
    "--json",
  ]);
  const request = {
    ...baseRequest("talk.observe", state),
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

export function talkPrepareMediaPrompt(state) {
  const exactCommand = command([
    "quasi-transcribe",
    "prepare-media",
    "--media",
    state.media,
    "--output",
    state.prepared,
    "--json",
  ]);
  const request = {
    ...baseRequest("talk.prepare-media", state),
    input: { role: "source", path: state.media },
    output: { role: "prepared_media", path: state.prepared },
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

export function talkTranscribePrompt(state, inputPath) {
  const exactCommand = command([
    "quasi-transcribe",
    "run",
    "--media",
    inputPath,
    "--slug",
    state.slug,
    "--title",
    state.title,
    "--engines",
    state.engines.join(","),
    "--lang",
    state.lang,
    "--json",
  ]);
  const request = {
    ...baseRequest("talk.transcribe", state),
    input: { role: "source", path: inputPath },
    outputs: [
      { role: "manifest", path: state.manifest },
      { role: "transcript", path: state.transcript },
      { role: "subtitle", path: state.subtitle },
    ],
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

export function talkClassifyPrompt(state, transcriptPath) {
  const exactCommand = command([
    "quasi-transcribe",
    "classify",
    "--slug",
    state.slug,
    "--transcript",
    transcriptPath,
    "--json",
  ]);
  const request = {
    ...baseRequest("talk.classify", state),
    input: { role: "transcript", path: transcriptPath },
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

export function talkRenderSilentPrompt(
  state,
  transcriptPath,
  signal,
  mode = "create",
  diagnostics = [],
) {
  const exactCommand = command([
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
  ]);
  const request = {
    ...baseRequest("talk.render-silent", state),
    input: { role: "transcript", path: transcriptPath },
    classification: { signal },
    output: { role: "canonical", path: state.canonical },
    mode,
    overwrite: mode === "repair",
    repair_diagnostics: mode === "repair" ? diagnostics : [],
    exact_command: exactCommand,
  };
  return JSON.stringify(request, null, 2);
}

// --- Receipt contracts -----------------------------------------------------
// Status invariants and exact-state echoes the host schema cannot carry.
// Context carries the graph's talk state plus per-call identity; the runtime
// enforces schema, echo, then these through classifyReceipt.

import { validText } from "../runtime.mjs";
import { composedSchema } from "./extract.mjs";

const TALK_HASH = /^[a-f0-9]{64}$/;
const TALK_HASH_PATTERN = "^[a-f0-9]{64}$";

const talkFailureBranch = (outcome) => ({
  type: "object",
  required: ["outcome"],
  properties: {
    outcome: { const: outcome },
    code: { minLength: 1, maxLength: 200 },
    message: { maxLength: 4000 },
  },
});

const validHash = (value) =>
  typeof value === "string" && TALK_HASH.test(value);

const sameStrings = (left, right) =>
  Array.isArray(left) &&
  Array.isArray(right) &&
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

const validTalkFailure = (failure, operationKey, outcome) =>
  !!(
    failure &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    failure.outcome === outcome &&
    failure.retryable === false &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );

const validArtifactRow = (row, state) => {
  if (
    !validText(row.path, 1, 2048) ||
    !validHash(row.sha256)
  )
    return false;
  if (row.role === "prepared_media")
    return row.path === state.prepared;
  if (row.role === "transcript")
    return row.path === state.transcript;
  if (row.role === "subtitle")
    return row.path === state.subtitle;
  if (row.role === "canonical")
    return row.path === state.canonical;
  return state.engines.some(
    (engine) =>
      row.path ===
      `${state.processingDir}/transcript.${engine}.srt`,
  );
};

const uniqueArtifactRows = (rows) => {
  const paths = rows.map((row) => row.path);
  return new Set(paths).size === paths.length;
};

const GENERATED_ROLES = [
  "transcript",
  "subtitle",
  "engine_transcript",
];

export const TALK_OBSERVE_CONTRACT = {
  schema: TALK_OBSERVE_SCHEMA,
  echo: (receipt, context) => {
    const state = context.state;
    return (
      receipt.material_key === state.materialKey &&
      receipt.slug === state.slug &&
      receipt.input_path === state.media &&
      receipt.output_dir === state.processingDir &&
      receipt.manifest_path === state.manifest &&
      [null, state.prepared].includes(receipt.prepared_path) &&
      [null, state.transcript].includes(receipt.transcript_path) &&
      [null, state.subtitle].includes(receipt.subtitle_path) &&
      receipt.talk_path === state.canonical &&
      receipt.artifacts.every((row) =>
        validArtifactRow(row, state),
      ) &&
      uniqueArtifactRows(receipt.artifacts)
    );
  },
  statuses: {
    succeeded: (receipt, context) => {
      const state = context.state;
      if (
        receipt.failure !== null ||
        !validHash(receipt.source_sha256) ||
        receipt.source_size < 1 ||
        (receipt.prepared_path === null) !==
          (receipt.prepared_sha256 === null) ||
        (receipt.prepared_sha256 !== null &&
          !validHash(receipt.prepared_sha256)) ||
        receipt.talk_exists !== (receipt.talk_sha256 !== null) ||
        (receipt.talk_sha256 !== null &&
          !validHash(receipt.talk_sha256))
      )
        return false;
      if (
        receipt.prepared_path !== null &&
        !receipt.artifacts.some(
          (row) =>
            row.role === "prepared_media" &&
            row.path === receipt.prepared_path &&
            row.sha256 === receipt.prepared_sha256,
        )
      )
        return false;
      if (receipt.manifest_exists) {
        if (validHash(receipt.request_fingerprint)) {
          if (
            receipt.transcript_path !== state.transcript ||
            !receipt.artifacts.some(
              (row) =>
                row.role === "transcript" &&
                row.path === state.transcript,
            )
          )
            return false;
        } else if (
          receipt.request_fingerprint !== null ||
          receipt.transcript_path !== state.transcript ||
          receipt.subtitle_path !== state.subtitle ||
          receipt.classification !== null ||
          receipt.artifacts.some((row) =>
            GENERATED_ROLES.includes(row.role),
          )
        ) {
          return false;
        }
      } else if (
        receipt.request_fingerprint !== null ||
        receipt.transcript_path !== null ||
        receipt.subtitle_path !== null ||
        receipt.classification !== null ||
        receipt.artifacts.some((row) =>
          GENERATED_ROLES.includes(row.role),
        )
      ) {
        return false;
      }
      if (
        !(receipt.manifest_exists &&
          receipt.request_fingerprint === null) &&
        receipt.talk_exists !==
          receipt.artifacts.some(
            (row) =>
              row.role === "canonical" &&
              row.path === state.canonical,
          )
      )
        return false;
      return true;
    },
    failed: (receipt) =>
      validTalkFailure(receipt.failure, "talk.observe", "known"),
    blocked: (receipt) =>
      validTalkFailure(receipt.failure, "talk.observe", "unknown"),
  },
};

export const talkPrepareMediaSchema = ({
  materialKey,
  input,
  output,
  inputSha,
}) =>
  composedSchema(
    TALK_PREPARE_MEDIA_SCHEMA,
    {
      material_key: { const: materialKey },
      input_path: { const: input },
      output_path: { const: output },
      input_sha256: { const: inputSha },
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
        },
      },
      failed: {
        properties: {
          status: { const: "failed" },
          action: { const: "create" },
          output_sha256: { type: "null" },
          size: { const: 0 },
          failure: talkFailureBranch("known"),
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          action: { const: "create" },
          output_sha256: { type: "null" },
          size: { const: 0 },
          failure: talkFailureBranch("unknown"),
        },
      },
    },
  );

export const TALK_PREPARE_MEDIA_CONTRACT = {
  schema: TALK_PREPARE_MEDIA_SCHEMA,
};

const strictEngineRow = (row, engine, state) => {
  if (row.name !== engine) return false;
  const expected = `${state.processingDir}/transcript.${engine}.srt`;
  if (row.status === "succeeded")
    return (
      row.segments > 0 &&
      row.path === expected &&
      validHash(row.sha256)
    );
  return (
    row.segments === 0 &&
    row.path === null &&
    row.sha256 === null
  );
};

export const TALK_TRANSCRIBE_CONTRACT = {
  schema: TALK_TRANSCRIBE_SCHEMA,
  echo: (receipt, context) => {
    const state = context.state;
    return (
      receipt.material_key === state.materialKey &&
      receipt.slug === state.slug &&
      receipt.input_path === context.inputPath &&
      receipt.output_dir === state.processingDir &&
      receipt.talk_dir === state.talkDir &&
      receipt.manifest_path === state.manifest &&
      receipt.source_sha256 === context.expectedInputSha &&
      receipt.lang === state.lang &&
      receipt.title === state.title &&
      sameStrings(receipt.engines, state.engines) &&
      receipt.per_engine.length === state.engines.length &&
      state.engines.every((engine, index) =>
        strictEngineRow(
          receipt.per_engine[index],
          engine,
          state,
        ),
      ) &&
      receipt.artifacts.every((row) =>
        validArtifactRow(row, state),
      ) &&
      uniqueArtifactRows(receipt.artifacts)
    );
  },
  statuses: {
    succeeded: (receipt, context) => {
      const state = context.state;
      if (
        receipt.failure !== null ||
        receipt.manifest_exists !== true ||
        !validHash(receipt.manifest_fingerprint) ||
        !validHash(receipt.request_fingerprint) ||
        !validHash(receipt.source_sha256) ||
        !["created", "replaced", "reconciled"].includes(
          receipt.disposition,
        ) ||
        receipt.transcript_path !== state.transcript ||
        !receipt.artifacts.some(
          (row) =>
            row.role === "transcript" &&
            row.path === state.transcript,
        )
      )
        return false;
      const succeeded = receipt.per_engine.filter(
        (row) => row.status === "succeeded",
      );
      if (receipt.primary_engine === null)
        return (
          succeeded.length === 0 &&
          receipt.subtitle_path === null &&
          !receipt.artifacts.some(
            (row) =>
              row.role === "subtitle" ||
              row.role === "engine_transcript",
          )
        );
      const primary = receipt.per_engine.find(
        (row) => row.name === receipt.primary_engine,
      );
      return !!(
        primary &&
        primary.status === "succeeded" &&
        receipt.subtitle_path === state.subtitle &&
        receipt.artifacts.some(
          (row) =>
            row.role === "subtitle" &&
            row.path === state.subtitle,
        ) &&
        succeeded.every((row) =>
          receipt.artifacts.some(
            (artifactRow) =>
              artifactRow.role === "engine_transcript" &&
              artifactRow.path === row.path &&
              artifactRow.sha256 === row.sha256,
          ),
        )
      );
    },
    failed: (receipt) =>
      receipt.manifest_exists === true &&
      validHash(receipt.manifest_fingerprint) &&
      validHash(receipt.request_fingerprint) &&
      receipt.disposition === null &&
      validTalkFailure(
        receipt.failure,
        "talk.transcribe",
        "known",
      ),
    blocked: (receipt) =>
      receipt.disposition === null &&
      (receipt.manifest_fingerprint === null ||
        validHash(receipt.manifest_fingerprint)) &&
      validTalkFailure(
        receipt.failure,
        "talk.transcribe",
        "unknown",
      ),
  },
};

export const TALK_CLASSIFY_CONTRACT = {
  schema: TALK_CLASSIFY_SCHEMA,
  echo: (receipt, context) =>
    receipt.material_key === context.state.materialKey &&
    receipt.input_path === context.transcript &&
    receipt.input_sha256 === context.transcriptSha,
  statuses: {
    succeeded: (receipt) =>
      receipt.failure === null &&
      ["live", "dead", "empty"].includes(receipt.signal) &&
      receipt.machine_signals !== null &&
      validText(receipt.machine_signals.reason, 1, 1000),
    failed: (receipt) =>
      receipt.signal === null &&
      receipt.machine_signals === null &&
      validTalkFailure(
        receipt.failure,
        "talk.classify",
        "known",
      ),
  },
};

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
          failure: talkFailureBranch("known"),
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          output_sha256: { type: "null" },
          action: { const: mode },
          failure: talkFailureBranch("unknown"),
        },
      },
    },
  );

export const TALK_RENDER_SILENT_CONTRACT = {
  schema: TALK_RENDER_SILENT_SCHEMA,
};
