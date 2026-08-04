import {
  PIPELINE,
  type KindDefinition,
  type OperationName,
  type WorkflowContext,
} from "../artifact-contracts/generated.mjs";
import {
  invalidMaterialInputResult,
  type MaterialResult,
  type ObservationKey,
  type ObservationRoute,
  type SparseObservationMap,
} from "./material-result.mts";

const MATERIAL_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const LANGUAGE_TAG = /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$/;
const SHA256 = /^[0-9a-f]{64}$/;

const MATERIAL_OPERATIONS = new Set<OperationName>(
  Object.values(PIPELINE).flatMap((definition: KindDefinition) =>
    definition.stages.map((stage) => stage.operation),
  ),
);

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

export interface BookIdentity {
  slug: string;
  title: string;
  authors: string[];
  year: number;
  isbn: string | null;
  publisher: string;
  category: "monograph" | "edited-volume" | "handbook" | "other";
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

export interface BookIntake {
  title?: string;
  isbn?: string;
  authors?: string[];
  year?: number;
  publisher?: string;
  category?: BookIdentity["category"];
}

export type LeafSeed<TIntake, TIdentity> =
  | { state: "provisional"; requested_slug: string; hints: TIntake }
  | { state: "canonical"; material_slug: string; identity: TIdentity };

export interface TranslationCandidate {
  path: string;
  sha256: string;
  size: number;
  pages: number;
}

export interface ArtifactObservation {
  path: string;
  present: boolean;
  usable: boolean;
}

export interface TopicOutlineProjection {
  subquestions: Array<{
    id: string;
    question: string;
    coverage: "gap" | "thin" | "covered" | "saturated";
    channel: "academic" | "web" | "mixed";
    theory_used: number;
  }>;
  members: Array<{
    kind: "paper" | "book" | "talk";
    slug: string;
    subq: string;
    role: "evidence" | "theory" | "method" | "context" | null;
    artifact: ArtifactObservation;
  }>;
  cards: Array<{
    slug: string;
    subq: string;
    title: string | null;
    artifact: ArtifactObservation;
  }>;
}

interface QuasiStatusObservationBase {
  schema_version: "quasi.status/0.2";
  slug: string;
  identity: WorkflowContext | null;
}

export type QuasiStatusObservation =
  | (QuasiStatusObservationBase & {
      kind: "paper";
      facts: {
        kind: "paper";
        source: ArtifactObservation;
        prepared: ArtifactObservation[];
        canonical: ArtifactObservation;
      };
    })
  | (QuasiStatusObservationBase & {
      kind: "book";
      facts: {
        kind: "book";
        sources: Array<{
          format: "epub" | "pdf";
          artifact: ArtifactObservation;
        }>;
        manifest: ArtifactObservation & { valid: boolean };
        chapters: Array<{
          slot: string;
          title: string;
          filename: string;
          slug: string;
          word_count: number;
          start_page: number | null;
          end_page: number | null;
          input: ArtifactObservation;
          output: ArtifactObservation;
        }>;
        overview: ArtifactObservation;
      };
    })
  | (QuasiStatusObservationBase & {
      kind: "talk";
      facts: {
        kind: "talk";
        media: ArtifactObservation[];
        transcripts: ArtifactObservation[];
        canonical: ArtifactObservation;
      };
    })
  | (QuasiStatusObservationBase & {
      kind: "translation";
      facts: {
        kind: "translation";
        target_language: string;
        source: ArtifactObservation;
        output: ArtifactObservation;
        manifest: ArtifactObservation;
      };
    })
  | (QuasiStatusObservationBase & {
      kind: "author";
      facts: {
        kind: "author";
        canonical: ArtifactObservation;
      };
    })
  | (QuasiStatusObservationBase & {
      kind: "topic";
      facts: {
        kind: "topic";
        outline: ArtifactObservation & {
          valid: boolean;
          projection: TopicOutlineProjection | null;
        };
        overview: ArtifactObservation;
        resources: ArtifactObservation;
      };
    });

export interface UserDecision {
  material_key: string;
  operation: OperationName;
  value: unknown;
}

export interface TranslationSourceDecisionValue {
  candidates_fingerprint: string;
  source_path: string;
}

export interface ParsedLeafMaterialInput<
  TIntake extends PaperIntake | BookIntake,
  TIdentity extends PaperIdentity | BookIdentity,
> {
  seed: LeafSeed<TIntake, TIdentity>;
  observations: SparseObservationMap;
  options: Readonly<Record<string, unknown>>;
  userDecision: UserDecision | null;
}

export type ParsedLeafMaterialInputResult =
  | {
      ok: true;
      value: ParsedLeafMaterialInput<
        PaperIntake | BookIntake,
        PaperIdentity | BookIdentity
      >;
    }
  | { ok: false; result: MaterialResult };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const exactKeys = (
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean => {
  const allowed = new Set([...required, ...optional]);
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => allowed.has(key))
  );
};

