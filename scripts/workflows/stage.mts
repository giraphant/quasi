// Shared Stage Unit envelope. A Stage Unit is one goal-owning specialist
// invocation: the worker may use its declared capabilities until it can make
// one of four honest terminal judgements. run-stage supplies the boundaries
// and host-validated receipt shape; the driving skill consumes the terminal.

import type {
  JsonSchema,
  StageReceipt,
  StageTerminal,
  WorkflowContext,
} from "./artifact-contracts/generated.mjs";

export type StageStatus = StageTerminal["status"];

export const STAGE_RECEIPT_VERSION = "quasi.stage.receipt/0.3";

export const STAGE_STATUSES: StageStatus[] = [
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
export const annotateConstTypes = (node: any): any => {
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
export const stageTerminalSchema = (
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

export interface StageReceiptDefinition {
  operation: string;
  stage: string;
  materialKey: any;
  effect: string;
  required?: string[];
  properties?: WorkflowContext;
  terminalPayloads?: WorkflowContext;
}

export interface StageReceiptPartition {
  modelSchema: JsonSchema;
  stampedValues: WorkflowContext;
}

export const partitionStageReceiptSchema = (
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
  });
  return partitionStageReceiptSchema(fullSchema);
}

export function stageReceiptSchema(
  definition: StageReceiptDefinition,
): JsonSchema {
  return stageReceiptPartition(definition).modelSchema;
}

// The common matrix is intentionally small. It checks the meaning of the four
// Stage exits, not the specialist's internal method. Operation-specific
// completion predicates should prove only the exact artifacts needed by the
// next stage.
interface StageContractDefinition {
  schema: JsonSchema | null;
  complete: (receipt: StageReceipt, context: any) => boolean;
}

export function stageContract({
  schema,
  complete,
}: StageContractDefinition) {
  return {
    schema,
    status: (receipt: StageReceipt) =>
      receipt.terminal.status,
    statuses: {
      complete: (receipt: StageReceipt, context: any) =>
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

export const stageStatus = (
  receipt: StageReceipt | null | undefined,
): StageStatus | null =>
  receipt && receipt.terminal ? receipt.terminal.status : null;

export const stageIssue = (
  receipt: StageReceipt | null | undefined,
) =>
  receipt && receipt.terminal ? receipt.terminal.issue : null;
