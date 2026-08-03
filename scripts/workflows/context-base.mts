import type {
  ArtifactTemplates,
  KindName,
  WorkflowContext,
} from "./artifact-contracts/generated.mjs";

export const contextValue = (
  source: WorkflowContext,
  camel: string,
  snake: string = camel,
): any =>
  source[camel] === undefined ? source[snake] : source[camel];

export function operationContextBase(
  kind: KindName,
  slug: string,
  rawContext: unknown,
  artifactRoles: readonly string[] = [],
): WorkflowContext {
  const context = (
    rawContext && typeof rawContext === "object" ? rawContext : {}
  ) as WorkflowContext;
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

export function expandArtifactTemplates(
  templates: ArtifactTemplates,
  rawContext: unknown,
  context: WorkflowContext,
): WorkflowContext {
  const raw = (
    rawContext && typeof rawContext === "object" ? rawContext : {}
  ) as WorkflowContext;
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
