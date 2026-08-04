import type {
  TalkRunInput,
  TalkStatusObservation,
} from "../contracts/talk.mts";
import { prepareOperation } from "../operations/catalogs/talk.mts";
import { observationKey } from "../shared/material-input.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  completeMaterialResult,
  stoppedMaterialResult,
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

interface TalkState {
  slug: string;
}

interface TalkCarry {
  classification: "live" | "dead" | "empty";
  inputs: Array<{
    role: string;
    path: string;
    sha256: string;
    size: number;
  }>;
}

const resultSeed = (state: TalkState): MaterialResultSeed => ({
  material: {
    requested: { kind: "talk", slug: state.slug },
    canonical: { kind: "talk", slug: state.slug },
  },
});

const planIssue = (
  code: string,
  operation: OperationName | null,
  summary: string,
): MaterialIssue => ({
  code,
  operation,
  summary,
  retryable: false,
  observation_request: null,
});

const receiptIssue = (receipt: StageReceipt): MaterialIssue => {
  const issue = receipt.terminal.issue!;
  return {
    code: issue.code,
    operation: issue.operation as OperationName,
    summary: issue.summary,
    retryable: issue.retryable,
    observation_request: null,
  };
};

const stopForOutcome = (
  state: TalkState,
  outcome: DispatchOutcome,
): MaterialResult | null => {
  if (outcome.kind !== "receipt")
    return blockedMaterialResult(resultSeed(state), outcome.issue);
  if (outcome.receipt.terminal.status === "complete") return null;
  if (outcome.receipt.terminal.status === "needs_input")
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.incoherent_gate",
        outcome.receipt.operation,
        "Talk returned a human gate even though this material has no typed gate.",
      ),
    );
  return stoppedMaterialResult(
    resultSeed(state),
    outcome.receipt.terminal.status,
    receiptIssue(outcome.receipt),
  );
};

const dispatch = (
  runtime: MaterialRuntime,
  operation: OperationName,
  slug: string,
  context: WorkflowContext,
): Promise<DispatchOutcome> =>
  dispatchPreparedOperation(
    runtime,
    prepareOperation({
      operation,
      slug,
      context,
      label: `${slug}:${operation}`,
    }),
  );

const carryFromPrepare = (receipt: StageReceipt): TalkCarry => {
  const primary = receipt.artifacts.find(
    (artifact: { role: string }) => artifact.role === "transcript",
  );
  const engineTranscripts = receipt.artifacts.filter(
    (artifact: { role: string }) => artifact.role === "engine_transcript",
  );
  return {
    classification: receipt.classification,
    inputs: [primary, ...engineTranscripts],
  } as TalkCarry;
};

const completedTalk = (state: TalkState): MaterialResult =>
  completeMaterialResult(
    resultSeed(state),
    [
      {
        role: "canonical",
        path: `vault/talks/${state.slug}/talk.md`,
      },
    ],
    null,
  );

const auditHasForeignTarget = (
  receipt: StageReceipt,
  target: string,
): boolean =>
  receipt.escalated.some(
    (diagnostic: { path: string }) => diagnostic.path !== target,
  );

const auditTalk = async (
  runtime: MaterialRuntime,
  input: TalkRunInput,
  state: TalkState,
  currentCarry: TalkCarry | null,
): Promise<MaterialResult> => {
  const common = {
    meta: {
      ...input.seed.identity,
      engines: input.options.engines,
      lang: input.options.lang,
      prepare_media: input.options.prepare_media,
    },
    materialKey: `talk:${state.slug}`,
  };
  const firstAudit = await dispatch(runtime, "talk.audit", state.slug, {
    ...common,
    pass: 1,
  });
  const firstStop = stopForOutcome(state, firstAudit);
  if (firstStop !== null) return firstStop;

  const firstReceipt = firstAudit.receipt as StageReceipt;
  const target = firstReceipt.target_path as string;
  if (firstReceipt.remaining_violations === 0) return completedTalk(state);
  if (auditHasForeignTarget(firstReceipt, target))
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "talk.audit",
        "Audit escalation targeted an artifact outside this Talk.",
      ),
    );

  let repairCarry = currentCarry;
  if (repairCarry === null || repairCarry.classification !== "live") {
    const prepared = await dispatch(runtime, "talk.prepare", state.slug, {
      ...common,
      mode: "repair",
      diagnostics: firstReceipt.escalated,
    });
    const prepareStop = stopForOutcome(state, prepared);
    if (prepareStop !== null) return prepareStop;
    repairCarry = carryFromPrepare(prepared.receipt as StageReceipt);
  }

  if (repairCarry.classification === "live") {
    const analysed = await dispatch(runtime, "talk.analyse", state.slug, {
      ...common,
      inputs: repairCarry.inputs,
      mode: "repair",
      diagnostics: firstReceipt.escalated,
    });
    const analyseStop = stopForOutcome(state, analysed);
    if (analyseStop !== null) return analyseStop;
  }

  const secondAudit = await dispatch(runtime, "talk.audit", state.slug, {
    ...common,
    pass: 2,
  });
  const secondStop = stopForOutcome(state, secondAudit);
  if (secondStop !== null) return secondStop;
  const secondReceipt = secondAudit.receipt as StageReceipt;
  if (auditHasForeignTarget(secondReceipt, target))
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "talk.audit",
        "Audit escalation targeted an artifact outside this Talk.",
      ),
    );
  if (secondReceipt.remaining_violations === 0) return completedTalk(state);
  return blockedMaterialResult(
    resultSeed(state),
    planIssue(
      "workflow.repair_exhausted",
      "talk.audit",
      "The bounded Talk repair completed, but the second audit still found violations.",
    ),
  );
};

export async function runTalkPlan(
  runtime: MaterialRuntime,
  input: TalkRunInput,
): Promise<MaterialResult> {
  const slug = input.seed.material_slug;
  const observation = input.observations.get(
    observationKey({ kind: "talk", slug }),
  ) as TalkStatusObservation;
  const state = { slug };

  if (observation.facts.canonical.usable)
    return auditTalk(runtime, input, state, null);

  const common = {
    meta: {
      ...input.seed.identity,
      engines: input.options.engines,
      lang: input.options.lang,
      prepare_media: input.options.prepare_media,
    },
    materialKey: `talk:${slug}`,
  };
  const prepared = await dispatch(runtime, "talk.prepare", slug, common);
  const prepareStop = stopForOutcome(state, prepared);
  if (prepareStop !== null) return prepareStop;
  const carry = carryFromPrepare(prepared.receipt as StageReceipt);

  if (carry.classification === "live") {
    const analysed = await dispatch(runtime, "talk.analyse", slug, {
      ...common,
      inputs: carry.inputs,
      mode: observation.facts.canonical.present ? "repair" : "create",
    });
    const analyseStop = stopForOutcome(state, analysed);
    if (analyseStop !== null) return analyseStop;
  }

  return auditTalk(runtime, input, state, carry);
}
