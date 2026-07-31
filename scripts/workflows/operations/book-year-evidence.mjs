import { exactKeys, validText } from "../runtime.mjs";

export const BOOK_TEMP_PATH =
  /^\.quasi\/temp\/downloads\/[A-Za-z0-9][A-Za-z0-9._-]{0,220}\.(?:epub|pdf)$/;

const nullableYear = (value) =>
  value === null ||
  (Number.isInteger(value) && value >= 1000 && value <= 2500);

// One exact Book year-evidence contract is shared by Search decisions,
// acquisition receipts, user gates, and material joins.
export function validYearEvidence(evidence, expectedYear) {
  if (
    !exactKeys(evidence, [
      "slug_year",
      "source_years",
      "pdf_signals",
      "recommended_year",
      "recommendation_reason",
      "verdict",
    ]) ||
    evidence.slug_year !== expectedYear ||
    !evidence.source_years ||
    typeof evidence.source_years !== "object" ||
    Array.isArray(evidence.source_years) ||
    Object.keys(evidence.source_years).length > 64 ||
    Object.entries(evidence.source_years).some(
      ([source, year]) =>
        !validText(source, 1, 200) || !nullableYear(year) || year === null,
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
      (year) => !nullableYear(year) || year === null,
    ) ||
    !nullableYear(evidence.recommended_year) ||
    !validText(evidence.recommendation_reason, 1, 4000) ||
    !["MATCH", "MISMATCH", "AMBIGUOUS"].includes(evidence.verdict)
  )
    return false;
  if (evidence.verdict === "MATCH") {
    const support = [
      ...Object.values(evidence.source_years),
      evidence.pdf_signals.first_published,
      evidence.pdf_signals.copyright_year,
      ...evidence.pdf_signals.other_years,
    ].filter((year) => year === evidence.recommended_year).length;
    return evidence.recommended_year === expectedYear && support >= 2;
  }
  if (evidence.verdict === "MISMATCH")
    return (
      evidence.recommended_year !== null &&
      evidence.recommended_year !== expectedYear
    );
  return evidence.recommended_year === null;
}
