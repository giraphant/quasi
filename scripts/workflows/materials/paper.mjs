import {
  PAPER_ACQUIRE_STAGE_CONTRACT,
  paperAcquirePrompt,
  paperAcquireStageSchema,
} from "../operations/acquire.mjs";
import {
  PAPER_ANALYSE_STAGE_CONTRACT,
  paperAnalyseOperationPrompt,
  paperAnalyseStageSchema,
} from "../operations/analyse.mjs";
import {
  PAPER_AUDIT_STAGE_CONTRACT,
  paperAuditPrompt,
  paperAuditStageSchema,
} from "../operations/audit.mjs";
import {
  PAPER_PREPARE_STAGE_CONTRACT,
  paperPrepareStagePrompt,
  paperPrepareStageSchema,
} from "../operations/extract.mjs";
import { optionalText, validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { routeStageEdge } from "./route.mjs";
import { MATERIAL_RECEIPT_VERSION } from "./receipt.mjs";

const PAPER_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

function validatePaperIdentity(slug, meta) {
  if (typeof slug !== "string" || !PAPER_SLUG.test(slug))
    return {
      ok: false,
      code: "paper.slug_invalid",
      message: "paper slug is not canonical",
      canonicalSlug: null,
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "paper metadata must be an object",
      canonicalSlug: slug,
    };
  if (!validText(meta.title, 1, 500))
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "title is missing or invalid",
      canonicalSlug: slug,
    };
  if (
    !Array.isArray(meta.authors) ||
    meta.authors.length < 1 ||
    meta.authors.length > 32 ||
    meta.authors.some((author) => !validText(author, 1, 200))
  )
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "authors must be a bounded non-empty string array",
      canonicalSlug: slug,
    };
  if (
    !Number.isInteger(meta.year) ||
    meta.year < 1500 ||
    meta.year > 2030
  )
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "year must be an integer in the supported range",
      canonicalSlug: slug,
    };
  if (!validText(meta.journal, 1, 500))
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "journal is missing or invalid",
      canonicalSlug: slug,
    };
  if (
    !optionalText(meta.doi, 300) ||
    !optionalText(meta.oa_url, 2048) ||
    !optionalText(meta.url, 2048) ||
    (meta.confidence !== undefined &&
      !["provided", "verified"].includes(meta.confidence))
  )
    return {
      ok: false,
      code: "paper.identity_invalid",
      message: "optional identity fields are invalid",
      canonicalSlug: slug,
    };
  const normalized = {
    title: meta.title,
    authors: [...meta.authors],
    year: meta.year,
    journal: meta.journal,
    doi: meta.doi || null,
    oa_url: meta.oa_url || null,
    url: meta.url || null,
    confidence:
      meta.confidence === "verified" ? "verified" : "provided",
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
    operations: [],
    artifacts: [],
    audit: null,
    warnings: [],
    repaired: false,
    disposition: null,
    userGate: null,
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
    kind: "paper",
    id: state.slug,
    status,
    disposition:
      disposition ||
      (status === "complete"
        ? state.disposition ||
          (state.repaired ? "repaired" : "created")
        : null),
    stage,
    artifacts: state.artifacts,
    operations: state.operations,
    audit: state.audit,
    freshness: {
      observation: "unknown",
      basis: "operation-receipts-and-final-audit",
    },
    warnings: state.warnings,
    failure,
    user_gate: state.userGate,
    resume:
      status === "blocked"
        ? { operation_key: "paper.reconcile" }
        : status === "needs_input"
          ? { operation_key: "paper.user-gate", stage }
          : null,
  };
}

function rejectedPaperResult(slug, validation, code = null) {
  const canonical =
    typeof slug === "string" && PAPER_SLUG.test(slug);
  const failure = operationFailure(
    code || validation.code,
    "paper.identity",
    "known",
    validation.message ||
      "conflicting paper identity for one material key",
  );
  return {
    slug: typeof slug === "string" ? slug : null,
    status: "blocked",
    material_receipt: {
      schema_version: MATERIAL_RECEIPT_VERSION,
      material_key: canonical ? `paper:${slug}` : null,
      kind: "paper",
      id: typeof slug === "string" ? slug : null,
      status: "blocked",
      disposition: null,
      stage: "identity",
      artifacts: [],
      operations: [],
      audit: null,
      freshness: {
        observation: "unknown",
        basis: "operation-receipts-and-final-audit",
      },
      warnings: [],
      failure,
      user_gate: null,
      resume: null,
    },
  };
}

function result(state, status, stage, extra = {}, failure = null) {
  const terminal =
    status === "ok"
      ? "complete"
      : status === "blocked"
        ? "blocked"
        : status === "needs_input"
          ? "needs_input"
          : "failed";
  return {
    slug: state.slug,
    status,
    ...extra,
    material_receipt: materialReceipt(state, {
      status: terminal,
      stage,
      failure,
    }),
  };
}

