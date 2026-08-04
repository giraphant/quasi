from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "workflow_harness.mjs"


def run_workflow_export(
    source: str,
    export_name: str,
    *args: Any,
) -> Any:
    return _run_harness(
        {
            "source": source,
            "export": export_name,
            "args": args,
        }
    )


def read_workflow_export(source: str, export_name: str) -> Any:
    return _run_harness(
        {"action": "read", "source": source, "export": export_name}
    )


def workflow_bundle_inputs(source: str) -> set[str]:
    return {
        Path(item).as_posix()
        for item in _run_harness({"action": "inputs", "source": source})
    }


def run_workflow_entry(
    entry: str,
    value: dict[str, Any],
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _run_harness(
        {
            "action": "run",
            "source": f"scripts/workflows/{entry}.entry.mts",
            "export": "run",
            "input": value,
            "outputs": outputs or [],
        }
    )


def run_generated_workflow(
    entry: str,
    value: dict[str, Any],
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _run_harness(
        {
            "action": "run-generated",
            "source": f"workflows/{entry}.mjs",
            "input": value,
            "outputs": outputs or [],
        }
    )


def _run_harness(request: dict[str, Any]) -> Any:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)
