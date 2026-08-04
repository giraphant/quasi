import { PIPELINE } from "./artifact-contracts/generated.mjs";
import { InputContractError } from "./context-base.mts";
import {
  OPERATION_ROWS,
  resolveCatalogOperation,
  resolveOperationContext,
  type CatalogOperation,
} from "./operations/catalog.mts";
import {
  STAGE_STATUSES,
  stageReceiptPartition,
  stageReceiptSchema,
} from "./stage.mts";
import type {
  AgentOptions,
  DispatchRuntime,
} from "./shared/host-runtime.mts";
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

interface RunRuntime extends DispatchRuntime {
  parallel?: (
    thunks: Array<() => Promise<StageReceipt | null>>,
  ) => Promise<Array<StageReceipt | null>>;
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

const stampStageReceipt = (
  stampedValues: WorkflowContext,
  modelOutput: WorkflowContext | null,
): StageReceipt | null => {
  if (modelOutput == null) return null;
  const collisions = Object.keys(stampedValues).filter((key) =>
    Object.prototype.hasOwnProperty.call(modelOutput, key),
  );
  if (collisions.length > 0)
    throw new Error(
      `validated model output contains host-stamped receipt fields: ${collisions.join(", ")}`,
    );
  return { ...stampedValues, ...modelOutput } as StageReceipt;
};

const dispatchStageUnit = async (
  agent: DispatchRuntime["agent"],
  prompt: string,
  options: AgentOptions,
  stampedValues: WorkflowContext,
): Promise<StageReceipt | null> =>
  stampStageReceipt(stampedValues, await agent(prompt, options));

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

async function runChain(
  { agent, log }: RunRuntime,
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
    let stageContext;
    let prompt;
    let schema;
    let stampedValues;
    try {
      stageContext = resolveStageContext(
        current,
        args.slug,
        accumulatedContext,
      );
      prompt = current.row.prompt(stageContext);
      ({ modelSchema: schema, stampedValues } =
        current.row.receiptSchema(stageContext));
    } catch (error) {
      if (!(error instanceof InputContractError)) throw error;
      receipts.push({
        stage: currentStage,
        receipt: errorResult(
          "run-stage.invalid_context",
          { ...args, stage: currentStage },
          error instanceof Error ? error.message : String(error),
        ),
      });
      stopReason = "invalid_context";
      break;
    }

    if (typeof log === "function") {
      log(`${currentStage} — ${String(args.slug).slice(0, 60)}`);
    }
    const receipt = await dispatchStageUnit(
      agent,
      prompt,
      {
        schema,
        agentType: current.descriptor.agentType,
        phase: current.descriptor.stage,
        label: `${args.slug}:${currentStage}`,
      },
      stampedValues,
    );
    stoppedAt = currentStage;
    receipts.push({ stage: currentStage, receipt });

    if (receipt == null) {
      stopReason = "no_receipt";
      break;
    }
    if (receipt.terminal.status !== "complete") {
      stopReason = receipt.terminal.status;
      break;
    }

    let coherent = false;
    try {
      coherent =
        current.row.contract.statuses.complete(receipt, stageContext) === true;
    } catch {
      coherent = false;
    }
    if (!coherent) {
      stopReason = "incoherent_complete";
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
  { agent, parallel, log }: RunRuntime,
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
    return runChain({ agent, log }, args, resolved, chain, from, until);
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
    const pending = [];
    const promptIndexes = new Map();
    for (const [index, unit] of units.entries()) {
      const unitSlug = unit?.slug || args.slug;
      const unitArgs = { ...args, slug: unitSlug, context: unit?.context };
      let prompt;
      let schema;
      let stampedValues;
      try {
        const context = resolveStageContext(
          resolved,
          unitSlug,
          unit?.context,
        );
        prompt = resolved.row.prompt(context);
        ({ modelSchema: schema, stampedValues } =
          resolved.row.receiptSchema(context));
      } catch (error) {
        if (!(error instanceof InputContractError)) throw error;
        receipts[index] = errorResult(
          "run-stage.invalid_context",
          unitArgs,
          error instanceof Error ? error.message : String(error),
        );
        continue;
      }
      if (promptIndexes.has(prompt)) {
        const firstIndex = promptIndexes.get(prompt);
        return errorResult(
          "run-stage.duplicate_unit",
          args,
          `Duplicate run-stage units at indexes ${firstIndex} and ${index}`,
        );
      }
      promptIndexes.set(prompt, index);
      const cleanLabel =
        typeof unit?.label === "string"
          ? unit.label.trim().replace(/\s+/g, " ").slice(0, 40)
          : "";
      pending.push({
        index,
        prompt,
        schema,
        stampedValues,
        label: `${unitSlug}:${args.stage}${cleanLabel ? `:${cleanLabel}` : ""}`,
      });
    }
    if (typeof log === "function") {
      log(`${args.stage} × ${units.length} — ${String(args.slug).slice(0, 60)}`);
    }
    const thunks = pending.map(
      ({ prompt, schema, stampedValues, label }) => async () =>
        dispatchStageUnit(
          agent,
          prompt,
          {
            schema,
            agentType: resolved.descriptor.agentType,
            phase: resolved.descriptor.stage,
            label,
          },
          stampedValues,
        ),
    );
    const dispatched =
      typeof parallel === "function"
        ? await parallel(thunks)
        : await Promise.all(thunks.map((thunk) => thunk().catch(() => null)));
    for (const [pendingIndex, item] of pending.entries()) {
      receipts[item.index] = dispatched[pendingIndex];
    }
    return {
      schema_version: "quasi.run-stage.batch/0.1",
      kind: resolved.kind,
      stage: args.stage.trim().toLowerCase(),
      count: units.length,
      receipts,
    };
  }
  let context;
  let prompt;
  let schema;
  let stampedValues;
  try {
    context = resolveStageContext(resolved, args.slug, args.context);
    prompt = resolved.row.prompt(context);
    ({ modelSchema: schema, stampedValues } =
      resolved.row.receiptSchema(context));
  } catch (error) {
    if (!(error instanceof InputContractError)) throw error;
    return errorResult("run-stage.invalid_context", args, error instanceof Error ? error.message : String(error));
  }
  if (typeof log === "function") {
    log(`${args.stage} — ${String(args.slug).slice(0, 60)}`);
  }
  return dispatchStageUnit(
    agent,
    prompt,
    {
      schema,
      agentType: resolved.descriptor.agentType,
      phase: resolved.descriptor.stage,
      label: `${args.slug}:${args.stage}`,
    },
    stampedValues,
  );
}
