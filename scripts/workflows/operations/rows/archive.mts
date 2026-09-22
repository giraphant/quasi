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
      capabilities: ["quasi-archive inspect --url source_url", "WebFetch only source_url", "quasi-helpers vault resolve --items-json with kind=archive, candidate slug and source_url"],
      scope: "Return the resolver's unique existing owner identity, or the unoccupied candidate slug. Never return a conflicting or unsafe route. Do not write or follow links to additional objects. Preserve source_url as identity.url.",
    }),
  },
  {
    operation: "archive.collect",
    refs: c => c,
    writeTargets: r => [{scope: "exact", path: r.output}, {scope: "exact", path: r.manifest}, {scope: "subtree", path: r.originals}],
    payloadProperties: r => ({required: ["output_path", "topics"], properties: {
      output_path: {const: r.output}, topics: {const: r.topics},
    }}),
    complete: () => true,
    envelope: (_c, r) => ({
      schema_version: "quasi.stage.request/0.2", operation: "archive.collect", stage: "Acquire", effect: "writer",
      material_key: r.materialKey, goal: "Establish the exact Archive record with honest source coverage and merge the requested Topic membership.",
      identity: r.identity, topics: r.topics,
      exact_output: r.output, exact_manifest: r.manifest, originals_directory: r.originals,
      output_observation: r.outputObservation, collection_observation: r.collectionObservation,
      mode: r.mode, diagnostics: r.diagnostics, expected_frontmatter: r.expectedFrontmatter ?? null,
      artifact_contract: ARCHIVE_ARTIFACT_CONTRACT,
      capabilities: ["Read exact_output, exact_manifest and observed original paths",
        "quasi-archive inspect --url identity.url (or an exact linked asset selected from that object)",
        "WebFetch identity.url for verified source context",
        "Write one uniquely named request JSON under .quasi/temp/",
        "quasi-archive collect --request-file REQUEST_JSON"],
      request_contract: {
        identity: r.identity, topics: r.topics,
        expected_revision: r.collectionObservation?.revision,
        files: "Ordered selected originals: [{name: descriptive-kebab-case.ext, url, method: download|webarchive, title: nonblank readable title, description: nonblank content/scope description, source?: {url,title?}}]. For method=webarchive, name must end in .webarchive (not .html); download keeps the actual file format extension. Membership mode uses [].",
        metadata: "Verified creator (string array), date (full publication YYYY-MM-DD only), source (platform/publisher). Omit unknown fields. Inspect publication vs modification evidence; explain absent or partial dates in body. Membership mode uses {}. Existing nonempty values are preserved; conflicting changes stop before publication.",
        body: "New archive.md with H1 and substantive sections per artifact_contract (overview, provenance/coverage, content summary with locators). Explain date evidence or absence. No per-file annotations required. Existing body is preserved by the helper. Membership mode uses an empty string.",
        coverage: "Optional plain-language scope and missing material; empty string is valid. No completeness quota.",
      },
      scope: "The helper alone publishes originals, manifest.yaml and archive.md, preserving existing prose and merging topics under a writer lock with fresh revision checks. Select files belonging to this one object; no recursive crawling or unrelated objects. Common source is inherited; per-file source overrides are exceptional. Use descriptive stable filenames, optionally numbered. No extraction, OCR, transcription or transcoding. Download failures are recorded as coverage, including link-only collection. An ambiguous publication stops without retry.",
    }),
  },
  makeAuditRow({operation: "archive.audit", refs: c => c, targetRole: "canonical", targetScope: "exact", exactPaths: true}),
];
