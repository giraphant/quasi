import {
  CHAPTER_ARTIFACT_CONTRACT,
  PAPER_ARTIFACT_CONTRACT,
  TALK_ARTIFACT_CONTRACT,
} from "../artifact-contracts/generated.mjs";
import { composedSchema } from "./shared.mjs";

export const PAPER_ANALYSE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_path",
    "output_path",
    "artifact_roles",
    "action",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.paper.analyse.receipt/0.1",
    },
    key: { const: "paper.analyse" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "canonical" },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    failure: {
      type: ["object", "null"],
      additionalProperties: false,
      required: [
        "code",
        "operation_key",
        "outcome",
        "retryable",
      ],
      properties: {
        code: { type: "string" },
        operation_key: { const: "paper.analyse" },
        outcome: { type: "string", enum: ["known", "unknown"] },
        retryable: { const: false },
      },
    },
  },
};

export const CHAPTER_ANALYSE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_path",
    "output_path",
    "artifact_roles",
    "action",
    "write_state",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.chapter.analyse.receipt/0.1",
    },
    key: { const: "chapter.analyse" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_path: { type: "string" },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "chapter_canonical" },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    write_state: {
      type: "string",
      enum: ["written", "not_written", "unknown"],
    },
    failure: {
      type: ["object", "null"],
      additionalProperties: false,
      required: [
        "code",
        "operation_key",
        "outcome",
        "retryable",
      ],
      properties: {
        code: { type: "string" },
        operation_key: { const: "chapter.analyse" },
        outcome: { type: "string", enum: ["known", "unknown"] },
        retryable: { type: "boolean" },
      },
    },
  },
};

export const TALK_ANALYSE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "input_paths",
    "input_sha256s",
    "output_path",
    "artifact_roles",
    "action",
    "failure",
  ],
  properties: {
    schema_version: {
      const: "quasi.operation.talk.analyse.receipt/0.1",
    },
    key: { const: "talk.analyse" },
    effect: { const: "writer" },
    status: {
      type: "string",
      enum: ["succeeded", "failed", "blocked"],
    },
    attempt: { type: "integer", const: 1 },
    input_paths: {
      type: "array",
      minItems: 1,
      maxItems: 5,
      items: { type: "string" },
    },
    input_sha256s: {
      type: "array",
      minItems: 1,
      maxItems: 5,
      items: { type: "string" },
    },
    output_path: { type: "string" },
    artifact_roles: {
      type: "array",
      minItems: 1,
      maxItems: 1,
      items: { const: "canonical" },
    },
    action: {
      type: "string",
      enum: ["create", "repair", "reconciled"],
    },
    failure: {
      type: ["object", "null"],
      additionalProperties: false,
      required: [
        "code",
        "operation_key",
        "outcome",
        "retryable",
        "message",
      ],
      properties: {
        code: { type: "string" },
        operation_key: { const: "talk.analyse" },
        outcome: {
          type: "string",
          enum: ["known", "unknown"],
        },
        retryable: { const: false },
        message: { type: ["string", "null"] },
      },
    },
  },
};

const RECONCILE_CODE = "output_exists_requires_reconcile";

const nonReconcileFailure = (outcome) => ({
  type: "object",
  required: ["outcome", "code"],
  properties: {
    outcome: { const: outcome },
    code: { not: { const: RECONCILE_CODE } },
  },
});

// The create/repair action matrix rides the schema so a wrong receipt is
// bounced back to the still-running writer; the contract keeps only the
// reconcile-edge detector.
const paperAnalyseBranches = (mode) =>
  mode === "create"
    ? {
        succeeded: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            action: { const: "create" },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "create" },
            failure: nonReconcileFailure("known"),
          },
        },
        blocked_unknown: {
          properties: {
            status: { const: "blocked" },
            action: { const: "create" },
            failure: nonReconcileFailure("unknown"),
          },
        },
        blocked_reconcile: {
          properties: {
            status: { const: "blocked" },
            action: { const: "reconciled" },
            failure: {
              type: "object",
              required: ["outcome", "code"],
              properties: {
                outcome: { const: "known" },
                code: { const: RECONCILE_CODE },
              },
            },
          },
        },
      }
    : {
        succeeded: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            action: { enum: ["repair", "reconciled"] },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "repair" },
            failure: nonReconcileFailure("known"),
          },
        },
        blocked: {
          properties: {
            status: { const: "blocked" },
            action: { const: "repair" },
            failure: nonReconcileFailure("unknown"),
          },
        },
      };

