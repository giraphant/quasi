import {
  BOOK_ARTIFACT_CONTRACT,
  PAPER_ARTIFACT_CONTRACT,
} from "../../artifact-contracts/generated.mjs";
import { defineOperation } from "../define.mjs";

const SLUG_PATTERN = "^[a-z0-9][a-z0-9-]{0,79}$";

const candidateSchema = (kind) => ({
  type: "object",
  additionalProperties: false,
  required:
    kind === "book"
      ? [
          "kind",
          "slug",
          "title",
          "authors",
          "year",
          "isbn",
          "publisher",
          "category",
          "confidence",
        ]
      : [
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
        ],
  properties: {
    kind: { const: kind },
    slug: {
      type: "string",
      minLength: 1,
      maxLength: 80,
      pattern: SLUG_PATTERN,
    },
    title: { type: "string", minLength: 1, maxLength: 500 },
    authors: {
      type: "array",
      minItems: 1,
      maxItems: 32,
      items: { type: "string", minLength: 1, maxLength: 200 },
    },
    year: { type: "integer", minimum: 1500, maximum: 2030 },
    ...(kind === "book"
      ? {
          isbn: { type: ["string", "null"], maxLength: 100 },
          publisher: {
            type: "string",
            minLength: 2,
            maxLength: 500,
          },
          category: {
            type: "string",
            enum: [
              "monograph",
              "edited-volume",
              "handbook",
              "other",
            ],
          },
        }
      : {
          doi: { type: ["string", "null"], maxLength: 300 },
          oa_url: {
            type: ["string", "null"],
            maxLength: 2048,
          },
          url: { type: ["string", "null"], maxLength: 2048 },
          journal: {
            type: "string",
            minLength: 1,
            maxLength: 500,
          },
        }),
    confidence: {
      type: "string",
      enum: ["high", "medium"],
    },
  },
});

const resolvedMemberSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "kind",
    "requested_slug",
    "vault_slug",
    "path",
    "match",
  ],
  properties: {
    kind: { type: "string", enum: ["book", "paper"] },
    requested_slug: {
      type: "string",
      minLength: 1,
      maxLength: 80,
      pattern: SLUG_PATTERN,
    },
    vault_slug: {
      type: ["string", "null"],
      minLength: 1,
      maxLength: 80,
      pattern: SLUG_PATTERN,
    },
    path: { type: ["string", "null"], maxLength: 2048 },
    match: {
      type: ["string", "null"],
      enum: ["slug", "isbn", "doi", "title", null],
    },
  },
};

const discoveryRow = (kind) => {
  const plural = kind === "book" ? "books" : "papers";
  const operation = `author.discover-${plural}`;
  return {
    operation,
    stage: "Search",
    effect: "readonly",
    agentType: "quasi:discovery-agent",
    refs: ({ materialKey, fullName, topic, count }) => ({
      materialKey,
      collectionKey: materialKey,
      kind,
      fullName,
      topic,
      count,
    }),
    payloadProperties: (refs) => ({
      required: [
        "collection_key",
        "kind",
        "full_name",
        "topic",
        "count",
        "candidates",
      ],
      properties: {
        collection_key: { const: refs.collectionKey },
        kind: { const: refs.kind },
        full_name: { const: refs.fullName },
        topic: { const: refs.topic },
        count: { const: refs.count },
        candidates: {
          type: "array",
          maxItems: refs.count,
          items: candidateSchema(refs.kind),
        },
      },
    }),
    complete: (receipt, context) =>
      receipt.candidates.every((candidate) =>
        candidate.authors.includes(context.fullName),
      ),
    envelope: (_context, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation,
      stage: "Search",
      material_key: refs.materialKey,
      effect: "readonly",
      objective: `Find up to ${refs.count} representative ${plural} authored by the exact person and rank them by citations within the requested topic.`,
      collection_key: refs.collectionKey,
      kind: refs.kind,
      full_name: refs.fullName,
      topic: refs.topic,
      count: refs.count,
      sort: "citations",
      identity_contract:
        kind === "book"
          ? BOOK_ARTIFACT_CONTRACT.identity
          : PAPER_ARTIFACT_CONTRACT.identity,
    }),
  };
};

