import type {
  JsonSchema,
  PhaseName,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

export interface AgentOptions {
  schema: JsonSchema;
  agentType: string;
  phase: PhaseName;
  label: string;
}

export interface DispatchRuntime {
  agent(
    prompt: string,
    options: AgentOptions,
  ): Promise<WorkflowContext | null>;
}

export interface MaterialRuntime extends DispatchRuntime {
  pipeline<T, R>(
    items: readonly T[],
    worker: (item: T) => Promise<R>,
  ): Promise<R[]>;
}
