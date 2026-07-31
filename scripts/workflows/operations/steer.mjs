const CARD_SLUG_PATTERN = "^[a-z0-9][a-z0-9-]*$";
const CARD_SLUG_SCHEMA = {
  type: "string",
  minLength: 2,
  maxLength: 80,
  pattern: CARD_SLUG_PATTERN,
};

export const STEER_SCHEMA = {
  type: "object",
  required: ["subquestions"],
  properties: {
    outline_written: { type: "boolean" },
    saturated: { type: "boolean" },
    subquestions: {
      type: "array",
      items: {
        type: "object",
        required: ["id", "coverage", "items", "cards"],
        properties: {
          id: { type: "string" },
          question: { type: "string" },
          coverage: { type: "string" },
          dossier: { type: "boolean" },
          page: { type: "string" },
          items: {
            type: "array",
            items: {
              type: "object",
              required: ["slug"],
              properties: {
                kind: { type: "string" },
                slug: { type: "string" },
                role: { type: "string" },
              },
            },
          },
          cards: { type: "array", items: CARD_SLUG_SCHEMA },
        },
      },
    },
    dirty: { type: "array", items: { type: "string" } },
    candidates: {
      type: "array",
      items: {
        type: "object",
        required: ["slug", "subq", "role"],
        properties: {
          kind: { type: "string" },
          slug: { type: "string" },
          title: { type: "string" },
          authors: { type: "array" },
          year: {},
          isbn: { type: "string" },
          doi: { type: "string" },
          oa_url: { type: "string" },
          journal: { type: "string" },
          subq: { type: "string" },
          role: { type: "string" },
        },
      },
    },
    web_tasks: {
      type: "array",
      items: {
        type: "object",
        required: ["subq", "query", "card_slug"],
        properties: {
          subq: { type: "string" },
          query: { type: "string" },
          note: { type: "string" },
          card_slug: CARD_SLUG_SCHEMA,
        },
      },
    },
    suggested_queries: { type: "array", items: { type: "string" } },
  },
};

export const itemPath = (item) =>
  item.kind === "book"
    ? `vault/books/${item.slug}/00-overview.md`
    : item.kind === "author"
      ? `vault/authors/${item.slug}.md`
      : item.kind === "talk"
        ? `vault/talks/${item.slug}/talk.md`
        : `vault/papers/${item.slug}.md`;

export const cardPath = (topicSlug, cardSlug) =>
  `vault/topics/${topicSlug}/cards/${cardSlug}.md`;

const CARD_SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;
export const validCardSlug = (card) =>
  typeof card === "string" &&
  card.length >= 2 &&
  card.length <= 80 &&
  CARD_SLUG_RE.test(card);

export const registered = (state) =>
  ((state && state.subquestions) || [])
    .flatMap((subquestion) => (subquestion && subquestion.cards) || [])
    .filter(validCardSlug);

export const pendingCards = (state, doneSlugs, limit) => {
  const used = new Set(doneSlugs);
  const tasks = [];
  let dropped = 0;
  for (const task of (state && state.web_tasks) || []) {
    if (
      !task ||
      !task.query ||
      !task.subq ||
      !validCardSlug(task.card_slug)
    )
      continue;
    if (used.has(task.card_slug)) continue;
    if (tasks.length >= limit) {
      dropped++;
      continue;
    }
    used.add(task.card_slug);
    tasks.push({
      subq: task.subq,
      query: task.query,
      note: task.note || "",
      card_slug: task.card_slug,
    });
  }
  return { tasks, dropped };
};

export const mergeItems = (subquestions, items) =>
  subquestions.map((subquestion) => {
    const merged = new Map(
      (subquestion.items || []).map((item) => [
        `${item.kind}:${item.slug}`,
        item,
      ]),
    );
    (items || [])
      .filter(
        (item) =>
          item.subq === subquestion.id && item.kind !== "author",
      )
      .forEach((item) =>
        merged.set(`${item.kind}:${item.slug}`, {
          kind: item.kind,
          slug: item.slug,
          role: item.role,
        }),
      );
    return { ...subquestion, items: [...merged.values()] };
  });

