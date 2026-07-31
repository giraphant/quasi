import {
  CHAPTER_ARTIFACT_CONTRACT,
  PAPER_ARTIFACT_CONTRACT,
  TALK_ARTIFACT_CONTRACT,
} from "../artifact-contracts/generated.mjs";
import {
  stageContract,
  stageReceiptSchema,
} from "../stage.mjs";

const analysisArtifactRoles = (role) => ({
  type: "array",
  minItems: 1,
  maxItems: 1,
  items: { const: role },
});

const terminalActionPayloads = (mode, writeState = false) => ({
  complete: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: {
        type: "string",
        enum:
          mode === "create"
            ? ["create", "reconciled"]
            : ["repair", "reconciled"],
      },
      ...(writeState
        ? {
            write_state: {
              type: "string",
              enum: ["written", "not_written"],
            },
          }
        : {}),
    },
  },
  failed: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState
        ? { write_state: { const: "not_written" } }
        : {}),
    },
  },
  blocked: {
    required: ["action", ...(writeState ? ["write_state"] : [])],
    properties: {
      action: { const: mode },
      ...(writeState
        ? { write_state: { const: "unknown" } }
        : {}),
    },
  },
});

export const paperAnalyseStageSchema = ({
  materialKey,
  mode,
  input,
  output,
}) =>
  stageReceiptSchema({
    operation: "paper.analyse",
    stage: "Analyse",
    materialKey,
    effect: "writer",
    required: ["input_path", "output_path", "artifact_roles"],
    properties: {
      input_path: { const: input },
      output_path: { const: output },
      artifact_roles: analysisArtifactRoles("canonical"),
    },
    terminalPayloads: terminalActionPayloads(mode),
  });

export const PAPER_ANALYSE_STAGE_CONTRACT = stageContract({
  schema: paperAnalyseStageSchema({
    materialKey: "paper:placeholder",
    mode: "create",
    input: "processing/papers/placeholder/source.txt",
    output: "vault/papers/placeholder.md",
  }),
  complete: (receipt, context) =>
    [
      ...(context.mode === "create" ? ["create"] : ["repair"]),
      "reconciled",
    ].includes(receipt.terminal.action),
});

export const chapterAnalyseStageSchema = ({
  materialKey,
  mode,
  input,
  output,
}) =>
  stageReceiptSchema({
    operation: "chapter.analyse",
    stage: "Analyse",
    materialKey,
    effect: "writer",
    required: ["input_path", "output_path", "artifact_roles"],
    properties: {
      input_path: { const: input },
      output_path: { const: output },
      artifact_roles: analysisArtifactRoles("chapter_canonical"),
    },
    terminalPayloads: terminalActionPayloads(mode, true),
  });

export const CHAPTER_ANALYSE_STAGE_CONTRACT = stageContract({
  schema: chapterAnalyseStageSchema({
    materialKey: "book:placeholder",
    mode: "create",
    input: "processing/chapters/placeholder/01_chapter.txt",
    output: "vault/books/placeholder/ch01-chapter.md",
  }),
  complete: (receipt, context) => {
    const { action, write_state: writeState } = receipt.terminal;
    return (
      [
        ...(context.mode === "create" ? ["create"] : ["repair"]),
        "reconciled",
      ].includes(action) &&
      writeState === (action === "reconciled" ? "not_written" : "written")
    );
  },
});

export const talkAnalyseStageSchema = ({
  materialKey,
  inputs,
  mode,
  output,
}) =>
  stageReceiptSchema({
    operation: "talk.analyse",
    stage: "Analyse",
    materialKey,
    effect: "writer",
    required: [
      "input_paths",
      "input_sha256s",
      "output_path",
      "artifact_roles",
    ],
    properties: {
      input_paths: {
        const: inputs.map((input) => input.path),
      },
      input_sha256s: {
        const: inputs.map((input) => input.sha256),
      },
      output_path: { const: output },
      artifact_roles: analysisArtifactRoles("canonical"),
    },
    terminalPayloads: terminalActionPayloads(mode),
  });

export const TALK_ANALYSE_STAGE_CONTRACT = stageContract({
  schema: talkAnalyseStageSchema({
    materialKey: "talk:placeholder",
    inputs: [
      {
        path: "vault/talks/placeholder/transcript.md",
        sha256: "0".repeat(64),
      },
    ],
    mode: "create",
    output: "vault/talks/placeholder/talk.md",
  }),
  complete: (receipt, context) =>
    [
      ...(context.mode === "create" ? ["create"] : ["repair"]),
      "reconciled",
    ].includes(receipt.terminal.action),
});

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
    stage: "Analyse",
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
    stage: "Analyse",
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
    stage: "Analyse",
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
