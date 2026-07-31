import {
  TRANSLATION_RECONCILE_CONTRACT,
  TRANSLATION_RECONCILE_SCHEMA,
  TRANSLATION_REOCR_CONTRACT,
  TRANSLATION_REOCR_SCHEMA,
  TRANSLATION_RUN_CONTRACT,
  TRANSLATION_RUN_SCHEMA,
  normalizeLanguage,
  translationReconcilePrompt,
  translationReocrPrompt,
  translationRunPrompt,
  validRequestedSource,
  validSelectableSource,
  validTranslationHash,
} from "../operations/translate.mjs";
import { exactKeys, validText } from "../runtime.mjs";

const RECEIPT_VERSION =
  "quasi.derivative.translation.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

function validRelativePath(value, suffix) {
  if (
    !validText(value, 1, 2048) ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.split("/").includes("..") ||
    !value.toLowerCase().endsWith(suffix)
  )
    return false;
  return (
    value.startsWith("sources/") ||
    value.startsWith("processing/translations/") ||
    value.startsWith(".quasi/")
  );
}

function validateIdentity(slug, rawMeta) {
  if (typeof slug !== "string" || !SLUG.test(slug))
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "translation slug is not canonical ASCII kebab",
    };
  if (
    !rawMeta ||
    typeof rawMeta !== "object" ||
    Array.isArray(rawMeta)
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "translation metadata must be an object",
    };
  const targetLanguage = normalizeLanguage(
    rawMeta.target_language || "zh-CN",
  );
  if (!targetLanguage)
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "target_language is not a bounded language tag",
    };
  let requestedSource =
    rawMeta.source_file === undefined ||
    rawMeta.source_file === null
      ? null
      : rawMeta.source_file;
  if (
    requestedSource !== null &&
    !validRequestedSource(
      requestedSource,
      slug,
      targetLanguage,
    )
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message:
        "source_file must be an exact project-relative PDF path",
    };
  const sourceDecision =
    rawMeta.source_decision === undefined ||
    rawMeta.source_decision === null
      ? null
      : rawMeta.source_decision;
  if (
    sourceDecision !== null &&
    (!exactKeys(sourceDecision, [
      "path",
      "sha256",
      "candidates_fingerprint",
    ]) ||
      !validSelectableSource(
        sourceDecision.path,
        slug,
        targetLanguage,
      ) ||
      !validTranslationHash(sourceDecision.sha256) ||
      !validTranslationHash(
        sourceDecision.candidates_fingerprint,
      ) ||
      (requestedSource !== null &&
        requestedSource !== sourceDecision.path))
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message:
        "source_decision must be exact closed source evidence",
    };
  if (sourceDecision !== null)
    requestedSource = sourceDecision.path;
  const tocJson =
    rawMeta.toc_json === undefined ||
    rawMeta.toc_json === null
      ? null
      : rawMeta.toc_json;
  if (
    tocJson !== null &&
    !validRelativePath(tocJson, ".json")
  )
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "toc_json must be an exact project-relative JSON path",
    };
  const tocPageSide =
    rawMeta.toc_page_side === undefined
      ? "original"
      : rawMeta.toc_page_side;
  if (!["original", "translated"].includes(tocPageSide))
    return {
      ok: false,
      code: "translation.identity_invalid",
      message: "toc_page_side must be original or translated",
    };
  const meta = {
    requestedSource,
    sourceDecision:
      sourceDecision === null
        ? null
        : {
            path: sourceDecision.path,
            sha256: sourceDecision.sha256,
            candidates_fingerprint:
              sourceDecision.candidates_fingerprint,
          },
    targetLanguage,
    tocJson,
    tocPageSide,
  };
  return {
    ok: true,
    meta,
    fingerprint: JSON.stringify(meta),
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
  const langTag = meta.targetLanguage.toLowerCase();
  return {
    slug,
    translationKey: `translation:paper:${slug}:${meta.targetLanguage}`,
    targetLanguage: meta.targetLanguage,
    requestedSource: meta.requestedSource,
    sourceDecision: meta.sourceDecision,
    sourcePath: null,
    activeInput: null,
    tocJson: meta.tocJson,
    tocPageSide: meta.tocPageSide,
    output: `processing/translations/${slug}-${langTag}.pdf`,
    manifest: `processing/translations/${slug}-${langTag}.manifest.json`,
    recoverySource:
      `processing/translations/${slug}-${langTag}-reocr.pdf`,
    backend: null,
    requestFingerprint: null,
    sourceSha256: null,
    sourceSize: 0,
    sourcePages: 0,
    activeInputSha256: null,
    artifacts: [],
    operations: [],
    validation: null,
    gate: null,
    failure: null,
    disposition: null,
    recovered: false,
    pendingReocr: null,
    expectedGeneration: null,
    budgets: {
      reocr: { limit: 1, used: 0 },
      translation_runs: { limit: 2, used: 0 },
    },
  };
}

