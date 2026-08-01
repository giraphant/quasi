import { stageContract, stageReceiptSchema } from "../stage.mjs";

const RETRY_POLICY = {
  readonly: "safe",
  writer: "forbidden",
};

const UNKNOWN_FAILURE_CODE = {
  readonly: "material.readonly_outcome_unknown",
  writer: "material.writer_outcome_unknown",
};

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
  if (!Object.hasOwn(RETRY_POLICY, effect))
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
  const spec = (context) => ({
    key: operation,
    effect,
    retry: RETRY_POLICY[effect],
    replay: context.replay || "blocked",
    artifactRoles: context.artifactRoles || [],
    unknownFailureCode:
      context.unknownFailureCode || UNKNOWN_FAILURE_CODE[effect],
    contract,
    context,
    stage,
    agentType,
  });

  return { schema, contract, prompt, spec };
}
