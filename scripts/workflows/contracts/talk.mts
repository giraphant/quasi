import {
  exactKeys,
  isArtifactList,
  isArtifactObservation,
  isRecord,
  observationKey,
  parseStatusEnvelope,
  requestedLeafSlug,
  sparseObservations,
  validMaterialSlug,
  validString,
  type ArtifactObservation,
  type QuasiStatusObservation,
  type SparseObservationMap,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";

export interface TalkIdentity {
  title: string;
  date: string;
  media: string;
}

export interface TalkSeed {
  state: "canonical";
  material_slug: string;
  identity: TalkIdentity;
}

export type TalkEngine = "soniox" | "whisper" | "apple" | "parakeet";

export interface TalkOptions {
  engines: TalkEngine[];
  lang: string;
  prepare_media: boolean;
}

export interface TalkRunInput {
  seed: TalkSeed;
  observations: SparseObservationMap<TalkStatusObservation>;
  options: TalkOptions;
}

export type TalkRunInputResult =
  | { ok: true; value: TalkRunInput }
  | { ok: false; result: MaterialResult };

export interface TalkStatusFacts {
  kind: "talk";
  media: ArtifactObservation[];
  transcripts: ArtifactObservation[];
  canonical: ArtifactObservation;
}

export type TalkStatusObservation = QuasiStatusObservation<
  "talk",
  TalkStatusFacts
>;

const TALK_MEDIA_EXTENSIONS = [
  "mov",
  "mp4",
  "m4v",
  "mkv",
  "webm",
  "m4a",
  "wav",
  "mp3",
  "aac",
  "flac",
  "aiff",
  "aif",
  "ogg",
  "opus",
] as const;

const TALK_ENGINES = ["soniox", "whisper", "apple", "parakeet"] as const;
const TALK_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TALK_LANGUAGE = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;

const validTalkDate = (value: unknown): value is string => {
  if (typeof value !== "string" || !TALK_DATE.test(value)) return false;
  const timestamp = Date.parse(`${value}T00:00:00.000Z`);
  return (
    Number.isFinite(timestamp) &&
    new Date(timestamp).toISOString().slice(0, 10) === value
  );
};

const parseTalkIdentity = (
  value: unknown,
  slug: string,
): TalkIdentity | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["title", "date", "media"]) ||
    !validString(value.title, 1, 500) ||
    !validTalkDate(value.date) ||
    typeof value.media !== "string" ||
    !TALK_MEDIA_EXTENSIONS.some(
      (extension) => value.media === `sources/${slug}.${extension}`,
    )
  )
    return null;
  return value as unknown as TalkIdentity;
};

export const parseTalkSeed = (value: unknown): TalkSeed | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["state", "material_slug", "identity"]) ||
    value.state !== "canonical" ||
    !validMaterialSlug(value.material_slug)
  )
    return null;
  const identity = parseTalkIdentity(value.identity, value.material_slug);
  return identity === null
    ? null
    : { state: "canonical", material_slug: value.material_slug, identity };
};

export const parseTalkOptions = (value: unknown): TalkOptions | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [], ["engines", "lang", "prepare_media"])
  )
    return null;
  const engines = Object.hasOwn(value, "engines")
    ? value.engines
    : ["soniox", "apple", "parakeet"];
  const lang = Object.hasOwn(value, "lang") ? value.lang : "auto";
  const prepareMedia = Object.hasOwn(value, "prepare_media")
    ? value.prepare_media
    : false;
  if (
    !Array.isArray(engines) ||
    engines.length === 0 ||
    engines.some(
      (engine) =>
        typeof engine !== "string" ||
        !TALK_ENGINES.includes(engine as TalkEngine),
    ) ||
    new Set(engines).size !== engines.length ||
    (lang !== "auto" &&
      (typeof lang !== "string" || !TALK_LANGUAGE.test(lang))) ||
    typeof prepareMedia !== "boolean"
  )
    return null;
  return {
    engines: engines as TalkEngine[],
    lang,
    prepare_media: prepareMedia,
  };
};

export const parseTalkStatusObservation = (
  value: unknown,
): TalkStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "talk");
  if (observation === null) return null;
  const facts = observation.facts;
  const mediaPaths = TALK_MEDIA_EXTENSIONS.map(
    (extension) => `sources/${observation.slug}.${extension}`,
  );
  const transcriptRoot = `processing/talks/${observation.slug}/`;
  if (
    !exactKeys(facts, ["kind", "media", "transcripts", "canonical"]) ||
    facts.kind !== "talk" ||
    !isArtifactList(facts.media) ||
    facts.media.length !== mediaPaths.length ||
    facts.media.some(
      (artifact, index) => artifact.path !== mediaPaths[index],
    ) ||
    !isArtifactList(facts.transcripts) ||
    facts.transcripts.some((artifact) => {
      if (!artifact.path.startsWith(transcriptRoot)) return true;
      const child = artifact.path.slice(transcriptRoot.length);
      return (
        child.length === 0 ||
        child.includes("/") ||
        !child.startsWith("transcript.") ||
        child === "transcript.json"
      );
    }) ||
    new Set(facts.transcripts.map((artifact) => artifact.path)).size !==
      facts.transcripts.length ||
    !isArtifactObservation(facts.canonical) ||
    facts.canonical.path !== `vault/talks/${observation.slug}/talk.md`
  )
    return null;
  return observation as unknown as TalkStatusObservation;
};

export const parseTalkRunInput = (raw: unknown): TalkRunInputResult => {
  const invalid = (): TalkRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind: "talk",
      slug: requestedLeafSlug(raw),
    }),
  });
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["seed", "observation", "options"])
  )
    return invalid();
  const seed = parseTalkSeed(raw.seed);
  const observation = parseTalkStatusObservation(raw.observation);
  const options = parseTalkOptions(raw.options);
  if (
    seed === null ||
    observation === null ||
    options === null ||
    observation.slug !== seed.material_slug
  )
    return invalid();
  const observations = sparseObservations<TalkStatusObservation>([
    {
      route: { kind: "talk", slug: seed.material_slug },
      observation,
    },
  ]);
  if (
    observations === null ||
    !observations.has(
      observationKey({ kind: "talk", slug: seed.material_slug }),
    )
  )
    return invalid();
  return { ok: true, value: { seed, observations, options } };
};
