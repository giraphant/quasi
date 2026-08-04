import { PIPELINE } from "./artifact-contracts/generated.mjs";
import { InputContractError } from "./context-base.mts";
import {
  OPERATION_ROWS,
  prepareOperation,
  resolveCatalogOperation,
  resolveOperationContext,
  writeTargetsOverlap,
  type CatalogOperation,
  type OperationInvocation,
  type PreparedOperation,
} from "./operations/catalog.mts";
import {
  dispatchOperation,
  dispatchPreparedOperation,
  type DispatchOutcome,
} from "./shared/dispatch.mts";
import {
  STAGE_STATUSES,
  stageReceiptPartition,
  stageReceiptSchema,
} from "./stage.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";
import type {
  KindName,
  OperationName,
  StageName,
  StageReceipt,
  WorkflowContext,
} from "./artifact-contracts/generated.mjs";

export {
  OPERATION_ROWS,
  PIPELINE,
  STAGE_STATUSES,
  stageReceiptPartition,
  stageReceiptSchema,
};

export type ResolvedStage = CatalogOperation;

interface StageChain {
  sequence: StageName[];
  carries: Array<{
    from: StageName;
    apply: (
      receipt: StageReceipt,
      context: WorkflowContext,
    ) => WorkflowContext;
  }>;
}

interface RunUnit {
  slug?: any;
  label?: string;
  context?: WorkflowContext;
}

interface RunArgs {
  kind?: any;
  slug?: any;
  stage?: any;
  until?: any;
  context?: WorkflowContext;
  units?: RunUnit[];
}

interface RunRuntime extends MaterialRuntime {
  log?: (message: string) => void;
}

export const RUN_STAGE_REGISTRY: Record<
  string,
  Partial<Record<StageName, OperationName>>
> = Object.fromEntries(
  Object.entries(PIPELINE).map(([kind, definition]) => [
    kind,
    Object.fromEntries(
      definition.stages.map(({ stage, operation }) => [stage, operation]),
    ),
  ]),
);
RUN_STAGE_REGISTRY.translate = RUN_STAGE_REGISTRY.translation;

export const STAGE_CHAINS = Object.fromEntries(
  Object.entries(PIPELINE).flatMap(([kind, definition]) =>
    definition.chain
      ? [
          [
            kind,
            {
              sequence: [...definition.chain.sequence],
              carries: definition.chain.carries.map(
                ({ from, field, to }) => ({
                  from,
                  apply: (
                    receipt: StageReceipt,
                    context: WorkflowContext,
                  ) => ({
                    ...context,
                    [to]: receipt[field],
                  }),
                }),
              ),
            },
          ],
        ]
      : [],
  ),
) as Partial<Record<KindName, StageChain>>;

export const workflowMeta = {
  name: "Quasi",
  description: "Pipeline",
  phases: [
    { title: "Recall" }, { title: "Search" }, { title: "Acquire" },
    { title: "Prepare" }, { title: "Analyse" }, { title: "Synthesise" },
    { title: "Audit" },
  ],
};

const errorResult = (code: string, args: RunArgs, message: string) => ({
  schema_version: "quasi.run-stage.error/0.1",
  status: "error",
  error: {
    code,
    message,
    kind: typeof args.kind === "string" ? args.kind : null,
    slug: typeof args.slug === "string" ? args.slug : null,
    stage: typeof args.stage === "string" ? args.stage : null,
  },
});

export function resolveStage(
  kind: unknown,
  stage: unknown,
): ResolvedStage | null {
  const normalizedKind = typeof kind === "string" ? kind.trim().toLowerCase() : "";
  const normalizedStage = typeof stage === "string" ? stage.trim().toLowerCase() : "";
  const stageName = normalizedStage as StageName;
  const operation = RUN_STAGE_REGISTRY[normalizedKind]?.[stageName];
  if (!operation) return null;
  const canonicalKind = (
    normalizedKind === "translate" ? "translation" : normalizedKind
  ) as KindName;
  return resolveCatalogOperation(canonicalKind, operation);
}

