import {
  bookChapterOutputPath,
  bookManifestPath,
  bookObservationAdmitsIdentity,
  bookOverviewPath,
  parseBookStructureDecisionValue,
  parseBookStructureGate,
  parseBookYearDecisionValue,
  parseBookYearGate,
  type BookChapterObservation,
  type BookIdentity,
  type BookRunInput,
  type BookStatusObservation,
  type BookStructureDecisionValue,
  type BookYearDecisionValue,
} from "../contracts/book.mts";
import {
  parseIdentityConflictDecisionValue,
  parseIdentityConflictGate,
} from "../contracts/search.mts";
import { prepareOperation } from "../operations/catalogs/book.mts";
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
import { sameClosedValue } from "../runtime.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

type BookFormat = "epub" | "pdf";
type ChapterInventoryRow = Omit<
  BookChapterObservation,
  "input" | "output"
>;

interface BookState {
  requestedSlug: string;
  runtimeSlug: string | null;
  identity: BookIdentity | null;
  observation: BookStatusObservation | null;
}

interface SelectedSource {
  path: string;
  format: BookFormat;
}

const resultSeed = (state: BookState): MaterialResultSeed => ({
  material: {
    requested: { kind: "book", slug: state.requestedSlug },
    canonical:
      state.runtimeSlug === null
        ? null
        : { kind: "book", slug: state.runtimeSlug },
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
  state: BookState,
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
        "The specialist returned a human gate outside its typed Book boundary.",
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

const allowedFormats = (
  options: Readonly<Record<string, unknown>>,
): BookFormat[] | null => {
  if (Object.keys(options).some((key) => key !== "allowed_formats"))
    return null;
  if (!Object.hasOwn(options, "allowed_formats")) return ["epub", "pdf"];
  const formats = options.allowed_formats;
  if (
    !Array.isArray(formats) ||
    formats.length < 1 ||
    formats.length > 2 ||
    formats.some((format) => !["epub", "pdf"].includes(format as string)) ||
    new Set(formats).size !== formats.length
  )
    return null;
  return formats as BookFormat[];
};

const manifestReady = (observation: BookStatusObservation | null): boolean =>
  observation !== null &&
  observation.facts.manifest.present &&
  observation.facts.manifest.usable &&
  observation.facts.manifest.valid &&
  observation.facts.chapters.length > 0;

const fanoutReady = (observation: BookStatusObservation | null): boolean =>
  manifestReady(observation) &&
  observation!.facts.chapters.every(
    (chapter) => chapter.input.present && chapter.input.usable,
  );

const finalObservedBook = (
  observation: BookStatusObservation | null,
  identity: BookIdentity,
): boolean =>
  manifestReady(observation) &&
  observation!.facts.chapters.every(
    (chapter) => chapter.output.present && chapter.output.usable,
  ) &&
  observation!.facts.overview.present &&
  observation!.facts.overview.usable &&
  bookObservationAdmitsIdentity(observation!, identity);

const sourceFromObservation = (
  observation: BookStatusObservation | null,
  formats: readonly BookFormat[],
): SelectedSource | null => {
  if (observation === null) return null;
  for (const format of formats) {
    const source = observation.facts.sources.find(
      (candidate) => candidate.format === format,
    )!;
    if (source.artifact.present && source.artifact.usable)
      return { path: source.artifact.path, format };
  }
  return null;
};

const completedBook = (
  state: BookState,
  chapters: readonly ChapterInventoryRow[],
): MaterialResult => {
  const slug = state.runtimeSlug as string;
  return completeMaterialResult(
    resultSeed(state),
    [
      { role: "manifest", path: bookManifestPath(slug) },
      ...chapters.map((chapter) => ({
        role: "chapter" as const,
        path: bookChapterOutputPath(slug, chapter),
      })),
      { role: "overview", path: bookOverviewPath(slug) },
    ],
    null,
  );
};

const liftSearchGate = (
  state: BookState,
  receipt: StageReceipt,
): MaterialResult => {
  const gate = parseIdentityConflictGate(receipt, "book");
  return gate === null
    ? blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.incoherent_gate",
          "material.search",
          "The identity specialist returned an invalid Book conflict gate.",
        ),
      )
    : needsInputMaterialResult(resultSeed(state), receiptIssue(receipt), gate);
};

const bindSearchReceipt = (
  input: BookRunInput,
  state: BookState,
  receipt: StageReceipt,
): void => {
  state.identity = receipt.identity as BookIdentity;
  state.runtimeSlug =
    receipt.local_owner === null
      ? state.identity.slug
      : receipt.local_owner.vault_slug;
  state.observation =
    input.observations.get(
      observationKey({ kind: "book", slug: state.runtimeSlug as string }),
    ) ?? null;
};

const auditBook = async (
  runtime: MaterialRuntime,
  state: BookState,
  chapters: readonly ChapterInventoryRow[],
  observedOutputs: ReadonlySet<string>,
  currentRunOutputs: ReadonlySet<string>,
): Promise<MaterialResult> => {
  const slug = state.runtimeSlug as string;
  const common = {
    meta: state.identity,
    materialKey: `book:${slug}`,
  };
  const inputPaths = chapters.map((chapter) =>
    bookChapterOutputPath(slug, chapter),
  );
  const chapterOwners = new Map(
    chapters.map((chapter) => [bookChapterOutputPath(slug, chapter), chapter]),
  );
  const ownedOverview = bookOverviewPath(slug);

  const firstAudit = await dispatch(runtime, "book.audit", slug, {
    ...common,
    pass: 1,
  });
  const firstStop = stopForOutcome(state, firstAudit);
  if (firstStop !== null) return firstStop;
  const firstReceipt = firstAudit.receipt as StageReceipt;
  if (firstReceipt.remaining_violations === 0)
    return completedBook(state, chapters);

  const escalated = firstReceipt.escalated as Array<{
    path: string;
    kind: string;
    reason: string;
  }>;
  if (
    escalated.some(
      ({ path }) => path !== ownedOverview && !chapterOwners.has(path),
    )
  )
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "book.audit",
        "Audit escalation targeted an artifact outside this Book.",
      ),
    );

  const repairPath = escalated[0]!.path;
  const diagnostics = escalated.filter(({ path }) => path === repairPath);
  const chapter = chapterOwners.get(repairPath);
  if (chapter !== undefined) {
    if (!observedOutputs.has(repairPath) && !currentRunOutputs.has(repairPath))
      return blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.owner_ambiguity",
          "chapter.analyse",
          "Audit requested repair of a chapter output not established by disk or this run.",
        ),
      );
    const repaired = await dispatch(runtime, "chapter.analyse", slug, {
      ...common,
      chapter,
      mode: "repair",
      output_exists: true,
      diagnostics,
    });
    const repairStop = stopForOutcome(state, repaired);
    if (repairStop !== null) return repairStop;
  } else {
    const repaired = await dispatch(runtime, "book.synthesise", slug, {
      ...common,
      inputPaths,
      mode: "repair",
      diagnostics,
    });
    const repairStop = stopForOutcome(state, repaired);
    if (repairStop !== null) return repairStop;
  }

  const secondAudit = await dispatch(runtime, "book.audit", slug, {
    ...common,
    pass: 2,
  });
  const secondStop = stopForOutcome(state, secondAudit);
  if (secondStop !== null) return secondStop;
  const secondReceipt = secondAudit.receipt as StageReceipt;
  if (
    (secondReceipt.escalated as Array<{ path: string }>).some(
      ({ path }) => path !== ownedOverview && !chapterOwners.has(path),
    )
  )
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "workflow.owner_ambiguity",
        "book.audit",
        "The second audit targeted an artifact outside this Book.",
      ),
    );
  if (secondReceipt.remaining_violations === 0)
    return completedBook(state, chapters);
  return blockedMaterialResult(
    resultSeed(state),
    planIssue(
      "workflow.repair_exhausted",
      "book.audit",
      "The bounded Book repair completed, but the second audit still found violations.",
    ),
  );
};

