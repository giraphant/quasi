import {
  sameClosedValue,
  validateSchema,
} from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import {
  BOOK_TEMP_PATH,
  validYearEvidence,
} from "../operations/book-year-evidence.mjs";
import {
  bookAcquireStageSchema,
} from "../operations/acquire.mjs";
import {
  bookPrepareStageSchema,
} from "../operations/extract.mjs";
import {
  paperAcquire,
  paperPrepare,
} from "../operations/rows/paper.mjs";

export const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.2";

const record = (value) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value)
  );

const textSchema = (min, max) => ({
  type: "string",
  minLength: min,
  maxLength: max,
  pattern: "^(?!\\s)[^\\u0000-\\u001f\\u007f-\\u009f]+(?<!\\s)$",
});

const MATERIAL_ARTIFACT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["role", "path", "exists", "usable", "producer"],
  properties: {
    role: textSchema(1, 100),
    path: textSchema(1, 1000),
    exists: { const: true },
    usable: { enum: [null, true, false] },
    producer: textSchema(1, 200),
  },
};

export const MATERIAL_FAILURE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["code", "operation_key", "outcome", "retryable"],
  properties: {
    code: textSchema(1, 200),
    operation_key: textSchema(1, 200),
    outcome: { enum: ["known", "unknown"] },
    retryable: { type: "boolean" },
    message: { anyOf: [textSchema(1, 4000), { type: "null" }] },
  },
};

export const MATERIAL_RESUME_SCHEMA = {
  anyOf: [
    { type: "null" },
    {
      type: "object",
      additionalProperties: false,
      required: ["operation_key"],
      properties: {
        operation_key: textSchema(1, 200),
        stage: textSchema(1, 100),
        policy: textSchema(1, 400),
      },
    },
  ],
};

const MATERIAL_FRESHNESS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["observation", "basis"],
  properties: {
    observation: { const: "unknown" },
    basis: { const: "operation-receipts-and-final-audit" },
  },
};

export function materialReceiptSchema({ materialKey, kind, id }) {
  const base = {
    type: "object",
    additionalProperties: false,
    required: [
      "schema_version",
      "material_key",
      "kind",
      "id",
      "status",
      "disposition",
      "stage",
      "artifacts",
      "operations",
      "audit",
      "freshness",
      "warnings",
      "failure",
      "user_gate",
      "resume",
    ],
    properties: {
      schema_version: { const: MATERIAL_RECEIPT_VERSION },
      material_key: { const: materialKey },
      kind: { const: kind },
      id: { const: id },
      status: {
        enum: ["complete", "needs_input", "blocked", "failed"],
      },
      disposition: { type: ["string", "null"] },
      stage: { type: "string" },
      artifacts: {
        type: "array",
        items: MATERIAL_ARTIFACT_SCHEMA,
      },
      operations: {
        type: "array",
        items: { type: "object" },
      },
      // The child terminal decides whether this is a Paper object, Book pass
      // list, or an early-stage placeholder. The admitted complete branch
      // validates the actual final audit against its operation schema below.
      audit: {},
      freshness: MATERIAL_FRESHNESS_SCHEMA,
      warnings: {
        type: "array",
        items: textSchema(1, 1000),
      },
      failure: {
        anyOf: [MATERIAL_FAILURE_SCHEMA, { type: "null" }],
      },
      user_gate: { type: ["object", "null"] },
      resume: MATERIAL_RESUME_SCHEMA,
    },
  };
  if (kind !== "book") return base;
  return {
    anyOf: [
      base,
      {
        ...base,
        required: [
          ...base.required,
          "expected_slots",
          "present_slots",
          "missing_slots",
        ],
        properties: {
          ...base.properties,
          // Inventory semantics are a complete-Book cross-artifact join.
          // Earlier terminals may carry it only as diagnostic state.
          expected_slots: {},
          present_slots: {},
          missing_slots: {},
        },
      },
    ],
  };
}

export function stageUserGate(receipt, payload = {}) {
  const issue = stageIssue(receipt);
  const terminal = receipt.terminal;
  return {
    schema_version: "quasi.user-gate.stage/0.1",
    operation_key: receipt.operation,
    kind: "stage_needs_input",
    issue,
    candidates: Array.isArray(terminal.candidates)
      ? terminal.candidates
      : [],
    conflicts: Array.isArray(terminal.conflicts)
      ? terminal.conflicts
      : [],
    question: issue.user_question,
    ...payload,
  };
}

export function failureUserGate(failure) {
  const issue = {
    code: failure.code,
    operation: failure.operation_key,
    summary: failure.message,
    user_question: failure.message,
    retryable: failure.retryable,
  };
  return {
    schema_version: "quasi.user-gate.stage/0.1",
    operation_key: failure.operation_key,
    kind: "stage_needs_input",
    issue,
    candidates: [],
    conflicts: [],
    question: failure.message,
  };
}

