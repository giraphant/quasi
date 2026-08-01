import {
  TOPIC_DISCOVER_BOOK_CONTRACT,
  TOPIC_DISCOVER_PAPER_CONTRACT,
  TOPIC_RECALL_CONTRACT,
  TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
  topicDiscoverBookOperationPrompt,
  topicDiscoverBookStageSchema,
  topicDiscoverPaperOperationPrompt,
  topicDiscoverPaperStageSchema,
  topicRecallOperationPrompt as topicRecallPrompt,
  topicRecallStageSchema,
  topicResolveMembershipOperationPrompt as topicResolveMembershipPrompt,
  topicResolveMembershipStageSchema,
} from "../operations/acquire.mjs";
import { admitChildResult } from "../materials/member.mjs";
import { routeStageEdge } from "../materials/route.mjs";
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
import { stageIssue } from "../stage.mjs";

const RESEARCH_RECEIPT_VERSION =
  "quasi.research.topic.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

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

async function strictMaterialResult(runtime, result, demand) {
  const admitted = await admitChildResult(runtime, result, demand);
  if (
    !admitted ||
    !["complete", "needs_input", "blocked", "failed"].includes(
      admitted.status,
    )
  )
    return null;
  return {
    ...admitted,
    subq: demand.subq,
    role: demand.role,
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

function topicStageFailure(
  receipt,
  operationKey,
  outcome = "known",
) {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || `${operationKey}_failed`,
    operationKey,
    outcome,
    (issue && issue.summary) || `${operationKey} did not complete`,
  );
}

function routeTopicStage(
  run,
  state,
  stage,
  operationKey,
  {
    mismatchCode,
    mismatchMessage,
    failedStatus = "all_failed",
    needsInputStatus = "needs_seeds",
    needsInputExtra = null,
    onOk = (receipt) => ({ value: { edge: "ok", receipt } }),
    onFailed = null,
  },
) {
  return routeStageEdge(run, {
    state,
    stage,
    operationKey,
    emit: ({ status, failure, extra }) =>
      terminal(
        state,
        status === "needs_input" ? needsInputStatus : status,
        status === "all_failed" ? "failed" : status,
        stage,
        failure,
        extra,
      ),
    failure: (receipt, outcome) =>
      topicStageFailure(receipt, operationKey, outcome),
    unknown: () =>
      terminal(
        state,
        "blocked",
        "blocked",
        stage,
        operationFailure(
          mismatchCode,
          operationKey,
          "unknown",
          mismatchMessage,
        ),
      ),
    mismatch: () =>
      terminal(
        state,
        "blocked",
        "blocked",
        stage,
        operationFailure(
          mismatchCode,
          operationKey,
          "unknown",
          mismatchMessage,
        ),
      ),
    blockedStatus: "blocked",
    blockedOutcome: "unknown",
    failedStatus,
    needsInputStatus: "needs_input",
    needsInputExtra,
    onOk,
    onFailed,
  });
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
            ? topicDiscoverBookStageSchema({
                researchKey: state.researchKey,
                demandId,
                demand,
              })
            : topicDiscoverPaperStageSchema({
                researchKey: state.researchKey,
                demandId,
                demand,
              }),
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
  const discoveryRoutes = discoveryRuns.map((run, index) =>
    routeTopicStage(
      run,
      state,
      "discovery",
      `topic.discover-${ledger[index].demand.kind}`,
      {
        mismatchCode: "topic.discovery_receipt_invalid",
        mismatchMessage:
          "discovery receipt did not prove the exact demand contract",
        onOk: (receipt) => ({ value: { edge: "ok", receipt } }),
        onFailed: (receipt) => ({ value: { edge: "failed", receipt } }),
      },
    ),
  );
  const discoveryTerminal = discoveryRoutes.find(
    (routed) => routed.terminal,
  );
  if (discoveryTerminal) return discoveryTerminal;
  const discoveries = ledger
    .map((entry, index) => ({
      ...entry,
      ...discoveryRoutes[index].value,
    }))
    .filter(({ edge, receipt }) => {
      if (edge === "ok") return true;
      state.discoveryFailures.push(
        topicStageFailure(
          receipt,
          `topic.discover-${receipt.demand.kind}`,
        ),
      );
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
      schema: topicResolveMembershipStageSchema({
        researchKey: state.researchKey,
        requests,
      }),
    },
    operationOptions(
      "topic.resolve-membership",
      "readonly",
      [],
      TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
      { state, requests, allowAlias: true },
    ),
  );
  const membershipRoute = routeTopicStage(
    membershipRun,
    state,
    "membership",
    "topic.resolve-membership",
    {
      mismatchCode: "topic.membership_receipt_invalid",
      mismatchMessage:
        "discovered membership did not correlate exact candidates",
    },
  );
  if (membershipRoute.terminal) return membershipRoute;
  const membership = membershipRoute.value.receipt;
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
          (await strictMaterialResult(runtime, result, demand)) ||
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
          schema: topicRecallStageSchema({
            researchKey: state.researchKey,
            query: state.desc,
            maxItems: state.maxItems,
          }),
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
  const recallRoute = routeTopicStage(
    recallRun,
    state,
    "recall",
    "topic.recall",
    {
      mismatchCode: "topic.recall_receipt_invalid",
      mismatchMessage: "recall receipt did not prove the exact contract",
      onOk: (receipt) => ({ value: { edge: "ok", receipt } }),
      onFailed: (receipt) => ({ value: { edge: "failed", receipt } }),
    },
  );
  if (recallRoute.terminal) return recallRoute.terminal;
  if (initialSteerResult.terminal)
    return initialSteerResult.terminal;
  const { edge: recallEdge, receipt: recall } = recallRoute.value;
  const recallFailure = topicStageFailure(recall, "topic.recall");
  if (recallEdge === "failed" && meta.maxRounds === 0)
    return terminal(
      state,
      "no_works",
      "failed",
      "recall",
      recallFailure,
    );
  if (recallEdge === "failed") {
    state.recallFailed = true;
    state.warnings.push(
      `Topic recall failed before the material round: ${recallFailure.code}`,
    );
  }

  const requests = recallEdge === "ok" ? recall.items : [];
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
    const membershipRequests = requests.map(({ kind, slug: id }) => ({
      kind,
      slug: id,
    }));
    const membershipRun = await runtime.operate(
      topicResolveMembershipPrompt(
        state.researchKey,
        membershipRequests,
      ),
      {
        phase: "Recall",
        agentType: "general-purpose",
        label: `${slug}:resolve-membership`,
        schema: topicResolveMembershipStageSchema({
          researchKey: state.researchKey,
          requests: membershipRequests,
        }),
      },
      operationOptions(
        "topic.resolve-membership",
        "readonly",
        [],
        TOPIC_RESOLVE_MEMBERSHIP_CONTRACT,
        { state, requests: membershipRequests, allowAlias: false },
      ),
    );
    const membershipRoute = routeTopicStage(
      membershipRun,
      state,
      "membership",
      "topic.resolve-membership",
      {
        mismatchCode: "topic.membership_receipt_invalid",
        mismatchMessage:
          "membership receipt did not correlate exact requests",
        onFailed: (receipt) => ({
          terminal: terminal(
            state,
            "no_works",
            "failed",
            "membership",
            topicStageFailure(receipt, "topic.resolve-membership"),
          ),
        }),
      },
    );
    if (membershipRoute.terminal) return membershipRoute.terminal;
    const membership = membershipRoute.value.receipt;
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
