import { admitChildMaterialResult } from "./member.mjs";
import { normaliseMaterialRequest } from "./ingress.mjs";

const BATCH_RECEIPT_VERSION =
  "quasi.collection.material-batch.receipt/0.2";
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

function batchTerminal(kind, status, issue) {
  return {
    material_key: null,
    kind: kind || "invalid",
    id: null,
    status,
    canonical_artifacts: [],
    user_gate: null,
    issue,
    resume: null,
  };
}

async function classifyResult(runtime, item, result, error = null) {
  if (error)
    return batchTerminal(
      item.kind,
      "blocked",
      closedFailure(
        null,
        "material.batch_child_outcome_unknown",
        "material.batch",
        "unknown",
        error,
      ),
    );

  const projected = await admitChildMaterialResult(
    runtime,
    result,
    item.request,
  );
  if (projected) return projected;
  return batchTerminal(
    item.kind,
    "blocked",
    closedFailure(
      null,
      "material.batch_child_receipt_invalid",
      "material.batch",
      "unknown",
      "child result did not carry an exact terminal receipt",
    ),
  );
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

  const items = rawItems.map((raw, index) => {
    const kind =
      record(raw) && ["book", "paper"].includes(raw.kind)
        ? raw.kind
        : null;
    const normalized = kind
      ? normaliseMaterialRequest(kind, raw)
      : null;
    const request = normalized
      ? {
          ...normalized,
          yearDecision:
            kind === "book" &&
            record(raw) &&
            Object.prototype.hasOwnProperty.call(
              raw,
              "year_decision",
            )
              ? raw.year_decision
              : null,
        }
      : null;
    return {
      index,
      request_id: itemId(raw, index),
      kind,
      request,
      raw,
    };
  });

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
          summary: batchTerminal(null, "failed", failure),
        };
      }
      try {
        const result = await runItem(item.raw);
        return {
          ...item,
          summary: await classifyResult(runtime, item, result),
        };
      } catch (error) {
        const message =
          (error && error.message) || String(error);
        return {
          ...item,
          summary: await classifyResult(
            runtime,
            item,
            null,
            message,
          ),
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
    ...outcome.summary,
  }));
  runtime.log(
    `material batch result: total=${outcomes.length} complete=${counts.complete} needs_input=${counts.needs_input} blocked=${counts.blocked} failed=${counts.failed}`,
  );
  return {
    status: status === "complete" ? "ok" : status,
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
