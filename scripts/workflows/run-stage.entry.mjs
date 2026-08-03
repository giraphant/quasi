import { PIPELINE } from "./artifact-contracts/generated.mjs";
import {
  expandArtifactTemplates,
  operationContextBase,
} from "./context-base.mjs";
import { defineOperation } from "./operations/define.mjs";
import { authorOperationRows } from "./operations/rows/author.mjs";
import { bookOperationRows } from "./operations/rows/book.mjs";
import { paperOperationRows } from "./operations/rows/paper.mjs";
import { materialSearchOperationRows } from "./operations/rows/search.mjs";
import { talkOperationRows } from "./operations/rows/talk.mjs";
import { topicOperationRows } from "./operations/rows/topic.mjs";
import { translationOperationRows } from "./operations/rows/translation.mjs";

/** @typedef {import("./artifact-contracts/generated.mjs").KindName} KindName */
/** @typedef {import("./artifact-contracts/generated.mjs").OperationDescriptor} OperationDescriptor */
/** @typedef {import("./artifact-contracts/generated.mjs").OperationName} OperationName */
/** @typedef {import("./artifact-contracts/generated.mjs").OperationRow} OperationRow */
/** @typedef {import("./artifact-contracts/generated.mjs").PipelineStage} PipelineStage */
/** @typedef {import("./artifact-contracts/generated.mjs").StageName} StageName */
/** @typedef {import("./artifact-contracts/generated.mjs").StageReceipt} StageReceipt */
/** @typedef {import("./artifact-contracts/generated.mjs").WorkflowContext} WorkflowContext */
/** @typedef {{schema: (context: WorkflowContext) => Record<string, any>, contract: any, prompt: (context: WorkflowContext) => string}} DefinedOperation */
/** @typedef {{kind: KindName, operation: OperationName, descriptor: OperationDescriptor, row: DefinedOperation}} ResolvedStage */
/** @typedef {{sequence: StageName[], carries: Array<{from: StageName, apply: (receipt: StageReceipt, context: WorkflowContext) => WorkflowContext}>}} StageChain */
/** @typedef {{slug?: any, label?: string, context?: WorkflowContext}} RunUnit */
/** @typedef {{kind?: any, slug?: any, stage?: any, until?: any, context?: WorkflowContext, units?: RunUnit[]}} RunArgs */
/** @typedef {{schema: Record<string, any>, agentType: string, phase: string, label: string}} AgentOptions */
/** @typedef {(prompt: string, options: AgentOptions) => Promise<StageReceipt | null>} Agent */
/** @typedef {{agent: Agent, parallel?: (thunks: Array<() => Promise<StageReceipt | null>>) => Promise<Array<StageReceipt | null>>, log?: (message: string) => void}} RunRuntime */

export { PIPELINE };

/** @type {OperationRow[]} */
export const OPERATION_ROWS = [
  ...materialSearchOperationRows,
  ...paperOperationRows,
  ...bookOperationRows,
  ...talkOperationRows,
  ...translationOperationRows,
  ...topicOperationRows,
  ...authorOperationRows,
];

const descriptors = /** @type {Record<OperationName, OperationRow>} */ (
  Object.fromEntries(
    OPERATION_ROWS.map((row) => [row.operation, row]),
  )
);

const stageIdentities = /** @type {Record<KindName, Partial<Record<StageName, PipelineStage>>>} */ (
  Object.fromEntries(
    Object.entries(PIPELINE).map(([kind, definition]) => [
      kind,
      Object.fromEntries(
        definition.stages.map((identity) => [identity.stage, identity]),
      ),
    ]),
  )
);

/** @type {Record<string, Partial<Record<StageName, OperationName>>>} */
export const RUN_STAGE_REGISTRY = Object.fromEntries(
  Object.entries(PIPELINE).map(([kind, definition]) => [
    kind,
    Object.fromEntries(
      definition.stages.map(({ stage, operation }) => [stage, operation]),
    ),
  ]),
);
RUN_STAGE_REGISTRY.translate = RUN_STAGE_REGISTRY.translation;

