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
import {
  parseOcrGenerationObservation,
  type OcrGenerationObservation,
} from "./ocr-generation.mts";

const SHA256 = /^[0-9a-f]{64}$/;

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

export interface PaperOwnerConfirmation {
  operation: "material.search";
  identity_slug: string;
  owner_slug: string;
}

export interface PaperSourceCandidate {
  format: "pdf" | "txt";
  path: string;
  sha256: string;
  size: number;
}

export interface PaperSourceDecisionValue {
  candidates_fingerprint: string;
  source_path: string;
}

export interface PaperSourceGate {
  kind: "paper_source";
  operation: "paper.prepare";
  material_key: string;
  question: string;
  candidates: PaperSourceCandidate[];
  candidates_fingerprint: string;
}

type BasePaperSeed = LeafSeed<PaperIntake, PaperIdentity>;

export type PaperSeed =
  | BasePaperSeed
  | {
      state: "canonical";
      material_slug: string;
      identity: PaperIdentity;
      owner_confirmation: PaperOwnerConfirmation;
    };

export interface PaperStatusFacts {
  kind: "paper";
  sources: Array<{
    format: "pdf" | "txt";
    artifact: ArtifactObservation;
    candidate: PaperSourceCandidate | null;
  }>;
  source_candidates_fingerprint: string;
  prepared: ArtifactObservation[];
  legacy_recovery: {
    pdf: ArtifactObservation;
    text: ArtifactObservation;
  };
  ocr_generation: OcrGenerationObservation | null;
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

const parsePaperOwnerConfirmation = (
  value: unknown,
): PaperOwnerConfirmation | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["operation", "identity_slug", "owner_slug"]) ||
    value.operation !== "material.search" ||
    !validMaterialSlug(value.identity_slug) ||
    !validMaterialSlug(value.owner_slug) ||
    value.identity_slug === value.owner_slug
  )
    return null;
  return value as unknown as PaperOwnerConfirmation;
};

export const parsePaperSeed = (value: unknown): PaperSeed | null => {
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
    exactKeys(
      value,
      ["state", "material_slug", "identity"],
      ["owner_confirmation"],
    ) &&
    validMaterialSlug(value.material_slug)
  ) {
    const identity = parsePaperIdentity(value.identity);
    if (identity === null) return null;
    if (!Object.hasOwn(value, "owner_confirmation"))
      return { state: "canonical", material_slug: value.material_slug, identity };
    const ownerConfirmation = parsePaperOwnerConfirmation(
      value.owner_confirmation,
    );
    if (
      ownerConfirmation === null ||
      ownerConfirmation.identity_slug !== identity.slug ||
      ownerConfirmation.owner_slug !== value.material_slug
    )
      return null;
    return {
      state: "canonical",
      material_slug: value.material_slug,
      identity,
      owner_confirmation: ownerConfirmation,
    };
  }
  return null;
};

export const validSelectablePaperSource = (
  path: string,
  slug: string,
): boolean =>
  [`sources/${slug}.pdf`, `sources/${slug}.txt`].includes(path);

export const parsePaperSourceCandidate = (
  value: unknown,
): PaperSourceCandidate | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["format", "path", "sha256", "size"]) ||
    !["pdf", "txt"].includes(value.format as string) ||
    typeof value.path !== "string" ||
    typeof value.sha256 !== "string" ||
    !SHA256.test(value.sha256) ||
    !Number.isInteger(value.size) ||
    (value.size as number) < 1
  )
    return null;
  return value as unknown as PaperSourceCandidate;
};

export const parsePaperSourceDecisionValue = (
  value: unknown,
): PaperSourceDecisionValue | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["candidates_fingerprint", "source_path"]) ||
    typeof value.candidates_fingerprint !== "string" ||
    !SHA256.test(value.candidates_fingerprint) ||
    typeof value.source_path !== "string" ||
    value.source_path.length === 0
  )
    return null;
  return value as unknown as PaperSourceDecisionValue;
};

