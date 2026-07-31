import { cardPath, itemPath } from "./steer.mjs";
import { composedSchema } from "./extract.mjs";
import { BOOK_ARTIFACT_CONTRACT } from "../artifact-contracts/generated.mjs";

export const SY_SCHEMA = {
  type: "object",
  properties: {
    status: { type: "string" },
    inputs_analyzed: { type: "number" },
    chapters_analyzed: { type: "number" },
  },
};

export const BOOK_SYNTHESISE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_paths",
    "output_path",
    "artifact_roles",
    "action",
    "chapters_analyzed",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.book.synthesise.receipt/0.1",
    },
    key: { const: "book.synthesise" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_paths: {
      type: "array",
      minItems: 1,
      maxItems: 150,
      items: { type: "string" },
    },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "canonical" },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    chapters_analyzed: { type: "integer", minimum: 0 },
    failure: {
      type: ["object", "null"],
      additionalProperties: false,
      required: [
        "code",
        "operation_key",
        "outcome",
        "retryable",
      ],
      properties: {
        code: { type: "string" },
        operation_key: { const: "book.synthesise" },
        outcome: { type: "string", enum: ["known", "unknown"] },
        retryable: { const: false },
      },
    },
  },
};

export const AUTHOR_SYNTHESISE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_material_keys",
    "input_paths",
    "output_path",
    "artifact_roles",
    "action",
    "materials_analyzed",
    "failure",
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.author.synthesise.receipt/0.1",
    },
    key: { const: "author.synthesise" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_material_keys: {
      type: "array",
      minItems: 1,
      maxItems: 15,
      items: { type: "string" },
    },
    input_paths: {
      type: "array",
      minItems: 1,
      maxItems: 15,
      items: { type: "string" },
    },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "canonical" },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    materials_analyzed: { type: "integer", minimum: 0 },
    failure: {
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
        code: { type: "string" },
        operation_key: { const: "author.synthesise" },
        outcome: { type: "string", enum: ["known", "unknown"] },
        retryable: { const: false },
        message: { type: ["string", "null"] },
      },
    },
  },
};

const RECONCILE_CODE = "output_exists_requires_reconcile";

const knownOutcome = {
  type: "object",
  required: ["outcome"],
  properties: { outcome: { const: "known" } },
};
const unknownOutcome = {
  type: "object",
  required: ["outcome"],
  properties: { outcome: { const: "unknown" } },
};

// The author.synthesise writer matrix, exact ordered corpus echo, and the
// materials_analyzed count ride the schema as deep consts.
export const authorSynthesiseSchema = ({
  inputs,
  mode,
  output,
}) =>
  composedSchema(
    AUTHOR_SYNTHESISE_SCHEMA,
    {
      input_material_keys: {
        const: inputs.map((input) => input.material_key),
      },
      input_paths: {
        const: inputs.map((input) => input.path),
      },
      output_path: { const: output },
    },
    {
      succeeded: {
        properties: {
          status: { const: "succeeded" },
          failure: { type: "null" },
          materials_analyzed: { const: inputs.length },
          action:
            mode === "create"
              ? { const: "create" }
              : { enum: ["repair", "reconciled"] },
        },
      },
      failed: {
        properties: {
          status: { const: "failed" },
          action: { const: mode },
          failure: knownOutcome,
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          action: { const: mode },
          failure: unknownOutcome,
        },
      },
    },
  );

export const AUTHOR_SYNTHESISE_CONTRACT = {
  schema: AUTHOR_SYNTHESISE_SCHEMA,
};

const nonReconcileSynthFailure = (outcome) => ({
  type: "object",
  required: ["outcome", "code"],
  properties: {
    outcome: { const: outcome },
    code: { not: { const: RECONCILE_CODE } },
  },
});

// The book.synthesise matrix rides the schema; the typed create collision
// surfaces as the reconcile edge via the contract detector.
const bookSynthesiseBranches = (mode, count) =>
  mode === "create"
    ? {
        succeeded: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            chapters_analyzed: { const: count },
            action: { const: "create" },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "create" },
            failure: nonReconcileSynthFailure("known"),
          },
        },
        blocked_unknown: {
          properties: {
            status: { const: "blocked" },
            action: { const: "create" },
            failure: nonReconcileSynthFailure("unknown"),
          },
        },
        blocked_reconcile: {
          properties: {
            status: { const: "blocked" },
            action: { const: "reconciled" },
            failure: {
              type: "object",
              required: ["outcome", "code"],
              properties: {
                outcome: { const: "unknown" },
                code: { const: RECONCILE_CODE },
              },
            },
          },
        },
      }
    : {
        succeeded: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            chapters_analyzed: { const: count },
            action: { enum: ["repair", "reconciled"] },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "repair" },
            failure: nonReconcileSynthFailure("known"),
          },
        },
        blocked: {
          properties: {
            status: { const: "blocked" },
            action: { const: "repair" },
            failure: nonReconcileSynthFailure("unknown"),
          },
        },
      };

