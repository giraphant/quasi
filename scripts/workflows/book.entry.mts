import { parseBookRunInput } from "./contracts/book.mts";
import { runBookPlan } from "./plans/book.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "book";

export const workflowMeta = {
  name: "Quasi Book",
  description: "Process one Book through one owned chapter pipeline and audit.",
  phases: [
    { title: "Search" },
    { title: "Acquire" },
    { title: "Prepare" },
    { title: "Analyse" },
    { title: "Synthesise" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseBookRunInput(raw);
  return parsed.ok ? runBookPlan(runtime, parsed.value) : parsed.result;
}