export const mergeCards = (subquestions, cards) =>
  subquestions.map((subquestion) => ({
    ...subquestion,
    cards: [
      ...new Set([
        ...(subquestion.cards || []),
        ...(cards || [])
          .filter((card) => card.subq === subquestion.id)
          .map((card) => card.card_slug),
      ]),
    ],
  }));

export function steerPrompt(
  slug,
  desc,
  round,
  snowSrc,
  seenSlugs,
  want,
  seeds,
  newCards,
) {
  const books = snowSrc
    .filter((item) => item.kind === "book")
    .map((item) => item.slug);
  const rest = snowSrc
    .filter((item) => item.kind !== "book")
    .map(itemPath);
  const members = snowSrc
    .filter((item) => item.subq)
    .map((item) => ({
      kind: item.kind,
      slug: item.slug,
      subq: item.subq,
      role: item.role,
    }));
  const cards = (newCards || []).map((card) => ({
    subq: card.subq,
    card_slug: card.card_slug,
    title: card.title,
    path: cardPath(slug, card.card_slug),
  }));
  return `topic_slug: ${slug}
topic: ${desc}
outline_path: vault/topics/${slug}/02-outline.md
round: ${round}
want: ${want}
seen_slugs: ${JSON.stringify(seenSlugs)}
snowball_book_slugs: ${JSON.stringify(books)}
snowball_paths: ${JSON.stringify(rest)}
snowball_members: ${JSON.stringify(members)}   # 已定向候选的 subq/role 原样并入成员表${cards.length ? `
new_cards: ${JSON.stringify(cards)}   # 本轮落地的证据卡,并入对应子问题的 cards(不是 items)` : ""}${seeds && seeds.length ? `
extra_queries: ${JSON.stringify(seeds)}   # 用户补的种子检索词,优先照这些搜` : ""}`;
}

// Strict Topic recall-only steering. The legacy STEER_SCHEMA and steerPrompt stay
// intentionally permissive for the rolling Topic Loop above.
const TOPIC_STEER_FAILURE_SCHEMA = {
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "code",
    "operation_key",
    "outcome",
    "retryable",
    "message",
  ],
  properties: {
    code: { type: "string", minLength: 1, maxLength: 200 },
    operation_key: { const: "topic.steer" },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: false },
    message: { type: ["string", "null"], maxLength: 4000 },
  },
};

const TOPIC_MEMBER_REF_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["kind", "slug", "path"],
  properties: {
    kind: { type: "string", enum: ["book", "paper", "talk"] },
    slug: {
      type: "string",
      minLength: 1,
      maxLength: 80,
      pattern: "^[a-z0-9][a-z0-9-]*$",
    },
    path: { type: "string", minLength: 1, maxLength: 2048 },
  },
};

const TOPIC_OUTLINE_ITEM_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["kind", "slug", "role"],
  properties: {
    kind: { type: "string", enum: ["book", "paper", "talk"] },
    slug: {
      type: "string",
      minLength: 1,
      maxLength: 80,
      pattern: "^[a-z0-9][a-z0-9-]*$",
    },
    role: {
      type: "string",
      enum: ["evidence", "theory", "method", "context"],
    },
  },
};

const TOPIC_SUBQUESTION_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "id",
    "question",
    "coverage",
    "channel",
    "dossier",
    "page",
    "theory_used",
    "items",
    "cards",
  ],
  properties: {
    id: {
      type: "string",
      minLength: 4,
      maxLength: 80,
      pattern: "^sq-[a-z0-9][a-z0-9-]*$",
    },
    question: { type: "string", minLength: 1, maxLength: 500 },
    coverage: {
      type: "string",
      enum: ["gap", "thin", "covered", "saturated"],
    },
    channel: { type: "string", enum: ["academic", "web", "mixed"] },
    dossier: { type: "boolean" },
    page: {
      type: ["string", "null"],
      maxLength: 120,
      pattern: "^[0-9]{2}-[a-z0-9][a-z0-9-]*\\.md$",
    },
    theory_used: { type: "integer", minimum: 0, maximum: 3 },
    items: {
      type: "array",
      maxItems: 50,
      items: TOPIC_OUTLINE_ITEM_SCHEMA,
    },
    cards: {
      type: "array",
      maxItems: 50,
      items: CARD_SLUG_SCHEMA,
    },
  },
};

