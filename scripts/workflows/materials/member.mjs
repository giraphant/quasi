// Shared strict admission for one child MaterialReceipt at a collection or
// research join. The dispatch seam is host-pluggable (native subagents in the
// Codex driver, scripted children in tests), so a join must re-prove the exact
// identity binding, canonical artifact, and clean final audit before admitting
// a member — a child result is not trusted merely for arriving in-process.

import {
  exactKeys,
  sameClosedValue,
  validateSchema,
  validText,
} from "../runtime.mjs";
import {
  BOOK_ACQUIRE_STAGE_CONTRACT,
  MATERIAL_SEARCH_STAGE_CONTRACT,
  bookAcquireStageSchema,
  materialSearchStageSchema,
} from "../operations/acquire.mjs";
import {
  BOOK_AUDIT_STAGE_CONTRACT,
  bookAuditStageSchema,
} from "../operations/audit.mjs";
import { paperAudit } from "../operations/rows/paper.mjs";
import {
  applyBookYearDecision,
  ingressUserGate,
  validResolvedIngressEvidence,
  validYearDecisionEnvelope,
} from "./ingress.mjs";
import {
  validChapterSlot,
} from "../operations/extract.mjs";
import {
  MATERIAL_FAILURE_SCHEMA,
  MATERIAL_RESUME_SCHEMA,
  bookAcquireAllowedSources,
  materialReceiptSchema,
  validUserGate,
} from "./receipt.mjs";
const INGRESS_RECEIPT_VERSION =
  "quasi.material-ingress.receipt/0.2";
const MATERIAL_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

const record = (value) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value)
  );

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

function projectFailure(failure) {
  return {
    code: failure.code,
    operation_key: failure.operation_key,
    outcome: failure.outcome,
    retryable: failure.retryable,
    message: failure.message || null,
  };
}

function projectResume(resume) {
  if (resume === null) return null;
  return {
    operation_key: resume.operation_key,
    ...(resume.stage === undefined ? {} : { stage: resume.stage }),
    ...(resume.policy === undefined
      ? {}
      : { policy: resume.policy }),
  };
}

function validBlockedResume(receipt) {
  if (receipt.kind === "paper") {
    if (
      receipt.stage === "identity" &&
      receipt.failure.operation_key === "paper.identity" &&
      receipt.operations.length === 0
    )
      return receipt.resume === null;
    return sameClosedValue(receipt.resume, {
      operation_key: "paper.reconcile",
    });
  }
  if (receipt.failure.outcome === "unknown")
    return sameClosedValue(receipt.resume, {
      operation_key: "book.reconcile",
    });
  return sameClosedValue(receipt.resume, {
    operation_key: "book.user-gate",
    stage: receipt.stage,
    policy:
      receipt.stage === "download"
        ? "human-year-decision-or-correct-request"
        : "caller-correct-request",
  });
}

function validPaperAudit(audit, materialKey, expectedPath) {
  return !!(
    audit &&
    validateSchema(
      paperAudit.schema({
        materialKey,
        target: expectedPath,
        pass: audit.pass,
      }),
      audit,
    ) &&
    audit.terminal.status === "complete" &&
    paperAudit.contract.statuses.complete(audit) === true
  );
}

function validBookAuditItem(audit, materialKey, expectedPath) {
  return !!(
    audit &&
    validateSchema(
      bookAuditStageSchema({
        materialKey,
        target: expectedPath,
        pass: audit.pass,
      }),
      audit,
    )
  );
}

function cleanMaterialAudit(receipt, demand) {
  if (demand.kind === "paper")
    return validPaperAudit(
      receipt.audit,
      demand.material_key,
      canonicalMemberPath(demand.kind, demand.id),
    );
  const expected = `vault/books/${demand.id}`;
  if (
    !Array.isArray(receipt.audit) ||
    receipt.audit.length < 1 ||
    !receipt.audit.every((audit) =>
      validBookAuditItem(audit, demand.material_key, expected),
    )
  )
    return false;
  const last = receipt.audit[receipt.audit.length - 1];
  return (
    last.terminal.status === "complete" &&
    BOOK_AUDIT_STAGE_CONTRACT.statuses.complete(last) === true &&
    last.remaining_violations === 0 &&
    last.escalated.length === 0
  );
}

