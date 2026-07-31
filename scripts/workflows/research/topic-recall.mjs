import {
  TOPIC_DISCOVER_BOOK_CONTRACT,
  TOPIC_DISCOVER_BOOK_SCHEMA,
  TOPIC_DISCOVER_PAPER_CONTRACT,
  TOPIC_DISCOVER_PAPER_SCHEMA,
  TOPIC_RECALL_CONTRACT,
  TOPIC_RECALL_SCHEMA,
  TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
  TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
  topicDiscoverBookOperationPrompt,
  topicDiscoverPaperOperationPrompt,
  topicMemberPath,
  topicRecallOperationPrompt as topicRecallPrompt,
  topicResolveMembershipOperationPrompt as topicResolveMembershipPrompt,
} from "../operations/acquire.mjs";
import {
  TOPIC_AUDIT_CONTRACT,
  topicAuditLegacyPrompt,
  topicAuditSchema,
} from "../operations/audit.mjs";
import {
  TOPIC_OVERVIEW_SYNTHESISE_CONTRACT,
  TOPIC_RESOURCES_SYNTHESISE_CONTRACT,
  topicOverviewSynthesiseOperationPrompt as topicOverviewSynthesisePrompt,
  topicOverviewSynthesiseSchema,
  topicResourcesSynthesiseOperationPrompt as topicResourcesSynthesisePrompt,
  topicResourcesSynthesiseSchema,
} from "../operations/synthesise.mjs";
import {
  TOPIC_STEER_CONTRACT,
  TOPIC_STEER_SCHEMA as TOPIC_STEER_OPERATION_SCHEMA,
  topicSteerOperationPrompt,
} from "../operations/steer.mjs";
import { exactKeys, validText } from "../runtime.mjs";

const RESEARCH_RECEIPT_VERSION =
  "quasi.research.topic.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

const sameStrings = (left, right) =>
  Array.isArray(left) &&
  Array.isArray(right) &&
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

const operationFailure = (
  code,
  operationKey,
  outcome,
  message,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable: false,
  message,
});

function validateIdentity(slug, meta) {
  if (typeof slug !== "string" || !SLUG.test(slug))
    return {
      ok: false,
      code: "topic.slug_invalid",
      message: "topic slug is not canonical",
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "topic.identity_invalid",
      message: "topic metadata must be an object",
    };
  const desc = meta.desc || meta.topic_desc || slug;
  if (!validText(desc, 1, 1000))
    return {
      ok: false,
      code: "topic.identity_invalid",
      message: "topic description is missing or invalid",
    };
  if (![0, 1].includes(meta.maxRounds))
    return {
      ok: false,
      code: "topic.mode_invalid",
      message:
        "strict Topic mode requires maxRounds=0 (recall-only) or maxRounds=1 (one material round)",
    };
  const maxItems =
    meta.maxPerRound === undefined ? 8 : meta.maxPerRound;
  const minItems =
    meta.minItems === undefined ? 1 : meta.minItems;
  const maxCards =
    meta.maxCardsPerRound === undefined
      ? 0
      : meta.maxCardsPerRound;
  if (
    !Number.isInteger(maxItems) ||
    maxItems < 1 ||
    maxItems > 16 ||
    !Number.isInteger(minItems) ||
    minItems < 1 ||
    minItems > 16 ||
    maxCards !== 0
  )
    return {
      ok: false,
      code: "topic.budget_invalid",
      message:
        "strict Topic budgets require maxPerRound/minItems 1..16 and maxCardsPerRound=0",
    };
  if (
    meta.final !== undefined &&
    typeof meta.final !== "boolean"
  )
    return {
      ok: false,
      code: "topic.identity_invalid",
      message: "final must be boolean",
    };
  const seeds = meta.seeds === undefined ? [] : meta.seeds;
  if (
    !Array.isArray(seeds) ||
    seeds.length > 16 ||
    seeds.some((seed) => !validText(seed, 1, 500))
  )
    return {
      ok: false,
      code: "topic.identity_invalid",
      message: "seeds must be a bounded string array",
    };
  const normalized = {
    desc,
    strict: meta.strict === true,
    maxRounds: meta.maxRounds,
    maxItems,
    minItems,
    final: meta.final === true,
    seeds,
  };
  return {
    ok: true,
    meta: normalized,
    fingerprint: JSON.stringify(normalized),
  };
}

