import {
  parseBookSeed,
  parseBookStatusObservation,
  type BookSeed,
  type BookStatusObservation,
} from "./book.mts";
import {
  parsePaperSeed,
  parsePaperStatusObservation,
  type PaperSeed,
  type PaperStatusObservation,
} from "./paper.mts";
import {
  parseTalkOptions,
  parseTalkSeed,
  parseTalkStatusObservation,
  type TalkOptions,
  type TalkSeed,
  type TalkStatusObservation,
} from "./talk.mts";
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
  type ObservationKey,
  type QuasiStatusObservation,
  type UserDecision,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type ComposedLeafResumeSeed,
  type MaterialResult,
} from "../shared/material-result.mts";
import { sameClosedValue } from "../runtime.mts";

export type TopicMemberRole = "evidence" | "theory" | "method" | "context";

export interface TopicSubquestionProjection {
  id: string;
  question: string;
  coverage: "gap" | "thin" | "covered" | "saturated";
  channel: "academic" | "web" | "mixed";
  theory_used: number;
}

export interface TopicMemberObservation {
  kind: "paper" | "book" | "talk";
  slug: string;
  subq: string;
  role: TopicMemberRole | null;
  artifact: ArtifactObservation;
}

export interface TopicCardObservation {
  slug: string;
  subq: string;
  title: string | null;
  artifact: ArtifactObservation;
}

export interface TopicOutlineProjection {
  subquestions: TopicSubquestionProjection[];
  members: TopicMemberObservation[];
  cards: TopicCardObservation[];
}

export interface TopicStatusFacts {
  kind: "topic";
  outline: ArtifactObservation & {
    valid: boolean;
    projection: TopicOutlineProjection | null;
  };
  overview: ArtifactObservation;
  resources: ArtifactObservation;
}

export type TopicStatusObservation = QuasiStatusObservation<
  "topic",
  TopicStatusFacts
>;

export interface TopicQuery {
  slug: string;
  description: string;
}

export interface TopicOptions {
  maxRounds: number;
  maxCardsPerRound: number;
}

export type TopicChildRoute = {
  kind: "paper" | "book" | "talk";
  slug: string;
};

export type TopicSeedMaterial =
  | { kind: "paper"; seed: PaperSeed; options: Record<string, never> }
  | { kind: "book"; seed: BookSeed; options: Record<string, never> }
  | { kind: "talk"; seed: TalkSeed; options: TalkOptions };

export interface TopicCandidateDemand {
  kind: "paper" | "book";
  requested_slug: string;
  query: string;
  subq: string;
  role: TopicMemberRole;
  reason: string;
}

export interface TopicAssignment {
  subq: string;
  role: TopicMemberRole;
}

export type PaperOrBookLeafResume = Extract<
  ComposedLeafResumeSeed,
  { route: { kind: "paper" | "book" } }
>;

export type TopicSeedLeaf =
  | PaperOrBookLeafResume
  | { route: { kind: "talk"; slug: string }; seed: TalkSeed; options: TalkOptions };

export interface TopicSeedChildContinuation {
  kind: "seed_child";
  topic: TopicQuery;
  fingerprint: string;
  member_route: TopicChildRoute;
  leaf: TopicSeedLeaf;
}

export interface TopicWorkContinuation {
  kind: "material_work";
  topic: TopicQuery;
  demand: TopicCandidateDemand;
  assignment: TopicAssignment;
  fingerprint: string;
  member_route: TopicChildRoute;
  leaf: PaperOrBookLeafResume;
}

export interface TopicRecallContinuation {
  kind: "recalled_member";
  topic: TopicQuery;
  item: {
    kind: "paper" | "book" | "talk";
    slug: string;
    path: string | null;
  };
  fingerprint: string;
  route: TopicChildRoute;
}

export type TopicCheckpointAdmission =
  | {
      kind: "checkpoint_admission";
      topic: TopicQuery;
      item: "member";
      source_route: TopicChildRoute;
      ref: { kind: "paper" | "book" | "talk"; slug: string; path: string };
      assignment: TopicAssignment | null;
    }
  | {
      kind: "checkpoint_admission";
      topic: TopicQuery;
      item: "card";
      ref: { slug: string; path: string; title: string | null };
      assignment: { subq: string };
    };

export type TopicResumeSeed =
  | TopicSeedChildContinuation
  | TopicWorkContinuation
  | TopicRecallContinuation
  | TopicCheckpointAdmission;

