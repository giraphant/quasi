import { talkAnalyse, talkAudit, talkPrepare } from "../operations/rows/talk.mjs";
import { validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { runMaterialLoop } from "./interpreter.mjs";
import { assembleMaterialReceipt } from "./receipt.mjs";

const TALK_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const ENGINES = new Set(["soniox", "apple", "parakeet", "whisper"]);
const LANGS = new Set(["auto", "en", "zh", "yue", "ja", "fr", "de", "es"]);
const VIDEO_EXTENSIONS = new Set(["mov", "mp4", "m4v", "mkv", "webm"]);
const MEDIA_EXTENSIONS = new Set([...VIDEO_EXTENSIONS, "m4a", "wav", "mp3", "aac", "flac", "aiff", "aif", "ogg", "opus"]);

function validDate(value) {
  if (!DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function mediaExtension(path) {
  const match = String(path).match(/\.([A-Za-z0-9]+)$/);
  return match ? match[1].toLowerCase() : "";
}

function validateIdentity(slug, meta) {
  if (typeof slug !== "string" || !TALK_SLUG.test(slug)) return { ok: false, code: "talk.identity_invalid", message: "talk slug is not canonical ASCII kebab" };
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) return { ok: false, code: "talk.identity_invalid", message: "talk metadata must be an object" };
  if (!validText(meta.title, 2, 280)) return { ok: false, code: "talk.identity_invalid", message: "title is missing or invalid" };
  if (!validDate(meta.date)) return { ok: false, code: "talk.identity_invalid", message: "date must be an exact calendar YYYY-MM-DD" };
  if (!validText(meta.media, 1, 2048) || meta.media.includes("\\") || meta.media.split("/").includes("..") || mediaExtension(meta.media) === "" || !MEDIA_EXTENSIONS.has(mediaExtension(meta.media)))
    return { ok: false, code: "talk.identity_invalid", message: "media path or extension is invalid" };
  const engines = meta.engines === undefined ? ["soniox", "apple", "parakeet"] : meta.engines;
  if (!Array.isArray(engines) || engines.length < 1 || engines.length > 4 || new Set(engines).size !== engines.length || engines.some((engine) => !ENGINES.has(engine)))
    return { ok: false, code: "talk.identity_invalid", message: "engines must be a unique supported ordered list" };
  const lang = meta.lang === undefined ? "auto" : meta.lang;
  if (!LANGS.has(lang)) return { ok: false, code: "talk.identity_invalid", message: "lang is not supported" };
  if (meta.prepare_media !== undefined && typeof meta.prepare_media !== "boolean") return { ok: false, code: "talk.identity_invalid", message: "prepare_media must be boolean when supplied" };
  const normalized = {
    title: meta.title,
    date: meta.date,
    media: meta.media,
    engines: [...engines],
    lang,
    prepare_media: meta.prepare_media === undefined ? VIDEO_EXTENSIONS.has(mediaExtension(meta.media)) : meta.prepare_media,
  };
  return { ok: true, meta: normalized, fingerprint: JSON.stringify(normalized) };
}

const operationFailure = (code, operationKey, outcome = "known", message = null) => ({ code, operation_key: operationKey, outcome, retryable: false, message });

function createState(slug, meta) {
  const talkDir = `vault/talks/${slug}`;
  return {
    slug,
    materialKey: `talk:${slug}`,
    title: meta.title,
    date: meta.date,
    media: meta.media,
    engines: meta.engines,
    lang: meta.lang,
    prepareMedia: meta.prepare_media,
    talkDir,
    processingDir: `processing/talks/${slug}`,
    manifest: `processing/talks/${slug}/manifest.json`,
    prepared: `${talkDir}/recording.mp4`,
    transcript: `${talkDir}/transcript.md`,
    subtitle: `${talkDir}/recording.srt`,
    canonical: `${talkDir}/talk.md`,
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
    budgets: { produce: { used: 0, limit: 1 }, repair: { used: 0, limit: 1 }, auditPasses: { used: 0, limit: 2 } },
    warnings: [],
    userGate: null,
  };
}

const artifact = (role, path, producer, sha256 = null, size = null) => ({ role, path, exists: true, usable: true, producer, sha256, size });

function talkReceipt(state, status, stage, failure = null) {
  return assembleMaterialReceipt(state, {
    kind: "talk",
    status,
    stage,
    failure,
    fields: { budgets: state.budgets },
    resume: status === "blocked" ? { operation_key: "talk.reconcile" } : status === "needs_input" ? { operation_key: "talk.user-gate", stage } : null,
  });
}

function terminal(state, legacyStatus, receiptStatus, stage, failure = null, extra = {}) {
  return {
    slug: state.slug,
    status: legacyStatus,
    classification: state.classification,
    transcript_path: state.transcriptArtifacts.length > 0 ? state.transcript : null,
    talk_path: state.artifacts.some((item) => item.role === "canonical") ? state.canonical : null,
    ...extra,
    material_receipt: talkReceipt(state, receiptStatus, stage, failure),
  };
}

function rejectedResult(slug, validation) {
  const safeSlug = typeof slug === "string" && TALK_SLUG.test(slug) ? slug : "";
  const state = createState(safeSlug, { title: safeSlug || "invalid", date: "1970-01-01", media: "invalid.wav", engines: ["apple"], lang: "auto", prepare_media: false });
  return terminal(state, "blocked", "blocked", "identity", operationFailure(validation.code, "talk.identity", "known", validation.message));
}

function writerMismatch(state, descriptor) {
  return terminal(state, "blocked", "blocked", descriptor.receiptStage, operationFailure("talk.writer_receipt_mismatch", descriptor.operationKey, "unknown", "writer receipt did not prove the exact contract"));
}

function addGeneratedArtifacts(state, rows, producer) {
  const replace = new Map(state.artifacts.map((item) => [item.path, item]));
  for (const row of rows) replace.set(row.path, artifact(row.role, row.path, producer, row.sha256, row.size));
  state.artifacts = [...replace.values()];
}

function analysisInputs(state) {
  const primary = state.transcriptArtifacts.find((row) => row.role === "transcript");
  const engines = state.engines.map((engine) => state.transcriptArtifacts.find((row) => row.role === "engine_transcript" && row.path === `${state.processingDir}/transcript.${engine}.srt`)).filter(Boolean);
  return primary ? [primary, ...engines] : [];
}

const stageFailure = (fallback, operationKey) => (receipt, outcome = "known") => {
  const issue = stageIssue(receipt);
  return operationFailure((issue && issue.code) || fallback, operationKey, outcome, (issue && issue.summary) || `${operationKey} did not complete`);
};
const prepareFailure = stageFailure("talk.prepare_failed", "talk.prepare");
const analyseFailure = stageFailure("talk.analysis_failed", "talk.analyse");

function applyPrepare(state, receipt, _meta, _opts, call) {
  state.sourceSha256 = receipt.source_observation.sha256;
  state.requestFingerprint = receipt.generation_observation.request_fingerprint;
  state.outputExists = receipt.canonical_observation !== null;
  state.transcriptReplaced = receipt.transcript_changed;
  state.classification = receipt.classification;
  state.transcriptArtifacts = receipt.artifacts.filter((row) => ["transcript", "subtitle", "engine_transcript"].includes(row.role));
  addGeneratedArtifacts(state, receipt.artifacts, "talk.prepare");
  if (state.outputExists) {
    const canonicalArtifact = receipt.artifacts.find((item) => item.role === "canonical" && item.path === state.canonical);
    state.artifacts = state.artifacts.filter((item) => item.path !== state.canonical);
    state.artifacts.push(artifact("canonical", state.canonical, receipt.canonical_action ? `talk.prepare:${receipt.canonical_action}` : "talk.prepare:observed", receipt.canonical_observation.sha256, canonicalArtifact ? canonicalArtifact.size : null));
    if (receipt.canonical_action === "create") {
      state.disposition = "created";
      if (call.mode !== "repair") state.budgets.produce.used = 1;
    } else if (receipt.canonical_action === "repair") {
      state.repaired = true;
      state.disposition = "repaired";
      if (call.mode !== "repair") state.budgets.produce.used = 1;
    } else if (state.classification !== "live" || !state.transcriptReplaced) state.disposition = "reused";
  }
  if (state.classification === "live" && state.transcriptReplaced && state.outputExists) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  state.talkProducer = state.classification === "live" ? "talk.analyse" : "talk.prepare";
  return { receipt };
}

function analysisContext(state, _meta, _opts, call) {
  const inputs = analysisInputs(state);
  if (!inputs.length)
    return { terminal: terminal(state, "analyse_failed", "failed", "analyse", operationFailure("talk.transcript_generation_invalid", "talk.analyse", "known", "live Talk has no exact committed transcript inputs")) };
  if (call.mode === "create") state.budgets.produce.used = 1;
  let mode = call.mode;
  let diagnostics = call.diagnostics;
  if (mode === "create" && state.outputExists) {
    mode = "repair";
    diagnostics = [{ path: state.canonical, kind: "transcript_generation_changed", reason: "refresh the exact Talk product from the newly committed transcript generation" }];
  }
  return { materialKey: state.materialKey, title: state.title, date: state.date, media: state.media, inputs, output: state.canonical, mode, diagnostics, replay: mode === "repair" ? "reconciled" : "blocked", artifactRoles: ["canonical"], unknownFailureCode: "talk.writer_outcome_unknown" };
}

function applyAnalysis(state, receipt) {
  const { action } = receipt.terminal;
  state.talkProducer = "talk.analyse";
  state.artifacts = state.artifacts.filter((item) => item.path !== state.canonical);
  state.artifacts.push(artifact("canonical", state.canonical, action === "reconciled" ? "talk.analyse:reconciled" : "talk.analyse"));
  if (action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (action === "reconciled") state.disposition = state.disposition || "reused";
  else state.disposition = "created";
  return { receipt };
}

const ownedAuditPaths = (receipt, state) => [...receipt.escalated.map((item) => item.path), ...receipt.mutated_paths].every((path) => path === state.canonical);

function applyAudit(state, receipt) {
  if (!ownedAuditPaths(receipt, state))
    return { terminal: terminal(state, "audit_escalated", "failed", "audit", operationFailure("talk.repair_owner_unknown", "talk.audit", "known", "audit named a path outside the exact Talk product"), { escalated: receipt.escalated }) };
  if (receipt.mutated_paths.includes(state.canonical)) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return { clean: receipt.terminal.status === "complete" && receipt.remaining_violations === 0 && receipt.escalated.length === 0, diagnostics: receipt.escalated };
}

function talkRepairInput(state, audited) {
  if (audited.clean) return null;
  state.budgets.repair.used = 1;
  return audited.diagnostics;
}

const talkTable = {
  kind: "talk",
  recallPhase: true,
  identity: {
    pattern: TALK_SLUG,
    validate: validateIdentity,
    key: (slug) => `talk:${slug}`,
    fingerprint: (_slug, meta) => JSON.stringify(meta),
    conflict: () => ({ code: "talk.identity_conflict", message: "conflicting Talk identity for one material key" }),
  },
  state: createState,
  receipt: talkReceipt,
  reject: rejectedResult,
  emit: (state, { status, receiptStatus, stage, extra, failure }) => terminal(state, status, receiptStatus || (status === "blocked" ? "blocked" : status === "needs_input" ? "needs_input" : "failed"), stage, failure, extra),
  unknown: (state, descriptor, receipt, options) => options.unknown ? options.unknown(receipt) : writerMismatch(state, descriptor),
  mismatch: (state, descriptor, _receipt, options) => options.mismatch ? options.mismatch() : writerMismatch(state, descriptor),
  stages: [
    {
      stage: "Prepare", receiptStage: "prepare", operationKey: "talk.prepare", row: talkPrepare,
      label: (state, call) => `${state.slug}:${call.mode === "repair" ? "prepare-repair" : "prepare"}`,
      context: (state, _meta, _opts, call) => ({ materialKey: state.materialKey, slug: state.slug, title: state.title, date: state.date, language: state.lang, media: state.media, manifest: state.manifest, prepared: state.prepared, transcript: state.transcript, subtitle: state.subtitle, canonical: state.canonical, processingDir: state.processingDir, engines: state.engines, prepareMedia: state.prepareMedia, repairDiagnostics: call.diagnostics, repair: call.mode === "repair", artifactRoles: ["prepared_media", "transcript", "subtitle", "engine_transcript", "canonical"], unknownFailureCode: "talk.writer_outcome_unknown" }),
      routeOptions: (state) => ({ unknown: (receipt) => terminal(state, "blocked", "blocked", "prepare", prepareFailure(receipt, "unknown")), failure: prepareFailure, needsInputExtra: (receipt) => ({ question: receipt.terminal.issue.user_question }), failedStatus: "transcribe_failed", failedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }) }),
      apply: applyPrepare,
    },
    {
      stage: "Analyse", receiptStage: "analyse", operationKey: "talk.analyse", row: talkAnalyse,
      skip: (state, _meta, _opts, call) => call.mode !== "repair" && !(state.classification === "live" && (!state.outputExists || state.transcriptReplaced)),
      label: (state, call, context) => `${state.slug}:${context.mode === "repair" ? "analyse-repair" : "analyse"}`,
      context: analysisContext,
      routeOptions: () => ({ failure: analyseFailure, blockedFailure: (receipt) => analyseFailure(receipt, "unknown"), failedStatus: "analyse_failed" }),
      apply: applyAnalysis,
    },
    {
      stage: "Audit", receiptStage: "audit", operationKey: "talk.audit", row: talkAudit,
      label: (state, call) => `${state.slug}:audit${call.pass === 1 ? "" : `-${call.pass}`}`,
      context: (state, _meta, _opts, call) => { state.budgets.auditPasses.used += 1; return { materialKey: state.materialKey, target: state.canonical, pass: call.pass, artifactRoles: ["canonical"], unknownFailureCode: "talk.writer_outcome_unknown" }; },
      routeOptions: (state) => {
        const ownerFailure = () => operationFailure("talk.repair_owner_unknown", "talk.audit", "known", "audit named a path outside the exact Talk product");
        const auditFailure = stageFailure("talk.audit_failed", "talk.audit");
        return {
          onReceipt: (receipt, edge) => { if (edge !== "unknown" && edge !== "mismatch") state.audit.push(receipt); },
          failure: (receipt, outcome = "known") => ownedAuditPaths(receipt, state) ? auditFailure(receipt, outcome) : ownerFailure(),
          blockedFailure: (receipt) => ownedAuditPaths(receipt, state) ? auditFailure(receipt, "unknown") : ownerFailure(),
          blockedStatus: "audit_escalated",
          blockedExtra: (receipt) => ({ escalated: ownedAuditPaths(receipt, state) ? [] : receipt.escalated }),
          failedStatus: "audit_escalated",
          failedExtra: (receipt) => ({ escalated: ownedAuditPaths(receipt, state) ? [] : receipt.escalated }),
        };
      },
      apply: applyAudit,
      repair: {
        once: true,
        escalationsFrom: talkRepairInput,
        target: (state, diagnostics) => [{ stage: state.classification === "live" ? "Analyse" : "Prepare", diagnostics }],
        exhausted: (state, audited) => audited.clean ? null : terminal(state, "audit_escalated", "failed", "audit", operationFailure("talk.repair_exhausted", "talk.audit", "known", "Talk output remains non-clean after one producer repair"), { escalated: audited.diagnostics }),
      },
    },
  ],
  complete: (state) => terminal(state, "ok", "complete", "audit"),
};

export async function processTalk(runtime, slug, rawMeta) {
  return runMaterialLoop(runtime, talkTable, slug, rawMeta);
}
