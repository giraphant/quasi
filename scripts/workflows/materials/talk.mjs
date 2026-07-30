import {
  TALK_ANALYSE_SCHEMA,
  talkAnalyseOperationPrompt,
} from "../operations/analyse.mjs";
import {
  TALK_AUDIT_SCHEMA,
  talkAuditLegacyPrompt,
} from "../operations/audit.mjs";
import {
  TALK_CLASSIFY_SCHEMA,
  TALK_OBSERVE_SCHEMA,
  TALK_PREPARE_MEDIA_SCHEMA,
  TALK_RENDER_SILENT_SCHEMA,
  TALK_TRANSCRIBE_SCHEMA,
  talkClassifyPrompt,
  talkObservePrompt,
  talkPrepareMediaPrompt,
  talkRenderSilentPrompt,
  talkTranscribePrompt,
} from "../operations/transcribe.mjs";

const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.1";
const TALK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const HASH = /^[a-f0-9]{64}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const ENGINES = new Set([
  "soniox",
  "apple",
  "parakeet",
  "whisper",
]);
const LANGS = new Set([
  "auto",
  "en",
  "zh",
  "yue",
  "ja",
  "fr",
  "de",
  "es",
]);
const VIDEO_EXTENSIONS = new Set([
  "mov",
  "mp4",
  "m4v",
  "mkv",
  "webm",
]);
const MEDIA_EXTENSIONS = new Set([
  ...VIDEO_EXTENSIONS,
  "m4a",
  "wav",
  "mp3",
  "aac",
  "flac",
  "aiff",
  "aif",
  "ogg",
  "opus",
]);

const exactKeys = (value, keys) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const sameStrings = (left, right) =>
  Array.isArray(left) &&
  Array.isArray(right) &&
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

const validHash = (value) =>
  typeof value === "string" && HASH.test(value);

function validDate(value) {
  if (!DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.valueOf()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function mediaExtension(path) {
  const match = String(path).match(/\.([A-Za-z0-9]+)$/);
  return match ? match[1].toLowerCase() : "";
}

function validateIdentity(slug, meta) {
  if (
    typeof slug !== "string" ||
    !TALK_SLUG.test(slug)
  )
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "talk slug is not canonical ASCII kebab",
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "talk metadata must be an object",
    };
  if (!validText(meta.title, 2, 280))
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "title is missing or invalid",
    };
  if (!validDate(meta.date))
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "date must be an exact calendar YYYY-MM-DD",
    };
  if (
    !validText(meta.media, 1, 2048) ||
    meta.media.includes("\\") ||
    meta.media.split("/").includes("..") ||
    mediaExtension(meta.media) === "" ||
    !MEDIA_EXTENSIONS.has(mediaExtension(meta.media))
  )
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "media path or extension is invalid",
    };
  const engines =
    meta.engines === undefined
      ? ["soniox", "apple", "parakeet"]
      : meta.engines;
  if (
    !Array.isArray(engines) ||
    engines.length < 1 ||
    engines.length > 4 ||
    new Set(engines).size !== engines.length ||
    engines.some((engine) => !ENGINES.has(engine))
  )
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "engines must be a unique supported ordered list",
    };
  const lang = meta.lang === undefined ? "auto" : meta.lang;
  if (!LANGS.has(lang))
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "lang is not supported",
    };
  if (
    meta.prepare_media !== undefined &&
    typeof meta.prepare_media !== "boolean"
  )
    return {
      ok: false,
      code: "talk.identity_invalid",
      message: "prepare_media must be boolean when supplied",
    };
  const normalized = {
    title: meta.title,
    date: meta.date,
    media: meta.media,
    engines: [...engines],
    lang,
    prepare_media:
      meta.prepare_media === undefined
        ? VIDEO_EXTENSIONS.has(mediaExtension(meta.media))
        : meta.prepare_media,
  };
  return {
    ok: true,
    meta: normalized,
    fingerprint: JSON.stringify(normalized),
  };
}

const operationFailure = (
  code,
  operationKey,
  outcome = "known",
  message = null,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable: false,
  message,
});

