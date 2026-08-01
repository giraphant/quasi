import {
  paperAcquire,
  paperAnalyse,
  paperAudit,
  paperPrepare,
} from "../operations/rows/paper.mjs";
import { optionalText, validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { runMaterialLoop } from "./interpreter.mjs";
import { assembleMaterialReceipt } from "./receipt.mjs";

const PAPER_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

function validatePaperIdentity(slug, meta) {
  if (typeof slug !== "string" || !PAPER_SLUG.test(slug))
    return { ok: false, code: "paper.slug_invalid", message: "paper slug is not canonical", canonicalSlug: null };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return { ok: false, code: "paper.identity_invalid", message: "paper metadata must be an object", canonicalSlug: slug };
  if (!validText(meta.title, 1, 500))
    return { ok: false, code: "paper.identity_invalid", message: "title is missing or invalid", canonicalSlug: slug };
  if (!Array.isArray(meta.authors) || meta.authors.length < 1 || meta.authors.length > 32 || meta.authors.some((author) => !validText(author, 1, 200)))
    return { ok: false, code: "paper.identity_invalid", message: "authors must be a bounded non-empty string array", canonicalSlug: slug };
  if (!Number.isInteger(meta.year) || meta.year < 1500 || meta.year > 2030)
    return { ok: false, code: "paper.identity_invalid", message: "year must be an integer in the supported range", canonicalSlug: slug };
  if (!validText(meta.journal, 1, 500))
    return { ok: false, code: "paper.identity_invalid", message: "journal is missing or invalid", canonicalSlug: slug };
  if (!optionalText(meta.doi, 300) || !optionalText(meta.oa_url, 2048) || !optionalText(meta.url, 2048) || (meta.confidence !== undefined && !["provided", "verified"].includes(meta.confidence)))
    return { ok: false, code: "paper.identity_invalid", message: "optional identity fields are invalid", canonicalSlug: slug };
  const normalized = {
    title: meta.title,
    authors: [...meta.authors],
    year: meta.year,
    journal: meta.journal,
    doi: meta.doi || null,
    oa_url: meta.oa_url || null,
    url: meta.url || null,
    confidence: meta.confidence === "verified" ? "verified" : "provided",
  };
  return {
    ok: true,
    canonicalSlug: slug,
    meta: normalized,
    fingerprint: JSON.stringify({
      title: normalized.title,
      authors: normalized.authors,
      year: normalized.year,
      journal: normalized.journal,
      doi: normalized.doi,
    }),
  };
}

const operationFailure = (code, operationKey, outcome = "known", message = null) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable: false,
  ...(message ? { message } : {}),
});

function createPaperState(slug) {
  return {
    slug,
    materialKey: `paper:${slug}`,
    source: `sources/${slug}.pdf`,
    sourceText: `processing/papers/${slug}/source.txt`,
    ocrSource: `processing/papers/${slug}/ocr.pdf`,
    ocrText: `processing/papers/${slug}/ocr.txt`,
    canonical: `vault/papers/${slug}.md`,
    preparedInput: null,
    operations: [],
    artifacts: [],
    audit: null,
    warnings: [],
    repaired: false,
    disposition: null,
    userGate: null,
  };
}

function paperReceipt(state, status, stage, failure = null) {
  return assembleMaterialReceipt(state, {
    kind: "paper",
    status,
    stage,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "paper.reconcile" }
        : status === "needs_input"
          ? { operation_key: "paper.user-gate", stage }
          : null,
  });
}

function paperResult(state, status, stage, extra = {}, failure = null) {
  const terminalStatus = status === "ok" ? "complete" : status === "blocked" ? "blocked" : status === "needs_input" ? "needs_input" : "failed";
  return { slug: state.slug, status, ...extra, material_receipt: paperReceipt(state, terminalStatus, stage, failure) };
}