function validBookCanonicalSet(receipt, demand) {
  if (
    !Array.isArray(receipt.expected_slots) ||
    !Array.isArray(receipt.present_slots) ||
    !Array.isArray(receipt.missing_slots) ||
    !sameStrings(receipt.expected_slots, receipt.present_slots) ||
    receipt.expected_slots.length < 1 ||
    new Set(receipt.expected_slots).size !==
      receipt.expected_slots.length ||
    receipt.expected_slots.some(
      (slot) => !validChapterSlot(slot),
    ) ||
    receipt.missing_slots.length !== 0
  )
    return false;
  const chapterCanonicals = receipt.artifacts.filter(
    (artifact) => artifact.role === "chapter_canonical",
  );
  if (chapterCanonicals.length !== receipt.expected_slots.length)
    return false;
  const root = `vault/books/${demand.id}/`;
  const paths = new Set();
  const chapterSlugs = new Set();
  const slots = [];
  for (const artifact of chapterCanonicals) {
    if (
      artifact.producer !== "chapter.analyse" ||
      artifact.usable === false ||
      !artifact.path.startsWith(root)
    )
      return false;
    const relative = artifact.path.slice(root.length);
    const match = relative.match(
      /^ch([^-]+)-([a-z0-9][a-z0-9-]{0,79})\.md$/,
    );
    if (
      !match ||
      !validChapterSlot(match[1]) ||
      paths.has(artifact.path) ||
      chapterSlugs.has(match[2])
    )
      return false;
    paths.add(artifact.path);
    chapterSlugs.add(match[2]);
    slots.push(match[1]);
  }
  return sameStrings(slots, receipt.expected_slots);
}

function validBookAcquireStage(operation, demand, expectedYear) {
  const allowedSources = bookAcquireAllowedSources(
    operation,
    demand.id,
  );
  return !!(
    allowedSources &&
    validateSchema(
      bookAcquireStageSchema({
        materialKey: demand.material_key,
        slug: demand.id,
        allowedSources,
        yearDecision: null,
      }),
      operation,
    ) &&
    operation.terminal.status === "complete" &&
    BOOK_ACQUIRE_STAGE_CONTRACT.statuses.complete(operation, {
      allowedSources,
      expectedYear,
      batchAcceptYear: true,
      yearDecision: null,
    }) === true
  );
}

function bookYearWarning(receipt, demand) {
  if (demand.kind !== "book") return null;
  const expectedYear = demand.meta && demand.meta.year;
  if (!Number.isInteger(expectedYear)) return null;
  const acquire = [...receipt.operations]
    .reverse()
    .find(
      (operation) =>
        operation.operation === "book.acquire" &&
        operation.stage === "Acquire" &&
        operation.material_key === demand.material_key,
    );
  const evidence = acquire && acquire.year_evidence;
  return evidence &&
    validBookAcquireStage(acquire, demand, expectedYear) &&
    evidence.verdict !== "MATCH"
    ? evidence
    : null;
}

