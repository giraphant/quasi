import type {
  OperationName,
  StageReceipt,
} from "../artifact-contracts/generated.mjs";
import type {
  BookIdentity,
  PaperIdentity,
  QuasiStatusObservation,
} from "./material-input.mts";
import type { IdentityConflictGate } from "../contracts/search.mts";
import type {
  BookStructureGate,
  BookYearGate,
} from "../contracts/book.mts";
import type {
  TranslationConfigurationGate,
  TranslationSourceGate,
} from "../contracts/translation.mts";

export const MATERIAL_RESULT_VERSION = "quasi.material.result/0.1" as const;

export type MaterialKind =
  | "paper"
  | "book"
  | "talk"
  | "translation"
  | "author"
  | "topic";

export interface RequestedMaterialIdentity {
  kind: MaterialKind;
  slug: string | null;
}

export interface CanonicalMaterialIdentity {
  kind: MaterialKind;
  slug: string;
}

export interface ExactArtifactRef {
  role:
    | "source"
    | "normalized_text"
    | "manifest"
    | "chapter"
    | "canonical"
    | "overview"
    | "outline"
    | "resources"
    | "translation";
  path: string;
}

export type ObservationRoute =
  | { kind: "paper" | "book" | "talk"; slug: string }
  | {
      kind: "translation";
      slug: string;
      target_language: string;
    };

export type ObservationKey =
  | `paper:${string}`
  | `book:${string}`
  | `talk:${string}`
  | `translation:paper:${string}:${string}`;

export type SparseObservationMap = ReadonlyMap<
  ObservationKey,
  QuasiStatusObservation
>;

export interface SparseObservationInput {
  route: ObservationRoute;
  observation: QuasiStatusObservation;
}

export type MaterialNextRoute = {
  kind: "book";
  identity: BookIdentity;
};

export interface MaterialIssue {
  code: string;
  operation: OperationName | null;
  summary: string;
  retryable: boolean;
  observation_request: ObservationRoute | null;
}

export type DirectGate =
  | IdentityConflictGate
  | BookYearGate
  | BookStructureGate
  | TranslationSourceGate
  | TranslationConfigurationGate
  | {
      kind: "topic_seed";
      operation: null;
      question: string;
      seeds: Array<{
        kind: "paper" | "book" | "talk";
        slug: string;
        reason: string;
      }>;
    }
  | {
      kind: "topic_needs_seeds";
      operation: "topic.steer";
      question: string;
      suggested_queries: string[];
      uncovered_subquestions: string[];
    };

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

export type TypedGate =
  | DirectGate
  | {
      kind: "child";
      route: ObservationRoute;
      gate: DirectGate;
    };

export interface MaterialResultBase {
  schema_version: typeof MATERIAL_RESULT_VERSION;
  material: {
    requested: RequestedMaterialIdentity;
    canonical: CanonicalMaterialIdentity | null;
  };
  receipts: StageReceipt[];
}

export type MaterialResult =
  | (MaterialResultBase & {
      terminal: "complete";
      issue: null;
      artifacts: ExactArtifactRef[];
      next: MaterialNextRoute | null;
    })
  | (MaterialResultBase & {
      terminal: "needs_input";
      issue: MaterialIssue;
      gate: TypedGate;
    })
  | (MaterialResultBase & {
      terminal: "incomplete";
      issue: MaterialIssue & { code: "topic.round_limit" };
      artifacts: ExactArtifactRef[];
      pending_work: TopicPendingWork[];
    })
  | (MaterialResultBase & {
      terminal: "blocked" | "failed";
      issue: MaterialIssue;
    });

export type MaterialResultSeed = Omit<
  MaterialResultBase,
  "schema_version"
>;

const materialBase = (seed: MaterialResultSeed): MaterialResultBase => ({
  schema_version: MATERIAL_RESULT_VERSION,
  material: seed.material,
  receipts: seed.receipts,
});

export const completeMaterialResult = (
  seed: MaterialResultSeed,
  artifacts: ExactArtifactRef[],
  next: MaterialNextRoute | null,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "complete",
  issue: null,
  artifacts,
  next,
});

export const needsInputMaterialResult = (
  seed: MaterialResultSeed,
  issue: MaterialIssue,
  gate: TypedGate,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "needs_input",
  issue,
  gate,
});

export const incompleteTopicMaterialResult = (
  seed: MaterialResultSeed,
  issue: MaterialIssue & { code: "topic.round_limit" },
  artifacts: ExactArtifactRef[],
  pendingWork: TopicPendingWork[],
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "incomplete",
  issue,
  artifacts,
  pending_work: pendingWork,
});

export const stoppedMaterialResult = (
  seed: MaterialResultSeed,
  terminal: "blocked" | "failed",
  issue: MaterialIssue,
): MaterialResult => ({
  ...materialBase(seed),
  terminal,
  issue,
});

export const blockedMaterialResult = (
  seed: MaterialResultSeed,
  issue: MaterialIssue,
): MaterialResult => stoppedMaterialResult(seed, "blocked", issue);

export const failedMaterialResult = (
  seed: MaterialResultSeed,
  issue: MaterialIssue,
): MaterialResult => stoppedMaterialResult(seed, "failed", issue);

export const invalidMaterialInputResult = (
  requested: RequestedMaterialIdentity,
): MaterialResult =>
  stoppedMaterialResult(
    {
      material: { requested, canonical: null },
      receipts: [],
    },
    "blocked",
    {
      code: "material.invalid_input",
      operation: null,
      summary: "Material Workflow input is invalid.",
      retryable: false,
      observation_request: null,
    },
  );
