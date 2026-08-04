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
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    request = {
        "source": source,
        "export": export_name,
        "args": args,
    }
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
