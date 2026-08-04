import {
  exactKeys as exactEnvelopeKeys,
  isArtifactObservation,
  isRecord,
  normalizeLanguage,
  observationKey,
  parseUserDecision,
  parseStatusEnvelope,
  requestedLeafSlug,
  sparseObservations,
  validMaterialSlug,
  validString,
  type ArtifactObservation,
  type QuasiStatusObservation,
  type SparseObservationMap,
  type UserDecision,
} from "../shared/material-input.mts";
import { exactKeys, validText } from "../runtime.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";

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

export interface TranslationSeed {
  state: "canonical";
  material_slug: string;
}

export interface TranslationOptions {
  source_file: string | null;
  toc_json: string | null;
  toc_page_side: "original" | "translated";
}

export interface TranslationRunInput {
  seed: TranslationSeed;
  target_language: string;
  observations: SparseObservationMap<TranslationStatusObservation>;
  options: TranslationOptions;
  userDecision: UserDecision | null;
}

export type TranslationRunInputResult =
  | { ok: true; value: TranslationRunInput }
  | { ok: false; result: MaterialResult };

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

export function translationSourceRoles(
  slug: string,
  targetLanguage: string,
) {
  const target = targetLanguage.toLowerCase();
  return {
    canonical: `sources/${slug}.pdf`,
    paperOcr: `processing/papers/${slug}/ocr.pdf`,
    derivativeRecovery:
      `processing/translations/${slug}-${target}-reocr.pdf`,
  };
}

export function validRequestedTranslationSource(
  path: string,
  slug: string,
  targetLanguage: string,
): boolean {
  const roles = translationSourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr, roles.derivativeRecovery].includes(
    path,
  );
}

export function validSelectableTranslationSource(
  path: string,
  slug: string,
  targetLanguage: string,
): boolean {
  const roles = translationSourceRoles(slug, targetLanguage);
  return [roles.canonical, roles.paperOcr].includes(path);
}

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
  const target =
    typeof facts.target_language === "string"
      ? facts.target_language.toLowerCase()
      : "";
  if (
    !exactEnvelopeKeys(facts, [
      "kind",
      "target_language",
      "source",
      "output",
      "manifest",
    ]) ||
    facts.kind !== "translation" ||
    observation.identity !== null ||
    normalizeLanguage(facts.target_language) !== facts.target_language ||
    !isArtifactObservation(facts.source) ||
    facts.source.path !== `sources/${observation.slug}.pdf` ||
    !isArtifactObservation(facts.output) ||
    facts.output.path !==
      `processing/translations/${observation.slug}-${target}.pdf` ||
    !isArtifactObservation(facts.manifest) ||
    facts.manifest.path !==
      `processing/translations/${observation.slug}-${target}.manifest.json`
  )
    return null;
  return observation as unknown as TranslationStatusObservation;
};

const parseTranslationSeed = (value: unknown): TranslationSeed | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, ["state", "material_slug"]) ||
    value.state !== "canonical" ||
    !validMaterialSlug(value.material_slug)
  )
    return null;
  return value as unknown as TranslationSeed;
};

const parseTranslationOptions = (
  value: unknown,
  slug: string,
  targetLanguage: string,
): TranslationOptions | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(
      value,
      [],
      ["source_file", "toc_json", "toc_page_side"],
    )
  )
    return null;
  const sourceFile = Object.hasOwn(value, "source_file")
    ? value.source_file
    : null;
  const tocJson = Object.hasOwn(value, "toc_json") ? value.toc_json : null;
  const tocPageSide = Object.hasOwn(value, "toc_page_side")
    ? value.toc_page_side
    : "original";
  if (
    (sourceFile !== null &&
      (typeof sourceFile !== "string" ||
        !validRequestedTranslationSource(
          sourceFile,
          slug,
          targetLanguage,
        ))) ||
    (tocJson !== null && !validString(tocJson, 1, 2048)) ||
    !["original", "translated"].includes(tocPageSide as string)
  )
    return null;
  return {
    source_file: sourceFile as string | null,
    toc_json: tocJson as string | null,
    toc_page_side: tocPageSide as "original" | "translated",
  };
};

export const parseTranslationRunInput = (
  raw: unknown,
): TranslationRunInputResult => {
  const invalid = (): TranslationRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind: "translation",
      slug: requestedLeafSlug(raw),
    }),
  });
  if (
    !isRecord(raw) ||
    !exactEnvelopeKeys(
      raw,
      ["seed", "target_language", "observation", "options"],
      ["userDecision"],
    )
  )
    return invalid();
  const seed = parseTranslationSeed(raw.seed);
  const targetLanguage = normalizeLanguage(raw.target_language);
  const observation = parseTranslationStatusObservation(raw.observation);
  const userDecision = Object.hasOwn(raw, "userDecision")
    ? parseUserDecision(raw.userDecision)
    : null;
  if (
    seed === null ||
    targetLanguage === null ||
    observation === null ||
    observation.slug !== seed.material_slug ||
    observation.facts.target_language !== targetLanguage ||
    (Object.hasOwn(raw, "userDecision") && userDecision === null)
  )
    return invalid();
  const options = parseTranslationOptions(
    raw.options,
    seed.material_slug,
    targetLanguage,
  );
  if (options === null) return invalid();
  const route = {
    kind: "translation" as const,
    slug: seed.material_slug,
    target_language: targetLanguage,
  };
  const observations = sparseObservations<TranslationStatusObservation>([
    { route, observation },
  ]);
  if (
    observations === null ||
    !observations.has(observationKey(route))
  )
    return invalid();
  return {
    ok: true,
    value: {
      seed,
      target_language: targetLanguage,
      observations,
      options,
      userDecision,
    },
  };
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
