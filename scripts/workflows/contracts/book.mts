import {
  exactKeys,
  sameClosedValue,
  validText,
} from "../runtime.mts";
import {
  exactKeys as exactEnvelopeKeys,
  isArtifactObservation,
  isRecord,
  observationKey,
  parseLeafRunEnvelope,
  parseStatusEnvelope,
  requestedLeafSlug,
  sparseObservations,
  validAuthors,
  validMaterialSlug,
  validNullableString,
  validString,
  type ArtifactObservation,
  type LeafSeed,
  type QuasiStatusObservation,
  type SparseObservationMap,
  type UserDecision,
} from "../shared/material-input.mts";
import {
  invalidMaterialInputResult,
  type MaterialResult,
} from "../shared/material-result.mts";
import {
  parseBookYearEvidence,
  validBookTempPath,
  type BookYearEvidence,
} from "../operations/book-year-evidence.mts";

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

export interface BookIntake {
  title?: string;
  isbn?: string;
  authors?: string[];
  year?: number;
  publisher?: string;
  category?: BookIdentity["category"];
}

export type BookSeed = LeafSeed<BookIntake, BookIdentity>;

export interface BookChapterObservation {
  slot: string;
  title: string;
  filename: string;
  slug: string;
  word_count: number;
  start_page: number | null;
  end_page: number | null;
  input: ArtifactObservation;
  output: ArtifactObservation;
}

export interface BookStatusFacts {
  kind: "book";
  sources: Array<{
    format: "epub" | "pdf";
    artifact: ArtifactObservation;
  }>;
  manifest: ArtifactObservation & { valid: boolean };
  chapters: BookChapterObservation[];
  overview: ArtifactObservation;
}

export type BookStatusObservation = QuasiStatusObservation<
  "book",
  BookStatusFacts
>;

export interface BookRunInput {
  seed: BookSeed;
  observations: SparseObservationMap<BookStatusObservation>;
  options: Readonly<Record<string, unknown>>;
  userDecision: UserDecision | null;
}

export type BookRunInputResult =
  | { ok: true; value: BookRunInput }
  | { ok: false; result: MaterialResult };

export const parseBookIdentity = (
  value: unknown,
): BookIdentity | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, [
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

const optionalString = (
  value: Record<string, unknown>,
  key: string,
  minLength: number,
  maxLength: number,
): boolean =>
  !Object.hasOwn(value, key) ||
  validString(value[key], minLength, maxLength);

const parseBookIntake = (value: unknown): BookIntake | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, [], [
      "title",
      "isbn",
      "authors",
      "year",
      "publisher",
      "category",
    ]) ||
    (!Object.hasOwn(value, "title") && !Object.hasOwn(value, "isbn")) ||
    !optionalString(value, "title", 1, 500) ||
    !optionalString(value, "isbn", 1, 100) ||
    (Object.hasOwn(value, "authors") && !validAuthors(value.authors)) ||
    (Object.hasOwn(value, "year") &&
      (!Number.isInteger(value.year) ||
        (value.year as number) < 1500 ||
        (value.year as number) > 2030)) ||
    !optionalString(value, "publisher", 2, 500) ||
    (Object.hasOwn(value, "category") &&
      !["monograph", "edited-volume", "handbook", "other"].includes(
        value.category as string,
      ))
  )
    return null;
  return value as BookIntake;
};

const parseBookSeed = (value: unknown): BookSeed | null => {
  if (!isRecord(value)) return null;
  if (
    value.state === "provisional" &&
    exactEnvelopeKeys(value, ["state", "requested_slug", "hints"]) &&
    validMaterialSlug(value.requested_slug)
  ) {
    const hints = parseBookIntake(value.hints);
    return hints === null
      ? null
      : { state: "provisional", requested_slug: value.requested_slug, hints };
  }
  if (
    value.state === "canonical" &&
    exactEnvelopeKeys(value, ["state", "material_slug", "identity"]) &&
    validMaterialSlug(value.material_slug)
  ) {
    const identity = parseBookIdentity(value.identity);
    return identity === null
      ? null
      : { state: "canonical", material_slug: value.material_slug, identity };
  }
  return null;
};

