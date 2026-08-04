import {
  parseBookRunInput,
  parseBookStatusObservation,
  type BookRunInput,
  type BookStatusObservation,
} from "./book.mts";
import {
  parsePaperRunInput,
  parsePaperStatusObservation,
  type PaperRunInput,
  type PaperStatusObservation,
} from "./paper.mts";
import {
  exactKeys,
  isArtifactObservation,
  isRecord,
  observationKey,
  parseStatusEnvelope,
  parseUserDecision,
  validMaterialSlug,
  validString,
  type ArtifactObservation,
  type QuasiStatusObservation,
  type UserDecision,
} from "../shared/material-input.mts";
import {
  blockedMaterialResult,
  invalidMaterialInputResult,
  type ComposedLeafResumeSeed,
  type MaterialResult,
} from "../shared/material-result.mts";

export interface AuthorSeed {
  slug: string;
  full_name: string;
  topic: string;
}

export interface AuthorOptions {
  maxBooks?: number;
  maxPapers?: number;
}

export interface AuthorStatusFacts {
  kind: "author";
  canonical: ArtifactObservation;
}

export type AuthorStatusObservation = QuasiStatusObservation<
  "author",
  AuthorStatusFacts
>;

export type ChildRoute =
  | { kind: "paper"; slug: string }
  | { kind: "book"; slug: string };

export type PaperLeafContinuation = Extract<
  ComposedLeafResumeSeed,
  { route: { kind: "paper"; slug: string } }
>;
export type BookLeafContinuation = Extract<
  ComposedLeafResumeSeed,
  { route: { kind: "book"; slug: string } }
>;
export type AuthorLeafContinuation =
  | PaperLeafContinuation
  | BookLeafContinuation;

export interface AuthorMemberSeed {
  member_route: ChildRoute;
  leaf: AuthorLeafContinuation;
}

export interface AuthorResumeSeed {
  kind: "author";
  seed: AuthorSeed;
  options: AuthorOptions;
  members: AuthorMemberSeed[];
  decision_member: ChildRoute | null;
}

export type ChildStatusObservation =
  | PaperStatusObservation
  | BookStatusObservation;

interface AuthorDiscoverInput {
  mode: "discover";
  seed: AuthorSeed;
  observation: AuthorStatusObservation;
  options: AuthorOptions;
}

interface AuthorComposeInput {
  mode: "compose";
  observation: AuthorStatusObservation;
  resumeSeed: AuthorResumeSeed;
  childObservations: ReadonlyMap<string, ChildStatusObservation>;
  userDecision: UserDecision | null;
}

export type AuthorRunInput = AuthorDiscoverInput | AuthorComposeInput;

export type AuthorRunInputResult =
  | { ok: true; value: AuthorRunInput }
  | { ok: false; result: MaterialResult };

const childRoute = (value: unknown): ChildRoute | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["kind", "slug"]) ||
    !["paper", "book"].includes(value.kind as string) ||
    !validMaterialSlug(value.slug)
  )
    return null;
  return value as unknown as ChildRoute;
};

const routeKey = (route: ChildRoute): string =>
  observationKey(route);

const sameRoute = (left: ChildRoute, right: ChildRoute): boolean =>
  left.kind === right.kind && left.slug === right.slug;

const parseAuthorSeed = (value: unknown): AuthorSeed | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["slug", "full_name", "topic"]) ||
    !validMaterialSlug(value.slug) ||
    !validString(value.full_name, 1, 500) ||
    value.full_name !== value.full_name.trim() ||
    !validString(value.topic, 1, 2000) ||
    value.topic !== value.topic.trim()
  )
    return null;
  return value as unknown as AuthorSeed;
};

const parseAuthorOptions = (value: unknown): AuthorOptions | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [], ["maxBooks", "maxPapers"])
  )
    return null;
  if (
    Object.hasOwn(value, "maxBooks") &&
    (!Number.isInteger(value.maxBooks) ||
      (value.maxBooks as number) < 1 ||
      (value.maxBooks as number) > 5)
  )
    return null;
  if (
    Object.hasOwn(value, "maxPapers") &&
    (!Number.isInteger(value.maxPapers) ||
      (value.maxPapers as number) < 1 ||
      (value.maxPapers as number) > 10)
  )
    return null;
  return value as AuthorOptions;
};