const TOPIC_CANDIDATE_DEMAND_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["kind", "query", "subq", "role", "reason"],
  properties: {
    kind: { type: "string", enum: ["book", "paper"] },
    query: { type: "string", minLength: 1, maxLength: 500 },
    subq: {
      type: "string",
      minLength: 4,
      maxLength: 80,
      pattern: "^sq-[a-z0-9][a-z0-9-]*$",
    },
    role: {
      type: "string",
      enum: ["evidence", "theory", "method", "context"],
    },
    reason: { type: "string", minLength: 1, maxLength: 1000 },
  },
};

const TOPIC_WEB_TASK_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["subq", "query", "note", "card_slug"],
  properties: {
    subq: {
      type: "string",
      minLength: 4,
      maxLength: 80,
      pattern: "^sq-[a-z0-9][a-z0-9-]*$",
    },
    query: { type: "string", minLength: 1, maxLength: 500 },
    note: { type: "string", minLength: 1, maxLength: 1000 },
    card_slug: CARD_SLUG_SCHEMA,
  },
};

export const TOPIC_STEER_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.topic.steer.receipt/0.1",
    },
    key: { const: "topic.steer" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    research_key: { type: "string", minLength: 1, maxLength: 200 },
    member_refs: {
      type: "array",
      maxItems: 50,
      items: TOPIC_MEMBER_REF_SCHEMA,
    },
    input_paths: {
      type: "array",
      maxItems: 50,
      items: { type: "string", minLength: 1, maxLength: 2048 },
    },
    output_path: { type: "string", minLength: 1, maxLength: 2048 },
    action: {
      type: "string",
      enum: ["create", "refresh", "repair", "reconciled"],
    },
    signal: {
      type: "string",
      enum: ["continue", "needs_seeds", "saturated"],
    },
    subquestions: {
      type: "array",
      minItems: 1,
      maxItems: 6,
      items: TOPIC_SUBQUESTION_SCHEMA,
    },
    candidate_demands: {
      type: "array",
      maxItems: 12,
      items: TOPIC_CANDIDATE_DEMAND_SCHEMA,
    },
    web_tasks: {
      type: "array",
      maxItems: 6,
      items: TOPIC_WEB_TASK_SCHEMA,
    },
    dirty: {
      type: "array",
      maxItems: 6,
      items: {
        type: "string",
        minLength: 4,
        maxLength: 80,
        pattern: "^sq-[a-z0-9][a-z0-9-]*$",
      },
    },
    suggested_queries: {
      type: "array",
      maxItems: 6,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
    failure: TOPIC_STEER_FAILURE_SCHEMA,
  },
};

export function topicSteerOperationPrompt({
  researchKey,
  topicSlug,
  query,
  memberRefs,
  mode = "create",
  diagnostics = [],
}) {
  const output = `vault/topics/${topicSlug}/02-outline.md`;
  const repair = mode === "repair";
  const request = {
    schema_version: "quasi.operation.topic.steer.request/0.1",
    operation: "topic.steer",
    research_key: researchKey,
    topic_slug: topicSlug,
    query,
    members: memberRefs.map(({ kind, slug, path }) => ({
      kind,
      slug,
      path,
    })),
    input_paths: memberRefs.map(({ path }) => path),
    output: { role: "outline", path: output },
    mode,
    overwrite: mode === "refresh" || repair,
    repair_diagnostics: repair ? diagnostics : [],
    strict_recall_only: true,
  };
  return JSON.stringify(request, null, 2);
}

// Public graph alias: this names the strict receipt, not the legacy STEER_SCHEMA.
export const TOPIC_STEER_OPERATION_SCHEMA = TOPIC_STEER_SCHEMA;

