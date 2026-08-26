import {
  exactKeys,
  isRecord,
  validString,
} from "../shared/material-input.mts";

const exactEnvelopeKeys = exactKeys;

const SHA256 = /^[0-9a-f]{64}$/;

export type OcrMaterialKind = "paper" | "book";
export type OcrProfileName = "dsocr2-text" | "tesseract-text";

export interface OcrGenerationProfile {
  schema_version: "quasi.ocr.profile/0.2";
  language: "chi_sim+eng";
  text_extractor: "pymupdf";
  engine_order: Array<"dsocr2" | "tesseract">;
  chunk_pages: 16 | 32;
  name: OcrProfileName;
  validation_policy: "paper-text-v1" | "book-pdf-v1";
}

export interface OcrGenerationSource {
  path: string;
  sha256: string;
  size: number;
  pages: number;
}

export interface OcrGenerationPaths {
  lock: string;
  work_dir: string;
  progress: string;
  generation_dir: string;
  manifest: string;
  pdf: string;
  text: string;
}

export interface OcrGenerationRange {
  start_page: number;
  end_page: number;
  engine: "dsocr2" | "tesseract";
  path: string;
  sha256: string;
  pages: number;
}

export interface OcrGenerationProgress {
  completed_pages: number;
  total_pages: number;
  next_page: number | null;
  ranges: OcrGenerationRange[];
}

export interface OcrGenerationFileFact {
  path: string;
  exists: boolean;
  regular: boolean | null;
  sha256: string | null;
  size: number;
}

export interface OcrGenerationPdfFact extends OcrGenerationFileFact {
  pages: number;
}

export interface OcrGenerationTextFact extends OcrGenerationFileFact {
  utf8: boolean | null;
  chars: number;
  non_whitespace_chars: number;
}

export interface OcrGenerationObservation {
  state: "missing" | "in_progress" | "committed" | "invalid" | "unknown";
  material_key: string;
  kind: OcrMaterialKind;
  slug: string;
  generation_key: string;
  profile: OcrGenerationProfile;
  config_fingerprint: string;
  source: OcrGenerationSource;
  paths: OcrGenerationPaths;
  progress: OcrGenerationProgress | null;
  manifest: OcrGenerationFileFact;
  recovery_pdf: OcrGenerationPdfFact;
  normalized_text: OcrGenerationTextFact;
  failure: string | null;
}

const nonnegativeInteger = (value: unknown): value is number =>
  Number.isInteger(value) && (value as number) >= 0;

const parseProfile = (
  value: unknown,
  kind: OcrMaterialKind,
): OcrGenerationProfile | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, [
      "schema_version", "language", "text_extractor", "engine_order",
      "chunk_pages", "name", "validation_policy",
    ]) ||
    value.schema_version !== "quasi.ocr.profile/0.2" ||
    value.language !== "chi_sim+eng" ||
    value.text_extractor !== "pymupdf" ||
    !Array.isArray(value.engine_order) ||
    value.validation_policy !== (kind === "paper" ? "paper-text-v1" : "book-pdf-v1")
  ) return null;
  const ds =
    value.name === "dsocr2-text" && value.chunk_pages === 16 &&
    value.engine_order.length === 2 && value.engine_order[0] === "dsocr2" &&
    value.engine_order[1] === "tesseract";
  const tesseract =
    value.name === "tesseract-text" && value.chunk_pages === 32 &&
    value.engine_order.length === 1 && value.engine_order[0] === "tesseract";
  return ds || tesseract ? value as unknown as OcrGenerationProfile : null;
};

const validFileBase = (
  value: Record<string, unknown>, expectedPath: string,
): boolean => {
  if (
    value.path !== expectedPath || typeof value.exists !== "boolean" ||
    ![true, false, null].includes(value.regular as boolean | null) ||
    !nonnegativeInteger(value.size) ||
    !(value.sha256 === null || (typeof value.sha256 === "string" && SHA256.test(value.sha256)))
  ) return false;
  if (!value.exists) return value.regular === null && value.sha256 === null && value.size === 0;
  if (value.regular === false) return value.sha256 === null && value.size === 0;
  return value.regular === true && typeof value.sha256 === "string";
};

const parseFile = (
  value: unknown, expectedPath: string,
): OcrGenerationFileFact | null =>
  isRecord(value) &&
  exactEnvelopeKeys(value, ["path", "exists", "regular", "sha256", "size"]) &&
  validFileBase(value, expectedPath)
    ? value as unknown as OcrGenerationFileFact : null;

const parsePdf = (
  value: unknown, expectedPath: string,
): OcrGenerationPdfFact | null =>
  isRecord(value) &&
  exactEnvelopeKeys(value, ["path", "exists", "regular", "sha256", "size", "pages"]) &&
  validFileBase(value, expectedPath) && nonnegativeInteger(value.pages) &&
  (value.regular === true || value.pages === 0)
    ? value as unknown as OcrGenerationPdfFact : null;

const parseText = (
  value: unknown, expectedPath: string,
): OcrGenerationTextFact | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, [
      "path", "exists", "regular", "sha256", "size", "utf8", "chars",
      "non_whitespace_chars",
    ]) ||
    !validFileBase(value, expectedPath) ||
    ![true, false, null].includes(value.utf8 as boolean | null) ||
    !nonnegativeInteger(value.chars) || !nonnegativeInteger(value.non_whitespace_chars) ||
    (value.non_whitespace_chars as number) > (value.chars as number)
  ) return null;
  if (value.regular !== true)
    return value.utf8 === null && value.chars === 0 && value.non_whitespace_chars === 0
      ? value as unknown as OcrGenerationTextFact : null;
  return value as unknown as OcrGenerationTextFact;
};

