from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

import pytest

from workflow_test_support import HARNESS, ROOT, run_workflow_export


CATALOG_MODULE = "scripts/workflows/operations/catalog.mts"
CONTEXT_MODULE = "scripts/workflows/context-base.mts"
INPUT_MODULE = "scripts/workflows/shared/material-input.mts"
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
const preparedDispatch = await load(
  "scripts/workflows/shared/dispatch-prepared.mts",
);
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
    result = await preparedDispatch.dispatchPreparedOperation(runtime, prepared);
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
        "max_cards": 3,
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


def _terminal_statuses(prepared: dict[str, Any]) -> set[str]:
    terminal = prepared["options"]["schema"]["properties"]["terminal"]
    return {
        branch["properties"]["status"]["const"]
        for branch in terminal["anyOf"]
    }


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


def _audit_output(*, coherent: bool = True) -> dict[str, Any]:
    return {
        "remaining_violations": 0 if coherent else 1,
        "escalated": [],
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }


def _search_identity(
    kind: str,
    *,
    slug: str,
    year: int = 2024,
) -> dict[str, Any]:
    common = {
        "slug": slug,
        "title": "Exact Material",
        "authors": ["Ada Example"],
        "year": year,
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
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "identity": _search_identity(kind, slug=identity_slug, year=year),
        "local_owner": local_owner,
        "confidence": "high",
        "observations": [],
        "terminal": {"status": "complete", "issue": None},
    }


def _book_year_evidence(
    verdict: str,
    *,
    slug_year: int = 2024,
) -> dict[str, Any]:
    return {
        "slug_year": slug_year,
        "source_years": {"publisher": 2025, "catalogue": 2025},
        "pdf_signals": {
            "first_published": 2025,
            "copyright_year": 2025,
            "original_year": None,
            "other_years": [2024],
        },
        "recommended_year": {
            "MATCH": slug_year,
            "MISMATCH": 2025,
            "AMBIGUOUS": None,
        }[verdict],
        "recommendation_reason": "Publisher and catalogue evidence agree.",
        "verdict": verdict,
    }


def _book_year_decision(action: str) -> dict[str, Any]:
    current_identity = _search_identity(
        "book",
        slug="bibliographic-book-2024",
        year=2024,
    )
    return {
        "current_identity": current_identity,
        "tmp_path": ".quasi/temp/downloads/exact-material.pdf",
        "year_evidence": _book_year_evidence(
            "MISMATCH" if action == "use-recommended-year" else "AMBIGUOUS"
        ),
        "action": action,
    }


def _book_acquire_output(
    evidence: dict[str, Any],
    *,
    tmp_path: str | None = ".quasi/temp/downloads/exact-material.pdf",
) -> dict[str, Any]:
    return {
        "output_path": "sources/exact-material.pdf",
        "format": "pdf",
        "allowed_output_paths": [
            "sources/exact-material.epub",
            "sources/exact-material.pdf",
        ],
        "write_state": "written",
        "identity_verified": True,
        "isbn": "9780000000000",
        "attempts": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": "created",
            "source": "publisher",
            "tmp_path": tmp_path,
            "year_evidence": evidence,
        },
    }


