import {
  PAPER_ACQUIRE_CONTRACT,
  paperAcquirePrompt,
  paperAcquireSchema,
} from "../operations/acquire.mjs";
import {
  PAPER_ANALYSE_CONTRACT,
  paperAnalyseOperationPrompt,
  paperAnalyseSchema,
} from "../operations/analyse.mjs";
import {
  PAPER_AUDIT_CONTRACT,
  paperAuditPrompt,
  paperAuditSchema,
} from "../operations/audit.mjs";
import {
  PAPER_PREPARE_STAGE_CONTRACT,
  paperPrepareStagePrompt,
  paperPrepareStageSchema,
} from "../operations/extract.mjs";
import { optionalText, validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";

const MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1";
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

function auditOperation(receipt, output, pass) {
  const escalated = Array.isArray(receipt && receipt.escalated)
    ? receipt.escalated
    : [];
  const clean =
    receipt.status === "clean" &&
    escalated.length === 0 &&
    receipt.remaining_violations === 0;
  return {
    schema_version: "quasi.operation.paper.audit.receipt/0.1",
    key: "paper.audit",
    effect: "writer",
    status: receipt.status === "error" ? "failed" : "succeeded",
    attempt: 1,
    input_path: output,
    output_path: output,
    artifact_roles: ["canonical"],
    signal: clean ? "clean" : "escalated",
    pass,
    failure:
      receipt.status === "error"
        ? operationFailure(
          "paper.audit_failed",
          "paper.audit",
        )
        : null,
  };
}

function downloadOperation(item, output) {
  const succeeded = item && item.status === "ok";
  const blockedOutcome = item && item.status === "blocked";
  return {
    schema_version:
      "quasi.operation.paper.acquire.receipt/0.1",
    key: "paper.acquire",
    effect: "writer",
    status: succeeded
      ? "succeeded"
      : blockedOutcome
        ? "blocked"
        : "failed",
    attempt: 1,
    output_path: (item && item.path) || output,
    artifact_roles: ["source"],
    disposition: (item && item.disposition) || null,
    identity_verified:
      (item && item.identity_verified) || false,
    doi: (item && item.doi) || null,
    source: (item && item.source) || null,
    failure_reason:
      (item && (item.failure_reason || item.verdict_note)) || null,
    attempts:
      item && Array.isArray(item.attempts) ? item.attempts : [],
    failure: succeeded
      ? null
      : operationFailure(
          `paper.${(item && item.status) || "download_failed"}`,
          "paper.acquire",
          blockedOutcome ? "unknown" : "known",
        ),
  };
}

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
        basis: "identity-validation",
      },
      warnings: [],
      failure,
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

function prepareFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "paper.prepare_failed",
    "paper.prepare",
    outcome,
    (issue && issue.summary) || "Paper Prepare did not complete",
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
  state.operations.push(run.receipt);
  if (run.edge === "unknown")
    return {
      terminal: blocked(
        state,
        "prepare",
        "paper.prepare",
        run.receipt,
      ),
    };
  if (run.edge === "blocked")
    return {
      terminal: result(
        state,
        "blocked",
        "prepare",
        { diagnostics: run.receipt.diagnostics },
        prepareFailure(run.receipt, "unknown"),
      ),
    };
  if (run.edge === "mismatch")
    return {
      terminal: mismatchBlocked(state, "prepare", "paper.prepare"),
    };
  if (run.edge === "needs_input")
    return {
      terminal: result(
        state,
        "needs_input",
        "prepare",
        { question: stageIssue(run.receipt).user_question },
        prepareFailure(run.receipt),
      ),
    };
  if (run.edge === "failed")
    return {
      terminal: result(
        state,
        "analyse_failed",
        "prepare",
        { diagnostics: run.receipt.diagnostics },
        prepareFailure(run.receipt),
      ),
    };
  for (const artifact of run.receipt.artifacts)
    state.artifacts.push({
      ...artifact,
      producer: "paper.prepare",
    });
  return { input: run.receipt.selected_input };
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
      schema: paperAnalyseSchema({
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
      contract: PAPER_ANALYSE_CONTRACT,
      context: { mode, input, output: state.canonical },
    },
  );
  const receipt = analysis.receipt;
  state.operations.push(receipt);
  if (analysis.edge === "unknown" || analysis.edge === "blocked")
    return {
      terminal: blocked(
        state,
        "analyse",
        "paper.analyse",
        receipt,
      ),
    };
  if (analysis.edge === "mismatch")
    return {
      terminal: mismatchBlocked(
        state,
        "analyse",
        "paper.analyse",
      ),
    };
  if (analysis.edge === "reconcile") return { reconcile: true };
  if (analysis.edge !== "ok")
    return {
      terminal: result(
        state,
        "analyse_failed",
        "analyse",
        {
          notes: receipt.failure && receipt.failure.code,
        },
        receipt.failure ||
          operationFailure("paper.analysis_failed", "paper.analyse"),
      ),
    };
  state.artifacts = state.artifacts.filter(
    (artifact) => artifact.role !== "canonical",
  );
  state.artifacts.push({
    role: "canonical",
    path: state.canonical,
    exists: true,
    usable: true,
    producer: "paper.analyse",
  });
  if (mode === "repair") {
    if (receipt.action === "repair") {
      state.repaired = true;
      state.disposition = "repaired";
    } else {
      state.repaired = false;
      state.disposition = "reused";
    }
  } else {
    state.disposition = "created";
  }
  return { action: receipt.action };
}

