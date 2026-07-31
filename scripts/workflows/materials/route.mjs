import { stageUserGate } from "./receipt.mjs";

const valueFor = (value, receipt) =>
  typeof value === "function" ? value(receipt) : value;

const routedValue = (value) =>
  value && typeof value === "object" && "terminal" in value
    ? value
    : { value };

// Material loops share one closed runtime edge algebra. Each call site declares
// only its observable terminal status, evidence extras, and success handling;
// this router keeps receipt recording and writer-safe unknown/mismatch routing
// identical across material kinds.
export function routeStageEdge(run, {
  state,
  stage,
  operationKey,
  emit,
  failure,
  unknown,
  mismatch,
  onReceipt = null,
  onOk = null,
  onReconcile = null,
  onBlocked = null,
  blockedStatus = "blocked",
  blockedOutcome = "unknown",
  blockedExtra = null,
  blockedFailure = null,
  onNeedsInput = null,
  needsInputStatus = "needs_input",
  needsInputExtra = null,
  needsInputGate = undefined,
  assignGate = null,
  needsInputFailure = null,
  onFailed = null,
  failedStatus = null,
  failedExtra = null,
  failedFailure = null,
}) {
  const { edge, receipt } = run;
  state.operations.push(receipt);
  if (onReceipt) onReceipt(receipt, edge);

  if (edge === "unknown")
    return { terminal: unknown(receipt, state, stage, operationKey) };
  if (edge === "mismatch")
    return { terminal: mismatch(receipt, state, stage, operationKey) };

  if (edge === "blocked") {
    if (onBlocked)
      return routedValue(onBlocked(receipt, state, stage, operationKey));
    return {
      terminal: emit({
        status: blockedStatus,
        receipt,
        edge,
        extra: valueFor(blockedExtra, receipt) || {},
        failure: blockedFailure
          ? valueFor(blockedFailure, receipt)
          : failure(receipt, blockedOutcome),
      }),
    };
  }

  if (edge === "needs_input") {
    if (onNeedsInput)
      return routedValue(
        onNeedsInput(receipt, state, stage, operationKey),
      );
    const gate =
      needsInputGate === undefined
        ? stageUserGate(receipt)
        : valueFor(needsInputGate, receipt);
    if (gate !== undefined)
      (assignGate || ((value) => {
        state.userGate = value;
      }))(gate);
    return {
      terminal: emit({
        status: needsInputStatus,
        receipt,
        edge,
        extra: valueFor(needsInputExtra, receipt) || {},
        failure: needsInputFailure
          ? valueFor(needsInputFailure, receipt)
          : failure(receipt, "known"),
      }),
    };
  }

  if (edge === "failed") {
    if (onFailed)
      return routedValue(onFailed(receipt, state, stage, operationKey));
    if (failedStatus === null)
      throw new Error(`unhandled material failed edge: ${operationKey}`);
    return {
      terminal: emit({
        status: failedStatus,
        receipt,
        edge,
        extra: valueFor(failedExtra, receipt) || {},
        failure: failedFailure
          ? valueFor(failedFailure, receipt)
          : failure(receipt, "known"),
      }),
    };
  }

  if (edge === "reconcile")
    return routedValue(
      onReconcile
        ? onReconcile(receipt, state, stage, operationKey)
        : receipt,
    );
  if (edge === "ok")
    return routedValue(
      onOk
        ? onOk(receipt, state, stage, operationKey)
        : receipt,
    );

  throw new Error(`unhandled material operation edge: ${edge}`);
}
