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
  topicAudit,
  topicOverview,
  topicResources,
  topicSteer,
  topicWebcard,
} from "../operations/rows/topic.mjs";
import { cardPath } from "../operations/steer.mjs";
import { validText } from "../runtime.mjs";
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
  const maxRounds =
    meta.maxRounds === undefined ? 3 : meta.maxRounds;
  if (
    !Number.isInteger(maxRounds) ||
    maxRounds < 0 ||
    maxRounds > 8
  )
    return {
      ok: false,
      code: "topic.mode_invalid",
      message:
        "Topic maxRounds must be an integer from 0 (recall-only) through 8",
    };
  const maxItems =
    meta.maxPerRound === undefined ? 8 : meta.maxPerRound;
  const minItems =
    meta.minItems === undefined ? 3 : meta.minItems;
  const maxCards =
    meta.maxCardsPerRound === undefined
      ? 3
      : meta.maxCardsPerRound;
  if (
    !Number.isInteger(maxItems) ||
    maxItems < 1 ||
    maxItems > 16 ||
    !Number.isInteger(minItems) ||
    minItems < 1 ||
    minItems > 16 ||
    !Number.isInteger(maxCards) ||
    maxCards < 0 ||
    maxCards > 6
  )
    return {
      ok: false,
      code: "topic.budget_invalid",
      message:
        "Topic budgets require maxPerRound/minItems 1..16 and maxCardsPerRound 0..6",
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
    maxRounds,
    maxItems,
    maxCards,
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
    maxRounds: meta.maxRounds,
    maxItems: meta.maxItems,
    maxCards: meta.maxCards,
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
    cards: [],
    materialResults: [],
    discoveryFailures: [],
    cardFailures: [],
    recallFailed: false,
    recalled: 0,
    rounds: 0,
    artifacts: [],
    subquestions: [],
    memberAssignments: [],
    attemptedDemands: new Set(),
    attemptedCards: new Set(),
    dispatchedMaterials: new Set(),
    repaired: false,
    disposition: null,
    signal: null,
    suggestedQueries: null,
    deadEnd: true,
    warnings:
      meta.maxRounds === 0
        ? [
            "recall-only Topic does not dispatch new materials or web cards",
          ]
        : [],
    userGate: null,
    budgets: {
      recall: { used: 0, limit: meta.maxItems },
      discovery: {
        used: 0,
        limit: meta.maxRounds * meta.maxItems,
      },
      materials: {
        used: 0,
        limit: meta.maxRounds * meta.maxItems,
      },
      cards: {
        used: 0,
        limit: meta.maxRounds * meta.maxCards,
      },
      steer: { used: 0, limit: meta.maxRounds + 3 },
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
    card_failures: state.cardFailures,
    artifacts: state.artifacts,
    operations: state.operations,
    audit: state.audit,
    budgets: state.budgets,
    subquestions: state.subquestions,
    warnings: state.warnings,
    user_gate: state.userGate,
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
    cards: state.cards.length,
    recalled: state.recalled,
    rounds: state.rounds,
    overview: state.paths.overview,
    resources: state.paths.resources,
    outline: state.paths.outline,
    saturated: state.signal === "saturated",
    subquestions: state.subquestions.map((subquestion) => ({
      id: subquestion.id,
      coverage: subquestion.coverage,
    })),
    book_slugs: books,
    failures:
      state.materialResults.filter(
        (member) => member.status !== "complete",
      ).length +
      state.discoveryFailures.length +
      state.cardFailures.length +
      (failure ? 1 : 0),
    dead_end: state.deadEnd,
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
    maxItems: 0,
    maxCards: 0,
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

async function admittedMaterialResult(runtime, result, demand) {
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

function applySteer(state, receipt) {
  state.signal = receipt.signal;
  state.subquestions = receipt.subquestions;
  state.suggestedQueries = receipt.suggested_queries;
  for (const subquestion of receipt.subquestions) {
    for (const slug of subquestion.cards) {
      if (state.cards.some((card) => card.slug === slug)) continue;
      state.cards.push({
        slug,
        path: cardPath(state.slug, slug),
        subq: subquestion.id,
        title: slug,
      });
    }
  }
  const action = receipt.terminal.action;
  if (action === "repair") state.repaired = true;
  if (action === "create")
    state.disposition = "created";
  if (
    action === "reconciled" &&
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
    needsInputExtra = (receipt) => ({
      question: receipt.terminal.issue.user_question,
    }),
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
  const context = {
    materialKey: state.researchKey,
    researchKey: state.researchKey,
    topicSlug: state.slug,
    query:
      round === 0 && state.seeds.length
        ? `${state.desc}\nUser seeds: ${state.seeds.join("; ")}`
        : state.desc,
    memberRefs: members,
    memberAssignments: state.memberAssignments,
    cardRefs: state.cards,
    mode,
    diagnostics,
    artifactRoles: ["outline"],
    replay: "blocked",
    unknownFailureCode: "topic.writer_outcome_unknown",
  };
  const spec = topicSteer.spec(context);
  const steered = await runtime.operate(
    topicSteer.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label,
      schema: topicSteer.schema(context),
    },
    spec,
  );
  state.budgets.steer.used += 1;
  const routed = routeTopicStage(
    steered,
    state,
    "steer",
    "topic.steer",
    {
      mismatchCode: "topic.writer_receipt_mismatch",
      mismatchMessage:
        "writer receipt did not prove the exact contract",
      failedStatus: "synth_failed",
      needsInputExtra: (receipt) => ({
        question: receipt.terminal.issue.user_question,
        suggested_queries: receipt.suggested_queries,
      }),
    },
  );
  if (routed.terminal) return { terminal: routed.terminal };
  const receipt = routed.value.receipt;
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
  const role = overview ? "overview" : "resources";
  const operation = overview ? topicOverview : topicResources;
  const context = {
    materialKey: state.researchKey,
    researchKey: state.researchKey,
    topicSlug: state.slug,
    topic: state.desc,
    memberRefs: state.members,
    cardRefs: state.cards,
    mode,
    diagnostics,
    artifactRoles: [role],
    replay: "blocked",
    unknownFailureCode: "topic.writer_outcome_unknown",
  };
  const spec = operation.spec(context);
  const synthesis = await runtime.operate(
    operation.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label,
      schema: operation.schema(context),
    },
    spec,
  );
  const receipt = synthesis.receipt;
  state.budgets.synthesis.used += 1;
  const routed = routeTopicStage(
    synthesis,
    state,
    "synthesis",
    key,
    {
      mismatchCode: "topic.writer_receipt_mismatch",
      mismatchMessage:
        "writer receipt did not prove the exact contract",
      failedStatus: "synth_failed",
    },
  );
  if (routed.terminal) return { terminal: routed.terminal };
  if (receipt.terminal.action === "repair") state.repaired = true;
  if (receipt.terminal.action === "create")
    state.disposition = "created";
  if (
    receipt.terminal.action === "reconciled" &&
    state.disposition === null
  )
    state.disposition = "reused";
  return { receipt };
}

async function runAudit(runtime, state, target, pass) {
  const context = {
    materialKey: state.researchKey,
    target,
    pass,
    artifactRoles: ["topic_product"],
    replay: "blocked",
    unknownFailureCode: "topic.writer_outcome_unknown",
  };
  const spec = topicAudit.spec(context);
  const audited = await runtime.operate(
    topicAudit.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label: `${state.slug}:audit-${pass}:${target.split("/").pop()}`,
      schema: topicAudit.schema(context),
    },
    spec,
  );
  const receipt = audited.receipt;
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  const routed = routeTopicStage(
    audited,
    state,
    "audit",
    "topic.audit",
    {
      mismatchCode: "topic.writer_receipt_mismatch",
      mismatchMessage:
        "writer receipt did not prove the exact contract",
      failedStatus: "audit_escalated",
    },
  );
  if (routed.terminal) return { terminal: routed.terminal };
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
          "topic.audit",
          "known",
          "audit reported a path outside the exact Topic producer map",
        ),
        { escalated: receipt.escalated },
      ),
    };
  if (receipt.mutated_paths.length) state.repaired = true;
  return {
    receipt,
    clean: receipt.remaining_violations === 0,
    diagnostics: receipt.escalated,
  };
}

