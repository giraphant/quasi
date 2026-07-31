import { validText } from "../runtime.mjs";
import { composedSchema } from "./extract.mjs";

export const AU_SCHEMA = {
  type: "object",
  properties: {
    status: { type: "string" },
    escalated: {
      type: "array",
      items: {
        type: "object",
        properties: {
          path: { type: "string" },
          kind: { type: "string" },
          reason: { type: "string" },
        },
      },
    },
  },
};

export const PAPER_AUDIT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "target_path",
    "remaining_violations",
    "escalated",
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.paper.audit.agent-receipt/0.1",
    },
    key: { const: "paper.audit" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["clean", "partial", "error"],
    },
    attempt: { type: "integer", const: 1 },
    target_path: { type: "string" },
    remaining_violations: {
      type: "integer",
      minimum: 0,
      description:
        "Non-negative count; the Workflow validates status/count consistency.",
    },
    escalated: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "kind", "reason"],
        properties: {
          path: { type: "string" },
          kind: { type: "string" },
          reason: { type: "string" },
        },
      },
    },
  },
};

const PAPER_AUDIT_BRANCHES = {
  clean: {
    properties: {
      status: { const: "clean" },
      remaining_violations: { const: 0 },
      escalated: { maxItems: 0 },
    },
  },
  partial: {
    properties: {
      status: { const: "partial" },
      remaining_violations: { minimum: 1 },
      escalated: { minItems: 1 },
    },
  },
  error: {
    properties: { status: { const: "error" } },
  },
};

export const paperAuditSchema = ({ target }) =>
  composedSchema(
    PAPER_AUDIT_SCHEMA,
    { target_path: { const: target } },
    PAPER_AUDIT_BRANCHES,
  );

// Only the count/diagnostic arithmetic a JSON Schema cannot express stays in
// the contract; everything else rides the composed schema.
export const PAPER_AUDIT_CONTRACT = {
  schema: PAPER_AUDIT_SCHEMA,
  statuses: {
    clean: () => true,
    partial: (receipt) =>
      receipt.remaining_violations ===
      receipt.escalated.length,
    error: () => true,
  },
  edges: { clean: "ok", partial: "ok", error: "failed" },
};

export const BOOK_AUDIT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "target_path",
    "remaining_violations",
    "escalated",
    "mutated_paths",
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.book.audit.receipt/0.1",
    },
    key: { const: "book.audit" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["clean", "partial", "error"],
    },
    attempt: { type: "integer", const: 1 },
    target_path: { type: "string" },
    remaining_violations: { type: "integer", minimum: 0 },
    escalated: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "kind", "reason"],
        properties: {
          path: { type: "string" },
          kind: { type: "string" },
          reason: { type: "string" },
        },
      },
    },
    mutated_paths: {
      type: "array",
      items: { type: "string" },
    },
  },
};

const bookAuditReported = (receipt) =>
  new Set(receipt.mutated_paths).size ===
    receipt.mutated_paths.length &&
  receipt.mutated_paths.every((path) =>
    validText(path, 1, 2048),
  ) &&
  receipt.escalated.every(
    (diagnostic) =>
      validText(diagnostic.path, 1, 2048) &&
      validText(diagnostic.kind, 1, 200) &&
      validText(diagnostic.reason, 1, 4000),
  );

const AUDIT_STATUS_BRANCHES = {
  clean: {
    properties: {
      status: { const: "clean" },
      remaining_violations: { const: 0 },
      escalated: { maxItems: 0 },
    },
  },
  partial: {
    properties: {
      status: { const: "partial" },
      remaining_violations: { minimum: 1 },
      escalated: { minItems: 1 },
    },
  },
  error: {
    properties: { status: { const: "error" } },
  },
};

// Legacy composite audits close the error status: it is a command failure and
// must not smuggle diagnostics.
const CLOSED_ERROR_BRANCHES = {
  ...AUDIT_STATUS_BRANCHES,
  error: {
    properties: {
      status: { const: "error" },
      remaining_violations: { const: 0 },
      escalated: { maxItems: 0 },
    },
  },
};

export const bookAuditSchema = ({ target }) =>
  composedSchema(
    BOOK_AUDIT_SCHEMA,
    { target_path: { const: target } },
    AUDIT_STATUS_BRANCHES,
  );

