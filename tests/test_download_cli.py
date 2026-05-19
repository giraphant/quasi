from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = PLUGIN_ROOT / "scripts" / "download" / "download.py"
COOKIECLOUD = PLUGIN_ROOT / "scripts" / "download" / "cookiecloud.py"


def run_download(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOWNLOAD), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_download_help_exposes_agent_contract():
    top = run_download("--help")
    assert top.returncode == 0
    assert "{book,paper,accept}" in top.stdout

    for args in [
        ("book", "candidates", "--help"),
        ("book", "fetch", "--help"),
        ("paper", "fetch", "--help"),
        ("accept", "--help"),
    ]:
        result = run_download(*args)
        assert result.returncode == 0


def test_legacy_flag_mode_is_removed():
    result = run_download("--doi", "10.1/example")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_legacy_batch_mode_is_removed():
    result = run_download("batch", "--manifest", "manifest.json")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_accept_moves_temp_file_to_sources(tmp_path):
    project = tmp_path / "project"
    temp_dir = project / ".quasi" / "temp" / "downloads"
    temp_dir.mkdir(parents=True)
    src = temp_dir / "candidate.pdf"
    src.write_bytes(b"%PDF- test content")

    result = subprocess.run(
        [
            sys.executable,
            str(DOWNLOAD),
            "accept",
            "--path",
            str(src),
            "--slug",
            "author-title-2024",
            "--kind",
            "paper",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["kind"] == "paper"
    assert payload["moved"] is True
    assert Path(payload["path"]).name == "author-title-2024.pdf"
    assert Path(payload["path"]).exists()
    assert not src.exists()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


def test_ezproxy_base_url_normalises_to_login_prefix():
    mod = _load_module(COOKIECLOUD, "cookiecloud_under_test")

    assert mod._ezproxy_login_url("https://ezproxy.example.edu") == (
        "https://ezproxy.example.edu/login?url="
    )
    assert mod._ezproxy_login_url("ezproxy.example.edu/") == (
        "https://ezproxy.example.edu/login?url="
    )


def test_cookiecloud_domain_filter_keeps_parent_and_subdomain_cookies():
    mod = _load_module(COOKIECLOUD, "cookiecloud_domain_filter_under_test")
    data = {
        "cookie_data": {
            "bucket": [
                {"domain": "oclc.org", "name": "root", "value": "r"},
                {"domain": ".idm.oclc.org", "name": "idm", "value": "i"},
                {
                    "domain": "www-tandfonline-com.eux.idm.oclc.org",
                    "name": "tnf",
                    "value": "t",
                },
                {"domain": "example.org", "name": "other", "value": "x"},
            ]
        }
    }

    records = mod._filter_cookie_records(data, "oclc.org")

    assert [(r["domain"], r["name"]) for r in records] == [
        ("oclc.org", "root"),
        ("idm.oclc.org", "idm"),
        ("www-tandfonline-com.eux.idm.oclc.org", "tnf"),
    ]


def test_ezproxy_cookie_header_uses_only_cookies_matching_request_host():
    mod = _load_module(DOWNLOAD, "download_cookie_header_under_test")
    config = {
        "domain": "oclc.org",
        "cookie_records": [
            {"domain": "oclc.org", "name": "root", "value": "r", "path": "/"},
            {"domain": "idm.oclc.org", "name": "idm", "value": "i", "path": "/"},
            {
                "domain": "journals-sagepub-com.eux.idm.oclc.org",
                "name": "sage",
                "value": "s",
                "path": "/",
            },
        ],
    }

    header = mod._ezproxy_cookie_header(
        config,
        "https://www-tandfonline-com.eux.idm.oclc.org/doi/pdf/10.1/example",
    )

    assert header == "root=r; idm=i"
