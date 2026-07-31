import {
  exactKeys,
  sameClosedValue,
  validateSchema,
  validText,
} from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";
import {
  BOOK_TEMP_PATH,
  validYearEvidence,
} from "../operations/book-year-evidence.mjs";
import {
  validBookAcquireReceipt,
} from "../operations/acquire.mjs";
import {
  bookPrepareStageSchema,
  paperPrepareStageSchema,
} from "../operations/extract.mjs";

export const MATERIAL_RECEIPT_VERSION =
  "quasi.material-loop.receipt/0.2";

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

function validStageIssue(issue, operation, needsQuestion) {
  return !!(
    exactKeys(issue, [
      "code",
      "operation",
      "summary",
      "user_question",
      "retryable",
    ]) &&
    validText(issue.code, 1, 200) &&
    issue.operation === operation &&
    validText(issue.summary, 1, 4000) &&
    (needsQuestion
      ? validText(issue.user_question, 1, 4000)
      : issue.user_question === null ||
        validText(issue.user_question, 1, 4000)) &&
    typeof issue.retryable === "boolean"
  );
}

export function stageUserGate(receipt) {
  const issue = stageIssue(receipt);
  const terminal = receipt.terminal;
  return {
    schema_version: "quasi.user-gate.stage/0.1",
    operation_key: receipt.operation,
    kind: "stage_needs_input",
    issue,
    candidates: Array.isArray(terminal.candidates)
      ? terminal.candidates
      : [],
    conflicts: Array.isArray(terminal.conflicts)
      ? terminal.conflicts
      : [],
    question: issue.user_question,
  };
}

export function failureUserGate(failure) {
  const issue = {
    code: failure.code,
    operation: failure.operation_key,
    summary: failure.message,
    user_question: failure.message,
    retryable: failure.retryable,
  };
  return {
    schema_version: "quasi.user-gate.stage/0.1",
    operation_key: failure.operation_key,
    kind: "stage_needs_input",
    issue,
    candidates: [],
    conflicts: [],
    question: failure.message,
  };
}

export function bookYearUserGate(receipt) {
  const mismatch = receipt.signal === "year_mismatch";
  const evidence = receipt.year_evidence;
  return {
    schema_version: "quasi.user-gate.book-year/0.1",
    operation_key: "book.user-gate",
    kind: "book_year_decision",
    actions: mismatch
      ? ["accept-current", "use-recommended-year"]
      : ["accept-current"],
    tmp_path: receipt.tmp_path,
    year_evidence: evidence,
    question: mismatch
      ? `The acquired edition supports ${evidence.recommended_year} rather than the requested ${evidence.slug_year}. Which canonical year should this Book use?`
      : `The acquired edition does not prove one publication year for the requested ${evidence.slug_year}. Should the Book keep the requested year?`,
  };
}

function validStageUserGate(gate) {
  return !!(
    exactKeys(gate, [
      "schema_version",
      "operation_key",
      "kind",
      "issue",
      "candidates",
      "conflicts",
      "question",
    ]) &&
    gate.schema_version === "quasi.user-gate.stage/0.1" &&
    validText(gate.operation_key, 1, 200) &&
    gate.kind === "stage_needs_input" &&
    validStageIssue(gate.issue, gate.operation_key, true) &&
    gate.question === gate.issue.user_question &&
    Array.isArray(gate.candidates) &&
    gate.candidates.length <= 16 &&
    gate.candidates.every(record) &&
    Array.isArray(gate.conflicts) &&
    gate.conflicts.length <= 32 &&
    gate.conflicts.every((item) => validText(item, 1, 200))
  );
}

function validBookYearUserGate(gate, expectedYear) {
  if (
    !exactKeys(gate, [
      "schema_version",
      "operation_key",
      "kind",
      "actions",
      "tmp_path",
      "year_evidence",
      "question",
    ]) ||
    gate.schema_version !== "quasi.user-gate.book-year/0.1" ||
    gate.operation_key !== "book.user-gate" ||
    gate.kind !== "book_year_decision" ||
    !validText(gate.tmp_path, 1, 1000) ||
    !BOOK_TEMP_PATH.test(gate.tmp_path) ||
    !Number.isInteger(expectedYear) ||
    !record(gate.year_evidence) ||
    !validYearEvidence(
      gate.year_evidence,
      expectedYear,
    ) ||
    !validText(gate.question, 1, 4000)
  )
    return false;
  if (gate.year_evidence.verdict === "MISMATCH")
    return sameStrings(gate.actions, [
      "accept-current",
      "use-recommended-year",
    ]);
  return (
    gate.year_evidence.verdict === "AMBIGUOUS" &&
    sameStrings(gate.actions, ["accept-current"])
  );
}

