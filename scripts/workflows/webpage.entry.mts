import { parseWebpageRunInput } from "./contracts/webpage.mts";
import { runWebpagePlan } from "./plans/webpage.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "webpage";

export const workflowMeta = {
  name: "Quasi Webpage",
  description: "Capture one Webpage and create its canonical reading page.",
  phases: [
    { title: "Search" },
    { title: "Acquire" },
    { title: "Prepare" },
    { title: "Analyse" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseWebpageRunInput(raw);
  return parsed.ok ? runWebpagePlan(runtime, parsed.value) : parsed.result;
}