export function resolveStageContext(
  resolved: ResolvedStage,
  slug: any,
  rawContext: unknown,
): WorkflowContext {
  return resolveOperationContext(resolved, slug, rawContext);
}

const operationInvocation = (
  resolved: ResolvedStage,
  slug: any,
  context: WorkflowContext | undefined,
  label: string,
): OperationInvocation => ({
  kind: resolved.kind,
  operation: resolved.operation,
  slug,
  context: context || {},
  label,
});

const compatibilityError = (
  outcome: Exclude<DispatchOutcome, { kind: "receipt" }>,
  args: RunArgs,
) =>
  errorResult(
    `run-stage.${outcome.kind}`,
    args,
    outcome.issue.summary,
  );

const compatibilityResult = (
  outcome: DispatchOutcome,
  args: RunArgs,
) =>
  outcome.kind === "receipt"
    ? outcome.receipt
    : compatibilityError(outcome, args);

async function runChain(
  runtime: RunRuntime,
  args: RunArgs,
  resolved: ResolvedStage,
  chain: StageChain,
  from: StageName,
  until: StageName,
) {
  const receipts: Array<{ stage: StageName; receipt: any }> = [];
  let accumulatedContext =
    args.context && typeof args.context === "object" ? args.context : {};
  let stoppedAt: StageName | null = null;
  let stopReason = "end";
  const startIndex = chain.sequence.indexOf(from);
  const untilIndex = chain.sequence.indexOf(until);

  for (const currentStage of chain.sequence.slice(startIndex, untilIndex + 1)) {
    const current = (
      currentStage === from
        ? resolved
        : resolveStage(resolved.kind, currentStage)
    ) as ResolvedStage;
    const currentArgs = { ...args, stage: currentStage };
    const outcome = await dispatchOperation(
      runtime,
      operationInvocation(
        current,
        args.slug,
        accumulatedContext,
        `${args.slug}:${currentStage}`,
      ),
    );
    if (outcome.kind === "invalid_context") {
      receipts.push({
        stage: currentStage,
        receipt: compatibilityError(outcome, currentArgs),
      });
      stopReason = "invalid_context";
      break;
    }

    if (typeof runtime.log === "function") {
      runtime.log(`${currentStage} — ${String(args.slug).slice(0, 60)}`);
    }
    stoppedAt = currentStage;
    if (outcome.kind === "unknown_outcome") {
      receipts.push({ stage: currentStage, receipt: null });
      stopReason = "no_receipt";
      break;
    }
    const receipt = outcome.receipt;
    receipts.push({ stage: currentStage, receipt });
    if (outcome.kind === "incoherent_complete") {
      stopReason = "incoherent_complete";
      break;
    }
    if (receipt.terminal.status !== "complete") {
      stopReason = receipt.terminal.status;
      break;
    }

    for (const carry of chain.carries) {
      if (carry.from === currentStage)
        accumulatedContext = carry.apply(receipt, accumulatedContext);
    }
  }

  return {
    schema_version: "quasi.run-stage.chain/0.1",
    kind: resolved.kind,
    slug: args.slug,
    from,
    until,
    stopped_at: stoppedAt,
    stop_reason: stopReason,
    receipts,
  };
}

