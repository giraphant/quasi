import { stageContract, stageReceiptSchema } from "../stage.mjs";
import { AUTHOR_ARTIFACT_CONTRACT } from "../artifact-contracts/generated.mjs";

const synthesisArtifactRoles = (role) => ({
  type: "array",
  minItems: 1,
  maxItems: 1,
  items: { const: role },
});

const synthesisTerminalPayloads = (mode) => ({
  complete: {
    required: ["action"],
    properties: {
      action: {
        type: "string",
        enum:
          mode === "create"
            ? ["create", "reconciled"]
            : ["repair", "reconciled"],
      },
    },
  },
  failed: {
    required: ["action"],
    properties: { action: { const: mode } },
  },
  blocked: {
    required: ["action"],
    properties: { action: { const: mode } },
  },
});

export const authorSynthesiseStageSchema = ({
  materialKey,
  inputs,
  mode,
  output,
}) =>
  stageReceiptSchema({
    operation: "author.synthesise",
    stage: "Synthesise",
    materialKey,
    effect: "writer",
    required: [
      "input_material_keys",
      "input_paths",
      "output_path",
      "artifact_roles",
      "materials_analyzed",
    ],
    properties: {
      input_material_keys: {
        const: inputs.map((input) => input.material_key),
      },
      input_paths: {
        const: inputs.map((input) => input.path),
      },
      output_path: { const: output },
      artifact_roles: synthesisArtifactRoles("canonical"),
      materials_analyzed: { const: inputs.length },
    },
    terminalPayloads: synthesisTerminalPayloads(mode),
  });

export const AUTHOR_SYNTHESISE_STAGE_CONTRACT = stageContract({
  schema: authorSynthesiseStageSchema({
    materialKey: "author:placeholder",
    inputs: [
      {
        material_key: "paper:placeholder",
        path: "vault/papers/placeholder.md",
      },
    ],
    mode: "create",
    output: "vault/authors/placeholder.md",
  }),
  complete: (receipt, context) =>
    [
      ...(context.mode === "create" ? ["create"] : ["repair"]),
      "reconciled",
    ].includes(receipt.terminal.action),
});

export function authorSynthesiseOperationPrompt(
  name,
  full,
  topic,
  inputs,
  mode = "create",
  diagnostics = [],
) {
  const output = `vault/authors/${name}.md`;
  const repair = mode === "repair";
  const request = {
    schema_version:
      "quasi.operation.author.synthesise.request/0.1",
    operation: "author.synthesise",
    stage: "Synthesise",
    material_key: `author:${name}`,
    collection_key: `author:${name}`,
    inputs: inputs.map((input) => ({
      material_key: input.material_key,
      kind: input.kind,
      id: input.id,
      role: "canonical",
      path: input.path,
      title: input.title,
    })),
    input_material_keys: inputs.map(
      (input) => input.material_key,
    ),
    input_paths: inputs.map((input) => input.path),
    output: { role: "canonical", path: output },
    identity: {
      slug: name,
      full_name: full,
      topic,
    },
    artifact_contract: AUTHOR_ARTIFACT_CONTRACT,
    frontmatter_seed: {
      type: "author",
      name: full,
    },
    mode,
    overwrite: repair,
    repair_diagnostics: repair ? diagnostics : [],
  };
  return JSON.stringify(request, null, 2);
}
