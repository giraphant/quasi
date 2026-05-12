"""CookieCloud pull → in-memory EZProxy cookie dict.

Connection params come from plugin user-config env vars set by Claude Code
when the plugin is enabled (see `userConfig` in `.claude-plugin/plugin.json`).
The docs spec the env var name as `CLAUDE_PLUGIN_OPTION_<KEY>` but don't
specify whether `<KEY>` is uppercased or kept verbatim, so we probe both:

    CLAUDE_PLUGIN_OPTION_COOKIECLOUD_SERVER       (or cookiecloud_server)
    CLAUDE_PLUGIN_OPTION_COOKIECLOUD_UUID
    CLAUDE_PLUGIN_OPTION_COOKIECLOUD_PASSWORD     (sensitive → system keychain)
    CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_DOMAIN
    CLAUDE_PLUGIN_OPTION_COOKIECLOUD_LOGIN_URL    (optional)

No files are read or written. The pulled cookie dict is cached for the
lifetime of the Python process; `invalidate_cache()` forces a re-fetch on
the next `get_ezproxy_config()` call.
"""
from __future__ import annotations

import os
import sys

import requests

_cache: dict | None = None
_DEFAULT_LOGIN_URL = "http://ezp-prod1.hul.harvard.edu/login?url="


def _env(key: str) -> str:
    """Read an env var, trying upper/original case to handle Claude Code ambiguity."""
    prefix = "CLAUDE_PLUGIN_OPTION_"
    for variant in (f"{prefix}{key.upper()}", f"{prefix}{key}"):
        val = os.environ.get(variant, "").strip()
        if val:
            return val
    return ""


def _env_config() -> dict | None:
    server    = _env("cookiecloud_server")
    uuid      = _env("cookiecloud_uuid")
    password  = _env("cookiecloud_password")
    domain    = _env("cookiecloud_ezproxy_domain")
    login_url = _env("cookiecloud_login_url") or _DEFAULT_LOGIN_URL
    if not all([server, uuid, password, domain]):
        return None
    return {
        "server": server,
        "uuid": uuid,
        "password": password,
        "ezproxy_domain": domain,
        "login_url": login_url,
    }


def _fetch(cfg: dict, timeout: int = 15) -> dict | None:
    url = f"{cfg['server'].rstrip('/')}/get/{cfg['uuid']}"
    try:
        r = requests.post(url, json={"password": cfg["password"]}, timeout=timeout)
    except requests.RequestException as e:
        print(f"  cookiecloud fetch failed: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  cookiecloud HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return None
    try:
        data = r.json()
    except ValueError:
        print(f"  cookiecloud non-JSON response", file=sys.stderr)
        return None
    if "encrypted" in data and "cookie_data" not in data:
        print(f"  cookiecloud password rejected (got encrypted blob)", file=sys.stderr)
        return None
    return data


def _filter_cookies(data: dict, ezproxy_domain: str) -> dict[str, str]:
    """Pick cookies set on the EZProxy domain (exact match, leading-dot agnostic)."""
    target = ezproxy_domain.lstrip(".").lower()
    out: dict[str, str] = {}
    for bucket in data.get("cookie_data", {}).values():
        for c in bucket:
            dom = (c.get("domain") or "").lstrip(".").lower()
            if dom == target:
                name = c.get("name")
                value = c.get("value")
                if name and value:
                    out[name] = value
    return out


def get_ezproxy_config(verbose: bool = True) -> dict | None:
    """Return EZProxy config dict from CookieCloud (cached).

    Shape matches what download.py's `_build_ezproxy_session` expects:
        {"cookies": {name: value, ...}, "domain": "...", "login_url": "..."}

    Returns None when CookieCloud user-config is not set, the server is
    unreachable, the password is rejected, or no cookies match the configured
    EZProxy domain.
    """
    global _cache
    if _cache is not None:
        return _cache

    cfg = _env_config()
    if not cfg:
        return None

    data = _fetch(cfg)
    if not data:
        return None

    cookies = _filter_cookies(data, cfg["ezproxy_domain"])
    if not cookies:
        print(f"  cookiecloud: no cookies matched domain {cfg['ezproxy_domain']!r}",
              file=sys.stderr)
        return None

    _cache = {
        "cookies":   cookies,
        "domain":    cfg["ezproxy_domain"],
        "login_url": cfg["login_url"],
    }
    if verbose:
        print(f"  cookiecloud: {len(cookies)} cookies pulled "
              f"(domain {cfg['ezproxy_domain']!r})", file=sys.stderr)
    return _cache


def invalidate_cache() -> None:
    """Drop cached cookies so the next get_ezproxy_config() re-fetches."""
    global _cache
    _cache = None


def _debug_env() -> None:
    """Print which CLAUDE_PLUGIN_OPTION_* env vars are visible. For setup debugging."""
    keys = ["cookiecloud_server", "cookiecloud_uuid", "cookiecloud_password",
            "cookiecloud_ezproxy_domain", "cookiecloud_login_url"]
    seen = []
    missing = []
    for k in keys:
        # Don't print sensitive values, just flag presence
        for variant in (f"CLAUDE_PLUGIN_OPTION_{k.upper()}", f"CLAUDE_PLUGIN_OPTION_{k}"):
            if os.environ.get(variant, "").strip():
                seen.append(variant)
                break
        else:
            missing.append(k)
    print(f"env vars set:     {seen or '(none)'}")
    print(f"env vars missing: {missing or '(none)'}")
    cc_vars = [k for k in os.environ if k.startswith("CLAUDE_PLUGIN_OPTION_")]
    print(f"all CLAUDE_PLUGIN_OPTION_* visible: {cc_vars or '(none)'}")


if __name__ == "__main__":
    # CLI: print env-var visibility + resolved cookie set, exit 0/1.
    print("=== env probe ===")
    _debug_env()
    print("\n=== pull ===")
    cfg = get_ezproxy_config()
    if not cfg:
        print("cookiecloud: not configured or fetch failed", file=sys.stderr)
        sys.exit(1)
    print(f"domain:    {cfg['domain']}")
    print(f"login_url: {cfg['login_url']}")
    print(f"cookies:   {sorted(cfg['cookies'].keys())}")
    sys.exit(0)
