declare const process: {
  env: Record<string, string | undefined>;
  cwd: () => string;
};

const projectRoot = (): string => {
  const configured = process.env.CLAUDE_PROJECT_DIR;
  return configured && configured.trim().length > 0
    ? configured
    : process.cwd();
};

const lexicalResolve = (root: string, path: string): string => {
  const absolute = path.startsWith("/") ? path : `${root}/${path}`;
  const segments: string[] = [];
  for (const segment of absolute.split("/")) {
    if (segment === "" || segment === ".") continue;
    if (segment === "..") segments.pop();
    else segments.push(segment);
  }
  return `/${segments.join("/")}`;
};

export const projectPathIdentity = (path: string): string =>
  lexicalResolve(projectRoot(), path);