export interface TopicResumeInput {
  resume_seed: TopicResumeSeed;
  userDecision: UserDecision | null;
}

export type TopicChildStatusObservation =
  | PaperStatusObservation
  | BookStatusObservation
  | TalkStatusObservation;

export interface TopicRunInput {
  query: TopicQuery;
  observation: TopicStatusObservation;
  options: TopicOptions;
  seedMaterials: TopicSeedMaterial[];
  childObservations: ReadonlyMap<ObservationKey, TopicChildStatusObservation>;
  resume: TopicResumeInput | null;
}

export interface TopicSeedGate {
  kind: "topic_seed";
  operation: null;
  question: string;
  seeds: Array<{
    kind: "paper" | "book" | "talk";
    slug: string;
    reason: string;
  }>;
}

export interface TopicNeedsSeedsGate {
  kind: "topic_needs_seeds";
  operation: "topic.steer";
  question: string;
  suggested_queries: string[];
  uncovered_subquestions: string[];
}

export type TopicGate = TopicSeedGate | TopicNeedsSeedsGate;

export type TopicPendingWork =
  | {
      kind: "material";
      material_kind: "paper" | "book";
      requested_slug: string;
      subq: string;
      role: TopicMemberRole;
      fingerprint: string;
    }
  | {
      kind: "webcard";
      card_slug: string;
      subq: string;
      fingerprint: string;
    };

const topicSubquestion = (value: unknown): TopicSubquestionProjection | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["id", "question", "coverage", "channel", "theory_used"]) ||
    !validMaterialSlug(value.id) ||
    !validString(value.question, 4, 280) ||
    !["gap", "thin", "covered", "saturated"].includes(value.coverage as string) ||
    !["academic", "web", "mixed"].includes(value.channel as string) ||
    !Number.isInteger(value.theory_used) ||
    (value.theory_used as number) < 0
  ) return null;
  return value as unknown as TopicSubquestionProjection;
};

export const topicMemberPath = (
  kind: TopicChildRoute["kind"],
  slug: string,
): string =>
  kind === "paper"
    ? `vault/papers/${slug}.md`
    : kind === "book"
      ? `vault/books/${slug}/00-overview.md`
      : `vault/talks/${slug}/talk.md`;

const topicProjection = (
  value: unknown,
  topicSlug: string,
): TopicOutlineProjection | null => {
  if (!isRecord(value) || !exactKeys(value, ["subquestions", "members", "cards"]))
    return null;
  if (!Array.isArray(value.subquestions) || value.subquestions.length < 1 || value.subquestions.length > 6)
    return null;
  const subquestions = value.subquestions.map(topicSubquestion);
  if (subquestions.some((item) => item === null)) return null;
  const ids = new Set(subquestions.map((item) => item!.id));
  if (ids.size !== subquestions.length) return null;
  if (!Array.isArray(value.members) || value.members.length > 300) return null;
  for (const item of value.members) {
    if (
      !isRecord(item) ||
      !exactKeys(item, ["kind", "slug", "subq", "role", "artifact"]) ||
      !["paper", "book", "talk"].includes(item.kind as string) ||
      !validMaterialSlug(item.slug) ||
      !ids.has(item.subq as string) ||
      (item.role !== null && !["evidence", "theory", "method", "context"].includes(item.role as string)) ||
      !isArtifactObservation(item.artifact) ||
      item.artifact.path !== topicMemberPath(item.kind as TopicChildRoute["kind"], item.slug as string)
    ) return null;
  }
  if (!Array.isArray(value.cards) || value.cards.length > 300) return null;
  for (const item of value.cards) {
    if (
      !isRecord(item) ||
      !exactKeys(item, ["slug", "subq", "title", "artifact"]) ||
      !validMaterialSlug(item.slug) ||
      (item.slug as string).length < 2 ||
      !ids.has(item.subq as string) ||
      (item.title !== null && !validString(item.title, 1, 500)) ||
      !isArtifactObservation(item.artifact) ||
      item.artifact.path !== `vault/topics/${topicSlug}/cards/${item.slug}.md`
    ) return null;
  }
  return value as unknown as TopicOutlineProjection;
};

