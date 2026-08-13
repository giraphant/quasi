import type {
  WebpageIdentity,
  WebpageRunInput,
} from "../contracts/webpage.mts";
import { prepareOperation } from "../operations/catalogs/webpage.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  completeMaterialResult,
  needsObservationMaterialResult,
  stoppedMaterialResult,
  type LeafResumeSeed,
  type MaterialIssue,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type {
  OperationName,
  StageReceipt,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

const resultSeed = (canonicalSlug: string | null): MaterialResultSeed => ({
  material: {
    requested: { kind: "webpage", slug: null },
    canonical:
      canonicalSlug === null
        ? null
        : { kind: "webpage", slug: canonicalSlug },
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

const resumeSeed = (
  slug: string,
  identity: WebpageIdentity,
): Extract<LeafResumeSeed, { route: { kind: "webpage" } }> => ({
  route: { kind: "webpage", slug },
  seed: {
    state: "canonical",
    material_slug: slug,
    identity,
  },
  options: {},
});

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

const stopForOutcome = (
  slug: string | null,
  outcome: DispatchOutcome,
  ambiguityNeedsObservation: boolean,
  identity: WebpageIdentity | null,
): MaterialResult | null => {
  if (outcome.kind !== "receipt") {
    if (ambiguityNeedsObservation && slug !== null && identity !== null)
      return needsObservationMaterialResult(
        resultSeed(slug),
        [{ kind: "webpage", slug }],
        resumeSeed(slug, identity),
      );
    return blockedMaterialResult(resultSeed(slug), outcome.issue);
  }
  if (outcome.receipt.terminal.status === "complete") return null;
  if (outcome.receipt.terminal.status === "needs_input")
    return blockedMaterialResult(
      resultSeed(slug),
      planIssue(
        "workflow.incoherent_gate",
        outcome.receipt.operation,
        "Webpage returned a human gate even though this material has no typed gate.",
      ),
    );
  return stoppedMaterialResult(
    resultSeed(slug),
    outcome.receipt.terminal.status,
    receiptIssue(outcome.receipt),
  );
};

const completedWebpage = (slug: string): MaterialResult =>
  completeMaterialResult(
    resultSeed(slug),
    [
      {
        role: "snapshot",
        path: `vault/webpages/${slug}/snapshot.webarchive`,
      },
      {
        role: "normalized_text",
        path: `processing/webpages/${slug}/source.md`,
      },
      {
        role: "canonical",
        path: `vault/webpages/${slug}/webpage.md`,
      },
    ],
    null,
  );

interface PreparedCarry {
  path: string;
  sha256: string;
  size: number;
}

type PublicationMode = "create" | "replace_stale" | "reconcile";

const prepareForAnalysis = async (
  runtime: MaterialRuntime,
  slug: string,
  identity: WebpageIdentity,
  input: Extract<WebpageRunInput, { mode: "process" }>,
  snapshotCreated: boolean,
): Promise<PreparedCarry | MaterialResult> => {
  const snapshotPath = `vault/webpages/${slug}/snapshot.webarchive`;
  const outputObservation = input.observation.facts.prepared;
  let publicationMode: PublicationMode;
  if (!outputObservation.present) publicationMode = "create";
  else if (snapshotCreated) publicationMode = "replace_stale";
  else if (outputObservation.usable) publicationMode = "reconcile";
  else
    return blockedMaterialResult(
      resultSeed(slug),
      planIssue(
        "webpage.prepared_unusable_without_fresh_snapshot",
        "webpage.prepare",
        "The existing Webpage source projection is unusable and no snapshot was created by this invocation to authorize its replacement.",
      ),
    );
  const prepared = await dispatch(runtime, "webpage.prepare", slug, {
    materialKey: `webpage:${slug}`,
    snapshotObservation: snapshotCreated
      ? { path: snapshotPath, present: true, usable: true }
      : input.observation.facts.snapshot,
    outputObservation,
    publicationMode,
    snapshotCreated,
  });
  const stop = stopForOutcome(slug, prepared, true, identity);
  if (stop !== null) return stop;
  const receipt = prepared.receipt as StageReceipt;
  return {
    path: `processing/webpages/${slug}/source.md`,
    sha256: receipt.source_sha256 as string,
    size: receipt.source_size as number,
  };
};

const analyse = async (
  runtime: MaterialRuntime,
  slug: string,
  identity: WebpageIdentity,
  input: Extract<WebpageRunInput, { mode: "process" }>,
  carry: PreparedCarry,
  capturedAt: string,
  mode: "create" | "repair",
  diagnostics: unknown[] = [],
): Promise<MaterialResult | null> => {
  const analysed = await dispatch(runtime, "webpage.analyse", slug, {
    materialKey: `webpage:${slug}`,
    identity,
    capturedAt,
    inputObservation: carry,
    outputObservation: input.observation.facts.canonical,
    mode,
    diagnostics,
  });
  return stopForOutcome(slug, analysed, true, identity);
};

const auditWebpage = async (
  runtime: MaterialRuntime,
  slug: string,
  identity: WebpageIdentity,
  input: Extract<WebpageRunInput, { mode: "process" }>,
  currentCarry: PreparedCarry | null,
  capturedAt: string,
): Promise<MaterialResult> => {
  const firstAudit = await dispatch(runtime, "webpage.audit", slug, {
    materialKey: `webpage:${slug}`,
    pass: 1,
  });
  const firstStop = stopForOutcome(slug, firstAudit, false, identity);
  if (firstStop !== null) return firstStop;
  const firstReceipt = firstAudit.receipt as StageReceipt;
  const target = `vault/webpages/${slug}/webpage.md`;
  if (firstReceipt.remaining_violations === 0) return completedWebpage(slug);
  if (
    (firstReceipt.escalated as Array<{ path: string }>).some(
      ({ path }) => path !== target,
    )
  )
    return blockedMaterialResult(
      resultSeed(slug),
      planIssue(
        "workflow.owner_ambiguity",
        "webpage.audit",
        "Audit escalation targeted an artifact outside this Webpage.",
      ),
    );

  let carry = currentCarry;
  if (carry === null) {
    const prepared = await prepareForAnalysis(
      runtime,
      slug,
      identity,
      input,
      false,
    );
    if ("terminal" in prepared) return prepared;
    carry = prepared;
  }
  const repaired = await analyse(
    runtime,
    slug,
    identity,
    input,
    carry,
    capturedAt,
    "repair",
    firstReceipt.escalated,
  );
  if (repaired !== null) return repaired;

  const secondAudit = await dispatch(runtime, "webpage.audit", slug, {
    materialKey: `webpage:${slug}`,
    pass: 2,
  });
  const secondStop = stopForOutcome(slug, secondAudit, false, identity);
  if (secondStop !== null) return secondStop;
  const secondReceipt = secondAudit.receipt as StageReceipt;
  if (
    (secondReceipt.escalated as Array<{ path: string }>).some(
      ({ path }) => path !== target,
    )
  )
    return blockedMaterialResult(
      resultSeed(slug),
      planIssue(
        "workflow.owner_ambiguity",
        "webpage.audit",
        "The second audit targeted an artifact outside this Webpage.",
      ),
    );
  if (secondReceipt.remaining_violations === 0) return completedWebpage(slug);
  return blockedMaterialResult(
    resultSeed(slug),
    planIssue(
      "workflow.repair_exhausted",
      "webpage.audit",
      "The bounded Webpage repair completed, but the second audit still found violations.",
    ),
  );
};

export async function runWebpagePlan(
  runtime: MaterialRuntime,
  input: WebpageRunInput,
): Promise<MaterialResult> {
  if (input.mode === "identify") {
    const identified = await dispatch(
      runtime,
      "webpage.identify",
      "webpage-intake",
      {
        materialKey: "webpage:intake",
        requestedUrl: input.seed.url,
      },
    );
    const stop = stopForOutcome(null, identified, false, null);
    if (stop !== null) return stop;
    const receipt = identified.receipt as StageReceipt;
    const identity = receipt.identity as WebpageIdentity;
    const owner = receipt.local_owner as { slug: string } | null;
    const slug = owner?.slug ?? identity.slug;
    const canonicalIdentity = { ...identity, slug };
    return needsObservationMaterialResult(
      resultSeed(slug),
      [{ kind: "webpage", slug }],
      resumeSeed(slug, canonicalIdentity),
    );
  }

  const slug = input.seed.material_slug;
  let identity = input.effectiveIdentity;
  let capturedAt = input.observation.facts.captured_at;
  let snapshotCreated = false;
  if (!input.observation.facts.snapshot.usable) {
    const captured = await dispatch(runtime, "webpage.capture", slug, {
      materialKey: `webpage:${slug}`,
      identity,
      snapshotObservation: input.observation.facts.snapshot,
    });
    const captureStop = stopForOutcome(slug, captured, true, identity);
    if (captureStop !== null) return captureStop;
    const receipt = captured.receipt as StageReceipt;
    identity = {
      ...identity,
      title: receipt.title as string,
      site: receipt.site as string,
    };
    capturedAt = receipt.captured_at as string;
    snapshotCreated = true;
  }

  let carry: PreparedCarry | null = null;
  const needsAnalysis =
    !input.observation.facts.canonical.usable || snapshotCreated;
  if (!input.observation.facts.prepared.usable || needsAnalysis) {
    const prepared = await prepareForAnalysis(
      runtime,
      slug,
      identity,
      input,
      snapshotCreated,
    );
    if ("terminal" in prepared) return prepared;
    carry = prepared;
  }
  if (needsAnalysis) {
    const analysed = await analyse(
      runtime,
      slug,
      identity,
      input,
      carry as PreparedCarry,
      capturedAt as string,
      input.observation.facts.canonical.present ? "repair" : "create",
    );
    if (analysed !== null) return analysed;
  }

  return auditWebpage(
    runtime,
    slug,
    identity,
    input,
    carry,
    capturedAt as string,
  );
}
