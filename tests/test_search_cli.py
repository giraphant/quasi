from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SEARCH = PLUGIN_ROOT / "scripts" / "search" / "search.py"
SEARCH_DIR = PLUGIN_ROOT / "scripts" / "search"


def run_search(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SEARCH), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_search_help_exposes_fixed_json_contract():
    top = run_search("--help")
    book = run_search("book", "--help")
    paper = run_search("paper", "--help")
    kagi = run_search("kagi", "--help")

    assert top.returncode == 0
    assert book.returncode == 0
    assert paper.returncode == 0
    assert kagi.returncode == 0
    assert "{book,paper,kagi}" in top.stdout
    assert "--top" in book.stdout
    assert "--json" in book.stdout
    assert "--shape" not in book.stdout
    assert "--output" not in book.stdout
    assert "--shape" not in paper.stdout
    assert "--output" not in paper.stdout


def test_kagi_subcommand_passes_through_to_native_cli_with_quasi_auth(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    out_file = tmp_path / "out.json"
    fake_kagi = fake_bin / "kagi"
    fake_kagi.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(out_file)!r}).write_text(json.dumps({{'token': os.environ.get('KAGI_SESSION_TOKEN'), 'quasi_token': os.environ.get('QUASI_KAGI_SESSION_TOKEN'), 'args': sys.argv[1:]}}), encoding='utf-8')\n"
        "print('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    fake_kagi.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["QUASI_KAGI_SESSION_TOKEN"] = "session-token"
    env.pop("KAGI_SESSION_TOKEN", None)

    result = subprocess.run(
        [sys.executable, str(SEARCH), "kagi", "search", "--format", "json", "不受掌控 ISBN"],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ok": True}
    observed = json.loads(out_file.read_text(encoding="utf-8"))
    assert observed == {
        "token": "session-token",
        "quasi_token": None,
        "args": ["search", "--format", "json", "不受掌控 ISBN"],
    }


def test_legacy_shape_and_output_modes_are_removed():
    shape = run_search("paper", "--doi", "10.1/example", "--shape", "single")
    output = run_search("book", "--title", "Example", "--output", "out.json")

    assert shape.returncode == 2
    assert "unrecognized arguments" in shape.stderr
    assert output.returncode == 2
    assert "unrecognized arguments" in output.stderr


def load_search_module():
    sys.path.insert(0, str(SEARCH_DIR))
    spec = importlib.util.spec_from_file_location("quasi_search_for_tests", SEARCH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_book_localisation_sidecar_uses_douban_even_when_source_is_limited():
    search = load_search_module()
    calls: list[tuple[str, object]] = []

    def fake_adapter(source_id, query):
        calls.append((source_id, query))
        if source_id == "openlibrary":
            return search.AdapterResult(source=source_id, success=True, entries=[])
        if source_id == "douban_cn":
            return search.AdapterResult(
                source=source_id,
                success=True,
                entries=[{
                    "title": "与麻烦同在",
                    "authors": ["[美] 唐娜·哈拉维"],
                    "translators": ["赵文"],
                    "publisher": "华东师范大学出版社",
                    "year": 2024,
                    "isbn_13": "9787576048971",
                    "source_ids": {"douban_cn": "36500000"},
                    "language": "zh",
                }],
            )
        raise AssertionError(source_id)

    with patch.object(search, "_adapter_search_book", side_effect=fake_adapter):
        resp = search.book_search(
            search.BookQuery(title="Staying with the Trouble", author="Donna Haraway"),
            sources=["openlibrary"],
        )

    assert [source for source, _ in calls] == ["openlibrary", "douban_cn"]
    assert resp.diagnostics["sources_attempted"] == ["openlibrary"]
    assert resp.localisations["zh"]["status"] == "found"
    assert resp.localisations["zh"]["candidates"][0]["douban_id"] == "36500000"


def test_book_localisation_sidecar_preserves_weak_candidate_markers():
    search = load_search_module()
    weak_entry = {
        "title": "不受掌控",
        "authors": [],
        "translators": [],
        "publisher": "",
        "source_ids": {"douban_cn": "35948627"},
        "douban_url": "https://book.douban.com/subject/35948627/",
        "_weak": True,
        "_weak_reason": "douban-fetch-blocked-kagi-title-only",
    }

    with patch.object(
        search,
        "_adapter_search_book",
        return_value=search.AdapterResult(source="douban_cn", success=True, entries=[weak_entry]),
    ):
        resp = search.book_search(search.BookQuery(title="Uncontrollability", author="Hartmut Rosa"), sources=["openlibrary"])

    candidate = resp.localisations["zh"]["candidates"][0]
    assert candidate["_weak"] is True
    assert candidate["_weak_reason"] == "douban-fetch-blocked-kagi-title-only"
