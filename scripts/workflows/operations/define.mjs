import { stageContract, stageReceiptSchema } from "../stage.mjs";

/** @typedef {import("../artifact-contracts/generated.mjs").JsonSchema} JsonSchema */
/** @typedef {import("../artifact-contracts/generated.mjs").OperationDescriptor} OperationDescriptor */
/** @typedef {import("../artifact-contracts/generated.mjs").WorkflowContext} WorkflowContext */

/** @param {any} fragment @returns {WorkflowContext} */
const asFragment = (fragment) =>
  fragment && typeof fragment === "object" ? fragment : {};

/**
 * @param {OperationDescriptor} descriptor
 * @returns {{
 *   schema: (context: WorkflowContext) => JsonSchema,
 *   contract: any,
 *   prompt: (context: WorkflowContext) => string,
 * }}
 */
export function defineOperation(descriptor) {
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
  /** @param {WorkflowContext} context */
  const refs = (context) => makeRefs(context);
  /** @param {WorkflowContext} context @returns {JsonSchema} */
  const schema = (context) => {
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
  /** @param {WorkflowContext} context @returns {string} */
  const prompt = (context) => {
    const request = envelope(context, refs(context));
    return promptText
      ? promptText(request)
      : JSON.stringify(request, null, 2);
  };
  return { schema, contract, prompt };
}