function createState(slug, meta) {
  const root = `vault/topics/${slug}`;
  return {
    slug,
    researchKey: `topic:${slug}`,
    desc: meta.desc,
    strict: meta.strict,
    maxRounds: meta.maxRounds,
    maxItems: meta.maxItems,
    minItems: meta.minItems,
    final: meta.final,
    seeds: meta.seeds,
    paths: {
      overview: `${root}/00-overview.md`,
      resources: `${root}/01-resources.md`,
      outline: `${root}/02-outline.md`,
    },
    operations: [],
    audit: [],
    members: [],
    materialResults: [],
    discoveryFailures: [],
    recallFailed: false,
    recalled: 0,
    rounds: 0,
    artifacts: [],
    subquestions: [],
    repaired: false,
    disposition: null,
    signal: null,
    suggestedQueries: null,
    warnings: [
      meta.maxRounds === 0
        ? "strict recall-only Topic does not dispatch new materials, web cards, or dossiers"
        : "strict one-round Topic dispatches only discovered Book/Paper materials; web cards and dossiers remain disabled",
      "topic audit remains an explicitly named legacy composite",
    ],
    budgets: {
      recall: { used: 0, limit: meta.maxItems },
      discovery: {
        used: 0,
        limit: meta.maxRounds === 1 ? meta.maxItems : 0,
      },
      materials: {
        used: 0,
        limit: meta.maxRounds === 1 ? meta.maxItems : 0,
      },
      steer: { used: 0, limit: 3 },
      synthesis: { used: 0, limit: 4 },
      repairRounds: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 6 },
    },
  };
}

function researchReceipt(
  state,
  status,
  stage,
  failure = null,
) {
  return {
    schema_version: RESEARCH_RECEIPT_VERSION,
    research_key: state.researchKey,
    kind: "topic",
    id: state.slug,
    status,
    disposition:
      ["complete", "partial"].includes(status)
        ? state.repaired
          ? "repaired"
          : state.disposition || "created"
        : null,
    stage,
    members: state.members.map((member) => ({
      member_key: `${member.kind}:${member.slug}`,
      kind: member.kind,
      id: member.slug,
      path: member.path,
    })),
    material_results: state.materialResults,
    discovery_failures: state.discoveryFailures,
    artifacts: state.artifacts,
    operations: state.operations,
    audit: state.audit,
    budgets: state.budgets,
    subquestions: state.subquestions,
    warnings: state.warnings,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "topic.reconcile" }
        : null,
  };
}

function terminal(
  state,
  legacyStatus,
  researchStatus,
  stage,
  failure = null,
  extra = {},
) {
  const books = state.members
    .filter((member) => member.kind === "book")
    .map((member) => member.slug);
  return {
    slug: state.slug,
    status: legacyStatus,
    members: state.members,
    items: state.members.length,
    cards: 0,
    recalled: state.recalled,
    rounds: state.rounds,
    overview: state.paths.overview,
    resources: state.paths.resources,
    outline: state.paths.outline,
    saturated: state.signal === "saturated",
    subquestions: state.subquestions.map((subquestion) => ({
      id: subquestion.id,
      coverage: subquestion.coverage,
      dossier: false,
    })),
    dossiers_failed: [],
    book_slugs: books,
    failures:
      state.materialResults.filter(
        (member) => member.status !== "complete",
      ).length +
      state.discoveryFailures.length +
      (failure ? 1 : 0),
    dead_end: true,
    ...extra,
    research_receipt: researchReceipt(
      state,
      researchStatus,
      stage,
      failure,
    ),
  };
}

function rejectedResult(slug, validation, conflict = false) {
  const canonical =
    typeof slug === "string" && SLUG.test(slug);
  const state = createState(canonical ? slug : "", {
    desc: canonical ? slug : "",
    strict: false,
    maxItems: 0,
    maxRounds: 0,
    minItems: 1,
    final: false,
    seeds: [],
  });
  return terminal(
    state,
    "blocked",
    "blocked",
    "identity",
    operationFailure(
      conflict
        ? "topic.identity_conflict"
        : validation.code,
      "topic.identity",
      "known",
      validation.message,
    ),
  );
}

