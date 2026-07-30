export function createMaterialDispatch(runtime) {
  return async function dispatchMaterial(kind, args, opts = {}) {
    switch (kind) {
      case "book":
        return runtime.processBook(
          args.slug,
          args.meta || args,
          {
            batchYear: opts.batchYear === true,
            yearDecision:
              Object.prototype.hasOwnProperty.call(
                opts,
                "yearDecision",
              )
                ? opts.yearDecision
                : null,
          },
        );
      case "paper":
        return runtime.processPaper(args.slug, args.meta || args);
      case "talk":
        return runtime.processTalk(args.slug, args.meta || args);
      default:
        throw new Error(`process-material: 未知 material kind "${kind}"`);
    }
  };
}