export const parseAuthorStatusObservation = (
  value: unknown,
): AuthorStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "author");
  if (observation === null) return null;
  const canonical = observation.facts.canonical;
  if (
    !exactKeys(observation.facts, ["kind", "canonical"]) ||
    observation.facts.kind !== "author" ||
    !isArtifactObservation(canonical) ||
    canonical.path !== `vault/authors/${observation.slug}.md` ||
    (canonical.usable
      ? !isRecord(observation.identity) ||
        !exactKeys(observation.identity, ["name"]) ||
        !validString(observation.identity.name, 1, 500)
      : observation.identity !== null)
  )
    return null;
  return observation as unknown as AuthorStatusObservation;
};

const invalidResult = (raw: unknown): AuthorRunInputResult => {
  const requested = (() => {
    if (!isRecord(raw)) return null;
    if (isRecord(raw.seed) && validMaterialSlug(raw.seed.slug))
      return raw.seed.slug;
    if (
      isRecord(raw.resume_seed) &&
      isRecord(raw.resume_seed.seed) &&
      validMaterialSlug(raw.resume_seed.seed.slug)
    )
      return raw.resume_seed.seed.slug;
    return null;
  })();
  return {
    ok: false,
    result: invalidMaterialInputResult({ kind: "author", slug: requested }),
  };
};

const ownerConflictResult = (
  seed: AuthorSeed,
): AuthorRunInputResult => ({
  ok: false,
  result: blockedMaterialResult(
    {
      material: {
        requested: { kind: "author", slug: seed.slug },
        canonical: { kind: "author", slug: seed.slug },
      },
    },
    {
      code: "author.owner_conflict",
      operation: null,
      summary: "The exact Author path belongs to another person.",
      retryable: false,
      observation_request: null,
    },
  ),
});

const observationAdmitsSeed = (
  observation: AuthorStatusObservation,
  seed: AuthorSeed,
): boolean =>
  !observation.facts.canonical.usable ||
  (isRecord(observation.identity) &&
    observation.identity.name === seed.full_name);

const parseLeafShell = (
  value: unknown,
): AuthorLeafContinuation | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["route", "seed", "options"]) ||
    !isRecord(value.seed) ||
    !isRecord(value.options)
  )
    return null;
  const route = childRoute(value.route);
  if (route === null) return null;
  if (
    value.seed.state !== "canonical" ||
    value.seed.material_slug !== route.slug
  )
    return null;
  return value as unknown as AuthorLeafContinuation;
};

const parseResumeSeed = (value: unknown): AuthorResumeSeed | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, [
      "kind",
      "seed",
      "options",
      "members",
      "decision_member",
    ]) ||
    value.kind !== "author" ||
    !Array.isArray(value.members) ||
    value.members.length === 0
  )
    return null;
  const seed = parseAuthorSeed(value.seed);
  const options = parseAuthorOptions(value.options);
  if (seed === null || options === null) return null;
  const members: AuthorMemberSeed[] = [];
  const stableKeys = new Set<string>();
  for (const member of value.members) {
    if (
      !isRecord(member) ||
      !exactKeys(member, ["member_route", "leaf"])
    )
      return null;
    const memberRoute = childRoute(member.member_route);
    const leaf = parseLeafShell(member.leaf);
    if (
      memberRoute === null ||
      leaf === null ||
      (memberRoute.kind === "book" && leaf.route.kind !== "book")
    )
      return null;
    const key = routeKey(memberRoute);
    if (stableKeys.has(key)) return null;
    stableKeys.add(key);
    members.push({ member_route: memberRoute, leaf });
  }
  if (
    members.filter((member) => member.member_route.kind === "book")
      .length > (options.maxBooks ?? 5) ||
    members.filter((member) => member.member_route.kind === "paper")
      .length > (options.maxPapers ?? 10)
  )
    return null;
  const decisionMember =
    value.decision_member === null
      ? null
      : childRoute(value.decision_member);
  if (
    value.decision_member !== null &&
    (decisionMember === null || !stableKeys.has(routeKey(decisionMember)))
  )
    return null;
  return {
    kind: "author",
    seed,
    options,
    members,
    decision_member: decisionMember,
  };
};

const parseChildObservations = (
  value: unknown,
): ReadonlyMap<string, ChildStatusObservation> | null => {
  if (!Array.isArray(value)) return null;
  const result = new Map<string, ChildStatusObservation>();
  for (const entry of value) {
    if (
      !isRecord(entry) ||
      !exactKeys(entry, ["route", "observation"])
    )
      return null;
    const route = childRoute(entry.route);
    if (route === null) return null;
    const observation =
      route.kind === "paper"
        ? parsePaperStatusObservation(entry.observation)
        : parseBookStatusObservation(entry.observation);
    const key = routeKey(route);
    if (
      observation === null ||
      observation.slug !== route.slug ||
      result.has(key)
    )
      return null;
    result.set(key, observation);
  }
  return result;
};

