import type {
  OperationName,
} from "../artifact-contracts/generated.mjs";
import type {
  ObservationRoute,
} from "./material-input.mts";
import type { IdentityConflictGate } from "../contracts/search.mts";
import type {
  BookIdentity,
  BookStructureGate,
  BookYearGate,
} from "../contracts/book.mts";
import type {
  TranslationConfigurationGate,
  TranslationSourceGate,
} from "../contracts/translation.mts";
import type {
  TopicGate,
  TopicPendingWork,
} from "../contracts/topic.mts";

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
  /** Runtime vault-owner slug; bibliographic identity may retain another slug. */
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
  | TopicGate;

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

export interface MaterialResultSeed {
  material: {
    requested: RequestedMaterialIdentity;
    canonical: CanonicalMaterialIdentity | null;
  };
}

const materialBase = (seed: MaterialResultSeed): MaterialResultBase => ({
  schema_version: MATERIAL_RESULT_VERSION,
  material: {
    requested: seed.material.requested,
    canonical: seed.material.canonical,
  },
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
