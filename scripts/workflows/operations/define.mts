import { stageContract, stageReceiptSchema } from "../stage.mts";
import type {
  JsonSchema,
  OperationDescriptor,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

export interface DefinedOperation {
  schema: (context: WorkflowContext) => JsonSchema;
  contract: any;
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
  const refs = (context: WorkflowContext) => makeRefs(context);
  const schema = (context: WorkflowContext): JsonSchema => {
    const exactRefs = refs(context);
    const payload = asFragment(payloadProperties(exactRefs));
    return stageReceiptSchema({
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
  const contract = stageContract({ schema: null, complete });
  const prompt = (context: WorkflowContext): string => {
    const request = envelope(context, refs(context));
    return promptText
      ? promptText(request)
      : JSON.stringify(request, null, 2);
  };
  return { schema, contract, prompt };
}
