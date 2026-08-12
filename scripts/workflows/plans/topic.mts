import type {
  TopicCandidateDemand,
  TopicCheckpointAdmission,
  TopicChildRoute,
  TopicMemberRole,
  TopicPendingWork,
  TopicRecallContinuation,
  TopicRunInput,
  TopicSeedChildContinuation,
  TopicSeedLeaf,
  TopicSubquestionProjection,
  TopicWorkContinuation,
} from "../contracts/topic.mts";
import {
  canonicalFingerprint,
  topicMemberPath,
} from "../contracts/topic.mts";
import {
  paperObservationAdmitsIdentity,
  parsePaperRunInput,
  type PaperIdentity,
  type PaperStatusObservation,
} from "../contracts/paper.mts";
import {
  bookObservationAdmitsIdentity,
  parseBookRunInput,
  type BookIdentity,
  type BookStatusObservation,
} from "../contracts/book.mts";
import {
  parseTalkRunInput,
  type TalkStatusObservation,
} from "../contracts/talk.mts";
import { prepareOperation } from "../operations/catalogs/topic.mts";
import { runPaperPlanForComposition } from "./paper.mts";
import { runBookPlanForComposition } from "./book.mts";
import { runTalkPlan } from "./talk.mts";
import {
  observationKey,
  type UserDecision,
} from "../shared/material-input.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  completeMaterialResult,
  higherOrderNeedsInputMaterialResult,
  incompleteTopicMaterialResult,
  needsObservationMaterialResult,
  stoppedMaterialResult,
  type LeafGate,
  type ExactArtifactRef,
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";
import { sameClosedValue } from "../runtime.mts";

interface MemberRef {
  kind: "paper" | "book" | "talk";
  slug: string;
  path: string;
}

interface MemberAssignment {
  member_key: string;
  subq: string;
  role: TopicMemberRole;
}

interface CardRef {
  slug: string;
  path: string;
  subq: string;
  title: string | null;
}

interface TopicState {
  outlineEstablished: boolean;
  subquestions: TopicSubquestionProjection[];
  members: MemberRef[];
  assignments: MemberAssignment[];
  cards: CardRef[];
  sourceMembers: Map<string, MemberRef>;
}

