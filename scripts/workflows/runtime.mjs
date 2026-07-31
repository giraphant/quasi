// Shared execution shell. Legacy graph nodes keep retryNull; the Paper vertical slice
// uses runOperation so a writer with an unknown outcome is never auto-replayed.

export const OVERWRITE = "\noverwrite: true";

export const RUNTIME_RECEIPT_VERSION =
  "quasi.operation.runtime.receipt/0.1";

const CONTROL_CHARS = new RegExp("[\\u0000-\\u001f\\u007f-\\u009f]");

// Shared receipt-text primitives. Operation contracts and identity validators
// import these instead of keeping per-graph copies.
export const validText = (value, min, max) =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

export const optionalText = (value, max) =>
  value == null || value === "" || validText(value, 1, max);

export const exactKeys = (value, keys) =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

export function sameClosedValue(left, right) {
  if (Array.isArray(left) || Array.isArray(right))
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) =>
        sameClosedValue(value, right[index]),
      )
    );
  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(right, key) &&
          sameClosedValue(left[key], right[key]),
      )
    );
  }
  return Object.is(left, right);
}

const matchesType = (value, type) => {
  if (Array.isArray(type))
    return type.some((entry) => matchesType(value, entry));
  switch (type) {
    case "null":
      return value === null;
    case "array":
      return Array.isArray(value);
    case "object":
      return (
        !!value && typeof value === "object" && !Array.isArray(value)
      );
    case "string":
      return typeof value === "string";
    case "boolean":
      return typeof value === "boolean";
    case "integer":
      return Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    default:
      return false;
  }
};

// Schema validator used by foreign-receipt admission and pre-stage legacy
// operations, where Claude's terminal contract is not present. Covers the closed
// keyword subset the receipt schemas are allowed to use.
export function validateSchema(schema, value) {
  if (!schema || typeof schema !== "object") return true;
  if (
    schema.anyOf !== undefined &&
    !schema.anyOf.some((entry) => validateSchema(entry, value))
  )
    return false;
  if (schema.not !== undefined && validateSchema(schema.not, value))
    return false;
  if (schema.type !== undefined && !matchesType(value, schema.type))
    return false;
  if (
    schema.const !== undefined &&
    !sameClosedValue(value, schema.const)
  )
    return false;
  if (schema.enum !== undefined && !schema.enum.includes(value))
    return false;
  if (typeof value === "string") {
    if (
      schema.pattern !== undefined &&
      !new RegExp(schema.pattern).test(value)
    )
      return false;
    if (
      schema.minLength !== undefined &&
      value.length < schema.minLength
    )
      return false;
    if (
      schema.maxLength !== undefined &&
      value.length > schema.maxLength
    )
      return false;
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum)
      return false;
    if (schema.maximum !== undefined && value > schema.maximum)
      return false;
  }
  if (Array.isArray(value)) {
    if (
      schema.minItems !== undefined &&
      value.length < schema.minItems
    )
      return false;
    if (
      schema.maxItems !== undefined &&
      value.length > schema.maxItems
    )
      return false;
    if (schema.uniqueItems === true) {
      const seen = new Set(
        value.map((entry) => JSON.stringify(entry)),
      );
      if (seen.size !== value.length) return false;
    }
    if (
      schema.items !== undefined &&
      !value.every((entry) => validateSchema(schema.items, entry))
    )
      return false;
  }
  if (
    value &&
    typeof value === "object" &&
    !Array.isArray(value)
  ) {
    const properties = schema.properties || {};
    if (
      Array.isArray(schema.required) &&
      !schema.required.every((key) =>
        Object.prototype.hasOwnProperty.call(value, key),
      )
    )
      return false;
    for (const [key, entry] of Object.entries(value)) {
      if (
        !Object.prototype.hasOwnProperty.call(properties, key)
      ) {
        if (schema.additionalProperties === false) return false;
        continue;
      }
      if (!validateSchema(properties[key], entry)) return false;
    }
  }
  return true;
}

const DEFAULT_EDGES = {
  succeeded: "ok",
  failed: "failed",
  blocked: "blocked",
};

const TERMINAL_STATUSES = new Set([
  "complete",
  "needs_input",
  "blocked",
  "failed",
]);

const readableTerminal = (receipt) =>
  !!(
    receipt.terminal &&
    typeof receipt.terminal === "object" &&
    !Array.isArray(receipt.terminal) &&
    TERMINAL_STATUSES.has(receipt.terminal.status)
  );

// One shared receipt verdict for every Operation call. A contract lives beside
// its schema in scripts/workflows/operations/ and owns the status invariants;
// the graph consumes only the closed edge algebra:
//   unknown   — runtime receipt, the worker outcome was never observed
//   mismatch  — receipt failed an echo or a status invariant
//   reconcile — worker proved an existing output instead of writing
//   blocked   — typed unknown writer outcome, resume/reconcile territory
//   failed    — typed known failure
//   ok        — proven success
export function classifyReceipt(
  receipt,
  contract,
  context = {},
  hostSchema = null,
) {
  if (
    !receipt ||
    typeof receipt !== "object" ||
    Array.isArray(receipt)
  )
    return { edge: "unknown", receipt };
  if (receipt.schema_version === RUNTIME_RECEIPT_VERSION)
    return { edge: "unknown", receipt };
  if (contract.stage === true) {
    if (!readableTerminal(receipt)) return { edge: "unknown", receipt };
  } else if (!validateSchema(hostSchema || contract.schema, receipt)) {
    // Legacy operation receipts have not yet migrated to a host-enforced stage
    // terminal. Keep their shrinking compatibility boundary fail-closed.
    return { edge: "mismatch", receipt };
  }
  if (contract.echo && contract.echo(receipt, context) !== true)
    return { edge: "mismatch", receipt };
  const status = contract.status
    ? contract.status(receipt)
    : receipt.status;
  if (contract.statuses) {
    const invariant = contract.statuses[status];
    if (!invariant || invariant(receipt, context) !== true)
      return { edge: "mismatch", receipt };
  }
  if (
    contract.reconcile &&
    contract.reconcile(receipt, context) === true
  )
    return { edge: "reconcile", receipt };
  const edge = (contract.edges || DEFAULT_EDGES)[status];
  return edge ? { edge, receipt } : { edge: "mismatch", receipt };
}

