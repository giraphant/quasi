import type {
  OperationName,
  WorkflowContext,
} from "../artifact-contracts/generated.mjs";

const MATERIAL_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const LANGUAGE_TAG = /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$/;

export type LeafSeed<TIntake, TIdentity> =
  | { state: "provisional"; requested_slug: string; hints: TIntake }
  | { state: "canonical"; material_slug: string; identity: TIdentity };

export interface ArtifactObservation {
  path: string;
  present: boolean;
  usable: boolean;
}

export type StatusKind =
  | "paper"
  | "book"
  | "talk"
  | "webpage"
  | "translation"
  | "author"
  | "topic";

export interface QuasiStatusObservation<
  TKind extends StatusKind = StatusKind,
  TFacts = unknown,
> {
  schema_version: "quasi.status/0.2";
  kind: TKind;
  slug: string;
  identity: WorkflowContext | null;
  facts: TFacts;
}

export type ObservationRoute =
  | { kind: "paper" | "book" | "talk" | "webpage" | "topic"; slug: string }
  | { kind: "translation"; slug: string; target_language: string };

export type ObservationKey =
  | `paper:${string}`
  | `book:${string}`
  | `talk:${string}`
  | `webpage:${string}`
  | `topic:${string}`
  | `translation:paper:${string}:${string}`;

export type SparseObservationMap<
  TObservation extends QuasiStatusObservation = QuasiStatusObservation,
> = ReadonlyMap<ObservationKey, TObservation>;

export interface SparseObservationInput<
  TObservation extends QuasiStatusObservation = QuasiStatusObservation,
> {
  route: ObservationRoute;
  observation: TObservation;
}

export interface UserDecision {
  material_key: string;
  operation: string;
  value: unknown;
}

export interface LeafRunEnvelope {
  seed: unknown;
  observation: unknown;
  options: Readonly<Record<string, unknown>>;
  userDecision: UserDecision | null;
}

export const isRecord = (
  value: unknown,
): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export const exactKeys = (
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

export const validString = (
  value: unknown,
  minLength: number,
  maxLength: number,
): value is string =>
  typeof value === "string" &&
  value.length >= minLength &&
  value.length <= maxLength;

export const validNullableString = (
  value: unknown,
  maxLength: number,
): value is string | null =>
  value === null || validString(value, 0, maxLength);

export const validAuthors = (value: unknown): value is string[] =>
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

export const isArtifactObservation = (
  value: unknown,
): value is ArtifactObservation =>
  isRecord(value) &&
  exactKeys(value, ["path", "present", "usable"]) &&
  typeof value.path === "string" &&
  typeof value.present === "boolean" &&
  typeof value.usable === "boolean" &&
  (!value.usable || value.present);

export const isArtifactList = (
  value: unknown,
): value is ArtifactObservation[] =>
  Array.isArray(value) && value.every(isArtifactObservation);

export const parseStatusEnvelope = <TKind extends StatusKind>(
  value: unknown,
  expectedKind: TKind,
): QuasiStatusObservation<TKind, Record<string, unknown>> | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "schema_version",
      "kind",
      "slug",
      "identity",
      "facts",
    ]) ||
    value.schema_version !== "quasi.status/0.2" ||
    value.kind !== expectedKind ||
    !validMaterialSlug(value.slug) ||
    (value.identity !== null && !isRecord(value.identity)) ||
    !isRecord(value.facts)
  )
    return null;
  return value as unknown as QuasiStatusObservation<
    TKind,
    Record<string, unknown>
  >;
};

export const parseObservationRoute = (
  value: unknown,
): ObservationRoute | null => {
  if (!isRecord(value) || !validMaterialSlug(value.slug)) return null;
  if (
    ["paper", "book", "talk", "webpage", "topic"].includes(
      value.kind as string,
    ) &&
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

// Domain parsers validate facts before observations reach this binder. This
// function owns only route binding and duplicate-key rejection.
export const sparseObservations = <
  TObservation extends QuasiStatusObservation,
>(
  entries: unknown,
): SparseObservationMap<TObservation> | null => {
  if (!Array.isArray(entries)) return null;
  const observations = new Map<ObservationKey, TObservation>();
  for (const rawEntry of entries) {
    if (
      !isRecord(rawEntry) ||
      !exactKeys(rawEntry, ["route", "observation"])
    )
      return null;
    const route = parseObservationRoute(rawEntry.route);
    if (route === null) return null;
    const observation = parseStatusEnvelope(
      rawEntry.observation,
      route.kind,
    ) as TObservation | null;
    const observedTarget =
      route.kind === "translation" && observation !== null
        ? (observation.facts as Record<string, unknown>).target_language
        : null;
    if (
      observation === null ||
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
    !validString(value.operation, 1, 200)
  )
    return null;
  return value as unknown as UserDecision;
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

export const parseLeafRunEnvelope = (
  raw: unknown,
): LeafRunEnvelope | null => {
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["seed", "observation", "options"], ["userDecision"])
  )
    return null;
  const options = parseOptions(raw.options);
  const userDecision = Object.hasOwn(raw, "userDecision")
    ? parseUserDecision(raw.userDecision)
    : null;
  if (
    options === null ||
    (Object.hasOwn(raw, "userDecision") && userDecision === null)
  )
    return null;
  return {
    seed: raw.seed,
    observation: raw.observation,
    options,
    userDecision,
  };
};

export const requestedLeafSlug = (raw: unknown): string | null => {
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
