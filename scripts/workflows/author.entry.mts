import { parseAuthorRunInput } from "./contracts/author.mts";
import { runAuthorPlan } from "./plans/author.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "author";

export const workflowMeta = {
  name: "Quasi Author",
  description: "Compose representative Paper and Book workflows for one Author.",
  phases: [
    { title: "Search" },
    { title: "Analyse" },
    { title: "Synthesise" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseAuthorRunInput(raw);
  return parsed.ok
    ? runAuthorPlan(runtime, parsed.value)
    : parsed.result;
}