export const paperAnalyseSchema = ({ mode, input, output }) =>
  composedSchema(
    PAPER_ANALYSE_SCHEMA,
    {
      input_path: { const: input },
      output_path: { const: output },
    },
    paperAnalyseBranches(mode),
  );

export const PAPER_ANALYSE_CONTRACT = {
  schema: PAPER_ANALYSE_SCHEMA,
  reconcile: (receipt, context) =>
    context.mode === "create" &&
    receipt.status === "blocked" &&
    receipt.action === "reconciled",
};

// The chapter.analyse write_state matrix rides the schema: succeeded proves
// written (or a repair reconciliation that wrote nothing), failed proves
// not_written, blocked leaves it unknown except for the typed create
// collision. The contract keeps only the reconcile-edge detector.
const chapterAnalyseBranches = (mode) =>
  mode === "create"
    ? {
        succeeded: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            action: { const: "create" },
            write_state: { const: "written" },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "create" },
            write_state: { const: "not_written" },
            failure: nonReconcileFailure("known"),
          },
        },
        blocked_unknown: {
          properties: {
            status: { const: "blocked" },
            action: { const: "create" },
            write_state: { const: "unknown" },
            failure: nonReconcileFailure("unknown"),
          },
        },
        blocked_reconcile: {
          properties: {
            status: { const: "blocked" },
            action: { const: "reconciled" },
            write_state: { const: "not_written" },
            failure: {
              type: "object",
              required: ["outcome", "code"],
              properties: {
                outcome: { const: "unknown" },
                code: { const: RECONCILE_CODE },
              },
            },
          },
        },
      }
    : {
        succeeded_repair: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            action: { const: "repair" },
            write_state: { const: "written" },
          },
        },
        succeeded_reconciled: {
          properties: {
            status: { const: "succeeded" },
            failure: { type: "null" },
            action: { const: "reconciled" },
            write_state: { const: "not_written" },
          },
        },
        failed: {
          properties: {
            status: { const: "failed" },
            action: { const: "repair" },
            write_state: { const: "not_written" },
            failure: nonReconcileFailure("known"),
          },
        },
        blocked: {
          properties: {
            status: { const: "blocked" },
            action: { const: "repair" },
            write_state: { const: "unknown" },
            failure: nonReconcileFailure("unknown"),
          },
        },
      };

export const chapterAnalyseSchema = ({ mode, input, output }) =>
  composedSchema(
    CHAPTER_ANALYSE_SCHEMA,
    {
      input_path: { const: input },
      output_path: { const: output },
    },
    chapterAnalyseBranches(mode),
  );

export const CHAPTER_ANALYSE_CONTRACT = {
  schema: CHAPTER_ANALYSE_SCHEMA,
  reconcile: (receipt, context) =>
    context.mode === "create" &&
    receipt.status === "blocked" &&
    receipt.action === "reconciled" &&
    receipt.failure.code === RECONCILE_CODE,
};

// The talk.analyse writer matrix and the exact ordered transcript-generation
// echo (paths and hashes) ride the schema as deep consts.
const modeActionBranches = (mode) => ({
  succeeded: {
    properties: {
      status: { const: "succeeded" },
      failure: { type: "null" },
      action:
        mode === "create"
          ? { const: "create" }
          : { enum: ["repair", "reconciled"] },
    },
  },
  failed: {
    properties: {
      status: { const: "failed" },
      action: { const: mode },
      failure: {
        type: "object",
        required: ["outcome"],
        properties: { outcome: { const: "known" } },
      },
    },
  },
  blocked: {
    properties: {
      status: { const: "blocked" },
      action: { const: mode },
      failure: {
        type: "object",
        required: ["outcome"],
        properties: { outcome: { const: "unknown" } },
      },
    },
  },
});

export const talkAnalyseSchema = ({ inputs, mode, output }) =>
  composedSchema(
    TALK_ANALYSE_SCHEMA,
    {
      input_paths: {
        const: inputs.map((input) => input.path),
      },
      input_sha256s: {
        const: inputs.map((input) => input.sha256),
      },
      output_path: { const: output },
    },
    modeActionBranches(mode),
  );

export const TALK_ANALYSE_CONTRACT = {
  schema: TALK_ANALYSE_SCHEMA,
};

