"""CookieCloud pull → write config/ezproxy.json.

CookieCloud (https://github.com/easychen/CookieCloud) is a self-hosted browser-
cookie sync service: a Chrome extension pushes E2E-encrypted cookies to the
server; consumers pull and decrypt. We use the server-side-decrypt endpoint
(POST /get/<uuid> with password in body) since the server is user-controlled.

Config: config/cookiecloud.json
    {
        "server":         "https://cookiecloud.example.com",
        "uuid":           "...",
        "password":       "...",
        "ezproxy_domain": ".idm.oclc.org",
        "login_url":      "https://login.eux.idm.oclc.org/login?url="
    }

Only cookies whose `domain` field contains `ezproxy_domain` are kept — that
naturally filters out unrelated tracking cookies from publisher pages.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

_PROJECT_DIR = Path.cwd()
_PROJECT_CONFIG = _PROJECT_DIR / "config"
COOKIECLOUD_PATH = _PROJECT_CONFIG / "cookiecloud.json"
EZPROXY_PATH = _PROJECT_CONFIG / "ezproxy.json"


def load_config(path: Path = COOKIECLOUD_PATH) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        cfg = json.load(f)
    required = ("server", "uuid", "password", "ezproxy_domain")
    if not all(cfg.get(k) for k in required):
        print(f"  cookiecloud config missing keys; need {required}", file=sys.stderr)
        return None
    return cfg


def fetch(cfg: dict, timeout: int = 15) -> dict | None:
    """Fetch and server-side-decrypt the cookie blob. Returns parsed JSON or None."""
    server = cfg["server"].rstrip("/")
    url = f"{server}/get/{cfg['uuid']}"
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


def filter_cookies(data: dict, ezproxy_domain: str) -> dict[str, str]:
    """Pick cookies set on the EZProxy domain (exact match, leading-dot agnostic).

    A cookie's `domain` attribute equals the EZProxy domain — typically the
    parent host like `.idm.oclc.org`. Tracking cookies set on rewritten
    publisher subdomains (`.foo-com.eux.idm.oclc.org`) are excluded.
    """
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


def refresh_ezproxy_config(verbose: bool = True) -> bool:
    """Pull from CookieCloud and write config/ezproxy.json. Returns True on success.

    Safe to call when CookieCloud is not configured — returns False quietly.
    """
    cfg = load_config()
    if not cfg:
        return False

    data = fetch(cfg)
    if not data:
        return False

    cookies = filter_cookies(data, cfg["ezproxy_domain"])
    if not cookies:
        print(f"  cookiecloud: no cookies matched domain {cfg['ezproxy_domain']!r}",
              file=sys.stderr)
        return False

    out = {
        "cookies":   cookies,
        "domain":    cfg["ezproxy_domain"],
        "login_url": cfg.get("login_url", "https://login.eux.idm.oclc.org/login?url="),
    }
    EZPROXY_PATH.parent.mkdir(parents=True, exist_ok=True)
    EZPROXY_PATH.write_text(json.dumps(out, indent=2))
    if verbose:
        print(f"  cookiecloud: wrote {len(cookies)} cookies → {EZPROXY_PATH}",
              file=sys.stderr)
    return True


if __name__ == "__main__":
    # CLI: `python3 cookiecloud.py` to force a refresh.
    ok = refresh_ezproxy_config()
    sys.exit(0 if ok else 1)
