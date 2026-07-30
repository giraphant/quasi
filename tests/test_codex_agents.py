from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "codex-agents.mjs"


def node() -> str:
    command = shutil.which("node")
    if not command:
        pytest.skip("node not on PATH")
    return command


def run_sync(project: Path, *flags: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            node(),
            str(SCRIPT),
            "--plugin-root",
            str(PLUGIN_ROOT),
            "--project",
            str(project),
            *flags,
        ],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def test_codex_agent_sync_generates_native_roles_from_canonical_markdown(
    tmp_path: Path,
) -> None:
    first = run_sync(tmp_path)
    assert first.stdout.startswith("synced ")

    generated = sorted((tmp_path / ".codex" / "agents").glob("quasi_*.toml"))
    sources = sorted((PLUGIN_ROOT / "agents").glob("*.md"))
    assert len(generated) == len(sources)

    download = tomllib.loads(
        (tmp_path / ".codex" / "agents" / "quasi_download.toml").read_text(
            encoding="utf-8"
        )
    )
    assert download["name"] == "quasi_download"
    assert download["description"].startswith(
        "Worker for reconciling or acquiring one exact Book/Paper source"
    )
    assert "你是 quasi 的单材料 acquisition writer" in download[
        "developer_instructions"
    ]
    assert "Do not spawn subagents." in download["developer_instructions"]
    assert "model" not in download, "native roles should inherit the coordinator model"

    second = run_sync(tmp_path)
    assert "(0 written," in second.stdout
    run_sync(tmp_path, "--check")


def test_codex_agent_check_detects_missing_or_outdated_role(tmp_path: Path) -> None:
    run_sync(tmp_path)
    role = tmp_path / ".codex" / "agents" / "quasi_metadata.toml"
    role.write_text(role.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8")

    checked = run_sync(tmp_path, "--check", "--json", check=False)
    assert checked.returncode == 1
    assert '"ok": false' in checked.stdout
    assert '"outdated": 1' in checked.stdout


def test_codex_agent_sync_requires_an_explicit_scope() -> None:
    result = subprocess.run(
        [node(), str(SCRIPT)],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "choose exactly one destination" in result.stderr