const resultSeed = (input: TopicRunInput): MaterialResultSeed => ({
  material: {
    requested: { kind: "topic", slug: input.query.slug },
    canonical: { kind: "topic", slug: input.query.slug },
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
  input: TopicRunInput,
  outcome: DispatchOutcome,
): MaterialResult | null => {
  if (outcome.kind !== "receipt")
    return blockedMaterialResult(resultSeed(input), outcome.issue);
  if (outcome.receipt.terminal.status === "complete") return null;
  if (outcome.receipt.terminal.status === "needs_input")
    return blockedMaterialResult(
      resultSeed(input),
      planIssue(
        "workflow.incoherent_gate",
        outcome.receipt.operation,
        "A Topic specialist returned a gate outside the Topic boundary.",
      ),
    );
  return stoppedMaterialResult(
    resultSeed(input),
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

const initialState = (input: TopicRunInput): TopicState => {
  const projection = input.observation.facts.outline.projection;
  if (projection === null)
    return {
      outlineEstablished: input.observation.facts.outline.present,
      subquestions: [],
      members: [],
      assignments: [],
      cards: [],
      sourceMembers: new Map(),
    };
  const memberKeys = new Set<string>();
  const members: MemberRef[] = [];
  const assignments: MemberAssignment[] = [];
  for (const item of projection.members) {
    if (!item.artifact.usable) continue;
    const key = `${item.kind}:${item.slug}`;
    if (!memberKeys.has(key)) {
      memberKeys.add(key);
      members.push({ kind: item.kind, slug: item.slug, path: item.artifact.path });
    }
    if (item.role !== null)
      assignments.push({ member_key: key, subq: item.subq, role: item.role });
  }
  const cards = projection.cards
    .filter((item) => item.artifact.usable)
    .map((item) => ({
      slug: item.slug,
      path: item.artifact.path,
      subq: item.subq,
      title: item.title,
    }));
  return {
    outlineEstablished: true,
    subquestions: projection.subquestions,
    members,
    assignments,
    cards,
    sourceMembers: new Map(),
  };
};

const steerContext = (
  input: TopicRunInput,
  state: TopicState,
  mode: "create" | "refresh" | "repair",
  diagnostics: WorkflowContext[] = [],
): WorkflowContext => ({
  materialKey: `topic:${input.query.slug}`,
  researchKey: `topic:${input.query.slug}`,
  query: input.query.description,
  topic: input.query.description,
  memberRefs: state.members,
  memberAssignments: state.assignments,
  cardRefs: state.cards,
  subquestions: state.subquestions,
  mode,
  diagnostics,
  maxCards: input.options.maxCardsPerRound,
});

const updateSubquestions = (state: TopicState, receipt: StageReceipt): void => {
  state.outlineEstablished = true;
  state.subquestions = (receipt.subquestions as WorkflowContext[]).map((item) => ({
    id: item.id as string,
    question: item.question as string,
    coverage: item.coverage as TopicSubquestionProjection["coverage"],
    channel: item.channel as TopicSubquestionProjection["channel"],
    theory_used: item.theory_used as number,
  }));
  const ids = new Set(state.subquestions.map((item) => item.id));
  const assignments: MemberAssignment[] = [];
  for (const subquestion of receipt.subquestions as WorkflowContext[]) {
    for (const item of subquestion.items as WorkflowContext[]) {
      const ref = state.members.find(
        (member) => member.kind === item.kind && member.slug === item.slug,
      );
      if (
        ref !== undefined &&
        ["evidence", "theory", "method", "context"].includes(item.role as string)
      ) assignments.push({
        member_key: memberKey(ref),
        subq: subquestion.id as string,
        role: item.role as TopicMemberRole,
      });
    }
  }
  state.assignments = assignments.filter((item) => ids.has(item.subq));
};

const seedFingerprint = (
  memberRoute: TopicChildRoute,
  leaf: TopicSeedLeaf,
): string =>
  canonicalFingerprint([
    "seed",
    memberRoute.kind,
    memberRoute.slug,
    leaf.seed,
    leaf.options,
  ]);

const demandFingerprint = (demand: TopicCandidateDemand): string =>
  canonicalFingerprint([
    demand.kind,
    demand.requested_slug,
    demand.query,
    demand.subq,
    demand.role,
    demand.reason,
  ]);

const taskFingerprint = (task: WorkflowContext): string =>
  canonicalFingerprint([
    task.card_slug,
    task.subq,
    task.query,
    task.note,
  ]);

const directTopicGate = (
  input: TopicRunInput,
  code: string,
  gate: WorkflowContext,
): MaterialResult => ({
  ...resultSeed(input),
  schema_version: "quasi.material.result/0.1",
  terminal: "needs_input",
  issue: planIssue(code, gate.operation as OperationName | null, gate.question as string),
  gate,
} as MaterialResult);

const seedGate = (
  input: TopicRunInput,
  seeds: Array<{ kind: "paper" | "book" | "talk"; slug: string; reason: string }>,
): MaterialResult =>
  directTopicGate(input, "topic.seed_required", {
    kind: "topic_seed",
    operation: null,
    question: "Provide usable exact Topic seeds before synthesis.",
    seeds,
  });

const needsSeedsGate = (
  input: TopicRunInput,
  receipt: StageReceipt,
): MaterialResult =>
  directTopicGate(input, "topic.needs_seeds", {
    kind: "topic_needs_seeds",
    operation: "topic.steer",
    question: "Add explicit Topic seeds or revise the outline before continuing.",
    suggested_queries: receipt.suggested_queries,
    uncovered_subquestions: (receipt.subquestions as WorkflowContext[])
      .filter((item) => ["gap", "thin"].includes(item.coverage as string))
      .map((item) => item.id),
  });

const hasSubquestion = (state: TopicState, id: string): boolean =>
  state.subquestions.some((item) => item.id === id);

const memberKey = (ref: Pick<MemberRef, "kind" | "slug">): string =>
  `${ref.kind}:${ref.slug}`;

const hasMember = (state: TopicState, ref: Pick<MemberRef, "kind" | "slug">): boolean =>
  state.members.some((item) => item.kind === ref.kind && item.slug === ref.slug);

const hasAssignment = (
  state: TopicState,
  ref: Pick<MemberRef, "kind" | "slug">,
  assignment: { subq: string; role: TopicMemberRole },
): boolean =>
  state.assignments.some(
    (item) =>
      item.member_key === memberKey(ref) &&
      item.subq === assignment.subq &&
      item.role === assignment.role,
  );

const addMember = (
  state: TopicState,
  ref: MemberRef,
  assignment: { subq: string; role: TopicMemberRole } | null,
): void => {
  if (!hasMember(state, ref)) state.members.push(ref);
  if (assignment !== null && !hasAssignment(state, ref, assignment))
    state.assignments.push({
      member_key: memberKey(ref),
      subq: assignment.subq,
      role: assignment.role,
    });
};

const hasCard = (
  state: TopicState,
  ref: Pick<CardRef, "slug" | "subq">,
): boolean =>
  state.cards.some((item) => item.slug === ref.slug && item.subq === ref.subq);

const addCard = (state: TopicState, ref: CardRef): void => {
  if (!hasCard(state, ref)) state.cards.push(ref);
};

const hasEvidence = (state: TopicState): boolean =>
  state.members.length > 0 || state.cards.length > 0;

const childObservation = (
  input: TopicRunInput,
  route: TopicChildRoute,
) => input.childObservations.get(observationKey(route)) ?? null;

const canonicalChildArtifact = (
  route: TopicChildRoute,
  observation: PaperStatusObservation | BookStatusObservation | TalkStatusObservation,
) => {
  if (route.kind === "paper")
    return (observation as PaperStatusObservation).facts.canonical;
  if (route.kind === "book")
    return (observation as BookStatusObservation).facts.overview;
  return (observation as TalkStatusObservation).facts.canonical;
};

const checkpointProved = (
  input: TopicRunInput,
  checkpoint: TopicCheckpointAdmission,
): boolean => {
  const projection = input.observation.facts.outline.projection;
  if (projection === null) return false;
  if (checkpoint.item === "member")
    return projection.members.some(
      (item) =>
        item.kind === checkpoint.ref.kind &&
        item.slug === checkpoint.ref.slug &&
        item.artifact.path === checkpoint.ref.path &&
        item.artifact.usable &&
        (checkpoint.assignment === null ||
          (item.subq === checkpoint.assignment.subq &&
            item.role === checkpoint.assignment.role)),
    );
  return projection.cards.some(
    (item) =>
      item.slug === checkpoint.ref.slug &&
      item.subq === checkpoint.assignment.subq &&
      item.artifact.path === checkpoint.ref.path &&
      item.artifact.usable,
  );
};

interface CheckpointOutcome {
  result: MaterialResult | null;
  receipt: StageReceipt | null;
}

const runCheckpoint = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  checkpoint: TopicCheckpointAdmission,
): Promise<CheckpointOutcome> => {
  if (checkpoint.item === "member")
    state.sourceMembers.set(observationKey(checkpoint.source_route), checkpoint.ref);
  if (checkpoint.item === "member")
    addMember(state, checkpoint.ref, checkpoint.assignment);
  else
    addCard(state, {
      ...checkpoint.ref,
      subq: checkpoint.assignment.subq,
    });
  const outcome = await dispatch(
    runtime,
    "topic.steer",
    input.query.slug,
    steerContext(
      input,
      state,
      state.outlineEstablished ? "refresh" : "create",
    ),
  );
  if (outcome.kind === "unknown_outcome" || outcome.kind === "incoherent_complete")
    return {
      result: needsObservationMaterialResult(
        resultSeed(input),
        [{ kind: "topic", slug: input.query.slug }],
        checkpoint,
      ),
      receipt: null,
    };
  const stop = stopForOutcome(input, outcome);
  if (stop !== null) return { result: stop, receipt: null };
  const receipt = (outcome as { kind: "receipt"; receipt: StageReceipt }).receipt;
  updateSubquestions(state, receipt);
  return { result: null, receipt };
};

const checkpointMember = (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  sourceRoute: TopicChildRoute,
  ref: MemberRef,
  assignment: { subq: string; role: TopicMemberRole } | null,
): Promise<CheckpointOutcome> =>
  runCheckpoint(runtime, input, state, {
    kind: "checkpoint_admission",
    topic: input.query,
    item: "member",
    source_route: sourceRoute,
    ref,
    assignment,
  });

const checkpointCard = (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  ref: CardRef,
): Promise<CheckpointOutcome> =>
  runCheckpoint(runtime, input, state, {
    kind: "checkpoint_admission",
    topic: input.query,
    item: "card",
    ref: { slug: ref.slug, path: ref.path, title: ref.title },
    assignment: { subq: ref.subq },
  });

const updatedLeafContinuation = (
  continuation: TopicSeedChildContinuation | TopicWorkContinuation,
  leaf: TopicSeedLeaf,
): TopicSeedChildContinuation | TopicWorkContinuation => {
  if (continuation.kind === "material_work")
    return { ...continuation, leaf: leaf as TopicWorkContinuation["leaf"] };
  return {
    ...continuation,
    leaf,
    fingerprint: seedFingerprint(continuation.member_route, leaf),
  };
};

const runLeaf = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  leaf: TopicSeedLeaf,
  userDecision: UserDecision | null,
): Promise<{ result: MaterialResult; leaf: TopicSeedLeaf }> => {
  const observation = childObservation(input, leaf.route);
  if (observation === null)
    throw new Error("Topic attempted a leaf without its exact observation");
  if (leaf.route.kind === "paper") {
    const parsed = parsePaperRunInput({
      seed: leaf.seed,
      observation,
      options: leaf.options,
      ...(userDecision === null ? {} : { userDecision }),
    });
    if (!parsed.ok) return { result: parsed.result, leaf };
    const outcome = await runPaperPlanForComposition(runtime, parsed.value);
    return { result: outcome.result, leaf: outcome.continuation };
  }
  if (leaf.route.kind === "book") {
    const parsed = parseBookRunInput({
      seed: leaf.seed,
      observation,
      options: leaf.options,
      ...(userDecision === null ? {} : { userDecision }),
    });
    if (!parsed.ok) return { result: parsed.result, leaf };
    const outcome = await runBookPlanForComposition(runtime, parsed.value);
    return { result: outcome.result, leaf: outcome.continuation };
  }
  const parsed = parseTalkRunInput({
    seed: leaf.seed,
    observation,
    options: leaf.options,
  });
  if (!parsed.ok) return { result: parsed.result, leaf };
  return { result: await runTalkPlan(runtime, parsed.value), leaf };
};

const representativeRef = (
  result: Extract<MaterialResult, { terminal: "complete" }>,
): MemberRef | null => {
  const canonical = result.material.canonical;
  if (canonical === null || !["paper", "book", "talk"].includes(canonical.kind))
    return null;
  const path = topicMemberPath(
    canonical.kind as MemberRef["kind"],
    canonical.slug,
  );
  const role = canonical.kind === "book" ? "overview" : "canonical";
  return result.next === null &&
    result.artifacts.some((item) => item.role === role && item.path === path)
    ? { kind: canonical.kind as MemberRef["kind"], slug: canonical.slug, path }
    : null;
};

interface LeafProcessingOutcome {
  result: MaterialResult | null;
  receipt: StageReceipt | null;
}

const processLeafContinuation = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  continuation: TopicSeedChildContinuation | TopicWorkContinuation,
  userDecision: UserDecision | null,
): Promise<LeafProcessingOutcome> => {
  if (
    continuation.kind === "material_work" &&
    (!hasSubquestion(state, continuation.assignment.subq) ||
      hasAssignment(state, {
        kind: continuation.leaf.route.kind,
        slug: continuation.leaf.route.slug,
      }, continuation.assignment))
  ) return { result: null, receipt: null };

  if (childObservation(input, continuation.leaf.route) === null)
    return {
      result: needsObservationMaterialResult(
        resultSeed(input),
        [continuation.leaf.route],
        continuation,
      ),
      receipt: null,
    };

  const outcome = await runLeaf(runtime, input, continuation.leaf, userDecision);
  let current = updatedLeafContinuation(continuation, outcome.leaf);
  const result = outcome.result;
  if (result.terminal === "needs_observation")
    return {
      result: needsObservationMaterialResult(
        resultSeed(input),
        [current.leaf.route],
        current,
      ),
      receipt: null,
    };
  if (result.terminal === "needs_input") {
    if (
      !("resume_seed" in result) ||
      !["identity_conflict", "book_year", "book_structure"].includes(result.gate.kind) ||
      !sameClosedValue(result.resume_seed, outcome.leaf)
    )
      return { result: blockedMaterialResult(
        resultSeed(input),
        planIssue("workflow.incoherent_gate", result.issue.operation, "A leaf returned a non-leaf gate."),
      ), receipt: null };
    return {
      result: higherOrderNeedsInputMaterialResult(
        resultSeed(input),
        result.issue,
        (current as TopicSeedChildContinuation | TopicWorkContinuation).leaf.route,
        result.gate as LeafGate,
        [(current as TopicSeedChildContinuation | TopicWorkContinuation).leaf.route],
        current,
      ),
      receipt: null,
    };
  }
  if (result.terminal === "blocked" || result.terminal === "failed")
    return {
      result: stoppedMaterialResult(
        resultSeed(input),
        result.terminal,
        result.issue,
      ),
      receipt: null,
    };
  if (result.terminal !== "complete")
    return {
      result: blockedMaterialResult(
        resultSeed(input),
        planIssue("workflow.incoherent_complete", null, "A leaf returned an unsupported Topic terminal."),
      ),
      receipt: null,
    };
  if (result.next !== null) {
    const bookLeaf: TopicSeedLeaf = {
      route: { kind: "book", slug: result.next.identity.slug },
      seed: {
        state: "canonical",
        material_slug: result.next.identity.slug,
        identity: result.next.identity,
      },
      options: {},
    };
    current = updatedLeafContinuation(continuation, bookLeaf);
    return processLeafContinuation(runtime, input, state, current, null);
  }
  const ref = representativeRef(result);
  if (ref === null)
    return {
      result: blockedMaterialResult(
        resultSeed(input),
        planIssue("workflow.incoherent_complete", null, "A leaf completion omitted its exact canonical Topic member."),
      ),
      receipt: null,
    };
  const assignment = continuation.kind === "material_work"
    ? continuation.assignment
    : null;
  const checkpoint = await checkpointMember(
    runtime,
    input,
    state,
    continuation.member_route,
    ref,
    assignment,
  );
  return {
    result: checkpoint.result,
    receipt: checkpoint.receipt,
  };
};

const seedContinuation = (
  input: TopicRunInput,
  seed: TopicRunInput["seedMaterials"][number],
): TopicSeedChildContinuation => {
  const route: TopicChildRoute = seed.kind === "paper"
    ? {
        kind: "paper",
        slug: seed.seed.state === "provisional"
          ? seed.seed.requested_slug
          : seed.seed.material_slug,
      }
    : seed.kind === "book"
      ? {
          kind: "book",
          slug: seed.seed.state === "provisional"
            ? seed.seed.requested_slug
            : seed.seed.material_slug,
        }
      : { kind: "talk", slug: seed.seed.material_slug };
  const leaf = { route, seed: seed.seed, options: seed.options } as TopicSeedLeaf;
  return {
    kind: "seed_child",
    topic: input.query,
    fingerprint: seedFingerprint(route, leaf),
    member_route: route,
    leaf,
  };
};

const completeSeedRef = (
  continuation: TopicSeedChildContinuation,
  observation: PaperStatusObservation | BookStatusObservation | TalkStatusObservation,
): MemberRef | null => {
  const { leaf } = continuation;
  if (leaf.seed.state !== "canonical") return null;
  const artifact = canonicalChildArtifact(leaf.route, observation);
  if (!artifact.usable) return null;
  if (
    leaf.route.kind === "paper" &&
    !paperObservationAdmitsIdentity(
      observation as PaperStatusObservation,
      leaf.seed.identity as PaperIdentity,
    )
  ) return null;
  if (
    leaf.route.kind === "book" &&
    !bookObservationAdmitsIdentity(
      observation as BookStatusObservation,
      leaf.seed.identity as BookIdentity,
    )
  ) return null;
  return { kind: leaf.route.kind, slug: leaf.route.slug, path: artifact.path };
};

const processSeed = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  continuation: TopicSeedChildContinuation,
): Promise<LeafProcessingOutcome | { gate: { kind: "paper" | "book" | "talk"; slug: string; reason: string } }> => {
  if (
    continuation.leaf.seed.state === "provisional" &&
    input.options.maxRounds === 0
  ) return {
    gate: {
      kind: continuation.member_route.kind,
      slug: continuation.member_route.slug,
      reason: "The provisional seed requires material discovery outside a zero-round Topic run.",
    },
  };
  const observation = childObservation(input, continuation.leaf.route);
  if (observation === null)
    return {
      result: needsObservationMaterialResult(
        resultSeed(input),
        [continuation.leaf.route],
        continuation,
      ),
      receipt: null,
    };
  const complete = completeSeedRef(continuation, observation);
  if (complete !== null) {
    if (hasMember(state, complete))
      return { result: null, receipt: null };
    const checkpoint = await checkpointMember(
      runtime,
      input,
      state,
      continuation.member_route,
      complete,
      null,
    );
    return {
      result: checkpoint.result,
      receipt: checkpoint.receipt,
    };
  }
  if (
    continuation.leaf.route.kind === "talk" &&
    !(observation as TalkStatusObservation).facts.media.find(
      (item) => item.path === (
        continuation.leaf as Extract<TopicSeedLeaf, { route: { kind: "talk" } }>
      ).seed.identity.media,
    )?.usable
  ) return {
    gate: {
      kind: "talk",
      slug: continuation.member_route.slug,
      reason: "The exact Talk has neither a usable canonical product nor usable media.",
    },
  };
  return processLeafContinuation(runtime, input, state, continuation, null);
};

