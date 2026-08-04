import {
  exactKeys,
  isArtifactObservation,
  isRecord,
  parseStatusEnvelope,
  validMaterialSlug,
  type ArtifactObservation,
  type QuasiStatusObservation,
} from "../shared/material-input.mts";

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
      role: string;
      fingerprint: string;
    }
  | {
      kind: "webcard";
      card_slug: string;
      subq: string;
      fingerprint: string;
    };

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

export const parseTopicStatusObservation = (
  value: unknown,
): TopicStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "topic");
  if (observation === null) return null;
  const facts = observation.facts;
  const outline = facts.outline;
  if (
    !exactKeys(facts, ["kind", "outline", "overview", "resources"]) ||
    facts.kind !== "topic" ||
    !isRecord(outline) ||
    !exactKeys(outline, [
      "path",
      "present",
      "usable",
      "valid",
      "projection",
    ]) ||
    !isArtifactObservation({
      path: outline.path,
      present: outline.present,
      usable: outline.usable,
    }) ||
    typeof outline.valid !== "boolean" ||
    (outline.projection !== null && !isTopicProjection(outline.projection)) ||
    outline.valid !== (outline.projection !== null) ||
    !isArtifactObservation(facts.overview) ||
    !isArtifactObservation(facts.resources)
  )
    return null;
  return observation as unknown as TopicStatusObservation;
};
