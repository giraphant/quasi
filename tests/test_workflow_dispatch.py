from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

import pytest

from workflow_test_support import (
    HARNESS,
    ROOT,
    read_workflow_export,
    run_workflow_export,
    run_generated_workflow,
)


GENERATED_CONTRACTS = "scripts/workflows/artifact-contracts/generated.mjs"
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

const preparedDispatch = await load(
  "scripts/workflows/shared/dispatch-prepared.mts",
);
const catalog = await load(config.catalog);
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
  const prepared = catalog.prepareOperation(config.invocation);
  let result;
  if (config.mode === "throwing_predicate") {
    prepared.complete = () => {
      const error = new Error("predicate exploded");
      error.name = "PredicateExplosion";
      throw error;
    };
    result = await preparedDispatch.dispatchPreparedOperation(runtime, prepared);
  } else {
    result = await preparedDispatch.dispatchPreparedOperation(runtime, prepared);
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


def _ocr_generation(
    *,
    kind: str = "paper",
    slug: str = "exact-material",
    profile_name: str = "dsocr2-text",
    source_sha256: str = "a" * 64,
    state: str = "missing",
    completed_pages: int = 0,
    source_pages: int = 15,
) -> dict[str, Any]:
    profile = {
        "schema_version": "quasi.ocr.profile/0.2",
        "language": "chi_sim+eng",
        "text_extractor": "pymupdf",
        "engine_order": (
            ["dsocr2", "tesseract"]
            if profile_name == "dsocr2-text"
            else ["tesseract"]
        ),
        "chunk_pages": 16 if profile_name == "dsocr2-text" else 32,
        "name": profile_name,
        "validation_policy": (
            "paper-text-v1" if kind == "paper" else "book-pdf-v1"
        ),
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    request = {
        "schema_version": "quasi.ocr.generation.request/0.1",
        "material_key": f"{kind}:{slug}",
        "source_path": f"sources/{slug}.pdf",
        "source_sha256": source_sha256,
        "profile": profile,
    }
    generation = hashlib.sha256(
        json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    root = f"processing/{'papers' if kind == 'paper' else 'chapters'}/{slug}"
    generation_dir = f"{root}/ocr-generations/{generation}"
    work_dir = f"{root}/.ocr-work/{generation}"
    progress = None
    if state == "in_progress":
        ranges = []
        cursor = 1
        while cursor <= completed_pages:
            end = min(cursor + profile["chunk_pages"] - 1, completed_pages)
            ranges.append(
                {
                    "start_page": cursor,
                    "end_page": end,
                    "engine": profile["engine_order"][0],
                    "path": (
                        f"{work_dir}/parts/part-{cursor:06d}-{end:06d}."
                        f"{profile['engine_order'][0]}.pdf"
                    ),
                    "sha256": "f" * 64,
                    "pages": end - cursor + 1,
                }
            )
            cursor = end + 1
        progress = {
            "completed_pages": completed_pages,
            "total_pages": source_pages,
            "next_page": (
                completed_pages + 1 if completed_pages < source_pages else None
            ),
            "ranges": ranges,
        }
    return {
        "state": state,
        "material_key": f"{kind}:{slug}",
        "kind": kind,
        "slug": slug,
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": config_fingerprint,
        "source": {
            "path": f"sources/{slug}.pdf",
            "sha256": source_sha256,
            "size": 1234,
            "pages": source_pages,
        },
        "paths": {
            "lock": f"{root}/.ocr-generation.lock",
            "work_dir": work_dir,
            "progress": f"{work_dir}/ocr.progress.json",
            "generation_dir": generation_dir,
            "manifest": f"{generation_dir}/manifest.json",
            "pdf": f"{generation_dir}/ocr.pdf",
            "text": f"{generation_dir}/ocr.txt",
        },
        "progress": progress,
        "manifest": {
            "path": f"{generation_dir}/manifest.json",
            "exists": False,
            "regular": None,
            "sha256": None,
            "size": 0,
        },
        "recovery_pdf": {
            "path": f"{generation_dir}/ocr.pdf",
            "exists": False,
            "regular": None,
            "sha256": None,
            "size": 0,
            "pages": 0,
        },
        "normalized_text": {
            "path": f"{generation_dir}/ocr.txt",
            "exists": False,
            "regular": None,
            "sha256": None,
            "size": 0,
            "utf8": None,
            "chars": 0,
            "non_whitespace_chars": 0,
        },
        "failure": None,
    }


def _paper_ocr_generation(**kwargs: Any) -> dict[str, Any]:
    return _ocr_generation(kind="paper", **kwargs)


def _book_ocr_generation(**kwargs: Any) -> dict[str, Any]:
    return _ocr_generation(kind="book", source_pages=100, **kwargs)


def _paper_source_candidate(
    *,
    format: str = "pdf",
    slug: str = "exact-material",
) -> dict[str, Any]:
    return {
        "format": format,
        "path": f"sources/{slug}.{format}",
        "sha256": ("a" if format == "pdf" else "b") * 64,
        "size": 1234 if format == "pdf" else 4321,
    }


def _context(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "meta": dict(BASE_META),
        "mode": "create",
        "diagnostics": [],
        "pass": 1,
        "query": "exact material",
        "topic": "exact material",
        "fullName": "Ada Example",
        "count": 3,
        "format": "epub",
        "source": "sources/exact-material.epub",
        "input": "processing/papers/exact-material/source.txt",
        "inputs": [],
        "inputPaths": [],
        "outputExists": False,
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
        "memberRefs": [],
        "memberAssignments": [],
        "cardRefs": [],
        "subquestions": [],
        "task": {
            "subq": "sq-opening",
            "query": "exact web evidence",
            "note": "verify the claim",
            "card_slug": "exact-card",
        },
        "target": "vault/topics/exact-material/00-overview.md",
        "targetLanguage": "zh",
        "maxItems": 8,
        "maxCards": 3,
        "candidates": [],
    }
    value.update(overrides)
    return value


OPERATION_FIXTURES: dict[str, tuple[str, dict[str, Any]]] = {
    "archive.identify": ("archive", _context(url="https://example.org/manual")),
    "archive.collect": ("archive", _context(
        identity={"slug":"exact-material","title":"Repair manual","kind":"document","url":"https://example.org/manual"},
        topics=["exact-topic"], createdDate="2026-09-21",
        outputObservation={"path":"vault/archives/exact-material/archive.md","present":False,"usable":False},
    )),
    "archive.audit": ("archive", _context(target="vault/archives/exact-material/archive.md")),
    "topic.discover-archives": ("topic", _context()),
    "webpage.identify": (
        "webpage",
        _context(
            requestedUrl="https://example.org/requested",
            localOwner=None,
        ),
    ),
    "webpage.capture": (
        "webpage",
        _context(
            identity={
                "slug": "exact-material",
                "title": "Exact page",
                "url": "https://example.org/final",
                "site": "Example",
            },
            snapshotObservation={
                "path": "vault/webpages/exact-material/snapshot.webarchive",
                "present": False,
                "usable": False,
            },
        ),
    ),
    "webpage.prepare": (
        "webpage",
        _context(
            snapshotObservation={
                "path": "vault/webpages/exact-material/snapshot.webarchive",
                "present": True,
                "usable": True,
            },
            outputObservation={
                "path": "processing/webpages/exact-material/source.md",
                "present": False,
                "usable": False,
            },
            publicationMode="create",
            snapshotCreated=False,
        ),
    ),
    "webpage.analyse": (
        "webpage",
        _context(
            identity={
                "slug": "exact-material",
                "title": "Exact page",
                "url": "https://example.org/final",
                "site": "Example",
            },
            capturedAt="2026-08-13T12:34:56Z",
            inputObservation={
                "path": "processing/webpages/exact-material/source.md",
                "sha256": "a" * 64,
                "size": 42,
            },
            outputObservation={
                "path": "vault/webpages/exact-material/webpage.md",
                "exists": False,
                "usable": False,
            },
        ),
    ),
    "webpage.audit": (
        "webpage",
        _context(target="vault/webpages/exact-material/webpage.md"),
    ),
    "material.search": ("paper", _context()),
    "paper.acquire": ("paper", _context()),
    "paper.prepare": (
        "paper",
        _context(
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
            sourceCandidate=_paper_source_candidate(),
        ),
    ),
    "paper.ocr": (
        "paper",
        _context(ocrGeneration=_paper_ocr_generation()),
    ),
    "paper.analyse": ("paper", _context()),
    "paper.audit": ("paper", _context(target="vault/papers/exact-material.md")),
    "book.acquire": (
        "book",
        _context(meta={key: value for key, value in BASE_META.items() if key != "format"}),
    ),
    "book.prepare": (
        "book",
        _context(input="sources/exact-material.epub"),
    ),
    "book.ocr": (
        "book",
        _context(ocrGeneration=_book_ocr_generation()),
    ),
    "chapter.analyse": ("book", _context()),
    "book.synthesise": ("book", _context()),
    "book.audit": ("book", _context(target="vault/books/exact-material")),
    "talk.prepare": ("talk", _context()),
    "talk.analyse": ("talk", _context()),
    "talk.audit": ("talk", _context(target="vault/talks/exact-material/talk.md")),
    "translation.prepare": ("translation", _context()),
    "topic.recall": ("topic", _context()),
    "topic.steer": ("topic", _context()),
    "topic.webcard": ("topic", _context(archivePaths=["vault/archives/exact-material/archive.md"], archiveInputs=["vault/archives/exact-material/manifest.yaml"])),
    "topic.synthesise.overview": ("topic", _context()),
    "topic.synthesise.resources": ("topic", _context()),
    "topic.audit": ("topic", _context()),
    "author.discover-books": ("author", _context()),
    "author.discover-papers": ("author", _context()),
    "author.resolve-membership": ("author", _context()),
    "author.synthesise": ("author", _context()),
    "author.audit": ("author", _context(target="vault/authors/exact-material.md")),
}


def _registered_operations() -> dict[str, dict[str, Any]]:
    return read_workflow_export(GENERATED_CONTRACTS, "OPERATION_CATALOG")


def _catalog_module(kind: str) -> str:
    return f"scripts/workflows/operations/catalogs/{kind}.mts"


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
    invocation = _invocation(operation, **overrides)
    kind = invocation.pop("kind")
    return run_workflow_export(
        _catalog_module(kind),
        "prepareOperation",
        invocation,
    )


def _terminal_statuses(prepared: dict[str, Any]) -> set[str]:
    terminal = prepared["options"]["schema"]["properties"]["terminal"]
    return {
        branch["properties"]["status"]["const"]
        for branch in terminal["anyOf"]
    }


def _terminal_branches(prepared: dict[str, Any]) -> dict[str, dict[str, Any]]:
    terminal = prepared["options"]["schema"]["properties"]["terminal"]
    return {
        branch["properties"]["status"]["const"]: branch
        for branch in terminal["anyOf"]
    }


def _prompt_request(prompt: str) -> dict[str, Any]:
    if prompt.startswith("{"):
        return json.loads(prompt)
    if "```json\n" in prompt:
        payload = prompt.rsplit("```json\n", 1)[1].split("\n```", 1)[0]
        return json.loads(payload)
    return json.loads(prompt[prompt.index("\n{") + 1 :])


def _bare_consts(node: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        if "const" in node and "type" not in node:
            found.append(path)
        for key, value in node.items():
            if key not in {"const", "enum", "default", "examples"}:
                found.extend(_bare_consts(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_bare_consts(value, f"{path}/{index}"))
    return found


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
    local_config = deepcopy(config)
    invocation = local_config["invocation"]
    kind = invocation.pop("kind")
    local_config["catalog"] = _catalog_module(kind)
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            DISPATCH_HARNESS,
            json.dumps(local_config),
        ],
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


def _paper_prepare_output(
    *,
    selected_input: str | None,
    artifact_path: str,
    usable: bool,
    disposition: str,
) -> dict[str, Any]:
    return {
        "selected_input": selected_input,
        "artifacts": [
            {
                "role": "normalized_text",
                "path": artifact_path,
                "exists": True,
                "usable": usable,
            }
        ],
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": disposition,
        },
    }


def _book_prepare_output(**overrides: Any) -> dict[str, Any]:
    output = {
        "format": "pdf",
        "output_dir": "processing/chapters/exact-material",
        "selected_source": None,
        "normalized_path": None,
        "manifest_path": "processing/chapters/exact-material/manifest.json",
        "manifest_fingerprint": None,
        "mode": None,
        "disposition": None,
        "chapter_count": 0,
        "chapters": [],
        "artifacts": [],
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": "ocr_required",
        },
    }
    output.update(overrides)
    return output


def _paper_ocr_artifacts(
    generation: dict[str, Any],
    *,
    committed: bool,
) -> list[dict[str, Any]]:
    paths = generation["paths"]
    if not committed:
        return [
            {
                "path": paths["pdf"],
                "exists": False,
                "regular": None,
                "sha256": None,
                "size": 0,
                "pages": 0,
            },
            {
                "path": paths["text"],
                "exists": False,
                "regular": None,
                "sha256": None,
                "size": 0,
                "utf8": None,
                "chars": 0,
                "non_whitespace_chars": 0,
            },
            {
                "path": paths["manifest"],
                "exists": False,
                "regular": None,
                "sha256": None,
                "size": 0,
            },
        ]
    return [
        {
            "path": paths["pdf"],
            "exists": True,
            "regular": True,
            "sha256": "b" * 64,
            "size": 2400,
            "pages": generation["source"]["pages"],
        },
        {
            "path": paths["text"],
            "exists": True,
            "regular": True,
            "sha256": "c" * 64,
            "size": 1800,
            "utf8": True,
            "chars": 1700,
            "non_whitespace_chars": 1400,
        },
        {
            "path": paths["manifest"],
            "exists": True,
            "regular": True,
            "sha256": "d" * 64,
            "size": 900,
        },
    ]


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
    owner_slug: str | None,
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "terminal": {
            "status": "complete",
            "issue": None,
            "identity": _search_identity(kind, slug=identity_slug, year=year),
            "owner_slug": owner_slug,
        },
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
    write_state: str = "written",
    source: str = "publisher",
) -> dict[str, Any]:
    return {
        "output_path": "sources/exact-material.pdf",
        "format": "pdf",
        "allowed_output_paths": [
            "sources/exact-material.epub",
            "sources/exact-material.pdf",
        ],
        "write_state": write_state,
        "identity_verified": True,
        "isbn": "9780000000000",
        "attempts": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "source": source,
            "tmp_path": tmp_path,
            "year_evidence": evidence,
        },
    }