export const parsePaperStatusObservation = (
  value: unknown,
): PaperStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "paper");
  if (observation === null) return null;
  const facts = observation.facts;
  const slug = observation.slug;
  const expectedPrepared = [
    `processing/papers/${slug}/source.txt`,
    `processing/papers/${slug}/ocr.txt`,
  ];
  const expectedSources = [
    { format: "pdf", path: `sources/${slug}.pdf` },
    { format: "txt", path: `sources/${slug}.txt` },
  ];
  if (
    !exactKeys(facts, [
      "kind",
      "sources",
      "source_candidates_fingerprint",
      "prepared",
      "legacy_recovery",
      "ocr_generation",
      "canonical",
    ]) ||
    facts.kind !== "paper" ||
    typeof facts.source_candidates_fingerprint !== "string" ||
    !SHA256.test(facts.source_candidates_fingerprint) ||
    !Array.isArray(facts.sources) ||
    facts.sources.length !== expectedSources.length ||
    !facts.sources.every((item, index) => {
      if (
        !isRecord(item) ||
        !exactKeys(item, ["format", "artifact", "candidate"]) ||
        item.format !== expectedSources[index]!.format ||
        !isArtifactObservation(item.artifact) ||
        item.artifact.path !== expectedSources[index]!.path
      )
        return false;
      const candidate = parsePaperSourceCandidate(item.candidate);
      return item.artifact.usable
        ? candidate !== null &&
            candidate.format === item.format &&
            candidate.path === item.artifact.path
        : item.candidate === null;
    }) ||
    !isArtifactList(facts.prepared) ||
    facts.prepared.length !== expectedPrepared.length ||
    !facts.prepared.every(
      (artifact, index) => artifact.path === expectedPrepared[index],
    ) ||
    !isRecord(facts.legacy_recovery) ||
    !exactKeys(facts.legacy_recovery, ["pdf", "text"]) ||
    !isArtifactObservation(facts.legacy_recovery.pdf) ||
    facts.legacy_recovery.pdf.path !==
      `processing/papers/${slug}/ocr.pdf` ||
    !isArtifactObservation(facts.legacy_recovery.text) ||
    facts.legacy_recovery.text.path !==
      `processing/papers/${slug}/ocr.txt` ||
    !isArtifactObservation(facts.canonical) ||
    facts.canonical.path !== `vault/papers/${slug}.md`
  )
    return null;

  const firstSource = facts.sources[0] as Record<string, unknown>;
  const pdfCandidate = parsePaperSourceCandidate(firstSource.candidate);
  if (pdfCandidate === null) {
    if (facts.ocr_generation !== null) return null;
  } else if (
    pdfCandidate.format !== "pdf" ||
    parseOcrGenerationObservation(facts.ocr_generation, {
      kind: "paper",
      slug,
      source: pdfCandidate,
    }) === null
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

const validPaperDiskIdentity = (value: unknown): boolean =>
  isRecord(value) &&
  validString(value.title, 1, 500) &&
  validAuthors(value.authors) &&
  Number.isInteger(value.year) &&
  (value.year as number) >= 1500 &&
  (value.year as number) <= 2030;

export const paperObservationAdmitsOwnerContinuation = (
  observation: PaperStatusObservation,
  seed: Extract<PaperSeed, { owner_confirmation: PaperOwnerConfirmation }>,
): boolean =>
  seed.material_slug === seed.owner_confirmation.owner_slug &&
  seed.identity.slug === seed.owner_confirmation.identity_slug &&
  seed.material_slug !== seed.identity.slug &&
  observation.slug === seed.material_slug &&
  observation.facts.canonical.present &&
  observation.facts.canonical.usable &&
  validPaperDiskIdentity(observation.identity);

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
  if (envelope === null || !exactKeys(envelope.options, [])) return invalid();
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
  const ownerSeed =
    seed.state === "canonical" && "owner_confirmation" in seed
      ? seed
      : null;
  if (
    observations === null ||
    (seed.state === "canonical" &&
      seed.material_slug !== seed.identity.slug &&
      (bound === null ||
        (!paperObservationAdmitsIdentity(bound, seed.identity) &&
          (ownerSeed === null ||
            !paperObservationAdmitsOwnerContinuation(bound, ownerSeed)))))
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