function blocked(state, stage, operationKey, receipt) {
  const failure =
    (receipt && receipt.failure) ||
    operationFailure(
      "paper.writer_outcome_unknown",
      operationKey,
      "unknown",
    );
  return result(state, "blocked", stage, {}, failure);
}

function mismatchBlocked(state, stage, operationKey) {
  return result(
    state,
    "blocked",
    stage,
    {},
    operationFailure(
      "paper.writer_receipt_mismatch",
      operationKey,
      "unknown",
      "writer receipt did not prove the exact input/output contract",
    ),
  );
}

function routePaperStage(run, state, stage, operationKey, options) {
  return routeStageEdge(run, {
    ...options,
    state,
    stage,
    operationKey,
    emit: ({ status, extra, failure }) =>
      result(state, status, stage, extra, failure),
    unknown: (receipt) =>
      blocked(state, stage, operationKey, receipt),
    mismatch: () =>
      mismatchBlocked(state, stage, operationKey),
  });
}

function acquireFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "paper.acquire_failed",
    "paper.acquire",
    outcome,
    (issue && issue.summary) || "Paper Acquire did not complete",
  );
}

function prepareFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "paper.prepare_failed",
    "paper.prepare",
    outcome,
    (issue && issue.summary) || "Paper Prepare did not complete",
  );
}

function analyseFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "paper.analysis_failed",
    "paper.analyse",
    outcome,
    (issue && issue.summary) || "Paper Analyse did not complete",
  );
}

function auditFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "paper.audit_failed",
    "paper.audit",
    outcome,
    (issue && issue.summary) || "Paper Audit did not complete",
  );
}