const validString = (
  value: unknown,
  minLength: number,
  maxLength: number,
): value is string =>
  typeof value === "string" &&
  value.length >= minLength &&
  value.length <= maxLength;

const validNullableString = (
  value: unknown,
  maxLength: number,
): value is string | null =>
  value === null || validString(value, 0, maxLength);

const validAuthors = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.length >= 1 &&
  value.length <= 32 &&
  value.every((item) => validString(item, 1, 200));

export const validMaterialSlug = (value: unknown): value is string =>
  typeof value === "string" && MATERIAL_SLUG.test(value);

export function normalizeLanguage(value: unknown): string | null {
  if (typeof value !== "string" || !LANGUAGE_TAG.test(value)) return null;
  return value
    .split("-")
    .map((part, index) => {
      if (index === 0) return part.toLowerCase();
      if (/^[A-Za-z]{2}$/.test(part)) return part.toUpperCase();
      return part.toLowerCase();
    })
    .join("-");
}

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

export const parseBookIdentity = (
  value: unknown,
): BookIdentity | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "slug",
      "title",
      "authors",
      "year",
      "isbn",
      "publisher",
      "category",
      "confidence",
    ]) ||
    !validMaterialSlug(value.slug) ||
    !validString(value.title, 1, 500) ||
    !validAuthors(value.authors) ||
    !Number.isInteger(value.year) ||
    (value.year as number) < 1500 ||
    (value.year as number) > 2030 ||
    !validNullableString(value.isbn, 100) ||
    !validString(value.publisher, 2, 500) ||
    !["monograph", "edited-volume", "handbook", "other"].includes(
      value.category as string,
    ) ||
    !["high", "medium"].includes(value.confidence as string)
  )
    return null;
  return value as unknown as BookIdentity;
};

const optionalString = (
  value: Record<string, unknown>,
  key: string,
  minLength: number,
  maxLength: number,
): boolean =>
  !Object.hasOwn(value, key) || validString(value[key], minLength, maxLength);

const optionalAuthors = (
  value: Record<string, unknown>,
): boolean => !Object.hasOwn(value, "authors") || validAuthors(value.authors);

const optionalYear = (value: Record<string, unknown>): boolean =>
  !Object.hasOwn(value, "year") ||
  (Number.isInteger(value.year) &&
    (value.year as number) >= 1500 &&
    (value.year as number) <= 2030);

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
    !optionalAuthors(value) ||
    !optionalYear(value) ||
    !optionalString(value, "journal", 1, 500) ||
    !optionalString(value, "oa_url", 1, 2048) ||
    !optionalString(value, "url", 1, 2048)
  )
    return null;
  return value as PaperIntake;
};

const parseBookIntake = (value: unknown): BookIntake | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [], [
      "title",
      "isbn",
      "authors",
      "year",
      "publisher",
      "category",
    ]) ||
    (!Object.hasOwn(value, "title") && !Object.hasOwn(value, "isbn")) ||
    !optionalString(value, "title", 1, 500) ||
    !optionalString(value, "isbn", 1, 100) ||
    !optionalAuthors(value) ||
    !optionalYear(value) ||
    !optionalString(value, "publisher", 2, 500) ||
    (Object.hasOwn(value, "category") &&
      !["monograph", "edited-volume", "handbook", "other"].includes(
        value.category as string,
      ))
  )
    return null;
  return value as BookIntake;
};

