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
  return `Execute exactly one talk.observe command-relay operation from this JSON request.
Run exact_command once, parse its one JSON stdout object, and return only the strict receipt.
Copy every stdout field and value exactly: a CLI JSON null must remain the literal JSON null
token, never the string "null", and a null classification must not become empty.
Do not write, repair, transcribe, classify, or inspect another path.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one talk.prepare-media command-relay operation from this JSON request.
Run exact_command once and return only its strict one-object JSON receipt. Never run a
second command, overwrite an existing unverified output, or choose another output path.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one talk.transcribe command-relay operation from this JSON request.
Run exact_command once. The CLI owns engine fan-out, staging, locking, manifest-last commit,
and reconciliation. Do not invoke an engine or retry independently. Return only the exact
flat JSON receipt emitted by the command.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one read-only talk.classify command-relay operation from this JSON
request. Run exact_command once and return only its strict receipt. Machine signals are
evidence for the typed live|dead|empty result; do not write or select the next graph edge.
${JSON.stringify(request, null, 2)}`;
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
  return `Execute exactly one talk.render-silent command-relay operation from this JSON
request. Run exact_command once. create never clobbers; repair is allowed only for the exact
diagnostics and output. Return only the CLI's strict JSON receipt and choose no graph edge.
${JSON.stringify(request, null, 2)}`;
}
