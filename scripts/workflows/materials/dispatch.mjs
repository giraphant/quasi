import { processMaterialIngress } from "./ingress.mjs";

export function createMaterialDispatch(runtime, processors) {
  return async function dispatchMaterial(kind, args, opts = {}) {
    switch (kind) {
      case "book":
        {
          const bookOpts = {
            batchYear: opts.batchYear === true,
            yearDecision:
              Object.prototype.hasOwnProperty.call(
                opts,
                "yearDecision",
              )
                ? opts.yearDecision
                : null,
          };
          if (opts.resolveIdentity === true)
            return processMaterialIngress(
              runtime,
              kind,
              args,
              (slug, meta) =>
                processors.processBook(slug, meta, bookOpts),
              bookOpts,
            );
          return processors.processBook(
            args.slug,
            args.meta || args,
            bookOpts,
          );
        }
      case "paper":
        if (opts.resolveIdentity === true)
          return processMaterialIngress(
            runtime,
            kind,
            args,
            processors.processPaper,
          );
        return processors.processPaper(args.slug, args.meta || args);
      case "talk":
        return processors.processTalk(args.slug, args.meta || args);
      default:
        throw new Error(`process-material: 未知 material kind "${kind}"`);
    }
  };
}