function rejectedPaperResult(slug, validation) {
  const state = createPaperState(typeof slug === "string" ? slug : null);
  state.materialKey = typeof slug === "string" && PAPER_SLUG.test(slug) ? `paper:${slug}` : null;
  return paperResult(
    state,
    "blocked",
    "identity",
    {},
    operationFailure(validation.code, "paper.identity", "known", validation.message || "conflicting paper identity for one material key"),
  );
}

const receiptFailure = (fallback, operationKey) => (receipt, outcome = "known") => {
  const issue = stageIssue(receipt);
  return operationFailure((issue && issue.code) || fallback, operationKey, outcome, (issue && issue.summary) || `${operationKey} did not complete`);
};

const acquireFailure = receiptFailure("paper.acquire_failed", "paper.acquire");
const prepareFailure = receiptFailure("paper.prepare_failed", "paper.prepare");
const analyseFailure = receiptFailure("paper.analysis_failed", "paper.analyse");
const auditFailure = receiptFailure("paper.audit_failed", "paper.audit");

function addPreparedArtifacts(state, receipt) {
  for (const artifact of receipt.artifacts)
    state.artifacts.push({ ...artifact, producer: "paper.prepare" });
  state.preparedInput = receipt.selected_input;
  return { input: receipt.selected_input };
}

