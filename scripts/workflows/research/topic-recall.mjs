import {
  TOPIC_DISCOVER_BOOK_SCHEMA,
  TOPIC_DISCOVER_PAPER_SCHEMA,
  TOPIC_RECALL_SCHEMA,
  TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
  topicDiscoverBookOperationPrompt,
  topicDiscoverPaperOperationPrompt,
  topicRecallOperationPrompt as topicRecallPrompt,
  topicResolveMembershipOperationPrompt as topicResolveMembershipPrompt,
} from "../operations/acquire.mjs";
import {
  TOPIC_AUDIT_LEGACY_SCHEMA as TOPIC_AUDIT_SCHEMA,
  topicAuditLegacyPrompt,
} from "../operations/audit.mjs";
import {
  TOPIC_OVERVIEW_SYNTHESISE_SCHEMA,
  TOPIC_RESOURCES_SYNTHESISE_SCHEMA,
  topicOverviewSynthesiseOperationPrompt as topicOverviewSynthesisePrompt,
  topicResourcesSynthesiseOperationPrompt as topicResourcesSynthesisePrompt,
} from "../operations/synthesise.mjs";
import {
  TOPIC_STEER_SCHEMA as TOPIC_STEER_OPERATION_SCHEMA,
  topicSteerOperationPrompt,
} from "../operations/steer.mjs";

const RESEARCH_RECEIPT_VERSION =
  "quasi.research.topic.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const KINDS = new Set(["book", "paper", "talk"]);

const exactKeys = (value, keys) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const optionalText = (value, max) =>
  value === null || validText(value, 1, max);

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

function validFailure(failure, key, outcome) {
  return !!(
    exactKeys(failure, [
      "code",
      "operation_key",
      "outcome",
      "retryable",
      "message",
    ]) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === key &&
    failure.outcome === outcome &&
    failure.retryable === false &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

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

function validRecalledItem(item) {
  return !!(
    exactKeys(item, ["kind", "slug", "path"]) &&
    KINDS.has(item.kind) &&
    SLUG.test(item.slug) &&
    (item.path === null ||
      item.path === expectedPath(item.kind, item.slug))
  );
}

function strictRecall(receipt, state) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "query",
      "max_items",
      "items",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.topic.recall.receipt/0.1" ||
    receipt.key !== "topic.recall" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    receipt.query !== state.desc ||
    receipt.max_items !== state.maxItems ||
    !Array.isArray(receipt.items) ||
    receipt.items.length > state.maxItems ||
    receipt.items.some((item) => !validRecalledItem(item)) ||
    new Set(
      receipt.items.map((item) => `${item.kind}:${item.slug}`),
    ).size !== receipt.items.length
  )
    return false;
  if (receipt.status === "succeeded")
    return receipt.failure === null;
  if (receipt.status === "failed")
    return (
      receipt.items.length === 0 &&
      validFailure(receipt.failure, "topic.recall", "known")
    );
  return (
    receipt.status === "blocked" &&
    receipt.items.length === 0 &&
    validFailure(receipt.failure, "topic.recall", "unknown")
  );
}

function expectedPath(kind, slug) {
  if (kind === "book")
    return `vault/books/${slug}/00-overview.md`;
  if (kind === "paper")
    return `vault/papers/${slug}.md`;
  return `vault/talks/${slug}/talk.md`;
}

function strictMembership(
  receipt,
  state,
  requests,
  allowAlias = false,
) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "requests",
      "resolved",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.topic.resolve-membership.receipt/0.1" ||
    receipt.key !== "topic.resolve-membership" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    !Array.isArray(receipt.requests) ||
    !Array.isArray(receipt.resolved) ||
    receipt.requests.length !== requests.length ||
    !requests.every((request, index) => {
      const echoed = receipt.requests[index];
      return (
        exactKeys(echoed, ["kind", "slug"]) &&
        echoed.kind === request.kind &&
        echoed.slug === request.slug
      );
    })
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.resolved.length === 0 &&
      validFailure(
        receipt.failure,
        "topic.resolve-membership",
        "known",
      )
    );
  if (receipt.status === "blocked")
    return (
      receipt.resolved.length === 0 &&
      validFailure(
        receipt.failure,
        "topic.resolve-membership",
        "unknown",
      )
    );
  if (
    receipt.status !== "succeeded" ||
    receipt.failure !== null ||
    receipt.resolved.length !== requests.length
  )
    return false;
  return requests.every((request, index) => {
    const row = receipt.resolved[index];
    if (
      !exactKeys(row, [
        "kind",
        "requested_slug",
        "resolved_slug",
        "path",
        "match",
      ]) ||
      row.kind !== request.kind ||
      row.requested_slug !== request.slug
    )
      return false;
    if (row.resolved_slug === null)
      return row.path === null && row.match === null;
    if (
      !SLUG.test(row.resolved_slug) ||
      row.path !== expectedPath(row.kind, row.resolved_slug) ||
      !validText(row.match, 1, 100)
    )
      return false;
    return allowAlias
      ? true
      : row.resolved_slug === request.slug &&
          row.match === "slug";
  });
}

