// Shared strict admission for one child MaterialReceipt at a collection or
// research join. The dispatch seam is host-pluggable, so a join admits a
// complete child only when the disk oracle re-proves its identity and canonical
// artifacts. The receipt remains authoritative only for its terminal and,
// until audit gains a durable disk record, its clean final-audit result.

import {
  exactKeys,
  sameClosedValue,
  validateSchema,
  validText,
} from "../runtime.mjs";
import {
  MATERIAL_SEARCH_STAGE_CONTRACT,
  materialSearchStageSchema,
} from "../operations/acquire.mjs";
import {
  bookAcquire,
  bookAudit,
} from "../operations/rows/book.mjs";
import { memberAdmissionProbe } from "../operations/rows/member.mjs";
import { paperAudit } from "../operations/rows/paper.mjs";
import {
  applyBookYearDecision,
  ingressUserGate,
  validResolvedIngressEvidence,
  validYearDecisionEnvelope,
} from "./ingress.mjs";
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
      bookAudit.schema({
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
    bookAudit.contract.statuses.complete(last) === true &&
    last.remaining_violations === 0 &&
    last.escalated.length === 0
  );
}

const exactStage = (value, name, complete) =>
  record(value) &&
  exactKeys(value, ["stage", "complete", "evidence"]) &&
  value.stage === name &&
  value.complete === complete &&
  Array.isArray(value.evidence) &&
  new Set(value.evidence).size === value.evidence.length &&
  value.evidence.every((path) => validText(path, 1, 1000));

const exactEvidence = (stage, expected) =>
  stage.evidence.length === expected.length &&
  stage.evidence.every((path, index) => path === expected[index]);

function expectedDiskIdentity(demand) {
  const meta = demand.meta;
  if (
    !record(meta) ||
    !validText(meta.title, 1, 500) ||
    !Array.isArray(meta.authors) ||
    meta.authors.length < 1 ||
    meta.authors.some((author) => !validText(author, 1, 200)) ||
    !Number.isInteger(meta.year)
  )
    return null;
  return {
    title: meta.title,
    authors: meta.authors,
    year: meta.year,
  };
}

function diskCanonicalArtifacts(oracle, demand) {
  const stages = oracle.stages;
  const expectedIdentity = expectedDiskIdentity(demand);
  if (
    oracle.schema_version !== "quasi.status/0.1" ||
    oracle.kind !== demand.kind ||
    oracle.slug !== demand.id ||
    oracle.next_stage !== null ||
    !record(oracle.refs) ||
    Object.keys(oracle.refs).length !== 0 ||
    !Array.isArray(stages) ||
    !sameClosedValue(oracle.identity, expectedIdentity)
  )
    return null;

  const canonical = canonicalMemberPath(demand.kind, demand.id);
  if (demand.kind === "paper") {
    if (
      stages.length !== 4 ||
      !exactStage(stages[0], "acquire", true) ||
      !exactStage(stages[1], "prepare", true) ||
      !exactStage(stages[2], "analyse", true) ||
      !exactStage(stages[3], "audit", null) ||
      !exactEvidence(stages[0], [`sources/${demand.id}.pdf`]) ||
      stages[1].evidence.length < 1 ||
      stages[1].evidence.some(
        (path) =>
          ![
            `processing/papers/${demand.id}/source.txt`,
            `processing/papers/${demand.id}/ocr.txt`,
          ].includes(path),
      ) ||
      !exactEvidence(stages[2], [canonical]) ||
      stages[3].evidence.length !== 0
    )
      return null;
    return [
      {
        role: "canonical",
        path: canonical,
        exists: true,
        usable: true,
        producer: "member.admission-probe",
      },
    ];
  }

  const root = `vault/books/${demand.id}`;
  const chapterPattern = new RegExp(
    `^${root}/ch(\\d{2,3}[a-z]{0,2})-([a-z0-9][a-z0-9-]{0,79})\\.md$`,
  );
  if (
    stages.length !== 5 ||
    !exactStage(stages[0], "acquire", true) ||
    !exactStage(stages[1], "prepare", true) ||
    !exactStage(stages[2], "analyse", true) ||
    !exactStage(stages[3], "synthesise", true) ||
    !exactStage(stages[4], "audit", null) ||
    stages[0].evidence.length < 1 ||
    stages[0].evidence.some(
      (path) =>
        ![
          `sources/${demand.id}.epub`,
          `sources/${demand.id}.pdf`,
        ].includes(path),
    ) ||
    stages[1].evidence.length < 2 ||
    stages[1].evidence[0] !==
      `processing/chapters/${demand.id}/manifest.json` ||
    stages[1].evidence
      .slice(1)
      .some(
        (path) =>
          !path.startsWith(`processing/chapters/${demand.id}/`),
      ) ||
    stages[2].evidence.length < 1 ||
    !exactEvidence(stages[3], [canonical]) ||
    stages[4].evidence.length !== 0
  )
    return null;
  const matches = stages[2].evidence.map((path) =>
    path.match(chapterPattern),
  );
  if (
    matches.some((match) => match === null) ||
    new Set(matches.map((match) => match[1])).size !== matches.length ||
    new Set(matches.map((match) => match[2])).size !== matches.length
  )
    return null;
  return [
    {
      role: "canonical",
      path: canonical,
      exists: true,
      usable: true,
      producer: "member.admission-probe",
    },
    ...stages[2].evidence.map((path) => ({
      role: "chapter_canonical",
      path,
      exists: true,
      usable: true,
      producer: "member.admission-probe",
    })),
  ];
}

