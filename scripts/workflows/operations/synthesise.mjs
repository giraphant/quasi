import { authorSynthesise } from "./rows/author.mjs";

// Compatibility surface for the existing process-material graph. The
// descriptor row is the sole owner of the request, schema, and terminal
// contract; this module only adapts the older call signature.
export const authorSynthesiseStageSchema = ({
  materialKey,
  inputs,
  mode,
  output,
}) => authorSynthesise.schema({ materialKey, inputs, mode, output });

export const AUTHOR_SYNTHESISE_STAGE_CONTRACT =
  authorSynthesise.contract;

export function authorSynthesiseOperationPrompt(
  name,
  fullName,
  topic,
  inputs,
  mode = "create",
  diagnostics = [],
) {
  return authorSynthesise.prompt({
    materialKey: `author:${name}`,
    name,
    fullName,
    topic,
    inputs,
    output: `vault/authors/${name}.md`,
    mode,
    diagnostics,
  });
}
