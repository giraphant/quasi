import { InputContractError } from "../context-base.mts";
import {
  prepareOperation,
  type OperationInvocation,
  type PreparedOperation,
} from "../operations/catalog.mts";
import type { StageReceipt } from "../artifact-contracts/generated.mjs";
import type { DispatchRuntime } from "./host-runtime.mts";
import type { MaterialIssue } from "./material-result.mts";

export type DispatchOutcome =
  | { kind: "receipt"; receipt: StageReceipt }
  | { kind: "invalid_context"; receipt: null; issue: MaterialIssue }
  | {
      kind: "incoherent_complete";
      receipt: StageReceipt;
      issue: MaterialIssue;
    }
  | { kind: "unknown_outcome"; receipt: null; issue: MaterialIssue };

const dispatchIssue = (
  code: string,
  operation: OperationInvocation["operation"],
  summary: string,
): MaterialIssue => ({
  code,
  operation,
  summary,
  retryable: false,
  observation_request: null,
});

export async function dispatchPreparedOperation(
  runtime: DispatchRuntime,
  prepared: PreparedOperation,
): Promise<DispatchOutcome> {
  let modelOutput;
  try {
    modelOutput = await runtime.agent(prepared.prompt, prepared.options);
  } catch {
    return {
      kind: "unknown_outcome",
      receipt: null,
      issue: dispatchIssue(
        "workflow.unknown_outcome",
        prepared.invocation.operation,
        "The specialist outcome is unknown; re-observe disk state before resuming.",
      ),
    };
  }
  if (modelOutput === null) {
    return {
      kind: "unknown_outcome",
      receipt: null,
      issue: dispatchIssue(
        "workflow.unknown_outcome",
        prepared.invocation.operation,
        "The specialist outcome is unknown; re-observe disk state before resuming.",
      ),
    };
  }

  const receipt = {
    ...modelOutput,
    ...prepared.stampedValues,
  } as StageReceipt;
  if (receipt.terminal.status !== "complete")
    return { kind: "receipt", receipt };
  if (!prepared.complete(receipt)) {
    return {
      kind: "incoherent_complete",
      receipt,
      issue: dispatchIssue(
        "workflow.incoherent_complete",
        prepared.invocation.operation,
        "The specialist reported complete, but its cross-field completion evidence is incoherent.",
      ),
    };
  }
  return { kind: "receipt", receipt };
}

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