/** @type {Partial<Record<KindName, StageChain>>} */
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
                  /** @param {StageReceipt} receipt @param {WorkflowContext} context */
                  apply: (receipt, context) => ({
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
);

export const workflowMeta = {
  name: "Quasi",
  description: "Pipeline",
  phases: [
    { title: "Recall" }, { title: "Search" }, { title: "Acquire" },
    { title: "Prepare" }, { title: "Analyse" }, { title: "Synthesise" },
    { title: "Audit" },
  ],
};

/**
 * @param {string} code
 * @param {RunArgs} args
 * @param {string} message
 */
const errorResult = (code, args, message) => ({
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

/**
 * @param {unknown} kind
 * @param {unknown} stage
 * @returns {ResolvedStage | null}
 */
export function resolveStage(kind, stage) {
  const normalizedKind = typeof kind === "string" ? kind.trim().toLowerCase() : "";
  const normalizedStage = typeof stage === "string" ? stage.trim().toLowerCase() : "";
  const stageName = /** @type {StageName} */ (normalizedStage);
  const operation = RUN_STAGE_REGISTRY[normalizedKind]?.[stageName];
  if (!operation) return null;
  const canonicalKind = /** @type {KindName} */ (
    normalizedKind === "translate" ? "translation" : normalizedKind
  );
  const identity = /** @type {PipelineStage} */ (
    stageIdentities[canonicalKind][stageName]
  );
  const descriptor = /** @type {OperationDescriptor} */ ({
    ...descriptors[operation],
    stage: identity.phase,
    effect: identity.effect,
    agentType: identity.agent,
    artifacts: identity.artifacts || {},
  });
  return { kind: canonicalKind, operation, descriptor, row: defineOperation(descriptor) };
}

/**
 * @param {ResolvedStage} resolved
 * @param {any} slug
 * @param {unknown} rawContext
 * @returns {WorkflowContext}
 */
export function resolveStageContext(resolved, slug, rawContext) {
  const templates = resolved.descriptor.artifacts;
  const base = operationContextBase(
    resolved.kind,
    slug,
    rawContext,
    Object.keys(templates),
  );
  const context =
    typeof resolved.descriptor.context === "function"
      ? resolved.descriptor.context(
          rawContext && typeof rawContext === "object" ? rawContext : {},
          base,
        )
      : base;
  return expandArtifactTemplates(templates, rawContext, context);
}

/**
 * @param {RunRuntime} runtime
 * @param {RunArgs} args
 * @param {ResolvedStage} resolved
 * @param {StageChain} chain
 * @param {StageName} from
 * @param {StageName} until
 */
async function runChain({ agent, log }, args, resolved, chain, from, until) {
  /** @type {Array<{stage: StageName, receipt: any}>} */
  const receipts = [];
  let accumulatedContext =
    args.context && typeof args.context === "object" ? args.context : {};
  let stoppedAt = null;
  let stopReason = "end";
  const startIndex = chain.sequence.indexOf(from);
  const untilIndex = chain.sequence.indexOf(until);

  for (const currentStage of chain.sequence.slice(startIndex, untilIndex + 1)) {
    const current = /** @type {ResolvedStage} */ (
      currentStage === from
        ? resolved
        : resolveStage(resolved.kind, currentStage)
    );
    let stageContext;
    let prompt;
    let schema;
    try {
      stageContext = resolveStageContext(
        current,
        args.slug,
        accumulatedContext,
      );
      prompt = current.row.prompt(stageContext);
      schema = current.row.schema(stageContext);
    } catch (error) {
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
    const receipt = await agent(prompt, {
      schema,
      agentType: current.descriptor.agentType,
      phase: current.descriptor.stage,
      label: `${args.slug}:${currentStage}`,
    });
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

/**
 * @param {RunRuntime} runtime
 * @param {unknown} inputArgs
 */
export async function run({ agent, parallel, log }, inputArgs) {
  const args =
    inputArgs && typeof inputArgs === "object"
      ? /** @type {RunArgs} */ (inputArgs)
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
    const from = args.stage.trim().toLowerCase();
    const until = args.until.trim().toLowerCase();
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
      try {
        const context = resolveStageContext(
          resolved,
          unitSlug,
          unit?.context,
        );
        prompt = resolved.row.prompt(context);
        schema = resolved.row.schema(context);
      } catch (error) {
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
        label: `${unitSlug}:${args.stage}${cleanLabel ? `:${cleanLabel}` : ""}`,
      });
    }
    if (typeof log === "function") {
      log(`${args.stage} × ${units.length} — ${String(args.slug).slice(0, 60)}`);
    }
    const thunks = pending.map(
      ({ prompt, schema, label }) => async () =>
        agent(prompt, {
          schema,
          agentType: resolved.descriptor.agentType,
          phase: resolved.descriptor.stage,
          label,
        }),
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
  try {
    context = resolveStageContext(resolved, args.slug, args.context);
    prompt = resolved.row.prompt(context);
    schema = resolved.row.schema(context);
  } catch (error) {
    return errorResult("run-stage.invalid_context", args, error instanceof Error ? error.message : String(error));
  }
  if (typeof log === "function") {
    log(`${args.stage} — ${String(args.slug).slice(0, 60)}`);
  }
  return agent(prompt, {
    schema,
    agentType: resolved.descriptor.agentType,
    phase: resolved.descriptor.stage,
    label: `${args.slug}:${args.stage}`,
  });
}
