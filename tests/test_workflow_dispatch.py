from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import PurePosixPath
from typing import Any

import pytest

from workflow_test_support import HARNESS, ROOT, run_workflow_export


CATALOG_MODULE = "scripts/workflows/operations/catalog.mts"
CONTEXT_MODULE = "scripts/workflows/context-base.mts"
INPUT_MODULE = "scripts/workflows/shared/material-input.mts"
TRANSLATION_ROW_MODULE = "scripts/workflows/operations/rows/translation.mts"
LANGUAGE_TAGS = json.loads(
    (ROOT / "tests" / "fixtures" / "translation_language_tags.json").read_text(
        encoding="utf-8"
    )
)


DISPATCH_HARNESS = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const config = JSON.parse(process.argv[1]);

async function load(source) {
  const result = await build({
    absWorkingDir: root,
    bundle: true,
    charset: "utf8",
    entryPoints: [resolve(root, source)],
    format: "esm",
    legalComments: "none",
    logLevel: "silent",
    platform: "node",
    sourcemap: false,
    target: ["es2022"],
    treeShaking: true,
    write: false,
  });
  const bundled = result.outputFiles[0].text;
  const url = `data:text/javascript;base64,${Buffer.from(bundled).toString("base64")}`;
  return import(url);
}

const dispatch = await load("scripts/workflows/shared/dispatch.mts");
const catalog = await load("scripts/workflows/operations/catalog.mts");
let agentCalls = 0;
const runtime = {
  agent: async () => {
    agentCalls += 1;
    if (config.agent_result === "reject") {
      const error = new Error("agent exploded");
      error.name = "AgentExplosion";
      throw error;
    }
    if (config.agent_result === "null") return null;
    return config.model_output;
  },
};