function validFailure(
  failure,
  operationKey,
  outcome,
  retryable = false,
) {
  return !!(
    exactKeys(failure, [
      "code",
      "operation_key",
      "outcome",
      "retryable",
      "message",
    ]) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    failure.outcome === outcome &&
    failure.retryable === retryable &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

function createState(slug, meta) {
  const outputDir = `vault/talks/${slug}`;
  return {
    slug,
    materialKey: `talk:${slug}`,
    title: meta.title,
    date: meta.date,
    media: meta.media,
    engines: meta.engines,
    lang: meta.lang,
    prepareMedia: meta.prepare_media,
    talkDir: outputDir,
    processingDir: `processing/talks/${slug}`,
    manifest: `processing/talks/${slug}/manifest.json`,
    prepared: `${outputDir}/recording.mp4`,
    transcript: `${outputDir}/transcript.md`,
    subtitle: `${outputDir}/recording.srt`,
    canonical: `${outputDir}/talk.md`,
    sourceSha256: null,
    requestFingerprint: null,
    transcriptArtifacts: [],
    outputExists: false,
    transcriptReplaced: false,
    talkProducer: null,
    classification: null,
    artifacts: [],
    operations: [],
    audit: [],
    repaired: false,
    disposition: null,
    budgets: {
      prepareMedia: { used: 0, limit: meta.prepare_media ? 1 : 0 },
      transcribe: { used: 0, limit: 1 },
      classify: { used: 0, limit: 1 },
      produce: { used: 0, limit: 1 },
      repair: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 2 },
    },
    warnings: [
      "talk audit remains an explicitly named legacy composite",
    ],
  };
}

function artifact(
  role,
  path,
  producer,
  sha256 = null,
  size = null,
) {
  return {
    role,
    path,
    exists: true,
    usable: true,
    producer,
    sha256,
    size,
  };
}

function materialReceipt(
  state,
  {
    status,
    stage,
    failure = null,
    disposition = null,
  },
) {
  return {
    schema_version: MATERIAL_RECEIPT_VERSION,
    material_key: state.materialKey,
    kind: "talk",
    id: state.slug,
    status,
    disposition:
      disposition ||
      (status === "complete"
        ? state.repaired
          ? "repaired"
          : state.disposition || "created"
        : null),
    stage,
    artifacts: state.artifacts,
    operations: state.operations,
    audit: state.audit,
    warnings: state.warnings,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "talk.reconcile" }
        : null,
    budgets: state.budgets,
    freshness: {
      observation: "unknown",
      basis: "operation-receipts-and-final-audit",
    },
  };
}

function terminal(
  state,
  legacyStatus,
  receiptStatus,
  stage,
  failure = null,
  extra = {},
) {
  return {
    slug: state.slug,
    status: legacyStatus,
    classification: state.classification,
    transcript_path:
      state.transcriptArtifacts.length > 0
        ? state.transcript
        : null,
    talk_path:
      state.artifacts.some(
        (item) => item.role === "canonical",
      )
        ? state.canonical
        : null,
    ...extra,
    material_receipt: materialReceipt(state, {
      status: receiptStatus,
      stage,
      failure,
    }),
  };
}

function rejectedResult(slug, validation, conflict = false) {
  const safeSlug =
    typeof slug === "string" &&
    TALK_SLUG.test(slug)
      ? slug
      : "";
  const state = createState(safeSlug, {
    title: safeSlug || "invalid",
    date: "1970-01-01",
    media: "invalid.wav",
    engines: ["apple"],
    lang: "auto",
    prepare_media: false,
  });
  const failure = operationFailure(
    conflict ? "talk.identity_conflict" : validation.code,
    "talk.identity",
    "known",
    validation.message,
  );
  return terminal(
    state,
    "blocked",
    "blocked",
    "identity",
    failure,
  );
}

function runtimeUnknown(receipt) {
  return !!(
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    receipt.failure &&
    receipt.failure.outcome === "unknown"
  );
}

