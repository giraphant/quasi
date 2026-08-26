import {
  paperObservationAdmitsIdentity,
  paperObservationAdmitsOwnerContinuation,
  parsePaperSourceDecisionValue,
  type PaperIdentity,
  type PaperOwnerConfirmation,
  type PaperRunInput,
  type PaperSourceCandidate,
  type PaperSourceGate,
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
  needsObservationMaterialResult,
  stoppedMaterialResult,
  type ComposedLeafResumeSeed,
  type LeafCompositionOutcome,
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import { normalizeWebUrl } from "../shared/web-url.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

interface PaperState {
  requestedSlug: string;
  runtimeSlug: string | null;
  identity: PaperIdentity | null;
  ownerConfirmation: PaperOwnerConfirmation | null;
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
      ? state.ownerConfirmation === null
        ? {
            state: "canonical" as const,
            material_slug: state.runtimeSlug,
            identity: state.identity,
          }
        : {
            state: "canonical" as const,
            material_slug: state.runtimeSlug,
            identity: state.identity,
            owner_confirmation: state.ownerConfirmation,
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
  sourcePath: string,
  selectedInput: string,
  canonicalPath: string,
): MaterialResult =>
  completeMaterialResult(
    resultSeed(state),
    [
      {
        role: "source",
        path: sourcePath,
      },
      {
        role: "normalized_text",
        path: selectedInput,
      },
      {
        role: "canonical",
        path: canonicalPath,
      },
    ],
    null,
  );

const auditIsClean = (receipt: StageReceipt): boolean =>
  receipt.remaining_violations === 0 && receipt.escalated.length === 0;

const auditIsSettled = (receipt: StageReceipt): boolean =>
  auditIsClean(receipt) && receipt.mutated_paths.length === 0;

const auditOwnsTarget = (
  receipt: StageReceipt,
  target: string,
): boolean =>
  receipt.target_path === target &&
  receipt.escalated.every(
    (diagnostic: { path: string }) => diagnostic.path === target,
  ) &&
  receipt.mutated_paths.every((path: string) => path === target);

const auditOwnershipBlock = (state: PaperState): MaterialResult =>
  blockedMaterialResult(
    resultSeed(state),
    planIssue(
      "workflow.owner_ambiguity",
      "paper.audit",
      "Audit evidence targeted an artifact outside this Paper.",
    ),
  );

const auditUnstableBlock = (state: PaperState): MaterialResult =>
  blockedMaterialResult(
    resultSeed(state),
    planIssue(
      "workflow.audit_unstable",
      "paper.audit",
      "The final Paper audit was not stable and mutation-free.",
    ),
  );

const auditPaper = async (
  runtime: MaterialRuntime,
  input: PaperRunInput,
  state: PaperState,
  sourcePath: string,
  selectedInput: string,
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
  if (!auditOwnsTarget(firstReceipt, target))
    return auditOwnershipBlock(state);
  if (auditIsSettled(firstReceipt))
    return completedPaper(state, sourcePath, selectedInput, target);

  if (auditIsClean(firstReceipt)) {
    const stabilityAudit = await dispatch(runtime, "paper.audit", slug, {
      ...common,
      pass: 2,
    });
    const stabilityStop = stopForOutcome(state, stabilityAudit);
    if (stabilityStop !== null) return stabilityStop;
    const stabilityReceipt = stabilityAudit.receipt as StageReceipt;
    if (!auditOwnsTarget(stabilityReceipt, target))
      return auditOwnershipBlock(state);
    return auditIsSettled(stabilityReceipt)
      ? completedPaper(state, sourcePath, selectedInput, target)
      : auditUnstableBlock(state);
  }

  const repaired = await dispatch(runtime, "paper.analyse", slug, {
    ...common,
    input: selectedInput,
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
  if (!auditOwnsTarget(secondReceipt, target))
    return auditOwnershipBlock(state);
  if (auditIsSettled(secondReceipt))
    return completedPaper(state, sourcePath, selectedInput, target);
  if (auditIsClean(secondReceipt)) return auditUnstableBlock(state);
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
    ownerConfirmation:
      input.seed.state === "canonical" &&
      "owner_confirmation" in input.seed
        ? input.seed.owner_confirmation
        : null,
    observation: initialObservation,
  };
  rememberContinuation(resumeSeed(input, state));

  const admittedCanonical =
    input.seed.state === "canonical" &&
    (paperObservationAdmitsIdentity(
      initialObservation,
      input.seed.identity,
    ) ||
      ("owner_confirmation" in input.seed &&
        paperObservationAdmitsOwnerContinuation(
          initialObservation,
          input.seed,
        )));
  let canonicalReady = admittedCanonical;

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
    if (
      searched.kind === "receipt" &&
      searched.receipt.terminal.status === "failed"
    ) {
      const terminal = searched.receipt.terminal as unknown as {
        issue: { code: string };
        webpage_url: unknown;
      };
      if (terminal.issue.code === "material.webpage_redirect") {
        const url = normalizeWebUrl(terminal.webpage_url);
        if (url === null)
          return blockedMaterialResult(
            resultSeed(state),
            planIssue(
              "workflow.incoherent_complete",
              "material.search",
              "The Webpage redirect omitted one valid public HTTP(S) URL.",
            ),
          );
        return completeMaterialResult(
          {
            material: {
              requested: { kind: "paper", slug: requestedSlug },
              canonical: null,
            },
          },
          [],
          { kind: "webpage", url },
        );
      }
      if (terminal.webpage_url !== null)
        return blockedMaterialResult(
          resultSeed(state),
          planIssue(
            "workflow.incoherent_complete",
            "material.search",
            "A non-redirect Search failure included a Webpage URL.",
          ),
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
    state.ownerConfirmation =
      search.owner_slug !== null && search.owner_slug !== state.identity.slug
        ? {
            operation: "material.search",
            identity_slug: state.identity.slug,
            owner_slug: search.owner_slug,
          }
        : null;
    state.observation =
      input.observations.get(
        observationKey({ kind: "paper", slug: runtimeSlug }),
      ) ?? null;
    rememberContinuation(resumeSeed(input, state));

    if (search.owner_slug !== null) {
      if (
        state.observation === null ||
        !state.observation.facts.canonical.present ||
        !state.observation.facts.canonical.usable
      )
        return needsObservationMaterialResult(
          resultSeed(state),
          [{ kind: "paper", slug: runtimeSlug }],
          resumeSeed(input, state),
        );
      canonicalReady = true;
    }
  }

  if (
    state.observation !== null &&
    paperObservationAdmitsIdentity(
      state.observation,
      state.identity as PaperIdentity,
    )
  )
    canonicalReady = true;

  const slug = state.runtimeSlug as string;
  const common = {
    ...input.options,
    meta: state.identity,
    materialKey: `paper:${slug}`,
  };
  const usableSourceFacts = (state.observation?.facts.sources ?? [])
    .filter(({ artifact }) => artifact.usable);
  const usableSources = usableSourceFacts.map(({ artifact }) => artifact.path);
  let sourcePath = usableSources[0] ?? null;
  if (usableSourceFacts.length > 1) {
    const materialKey = `paper:${slug}`;
    const candidates = usableSourceFacts.map(
      ({ candidate }) => candidate as PaperSourceCandidate,
    );
    const candidatesFingerprint = state.observation!
      .facts.source_candidates_fingerprint;
    const gate: PaperSourceGate = {
      kind: "paper_source",
      operation: "paper.prepare",
      material_key: materialKey,
      question: "Which exact Paper source should Prepare use?",
      candidates,
      candidates_fingerprint: candidatesFingerprint,
    };
    const matchingDecision =
      input.userDecision?.material_key === materialKey &&
      input.userDecision.operation === "paper.prepare";
    const rawDecision = decisionForOperation(
      input.userDecision,
      materialKey,
      "paper.prepare",
      false,
    );
    const sourceDecision = matchingDecision
      ? parsePaperSourceDecisionValue(rawDecision)
      : null;
    if (matchingDecision && sourceDecision === null)
      return blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.incoherent_gate",
          "paper.prepare",
          "The Paper source decision does not bind one candidate fingerprint and source path.",
        ),
      );
    const selectedCandidate =
      sourceDecision?.candidates_fingerprint === candidatesFingerprint
        ? candidates.find(
            (candidate) => candidate.path === sourceDecision.source_path,
          ) ?? null
        : null;
    if (selectedCandidate === null)
      return needsInputMaterialResult(
        resultSeed(state),
        planIssue(
          "paper.source_selection_required",
          "paper.prepare",
          "Two exact Paper source alternatives are usable and require one bound selection.",
        ),
        gate,
        resumeSeed(input, state),
      );
    sourcePath = selectedCandidate.path;
  }
  if (sourcePath === null) {
    const acquired = await dispatch(runtime, "paper.acquire", slug, common);
    const acquireStop = stopForOutcome(state, acquired);
    if (acquireStop !== null) return acquireStop;
    sourcePath = (acquired.receipt as StageReceipt).output_path as string;
  }

  const prepared = await dispatch(runtime, "paper.prepare", slug, {
    ...common,
    source: sourcePath,
  });
  const prepareStop = stopForOutcome(state, prepared);
  if (prepareStop !== null) return prepareStop;
  const selectedInput = (prepared.receipt as StageReceipt).selected_input;

  if (!canonicalReady) {
    const analysed = await dispatch(runtime, "paper.analyse", slug, {
      ...common,
      input: selectedInput,
      mode: state.observation?.facts.canonical.present ? "repair" : "create",
    });
    const analyseStop = stopForOutcome(state, analysed);
    if (analyseStop !== null) return analyseStop;
  }

  return auditPaper(runtime, input, state, sourcePath, selectedInput);
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
