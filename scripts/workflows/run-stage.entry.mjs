import { defineOperation } from "./operations/define.mjs";
import { authorOperationRows } from "./operations/rows/author.mjs";
import { bookOperationRows } from "./operations/rows/book.mjs";
import { memberOperationRows } from "./operations/rows/member.mjs";
import { paperOperationRows } from "./operations/rows/paper.mjs";
import { materialSearchOperationRows } from "./operations/rows/search.mjs";
import { talkOperationRows } from "./operations/rows/talk.mjs";
import { topicOperationRows } from "./operations/rows/topic.mjs";
import { translationOperationRows } from "./operations/rows/translation.mjs";
import { makeOperationContext } from "./run-stage-context.mjs";

const descriptors = Object.fromEntries(
  [
    ...materialSearchOperationRows,
    ...paperOperationRows,
    ...bookOperationRows,
    ...talkOperationRows,
    ...translationOperationRows,
    ...topicOperationRows,
    ...authorOperationRows,
    ...memberOperationRows,
  ].map((row) => [row.operation, row]),
);

export const RUN_STAGE_REGISTRY = {
  paper: {
    search: "material.search", acquire: "paper.acquire", prepare: "paper.prepare",
    analyse: "paper.analyse", audit: "paper.audit",
  },
  book: {
    search: "material.search", acquire: "book.acquire", prepare: "book.prepare",
    analyse: "chapter.analyse", synthesise: "book.synthesise", audit: "book.audit",
  },
  talk: { prepare: "talk.prepare", analyse: "talk.analyse", audit: "talk.audit" },
  translation: { prepare: "translation.prepare" },
  topic: {
    steer: "topic.steer", webcard: "topic.webcard",
    "synthesise-overview": "topic.synthesise.overview",
    "synthesise-resources": "topic.synthesise.resources", audit: "topic.audit",
  },
  author: {
    "discover-books": "author.discover-books",
    "discover-papers": "author.discover-papers",
    "resolve-membership": "author.resolve-membership",
  },
  member: { "admission-probe": "member.admission-probe" },
};
RUN_STAGE_REGISTRY.translate = RUN_STAGE_REGISTRY.translation;

export const workflowMeta = {
  name: "run-stage",
  description: "Runs one schema-enforced quasi stage and returns its receipt verbatim",
  phases: [
    { title: "Recall" }, { title: "Search" }, { title: "Acquire" },
    { title: "Prepare" }, { title: "Analyse" }, { title: "Synthesise" },
    { title: "Audit" },
  ],
};

const errorResult = (code, args, message) => ({
  schema_version: "quasi.run-stage.error/0.1",
  status: "error",
  error: {
    code,
    message,
    kind: typeof args.kind === "string" ? args.kind : null,
    slug: typeof args.slug === "string" ? args.slug : null,
    stage: typeof args.stage === "string" ? args.stage : null,
  },
});

export function resolveStage(kind, stage) {
  const normalizedKind = typeof kind === "string" ? kind.trim().toLowerCase() : "";
  const normalizedStage = typeof stage === "string" ? stage.trim().toLowerCase() : "";
  const operation = RUN_STAGE_REGISTRY[normalizedKind]?.[normalizedStage];
  if (!operation) return null;
  const descriptor = descriptors[operation];
  return { kind: normalizedKind === "translate" ? "translation" : normalizedKind, operation, descriptor, row: defineOperation(descriptor) };
}

export async function run({ agent }, inputArgs) {
  const args = inputArgs && typeof inputArgs === "object" ? inputArgs : {};
  const resolved = resolveStage(args.kind, args.stage);
  if (!resolved) {
    const normalizedKind =
      typeof args.kind === "string" ? args.kind.trim().toLowerCase() : "";
    return errorResult(
      RUN_STAGE_REGISTRY[normalizedKind]
        ? "run-stage.unknown_stage"
        : "run-stage.unknown_kind",
      args,
      `No run-stage row for kind=${String(args.kind)} stage=${String(args.stage)}`,
    );
  }
  let context;
  let prompt;
  let schema;
  try {
    context = makeOperationContext(resolved.kind, args.slug, resolved.operation, args.context);
    prompt = resolved.row.prompt(context);
    schema = resolved.row.schema(context);
  } catch (error) {
    return errorResult("run-stage.invalid_context", args, error instanceof Error ? error.message : String(error));
  }
  return agent(prompt, {
    schema,
    agentType: resolved.descriptor.agentType,
    phase: resolved.descriptor.stage,
    label: `${args.slug}:${args.stage}`,
  });
}