const parseLeafSeed = (
  value: unknown,
  kind: "paper" | "book",
):
  | LeafSeed<PaperIntake, PaperIdentity>
  | LeafSeed<BookIntake, BookIdentity>
  | null => {
  if (!isRecord(value)) return null;
  if (
    value.state === "provisional" &&
    exactKeys(value, ["state", "requested_slug", "hints"]) &&
    validMaterialSlug(value.requested_slug)
  ) {
    if (kind === "paper") {
      const hints = parsePaperIntake(value.hints);
      return hints === null
        ? null
        : { state: "provisional", requested_slug: value.requested_slug, hints };
    }
    const hints = parseBookIntake(value.hints);
    return hints === null
      ? null
      : { state: "provisional", requested_slug: value.requested_slug, hints };
  }
  if (
    value.state === "canonical" &&
    exactKeys(value, ["state", "material_slug", "identity"]) &&
    validMaterialSlug(value.material_slug)
  ) {
    if (kind === "paper") {
      const identity = parsePaperIdentity(value.identity);
      return identity === null
        ? null
        : { state: "canonical", material_slug: value.material_slug, identity };
    }
    const identity = parseBookIdentity(value.identity);
    return identity === null
      ? null
      : { state: "canonical", material_slug: value.material_slug, identity };
  }
  return null;
};

export const parseTranslationCandidate = (
  value: unknown,
): TranslationCandidate | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["path", "sha256", "size", "pages"]) ||
    typeof value.path !== "string" ||
    typeof value.sha256 !== "string" ||
    !SHA256.test(value.sha256) ||
    !Number.isInteger(value.size) ||
    (value.size as number) < 1 ||
    !Number.isInteger(value.pages) ||
    (value.pages as number) < 1
  )
    return null;
  return value as unknown as TranslationCandidate;
};

const isArtifactObservation = (
  value: unknown,
): value is ArtifactObservation =>
  isRecord(value) &&
  exactKeys(value, ["path", "present", "usable"]) &&
  typeof value.path === "string" &&
  typeof value.present === "boolean" &&
  typeof value.usable === "boolean";

const isArtifactList = (value: unknown): value is ArtifactObservation[] =>
  Array.isArray(value) && value.every(isArtifactObservation);

const isTopicProjection = (
  value: unknown,
): value is TopicOutlineProjection =>
  isRecord(value) &&
  exactKeys(value, ["subquestions", "members", "cards"]) &&
  Array.isArray(value.subquestions) &&
  value.subquestions.every(
    (item) =>
      isRecord(item) &&
      exactKeys(item, [
        "id",
        "question",
        "coverage",
        "channel",
        "theory_used",
      ]) &&
      typeof item.id === "string" &&
      typeof item.question === "string" &&
      ["gap", "thin", "covered", "saturated"].includes(
        item.coverage as string,
      ) &&
      ["academic", "web", "mixed"].includes(item.channel as string) &&
      Number.isInteger(item.theory_used),
  ) &&
  Array.isArray(value.members) &&
  value.members.every(
    (item) =>
      isRecord(item) &&
      exactKeys(item, ["kind", "slug", "subq", "role", "artifact"]) &&
      ["paper", "book", "talk"].includes(item.kind as string) &&
      validMaterialSlug(item.slug) &&
      typeof item.subq === "string" &&
      (item.role === null ||
        ["evidence", "theory", "method", "context"].includes(
          item.role as string,
        )) &&
      isArtifactObservation(item.artifact),
  ) &&
  Array.isArray(value.cards) &&
  value.cards.every(
    (item) =>
      isRecord(item) &&
      exactKeys(item, ["slug", "subq", "title", "artifact"]) &&
      validMaterialSlug(item.slug) &&
      typeof item.subq === "string" &&
      (item.title === null || typeof item.title === "string") &&
      isArtifactObservation(item.artifact),
  );