def _search_status_output(status: str) -> dict[str, Any]:
    if status == "complete":
        return _search_output(
            "paper",
            identity_slug="selected-paper",
            owner_slug=None,
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
    return {"terminal": terminal}


def test_search_complete_accepts_null_owner_slug_as_an_observed_miss() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind="paper"),
            "model_output": _search_output(
                "paper",
                identity_slug="selected-paper",
                owner_slug=None,
            ),
        }
    )

    assert report["result"]["kind"] == "receipt"


@pytest.mark.parametrize("kind", ["paper", "book"])
def test_material_search_model_schema_stays_under_claude_auto_cap(kind: str) -> None:
    """Catches a regression that inlines canonical identities per terminal."""
    schema = _prepare("material.search", kind=kind)["options"]["schema"]

    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))) <= 4096


@pytest.mark.parametrize("status", ["needs_input", "blocked", "failed"])
def test_search_non_complete_model_schema_excludes_legacy_fake_identity_fields(
    status: str,
) -> None:
    """Catches a regression that makes non-complete outputs carry fake facts."""
    schema = _prepare("material.search", kind="paper")["options"]["schema"]
    branch = _terminal_branches(_prepare("material.search", kind="paper"))[status]

    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"terminal"}
    assert all(
        field not in branch["properties"]
        for field in ("identity", "local_owner", "confidence", "observations")
    )