export function strictChildResult(result, demand) {
  if (
    !record(result) ||
    result.slug !== demand.id ||
    !validateSchema(
      materialReceiptSchema({
        materialKey: demand.material_key,
        kind: demand.kind,
        id: demand.id,
      }),
      result.material_receipt,
    )
  )
    return null;
  const receipt = result.material_receipt;
  if (
    !validUserGate(receipt.user_gate, receipt, {
      expectedYear: demand.meta && demand.meta.year,
    })
  )
    return null;

  const expected = canonicalMemberPath(demand.kind, demand.id);
  const canonicalProducers =
    demand.kind === "book"
      ? new Set([
          "book.synthesise",
          "book.synthesise:reconciled",
        ])
      : new Set([
          "paper.analyse",
          "paper.analyse:reconciled",
        ]);
  const allCanonicals = receipt.artifacts.filter(
    (artifact) => artifact.role === "canonical",
  );
  const canonicals = allCanonicals.filter(
    (artifact) =>
      artifact.path === expected &&
      artifact.usable !== false &&
      canonicalProducers.has(artifact.producer),
  );
  if (receipt.status === "complete") {
    if (
      !["created", "reused", "repaired"].includes(
        receipt.disposition,
      ) ||
      receipt.stage !== "audit" ||
      receipt.failure !== null ||
      receipt.user_gate !== null ||
      receipt.resume !== null ||
      receipt.operations.length < 1 ||
      allCanonicals.length !== 1 ||
      canonicals.length !== 1 ||
      !cleanMaterialAudit(receipt, demand)
    )
      return null;
    if (
      (demand.kind === "book" &&
        !validBookCanonicalSet(receipt, demand)) ||
      (demand.kind === "paper" &&
        receipt.artifacts.some(
          (artifact) => artifact.role === "chapter_canonical",
        ))
    )
      return null;
  } else if (
    receipt.disposition !== null ||
    !validateSchema(MATERIAL_FAILURE_SCHEMA, receipt.failure) ||
    (receipt.status === "failed" && receipt.resume !== null) ||
    (receipt.status === "needs_input" && receipt.resume === null) ||
    (receipt.status === "blocked" &&
      !validBlockedResume(receipt))
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
    year_warning: bookYearWarning(receipt, demand),
    title: demand.title,
  };
}

