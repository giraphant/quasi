import {
  paperObservationAdmitsIdentity,
  type PaperIdentity,
  type PaperRunInput,
  type PaperStatusObservation,
} from "../contracts/paper.mts";
import {
  parseIdentityConflictDecisionValue,
  parseIdentityConflictGate,
} from "../contracts/search.mts";
import { prepareOperation } from "../operations/catalogs/paper.mts";
import {
  decisionForOperation,
  observationKey,
} from "../shared/material-input.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  completeMaterialResult,
  needsInputMaterialResult,
  stoppedMaterialResult,
  type ComposedLeafResumeSeed,
  type LeafCompositionOutcome,
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

interface PaperState {
  requestedSlug: string;
  runtimeSlug: string | null;
  identity: PaperIdentity | null;
  observation: PaperStatusObservation | null;
}

const resultSeed = (state: PaperState): MaterialResultSeed => ({
  material: {
    requested: { kind: "paper", slug: state.requestedSlug },
    canonical:
      state.runtimeSlug === null
        ? null
        : { kind: "paper", slug: state.runtimeSlug },
  },
});

const resumeSeed = (
  input: PaperRunInput,
  state: PaperState,
): Extract<ComposedLeafResumeSeed, { route: { kind: "paper" } }> => {
  const seed =
    state.runtimeSlug !== null && state.identity !== null
      ? {
          state: "canonical" as const,
          material_slug: state.runtimeSlug,
          identity: state.identity,
        }
      : input.seed;
  return {
    route: {
      kind: "paper",
      slug:
        seed.state === "provisional"
          ? seed.requested_slug
          : seed.material_slug,
    },
    seed,
    options: input.options,
  };
};

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
  state: PaperState,
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
        "The specialist returned a human gate outside its typed material boundary.",
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

const completedPaper = (
  state: PaperState,
  canonicalPath: string,
): MaterialResult =>
  completeMaterialResult(
    resultSeed(state),
    [
      {
        role: "canonical",
        path: canonicalPath,
      },
    ],
    null,
  );

const auditPaper = async (
  runtime: MaterialRuntime,
  input: PaperRunInput,
  state: PaperState,
  selectedInput: string | null,
): Promise<MaterialResult> => {
  const slug = state.runtimeSlug as string;
  const common = {
    ...input.options,
    meta: state.identity,
    materialKey: `paper:${slug}`,
  };
  const firstAudit = await dispatch(runtime, "paper.audit", slug, {
    ...common,
    pass: 1,
  });
  const firstStop = stopForOutcome(state, firstAudit);
  if (firstStop !== null) return firstStop;

  const firstReceipt = firstAudit.receipt as StageReceipt;
  const target = firstReceipt.target_path as string;
  if (firstReceipt.remaining_violations === 0)
    return completedPaper(state, target);
  if (
    firstReceipt.escalated.some(
      (diagnostic: { path: string }) => diagnostic.path !== target,
    )
  )
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "paper.audit",
        "Audit escalation targeted an artifact outside this Paper.",
      ),
    );

  let repairInput = selectedInput;
  if (repairInput === null) {
    const prepared = await dispatch(runtime, "paper.prepare", slug, common);
    const prepareStop = stopForOutcome(state, prepared);
    if (prepareStop !== null) return prepareStop;
    repairInput = (prepared.receipt as StageReceipt).selected_input;
  }

  const repaired = await dispatch(runtime, "paper.analyse", slug, {
    ...common,
    input: repairInput,
    mode: "repair",
    diagnostics: firstReceipt.escalated,
  });
  const repairStop = stopForOutcome(state, repaired);
  if (repairStop !== null) return repairStop;

  const secondAudit = await dispatch(runtime, "paper.audit", slug, {
    ...common,
    pass: 2,
  });
  const secondStop = stopForOutcome(state, secondAudit);
  if (secondStop !== null) return secondStop;
  const secondReceipt = secondAudit.receipt as StageReceipt;
  if (
    secondReceipt.escalated.some(
      (diagnostic: { path: string }) => diagnostic.path !== target,
    )
  )
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "paper.audit",
        "Audit escalation targeted an artifact outside this Paper.",
      ),
    );
  if (secondReceipt.remaining_violations === 0)
    return completedPaper(state, secondReceipt.target_path as string);
  return blockedMaterialResult(
    resultSeed(state),
    planIssue(
      "workflow.repair_exhausted",
      "paper.audit",
      "The bounded Paper repair completed, but the second audit still found violations.",
    ),
  );
};