def test_search_complete_schema_excludes_the_removed_owner_object_shape() -> None:
    schema = _prepare("material.search", kind="paper")["options"]["schema"]
    complete = _terminal_branches(_prepare("material.search", kind="paper"))["complete"]

    assert schema["additionalProperties"] is False
    assert complete["additionalProperties"] is False
    assert set(complete["required"]) == {"status", "issue", "identity", "owner_slug"}
    assert "local_owner" not in complete["properties"]


@pytest.mark.parametrize(
    ("kind", "vault_slug"),
    [
        ("paper", "existing-paper"),
        ("book", "existing-book"),
    ],
)
def test_search_complete_accepts_one_owner_slug_bound_to_the_identity(
    kind: str,
    vault_slug: str,
) -> None:
    report = _dispatch(
        {
            "invocation": _invocation("material.search", kind=kind),
            "model_output": _search_output(
                kind,
                identity_slug="selected-identity",
                owner_slug=vault_slug,
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


def test_local_preparation_rejects_bad_context_before_agent_dispatch() -> None:
    report = _dispatch(
        {"invocation": _audit_invocation(slug=None), "model_output": None}
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"
    assert "invalid material slug" in report["thrown"]["message"]


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
    invocation = _invocation("paper.acquire", slug=None)
    invocation.pop("kind")
    stderr = _export_failure(
        _catalog_module("paper"),
        "prepareOperation",
        invocation,
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


def test_local_catalogs_preserve_each_operation_identity_and_schema_partition():
    registered = _registered_operations()
    assert set(OPERATION_FIXTURES) == set(registered)

    statuses: set[str] = set()
    for operation, definition in registered.items():
        for kind in definition["kinds"]:
            prepared = _prepare(operation, kind=kind)
            schema = prepared["options"]["schema"]
            stamps = prepared["stampedValues"]
            request = _prompt_request(prepared["prompt"])

            assert prepared["invocation"]["operation"] == operation
            assert prepared["invocation"]["kind"] == kind
            assert prepared["options"]["agentType"] == definition["agent"]
            assert prepared["options"]["phase"] == definition["phase"]
            assert prepared["options"]["label"] == f"exact-material:{operation}"
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"])
            assert set(schema["properties"]).isdisjoint(stamps)
            assert _bare_consts(schema) == []
            assert stamps["operation"] == operation
            assert stamps["effect"] == definition["effect"]
            assert stamps["stage"] == definition["phase"]
            assert request["schema_version"] == "quasi.stage.request/0.2"
            assert request["operation"] == operation
            assert request["stage"] == definition["phase"]
            statuses.update(_terminal_statuses(prepared))

    assert statuses == {"complete", "needs_input", "blocked", "failed"}


def test_webpage_descriptor_catalog_has_one_owned_output_per_producer() -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    assert _prepare("webpage.identify")["writeTargets"] == []
    assert _prepare("webpage.capture")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "vault/webpages/exact-material/snapshot.webarchive",
        }
    ]
    assert _prepare("webpage.prepare")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "processing/webpages/exact-material/source.md",
        }
    ]
    assert _prepare("webpage.analyse")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "vault/webpages/exact-material/webpage.md",
        }
    ]


def test_webpage_identify_binds_an_optional_owner_to_the_returned_identity() -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    matching = _dispatch(
        {
            "invocation": _invocation("webpage.identify"),
            "model_output": {
                "identity": {
                    "slug": "exact-material",
                    "title": "Exact page",
                    "url": "https://example.org/final",
                    "site": "Example",
                },
                "local_owner": {
                    "slug": "exact-material",
                    "path": "vault/webpages/exact-material/snapshot.webarchive",
                },
                "terminal": {"status": "complete", "issue": None},
            },
        }
    )
    mismatched = _dispatch(
        {
            "invocation": _invocation("webpage.identify"),
            "model_output": {
                "identity": {
                    "slug": "exact-material",
                    "title": "Exact page",
                    "url": "https://example.org/final",
                    "site": "Example",
                },
                "local_owner": {
                    "slug": "other-owner",
                    "path": "vault/webpages/other-owner/webpage.md",
                },
                "terminal": {"status": "complete", "issue": None},
            },
        }
    )

    assert matching["result"]["kind"] == "receipt"
    assert mismatched["result"]["kind"] == "incoherent_complete"


def test_webpage_capture_receipt_binds_the_exact_snapshot_and_capture_evidence() -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    prepared = _prepare("webpage.capture")
    schema = prepared["options"]["schema"]
    assert schema["properties"]["title"]["minLength"] == 1
    assert schema["properties"]["site"]["minLength"] == 1
    assert schema["properties"]["captured_at"]["pattern"].endswith("Z$")
    assert schema["properties"]["sha256"]["pattern"] == "^[a-f0-9]{64}$"
    assert schema["properties"]["size"] == {"type": "integer", "minimum": 1}
    assert prepared["stampedValues"] == {
        "schema_version": "quasi.stage.receipt/0.3",
        "operation": "webpage.capture",
        "stage": "Acquire",
        "material_key": "webpage:exact-material",
        "effect": "writer",
        "attempt": 1,
        "snapshot_path": "vault/webpages/exact-material/snapshot.webarchive",
        "final_url": "https://example.org/final",
        "write_state": "written",
    }


@pytest.mark.parametrize(
    ("publication_mode", "snapshot_created", "present", "usable", "write_state"),
    [
        ("create", False, False, False, "written"),
        ("create", True, False, False, "written"),
        ("replace_stale", True, True, False, "written"),
        ("replace_stale", True, True, True, "written"),
        ("reconcile", False, True, True, "not_written"),
    ],
)
def test_webpage_prepare_binds_observed_artifacts_and_its_single_effect_claim(
    publication_mode: str,
    snapshot_created: bool,
    present: bool,
    usable: bool,
    write_state: str,
) -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    context = _context(
        snapshotObservation={
            "path": "vault/webpages/exact-material/snapshot.webarchive",
            "present": True,
            "usable": True,
        },
        outputObservation={
            "path": "processing/webpages/exact-material/source.md",
            "present": present,
            "usable": usable,
        },
        publicationMode=publication_mode,
        snapshotCreated=snapshot_created,
    )
    prepared = _prepare("webpage.prepare", context=context)
    schema = prepared["options"]["schema"]
    assert schema["properties"]["source_sha256"]["pattern"] == "^[a-f0-9]{64}$"
    assert schema["properties"]["source_size"] == {"type": "integer", "minimum": 1}
    assert prepared["stampedValues"]["snapshot_path"] == (
        "vault/webpages/exact-material/snapshot.webarchive"
    )
    assert prepared["stampedValues"]["output_path"] == (
        "processing/webpages/exact-material/source.md"
    )
    assert prepared["stampedValues"]["write_state"] == write_state
    assert prepared["stampedValues"]["publication_mode"] == publication_mode
    assert prepared["stampedValues"]["content_ready"] is True
    request = _prompt_request(prepared["prompt"])
    assert request["publication_mode"] == publication_mode
    assert request["snapshot_created"] is snapshot_created
    assert request["output_observation"] == {
        "path": "processing/webpages/exact-material/source.md",
        "present": present,
        "usable": usable,
    }