function validSubquestion(value) {
  return !!(
    exactKeys(value, [
      "id",
      "question",
      "coverage",
      "channel",
      "dossier",
      "page",
      "theory_used",
      "items",
      "cards",
    ]) &&
    /^sq-[a-z0-9][a-z0-9-]{0,76}$/.test(value.id) &&
    validText(value.question, 1, 500) &&
    ["gap", "thin", "covered", "saturated"].includes(
      value.coverage,
    ) &&
    ["academic", "web", "mixed"].includes(value.channel) &&
    typeof value.dossier === "boolean" &&
    (value.page === null ||
      /^[0-9]{2}-[a-z0-9][a-z0-9-]*\.md$/.test(
        value.page,
      )) &&
    Number.isInteger(value.theory_used) &&
    value.theory_used >= 0 &&
    value.theory_used <= 3 &&
    Array.isArray(value.items) &&
    value.items.length <= 50 &&
    value.items.every(
      (item) =>
        exactKeys(item, ["kind", "slug", "role"]) &&
        KINDS.has(item.kind) &&
        SLUG.test(item.slug) &&
        ["evidence", "theory", "method", "context"].includes(
          item.role,
        ),
    ) &&
    Array.isArray(value.cards) &&
    value.cards.length <= 50 &&
    value.cards.every((card) => SLUG.test(card))
  );
}

function validCandidate(value) {
  return !!(
    exactKeys(value, [
      "kind",
      "query",
      "subq",
      "role",
      "reason",
    ]) &&
    ["book", "paper"].includes(value.kind) &&
    validText(value.query, 1, 500) &&
    /^sq-[a-z0-9][a-z0-9-]{0,76}$/.test(value.subq) &&
    ["evidence", "theory", "method", "context"].includes(
      value.role,
    ) &&
    validText(value.reason, 1, 1000)
  );
}

function sameDemand(left, right) {
  return (
    exactKeys(left, ["kind", "query", "subq", "role", "reason"]) &&
    exactKeys(right, ["kind", "query", "subq", "role", "reason"]) &&
    ["kind", "query", "subq", "role", "reason"].every(
      (key) => left[key] === right[key],
    )
  );
}

function validDiscoveredCandidate(candidate, kind) {
  if (!candidate || typeof candidate !== "object")
    return false;
  if (kind === "book")
    return !!(
      exactKeys(candidate, [
        "kind",
        "slug",
        "title",
        "authors",
        "year",
        "isbn",
        "publisher",
        "category",
        "confidence",
      ]) &&
      candidate.kind === "book" &&
      SLUG.test(candidate.slug) &&
      validText(candidate.title, 1, 1000) &&
      Array.isArray(candidate.authors) &&
      candidate.authors.length > 0 &&
      candidate.authors.length <= 32 &&
      candidate.authors.every((author) =>
        validText(author, 1, 500),
      ) &&
      Number.isInteger(candidate.year) &&
      candidate.year >= 1 &&
      candidate.year <= 9999 &&
      (candidate.isbn === null ||
        validText(candidate.isbn, 1, 64)) &&
      validText(candidate.publisher, 1, 500) &&
      [
        "monograph",
        "edited-volume",
        "handbook",
        "other",
      ].includes(candidate.category) &&
      ["high", "medium"].includes(candidate.confidence)
    );
  return !!(
    exactKeys(candidate, [
      "kind",
      "slug",
      "title",
      "authors",
      "year",
      "doi",
      "oa_url",
      "url",
      "journal",
      "confidence",
    ]) &&
    candidate.kind === "paper" &&
    SLUG.test(candidate.slug) &&
    validText(candidate.title, 1, 1000) &&
    Array.isArray(candidate.authors) &&
    candidate.authors.length > 0 &&
    candidate.authors.length <= 32 &&
    candidate.authors.every((author) =>
      validText(author, 1, 500),
    ) &&
    Number.isInteger(candidate.year) &&
    candidate.year >= 1 &&
    candidate.year <= 9999 &&
    ["doi", "oa_url", "url"].every(
      (key) =>
        candidate[key] === null ||
        validText(candidate[key], 1, key === "doi" ? 500 : 2048),
    ) &&
    validText(candidate.journal, 1, 1000) &&
    ["high", "medium"].includes(candidate.confidence)
  );
}