export const parseBookStatusObservation = (
  value: unknown,
): BookStatusObservation | null => {
  const observation = parseStatusEnvelope(value, "book");
  if (observation === null) return null;
  const facts = observation.facts;
  const manifest = facts.manifest;
  if (
    !exactEnvelopeKeys(facts, [
      "kind",
      "sources",
      "manifest",
      "chapters",
      "overview",
    ]) ||
    facts.kind !== "book" ||
    !Array.isArray(facts.sources) ||
    !facts.sources.every(
      (item) =>
        isRecord(item) &&
        exactEnvelopeKeys(item, ["format", "artifact"]) &&
        ["epub", "pdf"].includes(item.format as string) &&
        isArtifactObservation(item.artifact),
    ) ||
    !isRecord(manifest) ||
    !exactEnvelopeKeys(manifest, ["path", "present", "usable", "valid"]) ||
    !isArtifactObservation({
      path: manifest.path,
      present: manifest.present,
      usable: manifest.usable,
    }) ||
    typeof manifest.valid !== "boolean" ||
    !Array.isArray(facts.chapters) ||
    !facts.chapters.every(
      (chapter) =>
        isRecord(chapter) &&
        exactEnvelopeKeys(chapter, [
          "slot",
          "title",
          "filename",
          "slug",
          "word_count",
          "start_page",
          "end_page",
          "input",
          "output",
        ]) &&
        typeof chapter.slot === "string" &&
        typeof chapter.title === "string" &&
        typeof chapter.filename === "string" &&
        validMaterialSlug(chapter.slug) &&
        Number.isInteger(chapter.word_count) &&
        (chapter.start_page === null || Number.isInteger(chapter.start_page)) &&
        (chapter.end_page === null || Number.isInteger(chapter.end_page)) &&
        isArtifactObservation(chapter.input) &&
        isArtifactObservation(chapter.output),
    ) ||
    !isArtifactObservation(facts.overview)
  )
    return null;
  return observation as unknown as BookStatusObservation;
};

export const bookObservationAdmitsIdentity = (
  observation: BookStatusObservation,
  identity: BookIdentity,
): boolean => {
  const diskIdentity = observation.identity;
  return (
    observation.facts.overview.present &&
    observation.facts.overview.usable &&
    isRecord(diskIdentity) &&
    diskIdentity.title === identity.title &&
    diskIdentity.year === identity.year &&
    Array.isArray(diskIdentity.authors) &&
    diskIdentity.authors.length === identity.authors.length &&
    diskIdentity.authors.every(
      (author, index) => author === identity.authors[index],
    )
  );
};

export const parseBookRunInput = (
  raw: unknown,
): BookRunInputResult => {
  const invalid = (): BookRunInputResult => ({
    ok: false,
    result: invalidMaterialInputResult({
      kind: "book",
      slug: requestedLeafSlug(raw),
    }),
  });
  const envelope = parseLeafRunEnvelope(raw);
  if (envelope === null) return invalid();
  const seed = parseBookSeed(envelope.seed);
  const observation = parseBookStatusObservation(envelope.observation);
  if (seed === null || observation === null) return invalid();
  const materialSlug =
    seed.state === "provisional" ? seed.requested_slug : seed.material_slug;
  const observations = sparseObservations<BookStatusObservation>([
    {
      route: { kind: "book", slug: materialSlug },
      observation,
    },
  ]);
  const bound =
    observations?.get(
      observationKey({ kind: "book", slug: materialSlug }),
    ) ?? null;
  if (
    observations === null ||
    (seed.state === "canonical" &&
      seed.material_slug !== seed.identity.slug &&
      (bound === null ||
        !bookObservationAdmitsIdentity(bound, seed.identity)))
  )
    return invalid();
  return {
    ok: true,
    value: {
      seed,
      observations,
      options: envelope.options,
      userDecision: envelope.userDecision,
    },
  };
};

export interface BookYearDecisionValue {
  current_identity: BookIdentity;
  tmp_path: string;
  year_evidence: BookYearEvidence;
  action: "accept-current" | "use-recommended-year";
}

export interface BookYearGate {
  kind: "book_year";
  operation: "book.acquire";
  material_key: string;
  current_identity: BookIdentity;
  question: string;
  tmp_path: string;
  year_evidence: BookYearEvidence;
  proposed_actions: Array<
    "accept-current" | "use-recommended-year"
  >;
}

