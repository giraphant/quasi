// Shared Stage Unit envelope. A Stage Unit is one goal-owning specialist
// invocation: the worker may use its declared capabilities until it can make
// one of four honest terminal judgements. The owning descriptor row and
// prepared-dispatch boundary supply the host-validated receipt shape; the
// named material plan consumes the terminal.

import type {
  JsonSchema,
  StageTerminal,
  WorkflowContext,
} from "./artifact-contracts/generated.mjs";

type StageStatus = StageTerminal["status"];

const STAGE_RECEIPT_VERSION = "quasi.stage.receipt/0.3";

const STAGE_STATUSES: StageStatus[] = [
  "complete",
  "needs_input",
  "blocked",
  "failed",
];

const stageIssueObjectSchema = (
  operation: string,
  { questionRequired = false }: { questionRequired?: boolean } = {},
): JsonSchema => ({
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

const constType = (value: any): string => {
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
const annotateConstTypes = (node: any): any => {
  if (Array.isArray(node)) return node.map(annotateConstTypes);
  if (!node || typeof node !== "object") return node;
  const out: WorkflowContext = {};
  for (const [key, value] of Object.entries(node))
    out[key] = SCHEMA_DATA_KEYWORDS.has(key)
      ? value
      : annotateConstTypes(value);
  if ("const" in out && !("type" in out)) out.type = constType(out.const);
  return out;
};

const terminalPayload = (
  payloads: WorkflowContext,
  status: StageStatus,
): WorkflowContext => {
  const payload = payloads && payloads[status];
  return payload && typeof payload === "object" ? payload : {};
};

const stageTerminalBranch = (
  operation: string,
  status: StageStatus,
  payloads: WorkflowContext,
): JsonSchema => {
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
const stageTerminalSchema = (
  operation: string,
  payloads: WorkflowContext = {},
): JsonSchema => ({
  anyOf: STAGE_STATUSES.filter(
    (status) =>
      status !== "needs_input" ||
      (Object.prototype.hasOwnProperty.call(payloads, status) &&
        payloads[status] != null),
  ).map((status) =>
    stageTerminalBranch(operation, status, payloads),
  ),
});

interface StageReceiptDefinition {
  operation: string;
  stage: string;
  materialKey: any;
  effect: string;
  required?: string[];
  properties?: WorkflowContext;
  definitions?: WorkflowContext;
  terminalPayloads?: WorkflowContext;
}

export interface StageReceiptPartition {
  modelSchema: JsonSchema;
  stampedValues: WorkflowContext;
}

const partitionStageReceiptSchema = (
  fullSchema: JsonSchema,
): StageReceiptPartition => {
  const properties: WorkflowContext = fullSchema.properties || {};
  const stampedKeys = new Set(
    Object.entries(properties)
      .filter(([, propertySchema]) =>
        propertySchema &&
        typeof propertySchema === "object" &&
        Object.prototype.hasOwnProperty.call(propertySchema, "const"),
      )
      .map(([key]) => key),
  );
  return {
    modelSchema: {
      ...fullSchema,
      required: (fullSchema.required || []).filter(
        (key: string) => !stampedKeys.has(key),
      ),
      properties: Object.fromEntries(
        Object.entries(properties).filter(([key]) => !stampedKeys.has(key)),
      ),
    },
    stampedValues: Object.fromEntries(
      Object.entries(properties)
        .filter(([key]) => stampedKeys.has(key))
        .map(([key, propertySchema]) => [key, propertySchema.const]),
    ),
  };
};

export function stageReceiptPartition({
  operation,
  stage,
  materialKey,
  effect,
  required = [],
  properties = {},
  definitions = {},
  terminalPayloads = {},
}: StageReceiptDefinition): StageReceiptPartition {
  const fullSchema = annotateConstTypes({
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
    ...(Object.keys(definitions).length === 0
      ? {}
      : {
          $schema: "http://json-schema.org/draft-07/schema#",
          definitions,
        }),
  });
  return partitionStageReceiptSchema(fullSchema);
}
