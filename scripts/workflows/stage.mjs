// Shared Stage Unit envelope. A Stage Unit is one goal-owning specialist
// invocation: the worker may use its declared capabilities until it can make
// one of four honest terminal judgements. The Workflow supplies boundaries,
// validates this one receipt shape, and routes the resulting edge.

export const STAGE_RECEIPT_VERSION = "quasi.stage.receipt/0.1";

export const STAGE_STATUSES = [
  "complete",
  "needs_input",
  "blocked",
  "failed",
];

export const stageIssueSchema = (operation) => ({
  type: ["object", "null"],
  additionalProperties: false,
  required: [
    "code",
    "operation",
    "summary",
    "user_question",
    "retryable",
  ],
  properties: {
    code: { type: "string", minLength: 1, maxLength: 200 },
    operation: { const: operation },
    summary: { type: "string", minLength: 1, maxLength: 4000 },
    user_question: {
      type: ["string", "null"],
      maxLength: 4000,
    },
    retryable: { type: "boolean" },
  },
});

export function stageReceiptSchema({
  operation,
  stage,
  materialKey,
  effect,
  required = [],
  properties = {},
}) {
  return {
    type: "object",
    additionalProperties: false,
    required: [
      "schema_version",
      "operation",
      "stage",
      "material_key",
      "effect",
      "status",
      "attempt",
      ...required,
      "issue",
    ],
    properties: {
      schema_version: { const: STAGE_RECEIPT_VERSION },
      operation: { const: operation },
      stage: { const: stage },
      material_key: { const: materialKey },
      effect: { const: effect },
      status: { type: "string", enum: STAGE_STATUSES },
      attempt: { type: "integer", const: 1 },
      ...properties,
      issue: stageIssueSchema(operation),
    },
  };
}

// The common matrix is intentionally small. It checks the meaning of the four
// Stage exits, not the specialist's internal method. Operation-specific
// completion predicates should prove only the exact artifacts needed by the
// next stage.
export function stageContract({ schema, complete }) {
  return {
    schema,
    status: (receipt) => receipt.status,
    statuses: {
      complete: (receipt, context) =>
        receipt.issue === null && complete(receipt, context) === true,
      needs_input: (receipt) =>
        !!(
          receipt.issue &&
          typeof receipt.issue.user_question === "string" &&
          receipt.issue.user_question.length > 0
        ),
      blocked: (receipt) => !!receipt.issue,
      failed: (receipt) => !!receipt.issue,
    },
    edges: {
      complete: "ok",
      needs_input: "needs_input",
      blocked: "blocked",
      failed: "failed",
    },
  };
}

export const stageIssue = (
  operation,
  code,
  summary,
  { userQuestion = null, retryable = false } = {},
) => ({
  code,
  operation,
  summary,
  user_question: userQuestion,
  retryable,
});
