import { InputContractError } from "../context-base.mts";
import {
  prepareOperation,
  type OperationInvocation,
} from "../operations/catalog.mts";
import type { DispatchRuntime } from "./host-runtime.mts";
import {
  dispatchIssue,
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "./dispatch-prepared.mts";

export {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "./dispatch-prepared.mts";

export async function dispatchOperation(
  runtime: DispatchRuntime,
  invocation: OperationInvocation,
): Promise<DispatchOutcome> {
  let prepared;
  try {
    prepared = prepareOperation(invocation);
  } catch (error) {
    if (!(error instanceof InputContractError)) throw error;
    return {
      kind: "invalid_context",
      receipt: null,
      issue: dispatchIssue(
        "workflow.invalid_context",
        invocation.operation,
        error.message,
      ),
    };
  }
  return dispatchPreparedOperation(runtime, prepared);
}