export const parseTopicStatusObservation = (
  value: unknown,
): TopicStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "topic");
  if (observation === null) return null;
  const facts = observation.facts;
  const outline = facts.outline;
  const outlinePath = `vault/topics/${observation.slug}/02-outline.md`;
  if (
    !exactKeys(facts, ["kind", "outline", "overview", "resources"]) ||
    facts.kind !== "topic" ||
    !isRecord(outline) ||
    !exactKeys(outline, ["path", "present", "usable", "valid", "projection"]) ||
    !isArtifactObservation({ path: outline.path, present: outline.present, usable: outline.usable }) ||
    outline.path !== outlinePath ||
    typeof outline.valid !== "boolean" ||
    !isArtifactObservation(facts.overview) ||
    facts.overview.path !== `vault/topics/${observation.slug}/00-overview.md` ||
    !isArtifactObservation(facts.resources) ||
    facts.resources.path !== `vault/topics/${observation.slug}/01-resources.md`
  ) return null;
  const projection = outline.projection === null
    ? null
    : topicProjection(outline.projection, observation.slug);
  if (
    (outline.projection !== null && projection === null) ||
    outline.valid !== (projection !== null) ||
    (projection !== null && outline.usable !== true)
  ) return null;
  return observation as unknown as TopicStatusObservation;
};

const parseQuery = (value: unknown): TopicQuery | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["slug", "description"]) ||
    !validMaterialSlug(value.slug) ||
    !validString(value.description, 1, 2000) ||
    value.description !== value.description.trim()
  ) return null;
  return value as unknown as TopicQuery;
};

const parseOptions = (value: unknown): TopicOptions | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["maxRounds", "maxCardsPerRound"]) ||
    !Number.isInteger(value.maxRounds) ||
    (value.maxRounds as number) < 0 ||
    (value.maxRounds as number) > 8 ||
    !Number.isInteger(value.maxCardsPerRound) ||
    (value.maxCardsPerRound as number) < 0 ||
    (value.maxCardsPerRound as number) > 6
  ) return null;
  return value as unknown as TopicOptions;
};

const parseChildRoute = (value: unknown): TopicChildRoute | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["kind", "slug"]) ||
    !["paper", "book", "talk"].includes(value.kind as string) ||
    !validMaterialSlug(value.slug)
  ) return null;
  return value as unknown as TopicChildRoute;
};

const parseSeedMaterial = (value: unknown): TopicSeedMaterial | null => {
  if (!isRecord(value) || !exactKeys(value, ["kind", "seed", "options"]) || !isRecord(value.options))
    return null;
  if (value.kind === "paper" && exactKeys(value.options, [])) {
    const seed = parsePaperSeed(value.seed);
    return seed === null ? null : { kind: "paper", seed, options: {} };
  }
  if (value.kind === "book" && exactKeys(value.options, [])) {
    const seed = parseBookSeed(value.seed);
    return seed === null ? null : { kind: "book", seed, options: {} };
  }
  if (value.kind === "talk") {
    const seed = parseTalkSeed(value.seed);
    const options = parseTalkOptions(value.options);
    return seed === null || options === null ? null : { kind: "talk", seed, options };
  }
  return null;
};

const canonicalValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]),
  );
};

export const canonicalFingerprint = (value: unknown): string =>
  JSON.stringify(canonicalValue(value));

const parseDemand = (value: unknown): TopicCandidateDemand | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["kind", "requested_slug", "query", "subq", "role", "reason"]) ||
    !["paper", "book"].includes(value.kind as string) ||
    !validMaterialSlug(value.requested_slug) ||
    !validString(value.query, 1, 500) ||
    !validMaterialSlug(value.subq) ||
    !["evidence", "theory", "method", "context"].includes(value.role as string) ||
    !validString(value.reason, 1, 1000)
  ) return null;
  return value as unknown as TopicCandidateDemand;
};

const parseAssignment = (value: unknown): TopicAssignment | null => {
  if (
    !isRecord(value) ||
    !exactKeys(value, ["subq", "role"]) ||
    !validMaterialSlug(value.subq) ||
    !["evidence", "theory", "method", "context"].includes(value.role as string)
  ) return null;
  return value as unknown as TopicAssignment;
};