const recalledContinuation = (
  input: TopicRunInput,
  item: TopicRecallContinuation["item"],
): TopicRecallContinuation => ({
  kind: "recalled_member",
  topic: input.query,
  item,
  fingerprint: canonicalFingerprint(["recall", item.kind, item.slug, item.path]),
  route: { kind: item.kind, slug: item.slug },
});

const processRecalled = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
  continuation: TopicRecallContinuation,
): Promise<LeafProcessingOutcome> => {
  const observation = childObservation(input, continuation.route);
  if (observation === null)
    return {
      result: needsObservationMaterialResult(
        resultSeed(input),
        [continuation.route],
        continuation,
      ),
      receipt: null,
    };
  const artifact = canonicalChildArtifact(continuation.route, observation);
  if (!artifact.usable)
    return { result: null, receipt: null };
  const ref = {
    kind: continuation.route.kind,
    slug: continuation.route.slug,
    path: artifact.path,
  };
  if (hasMember(state, ref))
    return { result: null, receipt: null };
  const checkpoint = await checkpointMember(
    runtime,
    input,
    state,
    continuation.route,
    ref,
    null,
  );
  return {
    result: checkpoint.result,
    receipt: checkpoint.receipt,
  };
};

type WorkItem =
  | { kind: "material"; demand: TopicCandidateDemand; fingerprint: string }
  | { kind: "webcard"; task: WorkflowContext; fingerprint: string };

