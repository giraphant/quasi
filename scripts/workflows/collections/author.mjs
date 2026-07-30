import {
  AUTHOR_DISCOVER_BOOKS_SCHEMA,
  AUTHOR_DISCOVER_PAPERS_SCHEMA,
  AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA,
  authorDiscoveryPrompt,
  authorResolveMembershipPrompt,
} from "../operations/acquire.mjs";
import {
  AUTHOR_AUDIT_SCHEMA,
  authorAuditLegacyPrompt,
} from "../operations/audit.mjs";
import {
  AUTHOR_SYNTHESISE_SCHEMA,
  authorSynthesiseOperationPrompt,
} from "../operations/synthesise.mjs";

const AUTHOR_RECEIPT_VERSION =
  "quasi.collection.author.receipt/0.1";
const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.1";
const AUTHOR_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const CATEGORIES = new Set([
  "monograph",
  "edited-volume",
  "handbook",
  "other",
]);

const exactKeys = (value, keys) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

const optionalText = (value, max) =>
  value == null || value === "" || validText(value, 1, max);

const sameStrings = (left, right) =>
  Array.isArray(left) &&
  Array.isArray(right) &&
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

const operationFailure = (
  code,
  operationKey,
  outcome = "known",
  retryable = false,
  message = null,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable,
  ...(message ? { message } : {}),
});

const runtimeUnknown = (receipt) =>
  !!(
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    receipt.failure &&
    receipt.failure.outcome === "unknown"
  );

function validFailure(
  failure,
  operationKey,
  outcome,
  retryable,
) {
  return !!(
    exactKeys(failure, [
        "code",
        "operation_key",
        "outcome",
        "retryable",
        "message",
      ]) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === operationKey &&
    failure.outcome === outcome &&
    failure.retryable === retryable &&
    (failure.message === null ||
      validText(failure.message, 1, 4000))
  );
}

function validateIdentity(name, meta) {
  if (typeof name !== "string" || !AUTHOR_SLUG.test(name))
    return {
      ok: false,
      code: "author.slug_invalid",
      message: "author slug is not canonical",
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "author metadata must be an object",
    };
  const full = Object.prototype.hasOwnProperty.call(
    meta,
    "full_name",
  )
    ? meta.full_name
    : Object.prototype.hasOwnProperty.call(meta, "fullName")
      ? meta.fullName
      : name;
  const topic = meta.topic || "";
  if (!validText(full, 2, 200))
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "full_name is missing or invalid",
    };
  if (
    typeof topic !== "string" ||
    topic !== topic.trim() ||
    topic.length > 500 ||
    CONTROL_CHARS.test(topic)
  )
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "topic is invalid",
    };
  const rawBooks =
    meta.maxBooks === undefined ? 5 : meta.maxBooks;
  const rawPapers =
    meta.maxPapers === undefined ? 10 : meta.maxPapers;
  if (
    !Number.isInteger(rawBooks) ||
    rawBooks < 0 ||
    rawBooks > 5 ||
    !Number.isInteger(rawPapers) ||
    rawPapers < 0 ||
    rawPapers > 10 ||
    rawBooks + rawPapers < 1
  )
    return {
      ok: false,
      code: "author.budget_invalid",
      message:
        "maxBooks must be 0..5, maxPapers 0..10, and total positive",
    };
  const normalized = {
    full_name: full,
    topic,
    maxBooks: rawBooks,
    maxPapers: rawPapers,
  };
  return {
    ok: true,
    meta: normalized,
    fingerprint: JSON.stringify(normalized),
  };
}

function createState(name, meta) {
  return {
    name,
    full: meta.full_name,
    topic: meta.topic,
    collectionKey: `author:${name}`,
    output: `vault/authors/${name}.md`,
    maxBooks: meta.maxBooks,
    maxPapers: meta.maxPapers,
    operations: [],
    audit: [],
    members: [],
    artifact: null,
    outputExists: false,
    repaired: false,
    disposition: null,
    discoveryFailures: [],
    warnings: [
      "author discovery and audit remain explicitly named legacy composites",
    ],
    budgets: {
      books: { used: 0, limit: meta.maxBooks },
      papers: { used: 0, limit: meta.maxPapers },
      synthesis: { used: 0, limit: 1 },
      repair: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 2 },
    },
  };
}