export function bookAcquireAllowedSources(operation, slug) {
  const paths = operation && operation.allowed_output_paths;
  if (
    !Array.isArray(paths) ||
    paths.length < 1 ||
    paths.length > 2 ||
    new Set(paths).size !== paths.length
  )
    return null;
  const sources = paths.map((path) => ({
    path,
    format: path.endsWith(".epub")
      ? "epub"
      : path.endsWith(".pdf")
        ? "pdf"
        : null,
  }));
  return sources.some(
    ({ path, format }) =>
      format === null || path !== `sources/${slug}.${format}`,
  )
    ? null
    : sources;
}

function stageGateBinding(receipt) {
  const paperAcquire =
    receipt.kind === "paper" && receipt.stage === "download";
  const bookAcquire =
    receipt.kind === "book" && receipt.stage === "download";
  const operationKey = paperAcquire
    ? "paper.acquire"
    : bookAcquire
      ? "book.acquire"
      : `${receipt.kind}.prepare`;
  const operation = Array.isArray(receipt.operations)
    ? [...receipt.operations]
        .reverse()
        .find(
          (item) =>
            item.operation === operationKey &&
            item.material_key === receipt.material_key,
        )
    : null;
  if (!record(operation)) return null;

  const root = `processing/chapters/${receipt.id}`;
  const allowedSources = bookAcquire
    ? bookAcquireAllowedSources(operation, receipt.id)
    : null;
  const schema = paperAcquire
    ? paperAcquire.schema({
        materialKey: receipt.material_key,
        output: `sources/${receipt.id}.pdf`,
        doi: operation.doi,
      })
    : bookAcquire && allowedSources
      ? bookAcquireStageSchema({
          materialKey: receipt.material_key,
          slug: receipt.id,
          allowedSources,
          yearDecision: null,
        })
      : receipt.kind === "paper"
        ? paperPrepare.schema({
            materialKey: receipt.material_key,
            source: `sources/${receipt.id}.pdf`,
            normalized: `processing/papers/${receipt.id}/source.txt`,
            recoverySource: `processing/papers/${receipt.id}/ocr.pdf`,
            recoveryText: `processing/papers/${receipt.id}/ocr.txt`,
          })
        : receipt.kind === "book" &&
            ["epub", "pdf"].includes(operation.format)
          ? bookPrepareStageSchema({
              materialKey: receipt.material_key,
              source: `sources/${receipt.id}.${operation.format}`,
              format: operation.format,
              normalized: `${root}/source.txt`,
              recoverySource: `${root}/ocr.pdf`,
              recoveryText: `${root}/ocr.txt`,
              outputDir: root,
              manifest: `${root}/manifest.json`,
            })
          : null;
  if (schema === null) return null;

  const resume = receipt.kind === "paper"
    ? {
        operation_key: "paper.user-gate",
        stage: receipt.stage,
      }
    : bookAcquire
      ? {
          operation_key: "book.user-gate",
          stage: "download",
          policy: "human-year-decision-or-correct-request",
        }
      : {
          operation_key: "book.user-gate",
          stage: "prepare",
          policy: "answer-the-stage-question",
        };
  const payload = bookAcquire
    ? {
        year_evidence: operation.terminal.year_evidence,
        tmp_path: operation.terminal.tmp_path,
        proposed_actions: operation.terminal.proposed_actions,
      }
    : {};
  return {
    operation,
    schema,
    stage: paperAcquire || bookAcquire ? "download" : "prepare",
    resume,
    payload,
    bookAcquire,
  };
}

export function validUserGate(gate, receipt, context = {}) {
  if (gate === null) return receipt.status !== "needs_input";
  if (!record(gate) || receipt.status !== "needs_input")
    return false;
  const binding = stageGateBinding(receipt);
  if (!binding) return false;
  const { operation } = binding;
  if (
    !validateSchema(binding.schema, operation) ||
    operation.terminal.status !== "needs_input" ||
    receipt.stage !== binding.stage
  )
    return false;
  if (
    binding.bookAcquire &&
    !validYearEvidence(
      operation.terminal.year_evidence,
      context.expectedYear,
    )
  )
    return false;
  return (
    sameClosedValue(
      gate,
      stageUserGate(operation, binding.payload),
    ) &&
    sameClosedValue(receipt.resume, binding.resume) &&
    sameClosedValue(receipt.failure, {
      code: operation.terminal.issue.code,
      operation_key: operation.operation,
      outcome: "known",
      retryable:
        receipt.kind === "book"
          ? operation.terminal.issue.retryable
          : false,
      message: operation.terminal.issue.summary,
    })
  );
}
