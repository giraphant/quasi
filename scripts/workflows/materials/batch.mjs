const BATCH_RECEIPT_VERSION =
  "quasi.collection.material-batch.receipt/0.1";
const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.1";
const INGRESS_RECEIPT_VERSION =
  "quasi.material-ingress.receipt/0.1";
const MAX_BATCH_ITEMS = 32;
const ID_CHARS = /[^a-z0-9]+/g;

const record = (value) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value)
  );

function itemId(item, index) {
  const nested = record(item && item.request)
    ? item.request
    : record(item && item.meta)
      ? item.meta
      : item;
  const seed =
    (item && item.slug) ||
    (nested && nested.slug) ||
    (nested && nested.title) ||
    `${item && item.kind ? item.kind : "material"}-${index + 1}`;
  const slug = String(seed || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(ID_CHARS, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
  return `item-${String(index + 1).padStart(2, "0")}-${slug || "material"}`;
}

function closedFailure(
  raw,
  code,
  operationKey,
  outcome = "known",
  message = null,
) {
  const source = record(raw) ? raw : {};
  return {
    code:
      typeof source.code === "string" && source.code
        ? source.code
        : code,
    operation_key:
      typeof source.operation_key === "string" &&
      source.operation_key
        ? source.operation_key
        : operationKey,
    outcome: ["known", "unknown"].includes(source.outcome)
      ? source.outcome
      : outcome,
    retryable:
      typeof source.retryable === "boolean"
        ? source.retryable
        : false,
    message:
      typeof source.message === "string"
        ? source.message.slice(0, 4000)
        : message,
  };
}

function materialReceipt(result) {
  const receipt = result && result.material_receipt;
  return record(receipt) &&
    receipt.schema_version === MATERIAL_RECEIPT_VERSION &&
    ["book", "paper"].includes(receipt.kind) &&
    typeof receipt.id === "string" &&
    receipt.material_key === `${receipt.kind}:${receipt.id}` &&
    ["complete", "blocked", "failed"].includes(receipt.status)
    ? receipt
    : null;
}

function ingressReceipt(result) {
  const receipt = result && result.ingress_receipt;
  return record(receipt) &&
    receipt.schema_version === INGRESS_RECEIPT_VERSION &&
    ["resolved", "needs_input", "blocked", "failed"].includes(
      receipt.status,
    )
    ? receipt
    : null;
}

function classifyResult(item, result, error = null) {
  if (error)
    return {
      status: "blocked",
      slug: null,
      ingressStatus: null,
      materialStatus: null,
      failure: closedFailure(
        null,
        "material.batch_child_outcome_unknown",
        "material.batch",
        "unknown",
        error,
      ),
    };

  const ingress = ingressReceipt(result);
  const material = materialReceipt(result);
  const publicStatus =
    result && typeof result.status === "string"
      ? result.status
      : "unknown";
  const slug =
    result && typeof result.slug === "string"
      ? result.slug
      : material
        ? material.id
        : null;

  if (
    publicStatus === "year_mismatch" ||
    publicStatus === "year_ambiguous" ||
    (ingress && ingress.status === "needs_input")
  )
    return {
      status: "needs_input",
      slug,
      ingressStatus: ingress ? ingress.status : null,
      materialStatus: material ? material.status : null,
      failure: closedFailure(
        (material && material.failure) ||
          (ingress && ingress.failure),
        "material.batch_item_needs_input",
        item.kind === "book"
          ? "book.user-gate"
          : "material.search",
      ),
    };

  if (
    publicStatus === "ok" &&
    material &&
    material.kind === item.kind &&
    material.status === "complete"
  )
    return {
      status: "complete",
      slug,
      ingressStatus: ingress ? ingress.status : null,
      materialStatus: material.status,
      failure: null,
    };

  if (
    publicStatus === "blocked" ||
    (ingress && ingress.status === "blocked") ||
    (material && material.status === "blocked")
  )
    return {
      status: "blocked",
      slug,
      ingressStatus: ingress ? ingress.status : null,
      materialStatus: material ? material.status : null,
      failure: closedFailure(
        (material && material.failure) ||
          (ingress && ingress.failure),
        "material.batch_item_blocked",
        "material.batch",
        "unknown",
      ),
    };

  if (
    (ingress && ingress.status === "failed") ||
    (material && material.status === "failed")
  )
    return {
      status: "failed",
      slug,
      ingressStatus: ingress ? ingress.status : null,
      materialStatus: material ? material.status : null,
      failure: closedFailure(
        (material && material.failure) ||
          (ingress && ingress.failure),
        "material.batch_item_failed",
        "material.batch",
      ),
    };

  return {
    status: "blocked",
    slug,
    ingressStatus: ingress ? ingress.status : null,
    materialStatus: material ? material.status : null,
    failure: closedFailure(
      null,
      "material.batch_child_receipt_invalid",
      "material.batch",
      "unknown",
      "child result did not carry an exact terminal receipt",
    ),
  };
}

function aggregateStatus(counts, total) {
  if (counts.complete === total) return "complete";
  if (counts.failed === total) return "failed";
  if (counts.blocked === total) return "blocked";
  return "partial";
}

function invalidBatch(message, total = 0) {
  const counts = {
    complete: 0,
    needs_input: 0,
    blocked: 0,
    failed: total,
  };
  const failure = closedFailure(
    null,
    "material.batch_request_invalid",
    "material.batch",
    "known",
    message,
  );
  return {
    status: "failed",
    results: [],
    batch_receipt: {
      schema_version: BATCH_RECEIPT_VERSION,
      status: "failed",
      total,
      counts,
      items: [],
      failure,
    },
  };
}

export async function processMaterialBatch(
  runtime,
  rawItems,
  runItem,
) {
  if (!Array.isArray(rawItems))
    return invalidBatch("batch items must be an array");
  if (rawItems.length < 2 || rawItems.length > MAX_BATCH_ITEMS)
    return invalidBatch(
      `batch must contain 2-${MAX_BATCH_ITEMS} items`,
      rawItems.length,
    );

  const items = rawItems.map((raw, index) => ({
    index,
    request_id: itemId(raw, index),
    kind:
      record(raw) && ["book", "paper"].includes(raw.kind)
        ? raw.kind
        : null,
    raw,
  }));

  const outcomes = await runtime.parallel(
    items.map((item) => async () => {
      if (!item.kind) {
        const failure = closedFailure(
          null,
          "material.batch_item_invalid",
          "material.batch",
          "known",
          "batch items must be Book or Paper objects",
        );
        return {
          ...item,
          result: {
            status: "failed",
            failure,
          },
          summary: {
            status: "failed",
            slug: null,
            ingressStatus: null,
            materialStatus: null,
            failure,
          },
        };
      }
      try {
        const result = await runItem(item.raw);
        return {
          ...item,
          result,
          summary: classifyResult(item, result),
        };
      } catch (error) {
        const message =
          (error && error.message) || String(error);
        return {
          ...item,
          result: {
            status: "blocked",
            failure: closedFailure(
              null,
              "material.batch_child_outcome_unknown",
              "material.batch",
              "unknown",
              message,
            ),
          },
          summary: classifyResult(item, null, message),
        };
      }
    }),
  );

  const counts = {
    complete: 0,
    needs_input: 0,
    blocked: 0,
    failed: 0,
  };
  for (const outcome of outcomes)
    counts[outcome.summary.status] += 1;
  const status = aggregateStatus(counts, outcomes.length);
  const summaries = outcomes.map((outcome) => ({
    index: outcome.index,
    request_id: outcome.request_id,
    kind: outcome.kind || "invalid",
    status: outcome.summary.status,
    result_status:
      outcome.result &&
      typeof outcome.result.status === "string"
        ? outcome.result.status
        : "unknown",
    slug: outcome.summary.slug,
    ingress_status: outcome.summary.ingressStatus,
    material_status: outcome.summary.materialStatus,
    failure: outcome.summary.failure,
  }));
  const results = outcomes.map((outcome) => ({
    index: outcome.index,
    request_id: outcome.request_id,
    kind: outcome.kind || "invalid",
    status: outcome.summary.status,
    result: outcome.result,
  }));
  runtime.log(
    `material batch result: total=${outcomes.length} complete=${counts.complete} needs_input=${counts.needs_input} blocked=${counts.blocked} failed=${counts.failed}`,
  );
  return {
    status: status === "complete" ? "ok" : status,
    results,
    batch_receipt: {
      schema_version: BATCH_RECEIPT_VERSION,
      status,
      total: outcomes.length,
      counts,
      items: summaries,
      failure: null,
    },
  };
}
