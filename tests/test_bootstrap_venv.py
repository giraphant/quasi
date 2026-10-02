"""Exercise real shims/bootstrap with a disposable venv and a fake installer."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHIMS = sorted(path.name for path in (ROOT / "bin").glob("quasi-*")
               if path.name != "quasi-doctor")


@pytest.fixture
def runtime(tmp_path):
    plugin = tmp_path / "plugin"
    scripts = plugin / "scripts"
    scripts.mkdir(parents=True)
    shutil.copytree(ROOT / "bin", plugin / "bin")
    for name in ("bootstrap-venv.sh", "requirements.txt"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    # This test concerns dependency installation, never host credentials.
    (scripts / "load-keychain-env.sh").write_text("")
    data = tmp_path / "data"
    bindir = data / ".venv" / "bin"
    bindir.mkdir(parents=True)
    for name, body in {
        "python": 'print("dispatched")',
        "pip": '''import json, os, pathlib, sys
with pathlib.Path(os.environ["INSTALL_LOG"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("INSTALL_EXIT", "0")))
''',
    }.items():
        target = bindir / name
        target.write_text(f"#!{sys.executable}\n{body}\n")
        target.chmod(0o755)
    # The venv exists, but predates the dependency needed by MinerU cleanup.
    (data / "requirements.txt").write_text("pymupdf\n")
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(data),
               INSTALL_LOG=str(tmp_path / "installs.jsonl"))
    return plugin, data, env


def invoke(runtime, shim):
    plugin, _, env = runtime
    args = ["citation", "--help"] if shim == "quasi-helpers" else ["--help"]
    return subprocess.run([str(plugin / "bin" / shim), *args], env=env,
                          text=True, capture_output=True, timeout=20)


@pytest.mark.parametrize("shim", SHIMS)
def test_existing_venv_syncs_before_dispatch_and_skips_unchanged_deps(runtime, shim):
    plugin, data, env = runtime
    source = plugin / "scripts" / "requirements.txt"
    mirror = data / "requirements.txt"
    first = invoke(runtime, shim)
    assert first.returncode == 0, first.stderr
    assert mirror.read_bytes() == source.read_bytes()
    log = Path(env["INSTALL_LOG"])
    installs = log.read_text()
    assert json.loads(installs) == ["install", "--quiet", "--upgrade", "-r", str(source)]
    assert first.stdout.strip() == "dispatched"
    second = invoke(runtime, shim)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "dispatched"
    assert log.read_text() == installs


@pytest.mark.parametrize("shim", SHIMS)
def test_failed_sync_stops_dispatch_and_retries_next_invocation(runtime, shim):
    plugin, data, env = runtime
    env["INSTALL_EXIT"] = "1"
    failed = invoke(runtime, shim)
    assert failed.returncode != 0
    assert "dispatched" not in failed.stdout
    assert not (data / "requirements.txt").exists()
    env["INSTALL_EXIT"] = "0"
    retried = invoke(runtime, shim)
    assert retried.returncode == 0, retried.stderr
    assert retried.stdout.strip() == "dispatched"
    assert (data / "requirements.txt").read_bytes() == (plugin / "scripts" / "requirements.txt").read_bytes()
    assert len(Path(env["INSTALL_LOG"]).read_text().splitlines()) == 2
