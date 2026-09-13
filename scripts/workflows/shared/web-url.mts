// The Workflow sandbox exposes core ECMAScript only: `globalThis.URL` is absent
// there, so a WHATWG parser cannot be the gate for any material's web input.
// This self-contained normalizer is the sole comparison form in every runtime and
// mirrors scripts/webpage/webarchive.py::normalize_web_url, so the TypeScript gate
// and the Webpage capability agree on one canonical URL string.

const DIGITS = /^[0-9]+$/;
const FORBIDDEN_HOST_CHARACTER = /[\u0000-\u0020"#%\/:<>?@[\]^|\\]/;
const IPV6_HOST = /^\[[0-9a-f:.]+\]$/;

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
  const trimmed = value.replace(/^ +| +$/g, "");
  const schemeSeparator = trimmed.indexOf("://");
  if (schemeSeparator < 1) return null;
  const scheme = trimmed.slice(0, schemeSeparator).toLowerCase();
  if (scheme !== "http" && scheme !== "https") return null;
  const defaultPort = scheme === "http" ? 80 : 443;

  const rest = trimmed.slice(schemeSeparator + 3);
  const authority = rest.split(/[/?#]/, 1)[0];
  if (authority.includes("@")) return null;
  let host: string;
  let rawPort: string;
  if (authority.startsWith("[")) {
    const bracket = authority.indexOf("]");
    if (bracket < 0) return null;
    host = authority.slice(0, bracket + 1).toLowerCase();
    if (!IPV6_HOST.test(host)) return null;
    rawPort = authority.slice(bracket + 1);
  } else {
    const colon = authority.indexOf(":");
    host = (colon < 0 ? authority : authority.slice(0, colon)).toLowerCase();
    if (host.length === 0 || FORBIDDEN_HOST_CHARACTER.test(host)) return null;
    rawPort = colon < 0 ? "" : authority.slice(colon);
  }
  let port = "";
  if (rawPort.length > 0) {
    const digits = rawPort.slice(1);
    if (rawPort[0] !== ":" || (digits.length > 0 && !DIGITS.test(digits)))
      return null;
    const numeric = digits.length === 0 ? defaultPort : Number(digits);
    if (numeric > 65535) return null;
    if (numeric !== defaultPort) port = `:${numeric}`;
  }

  const tail = rest.slice(authority.length);
  const fragment = tail.indexOf("#");
  const beforeFragment = fragment < 0 ? tail : tail.slice(0, fragment);
  const queryStart = beforeFragment.indexOf("?");
  const path =
    queryStart < 0 ? beforeFragment : beforeFragment.slice(0, queryStart);
  const query = queryStart < 0 ? "" : beforeFragment.slice(queryStart + 1);
  return `${scheme}://${host}${port}${path.length === 0 ? "/" : path}${
    query.length === 0 ? "" : `?${query}`
  }`;
};