function collectionReceipt(
  state,
  {
    status,
    stage,
    failure = null,
    disposition = null,
  },
) {
  return {
    schema_version: AUTHOR_RECEIPT_VERSION,
    collection_key: state.collectionKey,
    kind: "author",
    id: state.name,
    status,
    disposition:
      disposition ||
      (["complete", "partial"].includes(status)
        ? state.repaired
          ? "repaired"
          : state.disposition || "created"
        : null),
    stage,
    members: state.members,
    artifact: state.artifact,
    operations: state.operations,
    audit: state.audit,
    budgets: state.budgets,
    warnings: state.warnings,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "author.reconcile" }
        : null,
  };
}

function legacyCounts(state) {
  const complete = state.members.filter(
    (member) => member.status === "complete",
  );
  const books = complete.filter(
    (member) => member.kind === "book",
  );
  const papers = complete.filter(
    (member) => member.kind === "paper",
  );
  const failedBooks = state.members.filter(
    (member) =>
      member.kind === "book" && member.status !== "complete",
  );
  const failedPapers = state.members.filter(
    (member) =>
      member.kind === "paper" && member.status !== "complete",
  );
  return {
    books,
    papers,
    legacy: {
      books: books.length,
      papers: papers.length,
      book_slugs: books.map((member) => member.id),
      paper_slugs: papers.map((member) => member.id),
      book_failures: failedBooks.length,
      paper_failures: failedPapers.length,
      year_warnings: (() => {
        const warnings = state.members
          .filter(
            (member) =>
              member.kind === "book" && member.year_warning,
          )
          .map((member) => ({
            slug: member.id,
            ...member.year_warning,
          }));
        return warnings.length ? warnings : null;
      })(),
    },
  };
}

function terminal(
  state,
  legacyStatus,
  collectionStatus,
  stage,
  failure = null,
  extra = {},
) {
  const counts = legacyCounts(state);
  return {
    name: state.name,
    status: legacyStatus,
    ...counts.legacy,
    ...extra,
    collection_receipt: collectionReceipt(state, {
      status: collectionStatus,
      stage,
      failure,
    }),
  };
}

function rejectedResult(name, validation, conflict = false) {
  const canonical =
    typeof name === "string" && AUTHOR_SLUG.test(name);
  const state = createState(
    canonical ? name : typeof name === "string" ? name : "",
    {
      full_name:
        canonical && validation.meta
          ? validation.meta.full_name
          : canonical
            ? name
            : "",
      topic: "",
      maxBooks: 0,
      maxPapers: 0,
    },
  );
  const failure = operationFailure(
    conflict ? "author.identity_conflict" : validation.code,
    "author.identity",
    "known",
    false,
    validation.message,
  );
  return terminal(
    state,
    "blocked",
    "blocked",
    "identity",
    failure,
  );
}

function validBookCandidate(candidate, full) {
  return !!(
    exactKeys(candidate, [
      "kind",
      "slug",
      "title",
      "authors",
      "year",
      "isbn",
      "publisher",
      "category",
      "confidence",
    ]) &&
    candidate.kind === "book" &&
    AUTHOR_SLUG.test(candidate.slug) &&
    validText(candidate.title, 1, 500) &&
    Array.isArray(candidate.authors) &&
    candidate.authors.length >= 1 &&
    candidate.authors.length <= 32 &&
    candidate.authors.every((author) =>
      validText(author, 1, 200),
    ) &&
    candidate.authors.includes(full) &&
    Number.isInteger(candidate.year) &&
    candidate.year >= 1500 &&
    candidate.year <= 2030 &&
    optionalText(candidate.isbn, 100) &&
    validText(candidate.publisher, 2, 500) &&
    CATEGORIES.has(candidate.category) &&
    ["high", "medium"].includes(candidate.confidence)
  );
}

