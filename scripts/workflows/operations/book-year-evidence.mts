import { exactKeys, validText } from "../runtime.mts";

export const BOOK_TEMP_PATH =
  /^\.quasi\/temp\/downloads\/[A-Za-z0-9][A-Za-z0-9._-]{0,220}\.(?:epub|pdf)$/;

export type BookYearVerdict = "MATCH" | "MISMATCH" | "AMBIGUOUS";

export interface BookYearEvidence {
  slug_year: number;
  source_years: Record<string, number>;
  pdf_signals: {
    first_published: number | null;
    copyright_year: number | null;
    original_year: number | null;
    other_years: number[];
  };
  recommended_year: number | null;
  recommendation_reason: string;
  verdict: BookYearVerdict;
}

const YEAR_SCHEMA = {
  type: "integer",
  minimum: 1500,
  maximum: 2030,
};

const NULLABLE_YEAR_SCHEMA = {
  type: ["integer", "null"],
  minimum: 1500,
  maximum: 2030,
};

export const BOOK_YEAR_EVIDENCE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "slug_year",
    "source_years",
    "pdf_signals",
    "recommended_year",
    "recommendation_reason",
    "verdict",
  ],
  properties: {
    slug_year: YEAR_SCHEMA,
    source_years: {
      type: "object",
      additionalProperties: YEAR_SCHEMA,
      maxProperties: 64,
    },
    pdf_signals: {
      type: "object",
      additionalProperties: false,
      required: [
        "first_published",
        "copyright_year",
        "original_year",
        "other_years",
      ],
      properties: {
        first_published: NULLABLE_YEAR_SCHEMA,
        copyright_year: NULLABLE_YEAR_SCHEMA,
        original_year: NULLABLE_YEAR_SCHEMA,
        other_years: {
          type: "array",
          maxItems: 64,
          items: YEAR_SCHEMA,
        },
      },
    },
    recommended_year: NULLABLE_YEAR_SCHEMA,
    recommendation_reason: {
      type: "string",
      minLength: 1,
      maxLength: 4000,
    },
    verdict: {
      type: "string",
      enum: ["MATCH", "MISMATCH", "AMBIGUOUS"],
    },
  },
};

const bookYear = (value: any): boolean =>
  Number.isInteger(value) && value >= 1500 && value <= 2030;

const nullableYear = (value: any): boolean =>
  value === null ||
  bookYear(value);

export const validBookTempPath = (value: unknown): value is string =>
  typeof value === "string" && BOOK_TEMP_PATH.test(value);

// Search, Acquire, and the Book gate share this one semantic parser.
export function parseBookYearEvidence(
  value: unknown,
): BookYearEvidence | null {
  const evidence = value as any;
  if (
    !exactKeys(evidence, [
      "slug_year",
      "source_years",
      "pdf_signals",
      "recommended_year",
      "recommendation_reason",
      "verdict",
    ]) ||
    !bookYear(evidence.slug_year) ||
    !evidence.source_years ||
    typeof evidence.source_years !== "object" ||
    Array.isArray(evidence.source_years) ||
    Object.keys(evidence.source_years).length > 64 ||
    Object.entries(
      evidence.source_years as Record<string, any>,
    ).some(
      ([source, year]) =>
        !validText(source, 1, 200) || !bookYear(year),
    ) ||
    !exactKeys(evidence.pdf_signals, [
      "first_published",
      "copyright_year",
      "original_year",
      "other_years",
    ]) ||
    !nullableYear(evidence.pdf_signals.first_published) ||
    !nullableYear(evidence.pdf_signals.copyright_year) ||
    !nullableYear(evidence.pdf_signals.original_year) ||
    !Array.isArray(evidence.pdf_signals.other_years) ||
    evidence.pdf_signals.other_years.length > 64 ||
    evidence.pdf_signals.other_years.some(
      (year: any) => !bookYear(year),
    ) ||
    !nullableYear(evidence.recommended_year) ||
    !validText(evidence.recommendation_reason, 1, 4000) ||
    !["MATCH", "MISMATCH", "AMBIGUOUS"].includes(evidence.verdict) ||
    (evidence.verdict === "MATCH" &&
      evidence.recommended_year !== evidence.slug_year) ||
    (evidence.verdict === "MISMATCH" &&
      (evidence.recommended_year === null ||
        evidence.recommended_year === evidence.slug_year)) ||
    (evidence.verdict === "AMBIGUOUS" &&
      evidence.recommended_year !== null)
  )
    return null;
  return evidence as BookYearEvidence;
}