function validIngressReceipt(receipt, expected) {
  const expectedKind = expected.kind;
  const expectedRequestKey = expected.ok
    ? expected.requestKey
    : `${expectedKind}:invalid-request`;
  const expectedQuery = expected.ok ? expected.query : null;
  if (
    !exactKeys(receipt, [
      "schema_version",
      "request_key",
      "kind",
      "status",
      "stage",
      "request",
      "operations",
      "identity",
      "failure",
      "user_gate",
      "resume",
    ]) ||
    receipt.schema_version !== INGRESS_RECEIPT_VERSION ||
    receipt.kind !== expectedKind ||
    receipt.request_key !== expectedRequestKey ||
    !sameClosedValue(receipt.request, expectedQuery) ||
    !validText(receipt.request_key, 1, 300) ||
    !receipt.request_key.startsWith(`${expectedKind}:`) ||
    !["resolved", "needs_input", "blocked", "failed"].includes(
      receipt.status,
    ) ||
    !validText(receipt.stage, 1, 100) ||
    !(receipt.request === null || record(receipt.request)) ||
    !Array.isArray(receipt.operations) ||
    receipt.operations.some((operation) => !record(operation)) ||
    !validateSchema(MATERIAL_RESUME_SCHEMA, receipt.resume)
  )
    return false;
  if (receipt.status === "resolved")
    return !!(
      exactKeys(receipt.identity, ["slug", "meta"]) &&
      MATERIAL_SLUG.test(receipt.identity.slug) &&
      record(receipt.identity.meta) &&
      receipt.failure === null &&
      receipt.user_gate === null &&
      receipt.resume === null &&
      validResolvedIngressEvidence(
        receipt,
        expected,
        expected.yearDecision || null,
      )
    );
  if (
    receipt.identity !== null ||
    !validateSchema(MATERIAL_FAILURE_SCHEMA, receipt.failure)
  )
    return false;
  const expectedGate = ingressUserGate(
    receipt.status,
    receipt.operations,
    receipt.failure,
  );
  if (
    (receipt.status === "needs_input"
      ? !sameClosedValue(receipt.user_gate, expectedGate)
      : receipt.user_gate !== null)
  )
    return false;
  const exactResume = (operationKey) =>
    exactKeys(receipt.resume, ["operation_key"]) &&
    receipt.resume.operation_key === operationKey;
  if (!expected.ok)
    return !!(
      receipt.operations.length === 0 &&
      receipt.status === "needs_input" &&
      receipt.stage === "search" &&
      sameClosedValue(receipt.failure, {
        code: "material.request_invalid",
        operation_key: "material.search",
        outcome: "known",
        retryable: false,
        message: expected.message,
      }) &&
      exactResume("material.user-gate")
    );

  if (receipt.operations.length === 0) {
    const conflict = sameClosedValue(receipt.failure, {
      code: "material.request_identity_conflict",
      operation_key: "material.search",
      outcome: "known",
      retryable: false,
      message:
        "same-run raw requests share one request key but disagree",
    });
    const invalidYearDecision =
      expected.kind === "book" &&
      expected.yearDecision !== null &&
      !validYearDecisionEnvelope(expected.yearDecision) &&
      sameClosedValue(receipt.failure, {
        code: "book.year_decision_invalid",
        operation_key: "material.search",
        outcome: "known",
        retryable: false,
        message: "year_decision is not one exact prior Book gate",
      });
    return !!(
      (conflict || invalidYearDecision) &&
      receipt.status === "needs_input" &&
      receipt.stage === "search" &&
      exactResume("material.user-gate")
    );
  }
  if (receipt.operations.length !== 1) return false;
  const search = receipt.operations[0];
  const schemaValid = validateSchema(
    materialSearchStageSchema({
      request_key: expected.requestKey,
      kind: expected.kind,
    }),
    search,
  );
  if (schemaValid) {
    const terminal = search.terminal.status;
    if (terminal === "complete") {
      const contractComplete =
        MATERIAL_SEARCH_STAGE_CONTRACT.statuses.complete(search) ===
        true;
      if (!contractComplete)
        return !!(
          receipt.status === "failed" &&
          receipt.stage === "search" &&
          receipt.resume === null &&
          sameClosedValue(receipt.failure, {
            code: "material.search_receipt_invalid",
            operation_key: "material.search",
            outcome: "known",
            retryable: false,
            message:
              "Search did not return the exact identity contract",
          })
        );
      const adjusted =
        expected.kind === "book"
          ? applyBookYearDecision(
              search.identity,
              expected.yearDecision || null,
            )
          : { ok: true, picked: search.identity };
      if (!adjusted.ok)
        return !!(
          receipt.status === "needs_input" &&
          receipt.stage === "search" &&
          exactResume("material.user-gate") &&
          sameClosedValue(receipt.failure, {
            code: "book.year_decision_invalid",
            operation_key: "material.search",
            outcome: "known",
            retryable: false,
            message: adjusted.message,
          })
        );
      const owner = search.local_owner;
      const ownerMismatch =
        owner !== null &&
        owner.identity_slug !== adjusted.picked.slug;
      return !!(
        ownerMismatch &&
        receipt.status === "failed" &&
        receipt.stage === "resolve" &&
        receipt.resume === null &&
        sameClosedValue(receipt.failure, {
          code: "material.search_owner_mismatch",
          operation_key: "material.search",
          outcome: "known",
          retryable: false,
          message:
            "Search did not resolve the selected canonical slug",
        })
      );
    }
    const issue = search.terminal.issue;
    const status =
      terminal === "needs_input"
        ? "needs_input"
        : terminal === "blocked"
          ? "blocked"
          : "failed";
    const outcome = terminal === "blocked" ? "unknown" : "known";
    const expectedFailure = {
      code: issue.code,
      operation_key: "material.search",
      outcome,
      retryable: issue.retryable,
      message: issue.user_question || issue.summary,
    };
    return !!(
      terminal !== "complete" &&
      receipt.status === status &&
      receipt.stage === "search" &&
      sameClosedValue(receipt.failure, expectedFailure) &&
      (status === "needs_input"
        ? exactResume("material.user-gate")
        : status === "blocked"
          ? exactResume("material.search")
          : receipt.resume === null)
    );
  }

  const runtimeUnknown = exactKeys(search, [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "artifact_roles",
    "replay",
    "signal",
    "failure",
  ]) &&
    search.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    search.key === "material.search" &&
    search.effect === "readonly" &&
    search.status === "failed" &&
    search.attempt === 1 &&
    Array.isArray(search.artifact_roles) &&
    search.artifact_roles.length === 0 &&
    search.replay === "safe" &&
    search.signal === null &&
    sameClosedValue(search.failure, {
      code: "material.readonly_outcome_unknown",
      operation_key: "material.search",
      outcome: "unknown",
      retryable: true,
    });
  if (runtimeUnknown)
    return !!(
      receipt.status === "blocked" &&
      receipt.stage === "search" &&
      exactResume("material.search") &&
      sameClosedValue(receipt.failure, {
        code: "material.readonly_outcome_unknown",
        operation_key: "material.search",
        outcome: "unknown",
        retryable: false,
        message: "material.search outcome was not observed",
      })
    );

  return !!(
    receipt.status === "failed" &&
    receipt.stage === "search" &&
    receipt.resume === null &&
    sameClosedValue(receipt.failure, {
      code: "material.search_receipt_invalid",
      operation_key: "material.search",
      outcome: "known",
      retryable: false,
      message: "Search did not return the exact identity contract",
    })
  );
}

