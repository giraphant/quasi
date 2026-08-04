import {
  exactKeys,
  isArtifactList,
  isArtifactObservation,
  isRecord,
  observationKey,
  parseLeafRunEnvelope,
  parseStatusEnvelope,
  requestedLeafSlug,
  sparseObservations,
  validAuthors,
  validMaterialSlug,
  validNullableString,
  validString,
  type ArtifactObservation,
  type LeafSeed,
  type QuasiStatusObservation,
  type SparseObservationMap,
  type UserDecision,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";

export interface PaperIdentity {
  slug: string;
  title: string;
  authors: string[];
  year: number;
  doi: string | null;
  oa_url: string | null;
  url: string | null;
  journal: string;
  confidence: "high" | "medium";
}

export interface PaperIntake {
  title?: string;
  doi?: string;
  authors?: string[];
  year?: number;
  journal?: string;
  oa_url?: string;
  url?: string;
}

export type PaperSeed = LeafSeed<PaperIntake, PaperIdentity>;

export interface PaperStatusFacts {
  kind: "paper";
  source: ArtifactObservation;
  prepared: ArtifactObservation[];
  canonical: ArtifactObservation;
}

export type PaperStatusObservation = QuasiStatusObservation<
  "paper",
  PaperStatusFacts
>;

export interface PaperRunInput {
  seed: PaperSeed;
  observations: SparseObservationMap<PaperStatusObservation>;
  options: Readonly<Record<string, unknown>>;
  userDecision: UserDecision | null;
}

export type PaperRunInputResult =
  | { ok: true; value: PaperRunInput }
  | { ok: false; result: MaterialResult };

export const parsePaperIdentity = (
  value: unknown,
): PaperIdentity | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "slug",
      "title",
      "authors",
      "year",
      "doi",
      "oa_url",
      "url",
      "journal",
      "confidence",
    ]) ||
    !validMaterialSlug(value.slug) ||
    !validString(value.title, 1, 500) ||
    !validAuthors(value.authors) ||
    !Number.isInteger(value.year) ||
    (value.year as number) < 1500 ||
    (value.year as number) > 2030 ||
    !validNullableString(value.doi, 300) ||
    !validNullableString(value.oa_url, 2048) ||
    !validNullableString(value.url, 2048) ||
    !validString(value.journal, 1, 500) ||
    !["high", "medium"].includes(value.confidence as string)
  )
    return null;
  return value as unknown as PaperIdentity;
};

const optionalString = (
  value: Record<string, unknown>,
  key: string,
  minLength: number,
  maxLength: number,
): boolean =>
  !Object.hasOwn(value, key) ||
  validString(value[key], minLength, maxLength);

const parsePaperIntake = (value: unknown): PaperIntake | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [], [
      "title",
      "doi",
      "authors",
      "year",
      "journal",
      "oa_url",
      "url",
    ]) ||
    (!Object.hasOwn(value, "title") && !Object.hasOwn(value, "doi")) ||
    !optionalString(value, "title", 1, 500) ||
    !optionalString(value, "doi", 1, 300) ||
    (Object.hasOwn(value, "authors") && !validAuthors(value.authors)) ||
    (Object.hasOwn(value, "year") &&
      (!Number.isInteger(value.year) ||
        (value.year as number) < 1500 ||
        (value.year as number) > 2030)) ||
    !optionalString(value, "journal", 1, 500) ||
    !optionalString(value, "oa_url", 1, 2048) ||
    !optionalString(value, "url", 1, 2048)
  )
    return null;
  return value as PaperIntake;
};

const parsePaperSeed = (value: unknown): PaperSeed | null => {
  if (!isRecord(value)) return null;
  if (
    value.state === "provisional" &&
    exactKeys(value, ["state", "requested_slug", "hints"]) &&
    validMaterialSlug(value.requested_slug)
  ) {
    const hints = parsePaperIntake(value.hints);
    return hints === null
      ? null
      : { state: "provisional", requested_slug: value.requested_slug, hints };
  }
  if (
    value.state === "canonical" &&
    exactKeys(value, ["state", "material_slug", "identity"]) &&
    validMaterialSlug(value.material_slug)
  ) {
    const identity = parsePaperIdentity(value.identity);
    return identity === null
      ? null
      : { state: "canonical", material_slug: value.material_slug, identity };
  }
  return null;
};

export const parsePaperStatusObservation = (
  value: unknown,
): PaperStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "paper");
  if (observation === null) return null;
  const facts = observation.facts;
  if (
    !exactKeys(facts, ["kind", "source", "prepared", "canonical"]) ||
    facts.kind !== "paper" ||
    !isArtifactObservation(facts.source) ||
    !isArtifactList(facts.prepared) ||
    !isArtifactObservation(facts.canonical)
  )
    return null;
  return observation as unknown as PaperStatusObservation;
};

export const paperObservationAdmitsIdentity = (
  observation: PaperStatusObservation,
  identity: PaperIdentity,
): boolean => {
  const diskIdentity = observation.identity;
  return (
    observation.facts.canonical.present &&
    observation.facts.canonical.usable &&
    isRecord(diskIdentity) &&
    diskIdentity.title === identity.title &&
    diskIdentity.year === identity.year &&
    Array.isArray(diskIdentity.authors) &&
    diskIdentity.authors.length === identity.authors.length &&
    diskIdentity.authors.every(
      (author, index) => author === identity.authors[index],
    )
  );
};

export const parsePaperRunInput = (
  raw: unknown,
): PaperRunInputResult => {
  const invalid = (): PaperRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind: "paper",
      slug: requestedLeafSlug(raw),
    }),
  });
  const envelope = parseLeafRunEnvelope(raw);
  if (envelope === null) return invalid();
  const seed = parsePaperSeed(envelope.seed);
  const observation = parsePaperStatusObservation(envelope.observation);
  if (seed === null || observation === null) return invalid();
  const materialSlug =
    seed.state === "provisional" ? seed.requested_slug : seed.material_slug;
  const observations = sparseObservations<PaperStatusObservation>([
    {
      route: { kind: "paper", slug: materialSlug },
      observation,
    },
  ]);
  const bound =
    observations?.get(
      observationKey({ kind: "paper", slug: materialSlug }),
    ) ?? null;
  if (
    observations === null ||
    (seed.state === "canonical" &&
      seed.material_slug !== seed.identity.slug &&
      (bound === null ||
        !paperObservationAdmitsIdentity(bound, seed.identity)))
  )
    return invalid();
  return {
    ok: true,
    value: {
      seed,
      observations,
      options: envelope.options,
      userDecision: envelope.userDecision,
    },
  };
};