function validPaperCandidate(candidate, full) {
  return !!(
    exactKeys(candidate, [
      "kind",
      "slug",
      "title",
      "authors",
      "year",
      "doi",
      "oa_url",
      "url",
      "journal",
      "confidence",
    ]) &&
    candidate.kind === "paper" &&
    AUTHOR_SLUG.test(candidate.slug) &&
    validText(candidate.title, 1, 500) &&
    Array.isArray(candidate.authors) &&
    candidate.authors.length >= 1 &&
    candidate.authors.length <= 32 &&
    candidate.authors.every((author) =>
      validText(author, 1, 200),
    ) &&
    candidate.authors.includes(full) &&
    Number.isInteger(candidate.year) &&
    candidate.year >= 1500 &&
    candidate.year <= 2030 &&
    optionalText(candidate.doi, 300) &&
    optionalText(candidate.oa_url, 2048) &&
    optionalText(candidate.url, 2048) &&
    validText(candidate.journal, 1, 500) &&
    ["high", "medium"].includes(candidate.confidence)
  );
}

function strictDiscovery(
  receipt,
  state,
  kind,
  count,
) {
  const key =
    kind === "book"
      ? "author.discover-books"
      : "author.discover-papers";
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "collection_key",
      "kind",
      "full_name",
      "topic",
      "count",
      "candidates",
      "failure",
    ]) ||
    receipt.schema_version !==
      `quasi.operation.${key}.receipt/0.1` ||
    receipt.key !== key ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.collection_key !== state.collectionKey ||
    receipt.kind !== kind ||
    receipt.full_name !== state.full ||
    receipt.topic !== state.topic ||
    receipt.count !== count ||
    !Array.isArray(receipt.candidates) ||
    receipt.candidates.length > count ||
    receipt.candidates.some((candidate) =>
      kind === "book"
        ? !validBookCandidate(candidate, state.full)
        : !validPaperCandidate(candidate, state.full),
    )
  )
    return false;
  if (receipt.status === "succeeded")
    return receipt.failure === null;
  return (
    receipt.status === "failed" &&
    receipt.candidates.length === 0 &&
    validFailure(receipt.failure, key, "known", false)
  );
}

function emptyDiscovery(state, kind) {
  const key =
    kind === "book"
      ? "author.discover-books"
      : "author.discover-papers";
  return {
    schema_version: `quasi.operation.${key}.receipt/0.1`,
    key,
    effect: "readonly",
    status: "succeeded",
    attempt: 1,
    collection_key: state.collectionKey,
    kind,
    full_name: state.full,
    topic: state.topic,
    count: 0,
    candidates: [],
    failure: null,
  };
}

function strictMembership(
  receipt,
  state,
  candidates,
) {
  const requests = candidates.map(({ kind, slug }) => ({
    kind,
    slug,
  }));
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "collection_key",
      "output_path",
      "output_exists",
      "requests",
      "resolved",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.author.resolve-membership.receipt/0.1" ||
    receipt.key !== "author.resolve-membership" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.collection_key !== state.collectionKey ||
    receipt.output_path !== state.output ||
    typeof receipt.output_exists !== "boolean" ||
    !Array.isArray(receipt.requests) ||
    !Array.isArray(receipt.resolved) ||
    receipt.requests.length !== requests.length ||
    !requests.every((request, index) => {
      const echoed = receipt.requests[index];
      return (
        exactKeys(echoed, ["kind", "slug"]) &&
        echoed.kind === request.kind &&
        echoed.slug === request.slug
      );
    })
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.output_exists === false &&
      receipt.resolved.length === 0 &&
      validFailure(
        receipt.failure,
        "author.resolve-membership",
        "known",
        false,
      )
    );
  if (receipt.status !== "succeeded" || receipt.failure !== null)
    return false;
  if (receipt.resolved.length !== requests.length) return false;
  return requests.every((request, index) => {
    const row = receipt.resolved[index];
    if (
      !exactKeys(row, [
        "kind",
        "requested_slug",
        "vault_slug",
        "path",
        "match",
      ]) ||
      row.kind !== request.kind ||
      row.requested_slug !== request.slug
    )
      return false;
    if (row.vault_slug === null)
      return row.path === null && row.match === null;
    if (
      typeof row.vault_slug !== "string" ||
      !AUTHOR_SLUG.test(row.vault_slug) ||
      !validText(row.match, 1, 100)
    )
      return false;
    const expected =
      row.kind === "book"
        ? `vault/books/${row.vault_slug}/00-overview.md`
        : `vault/papers/${row.vault_slug}.md`;
    return row.path === expected;
  });
}