const parseProgress = (
  value: unknown,
  sourcePages: number,
  profile: OcrGenerationProfile,
  workRoot: string,
): OcrGenerationProgress | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, ["completed_pages", "total_pages", "next_page", "ranges"]) ||
    !nonnegativeInteger(value.completed_pages) || value.total_pages !== sourcePages ||
    !Array.isArray(value.ranges) ||
    value.next_page !== ((value.completed_pages as number) < sourcePages
      ? (value.completed_pages as number) + 1 : null)
  ) return null;
  let cursor = 1;
  for (const range of value.ranges) {
    const expectedEnd = Math.min(cursor + profile.chunk_pages - 1, sourcePages);
    if (
      !isRecord(range) ||
      !exactEnvelopeKeys(range, ["start_page", "end_page", "engine", "path", "sha256", "pages"]) ||
      range.start_page !== cursor || range.end_page !== expectedEnd ||
      !profile.engine_order.includes(range.engine as "dsocr2" | "tesseract") ||
      range.pages !== (range.end_page as number) - cursor + 1 ||
      range.path !== (
        `${workRoot}/parts/part-${String(cursor).padStart(6, "0")}-` +
        `${String(expectedEnd).padStart(6, "0")}.${String(range.engine)}.pdf`
      ) ||
      typeof range.sha256 !== "string" || !SHA256.test(range.sha256)
    ) return null;
    cursor = (range.end_page as number) + 1;
  }
  return cursor - 1 === value.completed_pages
    ? value as unknown as OcrGenerationProgress : null;
};

export const parseOcrGenerationObservation = (
  value: unknown,
  expected: {
    kind: OcrMaterialKind;
    slug: string;
    source: { path: string; sha256: string; size: number };
  },
): OcrGenerationObservation | null => {
  if (
    !isRecord(value) ||
    !exactEnvelopeKeys(value, [
      "state", "material_key", "kind", "slug", "generation_key", "profile",
      "config_fingerprint", "source", "paths", "progress", "manifest",
      "recovery_pdf", "normalized_text", "failure",
    ]) ||
    !["missing", "in_progress", "committed", "invalid", "unknown"].includes(value.state as string) ||
    value.material_key !== `${expected.kind}:${expected.slug}` ||
    value.kind !== expected.kind || value.slug !== expected.slug ||
    typeof value.generation_key !== "string" || !SHA256.test(value.generation_key) ||
    typeof value.config_fingerprint !== "string" || !SHA256.test(value.config_fingerprint) ||
    !(value.failure === null || validString(value.failure, 1, 200)) ||
    !isRecord(value.source) ||
    !exactEnvelopeKeys(value.source, ["path", "sha256", "size", "pages"]) ||
    value.source.path !== expected.source.path || value.source.sha256 !== expected.source.sha256 ||
    value.source.size !== expected.source.size || !nonnegativeInteger(value.source.pages)
  ) return null;
  const profile = parseProfile(value.profile, expected.kind);
  if (profile === null) return null;
  const generation = value.generation_key;
  const materialRoot = `processing/${expected.kind === "paper" ? "papers" : "chapters"}/${expected.slug}`;
  const workRoot = `${materialRoot}/.ocr-work/${generation}`;
  const generationRoot = `${materialRoot}/ocr-generations/${generation}`;
  const expectedPaths: OcrGenerationPaths = {
    lock: `${materialRoot}/.ocr-generation.lock`,
    work_dir: workRoot,
    progress: `${workRoot}/ocr.progress.json`,
    generation_dir: generationRoot,
    manifest: `${generationRoot}/manifest.json`,
    pdf: `${generationRoot}/ocr.pdf`,
    text: `${generationRoot}/ocr.txt`,
  };
  if (
    !isRecord(value.paths) || !exactEnvelopeKeys(value.paths, Object.keys(expectedPaths)) ||
    Object.entries(expectedPaths).some(
      ([key, path]) => (value.paths as Record<string, unknown>)[key] !== path,
    )
  ) return null;
  const manifest = parseFile(value.manifest, expectedPaths.manifest);
  const pdf = parsePdf(value.recovery_pdf, expectedPaths.pdf);
  const text = parseText(value.normalized_text, expectedPaths.text);
  if (manifest === null || pdf === null || text === null) return null;
  const sourcePages = value.source.pages as number;
  const progress = value.progress === null
    ? null : parseProgress(value.progress, sourcePages, profile, workRoot);
  if (value.progress !== null && progress === null) return null;
  const absent = !manifest.exists && !pdf.exists && !text.exists;
  const state = value.state as OcrGenerationObservation["state"];
  if (
    (state === "missing" && (sourcePages < 1 || progress !== null || value.failure !== null || !absent)) ||
    (state === "in_progress" && (progress === null || value.failure !== null || !absent)) ||
    (state === "committed" && (
      sourcePages < 1 || progress !== null || value.failure !== null ||
      !manifest.exists || manifest.regular !== true || manifest.size < 1 ||
      !pdf.exists || pdf.regular !== true || pdf.pages !== sourcePages ||
      !text.exists || text.regular !== true || text.utf8 !== true || text.size < 1
    )) ||
    (["invalid", "unknown"].includes(state) && value.failure === null)
  ) return null;
  return value as unknown as OcrGenerationObservation;
};