@pytest.mark.parametrize(
    ("publication_mode", "snapshot_created", "present", "usable"),
    [
        ("create", False, False, True),
        ("create", False, True, False),
        ("replace_stale", False, True, True),
        ("replace_stale", True, False, False),
        ("reconcile", True, True, True),
        ("reconcile", False, True, False),
    ],
)
def test_webpage_prepare_rejects_incoherent_publication_modes(
    publication_mode: str,
    snapshot_created: bool,
    present: bool,
    usable: bool,
) -> None:
    context = _context(
        snapshotObservation={
            "path": "vault/webpages/exact-material/snapshot.webarchive",
            "present": True,
            "usable": True,
        },
        outputObservation={
            "path": "processing/webpages/exact-material/source.md",
            "present": present,
            "usable": usable,
        },
        publicationMode=publication_mode,
        snapshotCreated=snapshot_created,
    )

    invocation = _invocation("webpage.prepare", context=context)
    invocation.pop("kind")
    stderr = _export_failure(
        _catalog_module("webpage"),
        "prepareOperation",
        invocation,
    )

    assert "InputContractError" in stderr


def test_webpage_analyse_receives_the_exact_projection_and_semantic_seed() -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    request = _prompt_request(_prepare("webpage.analyse")["prompt"])
    assert request["input"] == {
        "role": "normalized_text",
        "path": "processing/webpages/exact-material/source.md",
        "sha256": "a" * 64,
        "size": 42,
    }
    assert request["output"] == {
        "role": "canonical",
        "path": "vault/webpages/exact-material/webpage.md",
    }
    assert request["artifact_contract"]["artifact_type"] == "webpage"
    assert request["frontmatter_seed"] == {
        "type": "webpage",
        "title": "Exact page",
        "url": "https://example.org/final",
        "site": "Example",
        "captured_at": "2026-08-13T12:34:56Z",
    }


def test_webpage_audit_targets_only_the_canonical_page() -> None:
    catalog_path = ROOT / "scripts/workflows/operations/catalogs/webpage.mts"
    assert catalog_path.is_file()

    request = _prompt_request(_prepare("webpage.audit")["prompt"])
    assert request["target"] == {
        "role": "canonical",
        "path": "vault/webpages/exact-material/webpage.md",
    }


def test_material_search_stage_terminal_union_has_four_closed_branches() -> None:
    prepared = _prepare("material.search")
    branches = _terminal_branches(prepared)

    assert set(branches) == {"complete", "needs_input", "blocked", "failed"}
    for branch in branches.values():
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == set(branch["properties"])

    assert branches["complete"]["properties"]["issue"] == {"type": "null"}
    issue_fields = {
        "code",
        "operation",
        "summary",
        "user_question",
        "retryable",
    }
    definitions = prepared["options"]["schema"]["definitions"]
    for definition in ("issue", "conflict_issue"):
        issue = definitions[definition]
        assert issue["type"] == "object"
        assert issue["additionalProperties"] is False
        assert set(issue["required"]) == issue_fields
        assert set(issue["properties"]) == issue_fields
    assert branches["needs_input"]["properties"]["issue"] == {
        "$ref": "#/definitions/conflict_issue"
    }
    for status in ("blocked", "failed"):
        assert branches[status]["properties"]["issue"] == {
            "$ref": "#/definitions/issue"
        }


def test_paper_search_failed_receipt_may_carry_only_one_webpage_redirect_url() -> None:
    paper = _prepare("material.search")
    book = _prepare("material.search", kind="book")
    paper_failed = _terminal_branches(paper)["failed"]
    book_failed = _terminal_branches(book)["failed"]

    assert paper_failed["properties"]["webpage_url"] == {
        "type": ["string", "null"],
        "maxLength": 2048,
    }
    assert "webpage_url" not in book_failed["properties"]

    report = _dispatch(
        {
            "invocation": _invocation("material.search"),
            "model_output": {
                "terminal": {
                    "status": "failed",
                    "issue": {
                        "code": "material.webpage_redirect",
                        "operation": "material.search",
                        "summary": "The requested item is a public web article.",
                        "user_question": None,
                        "retryable": False,
                    },
                    "webpage_url": "https://example.org/essay",
                },
            },
        }
    )
    assert report["result"]["kind"] == "receipt"
    assert report["result"]["receipt"]["terminal"]["webpage_url"] == (
        "https://example.org/essay"
    )


@pytest.mark.parametrize(
    ("output_exists", "action", "write_state"),
    [
        (False, "create", "written"),
        (True, "reconciled", "not_written"),
    ],
)
def test_chapter_analyse_schema_binds_complete_to_output_testimony(
    output_exists: bool,
    action: str,
    write_state: str,
) -> None:
    branches = _terminal_branches(
        _prepare(
            "chapter.analyse",
            context=_context(outputExists=output_exists),
        )
    )

    complete = branches["complete"]
    assert complete["properties"]["action"] == {
        "const": action,
        "type": "string",
    }
    assert complete["properties"]["write_state"] == {
        "const": write_state,
        "type": "string",
    }


def test_chapter_analyse_requires_caller_output_testimony() -> None:
    context = _context(
        chapter={
            "slot": "01",
            "slug": "introduction",
            "filename": "ch01-introduction.md",
            "title": "Introduction",
        }
    )
    context.pop("outputExists")
    invocation = _invocation("chapter.analyse", context=context)
    invocation.pop("kind")

    stderr = _export_failure(
        _catalog_module("book"),
        "prepareOperation",
        invocation,
    )

    assert "chapter.analyse requires boolean context.outputExists" in stderr


@pytest.mark.parametrize(
    ("title", "chapter_label", "expected_title"),
    [
        ("Introduction: Politics and Ethics", None, "Introduction: Politics and Ethics"),
        (
            "Introduction: Politics and Ethics",
            "导论",
            "导论 Introduction: Politics and Ethics",
        ),
        (
            "导论 Introduction: Politics and Ethics",
            "导论",
            "导论 Introduction: Politics and Ethics",
        ),
    ],
)
def test_chapter_analyse_preserves_or_prefixes_the_manifest_title_once(
    title: str,
    chapter_label: str | None,
    expected_title: str,
) -> None:
    chapter = {
        "slot": "00a",
        "slug": "introduction",
        "filename": "ch00a-introduction.md",
        "title": title,
    }
    if chapter_label is not None:
        chapter["chapter_label"] = chapter_label
    prepared = _prepare(
        "chapter.analyse",
        slug="example-book",
        context=_context(chapter=chapter, outputExists=False),
    )
    request = _prompt_request(prepared["prompt"])

    assert request["frontmatter_seed"]["title"] == expected_title
    assert request["identity"]["chapter_label"] == chapter_label
    assert request["output_observation"] == {
        "path": "vault/books/example-book/ch00a-introduction.md",
        "exists": False,
        "authority": "caller",
    }


