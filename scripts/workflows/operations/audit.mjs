import { authorAudit } from "./rows/author.mjs";

// Compatibility surface for the existing process-material graph. The
// descriptor row is the sole owner of the request, schema, and terminal
// contract; this module only adapts the older call signature.
export const authorAuditStageSchema = ({
  materialKey,
  target,
  pass,
}) => authorAudit.schema({ materialKey, target, pass });

export const AUTHOR_AUDIT_STAGE_CONTRACT = authorAudit.contract;

export function authorAuditPrompt(name, pass) {
  return authorAudit.prompt({
    materialKey: `author:${name}`,
    target: `vault/authors/${name}.md`,
    pass,
  });
}