const currentCoverage = (state: TopicState, subq: string): string | null =>
  state.subquestions.find((item) => item.id === subq)?.coverage ?? null;

const applicableWork = (
  state: TopicState,
  receipt: StageReceipt,
  seen: ReadonlySet<string>,
): WorkItem[] => {
  const rows: WorkItem[] = [];
  const materialTargets = new Set<string>();
  const webRows = new Set<string>();
  for (const demand of receipt.candidate_demands as TopicCandidateDemand[]) {
    const fingerprint = demandFingerprint(demand);
    const target = `${demand.kind}:${demand.requested_slug}`;
    if (materialTargets.has(target)) continue;
    materialTargets.add(target);
    const coverage = currentCoverage(state, demand.subq);
    const resolved = state.sourceMembers.get(observationKey({
      kind: demand.kind,
      slug: demand.requested_slug,
    })) ?? { kind: demand.kind, slug: demand.requested_slug };
    if (
      seen.has(fingerprint) ||
      !["gap", "thin"].includes(coverage ?? "") ||
      hasAssignment(state, resolved, demand)
    ) continue;
    rows.push({ kind: "material", demand, fingerprint });
  }
  for (const task of receipt.web_tasks as WorkflowContext[]) {
    const row = canonicalFingerprint([
      task.card_slug,
      task.subq,
      task.query,
      task.note,
    ]);
    if (webRows.has(row)) continue;
    webRows.add(row);
    const fingerprint = taskFingerprint(task);
    const coverage = currentCoverage(state, task.subq as string);
    if (
      seen.has(fingerprint) ||
      !["gap", "thin"].includes(coverage ?? "") ||
      hasCard(state, {
        slug: task.card_slug as string,
        subq: task.subq as string,
      })
    ) continue;
    rows.push({ kind: "webcard", task, fingerprint });
  }
  return rows;
};

