import type { ArchiveRunInput, ArchiveIdentity } from "../contracts/archive.mts";
import { prepareOperation } from "../operations/catalogs/archive.mts";
import {
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "../shared/dispatch-prepared.mts";
import type { MaterialRuntime } from "../shared/host-runtime.mts";
import {
  blockedMaterialResult,
  stoppedMaterialResult,
  completeMaterialResult,
  needsObservationMaterialResult,
  type MaterialResult,
  type MaterialResultSeed,
} from "../shared/material-result.mts";
import type { OperationName, WorkflowContext } from "../artifact-contracts/generated.mjs";
import { normalizeWebUrl } from "../shared/web-url.mts";

export async function runArchivePlan(
  runtime: MaterialRuntime,
  input: ArchiveRunInput,
): Promise<MaterialResult> {
  let slug = input.seed.state === "canonical" ? input.seed.material_slug : null;
  const resultSeed = (): MaterialResultSeed => ({
    material: {
      requested: { kind: "archive", slug },
      canonical: slug ? { kind: "archive", slug } : null,
    },
  });
  const blocked = (
    code: string,
    summary: string,
    operation: OperationName | null = null,
  ) => blockedMaterialResult(resultSeed(), {
    code, summary, operation, retryable: false, observation_request: null,
  });
  const dispatch = (operation: OperationName, context: WorkflowContext) =>
    dispatchPreparedOperation(runtime, prepareOperation({
      operation,
      slug: slug ?? "archive-intake",
      context: {...context, ...(input.observation ? {
        archiveDirectory: input.observation.facts.canonical.path.slice(0, -"/archive.md".length),
      } : {})},
      label: `${slug ?? "archive-intake"}:${operation}`,
    }));
  const stop = (outcome: DispatchOutcome): MaterialResult | null => {
    if (outcome.kind !== "receipt")
      return blockedMaterialResult(resultSeed(), outcome.issue);
    const terminal = outcome.receipt.terminal;
    if (terminal.status === "complete") return null;
    if (terminal.status === "needs_input")
      return blocked("workflow.incoherent_gate", "Archive has no typed human gate.", outcome.receipt.operation);
    return stoppedMaterialResult(resultSeed(), terminal.status, {
      ...terminal.issue!, operation: outcome.receipt.operation, observation_request: null,
    });
  };
  const refresh = (identity: ArchiveIdentity) =>
    needsObservationMaterialResult(resultSeed(), [{ kind: "archive", slug: identity.slug }], {
      route: { kind: "archive", slug: identity.slug },
      seed: { state: "canonical", material_slug: identity.slug, identity },
      options: input.options,
    });

  if (input.seed.state === "provisional") {
    const outcome = await dispatch("archive.identify", { url: input.seed.url });
    const stopped = stop(outcome);
    if (stopped) return stopped;
    const identity = outcome.receipt!.identity as ArchiveIdentity;
    if (normalizeWebUrl(identity.url) !== normalizeWebUrl(input.seed.url))
      return blocked("archive.identity_conflict", "Identify changed the requested source URL.", "archive.identify");
    slug = identity.slug;
    return refresh(identity);
  }

  const identity = input.seed.identity;
  const observation = input.observation!;
  const canonical = observation.facts.canonical;
  const observed = observation.identity;
  const collection = observation.facts.collection;
  if (collection.revision === null || (collection.present && !collection.usable))
    return blocked("archive.collection_unusable", "Existing inventory or original requires explicit reconciliation.");
  if (canonical.present && !canonical.usable)
    return blocked("archive.existing_unusable", "Existing Archive requires explicit reconciliation; it will not be overwritten.");
  if (observed && (
    normalizeWebUrl(collection.source_url ?? observed.url) !== normalizeWebUrl(identity.url) ||
    (observed.url !== undefined && normalizeWebUrl(observed.url) !== normalizeWebUrl(identity.url)) ||
    observed.kind !== identity.kind
  )) return blocked("archive.identity_conflict", "Existing Archive belongs to a different source or material kind.");

  const topics: string[] = [...new Set([...(observed?.topics ?? []), ...input.options.topics])];
  if (!canonical.usable || !collection.usable || input.options.topics.some(topic => !(observed?.topics ?? []).includes(topic))) {
    const collected = await dispatch("archive.collect", {
      identity,
      topics,
      outputObservation: canonical,
      expectedFrontmatter: observed,
      collectionObservation: collection,
      mode: canonical.usable ? (collection.usable ? "membership" : "enrich") : "create",
    });
    const stopped = stop(collected);
    if (stopped) return stopped;
    return refresh(identity);
  }

  const audit = await dispatch("archive.audit", { pass: 1 });
  const stopped = stop(audit);
  if (stopped) return stopped;
  if (audit.receipt!.remaining_violations !== 0)
    return blocked("archive.audit_failed", "Archive audit reported unresolved violations.", "archive.audit");
  if ((audit.receipt!.mutated_paths as string[]).length > 0) return refresh(identity);
  return completeMaterialResult(resultSeed(), [
    { role: "canonical", path: canonical.path },
    { role: "manifest", path: collection.path },
    ...collection.files.map(file => ({role: "source" as const, path: file.path})),
  ], null);
}