export const bookSynthesiseSchema = ({
  inputPaths,
  mode,
  output,
}) =>
  composedSchema(
    BOOK_SYNTHESISE_SCHEMA,
    {
      input_paths: { const: inputPaths },
      output_path: { const: output },
    },
    bookSynthesiseBranches(mode, inputPaths.length),
  );

export const BOOK_SYNTHESISE_CONTRACT = {
  schema: BOOK_SYNTHESISE_SCHEMA,
  reconcile: (receipt, context) =>
    context.mode === "create" &&
    receipt.status === "blocked" &&
    receipt.action === "reconciled",
};

export function bookSynthesiseOperationPrompt(
  slug,
  meta,
  inputPaths,
  mode = "create",
  diagnostics = [],
) {
  const output = `vault/books/${slug}/00-overview.md`;
  const repair = mode === "repair";
  const request = {
    schema_version:
      "quasi.operation.book.synthesise.request/0.1",
    operation: "book.synthesise",
    material_key: `book:${slug}`,
    inputs: inputPaths.map((path) => ({
      role: "chapter_canonical",
      path,
    })),
    output: { role: "canonical", path: output },
    identity: {
      title: meta.title,
      authors: meta.authors,
      year: meta.year,
      publisher: meta.publisher,
      isbn: meta.isbn || null,
      category: meta.category,
      confidence:
        meta.confidence === "verified" ? "verified" : "provided",
    },
    artifact_contract: BOOK_ARTIFACT_CONTRACT,
    frontmatter_seed: {
      type: "book",
      title: meta.title,
      authors: meta.authors,
      year: meta.year,
      publisher: meta.publisher,
      isbn: meta.isbn || null,
      category: meta.category,
    },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
  };
  return JSON.stringify(request, null, 2);
}

export const AUTHOR_SYNTHESIS_INSTRUCTIONS = `author-synthesis/1

- Use only the supplied author identity and actual canonical Book/Paper analyses.
- YAML: type=author, name=identity.full_name, themes derived from the corpus; omit an
  unsupported rating. H1 is identity.full_name. Required H2 order: 思想肖像, 学术轨迹,
  关键概念, 理论网络, 金句要点, 项目关联. Add 代表著作 when the corpus contains a
  Book. Preserve evidence type and do not invent a chronology or quotation.
- First mention of every supplied work carries a wikilink derived from its exact canonical
  path: Book [[id/00-overview|title]], Paper [[id|title]].`;

export function authorSynthesiseOperationPrompt(
  name,
  full,
  topic,
  inputs,
  mode = "create",
  diagnostics = [],
) {
  const output = `vault/authors/${name}.md`;
  const repair = mode === "repair";
  const request = {
    schema_version:
      "quasi.operation.author.synthesise.request/0.1",
    operation: "author.synthesise",
    prompt_pack: "author-synthesis/1",
    collection_key: `author:${name}`,
    inputs: inputs.map((input) => ({
      material_key: input.material_key,
      kind: input.kind,
      id: input.id,
      role: "canonical",
      path: input.path,
      title: input.title,
    })),
    input_material_keys: inputs.map(
      (input) => input.material_key,
    ),
    input_paths: inputs.map((input) => input.path),
    output: { role: "canonical", path: output },
    identity: {
      slug: name,
      full_name: full,
      topic,
    },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
    operation_instructions: AUTHOR_SYNTHESIS_INSTRUCTIONS,
  };
  return JSON.stringify(request, null, 2);
}

// Strict Topic recall-only synthesis Operations. The dossier/spine prompts below remain
// isolated for the not-yet-migrated rolling Topic Loop.
const TOPIC_SYNTHESIS_FAILURE_SCHEMA = (operationKey) => ({
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
    operation_key: { const: operationKey },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: false },
    message: { type: ["string", "null"], maxLength: 4000 },
  },
});