const pendingRows = (work: WorkItem[]): TopicPendingWork[] =>
  work.map((item) =>
    item.kind === "material"
      ? {
          kind: "material",
          material_kind: item.demand.kind,
          requested_slug: item.demand.requested_slug,
          subq: item.demand.subq,
          role: item.demand.role,
          fingerprint: item.fingerprint,
        }
      : {
          kind: "webcard",
          card_slug: item.task.card_slug as string,
          subq: item.task.subq as string,
          fingerprint: item.fingerprint,
        },
  );

const artifacts = (slug: string): ExactArtifactRef[] => [
  { role: "outline", path: `vault/topics/${slug}/02-outline.md` },
  { role: "overview", path: `vault/topics/${slug}/00-overview.md` },
  { role: "resources", path: `vault/topics/${slug}/01-resources.md` },
];

const auditProduct = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  target: string,
  repair: (diagnostics: WorkflowContext[]) => Promise<MaterialResult | null>,
): Promise<MaterialResult | null> => {
  const first = await dispatch(runtime, "topic.audit", input.query.slug, {
    materialKey: `topic:${input.query.slug}`,
    target,
    pass: 1,
  });
  const firstStop = stopForOutcome(input, first);
  if (firstStop !== null) return firstStop;
  const firstReceipt = first.receipt as StageReceipt;
  if (firstReceipt.remaining_violations === 0) return null;
  const repaired = await repair(firstReceipt.escalated as WorkflowContext[]);
  if (repaired !== null) return repaired;
  const second = await dispatch(runtime, "topic.audit", input.query.slug, {
    materialKey: `topic:${input.query.slug}`,
    target,
    pass: 2,
  });
  const secondStop = stopForOutcome(input, second);
  if (secondStop !== null) return secondStop;
  if ((second.receipt as StageReceipt).remaining_violations === 0) return null;
  return blockedMaterialResult(
    resultSeed(input),
    planIssue(
      "workflow.repair_exhausted",
      "topic.audit",
      "The bounded Topic repair completed, but the second audit still found violations.",
    ),
  );
};

