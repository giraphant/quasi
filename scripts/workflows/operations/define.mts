import {
  stageReceiptPartition,
  type StageReceiptPartition,
} from "../stage.mts";
import type {
  OperationDescriptor,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

export interface DefinedOperation {
  refs: (context: WorkflowContext) => WorkflowContext;
  receiptSchema: (context: WorkflowContext) => StageReceiptPartition;
  complete: (receipt: StageReceipt, context: WorkflowContext) => boolean;
  prompt: (context: WorkflowContext) => string;
}

const asFragment = (fragment: any): WorkflowContext =>
  fragment && typeof fragment === "object" ? fragment : {};

export function defineOperation(
  descriptor: OperationDescriptor,
): DefinedOperation {
  const {
    operation,
    stage,
    effect,
    refs: makeRefs,
    payloadProperties,
    terminalPayloads,
    complete,
    envelope,
    promptText,
  } = descriptor;
  const refs = (context: WorkflowContext): WorkflowContext =>
    makeRefs(context);
  const receiptSchema = (
    context: WorkflowContext,
  ): StageReceiptPartition => {
    const exactRefs = refs(context);
    const payload = asFragment(payloadProperties(exactRefs));
    return stageReceiptPartition({
      operation,
      stage,
      materialKey: context.materialKey,
      effect,
      required: payload.required || [],
      properties: payload.properties || {},
      terminalPayloads: terminalPayloads
        ? terminalPayloads(exactRefs)
        : {},
    });
  };
  const prompt = (context: WorkflowContext): string => {
    const request = envelope(context, refs(context));
    return promptText
      ? promptText(request)
      : JSON.stringify(request, null, 2);
  };
  return {
    refs,
    receiptSchema,
    complete: (receipt, context) => complete(receipt, context) === true,
    prompt,
  };
}