const parseSeedLeaf = (value: unknown): TopicSeedLeaf | null => {
  if (!isRecord(value) || !exactKeys(value, ["route", "seed", "options"]) || !isRecord(value.options))
    return null;
  const route = parseChildRoute(value.route);
  if (route === null) return null;
  if (route.kind === "paper" && exactKeys(value.options, [])) {
    const seed = parsePaperSeed(value.seed);
    return seed === null ? null : { route, seed, options: {} } as TopicSeedLeaf;
  }
  if (route.kind === "book") {
    const seed = parseBookSeed(value.seed);
    return seed === null ? null : { route, seed, options: value.options } as TopicSeedLeaf;
  }
  const seed = parseTalkSeed(value.seed);
  const options = parseTalkOptions(value.options);
  return seed === null || options === null
    ? null
    : { route, seed, options } as TopicSeedLeaf;
};

const leafMatchesRoute = (leaf: TopicSeedLeaf): boolean =>
  (leaf.seed.state === "provisional"
    ? leaf.seed.requested_slug
    : leaf.seed.material_slug) === leaf.route.slug;

const validLeafTransition = (
  memberRoute: TopicChildRoute,
  leaf: TopicSeedLeaf,
): boolean => {
  if (memberRoute.kind === "talk" || leaf.route.kind === "talk")
    return memberRoute.kind === "talk" &&
      leaf.route.kind === "talk" &&
      memberRoute.slug === leaf.route.slug;
  if (memberRoute.kind === leaf.route.kind)
    return leaf.seed.state === "canonical" ||
      memberRoute.slug === leaf.route.slug;
  return memberRoute.kind === "paper" &&
    leaf.route.kind === "book" &&
    leaf.seed.state === "canonical";
};

const parseRecallItem = (value: unknown): TopicRecallContinuation["item"] | null => {
  const route = isRecord(value)
    ? parseChildRoute({ kind: value.kind, slug: value.slug })
    : null;
  if (
    !isRecord(value) ||
    !exactKeys(value, ["kind", "slug", "path"]) ||
    route === null ||
    (value.path !== null && value.path !== topicMemberPath(route.kind, route.slug))
  ) return null;
  return value as unknown as TopicRecallContinuation["item"];
};

const parseResumeSeed = (value: unknown, query: TopicQuery): TopicResumeSeed | null => {
  if (!isRecord(value) || !isRecord(value.topic) || !sameClosedValue(value.topic, query))
    return null;
  if (value.kind === "seed_child" && exactKeys(value, ["kind", "topic", "fingerprint", "member_route", "leaf"])) {
    const memberRoute = parseChildRoute(value.member_route);
    const leaf = parseSeedLeaf(value.leaf);
    if (memberRoute === null || leaf === null || !leafMatchesRoute(leaf) || typeof value.fingerprint !== "string")
      return null;
    const expected = canonicalFingerprint(["seed", memberRoute.kind, memberRoute.slug, leaf.seed, leaf.options]);
    return value.fingerprint === expected && validLeafTransition(memberRoute, leaf)
      ? value as unknown as TopicSeedChildContinuation
      : null;
  }
  if (value.kind === "material_work" && exactKeys(value, ["kind", "topic", "demand", "assignment", "fingerprint", "member_route", "leaf"])) {
    const demand = parseDemand(value.demand);
    const assignment = parseAssignment(value.assignment);
    const memberRoute = parseChildRoute(value.member_route);
    const leaf = parseSeedLeaf(value.leaf);
    const expected = demand === null ? "" : canonicalFingerprint([
      demand.kind, demand.requested_slug, demand.query, demand.subq, demand.role, demand.reason,
    ]);
    if (
      demand === null || assignment === null || memberRoute === null || leaf === null ||
      leaf.route.kind === "talk" || !leafMatchesRoute(leaf) ||
      assignment.subq !== demand.subq || assignment.role !== demand.role ||
      memberRoute.kind !== demand.kind || memberRoute.slug !== demand.requested_slug ||
      !validLeafTransition(memberRoute, leaf) ||
      value.fingerprint !== expected
    ) return null;
    return value as unknown as TopicWorkContinuation;
  }
  if (value.kind === "recalled_member" && exactKeys(value, ["kind", "topic", "item", "fingerprint", "route"])) {
    const item = parseRecallItem(value.item);
    const route = parseChildRoute(value.route);
    const expected = item === null ? "" : canonicalFingerprint(["recall", item.kind, item.slug, item.path]);
    if (item === null || route === null || route.kind !== item.kind || route.slug !== item.slug || value.fingerprint !== expected)
      return null;
    return value as unknown as TopicRecallContinuation;
  }
  if (value.kind === "checkpoint_admission" && value.item === "member" && exactKeys(value, ["kind", "topic", "item", "source_route", "ref", "assignment"])) {
    const sourceRoute = parseChildRoute(value.source_route);
    const ref = parseRecallItem(value.ref);
    const assignment = value.assignment === null ? null : parseAssignment(value.assignment);
    const validSource =
      sourceRoute !== null && ref !== null &&
      (sourceRoute.kind === "paper"
        ? ref.kind === "paper" || ref.kind === "book"
        : sourceRoute.kind === "book"
          ? ref.kind === "book"
          : ref.kind === "talk" && ref.slug === sourceRoute.slug);
    if (
      !validSource || ref === null || ref.path === null ||
      (value.assignment !== null && assignment === null)
    ) return null;
    return value as unknown as TopicCheckpointAdmission;
  }
  if (value.kind === "checkpoint_admission" && value.item === "card" && exactKeys(value, ["kind", "topic", "item", "ref", "assignment"])) {
    if (
      !isRecord(value.ref) || !exactKeys(value.ref, ["slug", "path", "title"]) ||
      !validMaterialSlug(value.ref.slug) || value.ref.slug.length < 2 ||
      value.ref.path !== `vault/topics/${query.slug}/cards/${value.ref.slug}.md` ||
      (value.ref.title !== null && !validString(value.ref.title, 1, 500)) ||
      !isRecord(value.assignment) || !exactKeys(value.assignment, ["subq"]) || !validMaterialSlug(value.assignment.subq)
    ) return null;
    return value as unknown as TopicCheckpointAdmission;
  }
  return null;
};

