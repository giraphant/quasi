from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUDIT = PLUGIN_ROOT / "scripts" / "audit" / "audit.py"


def run_audit(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_audit_fixed_json_contract_on_empty_vault(tmp_path: Path):
    project = tmp_path / "project"
    (project / "vault").mkdir(parents=True)

    result = run_audit(project, "--path", "vault")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "clean"
    assert payload["files_checked"] == 0
    assert "llm_editable" in payload
    assert "escalated" in payload
    assert "needs_backfill" not in payload


def test_audit_rejects_removed_subcommands(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    result = run_audit(project, "run")

    assert result.returncode == 2
    assert "unrecognized arguments: run" in result.stderr