const synthesisContext = (
  input: TopicRunInput,
  state: TopicState,
  mode: "create" | "refresh" | "repair",
  diagnostics: WorkflowContext[] = [],
): WorkflowContext => ({
  materialKey: `topic:${input.query.slug}`,
  researchKey: `topic:${input.query.slug}`,
  topic: input.query.description,
  memberRefs: state.members,
  cardRefs: state.cards,
  mode,
  diagnostics,
});

const finalise = async (
  runtime: MaterialRuntime,
  input: TopicRunInput,
  state: TopicState,
): Promise<MaterialResult> => {
  const [outline, overview, resources] = artifacts(input.query.slug);
  const outlineStop = await auditProduct(
    runtime,
    input,
    outline.path,
    async (diagnostics) => {
      const repaired = await dispatch(
        runtime,
        "topic.steer",
        input.query.slug,
        steerContext(input, state, "repair", diagnostics),
      );
      const stop = stopForOutcome(input, repaired);
      if (stop !== null) return stop;
      updateSubquestions(state, repaired.receipt as StageReceipt);
      return null;
    },
  );
  if (outlineStop !== null) return outlineStop;

  const overviewWrite = await dispatch(
    runtime,
    "topic.synthesise.overview",
    input.query.slug,
    synthesisContext(
      input,
      state,
      input.observation.facts.overview.present ? "refresh" : "create",
    ),
  );
  const overviewWriteStop = stopForOutcome(input, overviewWrite);
  if (overviewWriteStop !== null) return overviewWriteStop;
  const resourcesWrite = await dispatch(
    runtime,
    "topic.synthesise.resources",
    input.query.slug,
    synthesisContext(
      input,
      state,
      input.observation.facts.resources.present ? "refresh" : "create",
    ),
  );
  const resourcesWriteStop = stopForOutcome(input, resourcesWrite);
  if (resourcesWriteStop !== null) return resourcesWriteStop;

  const overviewStop = await auditProduct(
    runtime,
    input,
    overview.path,
    async (diagnostics) => {
      const repaired = await dispatch(
        runtime,
        "topic.synthesise.overview",
        input.query.slug,
        synthesisContext(input, state, "repair", diagnostics),
      );
      return stopForOutcome(input, repaired);
    },
  );
  if (overviewStop !== null) return overviewStop;
  const resourcesStop = await auditProduct(
    runtime,
    input,
    resources.path,
    async (diagnostics) => {
      const repaired = await dispatch(
        runtime,
        "topic.synthesise.resources",
        input.query.slug,
        synthesisContext(input, state, "repair", diagnostics),
      );
      return stopForOutcome(input, repaired);
    },
  );
  if (resourcesStop !== null) return resourcesStop;
  return completeMaterialResult(resultSeed(input), [outline, overview, resources], null);
};