try {
  let result;
  if (config.mode === "throwing_predicate") {
    const prepared = catalog.prepareOperation(config.invocation);
    prepared.complete = () => {
      const error = new Error("predicate exploded");
      error.name = "PredicateExplosion";
      throw error;
    };
    result = await dispatch.dispatchPreparedOperation(runtime, prepared);
  } else {
    result = await dispatch.dispatchOperation(runtime, config.invocation);
  }
  process.stdout.write(JSON.stringify({ result, agentCalls }));
} catch (error) {
  process.stdout.write(JSON.stringify({
    thrown: { name: error.name, message: error.message },
    agentCalls,
  }));
}
"""


BASE_META = {
    "title": "Exact Material",
    "authors": ["Ada Example"],
    "year": 2024,
    "doi": "10.1000/exact",
    "oa_url": "https://example.test/exact.pdf",
    "url": "https://example.test/exact",
    "journal": "Exact Joins",
    "isbn": "9780000000000",
    "publisher": "Exact Press",
    "category": "monograph",
    "confidence": "high",
    "date": "2024-01-02",
    "media": "sources/exact-talk.mp4",
    "description": "Exact topic",
    "engines": ["whisper"],
}


def _context(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "meta": dict(BASE_META),
        "mode": "create",
        "diagnostics": [],
        "pass": 1,
        "query": "exact material",
        "topic": "exact material",
        "full_name": "Ada Example",
        "count": 3,
        "format": "epub",
        "source": "sources/exact-material.epub",
        "input": "processing/papers/exact-material/source.txt",
        "inputs": [],
        "input_paths": [],
        "output_exists": False,
        "chapter": {
            "slot": "01",
            "slug": "opening",
            "filename": "ch01-opening.txt",
            "title": "Opening",
            "authors": ["Ada Example"],
            "word_count": 100,
            "start_page": 1,
            "end_page": 4,
        },
        "member_refs": [],
        "member_assignments": [],
        "card_refs": [],
        "subquestions": [],
        "task": {
            "subq": "sq-opening",
            "query": "exact web evidence",
            "note": "verify the claim",
            "card_slug": "exact-card",
        },
        "target": "vault/topics/exact-material/00-overview.md",
        "target_language": "zh-CN",
        "max_items": 8,
        "candidates": [],
    }
    value.update(overrides)
    return value


OPERATION_FIXTURES: dict[str, tuple[str, dict[str, Any]]] = {
    "material.search": ("paper", _context()),
    "paper.acquire": ("paper", _context()),
    "paper.prepare": ("paper", _context()),
    "paper.analyse": ("paper", _context()),
    "paper.audit": ("paper", _context(target="vault/papers/exact-material.md")),
    "book.acquire": (
        "book",
        _context(meta={key: value for key, value in BASE_META.items() if key != "format"}),
    ),
    "book.prepare": ("book", _context()),
    "chapter.analyse": ("book", _context()),
    "book.synthesise": ("book", _context()),
    "book.audit": ("book", _context(target="vault/books/exact-material")),
    "talk.prepare": ("talk", _context()),
    "talk.analyse": ("talk", _context()),
    "talk.audit": ("talk", _context(target="vault/talks/exact-material/talk.md")),
    "translation.prepare": ("translation", _context()),
    "topic.recall": ("topic", _context()),
    "topic.steer": ("topic", _context()),
    "topic.webcard": ("topic", _context()),
    "topic.synthesise.overview": ("topic", _context()),
    "topic.synthesise.resources": ("topic", _context()),
    "topic.audit": ("topic", _context()),
    "author.discover-books": ("author", _context()),
    "author.discover-papers": ("author", _context()),
    "author.resolve-membership": ("author", _context()),
    "author.synthesise": ("author", _context()),
    "author.audit": ("author", _context(target="vault/authors/exact-material.md")),
}


def _pipeline() -> dict[str, Any]:
    proc = subprocess.run(
        ["python3", "scripts/schemas/export_contracts.py", "--pipeline"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _registered_operations() -> dict[str, tuple[str, str]]:
    registered: dict[str, tuple[str, str]] = {}
    for kind, definition in _pipeline().items():
        for stage in definition["stages"]:
            operation = stage["operation"]
            prior = registered.get(operation)
            identity = (kind, stage["effect"])
            if prior is not None:
                assert prior[1] == identity[1]
                continue
            registered[operation] = identity
    return registered


def _invocation(
    operation: str,
    *,
    kind: str | None = None,
    slug: Any = "exact-material",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fixture_kind, fixture_context = OPERATION_FIXTURES[operation]
    return {
        "kind": kind or fixture_kind,
        "operation": operation,
        "slug": slug,
        "context": context if context is not None else fixture_context,
        "label": f"exact-material:{operation}",
    }


def _prepare(operation: str, **overrides: Any) -> dict[str, Any]:
    return run_workflow_export(
        CATALOG_MODULE,
        "prepareOperation",
        _invocation(operation, **overrides),
    )


def _export_failure(source: str, export_name: str, *args: Any) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        input=json.dumps({"source": source, "export": export_name, "args": args}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0, proc.stdout
    return proc.stderr


def _dispatch(config: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", DISPATCH_HARNESS, json.dumps(config)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _audit_invocation(*, slug: Any = "exact-material") -> dict[str, Any]:
    return {
        "kind": "paper",
        "operation": "paper.audit",
        "slug": slug,
        "context": {},
        "label": "exact-material:paper.audit",
    }


def _audit_output(status: str, *, coherent: bool = True) -> dict[str, Any]:
    issue = None
    if status != "complete":
        issue = {
            "code": f"paper.audit.{status}",
            "operation": "paper.audit",
            "summary": f"Paper audit returned {status}.",
            "user_question": (
                "Which audit finding should be resolved?"
                if status == "needs_input"
                else None
            ),
            "retryable": status != "failed",
        }
    return {
        "remaining_violations": 0 if coherent else 1,
        "escalated": [],
        "mutated_paths": [],
        "terminal": {"status": status, "issue": issue},
    }


def _search_identity(kind: str, *, slug: str) -> dict[str, Any]:
    common = {
        "slug": slug,
        "title": "Exact Material",
        "authors": ["Ada Example"],
        "year": 2024,
        "confidence": "high",
    }
    if kind == "book":
        return {
            **common,
            "isbn": "9780000000000",
            "publisher": "Exact Press",
            "category": "monograph",
        }
    return {
        **common,
        "doi": "10.1000/exact",
        "oa_url": "https://example.test/exact.pdf",
        "url": "https://example.test/exact",
        "journal": "Exact Joins",
    }


def _search_output(
    kind: str,
    *,
    identity_slug: str,
    local_owner: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "identity": _search_identity(kind, slug=identity_slug),
        "local_owner": local_owner,
        "confidence": "high",
        "observations": [],
        "terminal": {"status": "complete", "issue": None},
    }


def test_search_null_owner_is_a_coherent_observed_miss() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind="paper"),
            "model_output": _search_output(
                "paper",
                identity_slug="selected-paper",
                local_owner=None,
            ),
        }
    )

    assert report["result"]["kind"] == "receipt"


def test_search_owner_schema_does_not_encode_a_hit_with_null_fields() -> None:
    owner_schema = _prepare("material.search")["options"]["schema"]["properties"][
        "local_owner"
    ]

    assert owner_schema["type"] == ["object", "null"]
    for field in ("vault_slug", "path", "match"):
        assert owner_schema["properties"][field]["type"] == "string"


def test_search_complete_rejects_an_owner_for_a_different_identity() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind="paper"),
            "model_output": _search_output(
                "paper",
                identity_slug="selected-paper",
                local_owner={
                    "identity_slug": "different-paper",
                    "vault_slug": "existing-paper",
                    "path": "vault/papers/existing-paper.md",
                    "match": "doi",
                },
            ),
        }
    )

    assert report["result"]["kind"] == "incoherent_complete"


@pytest.mark.parametrize(
    ("kind", "vault_slug", "path"),
    [
        ("paper", "existing-paper", "vault/papers/existing-paper.md"),
        (
            "book",
            "existing-book",
            "vault/books/existing-book/00-overview.md",
        ),
    ],
)
def test_search_complete_accepts_identity_bound_to_a_different_vault_slug(
    kind: str,
    vault_slug: str,
    path: str,
) -> None:
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind=kind),
            "model_output": _search_output(
                kind,
                identity_slug="selected-identity",
                local_owner={
                    "identity_slug": "selected-identity",
                    "vault_slug": vault_slug,
                    "path": path,
                    "match": "title",
                },
            ),
        }
    )

    assert report["result"]["kind"] == "receipt"


@pytest.mark.parametrize(
    "status", ["complete", "needs_input", "blocked", "failed"]
)
def test_dispatch_preserves_each_validated_terminal_and_stamps_host_fields(
    status: str,
) -> None:
    model_output = _audit_output(status)
    report = _dispatch(
        {"invocation": _audit_invocation(), "model_output": model_output}
    )

    assert report["agentCalls"] == 1
    assert report["result"] == {
        "kind": "receipt",
        "receipt": {
            "schema_version": "quasi.stage.receipt/0.3",
            "operation": "paper.audit",
            "stage": "Audit",
            "material_key": "paper:exact-material",
            "effect": "writer",
            "attempt": 1,
            "target_path": "vault/papers/exact-material.md",
            "pass": 1,
            "artifact_roles": ["canonical"],
            **model_output,
        },
    }


def test_invalid_context_returns_typed_outcome_before_agent_dispatch() -> None:
    report = _dispatch(
        {"invocation": _audit_invocation(slug=None), "model_output": None}
    )

    assert report["agentCalls"] == 0
    assert report["result"]["kind"] == "invalid_context"
    assert report["result"]["receipt"] is None
    assert report["result"]["issue"]["operation"] == "paper.audit"
    assert report["result"]["issue"]["retryable"] is False
    assert report["result"]["issue"]["observation_request"] is None
    assert "invalid material slug" in report["result"]["issue"]["summary"]


def test_unexpected_preparation_error_propagates_without_agent_dispatch() -> None:
    invocation = _invocation(
        "book.acquire",
        context=_context(allowed_formats="epub"),
    )
    report = _dispatch({"invocation": invocation, "model_output": None})

    assert report == {
        "thrown": {
            "name": "TypeError",
            "message": "formats.map is not a function",
        },
        "agentCalls": 0,
    }


@pytest.mark.parametrize("agent_result", ["reject", "null"])
def test_unknown_agent_outcome_blocks_without_replay(agent_result: str) -> None:
    report = _dispatch(
        {
            "invocation": _audit_invocation(),
            "agent_result": agent_result,
        }
    )

    assert report["agentCalls"] == 1
    assert report["result"]["kind"] == "unknown_outcome"
    assert report["result"]["receipt"] is None
    assert report["result"]["issue"]["operation"] == "paper.audit"
    assert report["result"]["issue"]["retryable"] is False
    assert report["result"]["issue"]["observation_request"] is None


def test_schema_valid_incoherent_complete_retains_receipt() -> None:
    model_output = _audit_output("complete", coherent=False)
    report = _dispatch(
        {"invocation": _audit_invocation(), "model_output": model_output}
    )

    assert report["agentCalls"] == 1
    assert report["result"]["kind"] == "incoherent_complete"
    assert report["result"]["receipt"]["terminal"] == model_output["terminal"]
    assert report["result"]["receipt"]["remaining_violations"] == 1
    assert report["result"]["issue"]["operation"] == "paper.audit"


def test_completion_predicate_error_propagates_unchanged() -> None:
    report = _dispatch(
        {
            "mode": "throwing_predicate",
            "invocation": _audit_invocation(),
            "model_output": _audit_output("complete"),
        }
    )

    assert report == {
        "thrown": {
            "name": "PredicateExplosion",
            "message": "predicate exploded",
        },
        "agentCalls": 1,
    }


def test_missing_slug_rejects_before_prompt_construction():
    stderr = _export_failure(
        CATALOG_MODULE,
        "prepareOperation",
        _invocation("paper.acquire", slug=None),
    )

    assert "invalid material slug" in stderr
    assert "InputContractError" in stderr


def test_missing_artifact_variable_never_expands_to_undefined():
    stderr = _export_failure(
        CONTEXT_MODULE,
        "expandArtifactTemplates",
        {"source": "sources/{slug}.{format}"},
        {},
        {"slug": "exact-material"},
    )

    assert "missing artifact template value: format" in stderr
    assert "undefined" not in stderr


def test_catalog_prepares_each_operation_with_its_own_schema_and_refs():
    registered = _registered_operations()
    assert set(OPERATION_FIXTURES) == set(registered)

    for operation, (kind, effect) in registered.items():
        prepared = _prepare(operation, kind=kind)

        assert prepared["invocation"]["operation"] == operation
        assert prepared["invocation"]["kind"] == kind
        assert prepared["options"]["agentType"]
        assert prepared["options"]["phase"]
        assert prepared["options"]["label"] == f"exact-material:{operation}"
        assert prepared["options"]["schema"]["type"] == "object"
        assert prepared["stampedValues"]["operation"] == operation
        assert prepared["stampedValues"]["effect"] == effect
        request = (
            json.loads(prepared["prompt"])
            if prepared["prompt"].startswith("{")
            else None
        )
        if request is not None:
            assert request["operation"] == operation


def test_every_writer_has_normalized_project_relative_targets():
    registered = _registered_operations()

    for operation, (kind, effect) in registered.items():
        targets = _prepare(operation, kind=kind)["writeTargets"]
        if effect == "readonly":
            assert targets == []
            continue
        assert targets, operation
        for target in targets:
            path = target["path"]
            assert target["scope"] in {"exact", "subtree"}
            assert path and not path.startswith("/")
            assert "\\" not in path
            assert ".." not in PurePosixPath(path).parts
            assert str(PurePosixPath(path)) == path


def test_prepare_rows_expose_only_paths_they_can_publish():
    assert _prepare("paper.prepare")["writeTargets"] == [
        {"scope": "exact", "path": "processing/papers/exact-material/source.txt"},
        {"scope": "exact", "path": "processing/papers/exact-material/ocr.pdf"},
        {"scope": "exact", "path": "processing/papers/exact-material/ocr.txt"},
    ]
    assert _prepare("book.prepare")["writeTargets"] == [
        {"scope": "subtree", "path": "processing/chapters/exact-material"}
    ]
    assert _prepare("translation.prepare")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh-cn.pdf",
        },
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh-cn.manifest.json",
        },
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh-cn-reocr.pdf",
        },
    ]


@pytest.mark.parametrize(
    ("language", "normalized"),
    [(row["input"], row["normalized"]) for row in LANGUAGE_TAGS],
)
def test_bundled_language_normalizers_match_the_python_contract_fixture(
    language: str,
    normalized: str,
):
    assert (
        run_workflow_export(INPUT_MODULE, "normalizeLanguage", language)
        == normalized
    )
    assert (
        run_workflow_export(
            TRANSLATION_ROW_MODULE,
            "normalizeLanguage",
            language,
        )
        == normalized
    )


def test_translation_row_requires_the_exact_snake_case_target_field():
    context = _context()
    del context["target_language"]
    context["targetLanguage"] = "fr-FR"

    stderr = _export_failure(
        CATALOG_MODULE,
        "prepareOperation",
        _invocation("translation.prepare", context=context),
    )

    assert "requires a valid target language" in stderr


def test_book_acquire_conservatively_owns_both_possible_sources():
    assert _prepare("book.acquire")["writeTargets"] == [
        {"scope": "exact", "path": "sources/exact-material.epub"},
        {"scope": "exact", "path": "sources/exact-material.pdf"},
    ]


@pytest.mark.parametrize(
    ("operation", "scope", "path"),
    [
        ("paper.audit", "exact", "vault/papers/exact-material.md"),
        ("book.audit", "subtree", "vault/books/exact-material"),
        ("talk.audit", "exact", "vault/talks/exact-material/talk.md"),
        ("author.audit", "exact", "vault/authors/exact-material.md"),
        ("topic.audit", "exact", "vault/topics/exact-material/00-overview.md"),
    ],
)
def test_audit_rows_expose_their_real_target(operation: str, scope: str, path: str):
    assert _prepare(operation)["writeTargets"] == [{"scope": scope, "path": path}]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            {"scope": "exact", "path": "vault/papers/a.md"},
            {"scope": "exact", "path": "vault/papers/a.md"},
            True,
        ),
        (
            {"scope": "exact", "path": "vault/books/a/ch01.md"},
            {"scope": "subtree", "path": "vault/books/a"},
            True,
        ),
        (
            {"scope": "exact", "path": "vault/papers/a.md"},
            {"scope": "exact", "path": "vault/papers/b.md"},
            False,
        ),
        (
            {"scope": "subtree", "path": "vault/books/a"},
            {"scope": "exact", "path": "vault/books/abc/ch01.md"},
            False,
        ),
    ],
)
def test_write_target_overlap_uses_path_boundaries(
    left: dict[str, str],
    right: dict[str, str],
    expected: bool,
):
    assert (
        run_workflow_export(CATALOG_MODULE, "writeTargetsOverlap", left, right)
        is expected
    )


def _needs_input_candidate_variants(prepared: dict[str, Any]) -> list[dict[str, Any]]:
    terminal = prepared["options"]["schema"]["properties"]["terminal"]
    needs_input = next(
        branch
        for branch in terminal["anyOf"]
        if branch["properties"]["status"]["const"] == "needs_input"
    )
    items = needs_input["properties"]["candidates"]["items"]
    return items.get("anyOf", [items])


def test_paper_search_gate_has_only_typed_paper_and_book_candidates():
    variants = _needs_input_candidate_variants(_prepare("material.search", kind="paper"))

    assert {variant["properties"]["kind"]["const"] for variant in variants} == {
        "paper",
        "book",
    }
    for variant in variants:
        assert variant["required"] == ["kind", "identity"]
        assert variant["additionalProperties"] is False


def test_book_search_does_not_gain_a_cross_kind_alias():
    variants = _needs_input_candidate_variants(
        _prepare("material.search", kind="book")
    )

    assert [variant["properties"]["kind"]["const"] for variant in variants] == [
        "book"
    ]