function strictDiscovery(
  receipt,
  state,
  demandId,
  demand,
) {
  const key = `topic.discover-${demand.kind}`;
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "demand_id",
      "demand",
      "candidate",
      "failure",
    ]) ||
    receipt.schema_version !==
      `quasi.operation.${key}.receipt/0.1` ||
    receipt.key !== key ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    receipt.demand_id !== demandId ||
    !sameDemand(receipt.demand, demand)
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      validDiscoveredCandidate(receipt.candidate, demand.kind)
    );
  if (receipt.candidate !== null) return false;
  if (receipt.status === "failed")
    return validFailure(receipt.failure, key, "known");
  return (
    receipt.status === "blocked" &&
    validFailure(receipt.failure, key, "unknown")
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
  const target = expectedPath(demand.kind, demand.id);
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
  const target = expectedPath(demand.kind, demand.id);
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

function validWebTask(value) {
  return !!(
    exactKeys(value, [
      "subq",
      "card_slug",
      "query",
      "note",
    ]) &&
    /^sq-[a-z0-9][a-z0-9-]{0,76}$/.test(value.subq) &&
    SLUG.test(value.card_slug) &&
    validText(value.query, 1, 500) &&
    validText(value.note, 1, 1000)
  );
}

function strictSteer(
  receipt,
  state,
  memberRefs,
  inputPaths,
  mode,
) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "member_refs",
      "input_paths",
      "output_path",
      "action",
      "signal",
      "subquestions",
      "candidate_demands",
      "web_tasks",
      "dirty",
      "suggested_queries",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.topic.steer.receipt/0.1" ||
    receipt.key !== "topic.steer" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    !Array.isArray(receipt.member_refs) ||
    receipt.member_refs.length !== memberRefs.length ||
    !memberRefs.every((member, index) => {
      const echoed = receipt.member_refs[index];
      return (
        exactKeys(echoed, ["kind", "slug", "path"]) &&
        echoed.kind === member.kind &&
        echoed.slug === member.slug &&
        echoed.path === member.path
      );
    }) ||
    !sameStrings(receipt.input_paths, inputPaths) ||
    receipt.output_path !== state.paths.outline ||
    !["create", "refresh", "repair", "reconciled"].includes(
      receipt.action,
    ) ||
    !["continue", "needs_seeds", "saturated"].includes(
      receipt.signal,
    ) ||
    !Array.isArray(receipt.subquestions) ||
    receipt.subquestions.length < 1 ||
    receipt.subquestions.length > 6 ||
    receipt.subquestions.some(
      (subquestion) => !validSubquestion(subquestion),
    ) ||
    !Array.isArray(receipt.candidate_demands) ||
    receipt.candidate_demands.length > 12 ||
    receipt.candidate_demands.some(
      (candidate) => !validCandidate(candidate),
    ) ||
    !Array.isArray(receipt.web_tasks) ||
    receipt.web_tasks.length > 6 ||
    receipt.web_tasks.some((task) => !validWebTask(task)) ||
    !Array.isArray(receipt.dirty) ||
    receipt.dirty.length > 6 ||
    receipt.dirty.some(
      (id) => !/^sq-[a-z0-9][a-z0-9-]{0,76}$/.test(id),
    ) ||
    !Array.isArray(receipt.suggested_queries) ||
    receipt.suggested_queries.length > 6 ||
    receipt.suggested_queries.some(
      (query) => !validText(query, 1, 500),
    )
  )
    return false;
  const actionOk =
    mode === "create"
      ? ["create", "reconciled"].includes(receipt.action)
      : mode === "refresh"
        ? ["refresh", "reconciled"].includes(receipt.action)
        : ["repair", "reconciled"].includes(receipt.action);
  if (receipt.status === "succeeded")
    return actionOk && receipt.failure === null;
  if (receipt.status === "failed")
    return validFailure(
      receipt.failure,
      "topic.steer",
      "known",
    );
  return (
    receipt.status === "blocked" &&
    validFailure(
      receipt.failure,
      "topic.steer",
      "unknown",
    )
  );
}