// mutated_paths must be exact and duplicate-free because the graph settles
// producer ownership for every reported path; that stays in the contract.
export const BOOK_AUDIT_CONTRACT = {
  schema: BOOK_AUDIT_SCHEMA,
  statuses: {
    clean: (receipt) => bookAuditReported(receipt),
    partial: (receipt) =>
      bookAuditReported(receipt) &&
      receipt.escalated.length ===
        receipt.remaining_violations,
    error: (receipt) => bookAuditReported(receipt),
  },
  edges: { clean: "ok", partial: "ok", error: "failed" },
};

export const AUTHOR_AUDIT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "target_path",
    "remaining_violations",
    "escalated",
    "mutated_paths",
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.author.audit.legacy.receipt/0.1",
    },
    key: { const: "author.audit.legacy" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["clean", "partial", "error"],
    },
    attempt: { type: "integer", const: 1 },
    target_path: { type: "string" },
    remaining_violations: { type: "integer", minimum: 0 },
    escalated: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "kind", "reason"],
        properties: {
          path: { type: "string" },
          kind: { type: "string" },
          reason: { type: "string" },
        },
      },
    },
    mutated_paths: {
      type: "array",
      items: { type: "string" },
    },
  },
};

export const TALK_AUDIT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "target_path",
    "remaining_violations",
    "escalated",
    "mutated_paths",
  ],
  properties: {
    schema_version: {
      const:
        "quasi.operation.talk.audit.legacy.receipt/0.1",
    },
    key: { const: "talk.audit.legacy" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["clean", "partial", "error"],
    },
    attempt: { type: "integer", const: 1 },
    target_path: { type: "string" },
    remaining_violations: { type: "integer", minimum: 0 },
    escalated: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "kind", "reason"],
        properties: {
          path: { type: "string" },
          kind: { type: "string" },
          reason: { type: "string" },
        },
      },
    },
    mutated_paths: {
      type: "array",
      items: { type: "string" },
    },
  },
};

const legacyAuditReported = (receipt) =>
  receipt.escalated.every(
    (item) =>
      validText(item.path, 1, 2048) &&
      validText(item.kind, 1, 200) &&
      validText(item.reason, 1, 4000),
  ) &&
  receipt.mutated_paths.every((path) =>
    validText(path, 1, 2048),
  );

const legacyCompositeAuditContract = (schema) => ({
  schema,
  statuses: {
    clean: (receipt) => legacyAuditReported(receipt),
    partial: (receipt) =>
      legacyAuditReported(receipt) &&
      receipt.escalated.length ===
        receipt.remaining_violations,
    error: (receipt) => legacyAuditReported(receipt),
  },
  edges: { clean: "ok", partial: "ok", error: "failed" },
});

export const talkAuditSchema = ({ target }) =>
  composedSchema(
    TALK_AUDIT_SCHEMA,
    { target_path: { const: target } },
    CLOSED_ERROR_BRANCHES,
  );

export const authorAuditSchema = ({ target }) =>
  composedSchema(
    AUTHOR_AUDIT_SCHEMA,
    { target_path: { const: target } },
    CLOSED_ERROR_BRANCHES,
  );

export const TALK_AUDIT_CONTRACT =
  legacyCompositeAuditContract(TALK_AUDIT_SCHEMA);
export const AUTHOR_AUDIT_CONTRACT =
  legacyCompositeAuditContract(AUTHOR_AUDIT_SCHEMA);

export function paperAuditPrompt(slug, pass) {
  const output = `vault/papers/${slug}.md`;
  const request = {
    schema_version: "quasi.operation.paper.audit.request/0.1",
    operation: "paper.audit",
    material_key: `paper:${slug}`,
    effect: "writer",
    mode: pass === 1 ? "audit" : "re-audit",
    target: { role: "canonical", path: output },
  };
  return JSON.stringify(request, null, 2);
}

export function bookAuditPrompt(slug, pass) {
  const scope = `vault/books/${slug}`;
  const request = {
    schema_version: "quasi.operation.book.audit.request/0.1",
    operation: "book.audit",
    material_key: `book:${slug}`,
    effect: "writer",
    mode: pass === 1 ? "audit" : "re-audit",
    target: { role: "canonical_scope", path: scope },
  };
  return JSON.stringify(request, null, 2);
}

export function authorAuditLegacyPrompt(name, pass) {
  const output = `vault/authors/${name}.md`;
  const request = {
    schema_version:
      "quasi.operation.author.audit.legacy.request/0.1",
    operation: "author.audit.legacy",
    collection_key: `author:${name}`,
    effect: "writer",
    mode: pass === 1 ? "audit" : "re-audit",
    target: { role: "canonical", path: output },
    exact_output: output,
    composite_debt: true,
  };
  return JSON.stringify(request, null, 2);
}

