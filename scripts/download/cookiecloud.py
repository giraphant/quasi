"""CookieCloud pull → in-memory EZProxy cookie dict.

Connection params come from `QUASI_COOKIECLOUD_*` env vars, injected by the
PreToolUse hook (`scripts/hooks/inject-userconfig.py`) from the plugin's
`userConfig`. The script never reads any config file — credentials flow
exclusively through the agent → hook → bash env → process chain.

No files are read or written. The pulled cookie dict is cached for the
lifetime of the Python process; `invalidate_cache()` forces a re-fetch on
the next `get_ezproxy_config()` call.
"""
from __future__ import annotations

import os
import re
import sys

import requests

_cache: dict | None = None


def _env_config() -> dict | None:
    server    = os.environ.get("QUASI_COOKIECLOUD_SERVER", "").strip()
    uuid      = os.environ.get("QUASI_COOKIECLOUD_UUID", "").strip()
    password  = os.environ.get("QUASI_COOKIECLOUD_PASSWORD", "").strip()
    domain    = os.environ.get("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "").strip()
    base_url  = os.environ.get("QUASI_COOKIECLOUD_EZPROXY_BASE_URL", "").strip()
    if not all([server, uuid, password, domain, base_url]):
        return None
    return {
        "server": server,
        "uuid": uuid,
        "password": password,
        "ezproxy_domain": domain,
        "login_url": _ezproxy_login_url(base_url),
    }


def _ezproxy_login_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    if not re.match(r"^https?://", base, re.IGNORECASE):
        base = f"https://{base}"
    return f"{base}/login?url="


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
    """Return EZProxy config dict from CookieCloud (cached)."""
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


if __name__ == "__main__":
    cfg = get_ezproxy_config()
    if not cfg:
        print("cookiecloud: not configured or fetch failed", file=sys.stderr)
        sys.exit(1)
    print(f"domain:    {cfg['domain']}")
    print(f"login_url: {cfg['login_url']}")
    print(f"cookies:   {sorted(cfg['cookies'].keys())}")
    sys.exit(0)