function validBookAcquireStage(operation, demand, expectedYear) {
  const allowedSources = bookAcquireAllowedSources(
    operation,
    demand.id,
  );
  return !!(
    allowedSources &&
    validateSchema(
      bookAcquire.schema({
        materialKey: demand.material_key,
        allowedSources,
        yearDecision: null,
      }),
      operation,
    ) &&
    operation.terminal.status === "complete" &&
    bookAcquire.contract.statuses.complete(operation, {
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

export function strictChildResult(
  result,
  demand,
  oracle = null,
  { includeCanonicalArtifacts = false } = {},
) {
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
  let canonicalArtifacts = [];
  if (receipt.status === "complete") {
    canonicalArtifacts = record(oracle)
      ? diskCanonicalArtifacts(oracle, demand)
      : null;
    if (
      !["created", "reused", "repaired"].includes(
        receipt.disposition,
      ) ||
      receipt.stage !== "audit" ||
      receipt.failure !== null ||
      receipt.user_gate !== null ||
      receipt.resume !== null ||
      receipt.operations.length < 1 ||
      canonicalArtifacts === null ||
      !cleanMaterialAudit(receipt, demand)
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
    ...(includeCanonicalArtifacts
      ? { canonical_artifacts: canonicalArtifacts }
      : {}),
    receipt,
    year_warning: bookYearWarning(receipt, demand),
    title: demand.title,
  };
}

export async function admitChildResult(
  runtime,
  result,
  demand,
  options = {},
) {
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
  if (receipt.status !== "complete")
    return strictChildResult(result, demand, null, options);
  const context = {
    materialKey: demand.material_key,
    kind: demand.kind,
    slug: demand.id,
    replay: "safe",
    artifactRoles: [],
    unknownFailureCode: "material.readonly_outcome_unknown",
  };
  const spec = memberAdmissionProbe.spec(context);
  const run = await runtime.operate(
    memberAdmissionProbe.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label: `${demand.id}:admission-probe`,
      schema: memberAdmissionProbe.schema(context),
    },
    spec,
  );
  if (run.edge !== "ok") return null;
  return strictChildResult(
    result,
    demand,
    run.receipt.oracle,
    options,
  );
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
      status === "complete" ? admitted.canonical_artifacts : [],
    user_gate: receipt.user_gate,
    issue,
    resume: projectResume(receipt.resume),
  };
}

// One authoritative Batch/Collection-facing projection. It accepts either an
// exact child MaterialReceipt or an ingress terminal that stopped before a
// material identity existed. Public/legacy status fields are deliberately not
// consulted, and the projection never carries the child's full raw result.
export function projectChildMaterialResult(result, expected, oracle = null) {
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
    const admitted = strictChildResult(result, demand, oracle, {
      includeCanonicalArtifacts: true,
    });
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

export async function admitChildMaterialResult(
  runtime,
  result,
  expected,
) {
  if (
    !record(result) ||
    !record(expected) ||
    !["book", "paper"].includes(expected.kind)
  )
    return null;
  const receipt = result.material_receipt;
  const ingress = result.ingress_receipt;
  if (!record(receipt))
    return projectChildMaterialResult(result, expected);
  if (receipt.status !== "complete")
    return projectChildMaterialResult(result, expected);
  if (
    !record(ingress) ||
    !validIngressReceipt(ingress, expected) ||
    ingress.status !== "resolved" ||
    !record(ingress.identity) ||
    ingress.identity.slug !== receipt.id
  )
    return null;
  const demand = {
    material_key: `${receipt.kind}:${receipt.id}`,
    kind: receipt.kind,
    id: receipt.id,
    title: null,
    meta: ingress.identity.meta,
  };
  const admitted = await admitChildResult(runtime, result, demand, {
    includeCanonicalArtifacts: true,
  });
  if (!admitted) return null;
  return projectAdmittedMaterial(admitted, ingress);
}