async function audit(runtime, state, pass) {
  const auditRun = await runtime.operate(
    paperAuditPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit`,
      schema: paperAuditSchema({ target: state.canonical }),
    },
    {
      key: "paper.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "reconciled",
      artifactRoles: ["canonical"],
      contract: PAPER_AUDIT_CONTRACT,
      context: { target: state.canonical },
    },
  );
  const receipt = auditRun.receipt;
  if (auditRun.edge === "unknown") {
    state.operations.push(receipt);
    return {
      terminal: blocked(
        state,
        "audit",
        "paper.audit",
        receipt,
      ),
    };
  }
  if (auditRun.edge === "mismatch") {
    state.operations.push(receipt);
    state.audit = receipt || null;
    return {
      terminal: mismatchBlocked(
        state,
        "audit",
        "paper.audit",
      ),
    };
  }
  const operation = auditOperation(receipt, state.canonical, pass);
  state.operations.push(operation);
  state.audit = receipt;
  if (auditRun.edge !== "ok")
    return {
      terminal: result(
        state,
        "audit_escalated",
        "audit",
        {},
        operation.failure,
      ),
    };
  const escalated = receipt.escalated;
  const clean =
    receipt.status === "clean" &&
    escalated.length === 0 &&
    receipt.remaining_violations === 0;
  return { receipt, escalated, clean };
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
      schema: paperAcquireSchema({
        slug,
        output: state.source,
      }),
    },
    {
      key: "paper.acquire",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["source"],
      contract: PAPER_ACQUIRE_CONTRACT,
      context: { slug, output: state.source },
    },
  );
  if (download.edge === "unknown") {
    state.operations.push(download.receipt);
    return blocked(
      state,
      "download",
      "paper.acquire",
      download.receipt,
    );
  }
  if (download.edge === "mismatch") {
    state.operations.push(download.receipt);
    return mismatchBlocked(
      state,
      "download",
      "paper.acquire",
    );
  }
  const item = download.receipt.per_item[0];
  const downloadReceipt = downloadOperation(item, state.source);
  state.operations.push(downloadReceipt);
  if (download.edge === "blocked")
    return blocked(
      state,
      "download",
      "paper.acquire",
      downloadReceipt,
    );
  if (download.edge !== "ok") {
    return result(
      state,
      "download_failed",
      "download",
      {
        doi: item.doi || meta.doi || null,
        source: item.source || null,
        failure_reason: item.failure_reason || item.verdict_note,
        attempts: item.attempts || [],
      },
      downloadReceipt.failure,
    );
  }
  state.artifacts.push({
    role: "source",
    path: state.source,
    exists: true,
    usable: null,
    producer:
      item.disposition === "reused"
        ? "paper.acquire:reconciled"
        : "paper.acquire",
  });

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
  if (analysisResult.reconcile) {
    state.disposition = "reused";
    state.artifacts = state.artifacts.filter(
      (artifact) => artifact.role !== "canonical",
    );
    state.artifacts.push({
      role: "canonical",
      path: state.canonical,
      exists: true,
      usable: null,
      producer: "paper.analyse:reconciled",
    });
  }

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
