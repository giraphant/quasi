/** @typedef {import("./artifact-contracts/generated.mjs").ArtifactTemplates} ArtifactTemplates */
/** @typedef {import("./artifact-contracts/generated.mjs").KindName} KindName */
/** @typedef {import("./artifact-contracts/generated.mjs").WorkflowContext} WorkflowContext */

/**
 * @param {WorkflowContext} source
 * @param {string} camel
 * @param {string} [snake]
 * @returns {any}
 */
export const contextValue = (source, camel, snake = camel) =>
  source[camel] === undefined ? source[snake] : source[camel];

/**
 * @param {KindName} kind
 * @param {string} slug
 * @param {unknown} rawContext
 * @param {readonly string[]} [artifactRoles]
 * @returns {WorkflowContext}
 */
export function operationContextBase(
  kind,
  slug,
  rawContext,
  artifactRoles = [],
) {
  const context = /** @type {WorkflowContext} */ (
    rawContext && typeof rawContext === "object" ? rawContext : {}
  );
  const artifactRoleSet = new Set(artifactRoles);
  const passthrough = Object.fromEntries(
    Object.entries(context).filter(([name]) => !artifactRoleSet.has(name)),
  );
  const meta = context.meta || context.identity || context;
  return {
    ...passthrough,
    kind,
    slug,
    meta,
    materialKey:
      contextValue(context, "materialKey", "material_key") ||
      `${kind}:${slug}`,
    mode: context.mode || "create",
    diagnostics: context.diagnostics || [],
    pass: context.pass || 1,
  };
}

const EXACT_TEMPLATE_VALUE = /^\{([A-Za-z][A-Za-z0-9]*)\}$/;
const TEMPLATE_VALUE = /\{([A-Za-z][A-Za-z0-9]*)\}/g;

/**
 * @param {ArtifactTemplates} templates
 * @param {unknown} rawContext
 * @param {WorkflowContext} context
 * @returns {WorkflowContext}
 */
export function expandArtifactTemplates(templates, rawContext, context) {
  const raw = /** @type {WorkflowContext} */ (
    rawContext && typeof rawContext === "object" ? rawContext : {}
  );
  const values = { ...raw, ...context };
  const expanded = Object.fromEntries(
    Object.entries(templates || {}).map(([role, template]) => {
      const exact = EXACT_TEMPLATE_VALUE.exec(template);
      return [
        role,
        exact
          ? values[exact[1]]
          : template.replace(TEMPLATE_VALUE, (_match, name) =>
              String(values[name]),
            ),
      ];
    }),
  );
  return { ...expanded, ...context };
}