function validArtifactRow(row, state) {
  if (
    !exactKeys(row, ["role", "path", "sha256", "size"]) ||
    ![
      "prepared_media",
      "transcript",
      "subtitle",
      "engine_transcript",
      "canonical",
    ].includes(row.role) ||
    !validText(row.path, 1, 2048) ||
    !validHash(row.sha256) ||
    !Number.isInteger(row.size) ||
    row.size < 1
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
}

function uniqueArtifactRows(rows) {
  const paths = rows.map((row) => row.path);
  return new Set(paths).size === paths.length;
}

function strictObserve(receipt, state) {
  if (
    !exactKeys(receipt, [
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.observe.receipt/0.1" ||
    receipt.key !== "talk.observe" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.material_key !== state.materialKey ||
    receipt.slug !== state.slug ||
    receipt.input_path !== state.media ||
    receipt.output_dir !== state.processingDir ||
    receipt.manifest_path !== state.manifest ||
    typeof receipt.manifest_exists !== "boolean" ||
    !Number.isInteger(receipt.source_size) ||
    receipt.source_size < 0 ||
    ![null, state.prepared].includes(receipt.prepared_path) ||
    ![null, state.transcript].includes(receipt.transcript_path) ||
    ![null, state.subtitle].includes(receipt.subtitle_path) ||
    receipt.talk_path !== state.canonical ||
    typeof receipt.talk_exists !== "boolean" ||
    ![null, "live", "dead", "empty"].includes(
      receipt.classification,
    ) ||
    !Array.isArray(receipt.artifacts) ||
    receipt.artifacts.some(
      (row) => !validArtifactRow(row, state),
    ) ||
    !uniqueArtifactRows(receipt.artifacts)
  )
    return false;
  if (receipt.status === "succeeded") {
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
          ["transcript", "subtitle", "engine_transcript"].includes(
            row.role,
          ),
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
        ["transcript", "subtitle", "engine_transcript"].includes(
          row.role,
        ),
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
  }
  if (receipt.status === "failed")
    return validFailure(
      receipt.failure,
      "talk.observe",
      "known",
    );
  return (
    receipt.status === "blocked" &&
    validFailure(
      receipt.failure,
      "talk.observe",
      "unknown",
    )
  );
}

function strictPrepare(receipt, state) {
  if (
    !exactKeys(receipt, [
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.prepare-media.receipt/0.1" ||
    receipt.key !== "talk.prepare-media" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.material_key !== state.materialKey ||
    receipt.input_path !== state.media ||
    receipt.output_path !== state.prepared ||
    !sameStrings(receipt.artifact_roles, ["prepared_media"]) ||
    !["create", "reconciled"].includes(receipt.action) ||
    !Number.isInteger(receipt.size) ||
    receipt.size < 0
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      receipt.input_sha256 === state.sourceSha256 &&
      validHash(receipt.output_sha256) &&
      receipt.size > 0
    );
  if (receipt.status === "failed")
    return (
      receipt.action === "create" &&
      receipt.input_sha256 === state.sourceSha256 &&
      receipt.output_sha256 === null &&
      validFailure(
        receipt.failure,
        "talk.prepare-media",
        "known",
      ) &&
      receipt.size === 0
    );
  return (
    receipt.status === "blocked" &&
    receipt.action === "create" &&
    receipt.input_sha256 === state.sourceSha256 &&
    receipt.output_sha256 === null &&
    receipt.size === 0 &&
    validFailure(
      receipt.failure,
      "talk.prepare-media",
      "unknown",
    )
  );
}

function strictEngineRow(row, engine, state) {
  if (
    !exactKeys(row, [
      "name",
      "status",
      "segments",
      "path",
      "sha256",
    ]) ||
    row.name !== engine ||
    !["succeeded", "empty", "unavailable", "failed"].includes(
      row.status,
    ) ||
    !Number.isInteger(row.segments) ||
    row.segments < 0
  )
    return false;
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
}

function strictTranscribe(receipt, state, inputPath) {
  const expectedInputSha =
    inputPath === state.media
      ? state.sourceSha256
      : state.artifacts.find(
          (row) =>
            row.role === "prepared_media" &&
            row.path === inputPath,
        )?.sha256;
  if (
    !exactKeys(receipt, [
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.transcribe.receipt/0.1" ||
    receipt.key !== "talk.transcribe" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.material_key !== state.materialKey ||
    receipt.slug !== state.slug ||
    receipt.input_path !== inputPath ||
    receipt.output_dir !== state.processingDir ||
    receipt.talk_dir !== state.talkDir ||
    receipt.manifest_path !== state.manifest ||
    receipt.source_sha256 !== expectedInputSha ||
    receipt.lang !== state.lang ||
    receipt.title !== state.title ||
    !sameStrings(receipt.engines, state.engines) ||
    !Array.isArray(receipt.per_engine) ||
    receipt.per_engine.length !== state.engines.length ||
    !state.engines.every((engine, index) =>
      strictEngineRow(
        receipt.per_engine[index],
        engine,
        state,
      ),
    ) ||
    !Array.isArray(receipt.artifacts) ||
    receipt.artifacts.some(
      (row) => !validArtifactRow(row, state),
    ) ||
    !uniqueArtifactRows(receipt.artifacts) ||
    typeof receipt.previous_manifest_preserved !== "boolean"
  )
    return false;
  if (receipt.status === "succeeded") {
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
  }
  if (receipt.status === "failed")
    return (
      receipt.manifest_exists === true &&
      validHash(receipt.manifest_fingerprint) &&
      validHash(receipt.request_fingerprint) &&
      receipt.disposition === null &&
      validFailure(
        receipt.failure,
        "talk.transcribe",
        "known",
      )
    );
  return (
    receipt.status === "blocked" &&
    receipt.disposition === null &&
    (receipt.manifest_fingerprint === null ||
      validHash(receipt.manifest_fingerprint)) &&
    validFailure(
      receipt.failure,
      "talk.transcribe",
      "unknown",
    )
  );
}

function strictClassify(receipt, state, transcript) {
  const transcriptArtifact = state.transcriptArtifacts.find(
    (row) => row.role === "transcript",
  );
  if (
    !exactKeys(receipt, [
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.classify.receipt/0.1" ||
    receipt.key !== "talk.classify" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.material_key !== state.materialKey ||
    receipt.input_path !== transcript ||
    !transcriptArtifact ||
    receipt.input_sha256 !== transcriptArtifact.sha256
  )
    return false;
  if (receipt.status === "succeeded") {
    const signals = receipt.machine_signals;
    return !!(
      ["live", "dead", "empty"].includes(receipt.signal) &&
      exactKeys(signals, [
        "total",
        "uniq_ratio",
        "chars",
        "spam_hits",
        "blank_dominant",
        "reason",
      ]) &&
      Number.isInteger(signals.total) &&
      signals.total >= 0 &&
      typeof signals.uniq_ratio === "number" &&
      signals.uniq_ratio >= 0 &&
      signals.uniq_ratio <= 1 &&
      Number.isInteger(signals.chars) &&
      signals.chars >= 0 &&
      Number.isInteger(signals.spam_hits) &&
      signals.spam_hits >= 0 &&
      typeof signals.blank_dominant === "boolean" &&
      validText(signals.reason, 1, 1000) &&
      receipt.failure === null
    );
  }
  return (
    receipt.status === "failed" &&
    receipt.signal === null &&
    receipt.machine_signals === null &&
    validFailure(
      receipt.failure,
      "talk.classify",
      "known",
    )
  );
}

function strictProducerFailure(
  receipt,
  operationKey,
  mode,
) {
  if (receipt.status === "failed")
    return (
      receipt.action === mode &&
      validFailure(
        receipt.failure,
        operationKey,
        "known",
      )
    );
  return (
    receipt.status === "blocked" &&
    receipt.action === mode &&
    validFailure(
      receipt.failure,
      operationKey,
      "unknown",
    )
  );
}

function analysisInputs(state) {
  const primary = state.transcriptArtifacts.find(
    (row) => row.role === "transcript",
  );
  const engines = state.engines
    .map((engine) =>
      state.transcriptArtifacts.find(
        (row) =>
          row.role === "engine_transcript" &&
          row.path ===
            `${state.processingDir}/transcript.${engine}.srt`,
      ),
    )
    .filter(Boolean);
  return primary ? [primary, ...engines] : [];
}

function strictAnalyse(receipt, state, inputs, mode) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_paths",
      "input_sha256s",
      "output_path",
      "artifact_roles",
      "action",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.analyse.receipt/0.1" ||
    receipt.key !== "talk.analyse" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    !sameStrings(
      receipt.input_paths,
      inputs.map((input) => input.path),
    ) ||
    !sameStrings(
      receipt.input_sha256s,
      inputs.map((input) => input.sha256),
    ) ||
    receipt.output_path !== state.canonical ||
    !sameStrings(receipt.artifact_roles, ["canonical"]) ||
    !["create", "repair", "reconciled"].includes(
      receipt.action,
    )
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      (mode === "create"
        ? receipt.action === "create"
        : ["repair", "reconciled"].includes(receipt.action))
    );
  return strictProducerFailure(
    receipt,
    "talk.analyse",
    mode,
  );
}

function strictSilent(receipt, state, mode) {
  if (
    !exactKeys(receipt, [
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
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.render-silent.receipt/0.1" ||
    receipt.key !== "talk.render-silent" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.material_key !== state.materialKey ||
    receipt.input_path !== state.transcript ||
    receipt.output_path !== state.canonical ||
    !sameStrings(receipt.artifact_roles, ["canonical"]) ||
    receipt.classification_signal !== state.classification ||
    !["create", "repair", "reconciled"].includes(
      receipt.action,
    ) ||
    !Number.isInteger(receipt.size) ||
    receipt.size < 0
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      validHash(receipt.output_sha256) &&
      receipt.size > 0 &&
      (mode === "create"
        ? receipt.action === "create"
        : ["repair", "reconciled"].includes(receipt.action))
    );
  return (
    receipt.output_sha256 === null &&
    strictProducerFailure(
      receipt,
      "talk.render-silent",
      mode,
    )
  );
}

function validDiagnostic(item) {
  return !!(
    exactKeys(item, ["path", "kind", "reason"]) &&
    validText(item.path, 1, 2048) &&
    validText(item.kind, 1, 200) &&
    validText(item.reason, 1, 4000)
  );
}

function strictAudit(receipt, state) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "target_path",
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.talk.audit.legacy.receipt/0.1" ||
    receipt.key !== "talk.audit.legacy" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.target_path !== state.canonical ||
    !Number.isInteger(receipt.remaining_violations) ||
    receipt.remaining_violations < 0 ||
    !Array.isArray(receipt.escalated) ||
    receipt.escalated.some(
      (item) => !validDiagnostic(item),
    ) ||
    !Array.isArray(receipt.mutated_paths) ||
    receipt.mutated_paths.some(
      (path) => !validText(path, 1, 2048),
    )
  )
    return false;
  if (receipt.status === "clean")
    return (
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0
    );
  if (receipt.status === "partial")
    return (
      receipt.remaining_violations > 0 &&
      receipt.escalated.length ===
        receipt.remaining_violations
    );
  return (
    receipt.status === "error" &&
    receipt.remaining_violations === 0 &&
    receipt.escalated.length === 0
  );
}

function ownedAuditPaths(receipt, state) {
  return [
    ...receipt.escalated.map((item) => item.path),
    ...receipt.mutated_paths,
  ].every((path) => path === state.canonical);
}

function writerMismatch(state, stage, operationKey) {
  return terminal(
    state,
    "blocked",
    "blocked",
    stage,
    operationFailure(
      "talk.writer_receipt_mismatch",
      operationKey,
      "unknown",
      "writer receipt did not prove the exact contract",
    ),
  );
}

function addGeneratedArtifacts(state, rows, producer) {
  const replace = new Map(
    state.artifacts.map((item) => [item.path, item]),
  );
  for (const row of rows)
    replace.set(
      row.path,
      artifact(
        row.role,
        row.path,
        producer,
        row.sha256,
        row.size,
      ),
    );
  state.artifacts = [...replace.values()];
}

async function runProducer(
  runtime,
  state,
  mode,
  diagnostics,
) {
  if (state.classification === "live") {
    const inputs = analysisInputs(state);
    if (!inputs.length)
      return {
        terminal: terminal(
          state,
          "analyse_failed",
          "failed",
          "analyse",
          operationFailure(
            "talk.transcript_generation_invalid",
            "talk.analyse",
            "known",
            "live Talk has no exact committed transcript inputs",
          ),
        ),
      };
    const receipt = await runtime.runOperation(
      talkAnalyseOperationPrompt(
        state,
        inputs,
        mode,
        diagnostics,
      ),
      {
        phase: "Analyse",
        agentType: "quasi:analyse-agent",
        label:
          mode === "repair"
            ? `${state.slug}:analyse-repair`
            : `${state.slug}:analyse`,
        schema: TALK_ANALYSE_SCHEMA,
      },
      {
        key: "talk.analyse",
        effect: "writer",
        retry: "forbidden",
        replay: "blocked",
        artifactRoles: ["canonical"],
        unknownFailureCode: "talk.writer_outcome_unknown",
      },
    );
    state.operations.push(receipt);
    if (!strictAnalyse(receipt, state, inputs, mode))
      return {
        terminal: writerMismatch(
          state,
          "analyse",
          "talk.analyse",
        ),
      };
    if (receipt.status === "blocked")
      return {
        terminal: terminal(
          state,
          "blocked",
          "blocked",
          "analyse",
          receipt.failure,
        ),
      };
    if (receipt.status === "failed")
      return {
        terminal: terminal(
          state,
          "analyse_failed",
          "failed",
          "analyse",
          receipt.failure,
        ),
      };
    state.talkProducer = "talk.analyse";
    state.artifacts = state.artifacts.filter(
      (item) => item.path !== state.canonical,
    );
    state.artifacts.push(
      artifact(
        "canonical",
        state.canonical,
        receipt.action === "reconciled"
          ? "talk.analyse:reconciled"
          : "talk.analyse",
      ),
    );
    if (receipt.action === "repair") {
      state.repaired = true;
      state.disposition = "repaired";
    } else if (receipt.action === "reconciled") {
      state.disposition = state.disposition || "reused";
    } else {
      state.disposition = "created";
    }
    return { receipt };
  }

  const receipt = await runtime.runOperation(
    talkRenderSilentPrompt(
      state,
      state.transcript,
      state.classification,
      mode,
      diagnostics,
    ),
    {
      phase: "Analyse",
      agentType: "quasi:transcribe-agent",
      label:
        mode === "repair"
          ? `${state.slug}:render-silent-repair`
          : `${state.slug}:render-silent`,
      schema: TALK_RENDER_SILENT_SCHEMA,
    },
    {
      key: "talk.render-silent",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "talk.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (!strictSilent(receipt, state, mode))
    return {
      terminal: writerMismatch(
        state,
        "render-silent",
        "talk.render-silent",
      ),
    };
  if (receipt.status === "blocked")
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "render-silent",
        receipt.failure,
      ),
    };
  if (receipt.status === "failed")
    return {
      terminal: terminal(
        state,
        "analyse_failed",
        "failed",
        "render-silent",
        receipt.failure,
      ),
    };
  state.talkProducer = "talk.render-silent";
  state.artifacts = state.artifacts.filter(
    (item) => item.path !== state.canonical,
  );
  state.artifacts.push(
    artifact(
      "canonical",
      state.canonical,
      receipt.action === "reconciled"
        ? "talk.render-silent:reconciled"
        : "talk.render-silent",
      receipt.output_sha256,
      receipt.size,
    ),
  );
  if (receipt.action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (receipt.action === "reconciled") {
    state.disposition = state.disposition || "reused";
  } else {
    state.disposition = "created";
  }
  return { receipt };
}

async function runAudit(runtime, state, pass) {
  const receipt = await runtime.runOperation(
    talkAuditLegacyPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label:
        pass === 1
          ? `${state.slug}:audit`
          : `${state.slug}:audit-${pass}`,
      schema: TALK_AUDIT_SCHEMA,
    },
    {
      key: "talk.audit.legacy",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "talk.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (!strictAudit(receipt, state))
    return {
      terminal: writerMismatch(
        state,
        "audit",
        "talk.audit.legacy",
      ),
    };
  if (!ownedAuditPaths(receipt, state))
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        operationFailure(
          "talk.repair_owner_unknown",
          "talk.audit.legacy",
          "known",
          "audit named a path outside the exact Talk product",
        ),
        { escalated: receipt.escalated },
      ),
    };
  if (receipt.status === "error")
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        operationFailure(
          "talk.audit_failed",
          "talk.audit.legacy",
          "known",
          "legacy audit transaction reported an error",
        ),
        { escalated: [] },
      ),
    };
  if (receipt.mutated_paths.includes(state.canonical)) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return {
    clean: receipt.status === "clean",
    diagnostics: receipt.escalated,
  };
}

async function processTalkStrict(runtime, state) {
  const observe = await runtime.runOperation(
    talkObservePrompt(state),
    {
      phase: "Recall",
      agentType: "quasi:transcribe-agent",
      label: `${state.slug}:observe`,
      schema: TALK_OBSERVE_SCHEMA,
    },
    {
      key: "talk.observe",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: [],
      unknownFailureCode: "talk.readonly_outcome_unknown",
    },
  );
  state.operations.push(observe);
  if (!strictObserve(observe, state)) {
    const unknown = runtimeUnknown(observe);
    return terminal(
      state,
      unknown ? "blocked" : "transcribe_failed",
      unknown ? "blocked" : "failed",
      "reconcile",
      operationFailure(
        "talk.observation_receipt_invalid",
        "talk.observe",
        unknown ? "unknown" : "known",
        "observation receipt did not prove exact Talk state",
      ),
    );
  }
  if (observe.status === "blocked")
    return terminal(
      state,
      "blocked",
      "blocked",
      "reconcile",
      observe.failure,
    );
  if (observe.status === "failed")
    return terminal(
      state,
      "transcribe_failed",
      "failed",
      "reconcile",
      observe.failure,
    );
  state.sourceSha256 = observe.source_sha256;
  state.requestFingerprint = observe.request_fingerprint;
  state.outputExists = observe.talk_exists;
  if (observe.prepared_path) {
    addGeneratedArtifacts(
      state,
      [
        {
          role: "prepared_media",
          path: observe.prepared_path,
          sha256: observe.prepared_sha256,
          size:
            observe.artifacts.find(
              (row) => row.path === observe.prepared_path,
            )?.size || 1,
        },
      ],
      "talk.observe:reconciled",
    );
  }
  if (
    observe.manifest_exists &&
    observe.request_fingerprint !== null
  ) {
    state.transcriptArtifacts = observe.artifacts.filter(
      (row) =>
        ["transcript", "subtitle", "engine_transcript"].includes(
          row.role,
        ),
    );
    addGeneratedArtifacts(
      state,
      state.transcriptArtifacts,
      "talk.transcribe:reconciled",
    );
    state.disposition = observe.talk_exists ? "reused" : null;
  }
  if (observe.talk_exists) {
    const observedCanonical = observe.artifacts.find(
      (row) => row.role === "canonical",
    );
    if (observedCanonical)
      addGeneratedArtifacts(
        state,
        [observedCanonical],
        "talk.reconcile",
      );
    else
      state.artifacts.push(
        artifact(
          "canonical",
          state.canonical,
          "talk.reconcile:stale",
          observe.talk_sha256,
          null,
        ),
      );
  }

  let inputPath = state.media;
  const prepared = state.artifacts.find(
    (row) => row.role === "prepared_media",
  );
  if (state.prepareMedia) {
    if (prepared) {
      inputPath = prepared.path;
    } else {
      state.budgets.prepareMedia.used = 1;
      const receipt = await runtime.runOperation(
        talkPrepareMediaPrompt(state),
        {
          phase: "Prepare",
          agentType: "quasi:transcribe-agent",
          label: `${state.slug}:prepare-media`,
          schema: TALK_PREPARE_MEDIA_SCHEMA,
        },
        {
          key: "talk.prepare-media",
          effect: "writer",
          retry: "forbidden",
          replay: "blocked",
          artifactRoles: ["prepared_media"],
          unknownFailureCode: "talk.writer_outcome_unknown",
        },
      );
      state.operations.push(receipt);
      if (!strictPrepare(receipt, state))
        return writerMismatch(
          state,
          "prepare-media",
          "talk.prepare-media",
        );
      if (receipt.status === "blocked")
        return terminal(
          state,
          "blocked",
          "blocked",
          "prepare-media",
          receipt.failure,
        );
      if (receipt.status === "failed")
        return terminal(
          state,
          "transcribe_failed",
          "failed",
          "prepare-media",
          receipt.failure,
        );
      addGeneratedArtifacts(
        state,
        [
          {
            role: "prepared_media",
            path: receipt.output_path,
            sha256: receipt.output_sha256,
            size: receipt.size,
          },
        ],
        receipt.action === "reconciled"
          ? "talk.prepare-media:reconciled"
          : "talk.prepare-media",
      );
      inputPath = state.prepared;
    }
  }

  if (!state.transcriptArtifacts.length) {
    state.budgets.transcribe.used = 1;
    const receipt = await runtime.runOperation(
      talkTranscribePrompt(state, inputPath),
      {
        phase: "Prepare",
        agentType: "quasi:transcribe-agent",
        label: `${state.slug}:transcribe`,
        schema: TALK_TRANSCRIBE_SCHEMA,
      },
      {
        key: "talk.transcribe",
        effect: "writer",
        retry: "forbidden",
        replay: "blocked",
        artifactRoles: [
          "transcript",
          "subtitle",
          "engine_transcript",
        ],
        unknownFailureCode: "talk.writer_outcome_unknown",
      },
    );
    state.operations.push(receipt);
    if (!strictTranscribe(receipt, state, inputPath))
      return writerMismatch(
        state,
        "transcribe",
        "talk.transcribe",
      );
    if (receipt.status === "blocked")
      return terminal(
        state,
        "blocked",
        "blocked",
        "transcribe",
        receipt.failure,
      );
    if (receipt.status === "failed")
      return terminal(
        state,
        "transcribe_failed",
        "failed",
        "transcribe",
        receipt.failure,
      );
    state.requestFingerprint = receipt.request_fingerprint;
    state.transcriptArtifacts = receipt.artifacts.filter(
      (row) =>
        ["transcript", "subtitle", "engine_transcript"].includes(
          row.role,
        ),
    );
    addGeneratedArtifacts(
      state,
      state.transcriptArtifacts,
      receipt.disposition === "reconciled"
        ? "talk.transcribe:reconciled"
        : "talk.transcribe",
    );
    if (
      receipt.disposition === "replaced" ||
      (state.outputExists &&
        receipt.disposition === "created")
    ) {
      state.transcriptReplaced = true;
      state.repaired = true;
      state.disposition = "repaired";
    }
  }

  const transcript = state.transcriptArtifacts.find(
    (row) => row.role === "transcript",
  );
  if (!transcript)
    return terminal(
      state,
      "transcribe_failed",
      "failed",
      "transcribe",
      operationFailure(
        "talk.transcript_missing",
        "talk.transcribe",
        "known",
        "committed transcription generation has no transcript",
      ),
    );

  state.budgets.classify.used = 1;
  const classification = await runtime.runOperation(
    talkClassifyPrompt(state, transcript.path),
    {
      phase: "Prepare",
      agentType: "quasi:transcribe-agent",
      label: `${state.slug}:classify`,
      schema: TALK_CLASSIFY_SCHEMA,
    },
    {
      key: "talk.classify",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: [],
      unknownFailureCode: "talk.readonly_outcome_unknown",
    },
  );
  state.operations.push(classification);
  if (!strictClassify(classification, state, transcript.path))
    return terminal(
      state,
      "transcribe_failed",
      "failed",
      "classify",
      operationFailure(
        "talk.classification_receipt_invalid",
        "talk.classify",
        runtimeUnknown(classification) ? "unknown" : "known",
        "classification receipt did not prove exact typed state",
      ),
    );
  if (classification.status === "failed")
    return terminal(
      state,
      "transcribe_failed",
      "failed",
      "classify",
      classification.failure,
    );
  state.classification = classification.signal;
  state.talkProducer =
    state.classification === "live"
      ? "talk.analyse"
      : "talk.render-silent";

  if (!state.outputExists || state.transcriptReplaced) {
    state.budgets.produce.used = 1;
    const produced = await runProducer(
      runtime,
      state,
      state.outputExists ? "repair" : "create",
      state.outputExists
        ? [
            {
              path: state.canonical,
              kind: "transcript_generation_changed",
              reason:
                "refresh the exact Talk product from the newly committed transcript generation",
            },
          ]
        : [],
    );
    if (produced.terminal) return produced.terminal;
  } else {
    state.disposition = "reused";
  }

  let audited = await runAudit(runtime, state, 1);
  if (audited.terminal) return audited.terminal;
  if (!audited.clean) {
    state.budgets.repair.used = 1;
    const repaired = await runProducer(
      runtime,
      state,
      "repair",
      audited.diagnostics,
    );
    if (repaired.terminal) return repaired.terminal;
    audited = await runAudit(runtime, state, 2);
    if (audited.terminal) return audited.terminal;
    if (!audited.clean)
      return terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        operationFailure(
          "talk.repair_exhausted",
          "talk.audit.legacy",
          "known",
          "Talk output remains non-clean after one producer repair",
        ),
        { escalated: audited.diagnostics },
      );
  }
  return terminal(
    state,
    "ok",
    "complete",
    "audit",
  );
}

export async function processTalk(runtime, slug, rawMeta) {
  runtime.phase("Recall");
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  return runtime.coalesce(
    `talk:${slug}`,
    validation.fingerprint,
    () =>
      processTalkStrict(
        runtime,
        createState(slug, validation.meta),
      ),
    () =>
      rejectedResult(
        slug,
        {
          ...validation,
          code: "talk.identity_conflict",
          message:
            "conflicting Talk identity for one material key",
        },
        true,
      ),
  );
}
