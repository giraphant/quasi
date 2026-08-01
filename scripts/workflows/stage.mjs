// Shared Stage Unit envelope. A Stage Unit is one goal-owning specialist
// invocation: the worker may use its declared capabilities until it can make
// one of four honest terminal judgements. run-stage supplies the boundaries
// and host-validated receipt shape; the driving skill consumes the terminal.

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

// JSON-data keywords whose values are payload literals, not subschemas.
const SCHEMA_DATA_KEYWORDS = new Set(["const", "enum", "default", "examples"]);

const constType = (value) => {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number")
    return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
};

// StructuredOutput providers backed by weaker models guess "string" for a bare
// `const` and stringify non-string echoes (1 -> "1", ["canonical"] ->
// "[\"canonical\"]"), which makes exact-echo validation deterministically
// impossible. Every const therefore carries an explicit `type` hint.
export const annotateConstTypes = (node) => {
  if (Array.isArray(node)) return node.map(annotateConstTypes);
  if (!node || typeof node !== "object") return node;
  const out = {};
  for (const [key, value] of Object.entries(node))
    out[key] = SCHEMA_DATA_KEYWORDS.has(key)
      ? value
      : annotateConstTypes(value);
  if ("const" in out && !("type" in out)) out.type = constType(out.const);
  return out;
};

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
// example complete plus a non-null issue) before the receipt reaches the skill.
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
  return annotateConstTypes({
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
  });
}

// The common matrix is intentionally small. It checks the meaning of the four
// Stage exits, not the specialist's internal method. Operation-specific
// completion predicates should prove only the exact artifacts needed by the
// next stage.
export function stageContract({ schema, complete }) {
  return {
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