const isStatusFacts = (value: unknown, kind: string): boolean => {
  if (!isRecord(value) || value.kind !== kind) return false;
  if (kind === "paper")
    return (
      exactKeys(value, ["kind", "source", "prepared", "canonical"]) &&
      isArtifactObservation(value.source) &&
      isArtifactList(value.prepared) &&
      isArtifactObservation(value.canonical)
    );
  if (kind === "book")
    return (
      exactKeys(value, [
        "kind",
        "sources",
        "manifest",
        "chapters",
        "overview",
      ]) &&
      Array.isArray(value.sources) &&
      value.sources.every(
        (item) =>
          isRecord(item) &&
          exactKeys(item, ["format", "artifact"]) &&
          ["epub", "pdf"].includes(item.format as string) &&
          isArtifactObservation(item.artifact),
      ) &&
      isRecord(value.manifest) &&
      exactKeys(value.manifest, ["path", "present", "usable", "valid"]) &&
      isArtifactObservation({
        path: value.manifest.path,
        present: value.manifest.present,
        usable: value.manifest.usable,
      }) &&
      typeof value.manifest.valid === "boolean" &&
      Array.isArray(value.chapters) &&
      value.chapters.every(
        (chapter) =>
          isRecord(chapter) &&
          exactKeys(chapter, [
            "slot",
            "title",
            "filename",
            "slug",
            "word_count",
            "start_page",
            "end_page",
            "input",
            "output",
          ]) &&
          typeof chapter.slot === "string" &&
          typeof chapter.title === "string" &&
          typeof chapter.filename === "string" &&
          validMaterialSlug(chapter.slug) &&
          Number.isInteger(chapter.word_count) &&
          (chapter.start_page === null ||
            Number.isInteger(chapter.start_page)) &&
          (chapter.end_page === null || Number.isInteger(chapter.end_page)) &&
          isArtifactObservation(chapter.input) &&
          isArtifactObservation(chapter.output),
      ) &&
      isArtifactObservation(value.overview)
    );
  if (kind === "talk")
    return (
      exactKeys(value, ["kind", "media", "transcripts", "canonical"]) &&
      isArtifactList(value.media) &&
      isArtifactList(value.transcripts) &&
      isArtifactObservation(value.canonical)
    );
  if (kind === "translation")
    return (
      exactKeys(value, [
        "kind",
        "target_language",
        "source",
        "output",
        "manifest",
      ]) &&
      normalizeLanguage(value.target_language) === value.target_language &&
      isArtifactObservation(value.source) &&
      isArtifactObservation(value.output) &&
      isArtifactObservation(value.manifest)
    );
  if (kind === "author")
    return (
      exactKeys(value, ["kind", "canonical"]) &&
      isArtifactObservation(value.canonical)
    );
  if (kind === "topic")
    return (
      exactKeys(value, ["kind", "outline", "overview", "resources"]) &&
      isRecord(value.outline) &&
      exactKeys(value.outline, [
        "path",
        "present",
        "usable",
        "valid",
        "projection",
      ]) &&
      isArtifactObservation({
        path: value.outline.path,
        present: value.outline.present,
        usable: value.outline.usable,
      }) &&
      typeof value.outline.valid === "boolean" &&
      (value.outline.projection === null ||
        isTopicProjection(value.outline.projection)) &&
      value.outline.valid === (value.outline.projection !== null) &&
      isArtifactObservation(value.overview) &&
      isArtifactObservation(value.resources)
    );
  return false;
};

const parseStatusObservation = (
  value: unknown,
): QuasiStatusObservation | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["schema_version", "kind", "slug", "identity", "facts"]) ||
    value.schema_version !== "quasi.status/0.2" ||
    !["paper", "book", "talk", "translation", "author", "topic"].includes(
      value.kind as string,
    ) ||
    !validMaterialSlug(value.slug) ||
    (value.identity !== null && !isRecord(value.identity)) ||
    !isStatusFacts(value.facts, value.kind as string)
  )
    return null;
  return value as unknown as QuasiStatusObservation;
};

const parseObservationRoute = (
  value: unknown,
): ObservationRoute | null => {
  if (!isRecord(value) || !validMaterialSlug(value.slug)) return null;
  if (
    ["paper", "book", "talk"].includes(value.kind as string) &&
    exactKeys(value, ["kind", "slug"])
  )
    return value as unknown as ObservationRoute;
  if (
    value.kind === "translation" &&
    exactKeys(value, ["kind", "slug", "target_language"])
  ) {
    const target = normalizeLanguage(value.target_language);
    if (target !== null && target === value.target_language)
      return value as unknown as ObservationRoute;
  }
  return null;
};

export const observationKey = (
  route: ObservationRoute,
): ObservationKey =>
  route.kind === "translation"
    ? `translation:paper:${route.slug}:${route.target_language}`
    : `${route.kind}:${route.slug}`;