// --- Topic steer receipt contract ------------------------------------------

import { exactKeys, validText } from "../runtime.mjs";

const SQ_ID = /^sq-[a-z0-9][a-z0-9-]{0,76}$/;
const STEER_ITEM_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const STEER_ITEM_KINDS = new Set(["book", "paper", "talk"]);

const validSubquestion = (value) =>
  !!(
    SQ_ID.test(value.id) &&
    validText(value.question, 1, 500) &&
    ["gap", "thin", "covered", "saturated"].includes(
      value.coverage,
    ) &&
    ["academic", "web", "mixed"].includes(value.channel) &&
    (value.page === null ||
      /^[0-9]{2}-[a-z0-9][a-z0-9-]*\.md$/.test(value.page)) &&
    Number.isInteger(value.theory_used) &&
    value.theory_used >= 0 &&
    value.theory_used <= 3 &&
    Array.isArray(value.items) &&
    value.items.length <= 50 &&
    value.items.every(
      (item) =>
        exactKeys(item, ["kind", "slug", "role"]) &&
        STEER_ITEM_KINDS.has(item.kind) &&
        STEER_ITEM_SLUG.test(item.slug) &&
        ["evidence", "theory", "method", "context"].includes(
          item.role,
        ),
    ) &&
    Array.isArray(value.cards) &&
    value.cards.length <= 50 &&
    value.cards.every((card) => STEER_ITEM_SLUG.test(card))
  );

const validCandidateDemand = (value) =>
  !!(
    ["book", "paper"].includes(value.kind) &&
    validText(value.query, 1, 500) &&
    SQ_ID.test(value.subq) &&
    ["evidence", "theory", "method", "context"].includes(
      value.role,
    ) &&
    validText(value.reason, 1, 1000)
  );

const validWebTask = (value) =>
  !!(
    SQ_ID.test(value.subq) &&
    STEER_ITEM_SLUG.test(value.card_slug) &&
    validText(value.query, 1, 500) &&
    validText(value.note, 1, 1000)
  );

export const TOPIC_STEER_CONTRACT = {
  schema: TOPIC_STEER_SCHEMA,
  echo: (receipt, context) =>
    receipt.research_key === context.state.researchKey &&
    receipt.member_refs.length ===
      context.memberRefs.length &&
    context.memberRefs.every((member, index) => {
      const echoed = receipt.member_refs[index];
      return (
        echoed.kind === member.kind &&
        echoed.slug === member.slug &&
        echoed.path === member.path
      );
    }) &&
    JSON.stringify(receipt.input_paths) ===
      JSON.stringify(context.inputPaths) &&
    receipt.output_path === context.state.paths.outline &&
    receipt.subquestions.length >= 1 &&
    receipt.subquestions.length <= 6 &&
    receipt.subquestions.every((subquestion) =>
      validSubquestion(subquestion),
    ) &&
    receipt.candidate_demands.length <= 12 &&
    receipt.candidate_demands.every((candidate) =>
      validCandidateDemand(candidate),
    ) &&
    receipt.web_tasks.length <= 6 &&
    receipt.web_tasks.every((task) => validWebTask(task)) &&
    receipt.dirty.length <= 6 &&
    receipt.dirty.every((id) => SQ_ID.test(id)) &&
    receipt.suggested_queries.length <= 6 &&
    receipt.suggested_queries.every((query) =>
      validText(query, 1, 500),
    ),
  statuses: {
    succeeded: (receipt, context) => {
      const actionOk =
        context.mode === "create"
          ? ["create", "reconciled"].includes(receipt.action)
          : context.mode === "refresh"
            ? ["refresh", "reconciled"].includes(receipt.action)
            : ["repair", "reconciled"].includes(receipt.action);
      return actionOk && receipt.failure === null;
    },
    failed: (receipt) =>
      !!receipt.failure &&
      receipt.failure.outcome === "known",
    blocked: (receipt) =>
      !!receipt.failure &&
      receipt.failure.outcome === "unknown",
  },
};
