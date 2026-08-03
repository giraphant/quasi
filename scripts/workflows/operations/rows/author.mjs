import {
  AUTHOR_ARTIFACT_CONTRACT,
  BOOK_ARTIFACT_CONTRACT,
  PAPER_ARTIFACT_CONTRACT,
} from "../../artifact-contracts/generated.mjs";
import { contextValue } from "../../context-base.mjs";
import { actionPayloads, makeAuditRow } from "../shared.mjs";

/** @typedef {import("../../artifact-contracts/generated.mjs").OperationRow} OperationRow */
/** @typedef {(...args: any[]) => any} AnyFunction */

const SLUG_PATTERN = "^[a-z0-9][a-z0-9-]{0,79}$";

/** @type {AnyFunction} */
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

/** @type {(kind: "book" | "paper") => OperationRow} */
const discoveryRow = (kind) => {
  const plural = kind === "book" ? "books" : "papers";
  const operation =
    kind === "book"
      ? "author.discover-books"
      : "author.discover-papers";
  return {
    operation,
    context: (rawContext, base) => ({
      ...base,
      fullName: contextValue(rawContext, "fullName", "full_name"),
      topic: rawContext.topic,
      count: rawContext.count,
    }),
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
      receipt.candidates.every((/** @type {any} */ candidate) =>
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

/** @type {AnyFunction} */
const membershipRefs = ({ materialKey, name, output, candidates }) => {
  const requests = candidates.map(
    (/** @type {any} */ { kind, slug }) => ({
      kind,
      slug,
    }),
  );
  const helperItems = [
    { kind: "author", slug: name },
    ...candidates.map((/** @type {any} */ candidate) => ({
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

/** @type {AnyFunction} */
const completeMembership = (receipt, context) => {
  const requests = context.candidates.map(
    (/** @type {any} */ { kind, slug }) => ({
      kind,
      slug,
    }),
  );
  return (
    receipt.resolved.length === requests.length &&
    requests.every((
      /** @type {any} */ request,
      /** @type {number} */ index,
    ) => {
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

/** @type {OperationRow[]} */
export const authorOperationRows = [
  discoveryRow("book"),
  discoveryRow("paper"),
  {
    operation: "author.resolve-membership",
    context: (rawContext, base) => ({
      ...base,
      name: base.slug,
      candidates: rawContext.candidates || [],
    }),
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
  {
    operation: "author.synthesise",
    context: (rawContext, base) => ({
      ...base,
      name: base.slug,
      fullName:
        contextValue(rawContext, "fullName", "full_name") ||
        contextValue(base.meta, "fullName", "full_name") ||
        base.slug,
      topic: rawContext.topic || base.meta.topic || "",
      inputs: rawContext.inputs || [],
    }),
    refs: ({ materialKey, inputs, output, mode }) => ({
      materialKey,
      inputs,
      output,
      mode,
    }),
    payloadProperties: ({ inputs, output }) => ({
      required: [
        "input_material_keys",
        "input_paths",
        "output_path",
        "artifact_roles",
        "materials_analyzed",
      ],
      properties: {
        input_material_keys: {
          const: inputs.map(
            (/** @type {any} */ input) => input.material_key,
          ),
        },
        input_paths: {
          const: inputs.map((/** @type {any} */ input) => input.path),
        },
        output_path: { const: output },
        artifact_roles: { const: ["canonical"] },
        materials_analyzed: { const: inputs.length },
      },
    }),
    terminalPayloads: actionPayloads,
    complete: (receipt, context) =>
      [
        ...(context.mode === "create" ? ["create"] : ["repair"]),
        "reconciled",
      ].includes(/** @type {string} */ (receipt.terminal.action)),
    envelope: (
      { materialKey, name, fullName, topic, diagnostics },
      { inputs, output, mode },
    ) => ({
      schema_version: "quasi.stage.request/0.2",
      operation: "author.synthesise",
      stage: "Synthesise",
      material_key: materialKey,
      collection_key: materialKey,
      inputs: inputs.map((/** @type {any} */ input) => ({
        material_key: input.material_key,
        kind: input.kind,
        id: input.id,
        role: "canonical",
        path: input.path,
        title: input.title,
      })),
      input_material_keys: inputs.map(
        (/** @type {any} */ input) => input.material_key,
      ),
      input_paths: inputs.map(
        (/** @type {any} */ input) => input.path,
      ),
      output: { role: "canonical", path: output },
      identity: { slug: name, full_name: fullName, topic },
      artifact_contract: AUTHOR_ARTIFACT_CONTRACT,
      frontmatter_seed: { type: "author", name: fullName },
      mode,
      overwrite: mode === "repair",
      repair_diagnostics: mode === "repair" ? diagnostics : [],
    }),
  },
  makeAuditRow({
    operation: "author.audit",
    refs: ({ materialKey, target, pass }) => ({ materialKey, target, pass }),
    artifactRoles: ["canonical"],
    targetRole: "canonical",
    envelopeExtras: ({ materialKey }, { target }) => ({
      beforeEffect: { collection_key: materialKey },
      afterTarget: { exact_output: target, composite_debt: true },
    }),
  }),
];