function demandIdentity(candidate) {
  if (candidate.kind === "book")
    return JSON.stringify({
      title: candidate.title,
      authors: candidate.authors,
      year: candidate.year,
      isbn: candidate.isbn,
      publisher: candidate.publisher,
      category: candidate.category,
    });
  return JSON.stringify({
    title: candidate.title,
    authors: candidate.authors,
    year: candidate.year,
    doi: candidate.doi,
    oa_url: candidate.oa_url,
    url: candidate.url,
    journal: candidate.journal,
  });
}

function buildDemands(candidates, resolved) {
  const demands = [];
  const byKey = new Map();
  for (let index = 0; index < candidates.length; index += 1) {
    const candidate = candidates[index];
    const row = resolved[index];
    const id = row.vault_slug || candidate.slug;
    const materialKey = `${candidate.kind}:${id}`;
    const identity = demandIdentity(candidate);
    const existing = byKey.get(materialKey);
    if (existing) {
      if (existing.identity !== identity)
        return {
          ok: false,
          failure: operationFailure(
            "author.membership_identity_conflict",
            "author.resolve-membership",
            "known",
            false,
            `conflicting identities resolved to ${materialKey}`,
          ),
        };
      continue;
    }
    const meta =
      candidate.kind === "book"
        ? {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            isbn: candidate.isbn,
            publisher: candidate.publisher,
            category: candidate.category,
            confidence: "verified",
          }
        : {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            doi: candidate.doi,
            oa_url: candidate.oa_url,
            url: candidate.url,
            journal: candidate.journal,
            confidence: "verified",
          };
    const demand = {
      kind: candidate.kind,
      id,
      material_key: materialKey,
      title: candidate.title,
      meta,
      identity,
    };
    byKey.set(materialKey, demand);
    demands.push(demand);
  }
  return { ok: true, demands };
}

function canonicalPath(kind, id) {
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
      canonicalPath(demand.kind, demand.id),
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

function strictChildResult(result, demand) {
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
    !["complete", "blocked", "failed"].includes(receipt.status) ||
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
  const expected = canonicalPath(demand.kind, demand.id);
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

function malformedChild(demand, message) {
  return {
    material_key: demand.material_key,
    kind: demand.kind,
    id: demand.id,
    status: "blocked",
    canonical_path: null,
    receipt: null,
    year_warning: null,
    title: demand.title,
    failure: operationFailure(
      "author.child_receipt_invalid",
      "author.join",
      "unknown",
      false,
      message,
    ),
  };
}

function synthesisInputs(state) {
  return state.members
    .filter((member) => member.status === "complete")
    .map((member) => ({
      material_key: member.material_key,
      kind: member.kind,
      id: member.id,
      path: member.canonical_path,
      title: member.title,
    }));
}

function strictSynthesis(receipt, state, inputs, mode) {
  const keys = inputs.map((input) => input.material_key);
  const paths = inputs.map((input) => input.path);
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "input_material_keys",
      "input_paths",
      "output_path",
      "artifact_roles",
      "action",
      "materials_analyzed",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.author.synthesise.receipt/0.1" ||
    receipt.key !== "author.synthesise" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    !sameStrings(receipt.input_material_keys, keys) ||
    !sameStrings(receipt.input_paths, paths) ||
    receipt.output_path !== state.output ||
    !sameStrings(receipt.artifact_roles, ["canonical"]) ||
    !Number.isInteger(receipt.materials_analyzed) ||
    receipt.materials_analyzed < 0 ||
    !["create", "repair", "reconciled"].includes(
      receipt.action,
    )
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      receipt.materials_analyzed === inputs.length &&
      (mode === "create"
        ? receipt.action === "create"
        : ["repair", "reconciled"].includes(receipt.action))
    );
  if (receipt.status === "failed")
    return (
      receipt.action === mode &&
      validFailure(
        receipt.failure,
        "author.synthesise",
        "known",
        false,
      )
    );
  return (
    receipt.status === "blocked" &&
    receipt.action === mode &&
    validFailure(
      receipt.failure,
      "author.synthesise",
      "unknown",
      false,
    )
  );
}

function strictAudit(receipt, state) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "target_path",
      "remaining_violations",
      "escalated",
      "mutated_paths",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.author.audit.legacy.receipt/0.1" ||
    receipt.key !== "author.audit.legacy" ||
    receipt.effect !== "writer" ||
    receipt.attempt !== 1 ||
    receipt.target_path !== state.output ||
    !Number.isInteger(receipt.remaining_violations) ||
    receipt.remaining_violations < 0 ||
    !Array.isArray(receipt.escalated) ||
    !Array.isArray(receipt.mutated_paths) ||
    receipt.escalated.some(
      (diagnostic) =>
        !exactKeys(diagnostic, ["path", "kind", "reason"]) ||
        !validText(diagnostic.path, 1, 2048) ||
        !validText(diagnostic.kind, 1, 200) ||
        !validText(diagnostic.reason, 1, 4000),
    ) ||
    receipt.mutated_paths.some(
      (path) => !validText(path, 1, 2048),
    )
  )
    return false;
  if (receipt.status === "clean")
    return (
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0
    );
  if (receipt.status === "partial")
    return (
      receipt.remaining_violations > 0 &&
      receipt.escalated.length ===
        receipt.remaining_violations
    );
  return (
    receipt.status === "error" &&
    receipt.remaining_violations === 0 &&
    receipt.escalated.length === 0
  );
}

