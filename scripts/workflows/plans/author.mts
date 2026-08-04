import {
  childRunInput,
  type AuthorLeafContinuation,
  type AuthorMemberSeed,
  type AuthorResumeSeed,
  type AuthorRunInput,
  type AuthorSeed,
  type ChildRoute,
} from "../contracts/author.mts";
import { observationKey } from "../shared/material-input.mts";
import {
  parseBookIdentity,
  type BookRunInput,
} from "../contracts/book.mts";
import {
  parsePaperIdentity,
  type PaperRunInput,
} from "../contracts/paper.mts";
import { prepareOperation } from "../operations/catalogs/author.mts";
import { runBookPlanForComposition } from "./book.mts";
import { runPaperPlanForComposition } from "./paper.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  completeMaterialResult,
  higherOrderNeedsInputMaterialResult,
  needsObservationMaterialResult,
  stoppedMaterialResult,
  type ExactArtifactRef,
  type LeafCompositionOutcome,
  type LeafGate,
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

interface CompletedChild {
  material_key: string;
  kind: "paper" | "book";
  id: string;
  path: string;
  title: string;
}

const resultSeed = (seed: AuthorSeed): MaterialResultSeed => ({
  material: {
    requested: { kind: "author", slug: seed.slug },
    canonical: { kind: "author", slug: seed.slug },
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
  seed: AuthorSeed,
  outcome: DispatchOutcome,
): MaterialResult | null => {
  if (outcome.kind !== "receipt")
    return blockedMaterialResult(resultSeed(seed), outcome.issue);
  if (outcome.receipt.terminal.status === "complete") return null;
  if (outcome.receipt.terminal.status === "needs_input")
    return blockedMaterialResult(
      resultSeed(seed),
      planIssue(
        "workflow.incoherent_gate",
        outcome.receipt.operation,
        "An Author specialist returned a gate outside its typed boundary.",
      ),
    );
  return stoppedMaterialResult(
    resultSeed(seed),
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

const uniqueRoutes = (
  members: readonly AuthorMemberSeed[],
): ChildRoute[] => {
  const seen = new Set<string>();
  const routes: ChildRoute[] = [];
  for (const member of members) {
    const route = member.leaf.route;
    const key = observationKey(route);
    if (seen.has(key)) continue;
    seen.add(key);
    routes.push(route);
  }
  return routes;
};

const resumeSeed = (
  seed: AuthorSeed,
  options: AuthorResumeSeed["options"],
  members: AuthorMemberSeed[],
  decisionMember: ChildRoute | null,
): AuthorResumeSeed => ({
  kind: "author",
  seed,
  options,
  members,
  decision_member: decisionMember,
});

const discoverAuthor = async (
  runtime: MaterialRuntime,
  input: Extract<AuthorRunInput, { mode: "discover" }>,
): Promise<MaterialResult> => {
  const materialKey = `author:${input.seed.slug}`;
  const common = {
    materialKey,
    fullName: input.seed.full_name,
    topic: input.seed.topic,
  };
  const books = await dispatch(
    runtime,
    "author.discover-books",
    input.seed.slug,
    {
      ...common,
      count: input.options.maxBooks ?? 5,
    },
  );
  const bookStop = stopForOutcome(input.seed, books);
  if (bookStop !== null) return bookStop;

  const papers = await dispatch(
    runtime,
    "author.discover-papers",
    input.seed.slug,
    {
      ...common,
      count: input.options.maxPapers ?? 10,
    },
  );
  const paperStop = stopForOutcome(input.seed, papers);
  if (paperStop !== null) return paperStop;

  const candidates = [
    ...((books.receipt as StageReceipt).candidates as WorkflowContext[]),
    ...((papers.receipt as StageReceipt).candidates as WorkflowContext[]),
  ];
  const resolved = await dispatch(
    runtime,
    "author.resolve-membership",
    input.seed.slug,
    { ...common, candidates },
  );
  const resolveStop = stopForOutcome(input.seed, resolved);
  if (resolveStop !== null) return resolveStop;

  const rows = (resolved.receipt as StageReceipt)
    .resolved as WorkflowContext[];
  const members: AuthorMemberSeed[] = [];
  const seen = new Set<string>();
  for (const [index, candidate] of candidates.entries()) {
    const row = rows[index]!;
    const kind = candidate.kind as "book" | "paper";
    const { kind: _transportKind, ...identityValue } = candidate;
    const identity =
      kind === "book"
        ? parseBookIdentity(identityValue)
        : parsePaperIdentity(identityValue);
    if (identity === null)
      return blockedMaterialResult(
        resultSeed(input.seed),
        planIssue(
          "workflow.incoherent_complete",
          "author.resolve-membership",
          "Author discovery returned an invalid material identity.",
        ),
      );
    const route: ChildRoute = {
      kind,
      slug: (row.vault_slug ?? row.requested_slug) as string,
    };
    const key = observationKey(route);
    if (seen.has(key)) continue;
    seen.add(key);
    members.push({
      member_route: route,
      leaf: {
        route,
        seed: {
          state: "canonical",
          material_slug: route.slug,
          identity,
        },
        options: {},
      } as AuthorLeafContinuation,
    });
  }
  if (members.length === 0)
    return blockedMaterialResult(
      resultSeed(input.seed),
      planIssue(
        "author.no_representative_works",
        "author.resolve-membership",
        "No representative works were found for this Author.",
      ),
    );
  const continuation = resumeSeed(
    input.seed,
    input.options,
    members,
    null,
  );
  return needsObservationMaterialResult(
    resultSeed(input.seed),
    uniqueRoutes(members),
    continuation,
  );
};

const coherentContinuation = (
  continuation: AuthorLeafContinuation,
  kind: "paper" | "book",
): boolean =>
  continuation.route.kind === kind &&
  continuation.seed.state === "canonical" &&
  continuation.seed.material_slug === continuation.route.slug;

const representativeArtifact = (
  result: Extract<MaterialResult, { terminal: "complete" }>,
  continuation: AuthorLeafContinuation,
): ExactArtifactRef | null => {
  const canonical = result.material.canonical;
  if (
    canonical === null ||
    canonical.kind !== continuation.route.kind ||
    canonical.slug !== continuation.route.slug
  )
    return null;
  const role = canonical.kind === "paper" ? "canonical" : "overview";
  const path =
    canonical.kind === "paper"
      ? `vault/papers/${canonical.slug}.md`
      : `vault/books/${canonical.slug}/00-overview.md`;
  const matches = result.artifacts.filter(
    (artifact) => artifact.role === role && artifact.path === path,
  );
  return matches.length === 1 ? matches[0]! : null;
};

const stoppedChild = (
  seed: AuthorSeed,
  result: Extract<
    MaterialResult,
    { terminal: "blocked" | "failed" }
  >,
): MaterialResult =>
  stoppedMaterialResult(
    resultSeed(seed),
    result.terminal,
    result.issue,
  );

const runChild = async (
  runtime: MaterialRuntime,
  input: Extract<AuthorRunInput, { mode: "compose" }>,
  member: AuthorMemberSeed,
  decision: Extract<
    AuthorRunInput,
    { mode: "compose" }
  >["userDecision"],
): Promise<LeafCompositionOutcome> =>
  member.leaf.route.kind === "paper"
    ? runPaperPlanForComposition(
        runtime,
        childRunInput(input, member, decision) as PaperRunInput,
      )
    : runBookPlanForComposition(
        runtime,
        childRunInput(input, member, decision) as BookRunInput,
      );

const composeChildren = async (
  runtime: MaterialRuntime,
  input: Extract<AuthorRunInput, { mode: "compose" }>,
): Promise<MaterialResult | CompletedChild[]> => {
  const members = input.resumeSeed.members.map((member) => ({
    member_route: member.member_route,
    leaf: member.leaf,
  }));
  let decisionMember = input.resumeSeed.decision_member;
  const completed = new Map<string, CompletedChild>();

  for (let index = 0; index < members.length; index += 1) {
    const member = members[index]!;
    while (true) {
      if (completed.has(observationKey(member.leaf.route))) break;
      const getsDecision =
        decisionMember !== null &&
        sameClosedValue(member.member_route, decisionMember);
      const outcome = await runChild(
        runtime,
        input,
        member,
        getsDecision ? input.userDecision : null,
      );
      if (getsDecision) decisionMember = null;
      if (
        !coherentContinuation(
          outcome.continuation as AuthorLeafContinuation,
          member.leaf.route.kind,
        )
      )
        return blockedMaterialResult(
          resultSeed(input.resumeSeed.seed),
          planIssue(
            "workflow.incoherent_complete",
            null,
            "A child Workflow returned an incoherent continuation.",
          ),
        );
      member.leaf = outcome.continuation as AuthorLeafContinuation;
      const result = outcome.result;

      if (result.terminal === "needs_input") {
        if (
          !("resume_seed" in result) ||
          !sameClosedValue(result.resume_seed, member.leaf) ||
          ![
            "identity_conflict",
            "book_year",
            "book_structure",
          ].includes(result.gate.kind)
        )
          return blockedMaterialResult(
            resultSeed(input.resumeSeed.seed),
            planIssue(
              "workflow.incoherent_gate",
              result.issue.operation,
              "A child gate did not bind its effective continuation.",
            ),
          );
        const continuation = resumeSeed(
          input.resumeSeed.seed,
          input.resumeSeed.options,
          members,
          member.member_route,
        );
        return higherOrderNeedsInputMaterialResult(
          resultSeed(input.resumeSeed.seed),
          result.issue,
          member.leaf.route,
          result.gate as LeafGate,
          uniqueRoutes(members),
          continuation,
        );
      }
      if (result.terminal === "blocked" || result.terminal === "failed")
        return stoppedChild(input.resumeSeed.seed, result);
      if (result.terminal !== "complete")
        return blockedMaterialResult(
          resultSeed(input.resumeSeed.seed),
          planIssue(
            "workflow.incoherent_complete",
            null,
            "A leaf Workflow returned a terminal unavailable to Author.",
          ),
        );

      if (result.next?.kind === "book") {
        const route: ChildRoute = {
          kind: "book",
          slug: result.next.identity.slug,
        };
        member.leaf = {
          route,
          seed: {
            state: "canonical",
            material_slug: route.slug,
            identity: result.next.identity,
          },
          options: {},
        };
        if (!input.childObservations.has(observationKey(route))) {
          const continuation = resumeSeed(
            input.resumeSeed.seed,
            input.resumeSeed.options,
            members,
            decisionMember,
          );
          return needsObservationMaterialResult(
            resultSeed(input.resumeSeed.seed),
            uniqueRoutes(members),
            continuation,
          );
        }
        continue;
      }

      const artifact = representativeArtifact(result, member.leaf);
      if (artifact === null || member.leaf.seed.state !== "canonical")
        return blockedMaterialResult(
          resultSeed(input.resumeSeed.seed),
          planIssue(
            "workflow.incoherent_complete",
            null,
            "A completed child did not prove its exact representative artifact.",
          ),
        );
      const key = observationKey(member.leaf.route);
      if (!completed.has(key))
        completed.set(key, {
          material_key: key,
          kind: member.leaf.route.kind,
          id: member.leaf.route.slug,
          path: artifact.path,
          title: member.leaf.seed.identity.title,
        });
      break;
    }
  }
  return [...completed.values()];
};

const completeAuthor = (seed: AuthorSeed): MaterialResult =>
  completeMaterialResult(
    resultSeed(seed),
    [
      {
        role: "canonical",
        path: `vault/authors/${seed.slug}.md`,
      },
    ],
    null,
  );

const synthesiseAuthor = async (
  runtime: MaterialRuntime,
  input: Extract<AuthorRunInput, { mode: "compose" }>,
  children: CompletedChild[],
): Promise<MaterialResult> => {
  const seed = input.resumeSeed.seed;
  const common = {
    materialKey: `author:${seed.slug}`,
    fullName: seed.full_name,
    topic: seed.topic,
    inputs: children,
  };
  const firstSynthesis = await dispatch(
    runtime,
    "author.synthesise",
    seed.slug,
    {
      ...common,
      mode: input.observation.facts.canonical.present
        ? "repair"
        : "create",
    },
  );
  const synthesisStop = stopForOutcome(seed, firstSynthesis);
  if (synthesisStop !== null) return synthesisStop;

  const target = `vault/authors/${seed.slug}.md`;
  const firstAudit = await dispatch(runtime, "author.audit", seed.slug, {
    materialKey: common.materialKey,
    target,
    pass: 1,
  });
  const firstAuditStop = stopForOutcome(seed, firstAudit);
  if (firstAuditStop !== null) return firstAuditStop;
  const firstReceipt = firstAudit.receipt as StageReceipt;
  if (firstReceipt.remaining_violations === 0) return completeAuthor(seed);

  const repaired = await dispatch(
    runtime,
    "author.synthesise",
    seed.slug,
    {
      ...common,
      mode: "repair",
      diagnostics: firstReceipt.escalated,
    },
  );
  const repairStop = stopForOutcome(seed, repaired);
  if (repairStop !== null) return repairStop;

  const secondAudit = await dispatch(runtime, "author.audit", seed.slug, {
    materialKey: common.materialKey,
    target,
    pass: 2,
  });
  const secondAuditStop = stopForOutcome(seed, secondAudit);
  if (secondAuditStop !== null) return secondAuditStop;
  if ((secondAudit.receipt as StageReceipt).remaining_violations === 0)
    return completeAuthor(seed);
  return blockedMaterialResult(
    resultSeed(seed),
    planIssue(
      "workflow.repair_exhausted",
      "author.audit",
      "The bounded Author repair completed, but the second audit still found violations.",
    ),
  );
};

export async function runAuthorPlan(
  runtime: MaterialRuntime,
  input: AuthorRunInput,
): Promise<MaterialResult> {
  if (input.mode === "discover") return discoverAuthor(runtime, input);
  const children = await composeChildren(runtime, input);
  return Array.isArray(children)
    ? synthesiseAuthor(runtime, input, children)
    : children;
}