function artifact(
  role,
  path,
  producer,
  sha256,
  size,
  pages,
) {
  return {
    role,
    path,
    producer,
    sha256,
    size,
    pages,
  };
}

function setSourceArtifact(state) {
  state.artifacts = state.artifacts.filter(
    (row) => row.role !== "source",
  );
  state.artifacts.push(
    artifact(
      "source",
      state.sourcePath,
      "translation.reconcile",
      state.sourceSha256,
      state.sourceSize,
      state.sourcePages,
    ),
  );
}

function setFinalArtifacts(state, receipt, producer) {
  state.artifacts = state.artifacts.filter(
    (row) =>
      row.role !== "translated_pdf" &&
      row.role !== "translation_manifest",
  );
  state.artifacts.push(
    artifact(
      "translated_pdf",
      state.output,
      producer,
      receipt.output_sha256,
      receipt.output_size,
      receipt.output_pages,
    ),
    artifact(
      "translation_manifest",
      state.manifest,
      producer,
      receipt.manifest_sha256,
      null,
      null,
    ),
  );
}

function receipt(state, status, stage, failure = null) {
  return {
    schema_version: RECEIPT_VERSION,
    derivative_key: state.translationKey,
    kind: "translate",
    id: state.slug,
    slug: state.slug,
    target_language: state.targetLanguage,
    backend: state.backend,
    status,
    disposition:
      status === "complete" ? state.disposition : null,
    stage,
    source:
      state.sourcePath === null
        ? null
        : {
            path: state.sourcePath,
            sha256: state.sourceSha256,
            size: state.sourceSize,
            pages: state.sourcePages,
          },
    artifacts: state.artifacts,
    operations: state.operations,
    validation: state.validation,
    budgets: state.budgets,
    gate: state.gate,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "translation.reconcile" }
        : null,
  };
}

function legacyStatus(status, gate) {
  if (status === "complete") return "success";
  if (status === "failed") return "error";
  if (gate && gate.kind === "configuration_required")
    return "needs_auth";
  if (gate && gate.kind === "source_selection")
    return "needs_source_selection";
  return "blocked";
}

function terminal(state, status, stage, failure = null) {
  const translationReceipt = receipt(
    state,
    status,
    stage,
    failure,
  );
  return {
    slug: state.slug,
    status: legacyStatus(status, state.gate),
    translation_status: legacyStatus(status, state.gate),
    final_pdf:
      status === "complete" ? state.output : null,
    toc_entries:
      status === "complete" &&
      state.validation
        ? state.validation.toc_entries
        : null,
    translation_receipt: translationReceipt,
  };
}

function rejectedResult(slug, validation, conflict = false) {
  const canonical =
    typeof slug === "string" && SLUG.test(slug);
  const state = createState(
    canonical ? slug : "invalid",
    {
      requestedSource: null,
      sourceDecision: null,
      targetLanguage: "zh-CN",
      tocJson: null,
      tocPageSide: "original",
    },
  );
  if (!canonical) {
    state.slug =
      typeof slug === "string" ? slug : null;
    state.translationKey = null;
  }
  const failure = operationFailure(
    conflict
      ? "translation.identity_conflict"
      : validation.code,
    "translation.identity",
    "known",
    validation.message,
  );
  const result = terminal(
    state,
    conflict ? "blocked" : "failed",
    "identity",
    failure,
  );
  if (conflict)
    result.translation_receipt.resume = null;
  return result;
}