export const parseBookYearDecisionValue = (
  value: unknown,
): BookYearDecisionValue | null => {
  if (
    !exactKeys(value, [
      "current_identity",
      "tmp_path",
      "year_evidence",
      "action",
    ])
  )
    return null;
  const decision = value as Record<string, unknown>;
  const currentIdentity = parseBookIdentity(decision.current_identity);
  const evidence = parseBookYearEvidence(decision.year_evidence);
  const action = decision.action;
  if (
    currentIdentity === null ||
    !validBookTempPath(decision.tmp_path) ||
    evidence === null ||
    evidence.slug_year !== currentIdentity.year ||
    (action === "accept-current" &&
      !["MISMATCH", "AMBIGUOUS"].includes(evidence.verdict)) ||
    (action === "use-recommended-year" &&
      evidence.verdict !== "MISMATCH") ||
    !["accept-current", "use-recommended-year"].includes(
      action as string,
    )
  )
    return null;
  return {
    current_identity: currentIdentity,
    tmp_path: decision.tmp_path,
    year_evidence: evidence,
    action,
  } as BookYearDecisionValue;
};

const validBookMaterialKey = (value: unknown): value is string =>
  typeof value === "string" &&
  value.startsWith("book:") &&
  validMaterialSlug(value.slice("book:".length));

export const parseBookYearGate = (
  receipt: any,
  currentIdentityValue: unknown,
): BookYearGate | null => {
  const currentIdentity = parseBookIdentity(currentIdentityValue);
  const terminal = receipt?.terminal;
  const issue = terminal?.issue;
  const evidence = parseBookYearEvidence(terminal?.year_evidence);
  if (
    currentIdentity === null ||
    receipt?.operation !== "book.acquire" ||
    !validBookMaterialKey(receipt?.material_key) ||
    !exactKeys(terminal, [
      "status",
      "issue",
      "tmp_path",
      "year_evidence",
      "proposed_actions",
    ]) ||
    terminal.status !== "needs_input" ||
    !exactKeys(issue, [
      "code",
      "operation",
      "summary",
      "user_question",
      "retryable",
    ]) ||
    issue.operation !== "book.acquire" ||
    !validText(issue.summary, 1, 4000) ||
    !validText(issue.user_question, 1, 4000) ||
    typeof issue.retryable !== "boolean" ||
    !validBookTempPath(terminal.tmp_path) ||
    evidence === null ||
    evidence.slug_year !== currentIdentity.year ||
    (evidence.verdict === "MISMATCH"
      ? issue.code !== "book.year_mismatch" ||
        !sameClosedValue(terminal.proposed_actions, [
          "accept-current",
          "use-recommended-year",
        ])
      : evidence.verdict === "AMBIGUOUS"
        ? issue.code !== "book.year_ambiguous" ||
          !sameClosedValue(terminal.proposed_actions, ["accept-current"])
        : true)
  )
    return null;
  return {
    kind: "book_year",
    operation: "book.acquire",
    material_key: receipt.material_key,
    current_identity: currentIdentity,
    question: issue.user_question,
    tmp_path: terminal.tmp_path,
    year_evidence: evidence,
    proposed_actions: terminal.proposed_actions,
  };
};

export interface BookStructureChapter {
  title: string;
  start: number;
  end: number;
}

export interface BookStructureCandidate {
  key: string;
  label: string;
  summary: string;
  chapter_count: number;
  chapters: BookStructureChapter[];
}

export type BookStructureConflict =
  | "chapter_boundaries"
  | "reading_order"
  | "included_material";

export interface BookStructureGate {
  kind: "book_structure";
  operation: "book.prepare";
  material_key: string;
  question: string;
  source_path: string;
  candidates: BookStructureCandidate[];
  conflicts: BookStructureConflict[];
}

export interface BookStructureDecisionValue {
  source_path: string;
  candidates: BookStructureCandidate[];
  conflicts: BookStructureConflict[];
  selected_candidate: BookStructureCandidate;
}

const BOOK_STRUCTURE_CONFLICTS = [
  "chapter_boundaries",
  "reading_order",
  "included_material",
] as const;

