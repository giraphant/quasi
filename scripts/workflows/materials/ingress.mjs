import {
  MATERIAL_RECALL_SCHEMA,
  MATERIAL_RESOLVE_SCHEMA,
  MATERIAL_SEARCH_BOOK_SCHEMA,
  MATERIAL_SEARCH_PAPER_SCHEMA,
  materialRecallPrompt,
  materialResolvePrompt,
  materialSearchPrompt,
} from "../operations/acquire.mjs";

const INGRESS_RECEIPT_VERSION =
  "quasi.material-ingress.receipt/0.1";
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const BOOK_TEMP_PATH =
  /^\.quasi\/temp\/downloads\/[A-Za-z0-9][A-Za-z0-9._-]{0,220}\.(?:epub|pdf)$/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
const CATEGORIES = new Set([
  "monograph",
  "edited-volume",
  "handbook",
  "other",
]);
const LOOKUP_MISS = "__none__";

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
  value === null || validText(value, 1, max);

function sameClosedValue(left, right) {
  if (Array.isArray(left) || Array.isArray(right))
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) =>
        sameClosedValue(value, right[index]),
      )
    );
  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(right, key) &&
          sameClosedValue(left[key], right[key]),
      )
    );
  }
  return Object.is(left, right);
}

function cleanText(value) {
  if (value == null || value === "") return null;
  if (typeof value !== "string") return undefined;
  const cleaned = value.trim();
  return cleaned && !CONTROL_CHARS.test(cleaned)
    ? cleaned
    : undefined;
}

function cleanAuthors(raw) {
  if (raw == null || raw === "") return [];
  const values = Array.isArray(raw) ? raw : [raw];
  if (values.length > 32) return null;
  const authors = values.map(cleanText);
  return authors.every(
    (author) =>
      author !== undefined &&
      author !== null &&
      author.length <= 200,
  )
    ? authors
    : null;
}

function cleanYear(raw) {
  if (raw == null || raw === "") return null;
  const value =
    typeof raw === "string" && /^\d{4}$/.test(raw.trim())
      ? Number(raw.trim())
      : raw;
  return Number.isInteger(value) && value >= 1500 && value <= 2030
    ? value
    : undefined;
}

