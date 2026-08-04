import { parseTalkRunInput } from "./contracts/talk.mts";
import { runTalkPlan } from "./plans/talk.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";

export const materialKind = "talk";

export const workflowMeta = {
  name: "Quasi Talk",
  description: "Process one Talk from transcription through audit.",
  phases: [
    { title: "Prepare" },
    { title: "Analyse" },
    { title: "Audit" },
  ],
};

export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseTalkRunInput(raw);
  return parsed.ok ? runTalkPlan(runtime, parsed.value) : parsed.result;
}
