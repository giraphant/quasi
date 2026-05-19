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


def test_ezproxy_base_url_normalises_to_login_prefix():
    spec = importlib.util.spec_from_file_location("cookiecloud_under_test", COOKIECLOUD)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    assert mod._ezproxy_login_url("https://ezproxy.example.edu") == (
        "https://ezproxy.example.edu/login?url="
    )
    assert mod._ezproxy_login_url("ezproxy.example.edu/") == (
        "https://ezproxy.example.edu/login?url="
    )
