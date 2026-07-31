// Small deterministic helpers shared by Operation schema builders.  This
// module contains no material policy and no Agent workflow.

export const composedSchema = (base, overrides, branches) => ({
  ...base,
  properties: { ...base.properties, ...overrides },
  anyOf: Object.values(branches),
});

export const posixSingleQuote = (value) =>
  `'${String(value).split("'").join("'\"'\"'")}'`;
