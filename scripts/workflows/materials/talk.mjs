import {
  talkAnalyse,
  talkAudit,
  talkPrepare,
} from "../operations/rows/talk.mjs";
import { validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { MATERIAL_RECEIPT_VERSION } from "./receipt.mjs";
import { routeStageEdge } from "./route.mjs";

const TALK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
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
      produce: { used: 0, limit: 1 },
      repair: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 2 },
    },
    warnings: [],
    userGate: null,
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
    user_gate: state.userGate,
    resume:
      status === "blocked"
        ? { operation_key: "talk.reconcile" }
        : status === "needs_input"
          ? { operation_key: "talk.user-gate", stage }
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

function routeTalkStage(run, state, stage, operationKey, options) {
  return routeStageEdge(run, {
    ...options,
    state,
    stage,
    operationKey,
    emit: ({ status, receiptStatus, extra, failure }) =>
      terminal(
        state,
        status,
        receiptStatus ||
          (status === "blocked"
            ? "blocked"
            : status === "needs_input"
              ? "needs_input"
              : "failed"),
        stage,
        failure,
        extra,
      ),
    unknown: (receipt) =>
      options.unknown
        ? options.unknown(receipt)
        : writerMismatch(state, stage, operationKey, receipt),
    mismatch: () =>
      options.mismatch
        ? options.mismatch()
        : writerMismatch(state, stage, operationKey),
  });
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

function prepareFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "talk.prepare_failed",
    "talk.prepare",
    outcome,
    (issue && issue.summary) || "Talk Prepare did not complete",
  );
}

function analyseFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "talk.analysis_failed",
    "talk.analyse",
    outcome,
    (issue && issue.summary) || "Talk Analyse did not complete",
  );
}