def test_paper_acquire_preserves_both_urls_and_real_diagnostic_capabilities() -> None:
    prepared = _prepare(
        "paper.acquire",
        slug="example-paper",
        context=_context(
            meta={
                "title": "Example Title",
                "authors": ["Example Author"],
                "year": 1991,
                "doi": None,
                "oa_url": "https://example.org/example.pdf",
                "url": "https://www.jstor.org/stable/43154235",
            }
        ),
    )
    request = _prompt_request(prepared["prompt"])

    assert request["identity"]["oa_url"] == "https://example.org/example.pdf"
    assert request["identity"]["url"] == (
        "https://www.jstor.org/stable/43154235"
    )
    assert request["capabilities"][0].startswith(
        "quasi-download paper fetch --slug"
    )
    assert "--output" not in request["capabilities"][0]
    assert request["capabilities"][1] == (
        "quasi-download paper diagnose --url URL [--via-ezproxy] "
        "[--timeout SECONDS] --json"
    )
    assert any(
        "identity_uncertain" in capability
        for capability in request["capabilities"]
    )


def test_acquire_terminal_fields_remain_branch_local() -> None:
    paper_schema = _prepare("paper.acquire")["options"]["schema"]
    book_schema = _prepare("book.acquire")["options"]["schema"]

    for schema in (paper_schema, book_schema):
        assert "disposition" not in schema["properties"]
        assert "source" not in schema["properties"]
        branches = {
            branch["properties"]["status"]["const"]: branch
            for branch in schema["properties"]["terminal"]["anyOf"]
        }
        assert "source" in branches["complete"]["required"]
        assert "disposition" not in branches["complete"]["required"]
        assert "disposition" not in branches["complete"]["properties"]
        for status, branch in branches.items():
            if status != "complete":
                assert "disposition" not in branch["properties"]
                assert "source" not in branch["properties"]

    assert "tmp_path" not in book_schema["properties"]
    assert "year_evidence" not in book_schema["properties"]
    book_branches = {
        branch["properties"]["status"]["const"]: branch
        for branch in book_schema["properties"]["terminal"]["anyOf"]
    }
    assert {"tmp_path", "year_evidence"}.issubset(
        book_branches["complete"]["required"]
    )
    assert {"tmp_path", "year_evidence", "proposed_actions"}.issubset(
        book_branches["needs_input"]["required"]
    )
    assert "proposed_actions" not in book_branches["complete"]["properties"]


def test_paper_acquire_write_state_is_the_sole_effect_claim() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("paper.acquire"),
            "model_output": {
                "output_path": "sources/exact-material.pdf",
                "write_state": "written",
                "identity_verified": True,
                "terminal": {
                    "status": "complete",
                    "issue": None,
                    "source": "existing_file",
                },
            },
        }
    )

    assert report["result"]["kind"] == "receipt"
    assert report["result"]["receipt"]["output_path"] == (
        "sources/exact-material.pdf"
    )
    assert report["result"]["receipt"]["doi"] == "10.1000/exact"


def test_paper_acquire_exposes_pdf_and_text_source_alternatives() -> None:
    prepared = _prepare("paper.acquire")
    request = _prompt_request(prepared["prompt"])
    schema = prepared["options"]["schema"]

    assert prepared["writeTargets"] == [
        {"scope": "exact", "path": "sources/exact-material.pdf"},
        {"scope": "exact", "path": "sources/exact-material.txt"},
    ]
    assert request["allowed_outputs"] == [
        {"format": "pdf", "path": "sources/exact-material.pdf"},
        {"format": "txt", "path": "sources/exact-material.txt"},
    ]
    assert "--budget-seconds 30..540" in request["capabilities"][0]
    assert schema["properties"]["output_path"]["enum"] == [
        "sources/exact-material.pdf",
        "sources/exact-material.txt",
    ]


def test_paper_acquire_admits_the_typed_budget_boundary() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("paper.acquire"),
            "model_output": {
                "output_path": "sources/exact-material.pdf",
                "write_state": "not_written",
                "identity_verified": False,
                "terminal": {
                    "status": "blocked",
                    "issue": {
                        "code": "paper.acquire_blocked",
                        "operation": "paper.acquire",
                        "summary": "The bounded cascade ended before a source was found.",
                        "user_question": None,
                        "retryable": True,
                    },
                },
            },
        }
    )

    assert report["result"]["kind"] == "receipt"
    assert report["result"]["receipt"]["terminal"]["issue"]["code"] == (
        "paper.acquire_blocked"
    )


def test_paper_acquire_unknown_write_state_is_incoherent_complete() -> None:
    report = _dispatch(
        {
            "invocation": _invocation("paper.acquire"),
            "model_output": {
                "write_state": "unknown",
                "identity_verified": True,
                "terminal": {
                    "status": "complete",
                    "issue": None,
                    "source": "existing_file",
                },
            },
        }
    )

    assert report["result"]["kind"] == "incoherent_complete"


def test_paper_prepare_separates_direct_text_from_immutable_ocr() -> None:
    direct = _prepare(
        "paper.prepare",
        context=_context(
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
            sourceCandidate=_paper_source_candidate(),
        ),
    )
    direct_request = _prompt_request(direct["prompt"])
    assert direct["writeTargets"] == [
        {"scope": "exact", "path": "processing/papers/exact-material/source.txt"}
    ]
    assert direct_request["input"] == {
        "role": "source_pdf",
        "path": "sources/exact-material.pdf",
    }
    assert direct_request["source"] == _paper_source_candidate()
    for mechanical_field in ("source_format", "source_sha256", "source_size"):
        assert mechanical_field not in direct["options"]["schema"]["properties"]
    assert direct_request["refs"]["legacy_recovery_source"] == (
        "processing/papers/exact-material/ocr.pdf"
    )
    assert direct_request["refs"]["legacy_recovery_text"] == (
        "processing/papers/exact-material/ocr.txt"
    )
    assert all("quasi-extract ocr " not in item for item in direct_request["capabilities"])

    generation = _paper_ocr_generation()
    generation_text = generation["paths"]["text"]
    prepared_generation = _prepare(
        "paper.prepare",
        context=_context(
            source="sources/exact-material.pdf",
            input=generation_text,
            generationKey=generation["generation_key"],
            sourceCandidate=_paper_source_candidate(),
        ),
    )
    generation_request = _prompt_request(prepared_generation["prompt"])
    assert generation_request["input"] == {
        "role": "generation_text",
        "path": generation_text,
    }
    assert generation_request["capabilities"] == [
        "Read only the exact generation_text input named by this request; "
        "do not read or compare the fixed normalized or legacy recovery refs."
    ]
    generation_artifacts = prepared_generation["options"]["schema"]["properties"][
        "artifacts"
    ]
    assert generation_artifacts["maxItems"] == 1
    assert generation_artifacts["items"]["properties"]["path"]["enum"] == [
        generation_text
    ]


def test_paper_prepare_dispositions_enforce_input_semantics() -> None:
    normalized = "processing/papers/exact-material/source.txt"
    prepared = _dispatch(
        {
            "invocation": _invocation(
                "paper.prepare",
                context=_context(
                    source="sources/exact-material.pdf",
                    input="sources/exact-material.pdf",
                    sourceCandidate=_paper_source_candidate(),
                ),
            ),
            "model_output": _paper_prepare_output(
                selected_input=normalized,
                artifact_path=normalized,
                usable=True,
                disposition="full_text_prepared",
            ),
        }
    )
    ocr_required = _dispatch(
        {
            "invocation": _invocation(
                "paper.prepare",
                context=_context(
                    source="sources/exact-material.pdf",
                    input="sources/exact-material.pdf",
                    sourceCandidate=_paper_source_candidate(),
                ),
            ),
            "model_output": _paper_prepare_output(
                selected_input=None,
                artifact_path=normalized,
                usable=False,
                disposition="ocr_required",
            ),
        }
    )
    txt_cannot_request_ocr = _dispatch(
        {
            "invocation": _invocation(
                "paper.prepare",
                context=_context(
                    source="sources/exact-material.txt",
                    input="sources/exact-material.txt",
                    sourceCandidate=_paper_source_candidate(format="txt"),
                ),
            ),
            "model_output": _paper_prepare_output(
                selected_input=None,
                artifact_path=normalized,
                usable=False,
                disposition="ocr_required",
            ),
        }
    )

    assert prepared["result"]["kind"] == "receipt"
    assert prepared["result"]["receipt"]["input_kind"] == "source_pdf"
    assert ocr_required["result"]["kind"] == "receipt"
    assert txt_cannot_request_ocr["result"]["kind"] == "incoherent_complete"

    legacy_prepared = _dispatch(
        {
            "invocation": _invocation(
                "paper.prepare",
                context=_context(
                    source="sources/exact-material.pdf",
                    input="sources/exact-material.pdf",
                    sourceCandidate=_paper_source_candidate(),
                ),
            ),
            "model_output": _paper_prepare_output(
                selected_input=normalized,
                artifact_path=normalized,
                usable=True,
                disposition="prepared",
            ),
        }
    )
    assert legacy_prepared["result"]["kind"] != "receipt"


