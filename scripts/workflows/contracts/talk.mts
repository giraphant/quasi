import {
  exactKeys,
  isArtifactList,
  isArtifactObservation,
  parseStatusEnvelope,
  type ArtifactObservation,
  type QuasiStatusObservation,
} from "../shared/material-input.mts";

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

export const parseTalkStatusObservation = (
  value: unknown,
): TalkStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "talk");
  if (observation === null) return null;
  const facts = observation.facts;
  if (
    !exactKeys(facts, ["kind", "media", "transcripts", "canonical"]) ||
    facts.kind !== "talk" ||
    !isArtifactList(facts.media) ||
    !isArtifactList(facts.transcripts) ||
    !isArtifactObservation(facts.canonical)
  )
    return null;
  return observation as unknown as TalkStatusObservation;
};
