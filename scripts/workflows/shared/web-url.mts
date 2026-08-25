export const normalizeWebUrl = (value: unknown): string | null => {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 2048 ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  )
    return null;
  const schemeSeparator = value.indexOf("://");
  if (schemeSeparator < 1) return null;
  const rawAuthority = value
    .slice(schemeSeparator + 3)
    .split(/[/?#]/, 1)[0];
  if (rawAuthority.includes("@")) return null;
  let url: {
    protocol: string;
    hostname: string;
    username: string;
    password: string;
    hash: string;
    pathname: string;
    toString(): string;
  };
  try {
    const UrlConstructor = (globalThis as unknown as {
      URL: new (input: string) => typeof url;
    }).URL;
    url = new UrlConstructor(value);
  } catch {
    return null;
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.hostname.length === 0 ||
    url.username.length > 0 ||
    url.password.length > 0
  )
    return null;
  url.hash = "";
  if (url.pathname === "") url.pathname = "/";
  return url.toString();
};
