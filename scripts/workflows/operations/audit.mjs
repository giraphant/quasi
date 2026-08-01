import { validText } from "../runtime.mjs";
import { stageContract, stageReceiptSchema } from "../stage.mjs";

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