export const AGENT_TIMEOUT_MS = 45 * 60 * 1000;
export const PHASE_AGENT_LIMIT = 5;

const UNKNOWN_AGENT_STATUSES = new Set([
  "cancelled",
  "canceled",
  "timeout",
  "timed_out",
]);

export function createRuntime({ agent, parallel, phase, log }) {
  const coalesced = new Map();
  const phaseLanes = new Map();

  const phaseKey = (opts) =>
    typeof (opts && opts.phase) === "string" && opts.phase.length > 0
      ? opts.phase
      : "__unphased__";

  const finishPhaseEntry = (key, lane, entry) => {
    if (entry.settled) return;
    entry.settled = true;
    lane.active -= 1;
    lane.running.delete(entry);
    if (lane.poisoned) {
      // A poisoned lane is reset only after every underlying invocation that
      // caused the saturation has actually settled. Until then new work must
      // fail closed instead of slipping in behind a timed-out guard.
      if (lane.active === 0) phaseLanes.delete(key);
      return;
    }
    drainPhase(key, lane);
    if (lane.active === 0 && lane.queue.length === 0)
      phaseLanes.delete(key);
  };

  const poisonPhaseIfSaturated = (lane) => {
    if (
      lane.poisoned ||
      lane.active !== PHASE_AGENT_LIMIT ||
      lane.running.size !== PHASE_AGENT_LIMIT ||
      ![...lane.running].every(
        (entry) => entry.guarded && entry.timedOut,
      )
    )
      return;
    lane.poisoned = true;
    const queued = lane.queue.splice(0);
    // These entries never started, so null is an honest unknown outcome for
    // both readonly and writer callers. In particular, a queued writer is not
    // replayed later after the lane recovers.
    for (const entry of queued) entry.resolve(null);
  };

  const drainPhase = (key, lane) => {
    while (
      !lane.poisoned &&
      lane.active < PHASE_AGENT_LIMIT &&
      lane.queue.length > 0
    ) {
      const next = lane.queue.shift();
      next.started = true;
      lane.active += 1;
      lane.running.add(next);
      Promise.resolve()
        .then(next.invoke)
        .then(next.resolve, next.reject)
        .then(() => finishPhaseEntry(key, lane, next));
    }
  };

  // This is a stage-UI/pipeline bound, not a global provider cap: each visible
  // processing phase owns an independent FIFO lane. A host adapter may still
  // impose its own global provider limit. The slot follows the underlying Agent
  // Promise, not a guard's timeout verdict, so a possibly-live background call
  // continues to count against its phase limit.
  const admitAgent = (opts, invoke, guarded = false) => {
    const key = phaseKey(opts);
    let lane = phaseLanes.get(key);
    if (!lane) {
      lane = {
        active: 0,
        poisoned: false,
        queue: [],
        running: new Set(),
      };
      phaseLanes.set(key, lane);
    }
    if (lane.poisoned)
      return { promise: Promise.resolve(null), timedOut: () => {} };

    let entry;
    const promise = new Promise((resolve, reject) => {
      entry = {
        guarded,
        invoke,
        reject,
        resolve,
        settled: false,
        started: false,
        timedOut: false,
      };
      lane.queue.push(entry);
      drainPhase(key, lane);
    });
    return {
      promise,
      timedOut: () => {
        if (!entry.started || entry.settled || entry.timedOut) return;
        entry.timedOut = true;
        poisonPhaseIfSaturated(lane);
      },
    };
  };

  const rawAgent = (prompt, opts) =>
    Promise.resolve().then(() => agent(prompt, opts));

  const scheduleAgent = (
    prompt,
    opts,
    { guarded = false, onStart = null } = {},
  ) =>
    admitAgent(opts, () => {
      if (onStart) onStart();
      return rawAgent(prompt, opts);
    }, guarded);

  const callAgent = (prompt, opts) =>
    scheduleAgent(prompt, opts).promise;

  const guard = (prompt, opts) => {
    let timer;
    let armTimeout;
    let admission;
    const timeout = new Promise((resolve) => {
      armTimeout = () => {
        timer = setTimeout(() => {
          admission.timedOut();
          log(
            `⏱ ${opts.label} 超过 ${AGENT_TIMEOUT_MS / 60000} 分钟未返回,按死亡处理`,
          );
          resolve(null);
        }, AGENT_TIMEOUT_MS);
      };
    });
    admission = scheduleAgent(prompt, opts, {
      guarded: true,
      onStart: armTimeout,
    });
    const invocation = admission.promise;
    return Promise.race([
      invocation.finally(() => clearTimeout(timer)),
      timeout,
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
    schema_version: RUNTIME_RECEIPT_VERSION,
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

  // runOperation plus the shared contract verdict. spec.contract names the
  // operation's receipt contract; spec.context carries the call's exact
  // identity (paths, mode, slug) consumed by echo and status invariants.
  const operate = async (prompt, opts, spec) => {
    const receipt = await runOperation(prompt, opts, spec);
    return classifyReceipt(
      receipt,
      spec.contract,
      spec.context || {},
      spec.contract.stage === true ? null : opts.schema || null,
    );
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
    operate,
    parallel,
    phase,
    retryNull,
    runOperation,
  };
}
