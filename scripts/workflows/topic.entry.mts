import { parseTopicRunInput } from "./contracts/topic.mts";
import { runTopicPlan } from "./plans/topic.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "topic";

export const workflowMeta = {
  name: "Quasi Topic",
  description: "Research one Topic through bounded leaf composition and exact checkpoints.",
  phases: [
    { title: "Recall" },
    { title: "Search" },
    { title: "Synthesise" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseTopicRunInput(raw);
  return parsed.ok ? runTopicPlan(runtime, parsed.value) : parsed.result;
}