async function runPaperPlanResult(
  runtime: MaterialRuntime,
  input: PaperRunInput,
  rememberContinuation: (
    continuation: Extract<
      ComposedLeafResumeSeed,
      { route: { kind: "paper" } }
    >,
  ) => void,
): Promise<MaterialResult> {
  const requestedSlug =
    input.seed.state === "provisional"
      ? input.seed.requested_slug
      : input.seed.material_slug;
  const initialObservation = input.observations.get(
    observationKey({ kind: "paper", slug: requestedSlug }),
  ) as PaperStatusObservation;
  const state: PaperState = {
    requestedSlug,
    runtimeSlug:
      input.seed.state === "canonical" ? input.seed.material_slug : null,
    identity:
      input.seed.state === "canonical" ? input.seed.identity : null,
    observation: initialObservation,
  };
  rememberContinuation(resumeSeed(input, state));

  const admittedCanonical =
    input.seed.state === "canonical" &&
    paperObservationAdmitsIdentity(
      initialObservation,
      input.seed.identity,
    );

  if (!admittedCanonical) {
    const searchKey = `paper:${requestedSlug}`;
    const matchedDecision =
      input.userDecision?.material_key === searchKey &&
      input.userDecision.operation === "material.search";
    const rawDecision = decisionForOperation(
      input.userDecision,
      searchKey,
      "material.search",
      false,
    );
    const identityDecision = matchedDecision
      ? parseIdentityConflictDecisionValue(rawDecision, undefined, "paper")
      : null;
    if (matchedDecision && identityDecision === null)
      return blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.incoherent_gate",
          "material.search",
          "The identity decision does not echo one valid candidate set and selection.",
        ),
      );
    if (identityDecision?.selected_candidate.kind === "book")
      return completeMaterialResult(
        {
          material: {
            requested: { kind: "paper", slug: requestedSlug },
            canonical: null,
          },
        },
        [],
        identityDecision.selected_candidate,
      );

    const query =
      identityDecision?.selected_candidate.identity ??
      (input.seed.state === "provisional"
        ? input.seed.hints
        : input.seed.identity);
    const searchSlug =
      identityDecision?.selected_candidate.kind === "paper"
        ? identityDecision.selected_candidate.identity.slug
        : requestedSlug;
    const searched = await dispatch(runtime, "material.search", searchSlug, {
      ...input.options,
      materialKey: searchKey,
      meta: query,
      query,
      ...(identityDecision === null
        ? {}
        : { identityDecision }),
    });
    if (
      searched.kind === "receipt" &&
      searched.receipt.terminal.status === "needs_input"
    ) {
      const gate = parseIdentityConflictGate(searched.receipt, "paper");
      if (gate === null)
        return blockedMaterialResult(
          resultSeed(state),
          planIssue(
            "workflow.incoherent_gate",
            "material.search",
            "The identity specialist returned an invalid conflict gate.",
          ),
        );
      return needsInputMaterialResult(
        resultSeed(state),
        receiptIssue(searched.receipt),
        gate,
        resumeSeed(input, state),
      );
    }
    const searchStop = stopForOutcome(state, searched);
    if (searchStop !== null) return searchStop;

    const receipt = searched.receipt as StageReceipt;
    const search = receipt.terminal as unknown as {
      identity: PaperIdentity;
      owner_slug: string | null;
    };
    state.identity = search.identity;
    const runtimeSlug: string =
      search.owner_slug === null
        ? state.identity.slug
        : search.owner_slug;
    state.runtimeSlug = runtimeSlug;
    state.observation =
      input.observations.get(
        observationKey({ kind: "paper", slug: runtimeSlug }),
      ) ?? null;
    rememberContinuation(resumeSeed(input, state));

    if (search.owner_slug !== null)
      return auditPaper(runtime, input, state, null);
  }

  if (
    state.observation !== null &&
    paperObservationAdmitsIdentity(
      state.observation,
      state.identity as PaperIdentity,
    )
  )
    return auditPaper(runtime, input, state, null);

  const slug = state.runtimeSlug as string;
  const common = {
    ...input.options,
    meta: state.identity,
    materialKey: `paper:${slug}`,
  };
  if (!state.observation?.facts.source.usable) {
    const acquired = await dispatch(runtime, "paper.acquire", slug, common);
    const acquireStop = stopForOutcome(state, acquired);
    if (acquireStop !== null) return acquireStop;
  }

  const prepared = await dispatch(runtime, "paper.prepare", slug, common);
  const prepareStop = stopForOutcome(state, prepared);
  if (prepareStop !== null) return prepareStop;
  const selectedInput = (prepared.receipt as StageReceipt).selected_input;

  const analysed = await dispatch(runtime, "paper.analyse", slug, {
    ...common,
    input: selectedInput,
    mode: state.observation?.facts.canonical.present ? "repair" : "create",
  });
  const analyseStop = stopForOutcome(state, analysed);
  if (analyseStop !== null) return analyseStop;

  return auditPaper(runtime, input, state, selectedInput);
}

export async function runPaperPlanForComposition(
  runtime: MaterialRuntime,
  input: PaperRunInput,
): Promise<LeafCompositionOutcome> {
  let continuation = null as Extract<
    ComposedLeafResumeSeed,
    { route: { kind: "paper" } }
  > | null;
  const result = await runPaperPlanResult(
    runtime,
    input,
    (current) => {
      continuation = current;
    },
  );
  return { result, continuation: continuation! };
}

export async function runPaperPlan(
  runtime: MaterialRuntime,
  input: PaperRunInput,
): Promise<MaterialResult> {
  return (await runPaperPlanForComposition(runtime, input)).result;
}