async function prepareTalk(runtime, state, repairDiagnostics = []) {
  const context = {
    materialKey: state.materialKey,
    slug: state.slug,
    title: state.title,
    date: state.date,
    language: state.lang,
    media: state.media,
    manifest: state.manifest,
    prepared: state.prepared,
    transcript: state.transcript,
    subtitle: state.subtitle,
    canonical: state.canonical,
    processingDir: state.processingDir,
    engines: state.engines,
    prepareMedia: state.prepareMedia,
    repairDiagnostics,
    repair: repairDiagnostics.length > 0,
    artifactRoles: [
      "prepared_media",
      "transcript",
      "subtitle",
      "engine_transcript",
      "canonical",
    ],
    unknownFailureCode: "talk.writer_outcome_unknown",
  };
  const spec = talkPrepare.spec(context);
  const run = await runtime.operate(
    talkPrepare.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label: repairDiagnostics.length
        ? `${state.slug}:prepare-repair`
        : `${state.slug}:prepare`,
      schema: talkPrepare.schema(context),
    },
    spec,
  );
  const routed = routeTalkStage(
    run,
    state,
    "prepare",
    "talk.prepare",
    {
      unknown: (receipt) =>
        terminal(
          state,
          "blocked",
          "blocked",
          "prepare",
          prepareFailure(receipt, "unknown"),
        ),
      failure: prepareFailure,
      needsInputExtra: (receipt) => ({
        question: receipt.terminal.issue.user_question,
      }),
      failedStatus: "transcribe_failed",
      failedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }),
      onOk: (receipt) => {
        state.sourceSha256 = receipt.source_observation.sha256;
        state.requestFingerprint =
          receipt.generation_observation.request_fingerprint;
        state.outputExists = receipt.canonical_observation !== null;
        state.transcriptReplaced = receipt.transcript_changed;
        state.classification = receipt.classification;
        state.transcriptArtifacts = receipt.artifacts.filter((row) =>
          ["transcript", "subtitle", "engine_transcript"].includes(row.role),
        );
        addGeneratedArtifacts(state, receipt.artifacts, "talk.prepare");
        if (state.outputExists) {
          const canonicalArtifact = receipt.artifacts.find(
            (item) =>
              item.role === "canonical" && item.path === state.canonical,
          );
          state.artifacts = state.artifacts.filter(
            (item) => item.path !== state.canonical,
          );
          state.artifacts.push(
            artifact(
              "canonical",
              state.canonical,
              receipt.canonical_action
                ? `talk.prepare:${receipt.canonical_action}`
                : "talk.prepare:observed",
              receipt.canonical_observation.sha256,
              canonicalArtifact ? canonicalArtifact.size : null,
            ),
          );
          if (receipt.canonical_action === "create") {
            state.disposition = "created";
            if (!repairDiagnostics.length)
              state.budgets.produce.used = 1;
          } else if (receipt.canonical_action === "repair") {
            state.repaired = true;
            state.disposition = "repaired";
            if (!repairDiagnostics.length)
              state.budgets.produce.used = 1;
          } else state.disposition = "reused";
        }
        if (
          state.classification === "live" &&
          state.transcriptReplaced &&
          state.outputExists
        ) {
          state.repaired = true;
          state.disposition = "repaired";
        }
        return { value: { receipt } };
      },
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function runProducer(
  runtime,
  state,
  mode,
  diagnostics,
) {
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
  const context = {
    materialKey: state.materialKey,
    title: state.title,
    date: state.date,
    media: state.media,
    inputs,
    output: state.canonical,
    mode,
    diagnostics,
    replay: mode === "repair" ? "reconciled" : "blocked",
    artifactRoles: ["canonical"],
    unknownFailureCode: "talk.writer_outcome_unknown",
  };
  const spec = talkAnalyse.spec(context);
  const analysis = await runtime.operate(
    talkAnalyse.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label:
        mode === "repair"
          ? `${state.slug}:analyse-repair`
          : `${state.slug}:analyse`,
      schema: talkAnalyse.schema(context),
    },
    spec,
  );
  const routed = routeTalkStage(
    analysis,
    state,
    "analyse",
    "talk.analyse",
    {
      failure: analyseFailure,
      blockedFailure: (receipt) => analyseFailure(receipt, "unknown"),
      failedStatus: "analyse_failed",
      onOk: (receipt) => {
        const { action } = receipt.terminal;
        state.talkProducer = "talk.analyse";
        state.artifacts = state.artifacts.filter(
          (item) => item.path !== state.canonical,
        );
        state.artifacts.push(
          artifact(
            "canonical",
            state.canonical,
            action === "reconciled"
              ? "talk.analyse:reconciled"
              : "talk.analyse",
          ),
        );
        if (action === "repair") {
          state.repaired = true;
          state.disposition = "repaired";
        } else if (action === "reconciled") {
          state.disposition = state.disposition || "reused";
        } else state.disposition = "created";
        return { value: { receipt } };
      },
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function runAudit(runtime, state, pass) {
  const context = {
    materialKey: state.materialKey,
    target: state.canonical,
    pass,
    artifactRoles: ["canonical"],
    unknownFailureCode: "talk.writer_outcome_unknown",
  };
  const spec = talkAudit.spec(context);
  const auditRun = await runtime.operate(
    talkAudit.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label:
        pass === 1
          ? `${state.slug}:audit`
          : `${state.slug}:audit-${pass}`,
      schema: talkAudit.schema(context),
    },
    spec,
  );
  const ownerFailure = (receipt) =>
    operationFailure(
      "talk.repair_owner_unknown",
      "talk.audit",
      "known",
      "audit named a path outside the exact Talk product",
    );
  const auditFailure = (receipt, outcome = "known") => {
    const issue = stageIssue(receipt);
    return operationFailure(
      (issue && issue.code) || "talk.audit_failed",
      "talk.audit",
      outcome,
      (issue && issue.summary) || "Talk Audit did not complete",
    );
  };
  const routed = routeTalkStage(
    auditRun,
    state,
    "audit",
    "talk.audit",
    {
      onReceipt: (receipt, edge) => {
        if (edge === "unknown" || edge === "mismatch") return;
        state.audit.push(receipt);
        state.budgets.auditPasses.used += 1;
      },
      failure: (receipt, outcome = "known") =>
        ownedAuditPaths(receipt, state)
          ? auditFailure(receipt, outcome)
          : ownerFailure(receipt),
      blockedFailure: (receipt) =>
        ownedAuditPaths(receipt, state)
          ? auditFailure(receipt, "unknown")
          : ownerFailure(receipt),
      blockedStatus: "audit_escalated",
      blockedExtra: (receipt) => ({
        escalated: ownedAuditPaths(receipt, state)
          ? []
          : receipt.escalated,
      }),
      failedStatus: "audit_escalated",
      failedExtra: (receipt) => ({
        escalated: ownedAuditPaths(receipt, state)
          ? []
          : receipt.escalated,
      }),
      onOk: (receipt) => {
        if (!ownedAuditPaths(receipt, state))
          return {
            terminal: terminal(
              state,
              "audit_escalated",
              "failed",
              "audit",
              ownerFailure(receipt),
              { escalated: receipt.escalated },
            ),
          };
        if (receipt.mutated_paths.includes(state.canonical)) {
          state.repaired = true;
          state.disposition = "repaired";
        }
        return {
          value: {
            clean:
              receipt.terminal.status === "complete" &&
              receipt.remaining_violations === 0 &&
              receipt.escalated.length === 0,
            diagnostics: receipt.escalated,
          },
        };
      },
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function processTalkStrict(runtime, state) {
  runtime.phase("Prepare");
  const prepared = await prepareTalk(runtime, state);
  if (prepared.terminal) return prepared.terminal;
  state.talkProducer =
    state.classification === "live"
      ? "talk.analyse"
      : "talk.prepare";

  if (
    state.classification === "live" &&
    (!state.outputExists || state.transcriptReplaced)
  ) {
    runtime.phase("Analyse");
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
  } else if (state.outputExists) {
    state.disposition = state.disposition || "reused";
  } else {
    return writerMismatch(state, "prepare", "talk.prepare");
  }

  runtime.phase("Audit");
  let audited = await runAudit(runtime, state, 1);
  if (audited.terminal) return audited.terminal;
  if (!audited.clean) {
    state.budgets.repair.used = 1;
    let repaired;
    if (state.classification === "live") {
      runtime.phase("Analyse");
      repaired = await runProducer(
        runtime,
        state,
        "repair",
        audited.diagnostics,
      );
    } else {
      runtime.phase("Prepare");
      repaired = await prepareTalk(
        runtime,
        state,
        audited.diagnostics,
      );
    }
    if (repaired.terminal) return repaired.terminal;
    runtime.phase("Audit");
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
          "talk.audit",
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
