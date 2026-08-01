import { defineOperation } from "../define.mjs";
import { cardPath, validCardSlug } from "../steer.mjs";

const SLUG_PATTERN = "^[a-z0-9][a-z0-9-]{0,79}$";
const SUBQUESTION_PATTERN = "^sq-[a-z0-9][a-z0-9-]{0,76}$";

const CARD_SLUG_SCHEMA = {
  type: "string",
  minLength: 2,
  maxLength: 80,
  pattern: SLUG_PATTERN,
};

const OUTLINE_ITEM_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["kind", "slug", "role"],
  properties: {
    kind: { type: "string", enum: ["book", "paper", "talk"] },
    slug: {
      type: "string",
      minLength: 1,
      maxLength: 80,
      pattern: SLUG_PATTERN,
    },
    role: {
      type: "string",
      enum: ["evidence", "theory", "method", "context"],
    },
  },
};

const SUBQUESTION_SCHEMA = {
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
      pattern: SUBQUESTION_PATTERN,
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
      items: OUTLINE_ITEM_SCHEMA,
    },
    cards: {
      type: "array",
      maxItems: 50,
      items: CARD_SLUG_SCHEMA,
    },
  },
};

const CANDIDATE_DEMAND_SCHEMA = {
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
      pattern: SUBQUESTION_PATTERN,
    },
    role: {
      type: "string",
      enum: ["evidence", "theory", "method", "context"],
    },
    reason: { type: "string", minLength: 1, maxLength: 1000 },
  },
};

const WEB_TASK_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["subq", "query", "note", "card_slug"],
  properties: {
    subq: {
      type: "string",
      minLength: 4,
      maxLength: 80,
      pattern: SUBQUESTION_PATTERN,
    },
    query: { type: "string", minLength: 1, maxLength: 500 },
    note: { type: "string", minLength: 1, maxLength: 1000 },
    card_slug: CARD_SLUG_SCHEMA,
  },
};

const steerRefs = ({
  materialKey,
  researchKey,
  topicSlug,
  query,
  memberRefs,
  mode,
  diagnostics,
}) => ({
  materialKey,
  researchKey,
  topicSlug,
  query,
  memberRefs: memberRefs.map(({ kind, slug, path }) => ({
    kind,
    slug,
    path,
  })),
  inputPaths: memberRefs.map(({ path }) => path),
  outputPath: `vault/topics/${topicSlug}/02-outline.md`,
  mode,
  diagnostics: mode === "repair" ? diagnostics : [],
});

