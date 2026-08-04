import {
  parseTranslationGate,
  parseTranslationSourceDecisionValue,
  validSelectableTranslationSource,
  type TranslationRunInput,
  type TranslationStatusObservation,
} from "../contracts/translation.mts";
import { prepareOperation } from "../operations/catalogs/translation.mts";
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
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type {
  OperationName,
  StageReceipt,
} from "../artifact-contracts/generated.mjs";

interface TranslationState {
  slug: string;
  observation: TranslationStatusObservation;
}

const resultSeed = (state: TranslationState): MaterialResultSeed => ({
  material: {
    requested: { kind: "translation", slug: state.slug },
    canonical: { kind: "translation", slug: state.slug },
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

const completedTranslation = (state: TranslationState): MaterialResult =>
  completeMaterialResult(
    resultSeed(state),
    [
      { role: "translation", path: state.observation.facts.output.path },
      { role: "manifest", path: state.observation.facts.manifest.path },
    ],
    null,
  );

const stopForOutcome = (
  state: TranslationState,
  outcome: DispatchOutcome,
): MaterialResult => {
  if (outcome.kind !== "receipt")
    return blockedMaterialResult(resultSeed(state), outcome.issue);
  return stoppedMaterialResult(
    resultSeed(state),
    outcome.receipt.terminal.status === "failed" ? "failed" : "blocked",
    receiptIssue(outcome.receipt),
  );
};

export async function runTranslationPlan(
  runtime: MaterialRuntime,
  input: TranslationRunInput,
): Promise<MaterialResult> {
  const slug = input.seed.material_slug;
  const targetLanguage = input.target_language;
  const route = {
    kind: "translation" as const,
    slug,
    target_language: targetLanguage,
  };
  const observation = input.observations.get(
    observationKey(route),
  ) as TranslationStatusObservation;
  const state = { slug, observation };
  if (
    observation.facts.output.usable &&
    observation.facts.manifest.usable
  )
    return completedTranslation(state);

  const materialKey = `translation:paper:${slug}:${targetLanguage}`;
  const matchingDecision =
    input.userDecision?.material_key === materialKey &&
    input.userDecision.operation === "translation.prepare";
  const rawDecision = decisionForOperation(
    input.userDecision,
    materialKey,
    "translation.prepare",
    false,
  );
  const sourceDecision = matchingDecision
    ? parseTranslationSourceDecisionValue(rawDecision)
    : null;
  if (
    matchingDecision &&
    (sourceDecision === null ||
      !validSelectableTranslationSource(
        sourceDecision.source_path,
        slug,
        targetLanguage,
      ))
  )
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.incoherent_gate",
        "translation.prepare",
        "The Translation source decision does not bind one selectable source path and candidate fingerprint.",
      ),
    );

  const prepared = await dispatchPreparedOperation(
    runtime,
    prepareOperation({
      operation: "translation.prepare",
      slug,
      context: {
        materialKey,
        target_language: targetLanguage,
        source_file: input.options.source_file,
        sourceDecision,
        toc_json: input.options.toc_json,
        toc_page_side: input.options.toc_page_side,
      },
      label: `${slug}:translation.prepare`,
    }),
  );
  if (
    prepared.kind === "receipt" &&
    prepared.receipt.terminal.status === "needs_input"
  ) {
    const gate = parseTranslationGate(prepared.receipt);
    if (gate === null || gate.material_key !== materialKey)
      return blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.incoherent_gate",
          "translation.prepare",
          "The Translation specialist returned an invalid typed gate.",
        ),
      );
    return needsInputMaterialResult(
      resultSeed(state),
      receiptIssue(prepared.receipt),
      gate,
    );
  }
  if (
    prepared.kind !== "receipt" ||
    prepared.receipt.terminal.status !== "complete"
  )
    return stopForOutcome(state, prepared);
  return completedTranslation(state);
}
