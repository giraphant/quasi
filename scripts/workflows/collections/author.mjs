import {
  AUTHOR_DISCOVER_BOOKS_CONTRACT,
  AUTHOR_DISCOVER_BOOKS_SCHEMA,
  AUTHOR_DISCOVER_PAPERS_CONTRACT,
  AUTHOR_DISCOVER_PAPERS_SCHEMA,
  AUTHOR_RESOLVE_MEMBERSHIP_CONTRACT,
  AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA,
  authorDiscoveryPrompt,
  authorResolveMembershipPrompt,
} from "../operations/acquire.mjs";
import {
  AUTHOR_AUDIT_STAGE_CONTRACT,
  authorAuditPrompt,
  authorAuditStageSchema,
} from "../operations/audit.mjs";
import {
  AUTHOR_SYNTHESISE_STAGE_CONTRACT,
  authorSynthesiseOperationPrompt,
  authorSynthesiseStageSchema,
} from "../operations/synthesise.mjs";
import { AUTHOR_ARTIFACT_CONTRACT } from "../artifact-contracts/generated.mjs";
import { strictChildResult } from "../materials/member.mjs";
import { validText } from "../runtime.mjs";
import { stageIssue } from "../stage.mjs";

const AUTHOR_RECEIPT_VERSION =
  "quasi.collection.author.receipt/0.1";
const AUTHOR_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const AUTHOR_NAME_SCHEMA =
  AUTHOR_ARTIFACT_CONTRACT.identity.properties.name;

const operationFailure = (
  code,
  operationKey,
  outcome = "known",
  retryable = false,
  message = null,
) => ({
  code,
  operation_key: operationKey,
  outcome,
  retryable,
  ...(message ? { message } : {}),
});

function validateIdentity(name, meta) {
  if (typeof name !== "string" || !AUTHOR_SLUG.test(name))
    return {
      ok: false,
      code: "author.slug_invalid",
      message: "author slug is not canonical",
    };
  if (!meta || typeof meta !== "object" || Array.isArray(meta))
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "author metadata must be an object",
    };
  const full = Object.prototype.hasOwnProperty.call(
    meta,
    "full_name",
  )
    ? meta.full_name
    : Object.prototype.hasOwnProperty.call(meta, "fullName")
      ? meta.fullName
      : name;
  const topic = meta.topic || "";
  if (
    !validText(
      full,
      AUTHOR_NAME_SCHEMA.minLength,
      AUTHOR_NAME_SCHEMA.maxLength,
    )
  )
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "full_name is missing or invalid",
    };
  if (
    typeof topic !== "string" ||
    topic !== topic.trim() ||
    topic.length > 500 ||
    (topic !== "" && !validText(topic, 1, 500))
  )
    return {
      ok: false,
      code: "author.identity_invalid",
      message: "topic is invalid",
    };
  const rawBooks =
    meta.maxBooks === undefined ? 5 : meta.maxBooks;
  const rawPapers =
    meta.maxPapers === undefined ? 10 : meta.maxPapers;
  if (
    !Number.isInteger(rawBooks) ||
    rawBooks < 0 ||
    rawBooks > 5 ||
    !Number.isInteger(rawPapers) ||
    rawPapers < 0 ||
    rawPapers > 10 ||
    rawBooks + rawPapers < 1
  )
    return {
      ok: false,
      code: "author.budget_invalid",
      message:
        "maxBooks must be 0..5, maxPapers 0..10, and total positive",
    };
  const normalized = {
    full_name: full,
    topic,
    maxBooks: rawBooks,
    maxPapers: rawPapers,
  };
  return {
    ok: true,
    meta: normalized,
    fingerprint: JSON.stringify(normalized),
  };
}

function createState(name, meta) {
  return {
    name,
    full: meta.full_name,
    topic: meta.topic,
    collectionKey: `author:${name}`,
    output: `vault/authors/${name}.md`,
    maxBooks: meta.maxBooks,
    maxPapers: meta.maxPapers,
    operations: [],
    audit: [],
    members: [],
    artifact: null,
    outputExists: false,
    repaired: false,
    disposition: null,
    discoveryFailures: [],
    warnings: [],
    budgets: {
      books: { used: 0, limit: meta.maxBooks },
      papers: { used: 0, limit: meta.maxPapers },
      synthesis: { used: 0, limit: 1 },
      repair: { used: 0, limit: 1 },
      auditPasses: { used: 0, limit: 2 },
    },
  };
}