function ownedAuditPaths(receipt, output) {
  return [
    ...receipt.escalated.map((item) => item.path),
    ...receipt.mutated_paths,
  ].every((path) => path === output);
}

async function runSynthesis(
  runtime,
  state,
  inputs,
  mode,
  diagnostics,
  label,
) {
  const receipt = await runtime.runOperation(
    authorSynthesiseOperationPrompt(
      state.name,
      state.full,
      state.topic,
      inputs,
      mode,
      diagnostics,
    ),
    {
      phase: "Author",
      agentType: "quasi:synthesis-agent",
      label,
      schema: AUTHOR_SYNTHESISE_SCHEMA,
    },
    {
      key: "author.synthesise",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "author.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  if (!strictSynthesis(receipt, state, inputs, mode)) {
    const failure = operationFailure(
      "author.writer_receipt_mismatch",
      "author.synthesise",
      "unknown",
      false,
      "writer receipt did not prove the exact contract",
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "synthesis",
        failure,
      ),
    };
  }
  if (receipt.status === "blocked")
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "synthesis",
        receipt.failure,
      ),
    };
  if (receipt.status === "failed")
    return {
      terminal: terminal(
        state,
        "synth_failed",
        "failed",
        "synthesis",
        receipt.failure,
        { notes: receipt.failure.message || receipt.failure.code },
      ),
    };
  state.artifact = {
    role: "canonical",
    path: state.output,
    exists: true,
    producer:
      receipt.action === "reconciled"
        ? "author.synthesise:reconciled"
        : "author.synthesise",
  };
  if (receipt.action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (receipt.action === "reconciled") {
    state.disposition = state.disposition || "reused";
  } else {
    state.disposition = "created";
  }
  return { receipt };
}

async function runAudit(runtime, state, pass, label) {
  const receipt = await runtime.runOperation(
    authorAuditLegacyPrompt(state.name, pass),
    {
      phase: "Author",
      agentType: "quasi:audit-agent",
      label,
      schema: AUTHOR_AUDIT_SCHEMA,
    },
    {
      key: "author.audit.legacy",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "author.writer_outcome_unknown",
    },
  );
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (!strictAudit(receipt, state)) {
    const failure = operationFailure(
      "author.writer_receipt_mismatch",
      "author.audit.legacy",
      "unknown",
      false,
      "writer receipt did not prove the exact audit contract",
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "audit",
        failure,
      ),
    };
  }
  if (!ownedAuditPaths(receipt, state.output)) {
    const failure = operationFailure(
      "author.repair_owner_unknown",
      "author.audit.legacy",
      "known",
      false,
      "audit named a path outside the exact Author product",
    );
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        failure,
        { escalated: receipt.escalated },
      ),
    };
  }
  if (receipt.status === "error") {
    const failure = operationFailure(
      "author.audit_failed",
      "author.audit.legacy",
      "known",
      false,
      "legacy audit transaction reported an error",
    );
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        failure,
        { escalated: [] },
      ),
    };
  }
  if (receipt.mutated_paths.includes(state.output)) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return {
    clean: receipt.status === "clean",
    escalated: receipt.escalated,
  };
}

