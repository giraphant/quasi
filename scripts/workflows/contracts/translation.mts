import {
  parseTranslationCandidate,
  type TranslationCandidate,
} from "../shared/material-input.mts";
import { exactKeys, validText } from "../runtime.mts";

const SHA256 = /^[0-9a-f]{64}$/;

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