function collectionReceipt(
  state,
  {
    status,
    stage,
    failure = null,
    disposition = null,
  },
) {
  return {
    schema_version: AUTHOR_RECEIPT_VERSION,
    collection_key: state.collectionKey,
    kind: "author",
    id: state.name,
    status,
    disposition:
      disposition ||
      (["complete", "partial"].includes(status)
        ? state.repaired
          ? "repaired"
          : state.disposition || "created"
        : null),
    stage,
    members: state.members,
    artifact: state.artifact,
    operations: state.operations,
    audit: state.audit,
    budgets: state.budgets,
    warnings: state.warnings,
    failure,
    resume:
      status === "blocked"
        ? { operation_key: "author.reconcile" }
        : null,
  };
}

function legacyCounts(state) {
  const complete = state.members.filter(
    (member) => member.status === "complete",
  );
  const books = complete.filter(
    (member) => member.kind === "book",
  );
  const papers = complete.filter(
    (member) => member.kind === "paper",
  );
  const failedBooks = state.members.filter(
    (member) =>
      member.kind === "book" && member.status !== "complete",
  );
  const failedPapers = state.members.filter(
    (member) =>
      member.kind === "paper" && member.status !== "complete",
  );
  return {
    books,
    papers,
    legacy: {
      books: books.length,
      papers: papers.length,
      book_slugs: books.map((member) => member.id),
      paper_slugs: papers.map((member) => member.id),
      book_failures: failedBooks.length,
      paper_failures: failedPapers.length,
      year_warnings: (() => {
        const warnings = state.members
          .filter(
            (member) =>
              member.kind === "book" && member.year_warning,
          )
          .map((member) => ({
            slug: member.id,
            ...member.year_warning,
          }));
        return warnings.length ? warnings : null;
      })(),
    },
  };
}

function terminal(
  state,
  legacyStatus,
  collectionStatus,
  stage,
  failure = null,
  extra = {},
) {
  const counts = legacyCounts(state);
  return {
    name: state.name,
    status: legacyStatus,
    ...counts.legacy,
    ...extra,
    collection_receipt: collectionReceipt(state, {
      status: collectionStatus,
      stage,
      failure,
    }),
  };
}

function rejectedResult(name, validation, conflict = false) {
  const canonical =
    typeof name === "string" && AUTHOR_SLUG.test(name);
  const state = createState(
    canonical ? name : typeof name === "string" ? name : "",
    {
      full_name:
        canonical && validation.meta
          ? validation.meta.full_name
          : canonical
            ? name
            : "",
      topic: "",
      maxBooks: 0,
      maxPapers: 0,
    },
  );
  const failure = operationFailure(
    conflict ? "author.identity_conflict" : validation.code,
    "author.identity",
    "known",
    false,
    validation.message,
  );
  return terminal(
    state,
    "blocked",
    "blocked",
    "identity",
    failure,
  );
}

function emptyDiscovery(state, kind) {
  const key =
    kind === "book"
      ? "author.discover-books"
      : "author.discover-papers";
  return {
    schema_version: `quasi.operation.${key}.receipt/0.1`,
    key,
    effect: "readonly",
    status: "succeeded",
    attempt: 1,
    collection_key: state.collectionKey,
    kind,
    full_name: state.full,
    topic: state.topic,
    count: 0,
    candidates: [],
    failure: null,
  };
}

function demandIdentity(candidate) {
  if (candidate.kind === "book")
    return JSON.stringify({
      title: candidate.title,
      authors: candidate.authors,
      year: candidate.year,
      isbn: candidate.isbn,
      publisher: candidate.publisher,
      category: candidate.category,
    });
  return JSON.stringify({
    title: candidate.title,
    authors: candidate.authors,
    year: candidate.year,
    doi: candidate.doi,
    oa_url: candidate.oa_url,
    url: candidate.url,
    journal: candidate.journal,
  });
}

