// Shared Stage Unit envelope. A Stage Unit is one goal-owning specialist
// invocation: the worker may use its declared capabilities until it can make
// one of four honest terminal judgements. The Workflow supplies boundaries,
// validates this one receipt shape, and routes the resulting edge.

export const STAGE_RECEIPT_VERSION = "quasi.stage.receipt/0.2";

export const STAGE_STATUSES = [
  "complete",
  "needs_input",
  "blocked",
  "failed",
];

const stageIssueObjectSchema = (
  operation,
  { questionRequired = false } = {},
) => ({
  type: "object",
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
      type: questionRequired ? "string" : ["string", "null"],
      ...(questionRequired ? { minLength: 1 } : {}),
      maxLength: 4000,
    },
    retryable: { type: "boolean" },
  },
});

const terminalPayload = (payloads, status) => {
  const payload = payloads && payloads[status];
  return payload && typeof payload === "object" ? payload : {};
};

const stageTerminalBranch = (
  operation,
  status,
  payloads,
) => {
  const payload = terminalPayload(payloads, status);
  return {
    type: "object",
    additionalProperties: false,
    required: ["status", "issue", ...(payload.required || [])],
    properties: {
      status: { const: status },
      issue:
        status === "complete"
          ? { type: "null" }
          : stageIssueObjectSchema(operation, {
              questionRequired: status === "needs_input",
            }),
      ...(payload.properties || {}),
    },
  };
};

// Claude rejects top-level schema combinators, so the discriminated union lives
// inside one required property. The host can now reject hybrid terminals (for
// example complete plus a non-null issue) before the receipt reaches the Graph.
export const stageTerminalSchema = (operation, payloads = {}) => ({
  anyOf: STAGE_STATUSES.map((status) =>
    stageTerminalBranch(operation, status, payloads),
  ),
});

export function stageReceiptSchema({
  operation,
  stage,
  materialKey,
  effect,
  required = [],
  properties = {},
  terminalPayloads = {},
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
      "attempt",
      ...required,
      "terminal",
    ],
    properties: {
      schema_version: { const: STAGE_RECEIPT_VERSION },
      operation: { const: operation },
      stage: { const: stage },
      material_key: { const: materialKey },
      effect: { const: effect },
      attempt: { type: "integer", const: 1 },
      ...properties,
      terminal: stageTerminalSchema(operation, terminalPayloads),
    },
  };
}

// The common matrix is intentionally small. It checks the meaning of the four
// Stage exits, not the specialist's internal method. Operation-specific
// completion predicates should prove only the exact artifacts needed by the
// next stage.
export function stageContract({ schema, complete }) {
  return {
    stage: true,
    schema,
    status: (receipt) => receipt.terminal.status,
    statuses: {
      complete: (receipt, context) =>
        complete(receipt, context) === true,
      needs_input: () => true,
      blocked: () => true,
      failed: () => true,
    },
    edges: {
      complete: "ok",
      needs_input: "needs_input",
      blocked: "blocked",
      failed: "failed",
    },
  };
}

export const stageStatus = (receipt) =>
  receipt && receipt.terminal ? receipt.terminal.status : null;

export const stageIssue = (receipt) =>
  receipt && receipt.terminal ? receipt.terminal.issue : null;