async function runWebcardRound(runtime, state, tasks, round) {
  if (!tasks.length) return { partial: false, added: 0 };
  state.budgets.cards.used += tasks.length;
  const runs = await runtime.parallel(
    tasks.map((task) => () => {
      const context = {
        materialKey: `${state.researchKey}:card:${task.card_slug}`,
        topicSlug: state.slug,
        topic: state.desc,
        task,
        subquestions: state.subquestions,
        artifactRoles: ["evidence_card"],
        replay: "blocked",
        unknownFailureCode: "topic.writer_outcome_unknown",
      };
      const spec = topicWebcard.spec(context);
      return runtime.operate(
        topicWebcard.prompt(context),
        {
          phase: spec.stage,
          agentType: spec.agentType,
          label: `${state.slug}:webcard:r${round}:${task.card_slug}`,
          schema: topicWebcard.schema(context),
        },
        spec,
      );
    }),
  );
  const routes = runs.map((run) =>
    routeTopicStage(
      run,
      state,
      "webcard",
      "topic.webcard",
      {
        mismatchCode: "topic.writer_receipt_mismatch",
        mismatchMessage:
          "webcard receipt did not prove its exact card contract",
        onFailed: (receipt) => ({
          value: { edge: "failed", receipt },
        }),
      },
    ),
  );
  const stopped = routes.find((route) => route.terminal);
  if (stopped) return { terminal: stopped.terminal };
  let added = 0;
  routes.forEach((route, index) => {
    const { edge, receipt } = route.value;
    if (edge !== "ok") {
      state.cardFailures.push(
        topicStageFailure(receipt, "topic.webcard"),
      );
      return;
    }
    if (!receipt.card_available) return;
    const task = tasks[index];
    if (state.cards.some((card) => card.slug === task.card_slug))
      return;
    state.cards.push({
      slug: task.card_slug,
      path: receipt.card_path,
      subq: task.subq,
      title: receipt.title || task.card_slug,
    });
    added += 1;
  });
  return {
    partial: routes.some((route) => route.value.edge !== "ok"),
    added,
  };
}

