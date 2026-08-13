import {
  exactKeys,
  isArtifactObservation,
  isRecord,
  validMaterialSlug,
  validString,
  type ArtifactObservation,
  type QuasiStatusObservation,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";

export interface WebpageIdentity {
  slug: string;
  title: string;
  url: string;
  site: string;
}

export type WebpageSeed =
  | { state: "provisional"; url: string }
  | {
      state: "canonical";
      material_slug: string;
      identity: WebpageIdentity;
    };

export interface WebpageStatusFacts {
  kind: "webpage";
  snapshot: ArtifactObservation;
  prepared: ArtifactObservation;
  canonical: ArtifactObservation;
  captured_at: string | null;
}

export type WebpageStatusObservation = QuasiStatusObservation<
  "webpage",
  WebpageStatusFacts
>;

export type WebpageRunInput =
  | {
      mode: "identify";
      seed: Extract<WebpageSeed, { state: "provisional" }>;
      options: Readonly<Record<string, never>>;
    }
  | {
      mode: "process";
      seed: Extract<WebpageSeed, { state: "canonical" }>;
      observation: WebpageStatusObservation;
      effectiveIdentity: WebpageIdentity;
      options: Readonly<Record<string, never>>;
    };

export type WebpageRunInputResult =
  | { ok: true; value: WebpageRunInput }
  | { ok: false; result: MaterialResult };

const WHOLE_SECOND_UTC =
  /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

const normalizeWebUrl = (value: unknown): string | null => {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 2048 ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  )
    return null;
  const schemeSeparator = value.indexOf("://");
  if (schemeSeparator < 1) return null;
  const rawAuthority = value
    .slice(schemeSeparator + 3)
    .split(/[/?#]/, 1)[0];
  if (rawAuthority.includes("@")) return null;
  let url: {
    protocol: string;
    hostname: string;
    username: string;
    password: string;
    hash: string;
    pathname: string;
    toString(): string;
  };
  try {
    const UrlConstructor = (globalThis as unknown as {
      URL: new (input: string) => typeof url;
    }).URL;
    url = new UrlConstructor(value);
  } catch {
    return null;
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.hostname.length === 0 ||
    url.username.length > 0 ||
    url.password.length > 0
  )
    return null;
  url.hash = "";
  if (url.pathname === "") url.pathname = "/";
  return url.toString();
};

const parseWebpageIdentity = (value: unknown): WebpageIdentity | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["slug", "title", "url", "site"]) ||
    !validMaterialSlug(value.slug) ||
    !validString(value.title, 1, 500) ||
    normalizeWebUrl(value.url) === null ||
    !validString(value.site, 1, 200)
  )
    return null;
  return value as unknown as WebpageIdentity;
};

const validWholeSecondUtc = (value: unknown): value is string => {
  if (typeof value !== "string" || !WHOLE_SECOND_UTC.test(value)) return false;
  const timestamp = Date.parse(value);
  return (
    Number.isFinite(timestamp) &&
    new Date(timestamp).toISOString().replace(".000Z", "Z") === value
  );
};

export const parseWebpageStatusObservation = (
  value: unknown,
): WebpageStatusObservation | null => {
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
    value.kind !== "webpage" ||
    !validMaterialSlug(value.slug) ||
    (value.identity !== null && parseWebpageIdentity(value.identity) === null) ||
    !isRecord(value.facts)
  )
    return null;
  const facts = value.facts;
  const slug = value.slug;
  if (
    !exactKeys(facts, [
      "kind",
      "snapshot",
      "prepared",
      "canonical",
      "captured_at",
    ]) ||
    facts.kind !== "webpage" ||
    !isArtifactObservation(facts.snapshot) ||
    facts.snapshot.path !== `vault/webpages/${slug}/snapshot.webarchive` ||
    !isArtifactObservation(facts.prepared) ||
    facts.prepared.path !== `processing/webpages/${slug}/source.md` ||
    !isArtifactObservation(facts.canonical) ||
    facts.canonical.path !== `vault/webpages/${slug}/webpage.md` ||
    (facts.snapshot.usable
      ? !validWholeSecondUtc(facts.captured_at)
      : facts.captured_at !== null)
  )
    return null;
  return value as unknown as WebpageStatusObservation;
};

export const parseWebpageRunInput = (raw: unknown): WebpageRunInputResult => {
  const requestedSlug =
    isRecord(raw) &&
    isRecord(raw.seed) &&
    raw.seed.state === "canonical" &&
    validMaterialSlug(raw.seed.material_slug)
      ? raw.seed.material_slug
      : null;
  const invalid = (): WebpageRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind: "webpage",
      slug: requestedSlug,
    }),
  });
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["seed", "observation", "options"]) ||
    !isRecord(raw.options) ||
    !exactKeys(raw.options, []) ||
    !isRecord(raw.seed)
  )
    return invalid();

  if (
    raw.seed.state === "provisional" &&
    exactKeys(raw.seed, ["state", "url"]) &&
    normalizeWebUrl(raw.seed.url) !== null &&
    raw.observation === null
  )
    return {
      ok: true,
      value: {
        mode: "identify",
        seed: raw.seed as Extract<WebpageSeed, { state: "provisional" }>,
        options: raw.options as Readonly<Record<string, never>>,
      },
    };

  if (
    raw.seed.state !== "canonical" ||
    !exactKeys(raw.seed, ["state", "material_slug", "identity"]) ||
    !validMaterialSlug(raw.seed.material_slug)
  )
    return invalid();
  const identity = parseWebpageIdentity(raw.seed.identity);
  const observation = parseWebpageStatusObservation(raw.observation);
  if (
    identity === null ||
    identity.slug !== raw.seed.material_slug ||
    observation === null ||
    observation.slug !== raw.seed.material_slug
  )
    return invalid();

  const observedIdentity =
    observation.identity === null
      ? null
      : parseWebpageIdentity(observation.identity);
  if (
    observedIdentity !== null &&
    (observedIdentity.slug !== identity.slug ||
      normalizeWebUrl(observedIdentity.url) !== normalizeWebUrl(identity.url))
  )
    return invalid();
  const effectiveIdentity =
    observedIdentity === null
      ? identity
      : {
          ...identity,
          title: observedIdentity.title,
          site: observedIdentity.site,
        };
  return {
    ok: true,
    value: {
      mode: "process",
      seed: raw.seed as Extract<WebpageSeed, { state: "canonical" }>,
      observation,
      effectiveIdentity,
      options: raw.options as Readonly<Record<string, never>>,
    },
  };
};