function slugPart(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function provisionalSlug(kind, query) {
  if (query.slug) return query.slug;
  const author = query.authors.length
    ? query.authors[0].split(/\s+/).at(-1)
    : null;
  const seed = (
    query.title
      ? [author, query.title, query.year]
      : [kind, kind === "book" ? query.isbn : query.doi]
  )
    .filter((value) => value != null)
    .join(" ");
  const candidate = slugPart(seed).slice(0, 80).replace(/-+$/g, "");
  return SLUG.test(candidate) ? candidate : `${kind}-request`;
}

function invalidRequest(kind, message) {
  return {
    ok: false,
    kind,
    message,
  };
}

function normaliseRequest(kind, args) {
  if (!["book", "paper"].includes(kind))
    return invalidRequest(kind, "kind must be book or paper");
  const nested =
    args &&
    args.request &&
    typeof args.request === "object" &&
    !Array.isArray(args.request)
      ? args.request
      : args &&
          args.meta &&
          typeof args.meta === "object" &&
          !Array.isArray(args.meta)
        ? args.meta
        : args;
  if (!nested || typeof nested !== "object" || Array.isArray(nested))
    return invalidRequest(kind, "material request must be an object");

  const rawSlug =
    args && Object.prototype.hasOwnProperty.call(args, "slug")
      ? args.slug
      : nested.slug;
  const slug =
    rawSlug == null || rawSlug === "" ? null : cleanText(rawSlug);
  if (
    slug === undefined ||
    (slug !== null && !SLUG.test(slug))
  )
    return invalidRequest(kind, "supplied slug is not canonical");

  const title = cleanText(nested.title);
  const authors = cleanAuthors(
    nested.authors == null ? nested.author : nested.authors,
  );
  const year = cleanYear(nested.year);
  if (
    title === undefined ||
    (title !== null && title.length > 500) ||
    authors === null ||
    year === undefined
  )
    return invalidRequest(
      kind,
      "title, authors, or year is malformed",
    );

  if (kind === "book") {
    const isbn = cleanText(nested.isbn);
    const publisher = cleanText(nested.publisher);
    const category =
      nested.category == null || nested.category === ""
        ? null
        : cleanText(nested.category);
    const format =
      nested.format == null || nested.format === ""
        ? null
        : cleanText(nested.format);
    if (
      isbn === undefined ||
      (isbn !== null && isbn.length > 100) ||
      publisher === undefined ||
      (publisher !== null && publisher.length > 500) ||
      category === undefined ||
      (category !== null && !CATEGORIES.has(category)) ||
      format === undefined ||
      (format !== null && !["epub", "pdf"].includes(format)) ||
      (!title && !isbn)
    )
      return invalidRequest(
        kind,
        "Book request needs a valid title or ISBN and bounded hints",
      );
    const query = {
      slug,
      title,
      authors,
      year,
      isbn,
      publisher,
      category,
      format,
    };
    const requestedSlug = provisionalSlug(kind, query);
    return {
      ok: true,
      kind,
      query,
      requestedSlug,
      requestKey: `${kind}:${requestedSlug}`,
    };
  }

  const doi = cleanText(nested.doi);
  const oaUrl = cleanText(nested.oa_url);
  const url = cleanText(nested.url);
  const journal = cleanText(nested.journal || nested.venue);
  if (
    doi === undefined ||
    (doi !== null && doi.length > 300) ||
    oaUrl === undefined ||
    (oaUrl !== null && oaUrl.length > 2048) ||
    url === undefined ||
    (url !== null && url.length > 2048) ||
    journal === undefined ||
    (journal !== null && journal.length > 500) ||
    (!title && !doi)
  )
    return invalidRequest(
      kind,
      "Paper request needs a valid title or DOI and bounded hints",
    );
  const query = {
    slug,
    title,
    authors,
    year,
    doi,
    oa_url: oaUrl,
    url,
    journal,
  };
  const requestedSlug = provisionalSlug(kind, query);
  return {
    ok: true,
    kind,
    query,
    requestedSlug,
    requestKey: `${kind}:${requestedSlug}`,
  };
}

function operationFailure(
  code,
  operationKey,
  outcome,
  message,
) {
  return {
    code,
    operation_key: operationKey,
    outcome,
    retryable: false,
    message,
  };
}

function validFailure(failure, key) {
  return !!(
    exactKeys(failure, [
      "code",
      "operation_key",
      "outcome",
      "retryable",
      "message",
    ]) &&
    validText(failure.code, 1, 200) &&
    failure.operation_key === key &&
    ["known", "unknown"].includes(failure.outcome) &&
    failure.retryable === false &&
    optionalText(failure.message, 4000)
  );
}

function runtimeUnknown(receipt, key) {
  return !!(
    receipt &&
    receipt.schema_version ===
      "quasi.operation.runtime.receipt/0.1" &&
    receipt.key === key &&
    receipt.effect === "readonly" &&
    receipt.status === "failed" &&
    receipt.failure &&
    receipt.failure.operation_key === key &&
    receipt.failure.outcome === "unknown"
  );
}

function canonicalPath(kind, slug) {
  return kind === "book"
    ? `vault/books/${slug}/00-overview.md`
    : `vault/papers/${slug}.md`;
}

function normaliseLookupReceipt(receipt) {
  if (
    !receipt ||
    typeof receipt !== "object" ||
    Array.isArray(receipt)
  )
    return receipt;
  if (
    receipt.vault_slug === LOOKUP_MISS &&
    receipt.path === LOOKUP_MISS &&
    receipt.match === "none"
  )
    return {
      ...receipt,
      vault_slug: null,
      path: null,
      match: null,
    };
  return receipt;
}

function strictLookup(receipt, key, request) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "request_key",
      "kind",
      "requested_slug",
      "vault_slug",
      "path",
      "match",
      "failure",
    ]) ||
    receipt.schema_version !==
      `quasi.operation.${key}.receipt/0.2` ||
    receipt.key !== key ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.request_key !== request.request_key ||
    receipt.kind !== request.kind ||
    receipt.requested_slug !== request.requested_slug ||
    !["succeeded", "failed"].includes(receipt.status)
  )
    return false;
  if (receipt.status === "failed")
    return (
      receipt.vault_slug === null &&
      receipt.path === null &&
      receipt.match === null &&
      validFailure(receipt.failure, key) &&
      receipt.failure.outcome === "known"
    );
  if (receipt.failure !== null) return false;
  if (receipt.vault_slug === null)
    return receipt.path === null && receipt.match === null;
  const allowedMatches =
    request.kind === "book"
      ? ["slug", "isbn", "title"]
      : ["slug", "doi", "title"];
  return (
    SLUG.test(receipt.vault_slug) &&
    receipt.path ===
      canonicalPath(request.kind, receipt.vault_slug) &&
    allowedMatches.includes(receipt.match)
  );
}