const TOPIC_SYNTHESIS_MEMBER_REF_SCHEMA = {
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

const topicSynthesiseSchema = (operationKey, outputRole) => ({
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
    "outline_path",
    "output_path",
    "artifact_roles",
    "action",
    "members_analyzed",
    "failure",
  ],
  properties: {
    schema_version: {
      const: `quasi.operation.${operationKey}.receipt/0.1`,
    },
    key: { const: operationKey },
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
      items: TOPIC_SYNTHESIS_MEMBER_REF_SCHEMA,
    },
    input_paths: {
      type: "array",
      maxItems: 50,
      items: { type: "string", minLength: 1, maxLength: 2048 },
    },
    outline_path: { type: "string", minLength: 1, maxLength: 2048 },
    output_path: { type: "string", minLength: 1, maxLength: 2048 },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: outputRole },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    members_analyzed: { type: "integer", minimum: 0, maximum: 50 },
    failure: TOPIC_SYNTHESIS_FAILURE_SCHEMA(operationKey),
  },
});

export const TOPIC_OVERVIEW_SYNTHESISE_SCHEMA = topicSynthesiseSchema(
  "topic.synthesise.overview",
  "overview",
);

export const TOPIC_RESOURCES_SYNTHESISE_SCHEMA = topicSynthesiseSchema(
  "topic.synthesise.resources",
  "resources",
);

const TOPIC_SYNTHESIS_INSTRUCTIONS = {
  overview: `Write a compact topic overview only. The frontmatter is exactly type: topic,
kind: overview, title: supplied topic. H1 is the supplied topic. Use the exact outline ordering
for a \"子问题地图\" and distinguish every supplied Book/Paper/Talk only through the supplied
canonical paths. Include evidence limits and gaps only when supported by the outline or supplied
products; do not invent web evidence, citations, members, cards, or a next graph action.`,
  resources: `Write a reading-resources page only. The frontmatter is exactly type: topic,
kind: resources, title: supplied topic. H1 is the supplied topic. Use the exact outline ordering
to group only the supplied Book/Paper/Talk member paths into a readable list; leave a clearly
marked gap where a subquestion has no supplied member. Do not invent web evidence, citations,
members, cards, or a next graph action.`,
};

function topicSynthesiseOperationPrompt({
  operation,
  outputRole,
  researchKey,
  topicSlug,
  topic,
  memberRefs,
  mode = "create",
  diagnostics = [],
}) {
  const output = `vault/topics/${topicSlug}/${
    outputRole === "overview" ? "00-overview.md" : "01-resources.md"
  }`;
  const outline = `vault/topics/${topicSlug}/02-outline.md`;
  const repair = mode === "repair";
  const request = {
    schema_version: `quasi.operation.${operation}.request/0.1`,
    operation,
    research_key: researchKey,
    topic_slug: topicSlug,
    topic,
    members: memberRefs.map(({ kind, slug, path }) => ({
      kind,
      slug,
      path,
    })),
    input_paths: memberRefs.map(({ path }) => path),
    outline: { role: "outline", path: outline },
    output: { role: outputRole, path: output },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
    operation_instructions: TOPIC_SYNTHESIS_INSTRUCTIONS[outputRole],
  };
  return JSON.stringify(request, null, 2);
}

export function topicOverviewSynthesiseOperationPrompt(options) {
  return topicSynthesiseOperationPrompt({
    ...options,
    operation: "topic.synthesise.overview",
    outputRole: "overview",
  });
}

export function topicResourcesSynthesiseOperationPrompt(options) {
  return topicSynthesiseOperationPrompt({
    ...options,
    operation: "topic.synthesise.resources",
    outputRole: "resources",
  });
}

// Public graph aliases preserve the short existing naming convention.
export const topicOverviewSynthesisePrompt =
  topicOverviewSynthesiseOperationPrompt;
export const topicResourcesSynthesisePrompt =
  topicResourcesSynthesiseOperationPrompt;

const LEGACY_TOPIC_FRONTMATTER_CONTRACT = {
  additionalProperties: false,
  required: ["type", "title", "kind"],
  properties: {
    type: { const: "topic" },
    title: { type: "string", minLength: 2, maxLength: 280 },
    kind: {
      type: "string",
      enum: ["overview", "resources", "dossier"],
    },
  },
};