def _search_status_output(status: str) -> dict[str, Any]:
    if status == "complete":
        return _search_output(
            "paper",
            identity_slug="selected-paper",
            local_owner=None,
        )
    issue = {
        "code": (
            "material.identity_conflict"
            if status == "needs_input"
            else f"material.search.{status}"
        ),
        "operation": "material.search",
        "summary": f"Search returned {status}.",
        "user_question": (
            "Which identity should be used?" if status == "needs_input" else None
        ),
        "retryable": status != "failed",
    }
    terminal: dict[str, Any] = {"status": status, "issue": issue}
    if status == "needs_input":
        terminal.update(
            {
                "candidates": [
                    {
                        "kind": "paper",
                        "identity": _search_identity(
                            "paper",
                            slug="selected-paper",
                        ),
                    }
                ],
                "conflicts": ["title"],
            }
        )
    return {
        "identity": None,
        "local_owner": None,
        "confidence": "low",
        "observations": [],
        "terminal": terminal,
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
    model_output = _search_status_output(status)
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind="paper"),
            "model_output": model_output,
        }
    )

    assert report["agentCalls"] == 1
    assert report["result"] == {
        "kind": "receipt",
        "receipt": {
            "schema_version": "quasi.stage.receipt/0.3",
            "operation": "material.search",
            "stage": "Search",
            "material_key": "paper:exact-material",
            "effect": "readonly",
            "attempt": 1,
            "kind": "paper",
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
    model_output = _audit_output(coherent=False)
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
            "model_output": _audit_output(),
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


def test_only_operations_with_typed_gates_expose_needs_input() -> None:
    actual = set()
    for operation, (kind, _) in _registered_operations().items():
        overrides: dict[str, Any] = {"kind": kind}
        if operation == "book.prepare":
            overrides["context"] = _context(
                format="pdf",
                source="sources/exact-material.pdf",
            )
        if "needs_input" in _terminal_statuses(_prepare(operation, **overrides)):
            actual.add(operation)

    assert actual == {
        "material.search",
        "book.acquire",
        "book.prepare",
        "translation.prepare",
    }
    assert "needs_input" not in _terminal_statuses(_prepare("book.prepare"))


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


def test_talk_prepare_uses_the_cli_defaults_for_request_and_owned_outputs():
    meta = {
        "title": "Exact Talk",
        "date": "2024-01-02",
        "media": "sources/exact-talk.mp3",
    }
    prepared = _prepare(
        "talk.prepare",
        slug="exact-talk",
        context=_context(meta=meta),
    )
    request = json.loads(prepared["prompt"])

    assert request["engines"] == ["soniox", "apple", "parakeet"]
    assert request["identity"]["language"] == "auto"
    assert request["prepare_media"] is False
    assert prepared["writeTargets"][-3:] == [
        {
            "scope": "exact",
            "path": "processing/talks/exact-talk/transcript.soniox.srt",
        },
        {
            "scope": "exact",
            "path": "processing/talks/exact-talk/transcript.apple.srt",
        },
        {
            "scope": "exact",
            "path": "processing/talks/exact-talk/transcript.parakeet.srt",
        },
    ]


@pytest.mark.parametrize(
    ("classification", "canonical_action"),
    [("live", None), ("dead", "repair")],
)
def test_talk_prepare_repair_accepts_only_the_current_classification_owner(
    classification: str,
    canonical_action: str | None,
):
    slug = "exact-talk"
    canonical = f"vault/talks/{slug}/talk.md"
    artifacts = [
        {
            "role": "transcript",
            "path": f"vault/talks/{slug}/transcript.md",
            "sha256": "a" * 64,
            "size": 123,
        },
        {
            "role": "engine_transcript",
            "path": f"processing/talks/{slug}/transcript.soniox.srt",
            "sha256": "e" * 64,
            "size": 234,
        },
    ]
    canonical_observation = None
    if classification == "dead":
        canonical_observation = {"path": canonical, "sha256": "b" * 64}
        artifacts.append(
            {
                "role": "canonical",
                "path": canonical,
                "sha256": "b" * 64,
                "size": 456,
            }
        )
    output = {
        "source_observation": {
            "path": f"sources/{slug}.mp3",
            "sha256": "c" * 64,
        },
        "generation_observation": {
            "manifest_path": f"processing/talks/{slug}/manifest.json",
            "request_fingerprint": "d" * 64,
        },
        "classification": classification,
        "transcript_changed": False,
        "canonical_observation": canonical_observation,
        "canonical_action": canonical_action,
        "artifacts": artifacts,
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }
    report = _dispatch(
        {
            "invocation": _invocation(
                "talk.prepare",
                slug=slug,
                context=_context(
                    meta={
                        "title": "Exact Talk",
                        "date": "2024-01-02",
                        "media": f"sources/{slug}.mp3",
                        "engines": ["soniox"],
                    },
                    mode="repair",
                    diagnostics=[
                        {
                            "path": canonical,
                            "kind": "missing-section",
                            "reason": "Repair the exact Talk.",
                        }
                    ],
                ),
            ),
            "model_output": output,
        }
    )

    assert report["result"]["kind"] == "receipt"


def _dispatch_talk_prepare_artifacts(
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    slug = "exact-talk"
    output = {
        "source_observation": {
            "path": f"sources/{slug}.mp3",
            "sha256": "a" * 64,
        },
        "generation_observation": {
            "manifest_path": f"processing/talks/{slug}/manifest.json",
            "request_fingerprint": "b" * 64,
        },
        "classification": "live",
        "transcript_changed": False,
        "canonical_observation": None,
        "canonical_action": None,
        "artifacts": artifacts,
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }
    return _dispatch(
        {
            "invocation": _invocation(
                "talk.prepare",
                slug=slug,
                context=_context(
                    meta={
                        "title": "Exact Talk",
                        "date": "2024-01-02",
                        "media": f"sources/{slug}.mp3",
                        "engines": ["soniox"],
                    },
                ),
            ),
            "model_output": output,
        }
    )


def test_talk_prepare_rejects_a_media_path_disguised_as_generation_evidence():
    report = _dispatch_talk_prepare_artifacts(
        [
            {
                "role": "transcript",
                "path": "vault/talks/exact-talk/transcript.md",
                "sha256": "c" * 64,
                "size": 123,
            },
            {
                "role": "engine_transcript",
                "path": "vault/talks/exact-talk/recording.mp4",
                "sha256": "d" * 64,
                "size": 456,
            },
        ]
    )

    assert report["result"]["kind"] == "incoherent_complete"


def test_talk_prepare_rejects_a_duplicate_primary_transcript_path():
    primary = {
        "role": "transcript",
        "path": "vault/talks/exact-talk/transcript.md",
        "sha256": "c" * 64,
        "size": 123,
    }
    report = _dispatch_talk_prepare_artifacts(
        [
            primary,
            {**primary, "sha256": "d" * 64},
            {
                "role": "engine_transcript",
                "path": "processing/talks/exact-talk/transcript.soniox.srt",
                "sha256": "e" * 64,
                "size": 234,
            },
        ]
    )

    assert report["result"]["kind"] == "incoherent_complete"


@pytest.mark.parametrize(
    ("language", "normalized"),
    [(row["input"], row["normalized"]) for row in LANGUAGE_TAGS],
)
def test_workflow_language_normalizer_matches_the_python_contract_fixture(
    language: str,
    normalized: str,
):
    assert (
        run_workflow_export(INPUT_MODULE, "normalizeLanguage", language)
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


def test_book_acquire_rejects_a_truthy_malformed_year_decision_before_agent():
    report = _dispatch(
        {
            "invocation": _invocation(
                "book.acquire",
                context=_context(
                    meta=_search_identity("book", slug="exact-book"),
                    year_decision={"action": "accept-current"},
                ),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["result"]["kind"] == "invalid_context"


def test_book_acquire_batch_flag_cannot_bypass_a_year_mismatch():
    identity = _search_identity("book", slug="exact-book")
    report = _dispatch(
        {
            "invocation": _invocation(
                "book.acquire",
                context=_context(meta=identity, batch_accept_year=True),
            ),
            "model_output": _book_acquire_output(
                _book_year_evidence("MISMATCH")
            ),
        }
    )

    assert report["agentCalls"] == 1
    assert report["result"]["kind"] == "incoherent_complete"
    request = json.loads(
        _prepare(
            "book.acquire",
            context=_context(meta=identity, batch_accept_year=True),
        )["prompt"]
    )
    assert "batch_accept_year" not in request


def test_book_acquire_accept_current_keeps_exact_identity_and_prior_evidence():
    decision = _book_year_decision("accept-current")
    invocation = _invocation(
        "book.acquire",
        context=_context(
            meta=deepcopy(decision["current_identity"]),
            year_decision=deepcopy(decision),
        ),
    )
    report = _dispatch(
        {
            "invocation": invocation,
            "model_output": _book_acquire_output(
                deepcopy(decision["year_evidence"])
            ),
        }
    )

    assert report["result"]["kind"] == "receipt"
    request = json.loads(
        _prepare(
            "book.acquire",
            context=invocation["context"],
        )["prompt"]
    )
    assert request["identity"] == decision["current_identity"]
    assert request["current_identity"] == decision["current_identity"]
    assert request["year_decision"] == decision

    changed_identity = deepcopy(invocation)
    changed_identity["context"]["meta"]["publisher"] = "Another Press"
    rejected_identity = _dispatch(
        {"invocation": changed_identity, "model_output": None}
    )
    changed_evidence = _book_acquire_output(
        deepcopy(decision["year_evidence"])
    )
    changed_evidence["terminal"]["year_evidence"][
        "recommendation_reason"
    ] = "Different evidence."
    rejected_evidence = _dispatch(
        {"invocation": invocation, "model_output": changed_evidence}
    )

    assert rejected_identity["agentCalls"] == 0
    assert rejected_identity["result"]["kind"] == "invalid_context"
    assert rejected_evidence["result"]["kind"] == "incoherent_complete"


def test_book_acquire_use_recommended_accepts_search_identity_without_slug_rewrite():
    decision = _book_year_decision("use-recommended-year")
    search_identity = _search_identity(
        "book",
        slug="metadata-owned-book-2025",
        year=2025,
    )
    invocation = _invocation(
        "book.acquire",
        slug="existing-vault-owner",
        context=_context(
            meta=search_identity,
            year_decision=deepcopy(decision),
        ),
    )
    output = _book_acquire_output(deepcopy(decision["year_evidence"]))
    output["output_path"] = "sources/existing-vault-owner.pdf"
    output["allowed_output_paths"] = [
        "sources/existing-vault-owner.epub",
        "sources/existing-vault-owner.pdf",
    ]

    report = _dispatch({"invocation": invocation, "model_output": output})

    assert report["result"]["kind"] == "receipt"
    request = json.loads(
        _prepare(
            "book.acquire",
            slug="existing-vault-owner",
            context=invocation["context"],
        )["prompt"]
    )
    assert request["identity"] == search_identity
    assert request["identity"]["slug"] != "existing-vault-owner"
    assert request["current_identity"] == decision["current_identity"]


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


def test_search_owner_reconcile_requires_the_selected_identity() -> None:
    selected = {
        "kind": "paper",
        "identity": _search_identity("paper", slug="selected-paper"),
    }
    decision = {
        "candidates": [selected],
        "conflicts": ["title"],
        "selected_candidate": selected,
    }
    invocation = _invocation(
        "material.search",
        kind="paper",
        context=_context(identity_decision=decision),
    )

    accepted = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "paper",
                identity_slug="selected-paper",
                local_owner=None,
            ),
        }
    )
    changed = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "paper",
                identity_slug="different-paper",
                local_owner=None,
            ),
        }
    )

    assert accepted["result"]["kind"] == "receipt"
    assert changed["result"]["kind"] == "incoherent_complete"


def test_search_rejects_accept_current_year_decision_before_agent_dispatch():
    decision = _book_year_decision("accept-current")
    report = _dispatch(
        {
            "invocation": _invocation(
                "material.search",
                kind="book",
                context=_context(year_decision=decision),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["result"]["kind"] == "invalid_context"


def test_book_year_search_requires_the_recommended_year_then_uses_owner_proof():
    decision = _book_year_decision("use-recommended-year")
    invocation = _invocation(
        "material.search",
        kind="book",
        slug="existing-vault-owner",
        context=_context(year_decision=decision),
    )
    old_year = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "book",
                identity_slug="metadata-book-2024",
                local_owner=None,
                year=2024,
            ),
        }
    )
    recommended_year = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "book",
                identity_slug="metadata-book-2025",
                local_owner={
                    "identity_slug": "metadata-book-2025",
                    "vault_slug": "existing-vault-owner",
                    "path": "vault/books/existing-vault-owner/00-overview.md",
                    "match": "isbn",
                },
                year=2025,
            ),
        }
    )

    assert old_year["result"]["kind"] == "incoherent_complete"
    assert recommended_year["result"]["kind"] == "receipt"
    request = json.loads(
        _prepare(
            "material.search",
            kind="book",
            slug="existing-vault-owner",
            context=invocation["context"],
        )["prompt"]
    )
    assert request["current_identity"] == decision["current_identity"]
    assert request["year_decision"] == decision