def test_paper_prepare_rejects_source_candidate_mismatch_before_dispatch() -> None:
    mismatched = _paper_source_candidate()
    mismatched["sha256"] = "c" * 64
    report = _dispatch(
        {
            "invocation": _invocation(
                "paper.prepare",
                context=_context(
                    source="sources/exact-material.txt",
                    input="sources/exact-material.txt",
                    sourceCandidate=mismatched,
                ),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"


def test_paper_prepare_text_failure_is_source_incomplete() -> None:
    prepared = _prepare(
        "paper.prepare",
        context=_context(
            source="sources/exact-material.txt",
            input="sources/exact-material.txt",
            sourceCandidate=_paper_source_candidate(format="txt"),
        ),
    )
    failed = _terminal_branches(prepared)["failed"]

    assert (
        failed["properties"]["issue"]["properties"]["code"]["const"]
        == "paper.source_incomplete"
    )


def test_paper_prepare_generation_text_must_match_its_exact_key() -> None:
    generation = _paper_ocr_generation()
    context = _context(
        source="sources/exact-material.pdf",
        input=generation["paths"]["text"],
        generationKey="b" * 64,
        sourceCandidate=_paper_source_candidate(),
    )
    report = _dispatch(
        {
            "invocation": _invocation("paper.prepare", context=context),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"


def test_paper_ocr_owns_only_the_exact_generation_transaction() -> None:
    generation = _paper_ocr_generation()
    prepared = _prepare(
        "paper.ocr",
        context=_context(ocrGeneration=generation),
    )
    request = _prompt_request(prepared["prompt"])

    assert prepared["stampedValues"]["generation_key"] == generation["generation_key"]
    assert prepared["stampedValues"]["config_fingerprint"] == (
        generation["config_fingerprint"]
    )
    assert prepared["stampedValues"]["source"] == generation["source"]
    assert prepared["stampedValues"]["paths"] == generation["paths"]
    assert request["capabilities"] == [
        "quasi-extract ocr-generation --kind paper --slug 'exact-material' "
        "--source-file 'sources/exact-material.pdf' "
        f"--expected-source-sha256 '{generation['source']['sha256']}' "
        f"--generation-key '{generation['generation_key']}' "
        "--profile 'dsocr2-text' --json"
    ]
    progress_schema = prepared["options"]["schema"]["properties"]["progress"]
    assert progress_schema["anyOf"][1]["properties"]["next_page"] == {
        "type": ["integer", "null"],
        "minimum": 1,
    }
    assert all("generic OCR" not in item for item in request["capabilities"])


def test_paper_ocr_accepts_one_profile_range_and_rejects_extra_progress() -> None:
    generation = _paper_ocr_generation(source_pages=40)
    invocation = _invocation(
        "paper.ocr",
        context=_context(ocrGeneration=generation),
    )
    model_output = {
        "state": "in_progress",
        "progress": {
            "completed_pages": 16,
            "total_pages": 40,
            "next_page": 17,
            "ranges": [
                {
                    "start_page": 1,
                    "end_page": 16,
                    "engine": "dsocr2",
                    "path": (
                        f"{generation['paths']['work_dir']}/parts/"
                        "part-000001-000016.dsocr2.pdf"
                    ),
                    "sha256": "f" * 64,
                    "pages": 16,
                }
            ],
        },
        "artifacts": _paper_ocr_artifacts(generation, committed=False),
        "failure": None,
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": "partial",
        },
    }
    accepted = _dispatch(
        {"invocation": invocation, "model_output": deepcopy(model_output)}
    )
    model_output["progress"]["completed_pages"] = 17
    model_output["progress"]["next_page"] = 18
    rejected = _dispatch({"invocation": invocation, "model_output": model_output})

    assert accepted["result"]["kind"] == "receipt"
    assert rejected["result"]["kind"] == "incoherent_complete"


def test_paper_ocr_requires_committed_artifacts_for_publication() -> None:
    generation = _paper_ocr_generation(source_pages=7)
    invocation = _invocation(
        "paper.ocr",
        context=_context(ocrGeneration=generation),
    )
    model_output = {
        "state": "committed",
        "progress": None,
        "artifacts": _paper_ocr_artifacts(generation, committed=True),
        "failure": None,
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": "created",
        },
    }
    accepted = _dispatch(
        {"invocation": invocation, "model_output": deepcopy(model_output)}
    )
    completed_progress = deepcopy(model_output)
    completed_progress["progress"] = {
        "completed_pages": 7,
        "total_pages": 7,
        "next_page": None,
        "ranges": [
            {
                "start_page": 1,
                "end_page": 7,
                "engine": "dsocr2",
                "path": (
                    f"{generation['paths']['work_dir']}/parts/"
                    "part-000001-000007.dsocr2.pdf"
                ),
                "sha256": "f" * 64,
                "pages": 7,
            }
        ],
    }
    progress_rejected = _dispatch(
        {"invocation": invocation, "model_output": completed_progress}
    )
    model_output["artifacts"][1]["non_whitespace_chars"] = 0
    artifact_rejected = _dispatch(
        {"invocation": invocation, "model_output": model_output}
    )

    assert accepted["result"]["kind"] == "receipt"
    assert progress_rejected["result"]["kind"] == "incoherent_complete"
    assert artifact_rejected["result"]["kind"] == "incoherent_complete"


def test_paper_ocr_rejects_non_current_generation_before_dispatch() -> None:
    generation = _paper_ocr_generation(state="committed")
    report = _dispatch(
        {
            "invocation": _invocation(
                "paper.ocr",
                context=_context(ocrGeneration=generation),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"


def test_only_operations_with_typed_gates_expose_needs_input() -> None:
    actual = set()
    for operation, definition in _registered_operations().items():
        kind = definition["kinds"][0]
        overrides: dict[str, Any] = {"kind": kind}
        if operation == "book.prepare":
            overrides["context"] = _context(
                format="pdf",
                source="sources/exact-material.pdf",
                input="sources/exact-material.pdf",
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

    for operation, definition in registered.items():
        targets = _prepare(operation, kind=definition["kinds"][0])["writeTargets"]
        if definition["effect"] == "readonly":
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
    ]
    generation = _paper_ocr_generation()["generation_key"]
    assert _prepare("paper.ocr")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "processing/papers/exact-material/.ocr-generation.lock",
        },
        {
            "scope": "subtree",
            "path": f"processing/papers/exact-material/.ocr-work/{generation}",
        },
        {
            "scope": "subtree",
            "path": f"processing/papers/exact-material/ocr-generations/{generation}",
        },
    ]
    assert _prepare("book.prepare")["writeTargets"] == [
        {"scope": "subtree", "path": "processing/chapters/exact-material"}
    ]
    assert _prepare("translation.prepare")["writeTargets"] == [
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh.pdf",
        },
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh.manifest.json",
        },
        {
            "scope": "exact",
            "path": "processing/translations/exact-material-zh-reocr.pdf",
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
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slug = "exact-talk"
    output = {
        "source_observation": {
            "path": (meta or {}).get("media", f"sources/{slug}.mp3"),
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
                        **(meta or {}),
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


def test_book_acquire_conservatively_owns_both_possible_sources():
    assert _prepare("book.acquire")["writeTargets"] == [
        {"scope": "exact", "path": "sources/exact-material.epub"},
        {"scope": "exact", "path": "sources/exact-material.pdf"},
    ]


def test_book_acquire_distinguishes_unavailable_search_and_allows_query_reformulation():
    prepared = _prepare("book.acquire")
    request = _prompt_request(prepared["prompt"])
    failed = next(
        branch
        for branch in prepared["options"]["schema"]["properties"]["terminal"]["anyOf"]
        if branch["properties"]["status"]["const"] == "failed"
    )

    assert request["capabilities"][0] == (
        "quasi-download book candidates (--title TITLE --author AUTHOR | "
        "--query QUERY) [--year YEAR] --format FORMAT... --json"
    )
    assert failed["properties"]["issue"]["properties"]["code"]["enum"] == [
        "book.download_failed",
        "book.candidate_search_unavailable",
    ]
    assert request["resource_bounds"] == {"accept_budget": 1}
    assert request["capabilities"][1] == (
        "quasi-download book fetch --md5 MD5 --slug SLUG --format FORMAT "
        "[--temp-dir DIR] --json"
    )
    assert any(
        "normalize" in capability and "same temporary directory" in capability
        for capability in request["capabilities"]
    )


def test_paper_acquire_allows_agent_owned_discovery_and_temp_normalization():
    prepared = _prepare("paper.acquire")
    request = _prompt_request(prepared["prompt"])

    assert any(
        capability.startswith("quasi-search kagi ")
        for capability in request["capabilities"]
    )
    assert any(
        "normalize" in capability and "same temporary directory" in capability
        for capability in request["capabilities"]
    )


def test_book_acquire_year_mismatch_is_incoherent_complete():
    identity = _search_identity("book", slug="exact-book")
    report = _dispatch(
        {
            "invocation": _invocation(
                "book.acquire",
                context=_context(meta=identity),
            ),
            "model_output": _book_acquire_output(
                _book_year_evidence("MISMATCH")
            ),
        }
    )

    assert report["agentCalls"] == 1
    assert report["result"]["kind"] == "incoherent_complete"


@pytest.mark.parametrize(
    ("write_state", "expected_kind"),
    [
        ("not_written", "receipt"),
        ("unknown", "incoherent_complete"),
    ],
)
def test_book_acquire_write_state_controls_effect_completion(
    write_state: str,
    expected_kind: str,
) -> None:
    report = _dispatch(
        {
            "invocation": _invocation("book.acquire"),
            "model_output": _book_acquire_output(
                _book_year_evidence("MATCH"),
                write_state=write_state,
                source="existing_file",
            ),
        }
    )

    assert report["result"]["kind"] == expected_kind


def test_book_acquire_accept_current_keeps_exact_identity_and_prior_evidence():
    decision = _book_year_decision("accept-current")
    invocation = _invocation(
        "book.acquire",
        context=_context(
            meta=deepcopy(decision["current_identity"]),
            yearDecision=deepcopy(decision),
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
    assert rejected_identity["thrown"]["name"] == "InputContractError"
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
            yearDecision=deepcopy(decision),
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


def test_audit_receipt_paths_reject_absolute_or_non_target_paths() -> None:
    book_schema = _prepare("book.audit")["options"]["schema"]
    assert (
        book_schema["properties"]["escalated"]["items"]["properties"]["path"]
        ["pattern"]
        == "^[^/]"
    )
    assert (
        book_schema["properties"]["mutated_paths"]["items"]["pattern"]
        == "^[^/]"
    )

    for operation in ("paper.audit", "talk.audit"):
        prepared = _prepare(operation)
        target = json.loads(prepared["prompt"])["target"]["path"]
        schema = prepared["options"]["schema"]
        assert (
            schema["properties"]["escalated"]["items"]["properties"]["path"]
            ["const"]
            == target
        )
        assert (
            schema["properties"]["mutated_paths"]["items"]["const"]
            == target
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
        context=_context(identityDecision=decision),
    )

    accepted = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "paper",
                identity_slug="selected-paper",
                owner_slug=None,
            ),
        }
    )
    changed = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "paper",
                identity_slug="different-paper",
                owner_slug=None,
            ),
        }
    )

    assert accepted["result"]["kind"] == "receipt"
    assert changed["result"]["kind"] == "incoherent_complete"


def test_book_year_search_requires_the_recommended_year_then_uses_owner_proof():
    decision = _book_year_decision("use-recommended-year")
    invocation = _invocation(
        "material.search",
        kind="book",
        slug="existing-vault-owner",
        context=_context(yearDecision=decision),
    )
    old_year = _dispatch(
        {
            "invocation": invocation,
            "model_output": _search_output(
                "book",
                identity_slug="metadata-book-2024",
                owner_slug=None,
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
                owner_slug="existing-vault-owner",
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
                context=_context(identityDecision=decision),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"


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
                context=_context(identityDecision=decision),
            ),
            "model_output": None,
        }
    )

    assert report["agentCalls"] == 0
    assert report["thrown"]["name"] == "InputContractError"


def test_pdf_book_structure_gate_uses_direct_manual_split_specs() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
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


def test_book_prepare_artifact_schema_requires_project_relative_paths() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
        ),
    )
    path_schema = prepared["options"]["schema"]["properties"]["artifacts"][
        "items"
    ]["properties"]["path"]

    assert path_schema["minLength"] == 1
    assert re.search(
        path_schema["pattern"],
        "processing/chapters/exact-material/01-opening.txt",
    )
    assert not re.search(
        path_schema["pattern"],
        "/Users/example/vault/processing/chapters/exact-material/01-opening.txt",
    )


