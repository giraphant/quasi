import type {
  OperationName,
} from "../artifact-contracts/generated.mjs";
import type {
  ObservationRoute,
} from "./material-input.mts";
import type { IdentityConflictGate } from "../contracts/search.mts";
import type { PaperSeed } from "../contracts/paper.mts";
import type {
  BookIdentity,
  BookSeed,
  BookStructureGate,
  BookYearGate,
} from "../contracts/book.mts";
import type {
  TranslationConfigurationGate,
  TranslationOptions,
  TranslationSeed,
  TranslationSourceGate,
} from "../contracts/translation.mts";
import type {
  TopicGate,
  TopicPendingWork,
  TopicResumeSeed,
  TopicChildRoute,
} from "../contracts/topic.mts";
import type { AuthorResumeSeed } from "../contracts/author.mts";

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

export type LeafGate =
  | IdentityConflictGate
  | BookYearGate
  | BookStructureGate
  | TranslationSourceGate
  | TranslationConfigurationGate;

export type LeafResumeSeed =
  | {
      route: { kind: "paper"; slug: string };
      seed: PaperSeed;
      options: Readonly<Record<string, unknown>>;
    }
  | {
      route: { kind: "book"; slug: string };
      seed: BookSeed;
      options: Readonly<Record<string, unknown>>;
    }
  | {
      route: {
        kind: "translation";
        slug: string;
        target_language: string;
      };
      seed: TranslationSeed;
      options: TranslationOptions;
    };

export type ComposedLeafResumeSeed =
  | Extract<LeafResumeSeed, { route: { kind: "paper" } }>
  | Extract<LeafResumeSeed, { route: { kind: "book" } }>;

export interface LeafCompositionOutcome {
  result: MaterialResult;
  continuation: ComposedLeafResumeSeed;
}

export type HigherOrderObservationResumeSeed =
  | AuthorResumeSeed
  | TopicResumeSeed;

export type ObservationResumeSeed =
  | LeafResumeSeed
  | HigherOrderObservationResumeSeed;

export type HigherOrderChildResumeSeed =
  | AuthorResumeSeed
  | Extract<TopicResumeSeed, { kind: "seed_child" | "material_work" }>;

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
      gate: LeafGate;
      resume_seed: LeafResumeSeed;
    })
  | (MaterialResultBase & {
      terminal: "needs_input";
      issue: MaterialIssue;
      gate: TopicGate;
    })
  | (MaterialResultBase & {
      terminal: "needs_input";
      issue: MaterialIssue;
      gate: {
        kind: "child";
        route: TopicChildRoute;
        gate: LeafGate;
      };
      routes: TopicChildRoute[];
      resume_seed: HigherOrderChildResumeSeed;
    })
  | (MaterialResultBase & {
      terminal: "needs_observation";
      issue: null;
      routes: ObservationRoute[];
      resume_seed: ObservationResumeSeed;
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
  gate: LeafGate,
  resumeSeed: LeafResumeSeed,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "needs_input",
  issue,
  gate,
  resume_seed: resumeSeed,
});

export const needsObservationMaterialResult = (
  seed: MaterialResultSeed,
  routes: ObservationRoute[],
  resumeSeed: ObservationResumeSeed,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "needs_observation",
  issue: null,
  routes,
  resume_seed: resumeSeed,
});

export const higherOrderNeedsInputMaterialResult = (
  seed: MaterialResultSeed,
  issue: MaterialIssue,
  route: TopicChildRoute,
  gate: LeafGate,
  routes: TopicChildRoute[],
  resumeSeed: HigherOrderChildResumeSeed,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "needs_input",
  issue,
  gate: { kind: "child", route, gate },
  routes,
  resume_seed: resumeSeed,
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
