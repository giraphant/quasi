// Shared strict admission for one child MaterialReceipt at a collection or
// research join. The dispatch seam is host-pluggable (native subagents in the
// Codex driver, scripted children in tests), so a join must re-prove the exact
// identity binding, canonical artifact, and clean final audit before admitting
// a member — a child result is not trusted merely for arriving in-process.

import { exactKeys, validText } from "../runtime.mjs";

const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.1";

const sameStrings = (left, right) =>
  Array.isArray(left) &&
  Array.isArray(right) &&
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

export function canonicalMemberPath(kind, id) {
  return kind === "book"
    ? `vault/books/${id}/00-overview.md`
    : `vault/papers/${id}.md`;
}

function validMaterialFailure(failure) {
  if (
    !failure ||
    typeof failure !== "object" ||
    Array.isArray(failure) ||
    ![4, 5].includes(Object.keys(failure).length) ||
    !["code", "operation_key", "outcome", "retryable"].every(
      (key) =>
        Object.prototype.hasOwnProperty.call(failure, key),
    ) ||
    Object.keys(failure).some(
      (key) =>
        ![
          "code",
          "operation_key",
          "outcome",
          "retryable",
          "message",
        ].includes(key),
    )
  )
    return false;
  return (
    validText(failure.code, 1, 200) &&
    validText(failure.operation_key, 1, 200) &&
    ["known", "unknown"].includes(failure.outcome) &&
    typeof failure.retryable === "boolean" &&
    (failure.message === undefined ||
      failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

function validMaterialArtifact(artifact) {
  return !!(
    exactKeys(artifact, [
      "role",
      "path",
      "exists",
      "usable",
      "producer",
    ]) &&
    validText(artifact.role, 1, 100) &&
    validText(artifact.path, 1, 1000) &&
    artifact.exists === true &&
    [null, true, false].includes(artifact.usable) &&
    validText(artifact.producer, 1, 200)
  );
}

function validAuditDiagnostic(diagnostic) {
  return !!(
    exactKeys(diagnostic, ["path", "kind", "reason"]) &&
    validText(diagnostic.path, 1, 1000) &&
    validText(diagnostic.kind, 1, 200) &&
    validText(diagnostic.reason, 1, 4000)
  );
}

function validPaperAudit(audit, expectedPath) {
  return !!(
    exactKeys(audit, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "target_path",
      "remaining_violations",
      "escalated",
    ]) &&
    audit.schema_version ===
      "quasi.operation.paper.audit.agent-receipt/0.1" &&
    audit.key === "paper.audit" &&
    audit.effect === "writer" &&
    audit.status === "clean" &&
    audit.attempt === 1 &&
    audit.target_path === expectedPath &&
    audit.remaining_violations === 0 &&
    Array.isArray(audit.escalated) &&
    audit.escalated.length === 0
  );
}

function validBookAuditItem(audit, expectedPath) {
  return !!(
    exactKeys(audit, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "target_path",
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ]) &&
    audit.schema_version ===
      "quasi.operation.book.audit.receipt/0.1" &&
    audit.key === "book.audit" &&
    audit.effect === "writer" &&
    ["clean", "partial", "error"].includes(audit.status) &&
    audit.attempt === 1 &&
    audit.target_path === expectedPath &&
    Number.isInteger(audit.remaining_violations) &&
    audit.remaining_violations >= 0 &&
    Array.isArray(audit.escalated) &&
    audit.escalated.every(validAuditDiagnostic) &&
    Array.isArray(audit.mutated_paths) &&
    audit.mutated_paths.every((path) =>
      validText(path, 1, 1000),
    )
  );
}

function cleanMaterialAudit(receipt, demand) {
  if (demand.kind === "paper")
    return validPaperAudit(
      receipt.audit,
      canonicalMemberPath(demand.kind, demand.id),
    );
  const expected = `vault/books/${demand.id}`;
  if (
    !Array.isArray(receipt.audit) ||
    receipt.audit.length < 1 ||
    !receipt.audit.every((audit) =>
      validBookAuditItem(audit, expected),
    )
  )
    return false;
  const last = receipt.audit[receipt.audit.length - 1];
  return (
    last.status === "clean" &&
    last.remaining_violations === 0 &&
    last.escalated.length === 0
  );
}

export function strictChildResult(result, demand) {
  if (
    !result ||
    typeof result !== "object" ||
    Array.isArray(result) ||
    result.slug !== demand.id ||
    !result.material_receipt ||
    typeof result.material_receipt !== "object" ||
    Array.isArray(result.material_receipt)
  )
    return null;
  const receipt = result.material_receipt;
  const baseKeys = [
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
    "resume",
  ];
  const bookInventoryKeys = [
    "expected_slots",
    "present_slots",
    "missing_slots",
  ];
  const topLevelClosed =
    exactKeys(receipt, baseKeys) ||
    (demand.kind === "book" &&
      exactKeys(receipt, [...baseKeys, ...bookInventoryKeys]));
  if (
    !topLevelClosed ||
    receipt.schema_version !== MATERIAL_RECEIPT_VERSION ||
    receipt.material_key !== demand.material_key ||
    receipt.kind !== demand.kind ||
    receipt.id !== demand.id ||
    !["complete", "needs_input", "blocked", "failed"].includes(
      receipt.status,
    ) ||
    !Array.isArray(receipt.artifacts) ||
    !Array.isArray(receipt.operations) ||
    receipt.operations.some(
      (operation) =>
        !operation ||
        typeof operation !== "object" ||
        Array.isArray(operation),
    ) ||
    !Array.isArray(receipt.warnings) ||
    receipt.warnings.some(
      (warning) => !validText(warning, 1, 1000),
    ) ||
    !exactKeys(receipt.freshness, ["observation", "basis"]) ||
    receipt.freshness.observation !== "unknown" ||
    receipt.freshness.basis !==
      "operation-receipts-and-final-audit" ||
    typeof receipt.stage !== "string" ||
    receipt.artifacts.some(
      (artifact) => !validMaterialArtifact(artifact),
    )
  )
    return null;
  const expected = canonicalMemberPath(demand.kind, demand.id);
  const allCanonicals = receipt.artifacts.filter(
    (artifact) => artifact && artifact.role === "canonical",
  );
  const canonicals = allCanonicals.filter(
    (artifact) =>
      artifact.path === expected &&
      artifact.exists === true,
  );
  if (receipt.status === "complete") {
    if (
      !["created", "reused", "repaired"].includes(
        receipt.disposition,
      ) ||
      receipt.stage !== "audit" ||
      receipt.failure !== null ||
      receipt.resume !== null ||
      receipt.operations.length < 1 ||
      allCanonicals.length !== 1 ||
      canonicals.length !== 1 ||
      !cleanMaterialAudit(receipt, demand)
    )
      return null;
    if (
      demand.kind === "book" &&
      Object.prototype.hasOwnProperty.call(
        receipt,
        "expected_slots",
      ) &&
      (!Array.isArray(receipt.expected_slots) ||
        !Array.isArray(receipt.present_slots) ||
        !Array.isArray(receipt.missing_slots) ||
        !sameStrings(
          receipt.expected_slots,
          receipt.present_slots,
        ) ||
        receipt.expected_slots.some(
          (slot) => !/^\d{2,3}$/.test(slot),
        ) ||
        receipt.missing_slots.length !== 0)
    )
      return null;
  } else if (
    receipt.disposition !== null ||
    !validMaterialFailure(receipt.failure) ||
    (receipt.status === "failed" && receipt.resume !== null) ||
    (receipt.status === "needs_input" &&
      !(
        receipt.resume &&
        typeof receipt.resume === "object" &&
        !Array.isArray(receipt.resume)
      )) ||
    (receipt.status === "blocked" &&
      !(
        receipt.resume === null ||
        (receipt.resume &&
          typeof receipt.resume === "object" &&
          !Array.isArray(receipt.resume))
      ))
  ) {
    return null;
  }
  return {
    material_key: demand.material_key,
    kind: demand.kind,
    id: demand.id,
    status: receipt.status,
    canonical_path:
      receipt.status === "complete" ? expected : null,
    receipt,
    year_warning:
      demand.kind === "book" && result.year_warning
        ? result.year_warning
        : null,
    title: demand.title,
  };
}