async function runMaterialRound(
  runtime,
  router,
  state,
  candidateDemands,
  round,
) {
  const ledger = candidateDemands
    .slice(0, state.maxItems)
    .map((demand, index) => ({
      demand,
      demandId: `r${round}-d${String(index + 1).padStart(2, "0")}`,
    }));
  if (!ledger.length) return { partial: false };
  state.budgets.discovery.used += ledger.length;
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
      label: `${state.slug}:resolve-discovered:r${round}`,
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
  const freshDemands = grouped.demands.filter(
    (demand) => !state.dispatchedMaterials.has(demand.material_key),
  );
  freshDemands.forEach((demand) =>
    state.dispatchedMaterials.add(demand.material_key),
  );
  state.budgets.materials.used += freshDemands.length;
  const childResults = await runtime.parallel(
    freshDemands.map((demand) => async () => {
      try {
        const result = await router(
          demand.kind,
          { slug: demand.id, meta: demand.meta },
          demand.kind === "book" ? { batchYear: true } : {},
        );
        return (
          (await admittedMaterialResult(runtime, result, demand)) ||
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
  for (const demand of grouped.demands) {
    const admitted = state.members.some(
      (member) =>
        `${member.kind}:${member.slug}` === demand.material_key,
    );
    if (!admitted) continue;
    const assignment = {
      member_key: demand.material_key,
      subq: demand.subq,
      role: demand.role,
    };
    if (
      state.memberAssignments.some(
        (entry) =>
          entry.member_key === assignment.member_key &&
          entry.subq === assignment.subq &&
          entry.role === assignment.role,
      )
    )
      continue;
    state.memberAssignments.push(assignment);
  }
  return {
    partial:
      state.discoveryFailures.length > 0 ||
      childResults.some((child) => child.status !== "complete"),
  };
}

const demandFingerprint = (demand) =>
  JSON.stringify([
    demand.kind,
    demand.query,
    demand.subq,
    demand.role,
    demand.reason,
  ]);

function selectRoundWork(state, steer) {
  const demands = [];
  for (const demand of steer.candidate_demands) {
    const key = demandFingerprint(demand);
    if (state.attemptedDemands.has(key)) continue;
    if (demands.length >= state.maxItems) break;
    state.attemptedDemands.add(key);
    demands.push(demand);
  }
  const cards = [];
  for (const task of steer.web_tasks) {
    if (state.attemptedCards.has(task.card_slug)) continue;
    if (cards.length >= state.maxCards) break;
    state.attemptedCards.add(task.card_slug);
    cards.push(task);
  }
  return { demands, cards };
}

function hasFreshWork(state, steer) {
  return (
    steer.candidate_demands.some(
      (demand) =>
        !state.attemptedDemands.has(demandFingerprint(demand)),
    ) ||
    (state.maxCards > 0 &&
      steer.web_tasks.some(
        (task) => !state.attemptedCards.has(task.card_slug),
      ))
  );
}

async function processResearch(runtime, router, slug, meta) {
  const state = createState(slug, meta);
  runtime.log(
    `${slug}: Topic ${
      meta.maxRounds === 0
        ? "recall-only"
        : `up to ${meta.maxRounds} research rounds`
    }`,
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
  if (
    recallEdge === "failed" &&
    meta.maxRounds === 0 &&
    !state.cards.length
  )
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
  if (
    !requests.length &&
    meta.maxRounds === 0 &&
    !state.cards.length
  )
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
  if (
    !state.members.length &&
    meta.maxRounds === 0 &&
    !state.cards.length
  )
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
      0,
      state.members,
      "refresh",
      [],
      meta.maxRounds === 0
        ? `${slug}:steer:r0-close`
        : `${slug}:steer:r0-plan`,
    );
    if (planningSteer.terminal) return planningSteer.terminal;
  }

  let currentSteer = planningSteer.receipt;
  let partialRounds = false;
  for (
    let round = 1;
    round <= state.maxRounds && state.signal !== "saturated";
    round += 1
  ) {
    const work = selectRoundWork(state, currentSteer);
    if (!work.demands.length && !work.cards.length) {
      state.deadEnd = true;
      break;
    }
    state.rounds = round;
    const [materialRound, cardRound] = await runtime.parallel([
      () =>
        runMaterialRound(
          runtime,
          router,
          state,
          work.demands,
          round,
        ),
      () => runWebcardRound(runtime, state, work.cards, round),
    ]);
    if (materialRound.terminal) return materialRound.terminal;
    if (cardRound.terminal) return cardRound.terminal;
    partialRounds =
      partialRounds || materialRound.partial || cardRound.partial;
    const next = await runSteer(
      runtime,
      state,
      round,
      state.members,
      "refresh",
      [],
      `${slug}:steer:r${round}-close`,
    );
    if (next.terminal) return next.terminal;
    currentSteer = next.receipt;
    const fresh = hasFreshWork(state, currentSteer);
    state.deadEnd = state.signal === "saturated" || !fresh;
    runtime.log(
      `${slug}: round ${round} complete; ${state.members.length} materials / ${state.cards.length} cards; ${
        state.deadEnd ? "converged" : "more work proposed"
      }`,
    );
    if (state.deadEnd) break;
  }

  if (
    state.rounds === state.maxRounds &&
    state.maxRounds > 0 &&
    state.signal !== "saturated" &&
    hasFreshWork(state, currentSteer)
  )
    state.deadEnd = false;

  const evidence = state.members.length + state.cards.length;
  if (!evidence)
    return terminal(
      state,
      state.final
        ? state.rounds
          ? "all_failed"
          : "no_works"
        : "needs_seeds",
      state.final ? "failed" : "needs_input",
      state.rounds ? "material-join" : "steer",
      operationFailure(
        state.final
          ? state.rounds
            ? "topic.all_failed"
            : "topic.no_works"
          : "topic.needs_seeds",
        "topic.join",
        "known",
        state.rounds
          ? "the bounded rounds produced no usable material or evidence card"
          : "recall and steering produced no usable evidence",
      ),
      { suggested_queries: state.suggestedQueries },
    );
  if (evidence < state.minItems && !state.final)
    return terminal(
      state,
      "needs_seeds",
      "needs_input",
      "membership",
      operationFailure(
        "topic.needs_seeds",
        "topic.join",
        "known",
        "the combined material and card evidence is below the minimum budget",
      ),
      {
        collected: state.members.length,
        cards: state.cards.length,
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
          "topic.audit",
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
    ...state.cards.map((card) => ({
      role: "evidence_card",
      path: card.path,
      exists: true,
      producer: "topic.webcard",
    })),
  ];
  const partial =
    partialRounds ||
    state.recallFailed ||
    state.discoveryFailures.length > 0 ||
    state.cardFailures.length > 0 ||
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

export async function processTopic(
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
    () => processResearch(runtime, router, slug, validation.meta),
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