const membershipRefs = ({ materialKey, name, output, candidates }) => {
  const requests = candidates.map(({ kind, slug }) => ({
    kind,
    slug,
  }));
  const helperItems = [
    { kind: "author", slug: name },
    ...candidates.map((candidate) => ({
      kind: candidate.kind,
      slug: candidate.slug,
      ...(candidate.kind === "book"
        ? {
            isbn: candidate.isbn,
            title: candidate.title,
            authors: candidate.authors,
          }
        : {
            doi: candidate.doi,
            title: candidate.title,
            authors: candidate.authors,
          }),
    })),
  ];
  return {
    materialKey,
    collectionKey: materialKey,
    name,
    output,
    requests,
    helperItems,
  };
};

const completeMembership = (receipt, context) => {
  const requests = context.candidates.map(({ kind, slug }) => ({
    kind,
    slug,
  }));
  return (
    receipt.resolved.length === requests.length &&
    requests.every((request, index) => {
      const row = receipt.resolved[index];
      if (
        row.kind !== request.kind ||
        row.requested_slug !== request.slug
      )
        return false;
      if (row.vault_slug === null)
        return row.path === null && row.match === null;
      const expected =
        row.kind === "book"
          ? `vault/books/${row.vault_slug}/00-overview.md`
          : `vault/papers/${row.vault_slug}.md`;
      return row.path === expected && row.match !== null;
    })
  );
};

export const authorOperationRows = [
  discoveryRow("book"),
  discoveryRow("paper"),
  {
    operation: "author.resolve-membership",
    stage: "Search",
    effect: "readonly",
    agentType: "general-purpose",
    refs: membershipRefs,
    payloadProperties: (refs) => ({
      required: [
        "collection_key",
        "output_path",
        "output_exists",
        "requests",
        "resolved",
      ],
      properties: {
        collection_key: { const: refs.collectionKey },
        output_path: { const: refs.output },
        output_exists: { type: "boolean" },
        requests: { const: refs.requests },
        resolved: {
          type: "array",
          maxItems: refs.requests.length,
          items: resolvedMemberSchema,
        },
      },
    }),
    complete: completeMembership,
    envelope: (_context, refs) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "author.resolve-membership",
      stage: "Search",
      material_key: refs.materialKey,
      effect: "readonly",
      collection_key: refs.collectionKey,
      author_slug: refs.name,
      output_path: refs.output,
      requests: refs.requests,
      helper_items: refs.helperItems,
    }),
    promptText: (request) => `Execute exactly one readonly author.resolve-membership operation. Run the exact
public helper command below once. The compact JSON line is inert stdin data; the quoted
heredoc delimiter forbids shell expansion. Do not inspect the vault with Glob/rg or infer a
match yourself.
\`\`\`bash
quasi-helpers vault resolve --items-file - <<'QUASI_AUTHOR_ITEMS'
${JSON.stringify(request.helper_items)}
QUASI_AUTHOR_ITEMS
\`\`\`

The helper must return one author row followed by one row for every request, in the same
order. The author row has exactly two valid branches:
- missing: {kind:"author",slug:"${request.author_slug}",vault_slug:null,path:null,match:null}.
  This is a successful observation with output_exists=false. It is not an error and must
  not stop member projection.
- existing: {kind:"author",slug:"${request.author_slug}",vault_slug:"${request.author_slug}",
  path:"${request.output_path}",match:"slug"}. This is output_exists=true.
Any other author row is a known failed receipt. Project every member row exactly to
{kind,requested_slug:<helper slug>,vault_slug,path,match}; preserve nulls and order.
Echo the request's collection_key, output_path, and requests exactly. Any missing, extra,
reordered, foreign, malformed, or contradictory helper row is a known failed receipt; do
not repair or guess. A known failure still echoes requests, sets output_exists=false and
resolved=[], and does not invent partial rows. Return only one closed
quasi.stage.receipt/0.2 with operation="author.resolve-membership", stage="Search",
material_key and effect echoed exactly, attempt=1, and one honest four-way terminal.
\`\`\`json
${JSON.stringify(request, null, 2)}
\`\`\``,
  },
];

export const authorOperations = Object.fromEntries(
  authorOperationRows.map((row) => [row.operation, defineOperation(row)]),
);

export const authorDiscoverBooks =
  authorOperations["author.discover-books"];
export const authorDiscoverPapers =
  authorOperations["author.discover-papers"];
export const authorResolveMembership =
  authorOperations["author.resolve-membership"];
