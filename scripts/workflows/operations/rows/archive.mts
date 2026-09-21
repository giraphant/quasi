import { ARCHIVE_ARTIFACT_CONTRACT, type OperationRow } from "../../artifact-contracts/generated.mjs";
import { ARCHIVE_KINDS, parseArchiveIdentity } from "../../contracts/archive.mts";
import { makeAuditRow } from "../shared.mts";

export const archiveOperationRows: OperationRow[] = [
  {
    operation: "archive.identify",
    refs: c => c,
    payloadProperties: () => ({ required: ["identity"], properties: {identity: {
      type: "object", additionalProperties: false, required: ["slug", "title", "kind", "url"],
      properties: {
        slug: {type: "string", maxLength: 80, pattern: "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
        title: {type: "string", minLength: 2, maxLength: 280},
        kind: {type: "string", enum: ARCHIVE_KINDS},
        url: {type: "string", minLength: 8, maxLength: 2048},
      },
    }}}),
    complete: r => parseArchiveIdentity(r.identity) !== null,
    envelope: (_c, r) => ({
      schema_version: "quasi.stage.request/0.2", operation: "archive.identify", stage: "Search", effect: "readonly",
      material_key: r.materialKey, goal: "Identify one archival object at the exact URL and resolve its existing Archive owner.",
      source_url: r.url, artifact_contract: ARCHIVE_ARTIFACT_CONTRACT,
      capabilities: ["WebFetch only source_url", "quasi-helpers vault resolve --items-json with kind=archive, candidate slug and source_url"],
      scope: "Return the resolver's unique existing owner identity, or the unoccupied candidate slug. Never return a conflicting or unsafe route. Do not write or follow links to additional objects. Preserve source_url as identity.url.",
    }),
  },
  {
    operation: "archive.collect",
    refs: c => c,
    writeTargets: r => [{scope: "exact", path: r.output}],
    payloadProperties: r => ({required: ["output_path", "topics"], properties: {
      output_path: {const: r.output}, topics: {const: r.topics},
    }}),
    complete: () => true,
    envelope: (_c, r) => ({
      schema_version: "quasi.stage.request/0.2", operation: "archive.collect", stage: "Acquire", effect: "writer",
      material_key: r.materialKey, goal: "Establish the exact Archive record with honest source coverage and merge the requested Topic membership.",
      identity: r.identity, topics: r.topics, created_date: r.createdDate,
      exact_output: r.output, output_observation: r.outputObservation,
      mode: r.mode, diagnostics: r.diagnostics, expected_frontmatter: r.expectedFrontmatter ?? null,
      artifact_contract: ARCHIVE_ARTIFACT_CONTRACT,
      capabilities: ["Read, Write or Edit only exact_output", "WebFetch only identity.url"],
      scope: "Preserve existing identity, created date, metadata and user prose; membership-only updates merge topics without refetching or rewriting content. No attachment layout or Webpage object is created. New records state exactly what was read or only linked; inaccessible source contents must never be invented.",
    }),
  },
  makeAuditRow({operation: "archive.audit", refs: c => c, targetRole: "canonical", targetScope: "exact", exactPaths: true}),
];