function buildDemands(candidates, resolved) {
  const demands = [];
  const byKey = new Map();
  for (let index = 0; index < candidates.length; index += 1) {
    const candidate = candidates[index];
    const row = resolved[index];
    const id = row.vault_slug || candidate.slug;
    const materialKey = `${candidate.kind}:${id}`;
    const identity = demandIdentity(candidate);
    const existing = byKey.get(materialKey);
    if (existing) {
      if (existing.identity !== identity)
        return {
          ok: false,
          failure: operationFailure(
            "author.membership_identity_conflict",
            "author.resolve-membership",
            "known",
            false,
            `conflicting identities resolved to ${materialKey}`,
          ),
        };
      continue;
    }
    const meta =
      candidate.kind === "book"
        ? {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            isbn: candidate.isbn,
            publisher: candidate.publisher,
            category: candidate.category,
            confidence: "verified",
          }
        : {
            title: candidate.title,
            authors: [...candidate.authors],
            year: candidate.year,
            doi: candidate.doi,
            oa_url: candidate.oa_url,
            url: candidate.url,
            journal: candidate.journal,
            confidence: "verified",
          };
    const demand = {
      kind: candidate.kind,
      id,
      material_key: materialKey,
      title: candidate.title,
      meta,
      identity,
    };
    byKey.set(materialKey, demand);
    demands.push(demand);
  }
  return { ok: true, demands };
}

function malformedChild(demand, message) {
  return {
    material_key: demand.material_key,
    kind: demand.kind,
    id: demand.id,
    status: "blocked",
    canonical_path: null,
    receipt: null,
    year_warning: null,
    title: demand.title,
    failure: operationFailure(
      "author.child_receipt_invalid",
      "author.join",
      "unknown",
      false,
      message,
    ),
  };
}

function synthesisInputs(state) {
  return state.members
    .filter((member) => member.status === "complete")
    .map((member) => ({
      material_key: member.material_key,
      kind: member.kind,
      id: member.id,
      path: member.canonical_path,
      title: member.title,
    }));
}

function ownedAuditPaths(receipt, output) {
  return [
    ...receipt.escalated.map((item) => item.path),
    ...receipt.mutated_paths,
  ].every((path) => path === output);
}

function stageFailure(receipt, fallback, operation, outcome = "known") {
  const issue = stageIssue(receipt);
  return operationFailure(
    (issue && issue.code) || fallback,
    operation,
    outcome,
    !!(issue && issue.retryable),
    (issue && issue.summary) || `${operation} did not complete`,
  );
}

async function runSynthesis(
  runtime,
  state,
  inputs,
  mode,
  diagnostics,
  label,
) {
  const synthesis = await runtime.operate(
    authorSynthesiseOperationPrompt(
      state.name,
      state.full,
      state.topic,
      inputs,
      mode,
      diagnostics,
    ),
    {
      phase: "Synthesise",
      agentType: "quasi:synthesis-agent",
      label,
      schema: authorSynthesiseStageSchema({
        materialKey: state.collectionKey,
        inputs,
        mode,
        output: state.output,
      }),
    },
    {
      key: "author.synthesise",
      effect: "writer",
      retry: "forbidden",
      replay: mode === "repair" ? "reconciled" : "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "author.writer_outcome_unknown",
      contract: AUTHOR_SYNTHESISE_STAGE_CONTRACT,
      context: { inputs, mode, output: state.output },
    },
  );
  const receipt = synthesis.receipt;
  state.operations.push(receipt);
  if (
    synthesis.edge === "unknown" ||
    synthesis.edge === "mismatch"
  ) {
    const failure = operationFailure(
      "author.writer_receipt_mismatch",
      "author.synthesise",
      "unknown",
      false,
      "writer receipt did not prove the exact contract",
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "synthesis",
        failure,
      ),
    };
  }
  if (synthesis.edge === "blocked")
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "synthesis",
        stageFailure(
          receipt,
          "author.synthesise_failed",
          "author.synthesise",
          "unknown",
        ),
      ),
    };
  if (synthesis.edge === "needs_input")
    return {
      terminal: terminal(
        state,
        "needs_input",
        "needs_input",
        "synthesis",
        stageFailure(receipt, "author.synthesise_failed", "author.synthesise"),
        { question: stageIssue(receipt).user_question },
      ),
    };
  if (synthesis.edge !== "ok") {
    const failure = stageFailure(
      receipt,
      "author.synthesise_failed",
      "author.synthesise",
    );
    return {
      terminal: terminal(
        state,
        "synth_failed",
        "failed",
        "synthesis",
        failure,
        { notes: failure.message || failure.code },
      ),
    };
  }
  const { action } = receipt.terminal;
  state.artifact = {
    role: "canonical",
    path: state.output,
    exists: true,
    producer:
      action === "reconciled"
        ? "author.synthesise:reconciled"
        : "author.synthesise",
  };
  if (action === "repair") {
    state.repaired = true;
    state.disposition = "repaired";
  } else if (action === "reconciled") {
    state.disposition = state.disposition || "reused";
  } else {
    state.disposition = "created";
  }
  return { receipt };
}