def test_book_prepare_split_capabilities_bind_exact_pdf_inputs() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
        ),
    )
    request = _prompt_request(prepared["prompt"])
    split = [
        capability
        for capability in request["capabilities"]
        if capability.startswith("quasi-extract split ")
    ]
    source_prefix = "quasi-extract split 'sources/exact-material.pdf' "
    assert split
    assert any(capability.startswith(source_prefix) for capability in split)
    assert all(capability.startswith(source_prefix) for capability in split)
    assert all("source.txt" not in capability for capability in split)
    assert all("ocr.txt" not in capability for capability in split)


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "unusable_normalized",
        "usable_normalized",
        "unknown_usability",
        "wrong_role",
        "wrong_path",
        "extra_manifest",
        "written_chapters",
        "committed_generation",
        "epub",
    ],
)
def test_book_prepare_ocr_required_accepts_only_exact_unusable_normalized_evidence(
    case: str,
) -> None:
    chapter_root = "processing/chapters/exact-material"
    context = _context(
        format="pdf",
        source="sources/exact-material.pdf",
        input="sources/exact-material.pdf",
    )
    evidence = {
        "role": "normalized_document",
        "path": f"{chapter_root}/source.txt",
        "exists": True,
        "usable": False,
    }
    manifest = {
        "role": "chapter_manifest",
        "path": f"{chapter_root}/manifest.json",
        "exists": True,
        "usable": False,
    }
    output = _book_prepare_output(artifacts=[evidence])
    if case == "empty":
        output["artifacts"] = []
    elif case == "usable_normalized":
        evidence["usable"] = True
    elif case == "unknown_usability":
        evidence["usable"] = None
    elif case == "wrong_role":
        evidence["role"] = "recovery_source"
    elif case == "wrong_path":
        evidence["path"] = f"{chapter_root}/ocr.txt"
    elif case == "extra_manifest":
        output["artifacts"].append(manifest)
    elif case == "written_chapters":
        chapters = [
            {
                "slot": "01",
                "title": "X",
                "filename": "01-x.txt",
                "slug": "x",
                "word_count": 10,
                "start_page": 1,
                "end_page": 5,
            },
            {
                "slot": "02",
                "title": "Y",
                "filename": "02-y.txt",
                "slug": "y",
                "word_count": 10,
                "start_page": 6,
                "end_page": 9,
            },
        ]
        output.update(
            selected_source="sources/exact-material.pdf",
            normalized_path=f"{chapter_root}/source.txt",
            manifest_fingerprint="a" * 64,
            mode="manual",
            disposition="replaced",
            chapter_count=2,
            chapters=chapters,
            artifacts=[
                evidence,
                manifest,
                *[
                    {
                        "role": "normalized_chapter",
                        "path": f"{chapter_root}/{chapter['filename']}",
                        "exists": True,
                        "usable": False,
                    }
                    for chapter in chapters
                ],
            ],
        )
    elif case == "committed_generation":
        context["input"] = f"{chapter_root}/ocr-generations/{'b' * 64}/ocr.pdf"
    elif case == "epub":
        context.update(
            format="epub",
            source="sources/exact-material.epub",
            input="sources/exact-material.epub",
        )
        output["format"] = "epub"

    report = _dispatch(
        {
            "invocation": _invocation("book.prepare", context=context),
            "model_output": output,
        }
    )

    expected = (
        "receipt"
        if case in {"empty", "unusable_normalized"}
        else "incoherent_complete"
    )
    assert report["result"]["kind"] == expected


