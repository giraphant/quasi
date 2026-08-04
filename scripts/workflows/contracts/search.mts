import {
  parseBookIdentity,
  parsePaperIdentity,
  type BookIdentity,
  type PaperIdentity,
} from "../shared/material-input.mts";
import {
  exactKeys,
  sameClosedValue,
  validText,
} from "../runtime.mts";

export const IDENTITY_CONFLICTS = [
  "title",
  "authors",
  "year",
  "identifier",
  "edition",
  "publication_type",
] as const;

export type IdentityConflict = (typeof IDENTITY_CONFLICTS)[number];

export type IdentityCandidate =
  | { kind: "paper"; identity: PaperIdentity }
  | { kind: "book"; identity: BookIdentity };

export interface IdentityConflictGate {
  kind: "identity_conflict";
  operation: "material.search";
  material_key: string;
  question: string;
  candidates: IdentityCandidate[];
  conflicts: IdentityConflict[];
}

export interface IdentityConflictDecisionValue {
  candidates: IdentityCandidate[];
  conflicts: IdentityConflict[];
  selected_candidate: IdentityCandidate;
}

const parsedCandidate = (
  value: unknown,
  requestedKind?: "paper" | "book",
): IdentityCandidate | null => {
  if (!exactKeys(value, ["kind", "identity"])) return null;
  const candidate = value as Record<string, unknown>;
  if (candidate.kind === "paper" && requestedKind !== "book") {
    const identity = parsePaperIdentity(candidate.identity);
    return identity === null ? null : { kind: "paper", identity };
  }
  if (candidate.kind === "book") {
    const identity = parseBookIdentity(candidate.identity);
    return identity === null ? null : { kind: "book", identity };
  }
  return null;
};

const parsedCandidates = (
  value: unknown,
  requestedKind?: "paper" | "book",
): IdentityCandidate[] | null => {
  if (!Array.isArray(value) || value.length < 1 || value.length > 4)
    return null;
  const candidates = value.map((item) =>
    parsedCandidate(item, requestedKind),
  );
  if (
    candidates.some((candidate) => candidate === null) ||
    candidates.some((candidate, index) =>
      candidates
        .slice(0, index)
        .some((prior) => sameClosedValue(candidate, prior)),
    )
  )
    return null;
  return candidates as IdentityCandidate[];
};

const parsedConflicts = (value: unknown): IdentityConflict[] | null => {
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > IDENTITY_CONFLICTS.length ||
    value.some(
      (conflict) =>
        typeof conflict !== "string" ||
        !IDENTITY_CONFLICTS.includes(conflict as IdentityConflict),
    ) ||
    new Set(value).size !== value.length
  )
    return null;
  return value as IdentityConflict[];
};

export const parseIdentityConflictGate = (
  receipt: any,
  requestedKind: "paper" | "book",
): IdentityConflictGate | null => {
  const terminal = receipt?.terminal;
  const issue = terminal?.issue;
  const candidates = parsedCandidates(
    terminal?.candidates,
    requestedKind,
  );
  const conflicts = parsedConflicts(terminal?.conflicts);
  if (
    receipt?.operation !== "material.search" ||
    receipt?.kind !== requestedKind ||
    !validText(receipt?.material_key, 1, 512) ||
    terminal?.status !== "needs_input" ||
    issue?.code !== "material.identity_conflict" ||
    issue?.operation !== "material.search" ||
    !validText(issue?.user_question, 1, 4000) ||
    candidates === null ||
    conflicts === null
  )
    return null;
  return {
    kind: "identity_conflict",
    operation: "material.search",
    material_key: receipt.material_key,
    question: issue.user_question,
    candidates,
    conflicts,
  };
};

export const parseIdentityConflictDecisionValue = (
  value: unknown,
  expectedGate?: IdentityConflictGate,
  requestedKind?: "paper" | "book",
): IdentityConflictDecisionValue | null => {
  if (
    !exactKeys(value, [
      "candidates",
      "conflicts",
      "selected_candidate",
    ])
  )
    return null;
  const decision = value as Record<string, unknown>;
  const candidates = parsedCandidates(decision.candidates, requestedKind);
  const conflicts = parsedConflicts(decision.conflicts);
  const selected = parsedCandidate(
    decision.selected_candidate,
    requestedKind,
  );
  if (
    candidates === null ||
    conflicts === null ||
    selected === null ||
    !candidates.some((candidate) =>
      sameClosedValue(candidate, selected),
    ) ||
    (expectedGate !== undefined &&
      (!sameClosedValue(candidates, expectedGate.candidates) ||
        !sameClosedValue(conflicts, expectedGate.conflicts)))
  )
    return null;
  return value as IdentityConflictDecisionValue;
};