const steerPayload = (refs) => ({
  required: [
    "research_key",
    "member_refs",
    "input_paths",
    "output_path",
    "signal",
    "subquestions",
    "candidate_demands",
    "web_tasks",
    "dirty",
    "suggested_queries",
  ],
  properties: {
    research_key: { const: refs.researchKey },
    member_refs: { const: refs.memberRefs },
    input_paths: { const: refs.inputPaths },
    output_path: { const: refs.outputPath },
    signal: {
      type: "string",
      enum: ["continue", "needs_seeds", "saturated"],
    },
    subquestions: {
      type: "array",
      minItems: 1,
      maxItems: 6,
      items: SUBQUESTION_SCHEMA,
    },
    candidate_demands: {
      type: "array",
      maxItems: 12,
      items: CANDIDATE_DEMAND_SCHEMA,
    },
    web_tasks: {
      type: "array",
      maxItems: 6,
      items: WEB_TASK_SCHEMA,
    },
    dirty: {
      type: "array",
      maxItems: 6,
      items: {
        type: "string",
        minLength: 4,
        maxLength: 80,
        pattern: SUBQUESTION_PATTERN,
      },
    },
    suggested_queries: {
      type: "array",
      maxItems: 6,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
  },
});

const steerTerminalPayloads = ({ mode }) => ({
  complete: {
    required: ["action"],
    properties: {
      action: { type: "string", enum: [mode, "reconciled"] },
    },
  },
});

const webcardRefs = ({
  materialKey,
  topicSlug,
  topic,
  task,
  subquestions = [],
}) => {
  const subquestion =
    subquestions.find((item) => item && item.id === task.subq) || {};
  const existingCards = [
    ...new Set(
      subquestions
        .flatMap((item) => (item && item.cards) || [])
        .filter(validCardSlug),
    ),
  ];
  return {
    materialKey,
    topicSlug,
    topic,
    subq: task.subq,
    subquestion: subquestion.question || task.subq,
    query: task.query,
    note: task.note || "",
    cardSlug: task.card_slug,
    cardPath: cardPath(topicSlug, task.card_slug),
    existingCards,
  };
};

const webcardPayload = ({ cardPath: output, subq }) => ({
  required: [
    "card_path",
    "subq",
    "card_status",
    "wrote_card",
    "card_available",
    "title",
    "objects",
    "sources",
    "evidence",
    "note",
  ],
  properties: {
    card_path: { const: output },
    subq: { const: subq },
    card_status: {
      type: "string",
      enum: ["ok", "unchanged", "empty"],
    },
    wrote_card: { type: "boolean" },
    card_available: { type: "boolean" },
    title: { type: ["string", "null"], maxLength: 500 },
    objects: { type: "integer", minimum: 0 },
    sources: { type: "integer", minimum: 0 },
    evidence: {
      type: ["string", "null"],
      enum: ["confirmed", "single-source", "disputed", null],
    },
    note: { type: "string", maxLength: 2000 },
  },
});

const completeWebcard = (receipt) => {
  if (receipt.card_status === "ok")
    return receipt.wrote_card && receipt.card_available;
  if (receipt.card_status === "unchanged")
    return !receipt.wrote_card && receipt.card_available;
  return (
    receipt.card_status === "empty" &&
    !receipt.wrote_card &&
    !receipt.card_available &&
    receipt.title === null &&
    receipt.objects === 0 &&
    receipt.sources === 0 &&
    receipt.evidence === null &&
    receipt.note.length > 0
  );
};

export const topicOperationRows = [
  {
    operation: "topic.steer",
    stage: "Search",
    effect: "writer",
    agentType: "quasi:steer-agent",
    refs: steerRefs,
    payloadProperties: steerPayload,
    terminalPayloads: steerTerminalPayloads,
    complete: (receipt, context) =>
      receipt.output_path ===
      `vault/topics/${context.topicSlug}/02-outline.md`,
    envelope: (_context, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "topic.steer",
      stage: "Search",
      material_key: refs.materialKey,
      effect: "writer",
      objective:
        "Reconcile and update the exact Topic outline, then return bounded sub-question-targeted material and web evidence demands.",
      research_key: refs.researchKey,
      topic_slug: refs.topicSlug,
      query: refs.query,
      members: refs.memberRefs,
      input_paths: refs.inputPaths,
      output: { role: "outline", path: refs.outputPath },
      mode: refs.mode,
      overwrite: refs.mode !== "create",
      repair_diagnostics: refs.diagnostics,
      strict_recall_only: true,
      scope:
        "Read only the exact member and outline paths in this request; write only output.path and never dispatch the suggested demands.",
    }),
  },
  {
    operation: "topic.webcard",
    stage: "Search",
    effect: "writer",
    agentType: "quasi:webcard-agent",
    refs: webcardRefs,
    payloadProperties: webcardPayload,
    complete: completeWebcard,
    envelope: (_context, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "topic.webcard",
      stage: "Search",
      material_key: refs.materialKey,
      effect: "writer",
      objective:
        "Investigate one bounded web evidence task and establish at most one verified evidence card at the exact output path.",
      topic: { slug: refs.topicSlug, description: refs.topic },
      subquestion: { id: refs.subq, question: refs.subquestion },
      web_task: {
        subq: refs.subq,
        query: refs.query,
        note: refs.note,
        card_slug: refs.cardSlug,
      },
      exact_output: refs.cardPath,
      existing_cards: refs.existingCards,
      capabilities: [
        "quasi-search kagi search --format json ...",
        "WebFetch only the exact URLs returned by that search",
        "Read, Write, or Edit only exact_output",
      ],
      completion: {
        verified:
          "Return complete with card_status=ok and wrote_card=true only after publishing a verified new or updated exact_output.",
        unchanged:
          "Return complete with card_status=unchanged, wrote_card=false, and card_available=true when the existing exact card needs no material change.",
        empty:
          "When no verifiable evidence is available, do not write a card; return complete with card_status=empty, wrote_card=false, card_available=false, null evidence fields, zero counts, and a non-empty note.",
      },
      scope:
        "Never write an unverified or empty card and never write any path other than exact_output.",
    }),
  },
];

export const topicOperations = Object.fromEntries(
  topicOperationRows.map((row) => [row.operation, defineOperation(row)]),
);

export const topicSteer = topicOperations["topic.steer"];
export const topicWebcard = topicOperations["topic.webcard"];
