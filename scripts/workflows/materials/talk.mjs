import {
  TALK_ANALYSE_CONTRACT,
  talkAnalyseOperationPrompt,
  talkAnalyseSchema,
} from "../operations/analyse.mjs";
import {
  TALK_AUDIT_CONTRACT,
  talkAuditLegacyPrompt,
  talkAuditSchema,
} from "../operations/audit.mjs";
import {
  TALK_PREPARE_STAGE_CONTRACT,
  TALK_RENDER_SILENT_CONTRACT,
  talkRenderSilentPrompt,
  talkRenderSilentSchema,
  talkPrepareStagePrompt,
  talkPrepareStageSchema,
} from "../operations/transcribe.mjs";
import { validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";

const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.1";
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

async function prepareTalk(runtime, state) {
  const context = {
    prepared: state.prepared,
    transcript: state.transcript,
    subtitle: state.subtitle,
    processingDir: state.processingDir,
    engines: state.engines,
  };
  const schema = talkPrepareStageSchema({
    materialKey: state.materialKey,
    slug: state.slug,
    media: state.media,
    processingDir: state.processingDir,
    manifest: state.manifest,
    prepared: state.prepared,
    transcript: state.transcript,
    subtitle: state.subtitle,
    canonical: state.canonical,
  });
  const run = await runtime.operate(
    talkPrepareStagePrompt(state),
    {
      phase: "Prepare",
      agentType: "quasi:transcribe-agent",
      label: `${state.slug}:prepare`,
      schema,
    },
    {
      key: "talk.prepare",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: [
        "prepared_media",
        "transcript",
        "subtitle",
        "engine_transcript",
      ],
      unknownFailureCode: "talk.writer_outcome_unknown",
      contract: TALK_PREPARE_STAGE_CONTRACT,
      context,
    },
  );
  state.operations.push(run.receipt);
  if (run.edge === "unknown" || run.edge === "blocked")
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "prepare",
        prepareFailure(run.receipt, "unknown"),
      ),
    };
  if (run.edge === "mismatch")
    return {
      terminal: writerMismatch(state, "prepare", "talk.prepare"),
    };
  if (run.edge === "needs_input")
    return {
      terminal: terminal(
        state,
        "needs_input",
        "needs_input",
        "prepare",
        prepareFailure(run.receipt),
        { question: stageIssue(run.receipt).user_question },
      ),
    };
  if (run.edge === "failed")
    return {
      terminal: terminal(
        state,
        "transcribe_failed",
        "failed",
        "prepare",
        prepareFailure(run.receipt),
        { diagnostics: run.receipt.diagnostics },
      ),
    };
  const receipt = run.receipt;
  state.sourceSha256 = receipt.source_sha256;
  state.requestFingerprint = receipt.request_fingerprint;
  state.outputExists = receipt.canonical_exists;
  state.transcriptReplaced = receipt.transcript_changed;
  state.classification = receipt.classification;
  state.transcriptArtifacts = receipt.artifacts.filter((row) =>
    ["transcript", "subtitle", "engine_transcript"].includes(row.role),
  );
  addGeneratedArtifacts(state, receipt.artifacts, "talk.prepare");
  if (state.outputExists) {
    state.artifacts = state.artifacts.filter(
      (item) => item.path !== state.canonical,
    );
    state.artifacts.push(
      artifact(
        "canonical",
        state.canonical,
        "talk.prepare:observed",
        receipt.canonical_sha256,
      ),
    );
    state.disposition = "reused";
  }
  if (state.transcriptReplaced && state.outputExists) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return { receipt };
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
    const analysis = await runtime.operate(
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
        schema: talkAnalyseSchema({
          inputs,
          mode,
          output: state.canonical,
        }),
      },
      {
        key: "talk.analyse",
        effect: "writer",
        retry: "forbidden",
        replay: "blocked",
        artifactRoles: ["canonical"],
        unknownFailureCode: "talk.writer_outcome_unknown",
        contract: TALK_ANALYSE_CONTRACT,
        context: { inputs, mode, output: state.canonical },
      },
    );
    const receipt = analysis.receipt;
    state.operations.push(receipt);
    if (
      analysis.edge === "unknown" ||
      analysis.edge === "mismatch"
    )
      return {
        terminal: writerMismatch(
          state,
          "analyse",
          "talk.analyse",
        ),
      };
    if (analysis.edge === "blocked")
      return {
        terminal: terminal(
          state,
          "blocked",
          "blocked",
          "analyse",
          receipt.failure,
        ),
      };
    if (analysis.edge !== "ok")
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

  const rendered = await runtime.operate(
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
      schema: talkRenderSilentSchema({
        materialKey: state.materialKey,
        input: state.transcript,
        output: state.canonical,
        signal: state.classification,
        mode,
      }),
    },
    {
      key: "talk.render-silent",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "talk.writer_outcome_unknown",
      contract: TALK_RENDER_SILENT_CONTRACT,
      context: { state, mode },
    },
  );
  const receipt = rendered.receipt;
  state.operations.push(receipt);
  if (
    rendered.edge === "unknown" ||
    rendered.edge === "mismatch"
  )
    return {
      terminal: writerMismatch(
        state,
        "render-silent",
        "talk.render-silent",
      ),
    };
  if (rendered.edge === "blocked")
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "render-silent",
        receipt.failure,
      ),
    };
  if (rendered.edge !== "ok")
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
  const auditRun = await runtime.operate(
    talkAuditLegacyPrompt(state.slug, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label:
        pass === 1
          ? `${state.slug}:audit`
          : `${state.slug}:audit-${pass}`,
      schema: talkAuditSchema({ target: state.canonical }),
    },
    {
      key: "talk.audit.legacy",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "talk.writer_outcome_unknown",
      contract: TALK_AUDIT_CONTRACT,
      context: { target: state.canonical },
    },
  );
  const receipt = auditRun.receipt;
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (
    auditRun.edge === "unknown" ||
    auditRun.edge === "mismatch"
  )
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
  if (auditRun.edge !== "ok")
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
  runtime.phase("Prepare");
  const prepared = await prepareTalk(runtime, state);
  if (prepared.terminal) return prepared.terminal;
  state.talkProducer =
    state.classification === "live"
      ? "talk.analyse"
      : "talk.render-silent";

  runtime.phase("Analyse");
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

  runtime.phase("Audit");
  let audited = await runAudit(runtime, state, 1);
  if (audited.terminal) return audited.terminal;
  if (!audited.clean) {
    state.budgets.repair.used = 1;
    runtime.phase("Analyse");
    const repaired = await runProducer(
      runtime,
      state,
      "repair",
      audited.diagnostics,
    );
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
