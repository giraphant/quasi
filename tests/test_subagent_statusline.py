from __future__ import annotations

import ast
import importlib.util
import json
import pkgutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "subagent-statusline.py"


def run_statusline(
    payload: Any, *, raw: bool = False
) -> subprocess.CompletedProcess[str]:
    input_text = payload if raw else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        cwd=PLUGIN_ROOT,
    )


def rows(proc: subprocess.CompletedProcess[str]) -> list[dict[str, str]]:
    return [json.loads(line) for line in proc.stdout.splitlines()]


def load_module():
    spec = importlib.util.spec_from_file_location("quasi_statusline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_payload(tasks: list[Any], *, columns: int = 120) -> dict[str, Any]:
    return {
        "session_id": "session-123",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/vault",
        "permission_mode": "default",
        "hook_event_name": "SubagentStatus",
        "columns": columns,
        "tasks": tasks,
    }


def test_projects_multiple_quasi_rows_and_leaves_other_rows_default() -> None:
    proc = run_statusline(
        base_payload(
            [
                {
                    "id": "paper-worker",
                    "name": "quasi:analyse-agent",
                    "type": "quasi:analyse-agent",
                    "status": "running",
                    "description": "analyse a paper",
                    "label": "paper.analyse:ada-paper",
                    "startTime": 1730000000000,
                    "model": "claude-opus-4-6",
                    "effort": "high",
                    "contextWindowSize": 200000,
                    "tokenCount": 50000,
                    "tokenSamples": [12000, 50000],
                    "cwd": "/vault",
                },
                {
                    "id": "readability-worker",
                    "name": "general-purpose",
                    "type": "general-purpose",
                    "status": "pending",
                    "description": "assess normalized text",
                    "label": "paper.assess:ada-paper",
                    "startTime": 1730000001000,
                    "model": "claude-3-5-sonnet-20241022",
                    "contextWindowSize": 200000,
                    "tokenCount": 20000,
                    "tokenSamples": [],
                    "cwd": "/vault",
                },
                {
                    "id": "foreign-worker",
                    "name": "reviewer",
                    "type": "general-purpose",
                    "status": "running",
                    "label": "review:unrelated",
                    "model": "claude-haiku-4-5-20251001",
                },
            ]
        )
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert rows(proc) == [
        {
            "id": "paper-worker",
            "content": (
                "Paper/paper.analyse:ada-paper · running · Opus 4.6 · high · 25%"
            ),
        },
        {
            "id": "readability-worker",
            "content": (
                "Paper/paper.assess:ada-paper · pending · Sonnet 3.5 · 10%"
            ),
        },
    ]


def test_missing_211_fields_and_bad_task_fields_are_tolerated() -> None:
    proc = run_statusline(
        base_payload(
            [
                {
                    "id": "book-download",
                    "type": "quasi:download-agent",
                    "status": "queued",
                    "label": "download:book-slug",
                    "model": "default",
                },
                {
                    "id": "typed-only",
                    "type": "quasi:audit-agent",
                    "status": 9,
                    "label": None,
                    "model": None,
                    "effort": None,
                    "tokenCount": "1000",
                    "contextWindowSize": 200000,
                },
                None,
                "not a task",
                {"id": None, "type": "quasi:analyse-agent"},
            ]
        )
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert rows(proc) == [
        {
            "id": "book-download",
            "content": "Book/download:book-slug · queued",
        },
        {
            "id": "typed-only",
            "content": "Quasi/quasi:audit-agent · unknown",
        },
    ]


def test_narrow_columns_truncate_without_splitting_unicode_clusters() -> None:
    module = load_module()
    proc = run_statusline(
        base_payload(
            [
                {
                    "id": "unicode",
                    "type": "quasi:steer-agent",
                    "status": "running",
                    "label": (
                        "\x1b[31msteer:汉字👩\u200d🔬e\u0301研究:r1\x1b[0m"
                    ),
                    "model": "claude-opus-4-6",
                    "effort": "xhigh",
                    "tokenCount": 1000,
                    "contextWindowSize": 200000,
                }
            ],
            columns=19,
        )
    )

    assert proc.returncode == 0
    content = rows(proc)[0]["content"]
    assert content.endswith("…")
    assert module.display_width(content) <= 19
    assert "👩\u200d🔬" in content
    assert "\x1b" not in content


def test_non_quasi_and_empty_tasks_emit_no_override_lines() -> None:
    non_quasi = run_statusline(
        base_payload(
            [
                {
                    "id": "foreign",
                    "type": "general-purpose",
                    "label": "review:foreign",
                    "status": "running",
                }
            ]
        )
    )
    empty = run_statusline(base_payload([]))

    assert non_quasi.returncode == empty.returncode == 0
    assert non_quasi.stdout == empty.stdout == ""
    assert non_quasi.stderr == empty.stderr == ""


def test_malformed_input_reports_only_to_stderr() -> None:
    for payload in ("{bad json", "[]", '{"tasks": "not-an-array"}'):
        proc = run_statusline(payload, raw=True)
        assert proc.returncode == 0
        assert proc.stdout == ""
        assert "quasi subagent status line:" in proc.stderr


def test_numeric_effort_and_percentage_require_both_numeric_fields() -> None:
    proc = run_statusline(
        base_payload(
            [
                {
                    "id": "numeric-effort",
                    "type": "quasi:discovery-agent",
                    "label": "discover-papers:author",
                    "status": "running",
                    "model": "claude-haiku-4-5-20251001",
                    "effort": 4096,
                    "tokenCount": 100000,
                    "contextWindowSize": 200000,
                },
                {
                    "id": "missing-window",
                    "type": "general-purpose",
                    "label": "paper.extract-text:paper",
                    "status": "running",
                    "tokenCount": 1000,
                },
            ]
        )
    )

    assert rows(proc) == [
        {
            "id": "numeric-effort",
                "content": (
                    "Author/discover-papers:author · running · Haiku 4.5 · 4096 · 50%"
                ),
        },
        {
            "id": "missing-window",
            "content": "Paper/paper.extract-text:paper · running",
        },
    ]


def test_refresh_path_imports_only_stdlib_and_does_no_external_work() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    imported_roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = name.name
                imported_roots.add(name.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
            for name in node.names:
                aliases[name.asname or name.name] = f"{node.module}.{name.name}"

    stdlib_module_names = getattr(sys, "stdlib_module_names", None)
    if stdlib_module_names is None:  # Python 3.9 compatibility
        stdlib_path = sysconfig.get_path("stdlib")
        assert stdlib_path
        stdlib_paths = [stdlib_path]
        dynamic_path = sysconfig.get_config_var("DESTSHARED")
        if dynamic_path:
            stdlib_paths.append(dynamic_path)
        stdlib_module_names = {
            module.name for module in pkgutil.iter_modules(stdlib_paths)
        } | set(sys.builtin_module_names)
    assert imported_roots <= set(stdlib_module_names) | {"__future__"}

    def resolved_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = resolved_name(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := resolved_name(node.func)) is not None
    }
    external_roots = {"ftplib", "http", "smtplib", "socket", "subprocess", "urllib"}
    assert not {call.split(".", 1)[0] for call in calls} & external_roots