async function runAudit(runtime, state, pass, label) {
  const auditRun = await runtime.operate(
    authorAuditPrompt(state.name, pass),
    {
      phase: "Audit",
      agentType: "quasi:audit-agent",
      label,
      schema: authorAuditStageSchema({
        materialKey: state.collectionKey,
        target: state.output,
        pass,
      }),
    },
    {
      key: "author.audit",
      effect: "writer",
      retry: "forbidden",
      replay: "blocked",
      artifactRoles: ["canonical"],
      unknownFailureCode: "author.writer_outcome_unknown",
      contract: AUTHOR_AUDIT_STAGE_CONTRACT,
      context: { target: state.output, pass },
    },
  );
  const receipt = auditRun.receipt;
  state.operations.push(receipt);
  state.audit.push(receipt);
  state.budgets.auditPasses.used += 1;
  if (
    auditRun.edge === "unknown" ||
    auditRun.edge === "mismatch"
  ) {
    const failure = operationFailure(
      "author.writer_receipt_mismatch",
      "author.audit",
      "unknown",
      false,
      "writer receipt did not prove the exact audit contract",
    );
    return {
      terminal: terminal(
        state,
        "blocked",
        "blocked",
        "audit",
        failure,
      ),
    };
  }
  if (auditRun.edge === "needs_input")
    return {
      terminal: terminal(
        state,
        "needs_input",
        "needs_input",
        "audit",
        stageFailure(receipt, "author.audit_failed", "author.audit"),
        { question: stageIssue(receipt).user_question },
      ),
    };
  if (!ownedAuditPaths(receipt, state.output)) {
    const failure = operationFailure(
      "author.repair_owner_unknown",
      "author.audit",
      "known",
      false,
      "audit named a path outside the exact Author product",
    );
    return {
      terminal: terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        failure,
        { escalated: receipt.escalated },
      ),
    };
  }
  if (auditRun.edge !== "ok") {
    const failure = stageFailure(
      receipt,
      "author.audit_failed",
      "author.audit",
      auditRun.edge === "blocked" ? "unknown" : "known",
    );
    return {
      terminal: terminal(
        state,
        auditRun.edge === "blocked" ? "blocked" : "audit_escalated",
        auditRun.edge === "blocked" ? "blocked" : "failed",
        "audit",
        failure,
        { escalated: receipt.escalated },
      ),
    };
  }
  if (receipt.mutated_paths.includes(state.output)) {
    state.repaired = true;
    state.disposition = "repaired";
  }
  return {
    clean:
      receipt.terminal.status === "complete" &&
      receipt.remaining_violations === 0 &&
      receipt.escalated.length === 0,
    escalated: receipt.escalated,
  };
}