async function prepare(runtime, state) {
  const schema = paperPrepareStageSchema({
    materialKey: state.materialKey,
    source: state.source,
    normalized: state.sourceText,
    recoverySource: state.ocrSource,
    recoveryText: state.ocrText,
  });
  const run = await runtime.operate(
    paperPrepareStagePrompt({
      materialKey: state.materialKey,
      source: state.source,
      normalized: state.sourceText,
      recoverySource: state.ocrSource,
      recoveryText: state.ocrText,
    }),
    {
      phase: "Prepare",
      agentType: "quasi:extract-agent",
      label: `${state.slug}:prepare`,
      schema,
    },
    {
      key: "paper.prepare",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["normalized_text", "recovery_source"],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: PAPER_PREPARE_STAGE_CONTRACT,
      context: {
        normalized: state.sourceText,
        recoverySource: state.ocrSource,
        recoveryText: state.ocrText,
      },
    },
  );
  const routed = routePaperStage(
    run,
    state,
    "prepare",
    "paper.prepare",
    {
      failure: prepareFailure,
      blockedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }),
      needsInputExtra: (receipt) => ({
        question: receipt.terminal.issue.user_question,
      }),
      failedStatus: "analyse_failed",
      failedExtra: (receipt) => ({ diagnostics: receipt.diagnostics }),
      onOk: (receipt) => {
        for (const artifact of receipt.artifacts)
          state.artifacts.push({
            ...artifact,
            producer: "paper.prepare",
          });
        return { input: receipt.selected_input };
      },
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function analyse(
  runtime,
  state,
  meta,
  input,
  mode = "create",
  diagnostics = [],
) {
  const analysis = await runtime.operate(
    paperAnalyseOperationPrompt(
      state.slug,
      meta,
      input,
      mode,
      diagnostics,
    ),
    {
      phase: "Analyse",
      agentType: "quasi:analyse-agent",
      label: `${state.slug}:analyse`,
      schema: paperAnalyseStageSchema({
        materialKey: state.materialKey,
        mode,
        input,
        output: state.canonical,
      }),
    },
    {
      key: "paper.analyse",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
      contract: PAPER_ANALYSE_STAGE_CONTRACT,
      context: { mode, input, output: state.canonical },
    },
  );
  const routed = routePaperStage(
    analysis,
    state,
    "analyse",
    "paper.analyse",
    {
      failure: analyseFailure,
      blockedFailure: (receipt) => analyseFailure(receipt, "unknown"),
      failedStatus: "analyse_failed",
      failedExtra: (receipt) => ({
        notes: stageIssue(receipt).code,
      }),
      onOk: (receipt) => {
        const { action } = receipt.terminal;
        state.artifacts = state.artifacts.filter(
          (artifact) => artifact.role !== "canonical",
        );
        state.artifacts.push({
          role: "canonical",
          path: state.canonical,
          exists: true,
          usable: true,
          producer:
            action === "reconciled"
              ? "paper.analyse:reconciled"
              : "paper.analyse",
        });
        if (mode === "repair" && action === "repair") {
          state.repaired = true;
          state.disposition = "repaired";
        } else if (action === "reconciled") {
          state.repaired = false;
          state.disposition = "reused";
        } else state.disposition = "created";
        return { action };
      },
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function audit(runtime, state, pass) {
  const auditRun = await runtime.operate(
    paperAuditPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit`,
      schema: paperAuditStageSchema({
        materialKey: state.materialKey,
        target: state.canonical,
        pass,
      }),
    },
    {
      key: "paper.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
      contract: PAPER_AUDIT_STAGE_CONTRACT,
      context: { target: state.canonical, pass },
    },
  );
  const routed = routePaperStage(
    auditRun,
    state,
    "audit",
    "paper.audit",
    {
      failure: auditFailure,
      blockedFailure: (receipt) => auditFailure(receipt, "unknown"),
      onReceipt: (receipt, edge) => {
        if (edge === "unknown" || edge === "mismatch") return;
        state.audit = receipt;
        if (receipt.mutated_paths.includes(state.canonical)) {
          state.repaired = true;
          state.disposition = "repaired";
        }
      },
      blockedStatus: "audit_escalated",
      failedStatus: "audit_escalated",
      onOk: (receipt) => ({
        receipt,
        escalated: receipt.escalated,
        clean:
          receipt.terminal.status === "complete" &&
          receipt.escalated.length === 0 &&
          receipt.remaining_violations === 0,
      }),
    },
  );
  return routed.terminal ? { terminal: routed.terminal } : routed.value;
}

async function processValidatedPaper(runtime, slug, meta) {
  const { phase } = runtime;
  phase("Acquire");
  const state = createPaperState(slug);

  const download = await runtime.operate(
    paperAcquirePrompt(slug, meta),
    {
      phase: "Acquire",
      agentType: "quasi:download-agent",
      label: `${slug}:acquire`,
      schema: paperAcquireStageSchema({
        materialKey: state.materialKey,
        slug,
        output: state.source,
        doi: meta.doi,
      }),
    },
    {
      key: "paper.acquire",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["source"],
      unknownFailureCode: "material.writer_outcome_unknown",
      contract: PAPER_ACQUIRE_STAGE_CONTRACT,
      context: { output: state.source },
    },
  );
  const routed = routePaperStage(
    download,
    state,
    "download",
    "paper.acquire",
    {
      failure: acquireFailure,
      needsInputExtra: (receipt) => ({
        question: receipt.terminal.issue.user_question,
      }),
      failedStatus: "download_failed",
      failedExtra: (receipt) => ({
        doi: receipt.doi || meta.doi || null,
        source: receipt.source || null,
        failure_reason: receipt.terminal.issue.summary,
        attempts: receipt.attempts,
      }),
      onOk: (receipt) => {
        state.artifacts.push({
          role: "source",
          path: state.source,
          exists: true,
          usable: null,
          producer:
            receipt.disposition === "reused"
              ? "paper.acquire:reconciled"
              : "paper.acquire",
        });
      },
    },
  );
  if (routed.terminal) return routed.terminal;

  phase("Prepare");
  const prepared = await prepare(runtime, state);
  if (prepared.terminal) return prepared.terminal;

  phase("Analyse");
  const analysisResult = await analyse(
    runtime,
    state,
    meta,
    prepared.input,
  );
  if (analysisResult.terminal) return analysisResult.terminal;
  phase("Audit");
  let auditResult = await audit(runtime, state, 1);
  if (auditResult.terminal) return auditResult.terminal;
  if (!auditResult.clean) {
    const exactDiagnostics = auditResult.escalated
      .filter(
        (diagnostic) =>
          diagnostic &&
          diagnostic.path === state.canonical &&
          diagnostic.kind &&
          diagnostic.reason,
      )
      .map(({ path, kind, reason }) => ({
        path,
        kind,
        reason,
      }));
    if (
      !exactDiagnostics.length ||
      exactDiagnostics.length !== auditResult.escalated.length
    )
      return result(
        state,
        "audit_escalated",
        "audit",
        { escalated: auditResult.escalated },
        operationFailure(
          "paper.repair_owner_unknown",
          "paper.audit",
        ),
      );

    phase("Analyse");
    const repairResult = await analyse(
      runtime,
      state,
      meta,
      prepared.input,
      "repair",
      exactDiagnostics,
    );
    if (repairResult.terminal) return repairResult.terminal;
    phase("Audit");
    auditResult = await audit(runtime, state, 2);
    if (auditResult.terminal) return auditResult.terminal;
    if (!auditResult.clean)
      return result(
        state,
        "audit_escalated",
        "audit",
        { escalated: auditResult.escalated },
        operationFailure(
          "paper.repair_exhausted",
          "paper.audit",
        ),
      );
  }

  return result(state, "ok", "audit");
}

export async function processPaper(runtime, slug, meta) {
  const validation = validatePaperIdentity(slug, meta);
  if (!validation.ok)
    return rejectedPaperResult(slug, validation);
  return runtime.coalesce(
    `paper:${slug}`,
    validation.fingerprint,
    () =>
      processValidatedPaper(
        runtime,
        slug,
        validation.meta,
      ),
    () =>
      rejectedPaperResult(
        slug,
        {
          code: "paper.identity_conflict",
          message:
            "same-run requests disagree on the paper identity",
        },
        "paper.identity_conflict",
      ),
  );
}