function writerMismatch(state, stage, operationKey) {
  return terminal(
    state,
    "blocked",
    stage,
    operationFailure(
      "translation.writer_receipt_mismatch",
      operationKey,
      "unknown",
      "writer receipt did not prove the exact translation contract",
    ),
  );
}

function reconcileMismatch(state, mode) {
  return terminal(
    state,
    "blocked",
    mode === "initial" ? "reconcile" : "validation",
    operationFailure(
      "translation.reconcile_receipt_invalid",
      "translation.reconcile",
      "unknown",
      "reconcile receipt did not prove the exact generation",
    ),
  );
}

function adoptReconcile(state, receipt) {
  if (state.sourcePath === null) {
    state.sourcePath = receipt.source_path;
    state.sourceSha256 = receipt.source_sha256;
    state.sourceSize = receipt.source_size;
    state.sourcePages = receipt.source_pages;
    setSourceArtifact(state);
  }
  state.backend = receipt.backend;
  state.requestFingerprint = receipt.request_fingerprint;
  state.activeInput = receipt.source_path;
  state.activeInputSha256 = receipt.source_sha256;
}

function adoptValidation(state, receipt, producer) {
  state.validation = {
    status: "clean",
    backend: receipt.backend,
    input_path: receipt.source_path,
    input_sha256: receipt.source_sha256,
    output_path: state.output,
    output_sha256: receipt.output_sha256,
    manifest_path: state.manifest,
    manifest_sha256: receipt.manifest_sha256,
    source_pages: receipt.source_pages,
    output_pages: receipt.output_pages,
    toc_entries: receipt.toc_entries,
    coverage: receipt.coverage,
  };
  setFinalArtifacts(state, receipt, producer);
}

function reocrEnvelope(
  state,
  raw,
  status,
  sha256,
  failure,
) {
  return {
    schema_version:
      "quasi.operation.translation.reocr.receipt/0.1",
    key: "translation.reocr",
    effect: "writer",
    status,
    attempt: 1,
    derivative_key: state.translationKey,
    input_path: state.sourcePath,
    output_path: state.recoverySource,
    artifact_roles: ["recovery_source"],
    exit: Number.isInteger(raw?.exit) ? raw.exit : null,
    exists:
      typeof raw?.exists === "boolean"
        ? raw.exists
        : false,
    size:
      Number.isInteger(raw?.size) && raw.size >= 0
        ? raw.size
        : 0,
    sha256,
    action: status === "succeeded" ? "created" : null,
    failure,
  };
}

function recordPendingReocr(state, reconcileReceipt) {
  if (!state.pendingReocr) return;
  const raw = state.pendingReocr;
  state.operations.push(
    reocrEnvelope(
      state,
      raw,
      "succeeded",
      reconcileReceipt.source_sha256,
      null,
    ),
  );
  state.artifacts.push(
    artifact(
      "recovery_source",
      state.recoverySource,
      "translation.reocr:reconciled",
      reconcileReceipt.source_sha256,
      reconcileReceipt.source_size,
      reconcileReceipt.source_pages,
    ),
  );
  state.pendingReocr = null;
}

