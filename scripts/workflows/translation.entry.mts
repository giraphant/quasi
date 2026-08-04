import { parseTranslationRunInput } from "./contracts/translation.mts";
import { runTranslationPlan } from "./plans/translation.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "translation";

export const workflowMeta = {
  name: "Quasi Translation",
  description: "Translate one Paper-derived source into one exact target.",
  phases: [{ title: "Prepare" }],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseTranslationRunInput(raw);
  return parsed.ok
    ? runTranslationPlan(runtime, parsed.value)
    : parsed.result;
}