export function talkAuditLegacyPrompt(slug, pass) {
  const output = `vault/talks/${slug}/talk.md`;
  const request = {
    schema_version:
      "quasi.operation.talk.audit.legacy.request/0.1",
    operation: "talk.audit.legacy",
    material_key: `talk:${slug}`,
    effect: "writer",
    mode: pass === 1 ? "audit" : "re-audit",
    target: { role: "canonical", path: output },
    exact_output: output,
    composite_debt: true,
  };
  return JSON.stringify(request, null, 2);
}

// Strict Topic recall-only audit. Author and Talk retain their current operation ids until
// their own cleanup slices; Paper and Book use the strict ids above.
const TOPIC_AUDIT_DIAGNOSTIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["path", "kind", "reason"],
  properties: {
    path: { type: "string", minLength: 1, maxLength: 2048 },
    kind: { type: "string", minLength: 1, maxLength: 200 },
    reason: { type: "string", minLength: 1, maxLength: 4000 },
  },
};

const TOPIC_AUDIT_FAILURE_SCHEMA = {
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
    operation_key: { const: "topic.audit.legacy" },
    outcome: { type: "string", enum: ["known", "unknown"] },
    retryable: { const: false },
    message: { type: ["string", "null"], maxLength: 4000 },
  },
};

export const TOPIC_AUDIT_LEGACY_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.topic.audit.legacy.receipt/0.1",
    },
    key: { const: "topic.audit.legacy" },
    effect: { const: "writer" },
    status: { type: "string", enum: ["clean", "partial", "error"] },
    attempt: { type: "integer", const: 1 },
    research_key: { type: "string", minLength: 1, maxLength: 200 },
    target_path: { type: "string", minLength: 1, maxLength: 2048 },
    remaining_violations: { type: "integer", minimum: 0 },
    escalated: {
      type: "array",
      items: TOPIC_AUDIT_DIAGNOSTIC_SCHEMA,
    },
    mutated_paths: {
      type: "array",
      uniqueItems: true,
      items: { type: "string", minLength: 1, maxLength: 2048 },
    },
    failure: TOPIC_AUDIT_FAILURE_SCHEMA,
  },
};

// Public graph alias uses the concise schema name while retaining the explicit
// legacy qualifier for callers that catalogue operation receipts.
export const TOPIC_AUDIT_SCHEMA = TOPIC_AUDIT_LEGACY_SCHEMA;

export function topicAuditLegacyPrompt(
  researchKey,
  targetPath,
  pass = 1,
) {
  const request = {
    schema_version:
      "quasi.operation.topic.audit.legacy.request/0.1",
    operation: "topic.audit.legacy",
    research_key: researchKey,
    effect: "writer",
    mode: pass === 1 ? "audit" : "re-audit",
    exact_output: targetPath,
    path: targetPath,
    composite_debt: true,
  };
  return JSON.stringify(request, null, 2);
}

// --- Topic legacy audit ----------------------------------------------------
// Unlike the Talk/Author composites, the Topic audit receipt carries its own
// closed failure; error surfaces it with a known or unknown outcome.

export const topicAuditSchema = ({ researchKey, target }) =>
  composedSchema(
    TOPIC_AUDIT_LEGACY_SCHEMA,
    {
      research_key: { const: researchKey },
      target_path: { const: target },
    },
    {
      clean: {
        properties: {
          status: { const: "clean" },
          remaining_violations: { const: 0 },
          escalated: { maxItems: 0 },
          failure: { type: "null" },
        },
      },
      partial: {
        properties: {
          status: { const: "partial" },
          remaining_violations: { minimum: 1 },
          escalated: { minItems: 1 },
          failure: { type: "null" },
        },
      },
      error: {
        properties: {
          status: { const: "error" },
          remaining_violations: { const: 0 },
          escalated: { maxItems: 0 },
          failure: { type: "object" },
        },
      },
    },
  );

export const TOPIC_AUDIT_CONTRACT = {
  schema: TOPIC_AUDIT_LEGACY_SCHEMA,
  statuses: {
    clean: (receipt) => legacyAuditReported(receipt),
    partial: (receipt) =>
      legacyAuditReported(receipt) &&
      receipt.escalated.length ===
        receipt.remaining_violations,
    error: (receipt) => legacyAuditReported(receipt),
  },
  edges: { clean: "ok", partial: "ok", error: "failed" },
};