function strictSynthesis(
  receipt,
  state,
  key,
  inputPaths,
  outputPath,
  role,
  mode,
) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "member_refs",
      "input_paths",
      "outline_path",
      "output_path",
      "artifact_roles",
      "action",
      "members_analyzed",
      "failure",
    ]) ||
    receipt.schema_version !==
      `quasi.operation.${key}.receipt/0.1` ||
    receipt.key !== key ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    !Array.isArray(receipt.member_refs) ||
    receipt.member_refs.length !== state.members.length ||
    !state.members.every((member, index) => {
      const echoed = receipt.member_refs[index];
      return (
        exactKeys(echoed, ["kind", "slug", "path"]) &&
        echoed.kind === member.kind &&
        echoed.slug === member.slug &&
        echoed.path === member.path
      );
    }) ||
    !sameStrings(receipt.input_paths, inputPaths) ||
    receipt.outline_path !== state.paths.outline ||
    receipt.output_path !== outputPath ||
    !sameStrings(receipt.artifact_roles, [role]) ||
    !["create", "repair", "reconciled"].includes(
      receipt.action,
    ) ||
    !Number.isInteger(receipt.members_analyzed) ||
    receipt.members_analyzed < 0
  )
    return false;
  const actionOk =
    mode === "create"
      ? ["create", "reconciled"].includes(receipt.action)
      : ["repair", "reconciled"].includes(receipt.action);
  if (receipt.status === "succeeded")
    return (
      actionOk &&
      receipt.failure === null &&
      (receipt.action === "reconciled"
        ? receipt.members_analyzed === 0
        : receipt.members_analyzed === state.members.length)
    );
  if (receipt.status === "failed")
    return validFailure(receipt.failure, key, "known");
  return (
    receipt.status === "blocked" &&
    validFailure(receipt.failure, key, "unknown")
  );
}

function strictAudit(receipt, state, target) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "research_key",
      "target_path",
      "remaining_violations",
      "escalated",
      "mutated_paths",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.topic.audit.legacy.receipt/0.1" ||
    receipt.key !== "topic.audit.legacy" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.research_key !== state.researchKey ||
    receipt.target_path !== target ||
    !Number.isInteger(receipt.remaining_violations) ||
    receipt.remaining_violations < 0 ||
    !Array.isArray(receipt.escalated) ||
    !Array.isArray(receipt.mutated_paths) ||
    receipt.escalated.some(
      (item) =>
        !exactKeys(item, ["path", "kind", "reason"]) ||
        !validText(item.path, 1, 2048) ||
        !validText(item.kind, 1, 200) ||
        !validText(item.reason, 1, 4000),
    ) ||
    receipt.mutated_paths.some(
      (path) => !validText(path, 1, 2048),
    )
  )
    return false;
  if (receipt.status === "clean")
    return (
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0 &&
      receipt.failure === null
    );
  if (receipt.status === "partial")
    return (
      receipt.remaining_violations > 0 &&
      receipt.escalated.length ===
        receipt.remaining_violations &&
      receipt.failure === null
    );
  return (
    receipt.status === "error" &&
    receipt.remaining_violations === 0 &&
    receipt.escalated.length === 0 &&
    (validFailure(
      receipt.failure,
      "topic.audit.legacy",
      "known",
    ) ||
      validFailure(
        receipt.failure,
        "topic.audit.legacy",
        "unknown",
      ))
  );
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