const LEGACY_TOPIC_DOSSIER_ARTIFACT_CONTRACT = {
  frontmatter: LEGACY_TOPIC_FRONTMATTER_CONTRACT,
  h1: "Use identity.subquestion exactly",
  section_order: [
    "问题与现状",
    "证据综述",
    "证据档案",
    "缺口与下一步",
  ],
  sections: {
    问题与现状: "State the exact subquestion and current evidence boundary.",
    证据综述:
      "Synthesize only analysis_inputs and wikilink their exact canonical paths.",
    证据档案:
      "When card_inputs is non-empty, report each card separately with its evidence level and uncertainty.",
    缺口与下一步:
      "State only gaps supported by the supplied analyses and cards.",
  },
};

const LEGACY_TOPIC_SPINE_ARTIFACT_CONTRACT = {
  frontmatter: LEGACY_TOPIC_FRONTMATTER_CONTRACT,
  overview: {
    kind: "overview",
    h1: "Use identity.topic exactly",
    section_order: [
      "总体趋势",
      "子问题地图",
      "缺口总览",
      "对研究的启示",
    ],
  },
  resources: {
    kind: "resources",
    h1: "Use identity.topic exactly",
    grouping: "Follow outline subquestion order exactly",
    separate_channels: ["academic_materials", "evidence_cards"],
    final_sections: ["推荐追踪的专著", "未归类"],
  },
};

function legacyTopicDiagnostics(outputPaths, reasons) {
  const supplied =
    Array.isArray(reasons) && reasons.length
      ? reasons
      : ["refresh the cumulative Topic product from the supplied corpus"];
  return outputPaths.flatMap((path) =>
    supplied.map((reason) => ({
      path,
      kind: "topic_refresh",
      reason,
    })),
  );
}

export function topicDossierSynthPrompt(
  slug,
  desc,
  subquestion,
  cards,
  diagnostics = [],
) {
  const mine = [
    ...new Set([
      ...(subquestion.cards || []),
      ...(cards || [])
        .filter((card) => card.subq === subquestion.id)
        .map((card) => card.card_slug),
    ]),
  ];
  const outputPath = `vault/topics/${slug}/${subquestion.page}`;
  const analysisInputs = (subquestion.items || []).map((item) => ({
    kind: item.kind,
    slug: item.slug,
    role: item.role || null,
    path: itemPath(item),
  }));
  const cardInputs = mine.map((card) => ({
    role: "evidence_card",
    path: cardPath(slug, card),
  }));
  const request = {
    schema_version:
      "quasi.operation.topic.synthesise.dossier.request/legacy",
    operation: "topic.synthesise.dossier",
    research_key: `topic:${slug}`,
    identity: {
      topic: desc,
      subquestion_id: subquestion.id,
      subquestion: subquestion.question || subquestion.id,
    },
    inputs: {
      analyses: analysisInputs,
      cards: cardInputs,
    },
    outputs: [{ role: "dossier", path: outputPath }],
    mode: "repair",
    overwrite: true,
    repair_diagnostics: legacyTopicDiagnostics(
      [outputPath],
      diagnostics,
    ),
    artifact_contract: LEGACY_TOPIC_DOSSIER_ARTIFACT_CONTRACT,
    operation_instructions: [
      "Read every analysis input in order; these are the complete academic materials for this subquestion.",
      "Evidence cards are a separate primary-evidence channel, not peer-reviewed analyses; preserve single-source and disputed qualifications.",
      "Do not write the outline, cards, spine pages, or any path other than outputs[0].path.",
      "Return status=success only after the exact output write is confirmed; inputs_analyzed counts analysis inputs, not cards.",
    ],
    receipt_contract: {
      status: ["success", "error"],
      fields: ["status", "inputs_analyzed", "output"],
    },
  };
  return `Execute exactly one legacy Topic dossier synthesis operation from this
self-contained request. Follow artifact_contract and operation_instructions; do not
reinterpret it as another synthesis mode.
${JSON.stringify(request, null, 2)}`;
}