export const sparseObservations = (
  entries: unknown,
): SparseObservationMap | null => {
  if (!Array.isArray(entries)) return null;
  const observations = new Map<ObservationKey, QuasiStatusObservation>();
  for (const rawEntry of entries) {
    if (
      !isRecord(rawEntry) ||
      !exactKeys(rawEntry, ["route", "observation"])
    )
      return null;
    const route = parseObservationRoute(rawEntry.route);
    const observation = parseStatusObservation(rawEntry.observation);
    const observedTarget =
      observation?.kind === "translation"
        ? observation.facts.target_language
        : null;
    if (
      route === null ||
      observation === null ||
      observation.kind !== route.kind ||
      observation.slug !== route.slug ||
      (route.kind === "translation" &&
        observedTarget !== route.target_language)
    )
      return null;
    const key = observationKey(route);
    if (observations.has(key)) return null;
    observations.set(key, observation);
  }
  return observations;
};

export const parseOptions = (
  value: unknown,
): Readonly<Record<string, unknown>> | null =>
  isRecord(value) ? value : null;

export const parseUserDecision = (
  value: unknown,
): UserDecision | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["material_key", "operation", "value"]) ||
    !validString(value.material_key, 1, 512) ||
    typeof value.operation !== "string" ||
    !MATERIAL_OPERATIONS.has(value.operation as OperationName)
  )
    return null;
  return value as unknown as UserDecision;
};

export const parseTranslationSourceDecisionValue = (
  value: unknown,
): TranslationSourceDecisionValue | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["candidates_fingerprint", "source_path"]) ||
    typeof value.candidates_fingerprint !== "string" ||
    !SHA256.test(value.candidates_fingerprint) ||
    typeof value.source_path !== "string" ||
    value.source_path.length === 0
  )
    return null;
  return value as unknown as TranslationSourceDecisionValue;
};

export const decisionForOperation = (
  decision: UserDecision | null,
  materialKey: string,
  operation: OperationName,
  durableOutputComplete: boolean,
): unknown | null =>
  !durableOutputComplete &&
  decision?.material_key === materialKey &&
  decision.operation === operation
    ? decision.value
    : null;

const requestedSlug = (raw: unknown): string | null => {
  if (!isRecord(raw) || !isRecord(raw.seed)) return null;
  if (
    raw.seed.state === "provisional" &&
    validMaterialSlug(raw.seed.requested_slug)
  )
    return raw.seed.requested_slug;
  if (
    raw.seed.state === "canonical" &&
    validMaterialSlug(raw.seed.material_slug)
  )
    return raw.seed.material_slug;
  return null;
};

const observationProvesCanonicalOwner = (
  observation: QuasiStatusObservation,
  identity: PaperIdentity | BookIdentity,
): boolean => {
  const canonical =
    observation.kind === "paper"
      ? observation.facts.canonical
      : observation.kind === "book"
        ? observation.facts.overview
        : null;
  const diskIdentity = observation.identity;
  return (
    canonical?.present === true &&
    canonical.usable === true &&
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

export const parseLeafMaterialInput = (
  raw: unknown,
  kind: "paper" | "book",
): ParsedLeafMaterialInputResult => {
  const invalid = (): ParsedLeafMaterialInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind,
      slug: requestedSlug(raw),
    }),
  });
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["seed", "observation", "options"], ["userDecision"])
  )
    return invalid();
  const seed = parseLeafSeed(raw.seed, kind);
  if (seed === null) return invalid();
  const materialSlug =
    seed.state === "provisional" ? seed.requested_slug : seed.material_slug;
  const observations = sparseObservations([
    {
      route: { kind, slug: materialSlug },
      observation: raw.observation,
    },
  ]);
  const options = parseOptions(raw.options);
  const userDecision = Object.hasOwn(raw, "userDecision")
    ? parseUserDecision(raw.userDecision)
    : null;
  const observation =
    observations?.get(observationKey({ kind, slug: materialSlug })) ?? null;
  if (
    observations === null ||
    options === null ||
    (Object.hasOwn(raw, "userDecision") && userDecision === null) ||
    (seed.state === "canonical" &&
      seed.material_slug !== seed.identity.slug &&
      (observation === null ||
        !observationProvesCanonicalOwner(observation, seed.identity)))
  )
    return invalid();
  return {
    ok: true,
    value: { seed, observations, options, userDecision },
  };
};