function validMaterialFailure(failure) {
  return !!(
    failure &&
    typeof failure === "object" &&
    !Array.isArray(failure) &&
    [4, 5].includes(Object.keys(failure).length) &&
    ["code", "operation_key", "outcome", "retryable"].every(
      (key) =>
        Object.prototype.hasOwnProperty.call(failure, key),
    ) &&
    Object.keys(failure).every((key) =>
      [
        "code",
        "operation_key",
        "outcome",
        "retryable",
        "message",
      ].includes(key),
    ) &&
    validText(failure.code, 1, 200) &&
    validText(failure.operation_key, 1, 200) &&
    ["known", "unknown"].includes(failure.outcome) &&
    typeof failure.retryable === "boolean" &&
    (failure.message === undefined ||
      failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

function validMaterialArtifact(artifact) {
  return !!(
    exactKeys(artifact, [
      "role",
      "path",
      "exists",
      "usable",
      "producer",
    ]) &&
    validText(artifact.role, 1, 100) &&
    validText(artifact.path, 1, 1000) &&
    artifact.exists === true &&
    [null, true, false].includes(artifact.usable) &&
    validText(artifact.producer, 1, 200)
  );
}

function cleanChildAudit(receipt, demand) {
  const target = topicMemberPath(demand.kind, demand.id);
  if (demand.kind === "paper")
    return !!(
      exactKeys(receipt.audit, [
        "schema_version",
        "key",
        "effect",
        "status",
        "attempt",
        "target_path",
        "remaining_violations",
        "escalated",
      ]) &&
      receipt.audit.schema_version ===
        "quasi.operation.paper.audit.agent-receipt/0.1" &&
      receipt.audit.key === "paper.audit" &&
      receipt.audit.effect === "writer" &&
      receipt.audit.status === "clean" &&
      receipt.audit.attempt === 1 &&
      receipt.audit.target_path === target &&
      receipt.audit.remaining_violations === 0 &&
      Array.isArray(receipt.audit.escalated) &&
      receipt.audit.escalated.length === 0
    );
  if (!Array.isArray(receipt.audit) || !receipt.audit.length)
    return false;
  const last = receipt.audit[receipt.audit.length - 1];
  return !!(
    last &&
    last.schema_version ===
      "quasi.operation.book.audit.receipt/0.1" &&
    last.key === "book.audit" &&
    last.effect === "writer" &&
    last.status === "clean" &&
    last.attempt === 1 &&
    last.target_path === `vault/books/${demand.id}` &&
    last.remaining_violations === 0 &&
    Array.isArray(last.escalated) &&
    last.escalated.length === 0
  );
}

function strictMaterialResult(result, demand) {
  if (
    !result ||
    typeof result !== "object" ||
    Array.isArray(result) ||
    result.slug !== demand.id ||
    !result.material_receipt ||
    typeof result.material_receipt !== "object" ||
    Array.isArray(result.material_receipt)
  )
    return null;
  const receipt = result.material_receipt;
  const baseKeys = [
    "schema_version",
    "material_key",
    "kind",
    "id",
    "status",
    "disposition",
    "stage",
    "artifacts",
    "operations",
    "audit",
    "freshness",
    "warnings",
    "failure",
    "resume",
  ];
  const bookKeys = [
    ...baseKeys,
    "expected_slots",
    "present_slots",
    "missing_slots",
  ];
  if (
    !(exactKeys(receipt, baseKeys) ||
      (demand.kind === "book" &&
        exactKeys(receipt, bookKeys))) ||
    receipt.schema_version !==
      "quasi.material-loop.receipt/0.1" ||
    receipt.material_key !== demand.material_key ||
    receipt.kind !== demand.kind ||
    receipt.id !== demand.id ||
    !["complete", "blocked", "failed"].includes(
      receipt.status,
    ) ||
    !Array.isArray(receipt.artifacts) ||
    receipt.artifacts.some(
      (artifact) => !validMaterialArtifact(artifact),
    ) ||
    !Array.isArray(receipt.operations) ||
    !Array.isArray(receipt.warnings) ||
    !exactKeys(receipt.freshness, ["observation", "basis"]) ||
    receipt.freshness.observation !== "unknown" ||
    receipt.freshness.basis !==
      "operation-receipts-and-final-audit"
  )
    return null;
  const target = topicMemberPath(demand.kind, demand.id);
  const canonicals = receipt.artifacts.filter(
    (artifact) =>
      artifact.role === "canonical" &&
      artifact.path === target &&
      artifact.exists === true &&
      artifact.usable !== false,
  );
  if (receipt.status === "complete") {
    if (
      !["created", "reused", "repaired"].includes(
        receipt.disposition,
      ) ||
      receipt.stage !== "audit" ||
      receipt.failure !== null ||
      receipt.resume !== null ||
      canonicals.length !== 1 ||
      !cleanChildAudit(receipt, demand)
    )
      return null;
    if (
      demand.kind === "book" &&
      Object.prototype.hasOwnProperty.call(
        receipt,
        "expected_slots",
      ) &&
      (!Array.isArray(receipt.expected_slots) ||
        !Array.isArray(receipt.present_slots) ||
        !Array.isArray(receipt.missing_slots) ||
        !sameStrings(
          receipt.expected_slots,
          receipt.present_slots,
        ) ||
        receipt.missing_slots.length !== 0)
    )
      return null;
  } else if (
    receipt.disposition !== null ||
    !validMaterialFailure(receipt.failure) ||
    (receipt.status === "failed" && receipt.resume !== null) ||
    (receipt.status === "blocked" &&
      !(
        receipt.resume === null ||
        (receipt.resume &&
          typeof receipt.resume === "object" &&
          !Array.isArray(receipt.resume))
      ))
  )
    return null;
  return {
    material_key: demand.material_key,
    kind: demand.kind,
    id: demand.id,
    status: receipt.status,
    canonical_path:
      receipt.status === "complete" ? target : null,
    subq: demand.subq,
    role: demand.role,
    receipt,
  };
}

function candidateIdentity(candidate) {
  if (candidate.kind === "book")
    return JSON.stringify({
      title: candidate.title,
      authors: candidate.authors,
      year: candidate.year,
      isbn: candidate.isbn,
      publisher: candidate.publisher,
      category: candidate.category,
    });
  return JSON.stringify({
    title: candidate.title,
    authors: candidate.authors,
    year: candidate.year,
    doi: candidate.doi,
    oa_url: candidate.oa_url,
    url: candidate.url,
    journal: candidate.journal,
  });
}

function buildMaterialDemands(discoveries, resolved) {
  const demands = [];
  const byKey = new Map();
  for (let index = 0; index < discoveries.length; index += 1) {
    const discovery = discoveries[index];
    const candidate = discovery.receipt.candidate;
    const row = resolved[index];
    const id = row.resolved_slug || candidate.slug;
    const materialKey = `${candidate.kind}:${id}`;
    const identity = candidateIdentity(candidate);
    const existing = byKey.get(materialKey);
    if (existing) {
      if (existing.identity !== identity)
        return {
          ok: false,
          failure: operationFailure(
            "topic.material_identity_conflict",
            "topic.resolve-membership",
            "known",
            `conflicting identities resolved to ${materialKey}`,
          ),
        };
      continue;
    }
    const meta =
      candidate.kind === "book"
        ? {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            isbn: candidate.isbn,
            publisher: candidate.publisher,
            category: candidate.category,
            confidence: "verified",
          }
        : {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            doi: candidate.doi,
            oa_url: candidate.oa_url,
            url: candidate.url,
            journal: candidate.journal,
            confidence: "verified",
          };
    const demand = {
      material_key: materialKey,
      kind: candidate.kind,
      id,
      meta,
      identity,
      subq: discovery.demand.subq,
      role: discovery.demand.role,
    };
    byKey.set(materialKey, demand);
    demands.push(demand);
  }
  return { ok: true, demands };
}

function invalidMaterialResult(demand, message) {
  return {
    material_key: demand.material_key,
    kind: demand.kind,
    id: demand.id,
    status: "blocked",
    canonical_path: null,
    subq: demand.subq,
    role: demand.role,
    receipt: null,
    failure: operationFailure(
      "topic.child_receipt_invalid",
      "topic.material-join",
      "unknown",
      message,
    ),
  };
}

function writerMismatch(state, key, stage) {
  return terminal(
    state,
    "blocked",
    "blocked",
    stage,
    operationFailure(
      "topic.writer_receipt_mismatch",
      key,
      "unknown",
      "writer receipt did not prove the exact contract",
    ),
  );
}

function writerTerminal(state, receipt, key, stage) {
  if (receipt.status === "blocked")
    return terminal(
      state,
      "blocked",
      "blocked",
      stage,
      receipt.failure,
    );
  if (receipt.status === "failed")
    return terminal(
      state,
      key === "topic.audit.legacy"
        ? "audit_escalated"
        : "synth_failed",
      "failed",
      stage,
      receipt.failure,
    );
  return null;
}

function applySteer(state, receipt) {
  state.signal = receipt.signal;
  state.subquestions = receipt.subquestions;
  state.suggestedQueries = receipt.suggested_queries;
  if (receipt.action === "repair") state.repaired = true;
  if (receipt.action === "create")
    state.disposition = "created";
  if (
    receipt.action === "reconciled" &&
    state.disposition === null
  )
    state.disposition = "reused";
}

function operationOptions(key, effect, roles, contract, context) {
  return {
    key,
    effect,
    retry: effect === "readonly" ? "safe" : "forbidden",
    replay: effect === "readonly" ? "safe" : "blocked",
    artifactRoles: roles,
    unknownFailureCode:
      effect === "readonly"
        ? "topic.readonly_outcome_unknown"
        : "topic.writer_outcome_unknown",
    contract,
    context,
  };
}

async function runSteer(
  runtime,
  state,
  round,
  members,
  mode,
  diagnostics,
  label,
) {
  const inputPaths = members.map((member) => member.path);
  const steered = await runtime.operate(
    topicSteerOperationPrompt({
      researchKey: state.researchKey,
      topicSlug: state.slug,
      query:
        round === 0 && state.seeds.length
          ? `${state.desc}\nUser seeds: ${state.seeds.join("; ")}`
          : state.desc,
      memberRefs: members,
      mode,
      diagnostics,
    }),
    {
      phase: "Search",
      agentType: "quasi:steer-agent",
      label,
      schema: TOPIC_STEER_OPERATION_SCHEMA,
    },
    operationOptions(
      "topic.steer",
      "writer",
      ["outline"],
      TOPIC_STEER_CONTRACT,
      { state, memberRefs: members, inputPaths, mode },
    ),
  );
  const receipt = steered.receipt;
  state.operations.push(receipt);
  state.budgets.steer.used += 1;
  if (
    steered.edge === "unknown" ||
    steered.edge === "mismatch"
  )
    return { terminal: writerMismatch(state, "topic.steer", "steer") };
  const stopped = writerTerminal(
    state,
    receipt,
    "topic.steer",
    "steer",
  );
  if (stopped) return { terminal: stopped };
  applySteer(state, receipt);
  return { receipt };
}

async function runSynthesis(
  runtime,
  state,
  kind,
  mode,
  diagnostics,
  label,
) {
  const overview = kind === "overview";
  const key = overview
    ? "topic.synthesise.overview"
    : "topic.synthesise.resources";
  const output = overview
    ? state.paths.overview
    : state.paths.resources;
  const role = overview ? "overview" : "resources";
  const inputPaths = [
    ...state.members.map((member) => member.path),
  ];
  const prompt = overview
    ? topicOverviewSynthesisePrompt({
        researchKey: state.researchKey,
        topicSlug: state.slug,
        topic: state.desc,
        memberRefs: state.members,
        mode,
        diagnostics,
      })
    : topicResourcesSynthesisePrompt({
        researchKey: state.researchKey,
        topicSlug: state.slug,
        topic: state.desc,
        memberRefs: state.members,
        mode,
        diagnostics,
      });
  const synthesis = await runtime.operate(
    prompt,
    {
      phase: "Synthesise",
      agentType: "quasi:synthesis-agent",
      label,
      schema: (overview
        ? topicOverviewSynthesiseSchema
        : topicResourcesSynthesiseSchema)({
        researchKey: state.researchKey,
        members: state.members,
        inputPaths,
        outline: state.paths.outline,
        output,
        mode,
      }),
    },
    operationOptions(
      key,
      "writer",
      [role],
      overview
        ? TOPIC_OVERVIEW_SYNTHESISE_CONTRACT
        : TOPIC_RESOURCES_SYNTHESISE_CONTRACT,
      { state, inputPaths, output, role, mode },
    ),
  );
  const receipt = synthesis.receipt;
  state.operations.push(receipt);
  state.budgets.synthesis.used += 1;
  if (
    synthesis.edge === "unknown" ||
    synthesis.edge === "mismatch"
  )
    return { terminal: writerMismatch(state, key, "synthesis") };
  const stopped = writerTerminal(
    state,
    receipt,
    key,
    "synthesis",
  );
  if (stopped) return { terminal: stopped };
  if (receipt.action === "repair") state.repaired = true;
  if (receipt.action === "create")
    state.disposition = "created";
  if (
    receipt.action === "reconciled" &&
    state.disposition === null
  )
    state.disposition = "reused";
  return { receipt };
}

async function runAudit(runtime, state, target, pass) {
  const audited = await runtime.operate(
    topicAuditLegacyPrompt(state.researchKey, target, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label: `${state.slug}:audit-${pass}:${target.split("/").pop()}`,
      schema: topicAuditSchema({
        researchKey: state.researchKey,
        target,
      }),
    },
    operationOptions(
      "topic.audit.legacy",
      "writer",
      ["topic_product"],
      TOPIC_AUDIT_CONTRACT,
      { researchKey: state.researchKey, target },
    ),
  );
  const receipt = audited.receipt;
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (
    audited.edge === "unknown" ||
    audited.edge === "mismatch"
  )
    return {
      terminal: writerMismatch(
        state,
        "topic.audit.legacy",
        "audit",
      ),
    };
  const owned = [
    ...receipt.escalated.map((item) => item.path),
    ...receipt.mutated_paths,
  ].every((path) => path === target);
  if (!owned)
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        operationFailure(
          "topic.repair_owner_unknown",
          "topic.audit.legacy",
          "known",
          "audit reported a path outside the exact Topic producer map",
        ),
        { escalated: receipt.escalated },
      ),
    };
  if (receipt.mutated_paths.length) state.repaired = true;
  if (audited.edge !== "ok")
    return {
      terminal: terminal(
        state,
        receipt.failure.outcome === "unknown"
          ? "blocked"
          : "audit_escalated",
        receipt.failure.outcome === "unknown"
          ? "blocked"
          : "failed",
        "audit",
        receipt.failure,
      ),
    };
  return {
    receipt,
    clean: receipt.status === "clean",
    diagnostics: receipt.escalated,
  };
}

async function runMaterialRound(
  runtime,
  router,
  state,
  candidateDemands,
) {
  const ledger = candidateDemands
    .slice(0, state.maxItems)
    .map((demand, index) => ({
      demand,
      demandId: `r1-d${String(index + 1).padStart(2, "0")}`,
    }));
  if (!ledger.length) return { partial: false };
  state.rounds = 1;
  state.budgets.discovery.used = ledger.length;
  const discoveryRuns = await runtime.parallel(
    ledger.map(({ demand, demandId }) => () => {
      const book = demand.kind === "book";
      return runtime.operate(
        book
          ? topicDiscoverBookOperationPrompt(
              state.researchKey,
              demandId,
              demand,
            )
          : topicDiscoverPaperOperationPrompt(
              state.researchKey,
              demandId,
              demand,
            ),
        {
          phase: "Search",
          agentType: "quasi:discovery-agent",
          label: `${state.slug}:discover:${demandId}`,
          schema: book
            ? TOPIC_DISCOVER_BOOK_SCHEMA
            : TOPIC_DISCOVER_PAPER_SCHEMA,
        },
        operationOptions(
          `topic.discover-${demand.kind}`,
          "readonly",
          [],
          book
            ? TOPIC_DISCOVER_BOOK_CONTRACT
            : TOPIC_DISCOVER_PAPER_CONTRACT,
          { state, demandId, demand },
        ),
      );
    }),
  );
  state.operations.push(
    ...discoveryRuns.map((run) => run.receipt),
  );
  for (let index = 0; index < ledger.length; index += 1) {
    if (
      ["unknown", "mismatch"].includes(
        discoveryRuns[index].edge,
      )
    )
      return {
        terminal: terminal(
          state,
          "blocked",
          "blocked",
          "discovery",
          operationFailure(
            "topic.discovery_receipt_invalid",
            `topic.discover-${ledger[index].demand.kind}`,
            "unknown",
            "discovery receipt did not prove the exact demand contract",
          ),
        ),
      };
  }
  const discoveries = ledger
    .map((entry, index) => ({
      ...entry,
      run: discoveryRuns[index],
      receipt: discoveryRuns[index].receipt,
    }))
    .filter(({ run, receipt }) => {
      if (run.edge === "ok") return true;
      state.discoveryFailures.push(receipt.failure);
      return false;
    });
  if (!discoveries.length)
    return { partial: state.discoveryFailures.length > 0 };

  const requests = discoveries.map(({ receipt }) => ({
    kind: receipt.candidate.kind,
    slug: receipt.candidate.slug,
  }));
  const membershipRun = await runtime.operate(
    topicResolveMembershipPrompt(state.researchKey, requests),
    {
      phase: "Recall",
      agentType: "general-purpose",
      label: `${state.slug}:resolve-discovered:r1`,
      schema: TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
    },
    operationOptions(
      "topic.resolve-membership",
      "readonly",
      [],
      TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
      { state, requests, allowAlias: true },
    ),
  );
  const membership = membershipRun.receipt;
  state.operations.push(membership);
  if (
    membershipRun.edge === "unknown" ||
    membershipRun.edge === "mismatch"
  )
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "membership",
        operationFailure(
          "topic.membership_receipt_invalid",
          "topic.resolve-membership",
          "unknown",
          "discovered membership did not correlate exact candidates",
        ),
      ),
    };
  if (membershipRun.edge !== "ok")
    return {
      terminal: terminal(
        state,
        membershipRun.edge === "blocked"
          ? "blocked"
          : "all_failed",
        membershipRun.edge === "blocked"
          ? "blocked"
          : "failed",
        "membership",
        membership.failure,
      ),
    };
  const grouped = buildMaterialDemands(
    discoveries,
    membership.resolved,
  );
  if (!grouped.ok)
    return {
      terminal: terminal(
        state,
        "all_failed",
        "failed",
        "membership",
        grouped.failure,
      ),
    };
  state.budgets.materials.used = grouped.demands.length;
  const childResults = await runtime.parallel(
    grouped.demands.map((demand) => async () => {
      try {
        const result = await router(
          demand.kind,
          { slug: demand.id, meta: demand.meta },
          demand.kind === "book" ? { batchYear: true } : {},
        );
        return (
          strictMaterialResult(result, demand) ||
          invalidMaterialResult(
            demand,
            "child result did not carry its exact MaterialReceipt",
          )
        );
      } catch (error) {
        return invalidMaterialResult(
          demand,
          (error && error.message) || String(error),
        );
      }
    }),
  );
  state.materialResults.push(...childResults);
  const existing = new Set(
    state.members.map(
      (member) => `${member.kind}:${member.slug}`,
    ),
  );
  for (const child of childResults) {
    if (child.status !== "complete") continue;
    if (existing.has(child.material_key)) continue;
    state.members.push({
      kind: child.kind,
      slug: child.id,
      path: child.canonical_path,
    });
    existing.add(child.material_key);
  }
  return {
    partial:
      state.discoveryFailures.length > 0 ||
      childResults.some((child) => child.status !== "complete"),
  };
}

