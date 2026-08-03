// Small deterministic helpers shared by Operation schema builders.  This
// module contains no material policy and no Agent workflow.

export const composedSchema = (base, overrides, branches) => ({
  ...base,
  properties: { ...base.properties, ...overrides },
  anyOf: Object.values(branches),
});

export const posixSingleQuote = (value) =>
  `'${String(value).split("'").join("'\"'\"'")}'`;

export const ATTEMPT_SCHEMA = {
  type: "array",
  maxItems: 64,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["source", "status", "error"],
    properties: {
      source: { type: "string", minLength: 1, maxLength: 200 },
      status: { type: "string", minLength: 1, maxLength: 100 },
      error: { type: ["string", "null"], maxLength: 4000 },
    },
  },
};

export const issueSchema = (
  operation,
  codes,
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
    code: Array.isArray(codes)
      ? { type: "string", enum: codes }
      : { const: codes },
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

export const PREPARE_STEP_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["capability", "outcome", "summary"],
  properties: {
    capability: { type: "string", minLength: 1, maxLength: 100 },
    outcome: {
      type: "string",
      enum: ["observed", "created", "reused", "repaired", "failed"],
    },
    summary: { type: "string", minLength: 1, maxLength: 2000 },
  },
};

export const AUDIT_DIAGNOSTIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["path", "kind", "reason"],
  properties: {
    path: { type: "string", minLength: 1, maxLength: 2048 },
    kind: { type: "string", minLength: 1, maxLength: 200 },
    reason: { type: "string", minLength: 1, maxLength: 4000 },
  },
};

export const actionPayloads = ({ mode, writeState = false }) => ({
  complete: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: {
        type: "string",
        enum:
          mode === "create"
            ? ["create", "reconciled"]
            : ["repair", "reconciled"],
      },
      ...(writeState
        ? {
            write_state: {
              type: "string",
              enum: ["written", "not_written"],
            },
          }
        : {}),
    },
  },
  failed: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState ? { write_state: { const: "not_written" } } : {}),
    },
  },
  blocked: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState ? { write_state: { const: "unknown" } } : {}),
    },
  },
});

const auditComplete = (receipt) =>
  receipt.remaining_violations === 0
    ? receipt.escalated.length === 0
    : receipt.remaining_violations === receipt.escalated.length;

const auditEnvelopeExtras = () => ({});

export const makeAuditRow = ({
  operation,
  refs,
  targetRole,
  artifactRoles,
  exactPaths = false,
  envelopeExtras = auditEnvelopeExtras,
}) => ({
  operation,
  stage: "Audit",
  effect: "writer",
  agentType: "quasi:audit-agent",
  refs,
  payloadProperties: ({ target, pass }) => ({
    required: [
      "target_path",
      "pass",
      ...(artifactRoles === undefined ? [] : ["artifact_roles"]),
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ],
    properties: {
      target_path: { const: target },
      pass: { const: pass },
      ...(artifactRoles === undefined
        ? {}
        : { artifact_roles: { const: artifactRoles } }),
      remaining_violations: { type: "integer", minimum: 0 },
      escalated: {
        type: "array",
        items: exactPaths
          ? {
              ...AUDIT_DIAGNOSTIC_SCHEMA,
              properties: {
                ...AUDIT_DIAGNOSTIC_SCHEMA.properties,
                path: {
                  const: target,
                  ...AUDIT_DIAGNOSTIC_SCHEMA.properties.path,
                },
              },
            }
          : AUDIT_DIAGNOSTIC_SCHEMA,
      },
      mutated_paths: {
        type: "array",
        uniqueItems: true,
        items: exactPaths
          ? { const: target, type: "string", maxLength: 2048 }
          : { type: "string", maxLength: 2048 },
      },
    },
  }),
  complete: auditComplete,
  envelope: (context, resolvedRefs) => {
    const extras = envelopeExtras(context, resolvedRefs);
    return {
      schema_version: "quasi.stage.request/0.2",
      operation,
      stage: "Audit",
      material_key: resolvedRefs.materialKey ?? context.materialKey,
      ...(extras.beforeEffect || {}),
      effect: "writer",
      ...(extras.beforePass || {}),
      pass: resolvedRefs.pass,
      mode: resolvedRefs.pass === 1 ? "audit" : "re-audit",
      target: { role: targetRole, path: resolvedRefs.target },
      ...(extras.afterTarget || {}),
    };
  },
});