export function validUserGate(gate, receipt, context = {}) {
  if (gate === null) return receipt.status !== "needs_input";
  if (!record(gate) || receipt.status !== "needs_input")
    return false;
  if (validStageUserGate(gate)) {
    const operationKey = `${receipt.kind}.prepare`;
    const operation = [...receipt.operations]
      .reverse()
      .find(
        (item) =>
          item.operation === operationKey &&
          item.material_key === receipt.material_key,
      );
    const root = `processing/chapters/${receipt.id}`;
    const prepareSchema =
      receipt.kind === "paper"
        ? paperPrepareStageSchema({
            materialKey: receipt.material_key,
            source: `sources/${receipt.id}.pdf`,
            normalized: `processing/papers/${receipt.id}/source.txt`,
            recoverySource: `processing/papers/${receipt.id}/ocr.pdf`,
            recoveryText: `processing/papers/${receipt.id}/ocr.txt`,
          })
        : receipt.kind === "book" &&
            ["epub", "pdf"].includes(operation && operation.format)
          ? bookPrepareStageSchema({
              materialKey: receipt.material_key,
              source: `sources/${receipt.id}.${operation.format}`,
              format: operation.format,
              normalized: `${root}/source.txt`,
              recoverySource: `${root}/ocr.pdf`,
              recoveryText: `${root}/ocr.txt`,
              outputDir: root,
              manifest: `${root}/manifest.json`,
            })
          : null;
    const expectedResume =
      receipt.kind === "paper"
        ? {
            operation_key: "paper.user-gate",
            stage: "prepare",
          }
        : {
            operation_key: "book.user-gate",
            stage: "prepare",
            policy: "answer-the-stage-question",
          };
    return !!(
      record(receipt.failure) &&
      receipt.stage === "prepare" &&
      receipt.failure.operation_key === operationKey &&
      gate.operation_key === operationKey &&
      record(operation) &&
      prepareSchema !== null &&
      validateSchema(prepareSchema, operation) &&
      record(operation.terminal) &&
      operation.terminal.status === "needs_input" &&
      sameClosedValue(receipt.resume, expectedResume) &&
      sameClosedValue(receipt.failure, {
        code: operation.terminal.issue.code,
        operation_key: operationKey,
        outcome: "known",
        retryable:
          receipt.kind === "book"
            ? operation.terminal.issue.retryable
            : false,
        message: operation.terminal.issue.summary,
      }) &&
      sameClosedValue(gate.issue, operation.terminal.issue) &&
      sameClosedValue(
        gate.candidates,
        Array.isArray(operation.terminal.candidates)
          ? operation.terminal.candidates
          : [],
      ) &&
      sameClosedValue(
        gate.conflicts,
        Array.isArray(operation.terminal.conflicts)
          ? operation.terminal.conflicts
          : [],
      )
    );
  }
  if (!validBookYearUserGate(gate, context.expectedYear))
    return false;
  const operation = [...receipt.operations]
    .reverse()
    .find(
      (item) =>
        item.key === "book.acquire" &&
        item.material_key === receipt.material_key,
    );
  return !!(
    record(receipt.failure) &&
    receipt.kind === "book" &&
    receipt.stage === "download" &&
    receipt.failure.operation_key === "book.acquire" &&
    record(operation) &&
    validBookAcquireReceipt(operation, {
      slug: receipt.id,
      expectedYear: context.expectedYear,
      batchAcceptYear: false,
      yearDecision: null,
    }) &&
    ["year_mismatch", "year_ambiguous"].includes(
      operation.signal,
    ) &&
    sameClosedValue(receipt.resume, {
      operation_key: "book.user-gate",
      stage: "download",
      policy: "human-year-decision-or-correct-request",
    }) &&
    sameClosedValue(receipt.failure, operation.failure) &&
    sameClosedValue(gate, bookYearUserGate(operation))
  );
}