export async function runBookPlan(
  runtime: MaterialRuntime,
  input: BookRunInput,
): Promise<MaterialResult> {
  const formats = allowedFormats(input.options);
  const requestedSlug =
    input.seed.state === "provisional"
      ? input.seed.requested_slug
      : input.seed.material_slug;
  const initialObservation = input.observations.get(
    observationKey({ kind: "book", slug: requestedSlug }),
  ) as BookStatusObservation;
  const state: BookState = {
    requestedSlug,
    runtimeSlug:
      input.seed.state === "canonical" ? input.seed.material_slug : null,
    identity:
      input.seed.state === "canonical" ? input.seed.identity : null,
    observation: initialObservation,
  };
  if (formats === null)
    return blockedMaterialResult(
      resultSeed(state),
      planIssue(
        "material.invalid_input",
        null,
        "Book options accept only one unique allowed_formats ordering.",
      ),
    );

  const rawYearDecision =
    input.userDecision?.operation === "book.acquire"
      ? input.userDecision.value
      : null;
  const parsedYearDecision: BookYearDecisionValue | null =
    rawYearDecision === null
      ? null
      : parseBookYearDecisionValue(rawYearDecision);
  const rawStructureDecision =
    input.userDecision?.operation === "book.prepare"
      ? input.userDecision.value
      : null;
  const parsedStructureDecision: BookStructureDecisionValue | null =
    rawStructureDecision === null
      ? null
      : parseBookStructureDecisionValue(rawStructureDecision);

  const admittedCanonical =
    input.seed.state === "canonical" &&
    bookObservationAdmitsIdentity(initialObservation, input.seed.identity);
  if (!admittedCanonical) {
    const searchKey = `book:${requestedSlug}`;
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
      ? parseIdentityConflictDecisionValue(rawDecision, undefined, "book")
      : null;
    if (matchedDecision && identityDecision === null)
      return blockedMaterialResult(
        resultSeed(state),
        planIssue(
          "workflow.incoherent_gate",
          "material.search",
          "The identity decision does not echo one valid Book candidate set and selection.",
        ),
      );

    const query =
      identityDecision?.selected_candidate.identity ??
      (input.seed.state === "provisional"
        ? input.seed.hints
        : input.seed.identity);
    const searchSlug =
      identityDecision?.selected_candidate.identity.slug ?? requestedSlug;
    const searched = await dispatch(runtime, "material.search", searchSlug, {
      materialKey: searchKey,
      meta: query,
      query,
      ...(identityDecision === null ? {} : { identityDecision }),
    });
    if (
      searched.kind === "receipt" &&
      searched.receipt.terminal.status === "needs_input"
    )
      return liftSearchGate(state, searched.receipt);
    const searchStop = stopForOutcome(state, searched);
    if (searchStop !== null) return searchStop;
    bindSearchReceipt(input, state, searched.receipt as StageReceipt);
  }

  if (finalObservedBook(state.observation, state.identity as BookIdentity)) {
    const observedOutputs = new Set(
      state.observation!.facts.chapters
        .filter((chapter) => chapter.output.present)
        .map((chapter) => chapter.output.path),
    );
    return auditBook(
      runtime,
      state,
      state.observation!.facts.chapters,
      observedOutputs,
      new Set(),
    );
  }

  let source = sourceFromObservation(state.observation, formats);
  let appliedYearDecision: BookYearDecisionValue | null = null;
  if (!fanoutReady(state.observation) && source === null) {
    const currentKey = `book:${state.runtimeSlug}`;
    const matchedYearEnvelope =
      input.userDecision?.operation === "book.acquire" &&
      input.userDecision.material_key === currentKey;
    if (
      matchedYearEnvelope &&
      rawYearDecision !== null
    ) {
      if (parsedYearDecision === null)
        return blockedMaterialResult(
          resultSeed(state),
          planIssue(
            "workflow.incoherent_gate",
            "book.acquire",
            "The Book year decision is structurally incoherent.",
          ),
        );
      if (
        sameClosedValue(
          parsedYearDecision.current_identity,
          state.identity,
        )
      ) {
        appliedYearDecision = parsedYearDecision;
        if (parsedYearDecision.action === "use-recommended-year") {
          const searched = await dispatch(
            runtime,
            "material.search",
            state.runtimeSlug as string,
            {
              materialKey: currentKey,
              meta: state.identity,
              query: state.identity,
              yearDecision: parsedYearDecision,
            },
          );
          if (
            searched.kind === "receipt" &&
            searched.receipt.terminal.status === "needs_input"
          )
            return liftSearchGate(state, searched.receipt);
          const searchStop = stopForOutcome(state, searched);
          if (searchStop !== null) return searchStop;
          bindSearchReceipt(input, state, searched.receipt as StageReceipt);
        }
      }
    }

    const slug = state.runtimeSlug as string;
    const acquired = await dispatch(runtime, "book.acquire", slug, {
      meta: state.identity,
      materialKey: `book:${slug}`,
      allowed_formats: formats,
      ...(appliedYearDecision === null
        ? {}
        : { yearDecision: appliedYearDecision }),
    });
    if (
      acquired.kind === "receipt" &&
      acquired.receipt.terminal.status === "needs_input"
    ) {
      const gate = parseBookYearGate(acquired.receipt, state.identity);
      return gate === null
        ? blockedMaterialResult(
            resultSeed(state),
            planIssue(
              "workflow.incoherent_gate",
              "book.acquire",
              "The download specialist returned an invalid Book year gate.",
            ),
          )
        : needsInputMaterialResult(
            resultSeed(state),
            receiptIssue(acquired.receipt),
            gate,
          );
    }
    const acquireStop = stopForOutcome(state, acquired);
    if (acquireStop !== null) return acquireStop;
    const receipt = acquired.receipt as StageReceipt;
    source = {
      path: receipt.output_path as string,
      format: receipt.format as BookFormat,
    };
  }

  let chapters: ChapterInventoryRow[];
  if (fanoutReady(state.observation)) {
    chapters = state.observation!.facts.chapters;
  } else {
    const slug = state.runtimeSlug as string;
    const currentKey = `book:${slug}`;
    let structureDecision: BookStructureDecisionValue | null = null;
    const matchedStructureEnvelope =
      input.userDecision?.operation === "book.prepare" &&
      input.userDecision.material_key === currentKey;
    if (matchedStructureEnvelope && source!.format === "pdf") {
      if (parsedStructureDecision === null)
        return blockedMaterialResult(
          resultSeed(state),
          planIssue(
            "workflow.incoherent_gate",
            "book.prepare",
            "The Book structure decision is structurally incoherent.",
          ),
        );
      const recoverySource = `processing/chapters/${slug}/ocr.pdf`;
      if (
        [source!.path, recoverySource].includes(
          parsedStructureDecision.source_path,
        )
      )
        structureDecision = parsedStructureDecision;
    }

    const prepared = await dispatch(runtime, "book.prepare", slug, {
      meta: state.identity,
      materialKey: currentKey,
      source: source!.path,
      format: source!.format,
      ...(structureDecision === null ? {} : { structureDecision }),
    });
    if (
      prepared.kind === "receipt" &&
      prepared.receipt.terminal.status === "needs_input"
    ) {
      const gate = parseBookStructureGate(prepared.receipt);
      return gate === null
        ? blockedMaterialResult(
            resultSeed(state),
            planIssue(
              "workflow.incoherent_gate",
              "book.prepare",
              "The extraction specialist returned an invalid Book structure gate.",
            ),
          )
        : needsInputMaterialResult(
            resultSeed(state),
            receiptIssue(prepared.receipt),
            gate,
          );
    }
    const prepareStop = stopForOutcome(state, prepared);
    if (prepareStop !== null) return prepareStop;
    chapters = (prepared.receipt as StageReceipt)
      .chapters as ChapterInventoryRow[];
  }

  const slug = state.runtimeSlug as string;
  const observedOutputs = new Set(
    (state.observation?.facts.chapters ?? [])
      .filter((chapter) => chapter.output.present)
      .map((chapter) => chapter.output.path),
  );
  const common = {
    meta: state.identity,
    materialKey: `book:${slug}`,
  };
  const preparedChapters = chapters.map((chapter) =>
    prepareOperation({
      operation: "chapter.analyse",
      slug,
      label: `${slug}:analyse:${chapter.slug}`,
      context: {
        ...common,
        chapter,
        output_exists: observedOutputs.has(
          bookChapterOutputPath(slug, chapter),
        ),
      },
    }),
  );
  const outcomes = await runtime.pipeline(
    preparedChapters,
    (operation) => dispatchPreparedOperation(runtime, operation),
  );
  const unknown = outcomes.find(
    (outcome) => outcome.kind === "unknown_outcome",
  );
  if (unknown !== undefined)
    return blockedMaterialResult(resultSeed(state), unknown.issue);
  for (const outcome of outcomes) {
    const stop = stopForOutcome(state, outcome);
    if (stop !== null) return stop;
  }

  const currentRunOutputs = new Set(
    outcomes.map(
      (outcome) =>
        (outcome as { kind: "receipt"; receipt: StageReceipt }).receipt
          .output_path as string,
    ),
  );
  const inputPaths = chapters.map((chapter) =>
    bookChapterOutputPath(slug, chapter),
  );
  const synthesised = await dispatch(runtime, "book.synthesise", slug, {
    ...common,
    inputPaths,
    mode: state.observation?.facts.overview.present ? "repair" : "create",
  });
  const synthesisStop = stopForOutcome(state, synthesised);
  if (synthesisStop !== null) return synthesisStop;

  return auditBook(
    runtime,
    state,
    chapters,
    observedOutputs,
    currentRunOutputs,
  );
}
