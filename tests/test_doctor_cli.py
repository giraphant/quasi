from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = PLUGIN_ROOT / "scripts" / "doctor" / "doctor.py"
DOCTOR_BIN = PLUGIN_ROOT / "bin" / "quasi-doctor"


def run_doctor(data_dir: Path, *args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(data_dir)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(DOCTOR), *args],
        text=True,
        capture_output=True,
        timeout=20,
        env=env,
    )


def load_doctor_module():
    spec = importlib.util.spec_from_file_location("quasi_doctor", DOCTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doctor_json_reports_missing_venv_without_crashing(tmp_path: Path):
    result = run_doctor(tmp_path / "data", "--json", "--profile", "core")

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == "quasi-doctor.v1"
    assert payload["status"] == "error"
    assert payload["venv"]["exists"] is False
    assert payload["venv"]["python_executable"] is False
    assert payload["venv"]["requirements_sync"] == "venv_missing"
    assert payload["summary"]["core_ok"] is False


def test_core_dependency_mapping_includes_curl_cffi(tmp_path: Path):
    result = run_doctor(tmp_path / "data", "--json", "--profile", "core")

    payload = json.loads(result.stdout)
    imports = {item["name"]: item["import"] for item in payload["python"]["core"]}
    assert imports["curl_cffi"] == "curl_cffi"
    assert imports["beautifulsoup4"] == "bs4"
    assert imports["pyyaml"] == "yaml"
    assert imports["pymupdf"] == "fitz"


def test_bin_help_works_without_venv(tmp_path: Path):
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path / "data")

    result = subprocess.run(
        [str(DOCTOR_BIN), "--help"],
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "--json" in result.stdout
    assert "--sync" in result.stdout
    assert "--profile" in result.stdout
    assert "--strict" in result.stdout


def test_doctor_does_not_report_dokobot(tmp_path: Path):
    result = run_doctor(tmp_path / "data", "--json", path="")

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert "dokobot" not in result.stdout.lower()
    assert "dokobot" not in payload["summary"]["optional_missing"]


def test_doctor_profile_registry_excludes_dokobot_and_download_profile():
    doctor = load_doctor_module()

    assert "download" not in doctor.EXTERNAL_PROFILES
    serialized = json.dumps(doctor.EXTERNAL_PROFILES)
    assert "dokobot" not in serialized.lower()


def test_strict_optional_failures_have_distinct_exit_code():
    doctor = load_doctor_module()

    assert doctor.exit_code({
        "summary": {"core_ok": True, "optional_missing": ["kagi"]},
        "strict": True,
    }) == 3
    assert doctor.exit_code({
        "summary": {"core_ok": True, "optional_missing": ["kagi"]},
        "strict": False,
    }) == 0
    assert doctor.exit_code({
        "summary": {"core_ok": False, "optional_missing": ["kagi"]},
        "strict": True,
    }) == 1


def test_doctor_flags_plugin_version_drift(tmp_path: Path, monkeypatch):
    """Agent/skill definitions load from the plugin cache at session start; a mid-session cache
    sync does not update the running session (a 0.48.0-contract agent ran long after 0.48.2 was
    installed). Doctor compares the copy it runs FROM against the installed registry and warns."""
    module = load_doctor_module()

    fake_home = tmp_path / "home"
    reg = fake_home / ".claude" / "plugins"
    reg.mkdir(parents=True)
    (reg / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"quasi@ramu-toolkit": [{"version": "9.9.9"}]}}))
    monkeypatch.setenv("HOME", str(fake_home))

    stale_root = tmp_path / "stale-plugin"
    (stale_root / ".claude-plugin").mkdir(parents=True)
    (stale_root / ".claude-plugin" / "plugin.json").write_text('{"version": "0.48.0"}')

    drift = module.check_plugin_version_drift(stale_root)
    assert drift == {"running": "0.48.0", "installed": "9.9.9", "drift": True}

    current_root = tmp_path / "current-plugin"
    (current_root / ".claude-plugin").mkdir(parents=True)
    (current_root / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}')
    assert module.check_plugin_version_drift(current_root)["drift"] is False

    # Missing registry (fresh machine, no plugin manager) must degrade to no-warning, not crash.
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    assert module.check_plugin_version_drift(stale_root)["drift"] is False
