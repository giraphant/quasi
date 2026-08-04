import type {
  ArtifactTemplates,
  KindName,
  WorkflowContext,
} from "./artifact-contracts/generated.mjs";

const MATERIAL_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

export class InputContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputContractError";
  }
}

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
  if (typeof slug !== "string" || !MATERIAL_SLUG.test(slug))
    throw new InputContractError(`invalid material slug: ${String(slug)}`);
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

const templateValue = (
  values: WorkflowContext,
  name: string,
): string => {
  const value = values[name];
  if (typeof value !== "string" && typeof value !== "number")
    throw new InputContractError(
      `missing artifact template value: ${name}`,
    );
  return String(value);
};

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
          ? templateValue(values, exact[1])
          : template.replace(TEMPLATE_VALUE, (_match, name) =>
              templateValue(values, name),
            ),
      ];
    }),
  );
  return { ...expanded, ...context };
}
