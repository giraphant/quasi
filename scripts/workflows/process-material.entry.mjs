import { processAuthor } from "./collections/author.mjs";
import {
  processTranslation,
  translationDependencyFailure,
} from "./derivatives/translation.mjs";
import { createMaterialDispatch } from "./materials/dispatch.mjs";
import { processBook } from "./materials/book.mjs";
import { processPaper } from "./materials/paper.mjs";
import { processTalk } from "./materials/talk.mjs";
import { processTopic } from "./research/topic.mjs";
import { createRuntime } from "./runtime.mjs";

export const workflowMeta = {
  name: "process-material",
  description:
    "Moves academic materials through a shared processing pipeline",
  phases: [
    { title: "Recall" },
    { title: "Search" },
    { title: "Acquire" },
    { title: "Prepare" },
    { title: "Analyse" },
    { title: "Synthesise" },
    { title: "Audit" },
  ],
};

export async function run(primitives, inputArgs) {
  const runtime = createRuntime(primitives);
  const materialProcessors = {
    processBook: (slug, meta, opts) =>
      processBook(runtime, slug, meta, opts),
    processPaper: (slug, meta) =>
      processPaper(runtime, slug, meta),
    processTalk: (slug, meta) =>
      processTalk(runtime, slug, meta),
  };
  const dispatchMaterial = createMaterialDispatch(
    runtime,
    materialProcessors,
  );

  async function router(kind, args, opts = {}) {
    switch (kind) {
      case "book":
      case "paper":
      case "talk":
        return dispatchMaterial(kind, args, opts);
      case "author":
        return processAuthor(
          runtime,
          materialProcessors,
          args.name || args.author_name,
          args.meta || args,
        );
      case "topic":
        return processTopic(
          runtime,
          router,
          args.slug || args.topic_slug,
          args.meta || args,
        );
      case "translate":
        return processTranslation(
          runtime,
          args.slug,
          {
            ...(args.meta || args),
            source_decision:
              args.source_decision ||
              (args.meta && args.meta.source_decision) ||
              null,
          },
        );
      default:
        throw new Error(`process-material: 未知 kind "${kind}"`);
    }
  }

  const args = inputArgs || {};
  if (!args.kind)
    throw new Error(
      "process-material: 需要 args.kind(book|paper|talk|translate|author|topic)",
    );
  const entryOpts = {
    ...(["book", "paper"].includes(args.kind)
      ? { resolveIdentity: true }
      : {}),
    ...(args.kind === "book" &&
    Object.prototype.hasOwnProperty.call(args, "year_decision")
      ? { yearDecision: args.year_decision }
      : {}),
  };
  let result = await router(args.kind, args, entryOpts);
  if (
    args.kind === "paper" &&
    args.translate === true &&
    result &&
    result.status === "ok"
  ) {
    const receipt = result.material_receipt;
    const resolvedSlug = result.slug;
    const sources =
      receipt &&
      receipt.schema_version ===
        "quasi.material-loop.receipt/0.1" &&
      receipt.material_key === `paper:${resolvedSlug}` &&
      receipt.kind === "paper" &&
      receipt.id === resolvedSlug &&
      receipt.status === "complete" &&
      Array.isArray(receipt.artifacts)
        ? receipt.artifacts.filter(
            (artifact) =>
              artifact &&
              artifact.role === "source" &&
              artifact.exists === true &&
              artifact.path === `sources/${resolvedSlug}.pdf`,
          )
        : [];
    const translationMeta = {
      source_file:
        sources.length === 1 ? sources[0].path : null,
      target_language:
        args.target_language || "zh-CN",
      toc_json: args.toc_json || null,
      toc_page_side:
        args.toc_page_side || "original",
      source_decision: args.source_decision || null,
    };
    const translation =
      sources.length === 1
        ? await processTranslation(
            runtime,
            resolvedSlug,
            translationMeta,
          )
        : translationDependencyFailure(
            resolvedSlug,
            translationMeta,
            "translation.paper_source_missing",
            "Paper MaterialReceipt did not contain one exact source artifact",
          );
    result = {
      ...result,
      translation,
      translation_status: translation.status,
      translation_receipt:
        translation.translation_receipt,
    };
  }
  const id =
    result &&
    (result.slug || result.name || args.slug || args.name);
  runtime.log(
    `process-material result: kind=${args.kind} id=${id || "unknown"} status=${(result && result.status) || "unknown"}`,
  );
  return result;
}
