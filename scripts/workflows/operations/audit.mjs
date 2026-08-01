import { validText } from "../runtime.mjs";
import { stageContract, stageReceiptSchema } from "../stage.mjs";
import { composedSchema } from "./shared.mjs";

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

const AUDIT_DIAGNOSTIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["path", "kind", "reason"],
  properties: {
    path: { type: "string" },
    kind: { type: "string" },
    reason: { type: "string" },
  },
};

const auditStageSchema = ({
  operation,
  materialKey,
  target,
  pass,
  artifactRoles = null,
}) =>
  stageReceiptSchema({
    operation,
    stage: "Audit",
    materialKey,
    effect: "writer",
    required: [
      "target_path",
      "pass",
      ...(artifactRoles ? ["artifact_roles"] : []),
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ],
    properties: {
      target_path: { const: target },
      pass: { const: pass },
      ...(artifactRoles
        ? { artifact_roles: { const: artifactRoles } }
        : {}),
      remaining_violations: { type: "integer", minimum: 0 },
      escalated: {
        type: "array",
        items: AUDIT_DIAGNOSTIC_SCHEMA,
      },
      mutated_paths: {
        type: "array",
        uniqueItems: true,
        items: { type: "string" },
      },
    },
  });

// Clean and partial are successful Audit terminal outcomes. The evidence carries
// the distinction: a clean result has no remaining violations or escalations.
const completeAudit = (receipt) =>
  receipt.remaining_violations === 0
    ? receipt.escalated.length === 0
    : receipt.remaining_violations === receipt.escalated.length;

const auditStageContract = ({ schema, complete, failed = () => true }) => {
  const contract = stageContract({ schema, complete });
  return {
    ...contract,
    statuses: {
      ...contract.statuses,
      failed,
    },
  };
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

const closedAuditFailure = (receipt) =>
  legacyAuditReported(receipt) &&
  receipt.remaining_violations === 0 &&
  receipt.escalated.length === 0;

export const authorAuditStageSchema = ({
  materialKey,
  target,
  pass,
}) =>
  auditStageSchema({
    operation: "author.audit",
    materialKey,
    target,
    pass,
    artifactRoles: ["canonical"],
  });

export const AUTHOR_AUDIT_STAGE_CONTRACT = auditStageContract({
  schema: authorAuditStageSchema({
    materialKey: "author:placeholder",
    target: "vault/authors/placeholder.md",
    pass: 1,
  }),
  complete: (receipt) =>
    legacyAuditReported(receipt) && completeAudit(receipt),
  failed: closedAuditFailure,
});

export function authorAuditPrompt(name, pass) {
  const output = `vault/authors/${name}.md`;
  const request = {
    schema_version:
      "quasi.operation.author.audit.request/0.1",
    operation: "author.audit",
    stage: "Audit",
    material_key: `author:${name}`,
    collection_key: `author:${name}`,
    effect: "writer",
    pass,
    mode: pass === 1 ? "audit" : "re-audit",
    target: { role: "canonical", path: output },
    exact_output: output,
    composite_debt: true,
  };
  return JSON.stringify(request, null, 2);
}

// Strict Topic recall-only audit remains on its legacy receipt contract below.
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
