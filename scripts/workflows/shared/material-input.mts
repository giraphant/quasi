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
const LANGUAGE_TAG = /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,2}$/;
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

export interface TranslationCandidate {
  path: string;
  sha256: string;
  size: number;
  pages: number;
}

export interface QuasiStatusStageObservation {
  stage: string;
  complete: boolean | null;
  evidence: string[];
}

interface QuasiStatusObservationBase {
  schema_version: "quasi.status/0.1";
  slug: string;
  stages: QuasiStatusStageObservation[];
  next_stage: string | null;
  refs: WorkflowContext;
  identity?: WorkflowContext | null;
}

export type QuasiStatusObservation =
  | (QuasiStatusObservationBase & {
      kind: "paper" | "book" | "talk";
      target_language?: never;
    })
  | (QuasiStatusObservationBase & {
      kind: "translation";
      target_language: string;
    });

export interface UserDecision {
  material_key: string;
  operation: OperationName;
  value: unknown;
}

export interface BookYearDecisionValue {
  tmp_path: string;
  year_evidence: WorkflowContext;
  action: "accept-current" | "use-recommended-year";
}

export interface TranslationSourceDecisionValue {
  candidates_fingerprint: string;
  source_path: string;
}

export interface ParsedLeafMaterialInput<
  TIdentity extends PaperIdentity | BookIdentity,
> {
  identity: TIdentity;
  observations: SparseObservationMap;
  options: Readonly<Record<string, unknown>>;
  userDecision: UserDecision | null;
}

export type ParsedLeafMaterialInputResult =
  | {
      ok: true;
      value: ParsedLeafMaterialInput<PaperIdentity | BookIdentity>;
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
      if (part.length === 2) return part.toUpperCase();
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

const parseStatusObservation = (
  value: unknown,
): QuasiStatusObservation | null => {
  const translation = isRecord(value) && value.kind === "translation";
  if (
    !isRecord(value) ||
    !exactKeys(
      value,
      ["schema_version", "kind", "slug", "stages", "next_stage", "refs"],
      translation ? ["identity", "target_language"] : ["identity"],
    ) ||
    value.schema_version !== "quasi.status/0.1" ||
    !["paper", "book", "talk", "translation"].includes(
      value.kind as string,
    ) ||
    !validMaterialSlug(value.slug) ||
    !Array.isArray(value.stages) ||
    !value.stages.every(
      (item) =>
        isRecord(item) &&
        exactKeys(item, ["stage", "complete", "evidence"]) &&
        validString(item.stage, 1, 64) &&
        (typeof item.complete === "boolean" || item.complete === null) &&
        Array.isArray(item.evidence) &&
        item.evidence.every((path) => typeof path === "string"),
    ) ||
    !(value.next_stage === null || validString(value.next_stage, 1, 64)) ||
    !isRecord(value.refs) ||
    (Object.hasOwn(value, "identity") &&
      value.identity !== null &&
      !isRecord(value.identity)) ||
    (translation &&
      normalizeLanguage(value.target_language) !== value.target_language)
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
    if (
      route === null ||
      observation === null ||
      observation.kind !== route.kind ||
      observation.slug !== route.slug ||
      (route.kind === "translation" &&
        observation.target_language !== route.target_language)
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

export const parseBookYearDecisionValue = (
  value: unknown,
): BookYearDecisionValue | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["tmp_path", "year_evidence", "action"]) ||
    typeof value.tmp_path !== "string" ||
    !isRecord(value.year_evidence) ||
    !["accept-current", "use-recommended-year"].includes(
      value.action as string,
    )
  )
    return null;
  return value as unknown as BookYearDecisionValue;
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
  if (!isRecord(raw) || !isRecord(raw.identity)) return null;
  return validMaterialSlug(raw.identity.slug) ? raw.identity.slug : null;
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
    !exactKeys(raw, ["identity", "observation", "options"], ["userDecision"])
  )
    return invalid();
  const identity =
    kind === "paper"
      ? parsePaperIdentity(raw.identity)
      : parseBookIdentity(raw.identity);
  if (identity === null) return invalid();
  const observations = sparseObservations([
    {
      route: { kind, slug: identity.slug },
      observation: raw.observation,
    },
  ]);
  const options = parseOptions(raw.options);
  const userDecision = Object.hasOwn(raw, "userDecision")
    ? parseUserDecision(raw.userDecision)
    : null;
  if (
    observations === null ||
    options === null ||
    (Object.hasOwn(raw, "userDecision") && userDecision === null)
  )
    return invalid();
  return {
    ok: true,
    value: { identity, observations, options, userDecision },
  };
};