async function reconcile(runtime, state, mode) {
  const observed = await runtime.operate(
    translationReconcilePrompt(state, mode),
    {
      phase:
        mode === "initial"
          ? "Recall"
          : mode === "final"
            ? "Audit"
            : "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:reconcile-${mode}`,
      schema: TRANSLATION_RECONCILE_SCHEMA,
    },
    {
      key: "translation.reconcile",
      effect: "readonly",
      retry: "safe",
      replay: "idempotent",
      artifactRoles: [],
      unknownFailureCode:
        "translation.reconcile_outcome_unknown",
      contract: TRANSLATION_RECONCILE_CONTRACT,
      context: { state, mode },
    },
  );
  const observeReceipt = observed.receipt;
  const pendingRecovery =
    mode === "recovery" && state.pendingReocr !== null;
  if (
    observed.edge === "unknown" ||
    observed.edge === "mismatch"
  ) {
    if (pendingRecovery) {
      state.operations.push(
        reocrEnvelope(
          state,
          state.pendingReocr,
          "blocked",
          null,
          operationFailure(
            "translation.recovery_reconcile_failed",
            "translation.reocr",
            "unknown",
            "layout OCR output could not be reconciled",
          ),
        ),
      );
      state.pendingReocr = null;
    }
    state.operations.push(observeReceipt);
    return { terminal: reconcileMismatch(state, mode) };
  }
  if (pendingRecovery)
    recordPendingReocr(state, observeReceipt);
  state.operations.push(observeReceipt);
  if (observed.edge === "blocked") {
    state.backend = observeReceipt.backend;
    state.gate = observeReceipt.gate;
    return {
      terminal: terminal(
        state,
        "blocked",
        "reconcile",
        observeReceipt.failure,
      ),
    };
  }
  if (observed.edge !== "ok")
    return {
      terminal: terminal(
        state,
        "failed",
        "reconcile",
        observeReceipt.failure,
      ),
    };
  adoptReconcile(state, observeReceipt);
  if (observeReceipt.signal === "reused") {
    adoptValidation(
      state,
      observeReceipt,
      mode === "initial"
        ? "translation.reconcile:reused"
        : "translation.run",
    );
    return { reused: true };
  }
  return { missing: true };
}

async function runTranslation(runtime, state, inputPath, attempt) {
  state.budgets.translation_runs.used += 1;
  const run = await runtime.operate(
    translationRunPrompt(state, inputPath, attempt),
    {
      phase: "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:translate-${attempt}`,
      schema: TRANSLATION_RUN_SCHEMA,
    },
    {
      key: "translation.run",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "translated_pdf",
        "translation_manifest",
      ],
      unknownFailureCode:
        "translation.writer_outcome_unknown",
      contract: TRANSLATION_RUN_CONTRACT,
      context: { state, inputPath, attempt },
    },
  );
  const runReceipt = run.receipt;
  state.operations.push(runReceipt);
  if (run.edge === "unknown")
    return {
      terminal: terminal(
        state,
        "blocked",
        "translate",
        operationFailure(
          "translation.writer_outcome_unknown",
          "translation.run",
          "unknown",
          "translation writer outcome is unknown",
        ),
      ),
    };
  if (run.edge === "mismatch")
    return {
      terminal: writerMismatch(
        state,
        "translate",
        "translation.run",
      ),
    };
  if (run.edge === "blocked") {
    if (runReceipt.gate) state.gate = runReceipt.gate;
    return {
      terminal: terminal(
        state,
        "blocked",
        "translate",
        runReceipt.failure,
      ),
    };
  }
  if (run.edge !== "ok")
    return {
      underTranslated:
        runReceipt.failure.code ===
        "translation.under_translated",
      terminal:
        runReceipt.failure.code ===
        "translation.under_translated"
          ? null
          : terminal(
              state,
              "failed",
              "translate",
              runReceipt.failure,
            ),
      receipt: runReceipt,
    };
  state.disposition =
    runReceipt.disposition === "reconciled"
      ? "reused"
      : "created";
  state.expectedGeneration = {
    attempt,
    outputSha256: runReceipt.output_sha256,
    manifestSha256: runReceipt.manifest_sha256,
    outputSize: runReceipt.output_size,
    sourcePages: runReceipt.source_pages,
    outputPages: runReceipt.output_pages,
    tocEntries: runReceipt.toc_entries,
    coverage: runReceipt.coverage,
  };
  return { succeeded: true, receipt: runReceipt };
}