async function processStrict(runtime, router, slug, meta) {
  const state = createState(slug, meta);
  runtime.log(
    `${slug}: strict Topic ${meta.maxRounds === 0 ? "recall-only" : "one material round"}`,
  );
  state.budgets.recall.used = state.maxItems;
  const [recallRun, initialSteerResult] = await runtime.parallel([
    () =>
      runtime.operate(
        topicRecallPrompt(
          state.researchKey,
          state.desc,
          state.maxItems,
        ),
        {
          phase: "Recall",
          agentType: "general-purpose",
          label: `${slug}:recall`,
          schema: TOPIC_RECALL_SCHEMA,
        },
        operationOptions(
          "topic.recall",
          "readonly",
          [],
          TOPIC_RECALL_CONTRACT,
          { state },
        ),
      ),
    () =>
      runSteer(
        runtime,
        state,
        0,
        [],
        "create",
        [],
        `${slug}:steer:r0`,
      ),
  ]);
  const recall = recallRun.receipt;
  state.operations.unshift(recall);
  if (
    recallRun.edge === "unknown" ||
    recallRun.edge === "mismatch"
  ) {
    return terminal(
      state,
      "blocked",
      "blocked",
      "recall",
      operationFailure(
        "topic.recall_receipt_invalid",
        "topic.recall",
        "unknown",
        "recall receipt did not prove the exact contract",
      ),
    );
  }
  if (initialSteerResult.terminal)
    return initialSteerResult.terminal;
  if (recallRun.edge === "blocked")
    return terminal(
      state,
      "blocked",
      "blocked",
      "recall",
      recall.failure,
    );
  if (recallRun.edge === "failed" && meta.maxRounds === 0)
    return terminal(
      state,
      "no_works",
      "failed",
      "recall",
      recall.failure,
    );
  if (recallRun.edge === "failed") {
    state.recallFailed = true;
    state.warnings.push(
      `Topic recall failed before the material round: ${recall.failure.code}`,
    );
  }

  const requests =
    recallRun.edge === "ok" ? recall.items : [];
  if (!requests.length && meta.maxRounds === 0)
    return terminal(
      state,
      "no_works",
      "failed",
      "recall",
      operationFailure(
        "topic.no_works",
        "topic.join",
        "known",
        "no recalled material is available",
      ),
    );

  if (requests.length) {
    const membershipRun = await runtime.operate(
      topicResolveMembershipPrompt(state.researchKey, requests),
      {
        phase: "Recall",
        agentType: "general-purpose",
        label: `${slug}:resolve-membership`,
        schema: TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
      },
      operationOptions(
        "topic.resolve-membership",
        "readonly",
        [],
        TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
        { state, requests, allowAlias: false },
      ),
    );
    const membership = membershipRun.receipt;
    state.operations.push(membership);
    if (
      membershipRun.edge === "unknown" ||
      membershipRun.edge === "mismatch"
    ) {
      return terminal(
        state,
        "blocked",
        "blocked",
        "membership",
        operationFailure(
          "topic.membership_receipt_invalid",
          "topic.resolve-membership",
          "unknown",
          "membership receipt did not correlate exact requests",
        ),
      );
    }
    if (membershipRun.edge === "failed")
      return terminal(
        state,
        "no_works",
        "failed",
        "membership",
        membership.failure,
      );
    if (membershipRun.edge === "blocked")
      return terminal(
        state,
        "blocked",
        "blocked",
        "membership",
        membership.failure,
      );
    state.members = membership.resolved
      .filter((row) => row.resolved_slug !== null)
      .map((row) => ({
        kind: row.kind,
        slug: row.resolved_slug,
        path: row.path,
      }));
    state.recalled = state.members.length;
  }
  if (!state.members.length && meta.maxRounds === 0)
    return terminal(
      state,
      state.final ? "no_works" : "needs_seeds",
      state.final ? "failed" : "needs_input",
      "membership",
      operationFailure(
        state.final ? "topic.no_works" : "topic.needs_seeds",
        "topic.join",
        "known",
        "no recalled member resolved to an exact canonical",
      ),
      { suggested_queries: state.suggestedQueries },
    );

  let planningSteer = initialSteerResult;
  if (state.members.length) {
    planningSteer = await runSteer(
      runtime,
      state,
      1,
      state.members,
      "refresh",
      [],
      meta.maxRounds === 0
        ? `${slug}:steer:r1-close`
        : `${slug}:steer:r1-plan`,
    );
    if (planningSteer.terminal) return planningSteer.terminal;
  }
  if (meta.maxRounds === 1) {
    const materialRound = await runMaterialRound(
      runtime,
      router,
      state,
      planningSteer.receipt.candidate_demands,
    );
    if (materialRound.terminal) return materialRound.terminal;
    if (planningSteer.receipt.candidate_demands.length) {
      const closingSteer = await runSteer(
        runtime,
        state,
        1,
        state.members,
        "refresh",
        [],
        `${slug}:steer:r1-close`,
      );
      if (closingSteer.terminal) return closingSteer.terminal;
    }
  }
  if (!state.members.length)
    return terminal(
      state,
      state.final ? "no_works" : "needs_seeds",
      state.final ? "failed" : "needs_input",
      state.rounds ? "material-join" : "steer",
      operationFailure(
        state.final ? "topic.no_works" : "topic.needs_seeds",
        "topic.join",
        "known",
        state.rounds
          ? "the material round produced no complete canonical members"
          : "steering produced no material demands",
      ),
      { suggested_queries: state.suggestedQueries },
    );
  if (state.members.length < state.minItems && !state.final)
    return terminal(
      state,
      "needs_seeds",
      "needs_input",
      "membership",
      operationFailure(
        "topic.needs_seeds",
        "topic.join",
        "known",
        "resolved recall corpus is below the minimum evidence budget",
      ),
      {
        collected: state.members.length,
        suggested_queries: state.suggestedQueries,
      },
    );

  const synthResults = await runtime.parallel([
    () =>
      runSynthesis(
        runtime,
        state,
        "overview",
        "create",
        [],
        `${slug}:synthesise-overview`,
      ),
    () =>
      runSynthesis(
        runtime,
        state,
        "resources",
        "create",
        [],
        `${slug}:synthesise-resources`,
      ),
  ]);
  const synthTerminal = synthResults.find(
    (result) => result.terminal,
  );
  if (synthTerminal) return synthTerminal.terminal;

  const targets = [
    state.paths.overview,
    state.paths.resources,
    state.paths.outline,
  ];
  const owner = new Map([
    [state.paths.outline, "steer"],
    [state.paths.overview, "overview"],
    [state.paths.resources, "resources"],
  ]);
  const firstAudits = await runtime.parallel(
    targets.map(
      (target) => () => runAudit(runtime, state, target, 1),
    ),
  );
  const auditTerminal = firstAudits.find(
    (result) => result.terminal,
  );
  if (auditTerminal) return auditTerminal.terminal;
  const dirty = firstAudits
    .map((result, index) => ({
      target: targets[index],
      result,
    }))
    .filter(({ result }) => !result.clean);
  if (dirty.length) {
    state.budgets.repairRounds.used = 1;
    const repairs = await runtime.parallel(
      dirty.map(({ target, result }) => () => {
        const producer = owner.get(target);
        if (producer === "steer")
          return runSteer(
            runtime,
            state,
            1,
            state.members,
            "repair",
            result.diagnostics,
            `${slug}:repair-outline`,
          );
        return runSynthesis(
          runtime,
          state,
          producer,
          "repair",
          result.diagnostics,
          `${slug}:repair-${producer}`,
        );
      }),
    );
    const repairTerminal = repairs.find(
      (result) => result.terminal,
    );
    if (repairTerminal) return repairTerminal.terminal;
    const secondAudits = await runtime.parallel(
      dirty.map(
        ({ target }) => () =>
          runAudit(runtime, state, target, 2),
      ),
    );
    const secondTerminal = secondAudits.find(
      (result) => result.terminal,
    );
    if (secondTerminal) return secondTerminal.terminal;
    const residual = secondAudits.find(
      (result) => !result.clean,
    );
    if (residual)
      return terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        operationFailure(
          "topic.audit_repair_exhausted",
          "topic.audit.legacy",
          "known",
          "Topic product remains non-clean after one repair round",
        ),
        { escalated: residual.diagnostics },
      );
  }

  state.artifacts = [
    {
      role: "outline",
      path: state.paths.outline,
      exists: true,
      producer: "topic.steer",
    },
    {
      role: "overview",
      path: state.paths.overview,
      exists: true,
      producer: "topic.synthesise.overview",
    },
    {
      role: "resources",
      path: state.paths.resources,
      exists: true,
      producer: "topic.synthesise.resources",
    },
  ];
  const partial =
    state.recallFailed ||
    state.discoveryFailures.length > 0 ||
    state.materialResults.some(
      (member) => member.status !== "complete",
    );
  return terminal(
    state,
    "ok",
    partial ? "partial" : "complete",
    "complete",
  );
}

export async function processTopicStrict(
  runtime,
  router,
  slug,
  rawMeta,
) {
  runtime.phase("Recall");
  const validation = validateIdentity(slug, rawMeta);
  if (!validation.ok)
    return rejectedResult(slug, validation);
  return runtime.coalesce(
    `topic:${slug}`,
    validation.fingerprint,
    () => processStrict(runtime, router, slug, validation.meta),
    () =>
      rejectedResult(
        slug,
        {
          ...validation,
          code: "topic.identity_conflict",
          message:
            "conflicting Topic identity for one research key",
        },
        true,
      ),
  );
}