export const TALK_EVIDENCE_RULES = [
  "inputs[0] 是 committed primary transcript，其余 inputs 是同一 generation 的 per-engine SRT evidence",
  "对照时间戳、人名、同音词和专业术语；优先采用多引擎一致且符合实际语境的内容",
  "引文、人物、著作和时间脉络必须能在 transcript evidence 中定位",
];

export function paperAnalyseOperationPrompt(
  slug,
  meta,
  input,
  mode = "create",
  diagnostics = [],
) {
  const output = `vault/papers/${slug}.md`;
  const repair = mode === "repair";
  const request = {
    schema_version: "quasi.operation.paper.analyse.request/0.1",
    operation: "paper.analyse",
    material_key: `paper:${slug}`,
    input: {
      role: "normalized_text",
      path: input,
    },
    output: {
      role: "canonical",
      path: output,
    },
    identity: {
      title: meta.title,
      authors: meta.authors,
      year: meta.year,
      doi: meta.doi || null,
      journal: meta.journal,
      confidence:
        meta.confidence === "verified" ? "verified" : "provided",
    },
    artifact_contract: PAPER_ARTIFACT_CONTRACT,
    frontmatter_seed: {
      type: "paper",
      title: meta.title,
      authors: meta.authors,
      year: meta.year,
      journal: meta.journal,
      doi: meta.doi || null,
    },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
  };
  return `Execute exactly one paper.analyse operation using this self-contained JSON request.
Do not reinterpret it as another operation and do not read project instruction files.
${JSON.stringify(request, null, 2)}`;
}

export function chapterAnalyseOperationPrompt(
  bookSlug,
  meta,
  chapter,
  input,
  output,
  mode = "create",
  diagnostics = [],
) {
  const repair = mode === "repair";
  const chapterLabel =
    chapter.chapter_label || chapter.label || `第${chapter.slot}章`;
  const chapterTitle = String(chapter.title || "").trim();
  const canonicalTitle = chapterTitle.startsWith(chapterLabel)
    ? chapterTitle
    : `${chapterLabel} ${chapterTitle}`.trim();
  const request = {
    schema_version: "quasi.operation.chapter.analyse.request/0.1",
    operation: "chapter.analyse",
    material_key: `book:${bookSlug}`,
    input: {
      role: "normalized_chapter",
      path: input,
    },
    output: {
      role: "chapter_canonical",
      path: output,
    },
    identity: {
      book_slug: bookSlug,
      book_title: meta.title,
      chapter_slot: chapter.slot,
      chapter_slug: chapter.slug,
      chapter_label: chapterLabel,
      chapter_title: chapter.title,
      authors:
        Array.isArray(chapter.authors) && chapter.authors.length
          ? chapter.authors
          : meta.authors,
      year: meta.year,
      confidence:
        meta.confidence === "verified" ? "verified" : "provided",
    },
    artifact_contract: CHAPTER_ARTIFACT_CONTRACT,
    frontmatter_seed: {
      type: "chapter",
      title: canonicalTitle,
      authors:
        Array.isArray(chapter.authors) && chapter.authors.length
          ? chapter.authors
          : meta.authors,
      year: meta.year,
      book: bookSlug,
    },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
  };
  return `Execute exactly one chapter.analyse operation using this self-contained JSON request.
Do not reinterpret it as another operation and do not read project instruction files.
${JSON.stringify(request, null, 2)}`;
}

export function talkAnalyseOperationPrompt(
  state,
  inputs,
  mode = "create",
  diagnostics = [],
) {
  const repair = mode === "repair";
  const request = {
    schema_version:
      "quasi.operation.talk.analyse.request/0.1",
    operation: "talk.analyse",
    material_key: state.materialKey,
    inputs: inputs.map((input) => ({
      role: input.role,
      path: input.path,
      sha256: input.sha256,
      size: input.size,
    })),
    output: { role: "canonical", path: state.canonical },
    identity: {
      title: state.title,
      date: state.date,
      media: state.media,
    },
    artifact_contract: TALK_ARTIFACT_CONTRACT,
    frontmatter_seed: {
      type: "talk",
      title: state.title,
      date: state.date,
      media: state.media,
    },
    evidence_rules: TALK_EVIDENCE_RULES,
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
  };
  return `Execute exactly one talk.analyse operation from this self-contained JSON request.
Do not reinterpret it as another operation or read project instruction files.
${JSON.stringify(request, null, 2)}`;
}