export function topicSpineSynthPrompt(
  slug,
  desc,
  ok,
  subquestions,
  cards,
  diagnostics = [],
) {
  const graduated = subquestions
    .filter((subquestion) => subquestion.dossier && subquestion.page)
    .map((subquestion) => ({
      id: subquestion.id,
      page: `vault/topics/${slug}/${subquestion.page}`,
    }));
  const inline = subquestions
    .filter((subquestion) => !(subquestion.dossier && subquestion.page))
    .map((subquestion) => ({
      id: subquestion.id,
      question: subquestion.question || subquestion.id,
      paths: (subquestion.items || []).map(itemPath),
      cards: (subquestion.cards || []).map((card) => cardPath(slug, card)),
    }));
  const allCards = [
    ...new Set([
      ...subquestions.flatMap((subquestion) => subquestion.cards || []),
      ...(cards || []).map((card) => card.card_slug),
    ]),
  ];
  const overviewPath = `vault/topics/${slug}/00-overview.md`;
  const resourcesPath = `vault/topics/${slug}/01-resources.md`;
  const request = {
    schema_version:
      "quasi.operation.topic.synthesise.spine.request/legacy",
    operation: "topic.synthesise.spine",
    research_key: `topic:${slug}`,
    identity: { topic: desc },
    inputs: {
      outline: {
        role: "outline",
        path: `vault/topics/${slug}/02-outline.md`,
      },
      corpus: ok.map((item) => ({
        kind: item.kind,
        slug: item.slug,
        path: itemPath(item),
      })),
      cards: allCards.map((card) => ({
        role: "evidence_card",
        path: cardPath(slug, card),
      })),
      dossiers: graduated,
      inline_clusters: inline,
    },
    outputs: [
      { role: "overview", path: overviewPath },
      { role: "resources", path: resourcesPath },
    ],
    mode: "repair",
    overwrite: true,
    repair_diagnostics: legacyTopicDiagnostics(
      [overviewPath, resourcesPath],
      diagnostics,
    ),
    artifact_contract: LEGACY_TOPIC_SPINE_ARTIFACT_CONTRACT,
    operation_instructions: [
      "Read the exact outline first and preserve its subquestion ids, titles, and order.",
      "Use supplied dossier pages as compressed completed subquestions and inline_clusters as the only unsynthesized corpus groups.",
      "Keep evidence cards in their own resources sublists; never present a card as an academic analysis.",
      "List every supplied corpus or card path under its registered subquestion or the final 未归类 section; do not silently drop members.",
      "Write only the two exact outputs. Return status=success only after both writes are confirmed; inputs_analyzed counts academic corpus inputs.",
    ],
    receipt_contract: {
      status: ["success", "error"],
      fields: [
        "status",
        "inputs_analyzed",
        "output",
        "reading_list",
      ],
    },
  };
  return `Execute exactly one legacy Topic spine synthesis operation from this
self-contained request. Follow artifact_contract and operation_instructions; do not
reinterpret it as another synthesis mode.
${JSON.stringify(request, null, 2)}`;
}

// --- Topic synthesis receipt contracts -------------------------------------
// The writer matrix rides the composed schema: exact ordered member echo as a
// deep const, path consts, and a per-mode action/members_analyzed pairing
// (a reconciled receipt reads nothing, a written one reads every member).

const topicSynthesiseComposed = (
  base,
  { researchKey, members, inputPaths, outline, output, mode },
) =>
  composedSchema(
    base,
    {
      research_key: { const: researchKey },
      member_refs: {
        const: members.map(({ kind, slug, path }) => ({
          kind,
          slug,
          path,
        })),
      },
      input_paths: { const: inputPaths },
      outline_path: { const: outline },
      output_path: { const: output },
    },
    {
      succeeded_write: {
        properties: {
          status: { const: "succeeded" },
          failure: { type: "null" },
          action:
            mode === "create"
              ? { const: "create" }
              : { const: "repair" },
          members_analyzed: { const: members.length },
        },
      },
      succeeded_reconciled: {
        properties: {
          status: { const: "succeeded" },
          failure: { type: "null" },
          action: { const: "reconciled" },
          members_analyzed: { const: 0 },
        },
      },
      failed: {
        properties: {
          status: { const: "failed" },
          failure: knownOutcome,
        },
      },
      blocked: {
        properties: {
          status: { const: "blocked" },
          failure: unknownOutcome,
        },
      },
    },
  );

export const topicOverviewSynthesiseSchema = (context) =>
  topicSynthesiseComposed(
    TOPIC_OVERVIEW_SYNTHESISE_SCHEMA,
    context,
  );

export const topicResourcesSynthesiseSchema = (context) =>
  topicSynthesiseComposed(
    TOPIC_RESOURCES_SYNTHESISE_SCHEMA,
    context,
  );

const topicSynthesisContract = (schema) => ({ schema });

export const TOPIC_OVERVIEW_SYNTHESISE_CONTRACT =
  topicSynthesisContract(TOPIC_OVERVIEW_SYNTHESISE_SCHEMA);
export const TOPIC_RESOURCES_SYNTHESISE_CONTRACT =
  topicSynthesisContract(TOPIC_RESOURCES_SYNTHESISE_SCHEMA);