export async function run(
  runtime: RunRuntime,
  inputArgs: unknown,
) {
  const args =
    inputArgs && typeof inputArgs === "object"
      ? (inputArgs as RunArgs)
      : {};
  const resolved = resolveStage(args.kind, args.stage);
  if (!resolved) {
    const normalizedKind =
      typeof args.kind === "string" ? args.kind.trim().toLowerCase() : "";
    return errorResult(
      RUN_STAGE_REGISTRY[normalizedKind]
        ? "run-stage.unknown_stage"
        : "run-stage.unknown_kind",
      args,
      `No run-stage row for kind=${String(args.kind)} stage=${String(args.stage)}`,
    );
  }
  const units =
    Array.isArray(args.units) && args.units.length > 0 ? args.units : null;
  const hasUntil =
    typeof args.until === "string" && args.until.trim().length > 0;
  if (hasUntil) {
    if (args.units !== undefined) {
      return errorResult(
        "run-stage.invalid_context",
        args,
        "run-stage until cannot be combined with units",
      );
    }
    const from = args.stage.trim().toLowerCase() as StageName;
    const until = args.until.trim().toLowerCase() as StageName;
    const chain = STAGE_CHAINS[resolved.kind];
    const fromIndex = chain?.sequence.indexOf(from) ?? -1;
    const untilIndex = chain?.sequence.indexOf(until) ?? -1;
    if (!chain || fromIndex < 0 || untilIndex < 0 || fromIndex > untilIndex) {
      return errorResult(
        "run-stage.invalid_chain",
        args,
        `No valid run-stage chain for kind=${resolved.kind} from=${from} until=${until}`,
      );
    }
    return runChain(runtime, args, resolved, chain, from, until);
  }
  if (units) {
    if (units.length > 64) {
      return errorResult(
        "run-stage.invalid_context",
        args,
        `run-stage units must contain at most 64 items; received ${units.length}`,
      );
    }
    const receipts = new Array(units.length);
    const pending: Array<{
      index: number;
      args: RunArgs;
      prepared: PreparedOperation;
    }> = [];
    for (const [index, unit] of units.entries()) {
      const unitSlug = unit?.slug || args.slug;
      const unitArgs = { ...args, slug: unitSlug, context: unit?.context };
      const cleanLabel =
        typeof unit?.label === "string"
          ? unit.label.trim().replace(/\s+/g, " ").slice(0, 40)
          : "";
      const invocation = operationInvocation(
        resolved,
        unitSlug,
        unit?.context,
        `${unitSlug}:${args.stage}${cleanLabel ? `:${cleanLabel}` : ""}`,
      );
      try {
        pending.push({
          index,
          args: unitArgs,
          prepared: prepareOperation(invocation),
        });
      } catch (error) {
        if (!(error instanceof InputContractError)) throw error;
        receipts[index] = errorResult(
          "run-stage.invalid_context",
          unitArgs,
          error instanceof Error ? error.message : String(error),
        );
      }
    }
    for (let left = 0; left < pending.length; left += 1) {
      for (let right = left + 1; right < pending.length; right += 1) {
        const overlaps = pending[left].prepared.writeTargets.some(
          (leftTarget) =>
            pending[right].prepared.writeTargets.some((rightTarget) =>
              writeTargetsOverlap(leftTarget, rightTarget),
            ),
        );
        if (overlaps) {
          return errorResult(
            "run-stage.duplicate_unit",
            args,
            `Duplicate run-stage write targets at indexes ${pending[left].index} and ${pending[right].index}`,
          );
        }
      }
    }
    if (typeof runtime.log === "function") {
      runtime.log(
        `${args.stage} × ${units.length} — ${String(args.slug).slice(0, 60)}`,
      );
    }
    const dispatched = await runtime.pipeline(
      pending,
      (item) => dispatchPreparedOperation(runtime, item.prepared),
    );
    for (const [pendingIndex, item] of pending.entries()) {
      receipts[item.index] = compatibilityResult(
        dispatched[pendingIndex],
        item.args,
      );
    }
    return {
      schema_version: "quasi.run-stage.batch/0.1",
      kind: resolved.kind,
      stage: args.stage.trim().toLowerCase(),
      count: units.length,
      receipts,
    };
  }
  const outcome = await dispatchOperation(
    runtime,
    operationInvocation(
      resolved,
      args.slug,
      args.context,
      `${args.slug}:${args.stage}`,
    ),
  );
  if (outcome.kind !== "invalid_context" && typeof runtime.log === "function")
    runtime.log(`${args.stage} — ${String(args.slug).slice(0, 60)}`);
  return compatibilityResult(outcome, args);
}
