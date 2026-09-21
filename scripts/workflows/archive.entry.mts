import { parseArchiveRunInput } from "./contracts/archive.mts";
import { runArchivePlan } from "./plans/archive.mts";
import type { MaterialRuntime } from "./shared/host-runtime.mts";
export const materialKind = "archive";
export const workflowMeta = { name: "Quasi Archive", description: "Collect one archival source with provenance and optional Topic membership.", phases: [{title: "Search"}, {title: "Acquire"}, {title: "Audit"}] };
export async function run(runtime: MaterialRuntime, raw: unknown) {
  const parsed = parseArchiveRunInput(raw);
  return parsed.ok ? runArchivePlan(runtime, parsed.value) : parsed.result;
}
