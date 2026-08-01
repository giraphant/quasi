import { stageContract, stageReceiptSchema } from "../stage.mjs";

const EFFECTS = new Set(["readonly", "writer"]);

const asFragment = (fragment) =>
  fragment && typeof fragment === "object" ? fragment : {};

export function defineOperation(descriptor) {
  const {
    operation,
    stage,
    effect,
    agentType,
    refs: makeRefs,
    payloadProperties,
    terminalPayloads,
    complete,
    envelope,
    promptText,
  } = descriptor;
  if (!EFFECTS.has(effect))
    throw new Error(`unknown operation effect: ${effect}`);

  const refs = (context) => makeRefs(context);
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
  const prompt = (context) => {
    const request = envelope(context, refs(context));
    return promptText
      ? promptText(request)
      : JSON.stringify(request, null, 2);
  };
  return { schema, contract, prompt };
}