def test_ordinary_search_request_has_no_book_year_handoff():
    request = json.loads(
        _prepare("material.search", kind="book")["prompt"]
    )

    assert "current_identity" not in request
    assert "year_decision" not in request


def test_search_rejects_a_cross_kind_owner_decision_before_agent_dispatch() -> None:
    selected = {
        "kind": "book",
        "identity": _search_identity("book", slug="selected-book"),
    }
    decision = {
        "candidates": [selected],
        "conflicts": ["publication_type"],
        "selected_candidate": selected,
    }

    report = _dispatch(
        {
            "invocation": _invocation(
                "material.search",
                kind="paper",
                context=_context(identity_decision=decision),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["result"]["kind"] == "invalid_context"


def test_book_search_rejects_a_paper_in_the_echoed_candidate_set() -> None:
    paper = {
        "kind": "paper",
        "identity": _search_identity("paper", slug="selected-paper"),
    }
    book = {
        "kind": "book",
        "identity": _search_identity("book", slug="selected-book"),
    }
    decision = {
        "candidates": [paper, book],
        "conflicts": ["publication_type"],
        "selected_candidate": book,
    }

    report = _dispatch(
        {
            "invocation": _invocation(
                "material.search",
                kind="book",
                context=_context(identity_decision=decision),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["result"]["kind"] == "invalid_context"


def test_pdf_book_structure_gate_uses_direct_manual_split_specs() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
        ),
    )
    terminal = prepared["options"]["schema"]["properties"]["terminal"]
    branch = next(
        item
        for item in terminal["anyOf"]
        if item["properties"]["status"]["const"] == "needs_input"
    )
    properties = branch["properties"]
    chapter = properties["candidates"]["items"]["properties"]["chapters"][
        "items"
    ]

    assert properties["issue"]["properties"]["code"]["const"] == (
        "book.chapter_structure_ambiguous"
    )
    assert properties["source_path"]["enum"] == [
        "sources/exact-material.pdf",
        "processing/chapters/exact-material/ocr.pdf",
    ]
    assert chapter["required"] == ["title", "start", "end"]
    assert chapter["additionalProperties"] is False


def test_translation_gate_is_required_only_inside_needs_input_terminal() -> None:
    schema = _prepare("translation.prepare")["options"]["schema"]
    assert "gate" not in schema["properties"]

    terminal = schema["properties"]["terminal"]
    branch = next(
        item
        for item in terminal["anyOf"]
        if item["properties"]["status"]["const"] == "needs_input"
    )
    assert "gate" in branch["required"]
    gate_variants = branch["properties"]["gate"]["anyOf"]
    assert {
        variant["properties"]["kind"]["const"] for variant in gate_variants
    } == {"source_selection", "configuration_required"}
    assert all(variant["type"] == "object" for variant in gate_variants)