async function reocr(runtime, state) {
  state.budgets.reocr.used = 1;
  const recovered = await runtime.operate(
    translationReocrPrompt(state),
    {
      phase: "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:reocr`,
      schema: TRANSLATION_REOCR_SCHEMA,
    },
    {
      key: "translation.reocr",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["recovery_source"],
      unknownFailureCode:
        "translation.writer_outcome_unknown",
      contract: TRANSLATION_REOCR_CONTRACT,
      context: { state },
    },
  );
  const rawReceipt = recovered.receipt;
  if (recovered.edge === "unknown") {
    state.operations.push(rawReceipt);
    return {
      terminal: terminal(
        state,
        "blocked",
        "reocr",
        operationFailure(
          "translation.writer_outcome_unknown",
          "translation.reocr",
          "unknown",
          "layout OCR writer outcome is unknown",
        ),
      ),
    };
  }
  if (recovered.edge === "mismatch") {
    state.operations.push(
      reocrEnvelope(
        state,
        rawReceipt,
        "blocked",
        null,
        operationFailure(
          "translation.writer_receipt_mismatch",
          "translation.reocr",
          "unknown",
          "raw layout OCR receipt did not prove the exact output",
        ),
      ),
    );
    return {
      terminal: writerMismatch(
        state,
        "reocr",
        "translation.reocr",
      ),
    };
  }
  if (recovered.edge === "blocked") {
    const failure = operationFailure(
      "translation.recovery_source_exists",
      "translation.reocr",
      "unknown",
      "existing recovery source has no provenance for this request",
    );
    state.operations.push(
      reocrEnvelope(
        state,
        rawReceipt,
        "blocked",
        null,
        failure,
      ),
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "reocr",
        failure,
      ),
    };
  }
  if (recovered.edge !== "ok") {
    const failure = operationFailure(
      "translation.reocr_failed",
      "translation.reocr",
      "known",
      `${rawReceipt.failure.code}: ${rawReceipt.failure.message}`,
    );
    state.operations.push(
      reocrEnvelope(
        state,
        rawReceipt,
        "failed",
        null,
        failure,
      ),
    );
    return {
      terminal: terminal(
        state,
        "failed",
        "reocr",
        failure,
      ),
    };
  }
  state.activeInput = state.recoverySource;
  state.activeInputSha256 = null;
  state.recovered = true;
  state.pendingReocr = rawReceipt;
  return { succeeded: true };
}

async function processStrict(runtime, state) {
  runtime.phase("Recall");
  const observed = await reconcile(runtime, state, "initial");
  if (observed.terminal) return observed.terminal;
  if (observed.reused) {
    state.disposition = "reused";
    return terminal(state, "complete", "validation");
  }

  let translated = await runTranslation(
    runtime,
    state,
    state.sourcePath,
    1,
  );
  if (translated.terminal) return translated.terminal;
  if (translated.underTranslated) {
    const recovered = await reocr(runtime, state);
    if (recovered.terminal) return recovered.terminal;
    const recoveryObserved = await reconcile(
      runtime,
      state,
      "recovery",
    );
    if (recoveryObserved.terminal)
      return recoveryObserved.terminal;
    if (!recoveryObserved.missing)
      return reconcileMismatch(state, "recovery");
    translated = await runTranslation(
      runtime,
      state,
      state.recoverySource,
      2,
    );
    if (translated.terminal) return translated.terminal;
    if (translated.underTranslated)
      return terminal(
        state,
        "failed",
        "translate",
        operationFailure(
          "translation.recovery_exhausted",
          "translation.run",
          "known",
          "translation remained under-translated after one layout OCR recovery",
        ),
      );
  }

  const verified = await reconcile(runtime, state, "final");
  if (verified.terminal) return verified.terminal;
  if (!verified.reused)
    return reconcileMismatch(state, "final");
  state.disposition = state.recovered
    ? "recovered"
    : state.disposition || "created";
  return terminal(state, "complete", "validation");
}

export function translationDependencyFailure(
  slug,
  rawMeta,
  code,
  message,
) {
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  const state = createState(slug, validation.meta);
  return terminal(
    state,
    "failed",
    "dependency",
    operationFailure(
      code,
      "translation.dependency",
      "known",
      message,
    ),
  );
}

export async function processTranslation(
  runtime,
  slug,
  rawMeta,
) {
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  return runtime.coalesce(
    `translation:paper:${slug}:${validation.meta.targetLanguage}`,
    validation.fingerprint,
    () =>
      processStrict(
        runtime,
        createState(slug, validation.meta),
      ),
    () =>
      rejectedResult(
        slug,
        {
          code: "translation.identity_conflict",
          message:
            "conflicting translation source, language, or TOC for one derivative key",
        },
        true,
      ),
  );
}
