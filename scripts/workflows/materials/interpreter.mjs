import { routeStageEdge } from "./route.mjs";

const directive = (value) =>
  value && typeof value === "object" && Object.hasOwn(value, "terminal")
    ? value
    : { value };

const stageCall = (stage, call = {}) => ({
  mode: "create",
  pass: 1,
  diagnostics: [],
  ...call,
  stage,
});

async function invoke(runtime, table, descriptor, state, meta, opts, call) {
  const operation = descriptor.row;
  const context = descriptor.context(state, meta, opts, call);
  if (context && context.terminal) return context;
  const spec = operation.spec(context);
  const run = await runtime.operate(
    operation.prompt(context),
    {
      phase: spec.stage,
      agentType: spec.agentType,
      label: descriptor.label(state, call, context),
      schema: operation.schema(context),
    },
    spec,
  );
  const options = descriptor.routeOptions
    ? descriptor.routeOptions(state, meta, opts, call, context)
    : {};
  return routeStageEdge(run, {
    ...options,
    state,
    stage: descriptor.receiptStage || descriptor.stage.toLowerCase(),
    operationKey: spec.key,
    emit: ({ status, receiptStatus, extra, failure }) =>
      table.emit(state, {
        status,
        receiptStatus,
        stage: descriptor.receiptStage || descriptor.stage.toLowerCase(),
        extra: extra || {},
        failure,
      }),
    unknown: (receipt) =>
      table.unknown(state, descriptor, receipt, options),
    mismatch: (receipt) =>
      table.mismatch(state, descriptor, receipt, options),
    onOk: (receipt) =>
      directive(descriptor.apply(state, receipt, meta, opts, call, context, runtime)),
  });
}

async function invokeFanOut(runtime, table, descriptor, state, meta, opts, call) {
  const fanOut = descriptor.fanOut;
  const items = call.items || fanOut.items(state, meta, opts, call);
  const runItems = async (selected, refill = false) => runtime.parallel(
    selected.map((item, index) => async () => {
      const itemCall = { ...call, item, index, refill };
      const routed = await invoke(
        runtime,
        table,
        {
          ...descriptor,
          row: fanOut.row || descriptor.row,
          context: fanOut.context,
          label: fanOut.label,
          routeOptions: fanOut.routeOptions || descriptor.routeOptions,
          apply: fanOut.apply,
        },
        state,
        meta,
        opts,
        itemCall,
      );
      return routed.terminal ? { terminal: routed.terminal } : routed.value;
    }),
  );
  const values = await runItems(items);
  const early = values.find((value) => value && value.terminal);
  if (early) return early;

  if (fanOut.retry) {
    const retryItems = fanOut.retry.items(state, values, items, call);
    if (retryItems.length) {
      if (fanOut.retry.before) fanOut.retry.before(state, retryItems, call);
      const retryValues = await runItems(retryItems, true);
      const retryEarly = retryValues.find((value) => value && value.terminal);
      if (retryEarly) return retryEarly;
      if (fanOut.retry.apply)
        fanOut.retry.apply(state, retryValues, retryItems, call);
    }
  }
  return directive(fanOut.join(state, values, items, meta, opts, call, runtime));
}

async function runStage(runtime, table, descriptor, state, meta, opts, call = {}) {
  const normalizedCall = stageCall(descriptor.stage, call);
  if (descriptor.skip && descriptor.skip(state, meta, opts, normalizedCall))
    return { value: undefined };
  runtime.phase(descriptor.phase || descriptor.stage);
  return descriptor.fanOut
    ? invokeFanOut(runtime, table, descriptor, state, meta, opts, normalizedCall)
    : invoke(runtime, table, descriptor, state, meta, opts, normalizedCall);
}

async function runValidated(runtime, table, slug, meta, opts) {
  const state = table.state(slug, meta, opts);
  const stages = new Map(table.stages.map((stage) => [stage.stage, stage]));
  for (const descriptor of table.stages) {
    const routed = await runStage(runtime, table, descriptor, state, meta, opts);
    if (routed.terminal) return routed.terminal;
    if (descriptor.after) {
      const after = directive(
        descriptor.after(state, routed.value, meta, opts, stageCall(descriptor.stage)),
      );
      if (after.terminal) return after.terminal;
    }
    if (!descriptor.repair) continue;

    const repair = descriptor.repair;
    const repairInput = repair.escalationsFrom(state, routed.value, meta, opts);
    if (repairInput === null) continue;
    if (repairInput && repairInput.terminal) return repairInput.terminal;
    const targets = repair.target(state, repairInput, routed.value, meta, opts);
    for (const target of targets) {
      if (target.when && !target.when(state, repairInput, routed.value)) continue;
      const targetStage = stages.get(target.stage);
      if (!targetStage)
        throw new Error(`unknown repair target stage: ${target.stage}`);
      const repaired = await runStage(
        runtime,
        table,
        targetStage,
        state,
        meta,
        opts,
        { ...target.call, mode: "repair", diagnostics: target.diagnostics || repairInput },
      );
      if (repaired.terminal) return repaired.terminal;
      if (target.after) {
        const after = directive(target.after(state, repaired.value, repairInput));
        if (after.terminal) return after.terminal;
      }
    }
    const reaudit = await runStage(
      runtime,
      table,
      descriptor,
      state,
      meta,
      opts,
      { mode: "repair", pass: 2 },
    );
    if (reaudit.terminal) return reaudit.terminal;
    const exhausted = repair.exhausted(state, reaudit.value, meta, opts);
    if (exhausted) return exhausted;
  }
  return table.complete(state, meta, opts);
}

export async function runMaterialLoop(runtime, table, slug, rawMeta, rawOpts = {}) {
  if (table.recallPhase) runtime.phase("Recall");
  const identity = table.identity.validate(slug, rawMeta, rawOpts);
  if (!identity.ok) return table.reject(slug, identity, false);
  const normalized = table.options
    ? table.options(slug, identity.meta, rawOpts)
    : { ok: true, value: rawOpts };
  if (!normalized.ok) return table.reject(slug, normalized, false);
  const key = table.identity.key(slug, identity.meta, normalized.value);
  const fingerprint = table.identity.fingerprint
    ? table.identity.fingerprint(slug, identity.meta, normalized.value)
    : identity.fingerprint;
  return runtime.coalesce(
    key,
    fingerprint,
    () => runValidated(runtime, table, slug, identity.meta, normalized.value),
    () => table.reject(slug, table.identity.conflict(identity), true),
  );
}