export async function runTopicPlan(
  runtime: MaterialRuntime,
  input: TopicRunInput,
): Promise<MaterialResult> {
  const state = initialState(input);
  const recalled = await dispatch(runtime, "topic.recall", input.query.slug, {
    materialKey: `topic:${input.query.slug}`,
    researchKey: `topic:${input.query.slug}`,
    query: input.query.description,
    maxItems: 8,
    subquestions: state.subquestions,
  });
  const recallStop = stopForOutcome(input, recalled);
  if (recallStop !== null) return recallStop;
  const recallReceipt = (recalled as { kind: "receipt"; receipt: StageReceipt }).receipt;
  let closing: StageReceipt | null = null;
  const handledIntakeRoutes = new Set<string>();
  const resumedWorkFingerprints = new Set<string>();

  const resumeSeed = input.resume?.resume_seed ?? null;
  if (resumeSeed !== null) {
    if (resumeSeed.kind === "checkpoint_admission") {
      const proved = checkpointProved(input, resumeSeed);
      if (resumeSeed.item === "member") {
        handledIntakeRoutes.add(observationKey(resumeSeed.source_route));
        if (proved)
          state.sourceMembers.set(
            observationKey(resumeSeed.source_route),
            resumeSeed.ref,
          );
      }
      if (!proved) {
        const checkpoint = await runCheckpoint(runtime, input, state, resumeSeed);
        if (checkpoint.result !== null) return checkpoint.result;
        closing = checkpoint.receipt;
      }
    } else if (resumeSeed.kind === "recalled_member") {
      handledIntakeRoutes.add(observationKey(resumeSeed.route));
      const resumed = await processRecalled(runtime, input, state, resumeSeed);
      if (resumed.result !== null) return resumed.result;
      closing = resumed.receipt;
    } else {
      const routeKey = observationKey(resumeSeed.member_route);
      if (resumeSeed.kind === "seed_child")
        handledIntakeRoutes.add(routeKey);
      if (resumeSeed.kind === "material_work") {
        const effectiveRef = state.members.find(
          (ref) =>
            ref.kind === resumeSeed.leaf.route.kind &&
            ref.slug === resumeSeed.leaf.route.slug,
        );
        if (
          effectiveRef !== undefined &&
          hasAssignment(state, effectiveRef, resumeSeed.assignment)
        ) state.sourceMembers.set(routeKey, effectiveRef);
      }
      const resumed = await processLeafContinuation(
        runtime,
        input,
        state,
        resumeSeed,
        input.resume?.userDecision ?? null,
      );
      if (resumed.result !== null) return resumed.result;
      if (
        resumeSeed.kind === "material_work" &&
        (resumed.receipt !== null || state.sourceMembers.has(routeKey) ||
          hasAssignment(state, resumeSeed.member_route, resumeSeed.assignment))
      ) {
        handledIntakeRoutes.add(routeKey);
        resumedWorkFingerprints.add(resumeSeed.fingerprint);
      }
      closing = resumed.receipt;
    }
  }

  const gatedSeeds: Array<{
    kind: "paper" | "book" | "talk";
    slug: string;
    reason: string;
  }> = [];
  for (const seed of input.seedMaterials) {
    const continuation = seedContinuation(input, seed);
    const routeKey = observationKey(continuation.member_route);
    if (handledIntakeRoutes.has(routeKey)) continue;
    handledIntakeRoutes.add(routeKey);
    const processed = await processSeed(runtime, input, state, continuation);
    if ("gate" in processed) {
      gatedSeeds.push(processed.gate);
      continue;
    }
    if (processed.result !== null) return processed.result;
    if (processed.receipt !== null) closing = processed.receipt;
  }
  if (gatedSeeds.length > 0) return seedGate(input, gatedSeeds);

  for (const item of recallReceipt.items as TopicRecallContinuation["item"][]) {
    const continuation = recalledContinuation(input, item);
    const routeKey = observationKey(continuation.route);
    if (handledIntakeRoutes.has(routeKey)) continue;
    handledIntakeRoutes.add(routeKey);
    const processed = await processRecalled(runtime, input, state, continuation);
    if (processed.result !== null) return processed.result;
    if (processed.receipt !== null) closing = processed.receipt;
  }

  if (closing === null) {
    const steered = await dispatch(
      runtime,
      "topic.steer",
      input.query.slug,
      steerContext(
        input,
        state,
        state.outlineEstablished ? "refresh" : "create",
      ),
    );
    const steerStop = stopForOutcome(input, steered);
    if (steerStop !== null) return steerStop;
    closing = (steered as { kind: "receipt"; receipt: StageReceipt }).receipt;
    updateSubquestions(state, closing);
  }

  if (closing.signal === "needs_seeds")
    return hasEvidence(state)
      ? needsSeedsGate(input, closing)
      : seedGate(input, []);

  const seen = new Set<string>(resumedWorkFingerprints);
  let rounds = 0;
  let pending: WorkItem[] = [];
  let stopSignal = closing.signal === "saturated";

  while (!stopSignal) {
    const work = applicableWork(state, closing, seen);
    if (work.length === 0) break;
    if (rounds >= input.options.maxRounds) {
      pending = work;
      break;
    }
    rounds += 1;
    for (const item of work) {
      const subq = item.kind === "material"
        ? item.demand.subq
        : item.task.subq as string;
      const satisfied = item.kind === "material"
        ? hasAssignment(
            state,
            state.sourceMembers.get(observationKey({
              kind: item.demand.kind,
              slug: item.demand.requested_slug,
            })) ?? { kind: item.demand.kind, slug: item.demand.requested_slug },
            item.demand,
          )
        : hasCard(state, {
            slug: item.task.card_slug as string,
            subq,
          });
      if (
        seen.has(item.fingerprint) || satisfied ||
        !["gap", "thin"].includes(currentCoverage(state, subq) ?? "")
      )
        continue;
      seen.add(item.fingerprint);
      let checkpoint: CheckpointOutcome | null = null;
      if (item.kind === "material") {
        const sourceRoute: TopicChildRoute = {
          kind: item.demand.kind,
          slug: item.demand.requested_slug,
        };
        const existing = state.sourceMembers.get(observationKey(sourceRoute)) ?? state.members.find(
          (ref) => ref.kind === item.demand.kind && ref.slug === item.demand.requested_slug,
        );
        if (existing !== undefined) {
          checkpoint = await checkpointMember(
            runtime,
            input,
            state,
            sourceRoute,
            existing,
            { subq: item.demand.subq, role: item.demand.role },
          );
        } else {
          const route: TopicChildRoute = {
            kind: item.demand.kind,
            slug: item.demand.requested_slug,
          };
          const leaf = {
            route,
            seed: {
              state: "provisional",
              requested_slug: item.demand.requested_slug,
              hints: { title: item.demand.query },
            },
            options: {},
          } as TopicWorkContinuation["leaf"];
          const continuation: TopicWorkContinuation = {
            kind: "material_work",
            topic: input.query,
            demand: item.demand,
            assignment: { subq: item.demand.subq, role: item.demand.role },
            fingerprint: item.fingerprint,
            member_route: route,
            leaf,
          };
          const processed = await processLeafContinuation(
            runtime,
            input,
            state,
            continuation,
            null,
          );
          if (processed.result !== null) return processed.result;
          checkpoint = { result: null, receipt: processed.receipt };
        }
      } else {
        const existing = state.cards.find(
          (ref) => ref.slug === item.task.card_slug,
        );
        if (existing !== undefined) {
          checkpoint = await checkpointCard(
            runtime,
            input,
            state,
            { ...existing, subq: item.task.subq as string },
          );
        } else {
          const web = await dispatch(runtime, "topic.webcard", input.query.slug, {
            materialKey: `topic:${input.query.slug}`,
            topic: input.query.description,
            task: item.task,
            cardRefs: state.cards,
            subquestions: state.subquestions,
          });
          const webStop = stopForOutcome(input, web);
          if (webStop !== null) return webStop;
          const receipt = (web as { kind: "receipt"; receipt: StageReceipt }).receipt;
          if (receipt.card_status === "empty") continue;
          const ref: CardRef = {
            slug: item.task.card_slug as string,
            path: receipt.card_path as string,
            subq: item.task.subq as string,
            title: receipt.title as string | null,
          };
          checkpoint = await checkpointCard(
            runtime,
            input,
            state,
            ref,
          );
        }
      }
      if (checkpoint.result !== null) return checkpoint.result;
      if (checkpoint.receipt !== null) {
        closing = checkpoint.receipt;
        if (closing.signal === "needs_seeds" || closing.signal === "saturated") {
          stopSignal = true;
          break;
        }
      }
    }
  }

  if (closing.signal === "needs_seeds")
    return hasEvidence(state)
      ? needsSeedsGate(input, closing)
      : seedGate(input, []);
  if (!hasEvidence(state)) return seedGate(input, []);

  const final = await finalise(runtime, input, state);
  if (final.terminal !== "complete" || pending.length === 0) return final;
  return incompleteTopicMaterialResult(
    resultSeed(input),
    {
      ...planIssue(
        "topic.round_limit",
        null,
        "The bounded Topic run ended with ordered applicable work still pending.",
      ),
      code: "topic.round_limit",
    },
    final.artifacts,
    pendingRows(pending),
  );
}