function applyAnalysis(state, receipt, _meta, _opts, call) {
  const { action } = receipt.terminal;
  state.artifacts = state.artifacts.filter((artifact) => artifact.role !== "canonical");
  state.artifacts.push({
    role: "canonical",
    path: state.canonical,
    exists: true,
    usable: true,
    producer: action === "reconciled" ? "paper.analyse:reconciled" : "paper.analyse",
  });
  if (call.mode === "repair" && action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (action === "reconciled") {
    state.repaired = false;
    state.disposition = "reused";
  } else state.disposition = "created";
  return { action };
}

function applyAudit(state, receipt) {
  state.audit = receipt;
  if (receipt.mutated_paths.includes(state.canonical)) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return {
    receipt,
    escalated: receipt.escalated,
    clean: receipt.terminal.status === "complete" && receipt.escalated.length === 0 && receipt.remaining_violations === 0,
  };
}

function paperRepairInput(state, audited) {
  if (audited.clean) return null;
  const diagnostics = audited.escalated
    .filter((item) => item && item.path === state.canonical && item.kind && item.reason)
    .map(({ path, kind, reason }) => ({ path, kind, reason }));
  if (diagnostics.length && diagnostics.length === audited.escalated.length) return diagnostics;
  return {
    terminal: paperResult(
      state,
      "audit_escalated",
      "audit",
      { escalated: audited.escalated },
      operationFailure("paper.repair_owner_unknown", "paper.audit"),
    ),
  };
}

const paperTable = {
  kind: "paper",
  identity: {
    pattern: PAPER_SLUG,
    validate: validatePaperIdentity,
    key: (slug) => `paper:${slug}`,
    fingerprint: (_slug, meta) => JSON.stringify({ title: meta.title, authors: meta.authors, year: meta.year, journal: meta.journal, doi: meta.doi }),
    conflict: () => ({ code: "paper.identity_conflict", message: "same-run requests disagree on the paper identity" }),
  },
  state: createPaperState,
  receipt: paperReceipt,
  reject: rejectedPaperResult,
  emit: (state, { status, stage, extra, failure }) => paperResult(state, status, stage, extra, failure),
  unknown: (state, descriptor, receipt) => paperResult(
    state,
    "blocked",
    descriptor.receiptStage,
    {},
    receipt && receipt.failure ? receipt.failure : operationFailure("paper.writer_outcome_unknown", descriptor.operationKey, "unknown"),
  ),
  mismatch: (state, descriptor) => paperResult(
    state,
    "blocked",
    descriptor.receiptStage,
    {},
    operationFailure("paper.writer_receipt_mismatch", descriptor.operationKey, "unknown", "writer receipt did not prove the exact input/output contract"),
  ),
  stages: [
    {
      stage: "Acquire",
      receiptStage: "download",
      operationKey: "paper.acquire",
      row: paperAcquire,
      label: (state) => `${state.slug}:acquire`,
      context: (state, meta) => ({ materialKey: state.materialKey, slug: state.slug, meta, output: state.source, doi: meta.doi, artifactRoles: ["source"] }),
      routeOptions: (_state, meta) => ({
        failure: acquireFailure,
        needsInputExtra: (receipt) => ({ question: receipt.terminal.issue.user_question }),
        failedStatus: "download_failed",
        failedExtra: (receipt) => ({ doi: receipt.doi || meta.doi || null, source: receipt.source || null, failure_reason: receipt.terminal.issue.summary, attempts: receipt.attempts }),
      }),
      apply: (state, receipt) => {
        state.artifacts.push({ role: "source", path: state.source, exists: true, usable: null, producer: receipt.disposition === "reused" ? "paper.acquire:reconciled" : "paper.acquire" });
      },
    },
    {
      stage: "Prepare",
      receiptStage: "prepare",
      operationKey: "paper.prepare",
      row: paperPrepare,
      label: (state) => `${state.slug}:prepare`,
      context: (state) => ({ materialKey: state.materialKey, source: state.source, normalized: state.sourceText, recoverySource: state.ocrSource, recoveryText: state.ocrText, artifactRoles: ["normalized_text", "recovery_source"] }),
      routeOptions: () => ({
        failure: prepareFailure,
        blockedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }),
        needsInputExtra: (receipt) => ({ question: receipt.terminal.issue.user_question }),
        failedStatus: "analyse_failed",
        failedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }),
      }),
      apply: addPreparedArtifacts,
    },
    {
      stage: "Analyse",
      receiptStage: "analyse",
      operationKey: "paper.analyse",
      row: paperAnalyse,
      label: (state, call) => `${state.slug}:${call.mode === "repair" ? "analyse-repair" : "analyse"}`,
      context: (state, meta, _opts, call) => ({ materialKey: state.materialKey, slug: state.slug, meta, input: state.preparedInput, output: state.canonical, mode: call.mode, diagnostics: call.diagnostics, replay: call.mode === "repair" ? "reconciled" : "blocked", artifactRoles: ["canonical"], unknownFailureCode: "paper.writer_outcome_unknown" }),
      routeOptions: () => ({ failure: analyseFailure, blockedFailure: (receipt) => analyseFailure(receipt, "unknown"), failedStatus: "analyse_failed", failedExtra: (receipt) => ({ notes: stageIssue(receipt).code }) }),
      apply: applyAnalysis,
    },
    {
      stage: "Audit",
      receiptStage: "audit",
      operationKey: "paper.audit",
      row: paperAudit,
      label: (state, call) => `${state.slug}:audit${call.pass === 1 ? "" : `-${call.pass}`}`,
      context: (state, _meta, _opts, call) => ({ materialKey: state.materialKey, slug: state.slug, target: state.canonical, pass: call.pass, replay: "reconciled", artifactRoles: ["canonical"], unknownFailureCode: "paper.writer_outcome_unknown" }),
      routeOptions: (state) => ({ failure: auditFailure, blockedFailure: (receipt) => auditFailure(receipt, "unknown"), onReceipt: (receipt, edge) => { if (edge !== "unknown" && edge !== "mismatch") state.audit = receipt; }, blockedStatus: "audit_escalated", failedStatus: "audit_escalated" }),
      apply: applyAudit,
      repair: {
        once: true,
        escalationsFrom: paperRepairInput,
        target: (_state, diagnostics) => [{ stage: "Analyse", diagnostics }],
        exhausted: (state, audited) => audited.clean ? null : paperResult(state, "audit_escalated", "audit", { escalated: audited.escalated }, operationFailure("paper.repair_exhausted", "paper.audit")),
      },
    },
  ],
  complete: (state) => paperResult(state, "ok", "audit"),
};

export async function processPaper(runtime, slug, meta) {
  return runMaterialLoop(runtime, paperTable, slug, meta);
}
