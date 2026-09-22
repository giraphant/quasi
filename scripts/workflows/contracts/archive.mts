import { ARCHIVE_ARTIFACT_CONTRACT } from "../artifact-contracts/generated.mjs";
import {
  exactKeys,
  isRecord,
  isArtifactObservation,
  validMaterialSlug,
  validString,
  type ArtifactObservation,
  type QuasiStatusObservation,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";
import { normalizeWebUrl } from "../shared/web-url.mts";

export const ARCHIVE_KINDS: string[] =
  ARCHIVE_ARTIFACT_CONTRACT.frontmatter.json_schema.properties.kind.enum;

export interface ArchiveIdentity {
  slug: string;
  title: string;
  kind: string;
  url: string;
}

export type ArchiveSeed =
  | { state: "provisional"; url: string }
  | { state: "canonical"; material_slug: string; identity: ArchiveIdentity };

export interface ArchiveOptions {
  topics: string[];
}

export type ArchiveStatusObservation = QuasiStatusObservation<
  "archive",
  { kind: "archive"; canonical: ArtifactObservation; collection: {
    path: string; present: boolean; usable: boolean; revision: string | null;
    source_url: string | null; coverage: string | null;
    files: (ArtifactObservation & {media_type: string; title: string; description: string})[];
  } }
>;

export interface ArchiveRunInput {
  seed: ArchiveSeed;
  observation: ArchiveStatusObservation | null;
  options: ArchiveOptions;
}

export const parseArchiveIdentity = (value: unknown): ArchiveIdentity | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["slug", "title", "kind", "url"]) ||
    !validMaterialSlug(value.slug) ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.slug) ||
    !validString(value.title, 2, 280) ||
    !ARCHIVE_KINDS.includes(value.kind as string) ||
    normalizeWebUrl(value.url) === null
  ) return null;
  return value as unknown as ArchiveIdentity;
};

export const parseArchiveSeed = (value: unknown): ArchiveSeed | null => {
  if (!isRecord(value)) return null;
  if (
    value.state === "provisional" &&
    exactKeys(value, ["state", "url"]) &&
    normalizeWebUrl(value.url) !== null
  ) return value as unknown as ArchiveSeed;
  const identity = parseArchiveIdentity(value.identity);
  if (
    value.state !== "canonical" ||
    !exactKeys(value, ["state", "material_slug", "identity"]) ||
    identity === null || value.material_slug !== identity.slug
  ) return null;
  return value as unknown as ArchiveSeed;
};

export const parseArchiveStatusObservation = (
  value: unknown,
): ArchiveStatusObservation | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["schema_version", "kind", "slug", "identity", "facts"]) ||
    value.schema_version !== "quasi.status/0.2" ||
    value.kind !== "archive" ||
    !validMaterialSlug(value.slug) ||
    !isRecord(value.facts) ||
    !exactKeys(value.facts, ["kind", "canonical", "collection"]) ||
    value.facts.kind !== "archive" ||
    !isArtifactObservation(value.facts.canonical) ||
    value.facts.canonical.path !== `vault/archives/${value.slug}/archive.md`
  ) return null;
  const collection = value.facts.collection;
  if (!isRecord(collection) || !exactKeys(collection, ["path", "present", "usable", "revision", "source_url", "files", "coverage"]) ||
      !isArtifactObservation({path: collection.path, present: collection.present, usable: collection.usable}) ||
      collection.path !== `vault/archives/${value.slug}/manifest.yaml` ||
      !(collection.revision === null || (typeof collection.revision === "string" && /^[0-9a-f]{64}$/.test(collection.revision))) ||
      !(collection.source_url === null || normalizeWebUrl(collection.source_url) !== null) ||
      !(collection.coverage === null || typeof collection.coverage === "string") ||
      !Array.isArray(collection.files) || !collection.files.every(file =>
        isRecord(file) && exactKeys(file, ["path", "present", "usable", "media_type", "title", "description"]) &&
        isArtifactObservation({path: file.path, present: file.present, usable: file.usable}) &&
        typeof file.media_type === "string" && typeof file.path === "string" &&
        typeof file.title === "string" && file.title.trim().length > 0 &&
        typeof file.description === "string" && file.description.trim().length > 0 &&
        file.path.startsWith(`vault/archives/${value.slug}/originals/`) &&
        /^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+$/.test(file.path.slice(`vault/archives/${value.slug}/originals/`.length))) ||
      new Set(collection.files.map(file => file.path)).size !== collection.files.length ||
      (collection.usable && (!collection.source_url || !collection.revision || collection.files.some(file => !file.usable)))) return null;
  if (value.facts.canonical.usable) {
    const identity = value.identity;
    if (
      !isRecord(identity) ||
      !exactKeys(identity, ["type", "title", "kind", "created"],
        ["creator", "date", "source", "url", "themes", "topics", "rating"]) ||
      identity.type !== "archive" ||
      !validString(identity.title, 2, 280) ||
      !ARCHIVE_KINDS.includes(identity.kind as string) ||
      !validString(identity.created, 10, 10) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(identity.created) ||
      ["creator", "themes", "topics"].some(key =>
        identity[key] !== undefined &&
        (!Array.isArray(identity[key]) || !identity[key].every(x => typeof x === "string")))
    ) return null;
  } else if (value.identity !== null) return null;
  return value as unknown as ArchiveStatusObservation;
};

export const parseArchiveRunInput = (
  raw: unknown,
): { ok: true; value: ArchiveRunInput } | { ok: false; result: MaterialResult } => {
  const invalid = () => ({
    ok: false as const,
    result: invalidMaterialInputResult({ kind: "archive", slug: null }),
  });
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["seed", "observation", "options"]) ||
    !isRecord(raw.options) ||
    !exactKeys(raw.options, [], ["topics"])
  ) return invalid();
  const topics = raw.options.topics ?? [];
  if (
    !Array.isArray(topics) || !topics.every(validMaterialSlug) ||
    new Set(topics).size !== topics.length
  ) return invalid();
  const seed = parseArchiveSeed(raw.seed);
  if (seed === null) return invalid();
  if (seed.state === "provisional") {
    if (raw.observation !== null) return invalid();
    return { ok: true, value: { seed, observation: null, options: { topics } } };
  }
  const observation = parseArchiveStatusObservation(raw.observation);
  if (observation === null || observation.slug !== seed.material_slug) return invalid();
  return { ok: true, value: { seed, observation, options: { topics } } };
};
