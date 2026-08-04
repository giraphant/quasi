import { parsePaperRunInput } from "./contracts/paper.mts";
import { runPaperPlan } from "./plans/paper.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "paper";

export const workflowMeta = {
  name: "Quasi Paper",
  description: "Process one Paper from identity through audit.",
  phases: [
    { title: "Search" },
    { title: "Acquire" },
    { title: "Prepare" },
    { title: "Analyse" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parsePaperRunInput(raw);
  return parsed.ok
    ? runPaperPlan(runtime, parsed.value)
    : parsed.result;
}