const validLeafInput = (
  member: AuthorMemberSeed,
  observation: ChildStatusObservation,
  decision: UserDecision | null,
): boolean => {
  const raw = {
    seed: member.leaf.seed,
    observation,
    options: member.leaf.options,
    ...(decision === null ? {} : { userDecision: decision }),
  };
  return member.leaf.route.kind === "paper"
    ? parsePaperRunInput(raw).ok
    : parseBookRunInput(raw).ok;
};

const parseCompose = (
  raw: Record<string, unknown>,
): AuthorRunInputResult => {
  if (
    !exactKeys(
      raw,
      ["observation", "resume_seed", "child_observations"],
      ["userDecision"],
    )
  )
    return invalidResult(raw);
  const resumeSeed = parseResumeSeed(raw.resume_seed);
  const observation = parseAuthorStatusObservation(raw.observation);
  const childObservations = parseChildObservations(
    raw.child_observations,
  );
  const hasDecision = Object.hasOwn(raw, "userDecision");
  const userDecision = hasDecision
    ? parseUserDecision(raw.userDecision)
    : null;
  if (
    resumeSeed === null ||
    observation === null ||
    childObservations === null ||
    observation.slug !== resumeSeed.seed.slug ||
    hasDecision !== (resumeSeed.decision_member !== null) ||
    (hasDecision && userDecision === null)
  )
    return invalidResult(raw);
  if (!observationAdmitsSeed(observation, resumeSeed.seed))
    return ownerConflictResult(resumeSeed.seed);

  const expectedKeys = new Set(
    resumeSeed.members.map((member) => routeKey(member.leaf.route)),
  );
  if (
    childObservations.size !== expectedKeys.size ||
    [...expectedKeys].some((key) => !childObservations.has(key))
  )
    return invalidResult(raw);

  const decisionMember = resumeSeed.decision_member;
  const decisionIndex =
    decisionMember === null
      ? -1
      : resumeSeed.members.findIndex((member) =>
          sameRoute(member.member_route, decisionMember),
        );
  if (
    decisionIndex >= 0 &&
    userDecision?.material_key !==
      routeKey(resumeSeed.members[decisionIndex]!.leaf.route)
  )
    return invalidResult(raw);

  for (const [index, member] of resumeSeed.members.entries()) {
    const observationForMember = childObservations.get(
      routeKey(member.leaf.route),
    )!;
    if (
      !validLeafInput(
        member,
        observationForMember,
        index === decisionIndex ? userDecision : null,
      )
    )
      return invalidResult(raw);
  }
  return {
    ok: true,
    value: {
      mode: "compose",
      observation,
      resumeSeed,
      childObservations,
      userDecision,
    },
  };
};

export const parseAuthorRunInput = (
  raw: unknown,
): AuthorRunInputResult => {
  if (!isRecord(raw)) return invalidResult(raw);
  if (Object.hasOwn(raw, "resume_seed")) return parseCompose(raw);
  if (!exactKeys(raw, ["seed", "observation", "options"]))
    return invalidResult(raw);
  const seed = parseAuthorSeed(raw.seed);
  const observation = parseAuthorStatusObservation(raw.observation);
  const options = parseAuthorOptions(raw.options);
  if (
    seed === null ||
    observation === null ||
    options === null ||
    observation.slug !== seed.slug
  )
    return invalidResult(raw);
  if (!observationAdmitsSeed(observation, seed))
    return ownerConflictResult(seed);
  return {
    ok: true,
    value: { mode: "discover", seed, observation, options },
  };
};

const childObservationFor = (
  input: AuthorComposeInput,
  route: ChildRoute,
): ChildStatusObservation => input.childObservations.get(routeKey(route))!;

export const childRunInput = (
  input: AuthorComposeInput,
  member: AuthorMemberSeed,
  decision: UserDecision | null,
): PaperRunInput | BookRunInput => {
  const observation = childObservationFor(input, member.leaf.route);
  const raw = {
    seed: member.leaf.seed,
    observation,
    options: member.leaf.options,
    ...(decision === null ? {} : { userDecision: decision }),
  };
  const parsed =
    member.leaf.route.kind === "paper"
      ? parsePaperRunInput(raw)
      : parseBookRunInput(raw);
  if (!parsed.ok) throw new Error("validated Author child became invalid");
  return parsed.value;
};
