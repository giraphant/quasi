// Shared execution shell. Legacy graph nodes keep retryNull; the Paper vertical slice
// uses runOperation so a writer with an unknown outcome is never auto-replayed.

export const OVERWRITE = "\noverwrite: true";

export const AGENT_TIMEOUT_MS = 45 * 60 * 1000;

const UNKNOWN_AGENT_STATUSES = new Set([
  "cancelled",
  "canceled",
  "timeout",
  "timed_out",
]);

export function createRuntime({ agent, parallel, phase, log }) {
  const coalesced = new Map();
  const callAgent = (prompt, opts) =>
    Promise.resolve(agent(prompt, opts));

  const guard = (prompt, opts) => {
    let timer;
    const invocation = callAgent(prompt, opts);
    return Promise.race([
      invocation.finally(() => clearTimeout(timer)),
      new Promise((resolve) => {
        timer = setTimeout(() => {
          log(
            `⏱ ${opts.label} 超过 ${AGENT_TIMEOUT_MS / 60000} 分钟未返回,按死亡处理`,
          );
          resolve(null);
        }, AGENT_TIMEOUT_MS);
      }),
    ]);
  };

  const retryNull = async (prompt, opts, retrySuffix = "") =>
    (await guard(prompt, opts)) ??
    guard(prompt + retrySuffix, { ...opts, label: `${opts.label}:retry` });

  const invokeReadonly = async (prompt, opts) => {
    try {
      const receipt = await guard(prompt, opts);
      if (
        receipt == null ||
        UNKNOWN_AGENT_STATUSES.has(
          String(receipt && receipt.status).toLowerCase(),
        )
      )
        return null;
      return receipt;
    } catch (error) {
      log(
        `⚠ ${opts.label} 未能确认 Agent outcome: ${
          (error && error.message) || String(error)
        }`,
      );
      return null;
    }
  };

  const invokeWriter = async (prompt, opts) => {
    try {
      const receipt = await callAgent(prompt, opts);
      if (
        receipt == null ||
        UNKNOWN_AGENT_STATUSES.has(
          String(receipt && receipt.status).toLowerCase(),
        )
      )
        return null;
      return receipt;
    } catch (error) {
      log(
        `⚠ ${opts.label} 未能确认 Agent outcome: ${
          (error && error.message) || String(error)
        }`,
      );
      return null;
    }
  };

  const unknownReceipt = (spec, effect) => ({
    schema_version: "quasi.operation.runtime.receipt/0.1",
    key: spec.key,
    effect,
    status: effect === "writer" ? "blocked" : "failed",
    attempt: 1,
    artifact_roles: spec.artifactRoles || [],
    replay: spec.replay || "blocked",
    signal: null,
    failure: {
      // Paper predates the shared failure-code hook, so keep its literals as
      // the compatibility default. New material/document Operations pass an
      // explicit neutral code and never inherit a paper.* failure.
      code:
        spec.unknownFailureCode ||
        (effect === "writer"
          ? "paper.writer_outcome_unknown"
          : "paper.readonly_outcome_unknown"),
      operation_key: spec.key,
      outcome: "unknown",
      retryable: effect === "readonly",
    },
  });

  const runOperation = async (prompt, opts, spec) => {
    const effect = spec && spec.effect;
    const retry = spec && spec.retry;
    if (effect !== "readonly" && effect !== "writer")
      throw new Error(`unknown operation effect: ${effect}`);
    if (retry !== "safe" && retry !== "forbidden")
      throw new Error(`unknown operation retry policy: ${retry}`);
    if (effect === "writer" && retry !== "forbidden")
      throw new Error("writer operation retry policy must be forbidden");

    // A writer is one awaited Agent invocation. In particular it must not be
    // raced against the legacy graph timer: losing that race would leave a
    // background writer able to mutate the exact output after the graph had
    // already returned a blocked receipt.
    const first =
      effect === "writer"
        ? await invokeWriter(prompt, opts)
        : await invokeReadonly(prompt, opts);
    if (first != null) return first;

    // Only a side-effect-free operation may be retried after an unknown Agent
    // outcome. Writer safety is decided by an explicit later reconcile, never
    // by treating null as a known failure.
    if (effect === "readonly" && retry === "safe") {
      const second = await invokeReadonly(prompt, {
        ...opts,
        label: `${opts.label}:retry`,
      });
      if (second != null) return second;
    }
    return unknownReceipt(spec, effect);
  };

  const coalesce = (key, identity, task, onConflict) => {
    const current = coalesced.get(key);
    if (current) {
      if (current.identity !== identity)
        return Promise.resolve(onConflict());
      return current.promise;
    }
    const promise = Promise.resolve().then(task);
    coalesced.set(key, { identity, promise });
    return promise;
  };

  return {
    coalesce,
    guard,
    log,
    parallel,
    phase,
    retryNull,
    runOperation,
  };
}
