import {
  exactKeys as exactEnvelopeKeys,
  isArtifactObservation,
  isRecord,
  normalizeLanguage,
  parseStatusEnvelope,
  type ArtifactObservation,
  type QuasiStatusObservation,
} from "../shared/material-input.mts";
import { exactKeys, validText } from "../runtime.mts";

const SHA256 = /^[0-9a-f]{64}$/;

export interface TranslationCandidate {
  path: string;
  sha256: string;
  size: number;
  pages: number;
}

export interface TranslationSourceDecisionValue {
  candidates_fingerprint: string;
  source_path: string;
}

export interface TranslationStatusFacts {
  kind: "translation";
  target_language: string;
  source: ArtifactObservation;
  output: ArtifactObservation;
  manifest: ArtifactObservation;
}

export type TranslationStatusObservation = QuasiStatusObservation<
  "translation",
  TranslationStatusFacts
>;

export const parseTranslationCandidate = (
  value: unknown,
): TranslationCandidate | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, ["path", "sha256", "size", "pages"]) ||
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

export const parseTranslationSourceDecisionValue = (
  value: unknown,
): TranslationSourceDecisionValue | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, ["candidates_fingerprint", "source_path"]) ||
    typeof value.candidates_fingerprint !== "string" ||
    !SHA256.test(value.candidates_fingerprint) ||
    typeof value.source_path !== "string" ||
    value.source_path.length === 0
  )
    return null;
  return value as unknown as TranslationSourceDecisionValue;
};

export const parseTranslationStatusObservation = (
  value: unknown,
): TranslationStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "translation");
  if (observation === null) return null;
  const facts = observation.facts;
  if (
    !exactEnvelopeKeys(facts, [
      "kind",
      "target_language",
      "source",
      "output",
      "manifest",
    ]) ||
    facts.kind !== "translation" ||
    normalizeLanguage(facts.target_language) !== facts.target_language ||
    !isArtifactObservation(facts.source) ||
    !isArtifactObservation(facts.output) ||
    !isArtifactObservation(facts.manifest)
  )
    return null;
  return observation as unknown as TranslationStatusObservation;
};

interface TranslationGateBase {
  operation: "translation.prepare";
  material_key: string;
  question: string;
}

export interface TranslationSourceGate extends TranslationGateBase {
  kind: "translation_source";
  missing_fields: [];
  candidates: TranslationCandidate[];
  candidates_fingerprint: string;
}

export interface TranslationConfigurationGate extends TranslationGateBase {
  kind: "translation_configuration";
  missing_fields: string[];
  candidates: [];
  candidates_fingerprint: null;
}

export type TranslationGate =
  | TranslationSourceGate
  | TranslationConfigurationGate;

const gateBase = (
  receipt: any,
): TranslationGateBase | null => {
  const terminal = receipt?.terminal;
  const issue = terminal?.issue;
  if (
    receipt?.operation !== "translation.prepare" ||
    !validText(receipt?.material_key, 1, 512) ||
    terminal?.status !== "needs_input" ||
    issue?.operation !== "translation.prepare" ||
    !validText(issue?.user_question, 1, 4000)
  )
    return null;
  return {
    operation: "translation.prepare",
    material_key: receipt.material_key,
    question: issue.user_question,
  };
};

export const parseTranslationGate = (
  receipt: any,
): TranslationGate | null => {
  const base = gateBase(receipt);
  const issueCode = receipt?.terminal?.issue?.code;
  const gate = receipt?.terminal?.gate;
  if (
    base === null ||
    !exactKeys(gate, [
      "kind",
      "missing_fields",
      "candidates",
      "candidates_fingerprint",
    ])
  )
    return null;

  if (
    issueCode === "translation.source_selection_required" &&
    gate.kind === "source_selection" &&
    Array.isArray(gate.missing_fields) &&
    gate.missing_fields.length === 0 &&
    Array.isArray(gate.candidates) &&
    gate.candidates.length >= 2 &&
    gate.candidates.length <= 32 &&
    SHA256.test(gate.candidates_fingerprint)
  ) {
    const candidates = gate.candidates.map(parseTranslationCandidate);
    if (candidates.some((candidate: any) => candidate === null))
      return null;
    return {
      ...base,
      kind: "translation_source",
      missing_fields: [],
      candidates: candidates as TranslationCandidate[],
      candidates_fingerprint: gate.candidates_fingerprint,
    };
  }

  if (
    issueCode === "translation.configuration_required" &&
    gate.kind === "configuration_required" &&
    Array.isArray(gate.missing_fields) &&
    gate.missing_fields.length >= 1 &&
    gate.missing_fields.length <= 8 &&
    gate.missing_fields.every((field: unknown) => validText(field, 1, 512)) &&
    new Set(gate.missing_fields).size === gate.missing_fields.length &&
    Array.isArray(gate.candidates) &&
    gate.candidates.length === 0 &&
    gate.candidates_fingerprint === null
  )
    return {
      ...base,
      kind: "translation_configuration",
      missing_fields: gate.missing_fields,
      candidates: [],
      candidates_fingerprint: null,
    };

  return null;
};