function validBookPicked(picked) {
  return !!(
    exactKeys(picked, [
      "slug",
      "title",
      "authors",
      "year",
      "isbn",
      "publisher",
      "category",
      "confidence",
    ]) &&
    SLUG.test(picked.slug) &&
    validText(picked.title, 1, 500) &&
    Array.isArray(picked.authors) &&
    picked.authors.length >= 1 &&
    picked.authors.length <= 32 &&
    picked.authors.every((author) =>
      validText(author, 1, 200),
    ) &&
    Number.isInteger(picked.year) &&
    picked.year >= 1500 &&
    picked.year <= 2030 &&
    optionalText(picked.isbn, 100) &&
    validText(picked.publisher, 2, 500) &&
    CATEGORIES.has(picked.category) &&
    ["high", "medium"].includes(picked.confidence)
  );
}

function validPaperPicked(picked) {
  return !!(
    exactKeys(picked, [
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
    SLUG.test(picked.slug) &&
    validText(picked.title, 1, 500) &&
    Array.isArray(picked.authors) &&
    picked.authors.length >= 1 &&
    picked.authors.length <= 32 &&
    picked.authors.every((author) =>
      validText(author, 1, 200),
    ) &&
    Number.isInteger(picked.year) &&
    picked.year >= 1500 &&
    picked.year <= 2030 &&
    optionalText(picked.doi, 300) &&
    optionalText(picked.oa_url, 2048) &&
    optionalText(picked.url, 2048) &&
    validText(picked.journal, 1, 500) &&
    ["high", "medium"].includes(picked.confidence)
  );
}

function strictSearch(receipt, request) {
  if (
    !exactKeys(receipt, [
      "schema_version",
      "key",
      "effect",
      "status",
      "attempt",
      "request_key",
      "kind",
      "query",
      "picked",
      "confidence",
      "sources_hit",
      "conflicts",
      "notes",
      "failure",
    ]) ||
    receipt.schema_version !==
      "quasi.operation.material.search.receipt/0.1" ||
    receipt.key !== "material.search" ||
    receipt.effect !== "readonly" ||
    receipt.attempt !== 1 ||
    receipt.request_key !== request.requestKey ||
    receipt.kind !== request.kind ||
    !sameClosedValue(receipt.query, request.query) ||
    !Array.isArray(receipt.sources_hit) ||
    receipt.sources_hit.length > 24 ||
    receipt.sources_hit.some(
      (source) => !validText(source, 1, 200),
    ) ||
    !Array.isArray(receipt.conflicts) ||
    receipt.conflicts.length > 32 ||
    receipt.conflicts.some(
      (conflict) => !validText(conflict, 1, 1000),
    ) ||
    !validText(receipt.notes, 0, 4000)
  )
    return false;
  if (receipt.status === "succeeded")
    return (
      receipt.failure === null &&
      ["high", "medium"].includes(receipt.confidence) &&
      receipt.picked &&
      receipt.picked.confidence === receipt.confidence &&
      (request.kind === "book"
        ? validBookPicked(receipt.picked)
        : validPaperPicked(receipt.picked))
    );
  return (
    receipt.status === "failed" &&
    receipt.picked === null &&
    receipt.confidence === "low" &&
    validFailure(receipt.failure, "material.search") &&
    receipt.failure.outcome === "known"
  );
}

function lookupRequest(key, requestKey, kind, requestedSlug, identity) {
  return {
    schema_version: `quasi.operation.${key}.request/0.1`,
    operation: key,
    effect: "readonly",
    request_key: requestKey,
    kind,
    requested_slug: requestedSlug,
    identity: {
      title: identity.title,
      authors: [...identity.authors],
      isbn: kind === "book" ? identity.isbn : null,
      doi: kind === "paper" ? identity.doi : null,
    },
  };
}

function operationSpec(key) {
  return {
    key,
    effect: "readonly",
    retry: "safe",
    artifactRoles: [],
    replay: "safe",
    unknownFailureCode: "material.readonly_outcome_unknown",
  };
}

function ingressReceipt(
  request,
  operations,
  {
    status,
    stage,
    identity = null,
    failure = null,
  },
) {
  return {
    schema_version: INGRESS_RECEIPT_VERSION,
    request_key: request.requestKey,
    kind: request.kind,
    status,
    stage,
    request: request.query,
    operations,
    identity,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "material.recall" }
        : status === "needs_input"
          ? { operation_key: "material.user-gate" }
          : null,
  };
}

function terminal(request, operations, publicStatus, stage, failure) {
  const status =
    publicStatus === "needs_input"
      ? "needs_input"
      : publicStatus === "blocked"
        ? "blocked"
        : "failed";
  return {
    kind: request.kind,
    slug: null,
    status: publicStatus,
    ingress_receipt: ingressReceipt(request, operations, {
      status,
      stage,
      failure,
    }),
  };
}

function invalidTerminal(kind, args, message) {
  const fallback = {
    kind,
    query: null,
    requestedSlug: null,
    requestKey: `${kind}:invalid-request`,
  };
  return terminal(
    fallback,
    [],
    "needs_input",
    "recall",
    operationFailure(
      "material.request_invalid",
      "material.recall",
      "known",
      message,
    ),
  );
}

function unknownTerminal(request, operations, stage, key) {
  return terminal(
    request,
    operations,
    "blocked",
    stage,
    operationFailure(
      "material.readonly_outcome_unknown",
      key,
      "unknown",
      `${key} did not return after its bounded readonly retry`,
    ),
  );
}

function resolvedMeta(request, picked) {
  return request.kind === "book"
    ? {
        title: picked.title,
        authors: [...picked.authors],
        year: picked.year,
        isbn: picked.isbn,
        publisher: picked.publisher,
        category: picked.category,
        format: request.query.format,
        confidence: "verified",
      }
    : {
        title: picked.title,
        authors: [...picked.authors],
        year: picked.year,
        doi: picked.doi,
        oa_url: picked.oa_url,
        url: picked.url,
        journal: picked.journal,
        confidence: "verified",
      };
}

function applyBookYearDecision(picked, decision) {
  if (
    !decision ||
    decision.action !== "use-recommended-year"
  )
    return { ok: true, picked };
  const evidence = decision.year_evidence;
  if (
    !evidence ||
    evidence.verdict !== "MISMATCH" ||
    !Number.isInteger(evidence.slug_year) ||
    !Number.isInteger(evidence.recommended_year) ||
    evidence.recommended_year === evidence.slug_year ||
    picked.year !== evidence.slug_year ||
    !picked.slug.endsWith(`-${evidence.slug_year}`)
  )
    return {
      ok: false,
      message:
        "year_decision does not match the identity returned by Search",
    };
  return {
    ok: true,
    picked: {
      ...picked,
      year: evidence.recommended_year,
      slug:
        picked.slug.slice(
          0,
          -String(evidence.slug_year).length,
        ) + String(evidence.recommended_year),
    },
  };
}

function validYearDecisionEnvelope(decision) {
  if (decision == null) return true;
  if (
    !exactKeys(decision, [
      "action",
      "tmp_path",
      "year_evidence",
    ]) ||
    !["accept-current", "use-recommended-year"].includes(
      decision.action,
    ) ||
    typeof decision.tmp_path !== "string" ||
    !BOOK_TEMP_PATH.test(decision.tmp_path)
  )
    return false;
  const evidence = decision.year_evidence;
  return !!(
    exactKeys(evidence, [
      "slug_year",
      "source_years",
      "pdf_signals",
      "recommended_year",
      "recommendation_reason",
      "verdict",
    ]) &&
    Number.isInteger(evidence.slug_year) &&
    evidence.source_years &&
    typeof evidence.source_years === "object" &&
    !Array.isArray(evidence.source_years) &&
    exactKeys(evidence.pdf_signals, [
      "first_published",
      "copyright_year",
      "original_year",
      "other_years",
    ]) &&
    Array.isArray(evidence.pdf_signals.other_years) &&
    (evidence.recommended_year === null ||
      Number.isInteger(evidence.recommended_year)) &&
    validText(evidence.recommendation_reason, 1, 4000) &&
    ["MISMATCH", "AMBIGUOUS"].includes(evidence.verdict)
  );
}

async function runResolvedIngress(
  runtime,
  request,
  next,
  options,
) {
  const operations = [];
  runtime.phase("Recall");
  const recallRequest = lookupRequest(
    "material.recall",
    request.requestKey,
    request.kind,
    request.requestedSlug,
    request.query,
  );
  const recall = normaliseLookupReceipt(
    await runtime.runOperation(
      materialRecallPrompt(recallRequest),
      {
        phase: "Recall",
        agentType: "quasi:metadata-agent",
        label: `${request.requestedSlug}:recall`,
        schema: MATERIAL_RECALL_SCHEMA,
      },
      operationSpec("material.recall"),
    ),
  );
  operations.push(recall);
  if (runtimeUnknown(recall, "material.recall"))
    return unknownTerminal(
      request,
      operations,
      "recall",
      "material.recall",
    );
  if (!strictLookup(recall, "material.recall", recallRequest))
    return terminal(
      request,
      operations,
      "metadata_failed",
      "recall",
      operationFailure(
        "material.recall_receipt_invalid",
        "material.recall",
        "known",
        "Recall did not return the exact readonly contract",
      ),
    );
  if (recall.status === "failed")
    return terminal(
      request,
      operations,
      "metadata_failed",
      "recall",
      recall.failure,
    );

  runtime.phase("Search");
  const searchRequest = {
    schema_version:
      "quasi.operation.material.search.request/0.1",
    operation: "material.search",
    effect: "readonly",
    request_key: request.requestKey,
    kind: request.kind,
    query: request.query,
  };
  const search = await runtime.runOperation(
    materialSearchPrompt(searchRequest),
    {
      phase: "Search",
      agentType: "quasi:metadata-agent",
      label: `${request.requestedSlug}:search`,
      schema:
        request.kind === "book"
          ? MATERIAL_SEARCH_BOOK_SCHEMA
          : MATERIAL_SEARCH_PAPER_SCHEMA,
    },
    operationSpec("material.search"),
  );
  operations.push(search);
  if (runtimeUnknown(search, "material.search"))
    return unknownTerminal(
      request,
      operations,
      "search",
      "material.search",
    );
  if (!strictSearch(search, request))
    return terminal(
      request,
      operations,
      "metadata_failed",
      "search",
      operationFailure(
        "material.search_receipt_invalid",
        "material.search",
        "known",
        "Search did not return the exact identity contract",
      ),
    );
  if (search.status === "failed")
    return terminal(
      request,
      operations,
      "needs_input",
      "search",
      search.failure,
    );

  const yearAdjusted =
    request.kind === "book"
      ? applyBookYearDecision(
          search.picked,
          options.yearDecision,
        )
      : { ok: true, picked: search.picked };
  if (!yearAdjusted.ok)
    return terminal(
      request,
      operations,
      "needs_input",
      "search",
      operationFailure(
        "book.year_decision_invalid",
        "material.search",
        "known",
        yearAdjusted.message,
      ),
    );
  const picked = yearAdjusted.picked;
  const resolveRequest = lookupRequest(
    "material.resolve",
    request.requestKey,
    request.kind,
    picked.slug,
    picked,
  );
  const resolved = normaliseLookupReceipt(
    await runtime.runOperation(
      materialResolvePrompt(resolveRequest),
      {
        phase: "Search",
        agentType: "quasi:metadata-agent",
        label: `${picked.slug}:resolve`,
        schema: MATERIAL_RESOLVE_SCHEMA,
      },
      operationSpec("material.resolve"),
    ),
  );
  operations.push(resolved);
  if (runtimeUnknown(resolved, "material.resolve"))
    return unknownTerminal(
      request,
      operations,
      "resolve",
      "material.resolve",
    );
  if (!strictLookup(resolved, "material.resolve", resolveRequest))
    return terminal(
      request,
      operations,
      "metadata_failed",
      "resolve",
      operationFailure(
        "material.resolve_receipt_invalid",
        "material.resolve",
        "known",
        "Canonical resolve did not return the exact readonly contract",
      ),
    );
  if (resolved.status === "failed")
    return terminal(
      request,
      operations,
      "metadata_failed",
      "resolve",
      resolved.failure,
    );
  if (
    recall.vault_slug !== null &&
    resolved.vault_slug !== recall.vault_slug
  )
    return terminal(
      request,
      operations,
      "needs_input",
      "resolve",
      operationFailure(
        "material.recall_identity_conflict",
        "material.resolve",
        "known",
        "Raw recall and verified metadata resolve to different local works",
      ),
    );

  const slug = resolved.vault_slug || picked.slug;
  const meta = resolvedMeta(request, picked);
  const identity = { slug, meta };
  const lower = await next(slug, meta);
  return {
    ...lower,
    ingress_receipt: ingressReceipt(request, operations, {
      status: "resolved",
      stage: "resolve",
      identity,
    }),
  };
}

export function processMaterialIngress(
  runtime,
  kind,
  args,
  next,
  options = {},
) {
  const request = normaliseRequest(kind, args);
  if (!request.ok)
    return Promise.resolve(
      invalidTerminal(kind, args, request.message),
    );
  if (
    kind === "book" &&
    !validYearDecisionEnvelope(options.yearDecision)
  )
    return Promise.resolve(
      terminal(
        request,
        [],
        "needs_input",
        "recall",
        operationFailure(
          "book.year_decision_invalid",
          "material.recall",
          "known",
          "year_decision is not one exact prior Book gate",
        ),
      ),
    );
  const identity = JSON.stringify({
    query: request.query,
    year_decision: options.yearDecision || null,
  });
  return runtime.coalesce(
    `material-ingress:${request.requestKey}`,
    identity,
    () => runResolvedIngress(runtime, request, next, options),
    () =>
      terminal(
        request,
        [],
        "needs_input",
        "recall",
        operationFailure(
          "material.request_identity_conflict",
          "material.recall",
          "known",
          "same-run raw requests share one request key but disagree",
        ),
      ),
  );
}