function projectAdmittedMaterial(admitted, ingress) {
  const receipt = admitted.receipt;
  const status = receipt.status;
  const issue =
    status === "complete" ? null : projectFailure(receipt.failure);
  return {
    material_key: receipt.material_key,
    kind: receipt.kind,
    id: receipt.id,
    status,
    canonical_artifacts:
      status === "complete"
        ? receipt.artifacts.filter(
            (artifact) =>
              artifact.role === "canonical" ||
              artifact.role === "chapter_canonical",
          )
        : [],
    user_gate: receipt.user_gate,
    issue,
    resume: projectResume(receipt.resume),
  };
}

// One authoritative Batch/Collection-facing projection. It accepts either an
// exact child MaterialReceipt or an ingress terminal that stopped before a
// material identity existed. Public/legacy status fields are deliberately not
// consulted, and the projection never carries the child's full raw result.
export function projectChildMaterialResult(result, expected) {
  if (
    !record(result) ||
    !record(expected) ||
    !["book", "paper"].includes(expected.kind)
  )
    return null;
  const expectedKind = expected.kind;
  const hasIngress = Object.prototype.hasOwnProperty.call(
    result,
    "ingress_receipt",
  );
  const ingress = hasIngress ? result.ingress_receipt : null;
  if (!hasIngress || !validIngressReceipt(ingress, expected))
    return null;

  if (record(result.material_receipt)) {
    const receipt = result.material_receipt;
    if (
      receipt.kind !== expectedKind ||
      !validText(receipt.id, 1, 80) ||
      !MATERIAL_SLUG.test(receipt.id)
    )
      return null;
    const demand = {
      material_key: `${expectedKind}:${receipt.id}`,
      kind: expectedKind,
      id: receipt.id,
      title: null,
      meta: ingress.identity.meta,
    };
    const admitted = strictChildResult(result, demand);
    if (
      !admitted ||
      ingress.status !== "resolved" ||
      ingress.identity.slug !== receipt.id
    )
      return null;
    return projectAdmittedMaterial(admitted, ingress);
  }

  if (ingress.status === "resolved") return null;
  const issue = projectFailure(ingress.failure);
  const userGate =
    ingress.status === "needs_input"
      ? ingress.user_gate
      : null;
  if (ingress.status === "needs_input" && userGate === null)
    return null;
  return {
    material_key: null,
    kind: ingress.kind,
    id: null,
    status: ingress.status,
    canonical_artifacts: [],
    user_gate: userGate,
    issue,
    resume: projectResume(ingress.resume),
  };
}