function operationOptions(key, effect, roles) {
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
  const receipt = await runtime.runOperation(
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
      phase: "Topic",
      agentType: "quasi:steer-agent",
      label,
      schema: TOPIC_STEER_OPERATION_SCHEMA,
    },
    operationOptions("topic.steer", "writer", ["outline"]),
  );
  state.operations.push(receipt);
  state.budgets.steer.used += 1;
  if (
    !strictSteer(
      receipt,
      state,
      members,
      inputPaths,
      mode,
    )
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
  const receipt = await runtime.runOperation(
    prompt,
    {
      phase: "Topic",
      agentType: "quasi:synthesis-agent",
      label,
      schema: overview
        ? TOPIC_OVERVIEW_SYNTHESISE_SCHEMA
        : TOPIC_RESOURCES_SYNTHESISE_SCHEMA,
    },
    operationOptions(key, "writer", [role]),
  );
  state.operations.push(receipt);
  state.budgets.synthesis.used += 1;
  if (
    !strictSynthesis(
      receipt,
      state,
      key,
      inputPaths,
      output,
      role,
      mode,
    )
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
  const receipt = await runtime.runOperation(
    topicAuditLegacyPrompt(state.researchKey, target, pass),
    {
      phase: "Topic",
      agentType: "quasi:audit-agent",
      label: `audit-topic:${pass}:${target}`,
      schema: TOPIC_AUDIT_SCHEMA,
    },
    operationOptions(
      "topic.audit.legacy",
      "writer",
      ["topic_product"],
    ),
  );
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (!strictAudit(receipt, state, target))
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
  if (receipt.status === "error")
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
  const discoveryReceipts = await runtime.parallel(
    ledger.map(({ demand, demandId }) => () => {
      const book = demand.kind === "book";
      return runtime.runOperation(
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
          phase: "Topic",
          agentType: "quasi:search-agent",
          label: `discover:${demandId}:${state.slug}`,
          schema: book
            ? TOPIC_DISCOVER_BOOK_SCHEMA
            : TOPIC_DISCOVER_PAPER_SCHEMA,
        },
        operationOptions(
          `topic.discover-${demand.kind}`,
          "readonly",
          [],
        ),
      );
    }),
  );
  state.operations.push(...discoveryReceipts);
  for (let index = 0; index < ledger.length; index += 1) {
    if (
      !strictDiscovery(
        discoveryReceipts[index],
        state,
        ledger[index].demandId,
        ledger[index].demand,
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
      receipt: discoveryReceipts[index],
    }))
    .filter(({ receipt }) => {
      if (receipt.status === "succeeded") return true;
      state.discoveryFailures.push(receipt.failure);
      return false;
    });
  if (!discoveries.length)
    return { partial: state.discoveryFailures.length > 0 };

  const requests = discoveries.map(({ receipt }) => ({
    kind: receipt.candidate.kind,
    slug: receipt.candidate.slug,
  }));
  const membership = await runtime.runOperation(
    topicResolveMembershipPrompt(state.researchKey, requests),
    {
      phase: "Topic",
      agentType: "general-purpose",
      label: `resolve-discovered:${state.slug}:r1`,
      schema: TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
    },
    operationOptions(
      "topic.resolve-membership",
      "readonly",
      [],
    ),
  );
  state.operations.push(membership);
  if (
    !strictMembership(
      membership,
      state,
      requests,
      true,
    )
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
  if (membership.status !== "succeeded")
    return {
      terminal: terminal(
        state,
        membership.status === "blocked"
          ? "blocked"
          : "all_failed",
        membership.status === "blocked"
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
  const [recall, initialSteerResult] = await runtime.parallel([
    () =>
      runtime.runOperation(
        topicRecallPrompt(
          state.researchKey,
          state.desc,
          state.maxItems,
        ),
        {
          phase: "Topic",
          agentType: "general-purpose",
          label: `recall:${slug}`,
          schema: TOPIC_RECALL_SCHEMA,
        },
        operationOptions("topic.recall", "readonly", []),
      ),
    () =>
      runSteer(
        runtime,
        state,
        0,
        [],
        "create",
        [],
        `steer:${slug}:r0`,
      ),
  ]);
  state.operations.unshift(recall);
  if (!strictRecall(recall, state)) {
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
  if (recall.status === "blocked")
    return terminal(
      state,
      "blocked",
      "blocked",
      "recall",
      recall.failure,
    );
  if (recall.status === "failed" && meta.maxRounds === 0)
    return terminal(
      state,
      "no_works",
      "failed",
      "recall",
      recall.failure,
    );
  if (recall.status === "failed") {
    state.recallFailed = true;
    state.warnings.push(
      `Topic recall failed before the material round: ${recall.failure.code}`,
    );
  }

  const requests =
    recall.status === "succeeded" ? recall.items : [];
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
    const membership = await runtime.runOperation(
      topicResolveMembershipPrompt(state.researchKey, requests),
      {
        phase: "Topic",
        agentType: "general-purpose",
        label: `resolve-membership:${slug}`,
        schema: TOPIC_RESOLVE_MEMBERSHIP_SCHEMA,
      },
      operationOptions(
        "topic.resolve-membership",
        "readonly",
        [],
      ),
    );
    state.operations.push(membership);
    if (!strictMembership(membership, state, requests)) {
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
    if (membership.status === "failed")
      return terminal(
        state,
        "no_works",
        "failed",
        "membership",
        membership.failure,
      );
    if (membership.status === "blocked")
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
        ? `steer:${slug}:r1-close`
        : `steer:${slug}:r1-plan`,
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
        `steer:${slug}:r1-close`,
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
        `synth-overview:${slug}`,
      ),
    () =>
      runSynthesis(
        runtime,
        state,
        "resources",
        "create",
        [],
        `synth-resources:${slug}`,
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
            `repair-outline:${slug}`,
          );
        return runSynthesis(
          runtime,
          state,
          producer,
          "repair",
          result.diagnostics,
          `repair-${producer}:${slug}`,
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
  runtime.phase("Topic");
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
