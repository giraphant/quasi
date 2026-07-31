import {
  MATERIAL_SEARCH_STAGE_CONTRACT,
  materialSearchStageSchema,
  materialSearchPrompt,
} from "../operations/acquire.mjs";
import { stageIssue } from "../stage.mjs";

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
  retryable = false,
) {
  return {
    code,
    operation_key: operationKey,
    outcome,
    retryable,
    message,
  };
}

function stageFailure(receipt, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || "material.search_failed",
    "material.search",
    outcome,
    (issue && (issue.user_question || issue.summary)) ||
      "Metadata Search did not complete",
    !!(issue && issue.retryable),
  );
}

function operationSpec(key) {
  return {
    key,
    effect: "readonly",
    retry: "forbidden",
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
        ? { operation_key: "material.search" }
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
    "search",
    operationFailure(
      "material.request_invalid",
      "material.search",
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
      `${key} outcome was not observed`,
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
    evidence &&
    picked.year === evidence.recommended_year &&
    picked.slug.endsWith(`-${evidence.recommended_year}`)
  )
    return { ok: true, picked };
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
  runtime.phase("Search");
  const searchRequest = {
    schema_version:
      "quasi.stage.material-search.request/0.1",
    operation: "material.search",
    stage: "Search",
    effect: "readonly",
    request_key: request.requestKey,
    kind: request.kind,
    requested_slug: request.requestedSlug,
    query: request.query,
    year_decision:
      request.kind === "book" ? options.yearDecision || null : null,
  };
  const searchSchema = materialSearchStageSchema(searchRequest);
  const searchRun = await runtime.operate(
    materialSearchPrompt(searchRequest),
    {
      phase: "Search",
      agentType: "quasi:metadata-agent",
      label: `${request.requestedSlug}:search`,
      schema: searchSchema,
    },
    {
      ...operationSpec("material.search"),
      contract: MATERIAL_SEARCH_STAGE_CONTRACT,
    },
  );
  const search = searchRun.receipt;
  operations.push(search);
  if (searchRun.edge === "unknown")
    return unknownTerminal(
      request,
      operations,
      "search",
      "material.search",
    );
  if (searchRun.edge === "mismatch")
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
  if (searchRun.edge === "blocked")
    return terminal(
      request,
      operations,
      "blocked",
      "search",
      stageFailure(search, "unknown"),
    );
  if (searchRun.edge === "needs_input")
    return terminal(
      request,
      operations,
      "needs_input",
      "search",
      stageFailure(search),
    );
  if (searchRun.edge === "failed")
    return terminal(
      request,
      operations,
      "metadata_failed",
      "search",
      stageFailure(search),
    );

  const yearAdjusted =
    request.kind === "book"
      ? applyBookYearDecision(
          search.identity,
          options.yearDecision,
        )
      : { ok: true, picked: search.identity };
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
  const resolved = search.local_owner;
  if (resolved !== null && resolved.identity_slug !== picked.slug)
    return terminal(
      request,
      operations,
      "metadata_failed",
      "resolve",
      operationFailure(
        "material.search_owner_mismatch",
        "material.search",
        "known",
        "Search did not resolve the selected canonical slug",
      ),
    );
  const slug = (resolved && resolved.vault_slug) || picked.slug;
  const meta = resolvedMeta(request, picked);
  const identity = { slug, meta };
  const lower = await next(slug, meta);
  return {
    ...lower,
    ingress_receipt: ingressReceipt(request, operations, {
      status: "resolved",
      stage: "search",
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
        "search",
        operationFailure(
          "book.year_decision_invalid",
          "material.search",
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
        "search",
        operationFailure(
          "material.request_identity_conflict",
          "material.search",
          "known",
          "same-run raw requests share one request key but disagree",
        ),
      ),
  );
}