const parseChildObservations = (
  value: unknown,
): ReadonlyMap<ObservationKey, TopicChildStatusObservation> | null => {
  if (!Array.isArray(value)) return null;
  const result = new Map<ObservationKey, TopicChildStatusObservation>();
  for (const entry of value) {
    if (!isRecord(entry) || !exactKeys(entry, ["route", "observation"])) return null;
    const route = parseChildRoute(entry.route);
    if (route === null) return null;
    const observation = route.kind === "paper"
      ? parsePaperStatusObservation(entry.observation)
      : route.kind === "book"
        ? parseBookStatusObservation(entry.observation)
        : parseTalkStatusObservation(entry.observation);
    if (observation === null || observation.slug !== route.slug) return null;
    const key = observationKey(route);
    if (result.has(key)) return null;
    result.set(key, observation);
  }
  return result;
};

export type TopicRunInputResult =
  | { ok: true; value: TopicRunInput }
  | { ok: false; result: MaterialResult };

export const parseTopicRunInput = (raw: unknown): TopicRunInputResult => {
  const invalid = (slug: string | null = null): TopicRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({ kind: "topic", slug }),
  });
  if (
    !isRecord(raw) ||
    !exactKeys(raw, ["query", "observation", "options", "seed_materials", "child_observations"], ["resume"])
  ) return invalid();
  const query = parseQuery(raw.query);
  const observation = parseTopicStatusObservation(raw.observation);
  const options = parseOptions(raw.options);
  const childObservations = parseChildObservations(raw.child_observations);
  if (
    query === null || observation === null || options === null || childObservations === null ||
    observation.slug !== query.slug || !Array.isArray(raw.seed_materials)
  ) return invalid(query?.slug ?? null);
  const seedMaterials = raw.seed_materials.map(parseSeedMaterial);
  if (seedMaterials.some((seed) => seed === null)) return invalid(query.slug);
  let resume: TopicResumeInput | null = null;
  if (Object.hasOwn(raw, "resume")) {
    if (!isRecord(raw.resume) || !exactKeys(raw.resume, ["resume_seed"], ["userDecision"]))
      return invalid(query.slug);
    const resumeSeed = parseResumeSeed(raw.resume.resume_seed, query);
    const userDecision = Object.hasOwn(raw.resume, "userDecision")
      ? parseUserDecision(raw.resume.userDecision)
      : null;
    if (resumeSeed === null || (Object.hasOwn(raw.resume, "userDecision") && userDecision === null))
      return invalid(query.slug);
    const leafResume = resumeSeed.kind === "seed_child" || resumeSeed.kind === "material_work";
    if (!leafResume && Object.hasOwn(raw.resume, "userDecision")) return invalid(query.slug);
    resume = { resume_seed: resumeSeed, userDecision };
  }
  return {
    ok: true,
    value: {
      query,
      observation,
      options,
      seedMaterials: seedMaterials as TopicSeedMaterial[],
      childObservations,
      resume,
    },
  };
};