async function processAuthorStrict(
  runtime,
  dispatchMaterial,
  name,
  meta,
) {
  const state = createState(name, meta);
  const discoveryTasks = [];
  if (state.maxBooks > 0)
    discoveryTasks.push(() =>
      runtime
        .runOperation(
        authorDiscoveryPrompt(
          name,
          state.full,
          state.topic,
          "book",
          state.maxBooks,
        ),
        {
          phase: "Author",
          agentType: "quasi:discovery-agent",
          label: `discover-books:${name}`,
          schema: AUTHOR_DISCOVER_BOOKS_SCHEMA,
        },
        {
          key: "author.discover-books",
          effect: "readonly",
          retry: "safe",
          replay: "safe",
          artifactRoles: [],
          unknownFailureCode:
            "author.readonly_outcome_unknown",
        },
        )
        .then((receipt) => ({ kind: "book", receipt })),
    );
  if (state.maxPapers > 0)
    discoveryTasks.push(() =>
      runtime
        .runOperation(
        authorDiscoveryPrompt(
          name,
          state.full,
          state.topic,
          "paper",
          state.maxPapers,
        ),
        {
          phase: "Author",
          agentType: "quasi:discovery-agent",
          label: `discover-papers:${name}`,
          schema: AUTHOR_DISCOVER_PAPERS_SCHEMA,
        },
        {
          key: "author.discover-papers",
          effect: "readonly",
          retry: "safe",
          replay: "safe",
          artifactRoles: [],
          unknownFailureCode:
            "author.readonly_outcome_unknown",
        },
        )
        .then((receipt) => ({ kind: "paper", receipt })),
    );
  const discoveries = await runtime.parallel(discoveryTasks);
  const bookDiscovery =
    discoveries.find((item) => item.kind === "book")?.receipt ||
    emptyDiscovery(state, "book");
  const paperDiscovery =
    discoveries.find((item) => item.kind === "paper")?.receipt ||
    emptyDiscovery(state, "paper");
  state.operations.push(bookDiscovery, paperDiscovery);
  if (
    !strictDiscovery(
      bookDiscovery,
      state,
      "book",
      state.maxBooks,
    ) ||
    !strictDiscovery(
      paperDiscovery,
      state,
      "paper",
      state.maxPapers,
    )
  ) {
    const failure = operationFailure(
      "author.discovery_receipt_invalid",
      "author.discovery",
      runtimeUnknown(bookDiscovery) ||
        runtimeUnknown(paperDiscovery)
        ? "unknown"
        : "known",
      false,
      "discovery receipt did not prove the exact contract",
    );
    return terminal(
      state,
      "all_failed",
      "failed",
      "discovery",
      failure,
    );
  }
  if (bookDiscovery.status === "failed")
    state.discoveryFailures.push(bookDiscovery.failure);
  if (paperDiscovery.status === "failed")
    state.discoveryFailures.push(paperDiscovery.failure);
  const candidates = [
    ...bookDiscovery.candidates,
    ...paperDiscovery.candidates,
  ];
  if (!candidates.length) {
    const failure = operationFailure(
      state.discoveryFailures.length
        ? "author.discovery_failed"
        : "author.no_works",
      "author.discovery",
      "known",
      false,
      state.discoveryFailures.length
        ? "no usable candidate was discovered"
        : "discovery returned no representative works",
    );
    return terminal(
      state,
      state.discoveryFailures.length
        ? "all_failed"
        : "no_works",
      "failed",
      "discovery",
      failure,
    );
  }

  const membership = await runtime.runOperation(
    authorResolveMembershipPrompt(
      name,
      state.output,
      candidates,
    ),
    {
      phase: "Author",
      agentType: "general-purpose",
      label: `resolve-membership:${name}`,
      schema: AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA,
    },
    {
      key: "author.resolve-membership",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: [],
      unknownFailureCode: "author.readonly_outcome_unknown",
    },
  );
  state.operations.push(membership);
  if (!strictMembership(membership, state, candidates)) {
    const failure = operationFailure(
      "author.membership_receipt_invalid",
      "author.resolve-membership",
      runtimeUnknown(membership) ? "unknown" : "known",
      false,
      "membership receipt did not correlate exact requests",
    );
    return terminal(
      state,
      "blocked",
      "blocked",
      "membership",
      failure,
    );
  }
  if (membership.status === "failed")
    return terminal(
      state,
      "all_failed",
      "failed",
      "membership",
      membership.failure,
    );
  state.outputExists = membership.output_exists;
  const grouped = buildDemands(candidates, membership.resolved);
  if (!grouped.ok)
    return terminal(
      state,
      "all_failed",
      "failed",
      "membership",
      grouped.failure,
    );

  runtime.log(
    `${name}: strict Author membership ${grouped.demands.length} unique works`,
  );
  const childResults = await runtime.parallel(
    grouped.demands.map((demand) => async () => {
      try {
        const result = await dispatchMaterial(
          demand.kind,
          { slug: demand.id, meta: demand.meta },
          demand.kind === "book" ? { batchYear: true } : {},
        );
        return { demand, result };
      } catch (error) {
        return {
          demand,
          error:
            (error && error.message) || String(error),
        };
      }
    }),
  );
  state.members = childResults.map(({ demand, result, error }) =>
    error
      ? malformedChild(demand, error)
      : strictChildResult(result, demand) ||
        malformedChild(
          demand,
          "child result did not carry its exact MaterialReceipt",
        ),
  );
  state.budgets.books.used = state.members.filter(
    (member) => member.kind === "book",
  ).length;
  state.budgets.papers.used = state.members.filter(
    (member) => member.kind === "paper",
  ).length;
  const inputs = synthesisInputs(state);
  if (!inputs.length) {
    const failure = operationFailure(
      "author.no_complete_members",
      "author.join",
      "known",
      false,
      "no child Material Loop completed with an exact canonical",
    );
    return terminal(
      state,
      "all_failed",
      "failed",
      "join",
      failure,
      { tried: state.members.length },
    );
  }

  state.budgets.synthesis.used = 1;
  const initialMode = state.outputExists ? "repair" : "create";
  const initialDiagnostics = state.outputExists
    ? [
        {
          path: state.output,
          kind: "membership_refresh",
          reason:
            "reconcile the existing Author product against the exact completed corpus",
        },
      ]
    : [];
  const synthesis = await runSynthesis(
    runtime,
    state,
    inputs,
    initialMode,
    initialDiagnostics,
    `synthesise-author:${name}`,
  );
  if (synthesis.terminal) return synthesis.terminal;

  let audited = await runAudit(
    runtime,
    state,
    1,
    `audit-author:${name}`,
  );
  if (audited.terminal) return audited.terminal;
  if (!audited.clean) {
    state.budgets.repair.used = 1;
    const repaired = await runSynthesis(
      runtime,
      state,
      inputs,
      "repair",
      audited.escalated,
      `repair-author:${name}`,
    );
    if (repaired.terminal) return repaired.terminal;
    audited = await runAudit(
      runtime,
      state,
      2,
      `audit2-author:${name}`,
    );
    if (audited.terminal) return audited.terminal;
    if (!audited.clean) {
      const failure = operationFailure(
        "author.repair_exhausted",
        "author.audit.legacy",
        "known",
        false,
        "Author output remains non-clean after one repair",
      );
      return terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        failure,
        { escalated: audited.escalated },
      );
    }
  }

  const incomplete =
    state.discoveryFailures.length > 0 ||
    state.members.some(
      (member) => member.status !== "complete",
    );
  return terminal(
    state,
    "ok",
    incomplete ? "partial" : "complete",
    "complete",
  );
}

export async function processAuthor(
  runtime,
  materials,
  name,
  rawMeta,
) {
  runtime.phase("Author");
  const validation = validateIdentity(name, rawMeta);
  if (!validation.ok)
    return rejectedResult(name, validation);
  const dispatchMaterial =
    typeof materials === "function"
      ? materials
      : (kind, args, opts = {}) =>
          kind === "book"
            ? materials.processBook(
                args.slug,
                args.meta || args,
                opts,
              )
            : materials.processPaper(
                args.slug,
                args.meta || args,
              );
  return runtime.coalesce(
    `author:${name}`,
    validation.fingerprint,
    () =>
      processAuthorStrict(
        runtime,
        dispatchMaterial,
        name,
        validation.meta,
      ),
    () =>
      rejectedResult(
        name,
        {
          ...validation,
          code: "author.identity_conflict",
          message:
            "conflicting Author identity for one collection key",
        },
        true,
      ),
  );
}