def test_book_prepare_envelope_states_the_ocr_required_stop_rule() -> None:
    pdf = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
        ),
    )
    contract = _prompt_request(pdf["prompt"])["disposition_contract"]

    assert set(contract) == {"prepared", "ocr_required"}
    assert "usable:false" in contract["ocr_required"]

    epub = _prepare(
        "book.prepare",
        context=_context(
            format="epub",
            source="sources/exact-material.epub",
            input="sources/exact-material.epub",
        ),
    )
    assert set(_prompt_request(epub["prompt"])["disposition_contract"]) == {
        "prepared"
    }

    legacy = {
        "path": "processing/chapters/exact-material/ocr.progress.json",
        "present": True,
        "usable": True,
        "source_sha256": "a" * 64,
        "total_pages": 100,
        "completed_pages": 16,
        "next_page": 17,
    }
    legacy_pdf = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
            legacyOcr=legacy,
        ),
    )
    assert set(_prompt_request(legacy_pdf["prompt"])["disposition_contract"]) == {
        "prepared"
    }


def test_book_prepare_exposes_fixed_ocr_only_for_released_legacy_progress() -> None:
    legacy = {
        "path": "processing/chapters/exact-material/ocr.progress.json",
        "present": True,
        "usable": True,
        "source_sha256": "a" * 64,
        "total_pages": 100,
        "completed_pages": 16,
        "next_page": 17,
    }
    prepared = _prepare(
        "book.prepare",
        context=_context(
            format="pdf",
            source="sources/exact-material.pdf",
            input="sources/exact-material.pdf",
            legacyOcr=legacy,
        ),
    )
    request = _prompt_request(prepared["prompt"])

    assert request["refs"]["legacy_ocr_progress"] == (
        "processing/chapters/exact-material/ocr.progress.json"
    )
    assert (
        "quasi-extract ocr 'sources/exact-material.pdf' "
        "'processing/chapters/exact-material/ocr.pdf' --resume --progress-file "
        "'processing/chapters/exact-material/ocr.progress.json' --chunk-pages 8 "
        "--no-clobber --json"
    ) in request["capabilities"]


def test_book_ocr_uses_the_same_generation_contract_with_book_paths() -> None:
    generation = _book_ocr_generation()
    prepared = _prepare(
        "book.ocr",
        context=_context(ocrGeneration=generation),
    )
    request = _prompt_request(prepared["prompt"])

    assert request["generation"]["profile"]["chunk_pages"] == 16
    assert request["refs"]["lock"] == (
        "processing/chapters/exact-material/.ocr-generation.lock"
    )
    assert request["capabilities"][0].startswith(
        "quasi-extract ocr-generation --kind book "
    )


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


@pytest.mark.parametrize("prepared", [False, True])
def test_talk_prepare_requires_requested_prepared_media_artifact(prepared):
    artifacts = [{"role": "transcript", "path": "vault/talks/exact-talk/transcript.md", "sha256": "a" * 64, "size": 100}]
    artifacts.append({"role": "engine_transcript", "path": "processing/talks/exact-talk/transcript.soniox.srt", "sha256": "b" * 64, "size": 80})
    if prepared:
        artifacts.append({"role": "prepared_media", "path": "vault/talks/exact-talk/recording.mp4", "sha256": "9" * 64, "size": 500})
    report = _dispatch_talk_prepare_artifacts(artifacts, meta={"media": "sources/exact-talk.mp4", "prepareMedia": True})
    assert report["result"]["kind"] == ("receipt" if prepared else "incoherent_complete")


def test_webpage_identify_request_has_one_direct_inspect_bound_resolver() -> None:
    from test_webpage_plan import identify_complete, provisional_webpage_input
    report = run_generated_workflow("webpage", provisional_webpage_input(), [identify_complete()], capture_agent_requests=True)
    assert report["agentCalls"] == 1
    assert report["value"]["terminal"] == "needs_observation"
    request = _prompt_request(report["agentRequests"][0]["prompt"])
    source_request = _prompt_request(_prepare("webpage.identify")["prompt"])
    assert request["capabilities"] == source_request["capabilities"]
    assert request["identify_contract"] == source_request["identify_contract"]
    assert request["capabilities"] == [
        "quasi-webpage inspect --url URL --json",
        "quasi-helpers vault resolve --items-json JSON",
    ]
    contract = request["identify_contract"]
    assert contract["command_form"] == "bare_direct_literal"
    assert contract["inspect"] == {"calls": 1, "require_status": "complete"}
    resolver = contract["resolver"]
    assert resolver["calls"] == resolver["array_length"] == 1
    assert resolver["after"] == "inspect.complete"
    assert resolver["argument"] == "--items-json"
    assert resolver["encoding"] == "literal_json_array"
    assert resolver["additional_item_fields"] is False
    assert resolver["repeat_or_repair"] is False
    assert set(resolver["item"]) == {"kind", "slug", "url", "title", "site"}
    assert resolver["item"]["kind"] == {"const": "webpage"}
    for key, field in (("url", "final_url"), ("title", "title"), ("site", "site")):
        assert resolver["item"][key] == {"source": f"inspect.{field}"}
    slug = resolver["item"]["slug"]
    assert slug["source"] == "candidate_slug"
    assert slug["derived_from"] == ["inspect.final_url", "inspect.title", "inspect.site"]
    assert slug["pattern"] == _prepare("webpage.identify")["options"]["schema"]["properties"]["identity"]["properties"]["slug"]["pattern"]
    assert set(contract["forbidden_command_forms"]) == {
        "printf", "pipe", "stdin", "shell_variable", "command_substitution",
    }
