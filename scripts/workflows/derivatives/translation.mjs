import {
  TRANSLATION_PREPARE_STAGE_CONTRACT,
  normalizeLanguage,
  translationPrepareStagePrompt,
  translationPrepareStageSchema,
  validRequestedSource,
  validSelectableSource,
  validTranslationHash,
} from "../operations/translate.mjs";
import { exactKeys, validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import { routeStageEdge } from "../materials/route.mjs";

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
    tocJson: meta.tocJson,
    tocPageSide: meta.tocPageSide,
    output: `processing/translations/${slug}-${langTag}.pdf`,
    manifest: `processing/translations/${slug}-${langTag}.manifest.json`,
    recoverySource:
      `processing/translations/${slug}-${langTag}-reocr.pdf`,
    backend: null,
    sourceSha256: null,
    sourceSize: 0,
    sourcePages: 0,
    artifacts: [],
    operations: [],
    validation: null,
    gate: null,
    failure: null,
    disposition: null,
    recovered: false,
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
      "translation.prepare",
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
    gate: state.gate,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "translation.reconcile" }
        : status === "needs_input"
          ? { operation_key: "translation.user-gate", stage }
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

function prepareFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "translation.prepare_failed",
    "translation.prepare",
    outcome,
    (issue && issue.summary) || "Translation Prepare did not complete",
  );
}

function routeTranslationStage(run, state, options) {
  return routeStageEdge(run, {
    ...options,
    state,
    stage: "prepare",
    operationKey: "translation.prepare",
    emit: ({ status, failure }) =>
      terminal(state, status, "prepare", failure),
    unknown: (receipt) =>
      terminal(
        state,
        "blocked",
        "prepare",
        prepareFailure(receipt, "unknown"),
      ),
    mismatch: () =>
      writerMismatch(state, "prepare", "translation.prepare"),
  });
}

async function processStrict(runtime, state) {
  runtime.phase("Prepare");
  const schema = translationPrepareStageSchema({
    derivativeKey: state.translationKey,
    slug: state.slug,
    targetLanguage: state.targetLanguage,
    output: state.output,
    manifest: state.manifest,
  });
  const run = await runtime.operate(
    translationPrepareStagePrompt(state),
    {
      phase: "Prepare",
      agentType: "quasi:translate-agent",
      label: `${state.slug}:prepare`,
      schema,
    },
    {
      key: "translation.prepare",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "source",
        "recovery_source",
        "translated_pdf",
        "translation_manifest",
      ],
      unknownFailureCode: "translation.writer_outcome_unknown",
      contract: TRANSLATION_PREPARE_STAGE_CONTRACT,
      context: {
        slug: state.slug,
        targetLanguage: state.targetLanguage,
        requestedSource: state.requestedSource,
        output: state.output,
        manifest: state.manifest,
        recoverySource: state.recoverySource,
      },
    },
  );
  const routed = routeTranslationStage(run, state, {
    failure: prepareFailure,
    needsInputGate: (receipt) => receipt.gate,
    assignGate: (gate) => {
      state.gate = gate;
    },
    failedStatus: "failed",
    onOk: (stageReceipt) => {
      state.backend = stageReceipt.backend;
      state.sourcePath = stageReceipt.source.path;
      state.sourceSha256 = stageReceipt.source.sha256;
      state.sourceSize = stageReceipt.source.size;
      state.sourcePages = stageReceipt.source.pages;
      state.disposition = stageReceipt.disposition;
      state.recovered = stageReceipt.recovered;
      setSourceArtifact(state);
      state.validation = {
        status: "clean",
        backend: stageReceipt.backend,
        input_path: stageReceipt.source.path,
        input_sha256: stageReceipt.source.sha256,
        output_path: state.output,
        output_sha256: stageReceipt.validation.output_sha256,
        manifest_path: state.manifest,
        manifest_sha256: stageReceipt.validation.manifest_sha256,
        source_pages: stageReceipt.validation.source_pages,
        output_pages: stageReceipt.validation.output_pages,
        toc_entries: stageReceipt.validation.toc_entries,
        coverage: stageReceipt.validation.coverage,
      };
      setFinalArtifacts(
        state,
        {
          ...stageReceipt.validation,
          output_path: state.output,
          manifest_path: state.manifest,
        },
        "translation.prepare",
      );
      return {
        terminal: terminal(state, "complete", "validation"),
      };
    },
  });
  return routed.terminal || routed.value;
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
