import { PIPELINE } from "../artifact-contracts/generated.mjs";
import {
  InputContractError,
  expandArtifactTemplates,
  operationContextBase,
} from "../context-base.mts";
import { defineOperation, type DefinedOperation } from "./define.mts";
import { authorOperationRows } from "./rows/author.mts";
import { bookOperationRows } from "./rows/book.mts";
import { paperOperationRows } from "./rows/paper.mts";
import { materialSearchOperationRows } from "./rows/search.mts";
import { talkOperationRows } from "./rows/talk.mts";
import { topicOperationRows } from "./rows/topic.mts";
import { translationOperationRows } from "./rows/translation.mts";
import type {
  KindName,
  OperationDescriptor,
  OperationName,
  OperationRow,
  PipelineStage,
  StageReceipt,
  WorkflowContext,
  WriteTarget,
} from "../artifact-contracts/generated.mjs";
import type { AgentOptions } from "../shared/host-runtime.mts";

export const OPERATION_ROWS: OperationRow[] = [
  ...materialSearchOperationRows,
  ...paperOperationRows,
  ...bookOperationRows,
  ...talkOperationRows,
  ...translationOperationRows,
  ...topicOperationRows,
  ...authorOperationRows,
];

const rowsByOperation = Object.fromEntries(
  OPERATION_ROWS.map((row) => [row.operation, row]),
) as Record<OperationName, OperationRow>;

export interface CatalogOperation {
  kind: KindName;
  operation: OperationName;
  descriptor: OperationDescriptor;
  row: DefinedOperation;
}

export interface OperationInvocation {
  kind: KindName;
  operation: OperationName;
  slug: string;
  context: WorkflowContext;
  label: string;
}

export interface PreparedOperation {
  invocation: OperationInvocation;
  context: WorkflowContext;
  prompt: string;
  options: AgentOptions;
  stampedValues: WorkflowContext;
  complete(receipt: StageReceipt): boolean;
  writeTargets: readonly WriteTarget[];
}

const stageIdentity = (
  kind: KindName,
  operation: OperationName,
): PipelineStage | null =>
  PIPELINE[kind]?.stages.find(
    (identity) => identity.operation === operation,
  ) || null;

export function resolveCatalogOperation(
  kind: KindName,
  operation: OperationName,
): CatalogOperation | null {
  const identity = stageIdentity(kind, operation);
  const operationRow = rowsByOperation[operation];
  if (!identity || !operationRow) return null;
  const descriptor = {
    ...operationRow,
    stage: identity.phase,
    effect: identity.effect,
    agentType: identity.agent,
    artifacts: identity.artifacts || {},
  } as OperationDescriptor;
  return {
    kind,
    operation,
    descriptor,
    row: defineOperation(descriptor),
  };
}

export function resolveOperationContext(
  resolved: CatalogOperation,
  slug: string,
  rawContext: unknown,
): WorkflowContext {
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

const validTargetPath = (path: unknown): path is string => {
  if (
    typeof path !== "string" ||
    path.length === 0 ||
    path.startsWith("/") ||
    path.includes("\\")
  )
    return false;
  const parts = path.split("/");
  return (
    parts.every((part) => part.length > 0 && part !== "." && part !== "..") &&
    parts.join("/") === path
  );
};

const resolvedWriteTargets = (
  resolved: CatalogOperation,
  refs: WorkflowContext,
  context: WorkflowContext,
): readonly WriteTarget[] => {
  const { effect, writeTargets } = resolved.descriptor;
  if (effect === "readonly") {
    if (writeTargets !== undefined)
      throw new Error(
        `readonly operation must omit writeTargets: ${resolved.operation}`,
      );
    return [];
  }
  if (typeof writeTargets !== "function")
    throw new Error(
      `writer operation has no writeTargets: ${resolved.operation}`,
    );
  const targets = writeTargets(refs, context);
  if (!Array.isArray(targets) || targets.length === 0)
    throw new Error(
      `writer operation has no resolved write target: ${resolved.operation}`,
    );
  for (const target of targets) {
    if (
      !target ||
      !["exact", "subtree"].includes(target.scope) ||
      !validTargetPath(target.path)
    )
      throw new Error(
        `writer operation has invalid write target: ${resolved.operation}`,
      );
  }
  return targets;
};

export function prepareOperation(
  invocation: OperationInvocation,
): PreparedOperation {
  const resolved = resolveCatalogOperation(
    invocation?.kind,
    invocation?.operation,
  );
  if (!resolved)
    throw new InputContractError(
      `operation is not registered for material kind: ${String(invocation?.kind)}:${String(invocation?.operation)}`,
    );
  if (typeof invocation.label !== "string" || invocation.label.length === 0)
    throw new InputContractError("operation invocation requires a label");

  const context = resolveOperationContext(
    resolved,
    invocation.slug,
    invocation.context,
  );
  const refs = resolved.row.refs(context);
  const prompt = resolved.row.prompt(context);
  const { modelSchema, stampedValues } =
    resolved.row.receiptSchema(context);
  const writeTargets = resolvedWriteTargets(resolved, refs, context);

  return {
    invocation,
    context,
    prompt,
    options: {
      schema: modelSchema,
      agentType: resolved.descriptor.agentType,
      phase: resolved.descriptor.stage,
      label: invocation.label,
    },
    stampedValues,
    complete: (receipt: StageReceipt): boolean =>
      receipt.terminal.status === "complete" &&
      resolved.row.contract.statuses.complete(receipt, context) === true,
    writeTargets,
  };
}

const atOrBelow = (path: string, root: string): boolean =>
  path === root || path.startsWith(`${root}/`);

export function writeTargetsOverlap(
  left: WriteTarget,
  right: WriteTarget,
): boolean {
  if (left.scope === "exact" && right.scope === "exact")
    return left.path === right.path;
  if (left.scope === "subtree" && right.scope === "subtree")
    return atOrBelow(left.path, right.path) || atOrBelow(right.path, left.path);
  return left.scope === "subtree"
    ? atOrBelow(right.path, left.path)
    : atOrBelow(left.path, right.path);
}