async function processAuthorStrict(
  runtime,
  dispatchMaterial,
  name,
  meta,
) {
  const state = createState(name, meta);
  const discoveryTasks = [];
  if (state.maxBooks > 0)
    discoveryTasks.push(() =>
      runtime
        .operate(
          authorDiscoveryPrompt(
            name,
            state.full,
            state.topic,
            "book",
            state.maxBooks,
          ),
          {
            phase: "Search",
            agentType: "quasi:discovery-agent",
            label: `${name}:discover-books`,
            schema: AUTHOR_DISCOVER_BOOKS_SCHEMA,
          },
          {
            key: "author.discover-books",
            effect: "readonly",
            retry: "safe",
            replay: "safe",
            artifactRoles: [],
            unknownFailureCode:
              "author.readonly_outcome_unknown",
            contract: AUTHOR_DISCOVER_BOOKS_CONTRACT,
            context: { state, count: state.maxBooks },
          },
        )
        .then((run) => ({ kind: "book", run })),
    );
  if (state.maxPapers > 0)
    discoveryTasks.push(() =>
      runtime
        .operate(
          authorDiscoveryPrompt(
            name,
            state.full,
            state.topic,
            "paper",
            state.maxPapers,
          ),
          {
            phase: "Search",
            agentType: "quasi:discovery-agent",
            label: `${name}:discover-papers`,
            schema: AUTHOR_DISCOVER_PAPERS_SCHEMA,
          },
          {
            key: "author.discover-papers",
            effect: "readonly",
            retry: "safe",
            replay: "safe",
            artifactRoles: [],
            unknownFailureCode:
              "author.readonly_outcome_unknown",
            contract: AUTHOR_DISCOVER_PAPERS_CONTRACT,
            context: { state, count: state.maxPapers },
          },
        )
        .then((run) => ({ kind: "paper", run })),
    );
  const discoveries = await runtime.parallel(discoveryTasks);
  const bookRun =
    discoveries.find((item) => item.kind === "book")?.run ||
    { edge: "ok", receipt: emptyDiscovery(state, "book") };
  const paperRun =
    discoveries.find((item) => item.kind === "paper")?.run ||
    { edge: "ok", receipt: emptyDiscovery(state, "paper") };
  const bookDiscovery = bookRun.receipt;
  const paperDiscovery = paperRun.receipt;
  state.operations.push(bookDiscovery, paperDiscovery);
  const invalid = [bookRun, paperRun].filter((run) =>
    ["unknown", "mismatch"].includes(run.edge),
  );
  if (invalid.length) {
    const failure = operationFailure(
      "author.discovery_receipt_invalid",
      "author.discovery",
      invalid.some((run) => run.edge === "unknown")
        ? "unknown"
        : "known",
      false,
      "discovery receipt did not prove the exact contract",
    );
    return terminal(
      state,
      "all_failed",
      "failed",
      "discovery",
      failure,
    );
  }
  if (bookRun.edge === "failed")
    state.discoveryFailures.push(bookDiscovery.failure);
  if (paperRun.edge === "failed")
    state.discoveryFailures.push(paperDiscovery.failure);
  const candidates = [
    ...bookDiscovery.candidates,
    ...paperDiscovery.candidates,
  ];
  if (!candidates.length) {
    const failure = operationFailure(
      state.discoveryFailures.length
        ? "author.discovery_failed"
        : "author.no_works",
      "author.discovery",
      "known",
      false,
      state.discoveryFailures.length
        ? "no usable candidate was discovered"
        : "discovery returned no representative works",
    );
    return terminal(
      state,
      state.discoveryFailures.length
        ? "all_failed"
        : "no_works",
      "failed",
      "discovery",
      failure,
    );
  }

  const membershipRun = await runtime.operate(
    authorResolveMembershipPrompt(
      name,
      state.output,
      candidates,
    ),
    {
      phase: "Search",
      agentType: "general-purpose",
      label: `${name}:resolve-membership`,
      schema: AUTHOR_RESOLVE_MEMBERSHIP_SCHEMA,
    },
    {
      key: "author.resolve-membership",
      effect: "readonly",
      retry: "safe",
      replay: "safe",
      artifactRoles: [],
      unknownFailureCode: "author.readonly_outcome_unknown",
      contract: AUTHOR_RESOLVE_MEMBERSHIP_CONTRACT,
      context: {
        state,
        requests: candidates.map(({ kind, slug }) => ({
          kind,
          slug,
        })),
      },
    },
  );
  const membership = membershipRun.receipt;
  state.operations.push(membership);
  if (
    membershipRun.edge === "unknown" ||
    membershipRun.edge === "mismatch"
  ) {
    const failure = operationFailure(
      "author.membership_receipt_invalid",
      "author.resolve-membership",
      membershipRun.edge === "unknown" ? "unknown" : "known",
      false,
      "membership receipt did not correlate exact requests",
    );
    return terminal(
      state,
      "blocked",
      "blocked",
      "membership",
      failure,
    );
  }
  if (membershipRun.edge !== "ok")
    return terminal(
      state,
      "all_failed",
      "failed",
      "membership",
      membership.failure,
    );
  state.outputExists = membership.output_exists;
  const grouped = buildDemands(candidates, membership.resolved);
  if (!grouped.ok)
    return terminal(
      state,
      "all_failed",
      "failed",
      "membership",
      grouped.failure,
    );

  runtime.log(
    `${name}: strict Author membership ${grouped.demands.length} unique works`,
  );
  const childResults = await runtime.parallel(
    grouped.demands.map((demand) => async () => {
      try {
        const result = await dispatchMaterial(
          demand.kind,
          { slug: demand.id, meta: demand.meta },
          demand.kind === "book" ? { batchYear: true } : {},
        );
        return { demand, result };
      } catch (error) {
        return {
          demand,
          error:
            (error && error.message) || String(error),
        };
      }
    }),
  );
  state.members = childResults.map(({ demand, result, error }) =>
    error
      ? malformedChild(demand, error)
      : strictChildResult(result, demand) ||
        malformedChild(
          demand,
          "child result did not carry its exact MaterialReceipt",
        ),
  );
  state.budgets.books.used = state.members.filter(
    (member) => member.kind === "book",
  ).length;
  state.budgets.papers.used = state.members.filter(
    (member) => member.kind === "paper",
  ).length;
  const inputs = synthesisInputs(state);
  if (!inputs.length) {
    const failure = operationFailure(
      "author.no_complete_members",
      "author.join",
      "known",
      false,
      "no child Material Loop completed with an exact canonical",
    );
    return terminal(
      state,
      "all_failed",
      "failed",
      "join",
      failure,
      { tried: state.members.length },
    );
  }

  state.budgets.synthesis.used = 1;
  const initialMode = state.outputExists ? "repair" : "create";
  const initialDiagnostics = state.outputExists
    ? [
        {
          path: state.output,
          kind: "membership_refresh",
          reason:
            "reconcile the existing Author product against the exact completed corpus",
        },
      ]
    : [];
  const synthesis = await runSynthesis(
    runtime,
    state,
    inputs,
    initialMode,
    initialDiagnostics,
    `${name}:synthesise`,
  );
  if (synthesis.terminal) return synthesis.terminal;

  let audited = await runAudit(
    runtime,
    state,
    1,
    `${name}:audit`,
  );
  if (audited.terminal) return audited.terminal;
  if (!audited.clean) {
    state.budgets.repair.used = 1;
    const repaired = await runSynthesis(
      runtime,
      state,
      inputs,
      "repair",
      audited.escalated,
      `${name}:synthesise-repair`,
    );
    if (repaired.terminal) return repaired.terminal;
    audited = await runAudit(
      runtime,
      state,
      2,
      `${name}:audit-2`,
    );
    if (audited.terminal) return audited.terminal;
    if (!audited.clean) {
      const failure = operationFailure(
        "author.repair_exhausted",
        "author.audit",
        "known",
        false,
        "Author output remains non-clean after one repair",
      );
      return terminal(
        state,
        "audit_escalated",
        "failed",
        "audit",
        failure,
        { escalated: audited.escalated },
      );
    }
  }

  const incomplete =
    state.discoveryFailures.length > 0 ||
    state.members.some(
      (member) => member.status !== "complete",
    );
  return terminal(
    state,
    "ok",
    incomplete ? "partial" : "complete",
    "complete",
  );
}

export async function processAuthor(
  runtime,
  materials,
  name,
  rawMeta,
) {
  runtime.phase("Search");
  const validation = validateIdentity(name, rawMeta);
  if (!validation.ok)
    return rejectedResult(name, validation);
  const dispatchMaterial =
    typeof materials === "function"
      ? materials
      : (kind, args, opts = {}) =>
          kind === "book"
            ? materials.processBook(
                args.slug,
                args.meta || args,
                opts,
              )
            : materials.processPaper(
                args.slug,
                args.meta || args,
              );
  return runtime.coalesce(
    `author:${name}`,
    validation.fingerprint,
    () =>
      processAuthorStrict(
        runtime,
        dispatchMaterial,
        name,
        validation.meta,
      ),
    () =>
      rejectedResult(
        name,
        {
          ...validation,
          code: "author.identity_conflict",
          message:
            "conflicting Author identity for one collection key",
        },
        true,
      ),
  );
}