const parsedChapter = (value: any): BookStructureChapter | null => {
  if (
    !exactKeys(value, ["title", "start", "end"]) ||
    !validText(value.title, 1, 500) ||
    !Number.isInteger(value.start) ||
    !Number.isInteger(value.end) ||
    value.start < 1 ||
    value.end < value.start
  )
    return null;
  return value as BookStructureChapter;
};

const parsedCandidate = (value: any): BookStructureCandidate | null => {
  if (
    !exactKeys(value, [
      "key",
      "label",
      "summary",
      "chapter_count",
      "chapters",
    ]) ||
    !validText(value.key, 1, 80) ||
    !validText(value.label, 1, 500) ||
    !validText(value.summary, 1, 2000) ||
    !Number.isInteger(value.chapter_count) ||
    !Array.isArray(value.chapters) ||
    value.chapters.length < 1 ||
    value.chapters.length > 150 ||
    value.chapter_count !== value.chapters.length
  )
    return null;
  const chapters = value.chapters.map(parsedChapter);
  if (
    chapters.some((chapter: any) => chapter === null) ||
    chapters.some(
      (chapter: any, index: number) =>
        index > 0 && chapter.start <= chapters[index - 1]!.end,
    )
  )
    return null;
  return value as BookStructureCandidate;
};

const parsedCandidates = (value: unknown): BookStructureCandidate[] | null => {
  if (!Array.isArray(value) || value.length < 2 || value.length > 4)
    return null;
  const candidates = value.map(parsedCandidate);
  if (
    candidates.some((candidate) => candidate === null) ||
    new Set(candidates.map((candidate) => candidate!.key)).size !==
      candidates.length
  )
    return null;
  return candidates as BookStructureCandidate[];
};

const parsedConflicts = (
  value: unknown,
): BookStructureConflict[] | null => {
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > BOOK_STRUCTURE_CONFLICTS.length ||
    value.some(
      (conflict) =>
        typeof conflict !== "string" ||
        !BOOK_STRUCTURE_CONFLICTS.includes(
          conflict as BookStructureConflict,
        ),
    ) ||
    new Set(value).size !== value.length
  )
    return null;
  return value as BookStructureConflict[];
};

export const parseBookStructureGate = (
  receipt: any,
): BookStructureGate | null => {
  const terminal = receipt?.terminal;
  const issue = terminal?.issue;
  const candidates = parsedCandidates(terminal?.candidates);
  const conflicts = parsedConflicts(terminal?.conflicts);
  if (
    receipt?.operation !== "book.prepare" ||
    receipt?.format !== "pdf" ||
    !validText(receipt?.material_key, 1, 512) ||
    terminal?.status !== "needs_input" ||
    issue?.code !== "book.chapter_structure_ambiguous" ||
    issue?.operation !== "book.prepare" ||
    !validText(issue?.user_question, 1, 4000) ||
    !validText(terminal?.source_path, 1, 2048) ||
    terminal.source_path !== receipt.selected_source ||
    candidates === null ||
    conflicts === null
  )
    return null;
  return {
    kind: "book_structure",
    operation: "book.prepare",
    material_key: receipt.material_key,
    question: issue.user_question,
    source_path: terminal.source_path,
    candidates,
    conflicts,
  };
};

export const parseBookStructureDecisionValue = (
  value: unknown,
  expectedGate?: BookStructureGate,
): BookStructureDecisionValue | null => {
  if (
    !exactKeys(value, [
      "source_path",
      "candidates",
      "conflicts",
      "selected_candidate",
    ])
  )
    return null;
  const decision = value as Record<string, unknown>;
  if (!validText(decision.source_path, 1, 2048)) return null;
  const candidates = parsedCandidates(decision.candidates);
  const conflicts = parsedConflicts(decision.conflicts);
  const selected = parsedCandidate(decision.selected_candidate);
  if (
    candidates === null ||
    conflicts === null ||
    selected === null ||
    !candidates.some((candidate) =>
      sameClosedValue(candidate, selected),
    ) ||
    (expectedGate !== undefined &&
      (decision.source_path !== expectedGate.source_path ||
        !sameClosedValue(candidates, expectedGate.candidates) ||
        !sameClosedValue(conflicts, expectedGate.conflicts)))
  )
    return null;
  return value as BookStructureDecisionValue;
};
