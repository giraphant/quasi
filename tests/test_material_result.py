from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from workflow_test_support import run_workflow_export


INPUT_MODULE = "scripts/workflows/shared/material-input.mts"
RESULT_MODULE = "scripts/workflows/shared/material-result.mts"
PAPER_CONTRACT_MODULE = "scripts/workflows/contracts/paper.mts"
SEARCH_CONTRACT_MODULE = "scripts/workflows/contracts/search.mts"
BOOK_CONTRACT_MODULE = "scripts/workflows/contracts/book.mts"
TALK_CONTRACT_MODULE = "scripts/workflows/contracts/talk.mts"
TRANSLATION_CONTRACT_MODULE = "scripts/workflows/contracts/translation.mts"
AUTHOR_CONTRACT_MODULE = "scripts/workflows/contracts/author.mts"
WEBPAGE_CONTRACT_MODULE = "scripts/workflows/contracts/webpage.mts"

PAPER_IDENTITY = {
    "slug": "exact-paper",
    "title": "Exact Paper",
    "authors": ["Ada Example"],
    "year": 2024,
    "doi": "10.1000/exact",
    "oa_url": "https://example.test/exact.pdf",
    "url": "https://example.test/exact",
    "journal": "Exact Joins",
    "confidence": "high",
}

BOOK_IDENTITY = {
    "slug": "exact-book",
    "title": "Exact Book",
    "authors": ["Ada Example"],
    "year": 2024,
    "isbn": "9780000000000",
    "publisher": "Exact Press",
    "category": "monograph",
    "confidence": "high",
}

WEBPAGE_IDENTITY = {
    "slug": "example-org-page",
    "title": "Example page",
    "url": "https://example.org/page",
    "site": "Example",
}


def webpage_observation(
    *,
    slug: str = "example-org-page",
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "webpage",
        "slug": slug,
        "identity": deepcopy(identity),
        "facts": {
            "kind": "webpage",
            "snapshot": {
                "path": f"vault/webpages/{slug}/snapshot.webarchive",
                "present": identity is not None,
                "usable": identity is not None,
            },
            "prepared": {
                "path": f"processing/webpages/{slug}/source.md",
                "present": False,
                "usable": False,
            },
            "canonical": {
                "path": f"vault/webpages/{slug}/webpage.md",
                "present": False,
                "usable": False,
            },
            "captured_at": (
                "2026-08-13T12:34:56Z" if identity is not None else None
            ),
        },
    }

PAPER_OBSERVATION = {
    "schema_version": "quasi.status/0.2",
    "kind": "paper",
    "slug": "exact-paper",
    "identity": None,
    "facts": {
        "kind": "paper",
        "sources": [
            {
                "format": "pdf",
                "artifact": {
                    "path": "sources/exact-paper.pdf",
                    "present": False,
                    "usable": False,
                },
                "candidate": None,
            },
            {
                "format": "txt",
                "artifact": {
                    "path": "sources/exact-paper.txt",
                    "present": False,
                    "usable": False,
                },
                "candidate": None,
            },
        ],
        "source_candidates_fingerprint": "0" * 64,
        "prepared": [
            {
                "path": "processing/papers/exact-paper/source.txt",
                "present": False,
                "usable": False,
            },
            {
                "path": "processing/papers/exact-paper/ocr.txt",
                "present": False,
                "usable": False,
            },
        ],
        "legacy_recovery": {
            "pdf": {
                "path": "processing/papers/exact-paper/ocr.pdf",
                "present": False,
                "usable": False,
            },
            "text": {
                "path": "processing/papers/exact-paper/ocr.txt",
                "present": False,
                "usable": False,
            },
        },
        "ocr_generation": None,
        "canonical": {
            "path": "vault/papers/exact-paper.md",
            "present": False,
            "usable": False,
        },
    },
}


def paper_observation_for_slug(slug: str) -> dict[str, Any]:
    value = deepcopy(PAPER_OBSERVATION)
    value["slug"] = slug
    value["facts"]["sources"][0]["artifact"]["path"] = f"sources/{slug}.pdf"
    value["facts"]["sources"][1]["artifact"]["path"] = f"sources/{slug}.txt"
    value["facts"]["prepared"][0]["path"] = (
        f"processing/papers/{slug}/source.txt"
    )
    value["facts"]["prepared"][1]["path"] = (
        f"processing/papers/{slug}/ocr.txt"
    )
    value["facts"]["legacy_recovery"]["pdf"]["path"] = (
        f"processing/papers/{slug}/ocr.pdf"
    )
    value["facts"]["legacy_recovery"]["text"]["path"] = (
        f"processing/papers/{slug}/ocr.txt"
    )
    value["facts"]["canonical"]["path"] = f"vault/papers/{slug}.md"
    return value


BOOK_OBSERVATION = {
    "schema_version": "quasi.status/0.2",
    "kind": "book",
    "slug": "request-book-1",
    "identity": None,
    "facts": {
        "kind": "book",
        "sources": [
            {
                "format": "epub",
                "artifact": {
                    "path": "sources/request-book-1.epub",
                    "present": False,
                    "usable": False,
                },
            },
            {
                "format": "pdf",
                "artifact": {
                    "path": "sources/request-book-1.pdf",
                    "present": False,
                    "usable": False,
                },
            },
        ],
        "manifest": {
            "path": "processing/chapters/request-book-1/manifest.json",
            "present": False,
            "usable": False,
            "valid": False,
        },
        "ocr_generation": None,
        "legacy_ocr": {
            "path": "processing/chapters/request-book-1/ocr.progress.json",
            "present": False,
            "usable": False,
            "source_sha256": None,
            "total_pages": None,
            "completed_pages": None,
            "next_page": None,
        },
        "chapters": [],
        "overview": {
            "path": "vault/books/request-book-1/00-overview.md",
            "present": False,
            "usable": False,
        },
    },
}


def test_book_status_parser_matches_only_the_status_producer_projection():
    producer_value = deepcopy(BOOK_OBSERVATION)
    producer_value["facts"]["manifest"] = {
        **producer_value["facts"]["manifest"],
        "present": True,
        "usable": True,
        "valid": True,
    }
    producer_value["facts"]["chapters"] = [
        {
            "slot": "01",
            "title": "Opening",
            "filename": "01_Opening.txt",
            "slug": "opening",
            "word_count": 20,
            "start_page": None,
            "end_page": None,
            "input": {
                "path": "processing/chapters/request-book-1/01_Opening.txt",
                "present": True,
                "usable": True,
            },
            "output": {
                "path": "vault/books/request-book-1/ch01-opening.md",
                "present": False,
                "usable": False,
            },
        }
    ]
    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStatusObservation",
        producer_value,
    ) == producer_value

    foreign_value = deepcopy(producer_value)
    foreign_value["facts"]["sources"] = [
        {
            "format": "pdf",
            "artifact": {
                "path": "sources/elsewhere.pdf",
                "present": True,
                "usable": True,
            },
        },
        deepcopy(producer_value["facts"]["sources"][1]),
    ]
    foreign_value["facts"]["manifest"] = {
        **foreign_value["facts"]["manifest"],
        "path": "processing/chapters/elsewhere/manifest.json",
        "valid": True,
        "present": True,
        "usable": True,
    }
    foreign_value["facts"]["chapters"] = [
        {
            "slot": "01",
            "title": "Opening",
            "filename": "01_Opening.txt",
            "slug": "opening",
            "word_count": 20,
            "start_page": None,
            "end_page": None,
            "input": {
                "path": "processing/chapters/elsewhere/01_Opening.txt",
                "present": True,
                "usable": True,
            },
            "output": {
                "path": "vault/books/elsewhere/ch01-opening.md",
                "present": False,
                "usable": False,
            },
        },
        {
            "slot": "01",
            "title": "Duplicate",
            "filename": "01_Duplicate.txt",
            "slug": "opening",
            "word_count": 10,
            "start_page": None,
            "end_page": None,
            "input": {
                "path": "processing/chapters/elsewhere/01_Duplicate.txt",
                "present": True,
                "usable": True,
            },
            "output": {
                "path": "vault/books/elsewhere/ch01-opening.md",
                "present": False,
                "usable": False,
            },
        },
    ]
    foreign_value["facts"]["overview"]["path"] = (
        "vault/books/elsewhere/overview.md"
    )

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStatusObservation",
        foreign_value,
    ) is None


def test_paper_status_parser_binds_the_status_producer_paths() -> None:
    producer_value = deepcopy(PAPER_OBSERVATION)

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        producer_value,
    ) == producer_value

    foreign_value = deepcopy(producer_value)
    foreign_value["facts"]["prepared"][0]["path"] = (
        "processing/papers/another-paper/source.txt"
    )

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        foreign_value,
    ) is None


def missing_paper_ocr_generation() -> dict[str, Any]:
    profile = {
        "schema_version": "quasi.ocr.profile/0.2",
        "language": "chi_sim+eng",
        "text_extractor": "pymupdf",
        "engine_order": ["mineru"],
        "chunk_pages": 16,
        "name": "mineru-text",
        "model": "opendatalab/MinerU2.5-Pro-2605-1.2B",
        "engine_revision": "mineru25-pro-2605-text/1",
        "validation_policy": "paper-text-v1",
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    request = {
        "schema_version": "quasi.ocr.generation.request/0.1",
        "material_key": "paper:exact-paper",
        "source_path": "sources/exact-paper.pdf",
        "source_sha256": "a" * 64,
        "profile": profile,
    }
    generation = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    paper_root = "processing/papers/exact-paper"
    work_root = f"{paper_root}/.ocr-work/{generation}"
    generation_root = f"{paper_root}/ocr-generations/{generation}"
    return {
        "state": "missing",
        "material_key": "paper:exact-paper",
        "kind": "paper",
        "slug": "exact-paper",
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": config_fingerprint,
        "source": {
            "path": "sources/exact-paper.pdf",
            "sha256": "a" * 64,
            "size": 123,
            "pages": 40,
        },
        "paths": {
            "lock": f"{paper_root}/.ocr-generation.lock",
            "work_dir": work_root,
            "progress": f"{work_root}/ocr.progress.json",
            "generation_dir": generation_root,
            "manifest": f"{generation_root}/manifest.json",
            "pdf": f"{generation_root}/ocr.pdf",
            "text": f"{generation_root}/ocr.txt",
        },
        "progress": None,
        "manifest": {
            "path": f"{generation_root}/manifest.json",
            "exists": False,
            "regular": None,
            "sha256": None,
            "size": 0,
        },
        "recovery_pdf": {
            "path": f"{generation_root}/ocr.pdf",
            "exists": False,
            "regular": None,
            "sha256": None,
            "size": 0,
            "pages": 0,
        },
        "normalized_text": {
            "path": f"{generation_root}/ocr.txt",
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


def usable_paper_source_observation() -> dict[str, Any]:
    value = deepcopy(PAPER_OBSERVATION)
    value["facts"]["sources"][0] = {
        "format": "pdf",
        "artifact": {
            "path": "sources/exact-paper.pdf",
            "present": True,
            "usable": True,
        },
        "candidate": {
            "format": "pdf",
            "path": "sources/exact-paper.pdf",
            "sha256": "a" * 64,
            "size": 123,
        },
    }
    value["facts"]["source_candidates_fingerprint"] = "f" * 64
    value["facts"]["ocr_generation"] = missing_paper_ocr_generation()
    return value


def test_paper_status_parser_binds_usable_source_candidate_evidence() -> None:
    value = usable_paper_source_observation()

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        value,
    ) == value


@pytest.mark.parametrize(
    "state",
    ["missing", "in_progress", "committed", "invalid", "unknown"],
)
def test_paper_status_parser_accepts_each_closed_ocr_generation_state(
    state: str,
) -> None:
    value = usable_paper_source_observation()
    generation = value["facts"]["ocr_generation"]
    if state == "in_progress":
        generation.update(
            {
                    "state": state,
                    "progress": {
                        "completed_pages": 16,
                        "total_pages": 40,
                        "next_page": 17,
                        "ranges": [
                            {
                                "start_page": 1,
                                "end_page": 16,
                                "engine": "mineru",
                                "path": (
                                    f"{generation['paths']['work_dir']}/parts/"
                                    "part-000001-000016.mineru.pdf"
                                ),
                                "sha256": "f" * 64,
                                "pages": 16,
                            }
                        ],
                },
            }
        )
    elif state == "committed":
        generation["state"] = state
        generation["manifest"].update(
            {"exists": True, "regular": True, "sha256": "b" * 64, "size": 100}
        )
        generation["recovery_pdf"].update(
            {
                "exists": True,
                "regular": True,
                "sha256": "c" * 64,
                "size": 200,
                    "pages": 40,
            }
        )
        generation["normalized_text"].update(
            {
                "exists": True,
                "regular": True,
                "sha256": "d" * 64,
                "size": 300,
                "utf8": True,
                "chars": 240,
                "non_whitespace_chars": 180,
            }
        )
    elif state == "invalid":
        generation.update(
            {"state": state, "failure": "paper.ocr_pdf_invalid"}
        )
        generation["source"]["pages"] = 0
    elif state == "unknown":
        generation.update(
            {"state": state, "failure": "paper.ocr_uncommitted_generation"}
        )

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        value,
    ) == value


def test_paper_status_parser_rejects_noncanonical_ocr_range_slot() -> None:
    value = usable_paper_source_observation()
    generation = value["facts"]["ocr_generation"]
    generation.update(
        {
            "state": "in_progress",
            "progress": {
                "completed_pages": 16,
                "total_pages": 40,
                "next_page": 17,
                "ranges": [
                    {
                        "start_page": 1,
                        "end_page": 16,
                        "engine": "mineru",
                        "path": f"{generation['paths']['work_dir']}/parts/foreign.pdf",
                        "sha256": "f" * 64,
                        "pages": 16,
                    }
                ],
            },
        }
    )

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        value,
    ) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["facts"]["ocr_generation"].update(
            {"generation_key": "b" * 64}
        ),
        lambda value: value["facts"]["ocr_generation"]["source"].update(
            {"sha256": "b" * 64}
        ),
        lambda value: value["facts"]["ocr_generation"]["paths"].update(
            {"text": "processing/papers/exact-paper/ocr.txt"}
        ),
        lambda value: value["facts"]["ocr_generation"].update(
            {
                "state": "in_progress",
                "progress": {
                    "completed_pages": 8,
                    "total_pages": 10,
                    "next_page": 10,
                },
            }
        ),
        lambda value: value["facts"]["ocr_generation"].update(
            {"state": "committed"}
        ),
    ],
)
def test_paper_status_parser_rejects_unbound_ocr_generation(mutate) -> None:
    value = usable_paper_source_observation()
    mutate(value)

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        value,
    ) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["facts"]["sources"][0]["candidate"].update(
            {"format": "txt"}
        ),
        lambda value: value["facts"]["sources"][0]["candidate"].update(
            {"path": "sources/other-paper.pdf"}
        ),
        lambda value: value["facts"]["sources"][0]["candidate"].update(
            {"sha256": "not-a-digest"}
        ),
        lambda value: value["facts"]["sources"][0].update(
            {"candidate": None}
        ),
        lambda value: value["facts"].update(
            {"source_candidates_fingerprint": "not-a-digest"}
        ),
    ],
)
def test_paper_status_parser_rejects_unbound_source_candidate_evidence(mutate):
    value = usable_paper_source_observation()
    mutate(value)

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperStatusObservation",
        value,
    ) is None


def test_author_contract_rejects_a_foreign_canonical_path() -> None:
    observation = {
        "schema_version": "quasi.status/0.2",
        "kind": "author",
        "slug": "ada-example",
        "identity": None,
        "facts": {
            "kind": "author",
            "canonical": {
                "path": "vault/authors/another-author.md",
                "present": False,
                "usable": False,
            },
        },
    }

    result = run_workflow_export(
        AUTHOR_CONTRACT_MODULE,
        "parseAuthorRunInput",
        {
            "seed": {
                "slug": "ada-example",
                "full_name": "Ada Example",
                "topic": "exact systems",
            },
            "observation": observation,
            "options": {},
        },
    )

    assert result["ok"] is False
    assert result["result"]["issue"]["code"] == "material.invalid_input"


def translation_observation(target_language: str) -> dict[str, Any]:
    target = target_language.lower()
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "translation",
        "slug": "exact-paper",
        "identity": None,
        "facts": {
            "kind": "translation",
            "target_language": target_language,
            "source": {
                "path": "sources/exact-paper.pdf",
                "present": True,
                "usable": True,
            },
            "output": {
                "path": f"processing/translations/exact-paper-{target}.pdf",
                "present": False,
                "usable": False,
            },
            "manifest": {
                "path": (
                    f"processing/translations/exact-paper-{target}.manifest.json"
                ),
                "present": False,
                "usable": False,
            },
        },
    }


def test_artifact_observation_never_marks_an_absent_path_usable():
    assert run_workflow_export(
        INPUT_MODULE,
        "isArtifactObservation",
        {"path": "sources/missing.pdf", "present": False, "usable": True},
    ) is False


def test_talk_status_parser_matches_the_exact_status_producer_projection():
    slug = "exact-talk"
    extensions = (
        "mov", "mp4", "m4v", "mkv", "webm", "m4a", "wav", "mp3",
        "aac", "flac", "aiff", "aif", "ogg", "opus",
    )
    producer_value = {
        "schema_version": "quasi.status/0.2",
        "kind": "talk",
        "slug": slug,
        "identity": None,
        "facts": {
            "kind": "talk",
            "media": [
                {
                    "path": f"sources/{slug}.{extension}",
                    "present": extension == "mp3",
                    "usable": extension == "mp3",
                }
                for extension in extensions
            ],
            "prepared": {"path": f"vault/talks/{slug}/recording.mp4", "present": False, "usable": False},
            "transcripts": [
                {
                    "path": f"processing/talks/{slug}/transcript.apple.srt",
                    "present": True,
                    "usable": True,
                },
                {
                    "path": f"processing/talks/{slug}/transcript.soniox.srt",
                    "present": True,
                    "usable": True,
                },
            ],
            "canonical": {
                "path": f"vault/talks/{slug}/talk.md",
                "present": False,
                "usable": False,
            },
        },
    }

    assert run_workflow_export(
        TALK_CONTRACT_MODULE,
        "parseTalkStatusObservation",
        producer_value,
    ) == producer_value

    foreign = deepcopy(producer_value)
    foreign["facts"]["media"][7]["path"] = "sources/another-talk.mp3"
    foreign["facts"]["transcripts"].append(
        deepcopy(foreign["facts"]["transcripts"][0])
    )
    foreign["facts"]["canonical"]["path"] = "vault/talks/elsewhere/talk.md"
    assert run_workflow_export(
        TALK_CONTRACT_MODULE,
        "parseTalkStatusObservation",
        foreign,
    ) is None

    foreign_prepared = deepcopy(producer_value)
    foreign_prepared["facts"]["prepared"]["path"] = "vault/talks/elsewhere/recording.mp4"
    assert run_workflow_export(TALK_CONTRACT_MODULE, "parseTalkStatusObservation", foreign_prepared) is None


def test_translation_status_parser_binds_null_identity_and_exact_target_paths():
    producer_value = translation_observation("zh")
    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationStatusObservation",
        producer_value,
    ) == producer_value

    foreign = deepcopy(producer_value)
    foreign["identity"] = {"title": "A source paper"}
    foreign["facts"]["source"]["path"] = "sources/another-paper.pdf"
    foreign["facts"]["output"]["path"] = (
        "processing/translations/exact-paper-fr-fr.pdf"
    )
    foreign["facts"]["manifest"]["path"] = (
        "processing/translations/exact-paper-fr-fr.manifest.json"
    )
    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationStatusObservation",
        foreign,
    ) is None


def valid_input() -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": "exact-paper",
            "identity": deepcopy(PAPER_IDENTITY),
        },
        "observation": deepcopy(PAPER_OBSERVATION),
        "options": {},
    }


def parse_paper(value: Any) -> dict[str, Any]:
    return run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperRunInput",
        value,
    )


def parse_book(value: Any) -> dict[str, Any]:
    return run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookRunInput",
        value,
    )


def assert_parsed_seed(
    value: dict[str, Any],
    kind: str,
    observation_key: str,
) -> None:
    module = PAPER_CONTRACT_MODULE if kind == "paper" else BOOK_CONTRACT_MODULE
    parser = "parsePaperRunInput" if kind == "paper" else "parseBookRunInput"
    result = run_workflow_export(module, parser, value)
    assert result == {
        "ok": True,
        "value": {
            "seed": value["seed"],
            "observations": {
                "__map_entries__": [[observation_key, value["observation"]]]
            },
            "options": value["options"],
            "userDecision": None,
        },
    }


def assert_invalid_input(
    result: dict[str, Any],
    requested_slug: str | None,
    kind: str = "paper",
) -> None:
    assert result == {
        "ok": False,
        "result": {
            "schema_version": "quasi.material.result/0.1",
            "material": {
                "requested": {"kind": kind, "slug": requested_slug},
                "canonical": None,
            },
            "terminal": "blocked",
            "issue": {
                "code": "material.invalid_input",
                "operation": None,
                "summary": "Material Workflow input is invalid.",
                "retryable": False,
                "observation_request": None,
            },
        },
    }


def parse_webpage(value: Any) -> dict[str, Any]:
    return run_workflow_export(
        WEBPAGE_CONTRACT_MODULE,
        "parseWebpageRunInput",
        value,
    )


def test_webpage_provisional_input_is_the_exact_readonly_intake_shape() -> None:
    value = {
        "seed": {"state": "provisional", "url": "https://example.org/page"},
        "observation": None,
        "options": {},
    }

    assert parse_webpage(value) == {
        "ok": True,
        "value": {
            "mode": "identify",
            "seed": value["seed"],
            "options": {},
        },
    }

    with_writer_observation = deepcopy(value)
    with_writer_observation["observation"] = webpage_observation()
    assert parse_webpage(with_writer_observation)["ok"] is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/page",
        "https://user:secret@example.org/page",
        "https://@example.org/page",
        "https://example.org/page\nnext",
    ],
)
def test_webpage_provisional_input_rejects_non_public_http_url(url: str) -> None:
    result = parse_webpage(
        {
            "seed": {"state": "provisional", "url": url},
            "observation": None,
            "options": {},
        }
    )

    assert result["ok"] is False


def test_webpage_url_normalizer_is_shared_by_material_redirects() -> None:
    assert run_workflow_export(
        WEBPAGE_CONTRACT_MODULE,
        "normalizeWebUrl",
        "HTTPS://EXAMPLE.ORG:443/essay#section",
    ) == "https://example.org/essay"
    assert run_workflow_export(
        WEBPAGE_CONTRACT_MODULE,
        "normalizeWebUrl",
        "file:///tmp/essay",
    ) is None


def test_webpage_canonical_input_adopts_same_url_observed_metadata() -> None:
    observed_identity = {
        **WEBPAGE_IDENTITY,
        "title": "Title from capture",
        "url": "HTTPS://EXAMPLE.ORG:443/page#fragment",
        "site": "Captured site",
    }
    value = {
        "seed": {
            "state": "canonical",
            "material_slug": "example-org-page",
            "identity": deepcopy(WEBPAGE_IDENTITY),
        },
        "observation": webpage_observation(identity=observed_identity),
        "options": {},
    }

    parsed = parse_webpage(value)

    assert parsed["ok"] is True
    assert parsed["value"]["mode"] == "process"
    assert parsed["value"]["effectiveIdentity"] == {
        **WEBPAGE_IDENTITY,
        "title": "Title from capture",
        "site": "Captured site",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["observation"].update({"slug": "other-page"}),
        lambda value: value["observation"]["identity"].update(
            {"slug": "other-page"}
        ),
        lambda value: value["observation"]["identity"].update(
            {"url": "https://example.org/other"}
        ),
        lambda value: value["observation"]["facts"]["prepared"].update(
            {"path": "processing/webpages/other-page/source.md"}
        ),
        lambda value: value["observation"]["facts"].update(
            {"captured_at": "2026-08-13T12:34:56.123Z"}
        ),
        lambda value: value["options"].update({"cursor": "hidden-state"}),
    ],
)
def test_webpage_canonical_input_rejects_non_owner_status(mutate) -> None:
    value = {
        "seed": {
            "state": "canonical",
            "material_slug": "example-org-page",
            "identity": deepcopy(WEBPAGE_IDENTITY),
        },
        "observation": webpage_observation(identity=WEBPAGE_IDENTITY),
        "options": {},
    }
    mutate(value)

    assert parse_webpage(value)["ok"] is False


def test_webpage_route_key_and_resume_seed_remain_leaf_only() -> None:
    route = {"kind": "webpage", "slug": "example-org-page"}
    assert run_workflow_export(INPUT_MODULE, "parseObservationRoute", route) == route
    assert run_workflow_export(INPUT_MODULE, "observationKey", route) == (
        "webpage:example-org-page"
    )

    seed = {
        "material": {
            "requested": {"kind": "webpage", "slug": None},
            "canonical": {"kind": "webpage", "slug": "example-org-page"},
        }
    }
    resume_seed = {
        "route": route,
        "seed": {
            "state": "canonical",
            "material_slug": "example-org-page",
            "identity": deepcopy(WEBPAGE_IDENTITY),
        },
        "options": {},
    }

    result = run_workflow_export(
        RESULT_MODULE,
        "needsObservationMaterialResult",
        seed,
        [route],
        resume_seed,
    )
    assert result["resume_seed"] == resume_seed
    assert "gate" not in result


def test_webpage_complete_result_carries_all_three_exact_artifact_roles() -> None:
    artifacts = [
        {
            "role": "snapshot",
            "path": "vault/webpages/example-org-page/snapshot.webarchive",
        },
        {
            "role": "normalized_text",
            "path": "processing/webpages/example-org-page/source.md",
        },
        {
            "role": "canonical",
            "path": "vault/webpages/example-org-page/webpage.md",
        },
    ]
    result = run_workflow_export(
        RESULT_MODULE,
        "completeMaterialResult",
        {
            "material": {
                "requested": {"kind": "webpage", "slug": None},
                "canonical": {"kind": "webpage", "slug": "example-org-page"},
            }
        },
        artifacts,
        None,
    )

    assert result["artifacts"] == artifacts


@pytest.mark.parametrize("value", [None, [], "paper", 42])
def test_non_object_input_blocks_before_dispatch(value: Any):
    assert_invalid_input(parse_paper(value), None)


def test_canonical_seed_missing_full_identity_blocks_before_dispatch():
    value = valid_input()
    del value["seed"]["identity"]

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_canonical_seed_with_malformed_identity_slug_blocks_before_dispatch():
    value = valid_input()
    value["seed"]["identity"]["slug"] = "Not/A-Slug"

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_missing_observation_blocks_before_dispatch():
    value = valid_input()
    del value["observation"]

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_strict_canonical_seed_builds_one_sparse_observation_map():
    assert_parsed_seed(valid_input(), "paper", "paper:exact-paper")


def test_minimal_paper_doi_seed_preserves_provisional_identity():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper-1",
            "hints": {"doi": "10.1000/provisional"},
        },
        "observation": paper_observation_for_slug("request-paper-1"),
        "options": {},
    }

    assert_parsed_seed(value, "paper", "paper:request-paper-1")


def test_minimal_book_isbn_seed_preserves_provisional_identity():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-book-1",
            "hints": {"isbn": "9780000000000"},
        },
        "observation": deepcopy(BOOK_OBSERVATION),
        "options": {},
    }

    assert_parsed_seed(value, "book", "book:request-book-1")


@pytest.mark.parametrize(
    ("kind", "seed", "observation"),
    [
        (
            "paper",
            {"state": "provisional", "requested_slug": "request-paper-1", "hints": {}},
            {**deepcopy(PAPER_OBSERVATION), "slug": "request-paper-1"},
        ),
        (
            "book",
            {"state": "provisional", "requested_slug": "request-book-1", "hints": {}},
            BOOK_OBSERVATION,
        ),
    ],
)
def test_provisional_seed_requires_one_search_anchor(
    kind: str,
    seed: dict[str, Any],
    observation: dict[str, Any],
):
    value = {"seed": seed, "observation": observation, "options": {}}

    result = parse_paper(value) if kind == "paper" else parse_book(value)

    requested_slug = seed["requested_slug"]
    assert_invalid_input(result, requested_slug, kind)


def test_provisional_observation_binds_to_requested_slug():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper-1",
            "hints": {"title": "A provisional paper"},
        },
        "observation": deepcopy(PAPER_OBSERVATION),
        "options": {},
    }

    assert_invalid_input(parse_paper(value), "request-paper-1")


def test_canonical_observation_binds_to_material_slug():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_owner_drift_keeps_material_slug_separate_from_identity_slug():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"
    value["observation"] = paper_observation_for_slug("owned-paper")
    value["observation"]["identity"] = {
        "title": PAPER_IDENTITY["title"],
        "authors": PAPER_IDENTITY["authors"],
        "year": PAPER_IDENTITY["year"],
    }
    value["observation"]["facts"]["canonical"] = {
        "path": "vault/papers/owned-paper.md",
        "present": True,
        "usable": True,
    }

    parsed = parse_paper(value)
    assert parsed["ok"] is True
    assert parsed["value"]["seed"]["material_slug"] == "owned-paper"
    assert parsed["value"]["seed"]["identity"]["slug"] == "exact-paper"

    result = run_workflow_export(
        RESULT_MODULE,
        "completeMaterialResult",
        {
            "material": {
                "requested": {"kind": "paper", "slug": "owned-paper"},
                "canonical": {"kind": "paper", "slug": "owned-paper"},
            }
        },
        [{"role": "canonical", "path": "vault/papers/owned-paper.md"}],
        None,
    )

    assert result["material"]["canonical"]["slug"] == "owned-paper"


def localized_owner_input() -> dict[str, Any]:
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"
    value["observation"] = paper_observation_for_slug("owned-paper")
    value["observation"]["identity"] = {
        "title": "精确论文",
        "authors": ["[[ada-example|Ada Example]]"],
        "year": PAPER_IDENTITY["year"],
    }
    value["observation"]["facts"]["canonical"] = {
        "path": "vault/papers/owned-paper.md",
        "present": True,
        "usable": True,
    }
    return value


def test_localized_owner_drift_requires_search_confirmation():
    value = localized_owner_input()

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_search_confirmed_owner_admits_localized_disk_identity():
    value = localized_owner_input()
    value["seed"]["owner_confirmation"] = {
        "operation": "material.search",
        "identity_slug": "exact-paper",
        "owner_slug": "owned-paper",
    }

    parsed = parse_paper(value)

    assert parsed["ok"] is True
    assert parsed["value"]["seed"] == value["seed"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["seed"]["owner_confirmation"].update(
            {"operation": "paper.prepare"}
        ),
        lambda value: value["seed"]["owner_confirmation"].update(
            {"identity_slug": "other-paper"}
        ),
        lambda value: value["seed"]["owner_confirmation"].update(
            {"owner_slug": "other-paper"}
        ),
        lambda value: value["seed"]["owner_confirmation"].update(
            {"cursor": "hidden-state"}
        ),
        lambda value: value["observation"]["facts"]["canonical"].update(
            {"usable": False}
        ),
        lambda value: value["observation"].update({"identity": None}),
    ],
)
def test_search_confirmed_owner_rejects_mismatched_or_unusable_evidence(mutate):
    value = localized_owner_input()
    value["seed"]["owner_confirmation"] = {
        "operation": "material.search",
        "identity_slug": "exact-paper",
        "owner_slug": "owned-paper",
    }
    mutate(value)

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_owner_drift_rejects_an_empty_status_query_echo():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"
    value["observation"]["slug"] = "owned-paper"

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_unknown_seed_key_blocks_before_dispatch():
    value = valid_input()
    value["seed"]["cursor"] = "hidden-state"

    assert_invalid_input(parse_paper(value), "exact-paper")


@pytest.mark.parametrize(
    ("observation_kind", "observation_slug"),
    [("book", "exact-paper"), ("paper", "other-paper")],
)
def test_observation_identity_mismatch_has_no_dispatchable_value(
    observation_kind: str,
    observation_slug: str,
):
    value = valid_input()
    value["observation"]["kind"] = observation_kind
    value["observation"]["slug"] = observation_slug

    result = parse_paper(value)

    assert_invalid_input(result, "exact-paper")
    assert "value" not in result


def test_translation_target_mismatch_has_no_dispatchable_value():
    observation = translation_observation("fr-FR")
    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_missing_target_has_no_dispatchable_value():
    observation = translation_observation("zh")
    del observation["facts"]["target_language"]

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_rejects_noncanonical_target_tag():
    observation = translation_observation("zh-CN")

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_non_translation_observation_rejects_target_field():
    observation = deepcopy(PAPER_OBSERVATION)
    observation["target_language"] = "zh-CN"

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {"kind": "paper", "slug": "exact-paper"},
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_key_uses_canonical_target():
    observation = translation_observation("zh")

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh",
                },
                "observation": observation,
            }
        ],
    )

    assert result == {
        "__map_entries__": [
            ["translation:paper:exact-paper:zh", observation]
        ]
    }


def test_sparse_observations_rejects_duplicate_keys():
    row = {
        "route": {"kind": "paper", "slug": "exact-paper"},
        "observation": deepcopy(PAPER_OBSERVATION),
    }

    result = run_workflow_export(INPUT_MODULE, "sparseObservations", [row, row])

    assert result is None


def test_shared_parser_rejects_universal_context_bag():
    value = valid_input()
    value["context"] = {"selected_input": "sources/exact-paper.pdf"}

    assert_invalid_input(parse_paper(value), "exact-paper")


@pytest.mark.parametrize("options", [None, [], "all"])
def test_shared_parser_rejects_non_object_options(options: Any):
    value = valid_input()
    value["options"] = options

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_decision_applies_only_to_matching_next_operation_and_fresh_state():
    decision = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": book_year_decision("use-recommended-year"),
    }

    matching = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.acquire",
        False,
    )
    wrong_material = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:other-book",
        "book.acquire",
        False,
    )
    wrong_operation = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.prepare",
        False,
    )
    stale = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.acquire",
        True,
    )

    assert matching == decision["value"]
    assert wrong_material is None
    assert wrong_operation is None
    assert stale is None


def test_translation_decision_value_keeps_its_evidence_binding():
    translation_value = {
        "candidates_fingerprint": "a" * 64,
        "source_path": "sources/exact-paper.pdf",
    }

    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationSourceDecisionValue",
        translation_value,
    ) == translation_value


def identity_conflict_receipt() -> dict[str, Any]:
    candidates = [
        {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
        {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
    ]
    return {
        "operation": "material.search",
        "material_key": "paper:request-paper-1",
        "kind": "paper",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "material.identity_conflict",
                "operation": "material.search",
                "summary": "The evidence supports two work types.",
                "user_question": "Is this the article or the book?",
                "retryable": False,
            },
            "candidates": candidates,
            "conflicts": ["publication_type"],
        },
    }


def test_identity_conflict_gate_binds_the_stamped_owner_and_closed_evidence():
    receipt = identity_conflict_receipt()

    gate = run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "paper",
    )

    assert gate == {
        "kind": "identity_conflict",
        "operation": "material.search",
        "material_key": "paper:request-paper-1",
        "question": "Is this the article or the book?",
        "candidates": receipt["terminal"]["candidates"],
        "conflicts": ["publication_type"],
    }


def test_book_search_gate_rejects_a_paper_candidate():
    receipt = identity_conflict_receipt()
    receipt["kind"] = "book"
    receipt["material_key"] = "book:request-book-1"

    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "book",
    ) is None


def test_identity_conflict_decision_echoes_gate_and_selects_a_member():
    receipt = identity_conflict_receipt()
    gate = run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "paper",
    )
    value = {
        "candidates": deepcopy(gate["candidates"]),
        "conflicts": deepcopy(gate["conflicts"]),
        "selected_candidate": deepcopy(gate["candidates"][1]),
    }

    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        value,
        gate,
    ) == value

    changed_echo = deepcopy(value)
    changed_echo["conflicts"] = ["title"]
    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        changed_echo,
        gate,
    ) is None

    foreign_selection = deepcopy(value)
    foreign_selection["selected_candidate"]["identity"]["slug"] = "other-book"
    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        foreign_selection,
        gate,
    ) is None


def book_year_evidence(
    verdict: str,
    *,
    slug_year: int = 2024,
) -> dict[str, Any]:
    recommended_year = {
        "MATCH": slug_year,
        "MISMATCH": 2025,
        "AMBIGUOUS": None,
    }[verdict]
    return {
        "slug_year": slug_year,
        "source_years": {"publisher": 2025, "catalogue": 2025},
        "pdf_signals": {
            "first_published": 2025,
            "copyright_year": 2025,
            "original_year": None,
            "other_years": [2024],
        },
        "recommended_year": recommended_year,
        "recommendation_reason": "Publisher and catalogue evidence agree.",
        "verdict": verdict,
    }


def book_year_decision(action: str) -> dict[str, Any]:
    verdict = "AMBIGUOUS" if action == "accept-current" else "MISMATCH"
    return {
        "current_identity": deepcopy(BOOK_IDENTITY),
        "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
        "year_evidence": book_year_evidence(verdict),
        "action": action,
    }


@pytest.mark.parametrize("action", ["accept-current", "use-recommended-year"])
def test_book_year_decision_preserves_all_four_bound_values(action: str):
    value = book_year_decision(action)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) == value


@pytest.mark.parametrize(
    ("verdict", "action"),
    [
        ("MATCH", "accept-current"),
        ("MATCH", "use-recommended-year"),
        ("AMBIGUOUS", "use-recommended-year"),
    ],
)
def test_book_year_decision_rejects_actions_without_a_prior_gate(
    verdict: str,
    action: str,
):
    value = book_year_decision(action)
    value["year_evidence"] = book_year_evidence(verdict)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) is None


def test_book_year_decision_binds_evidence_to_current_identity_year():
    value = book_year_decision("accept-current")
    value["year_evidence"] = book_year_evidence("AMBIGUOUS", slug_year=2023)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) is None


def book_year_receipt(
    verdict: str,
    *,
    material_key: str = "book:owned-book",
) -> dict[str, Any]:
    issue_code = {
        "MATCH": "book.year_mismatch",
        "MISMATCH": "book.year_mismatch",
        "AMBIGUOUS": "book.year_ambiguous",
    }[verdict]
    proposed_actions = (
        ["accept-current", "use-recommended-year"]
        if verdict == "MISMATCH"
        else ["accept-current"]
    )
    return {
        "operation": "book.acquire",
        "material_key": material_key,
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": issue_code,
                "operation": "book.acquire",
                "summary": "The source year needs a user decision.",
                "user_question": "Which publication year should be retained?",
                "retryable": False,
            },
            "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
            "year_evidence": book_year_evidence(verdict),
            "proposed_actions": proposed_actions,
        },
    }


@pytest.mark.parametrize(
    ("verdict", "proposed_actions"),
    [
        ("MISMATCH", ["accept-current", "use-recommended-year"]),
        ("AMBIGUOUS", ["accept-current"]),
    ],
)
def test_book_year_gate_keeps_owner_key_separate_from_identity_slug(
    verdict: str,
    proposed_actions: list[str],
):
    receipt = book_year_receipt(verdict)

    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearGate",
        receipt,
        BOOK_IDENTITY,
    )

    assert gate == {
        "kind": "book_year",
        "operation": "book.acquire",
        "material_key": "book:owned-book",
        "current_identity": BOOK_IDENTITY,
        "question": "Which publication year should be retained?",
        "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
        "year_evidence": receipt["terminal"]["year_evidence"],
        "proposed_actions": proposed_actions,
    }


@pytest.mark.parametrize("mutation", ["verdict", "issue", "actions"])
def test_book_year_gate_rejects_verdict_issue_action_incoherence(mutation: str):
    receipt = book_year_receipt("MISMATCH")
    terminal = receipt["terminal"]
    if mutation == "verdict":
        terminal["year_evidence"] = book_year_evidence("MATCH")
    elif mutation == "issue":
        terminal["issue"]["code"] = "book.year_ambiguous"
    else:
        terminal["proposed_actions"] = ["accept-current"]

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearGate",
        receipt,
        BOOK_IDENTITY,
    ) is None


def book_structure_candidates() -> list[dict[str, Any]]:
    return [
        {
            "key": "frontmatter-separate",
            "label": "Keep front matter separate",
            "summary": "The introduction starts after the preface.",
            "chapter_count": 3,
            "chapters": [
                {"title": "Preface", "start": 1, "end": 8},
                {"title": "Introduction", "start": 9, "end": 30},
                {"title": "Argument", "start": 31, "end": 70},
            ],
        },
        {
            "key": "frontmatter-combined",
            "label": "Combine front matter",
            "summary": "The preface belongs with the introduction.",
            "chapter_count": 2,
            "chapters": [
                {"title": "Preface and Introduction", "start": 1, "end": 30},
                {"title": "Argument", "start": 31, "end": 70},
            ],
        },
    ]


def book_structure_receipt() -> dict[str, Any]:
    return {
        "operation": "book.prepare",
        "material_key": "book:exact-book",
        "format": "pdf",
        "selected_source": "sources/exact-book.pdf",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "book.chapter_structure_ambiguous",
                "operation": "book.prepare",
                "summary": "Two coherent chapter structures remain.",
                "user_question": "Which chapter structure should be used?",
                "retryable": False,
            },
            "source_path": "sources/exact-book.pdf",
            "candidates": book_structure_candidates(),
            "conflicts": ["chapter_boundaries", "included_material"],
        },
    }


def test_book_structure_gate_is_a_complete_manual_split_choice():
    receipt = book_structure_receipt()

    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    )

    assert gate == {
        "kind": "book_structure",
        "operation": "book.prepare",
        "material_key": "book:exact-book",
        "question": "Which chapter structure should be used?",
        "source_path": "sources/exact-book.pdf",
        "candidates": receipt["terminal"]["candidates"],
        "conflicts": ["chapter_boundaries", "included_material"],
    }


@pytest.mark.parametrize("mutation", ["duplicate_key", "count", "overlap", "conflict"])
def test_book_structure_gate_rejects_incoherent_cross_field_evidence(
    mutation: str,
):
    receipt = book_structure_receipt()
    terminal = receipt["terminal"]
    if mutation == "duplicate_key":
        terminal["candidates"][1]["key"] = terminal["candidates"][0]["key"]
    elif mutation == "count":
        terminal["candidates"][0]["chapter_count"] = 2
    elif mutation == "overlap":
        terminal["candidates"][0]["chapters"][1]["start"] = 8
    else:
        terminal["conflicts"] = ["chapter_boundaries", "chapter_boundaries"]

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    ) is None


def test_book_structure_decision_echoes_gate_and_selects_a_member():
    receipt = book_structure_receipt()
    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    )
    value = {
        "source_path": gate["source_path"],
        "candidates": deepcopy(gate["candidates"]),
        "conflicts": deepcopy(gate["conflicts"]),
        "selected_candidate": deepcopy(gate["candidates"][0]),
    }

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureDecisionValue",
        value,
        gate,
    ) == value

    value["source_path"] = "sources/another-book.pdf"
    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureDecisionValue",
        value,
        gate,
    ) is None


def test_paper_source_decision_parser_accepts_only_closed_testimony() -> None:
    value = {
        "candidates_fingerprint": "c" * 64,
        "source_path": "sources/exact-paper.pdf",
    }

    assert run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperSourceDecisionValue",
        value,
    ) == value

    for invalid in (
        {**value, "candidates_fingerprint": "invalid"},
        {**value, "source_path": ""},
        {**value, "cursor": "hidden-state"},
    ):
        assert run_workflow_export(
            PAPER_CONTRACT_MODULE,
            "parsePaperSourceDecisionValue",
            invalid,
        ) is None


def test_paper_source_gate_crosses_the_closed_material_result_boundary() -> None:
    gate = {
        "kind": "paper_source",
        "operation": "paper.prepare",
        "material_key": "paper:exact-paper",
        "question": "Which exact Paper source should Prepare use?",
        "candidates": [
            {
                "format": "pdf",
                "path": "sources/exact-paper.pdf",
                "sha256": "a" * 64,
                "size": 123,
            },
            {
                "format": "txt",
                "path": "sources/exact-paper.txt",
                "sha256": "b" * 64,
                "size": 456,
            },
        ],
        "candidates_fingerprint": "c" * 64,
    }
    resume_seed = {
        "route": {"kind": "paper", "slug": "exact-paper"},
        "seed": {
            "state": "canonical",
            "material_slug": "exact-paper",
            "identity": deepcopy(PAPER_IDENTITY),
        },
        "options": {},
    }
    issue = {
        "code": "paper.source_selection_required",
        "operation": "paper.prepare",
        "summary": "Select one source.",
        "retryable": False,
        "observation_request": None,
    }

    result = run_workflow_export(
        RESULT_MODULE,
        "needsInputMaterialResult",
        {
            "material": {
                "requested": {"kind": "paper", "slug": "exact-paper"},
                "canonical": {"kind": "paper", "slug": "exact-paper"},
            }
        },
        issue,
        gate,
        resume_seed,
    )

    assert result["gate"] == gate
    assert result["resume_seed"] == resume_seed


def translation_gate_receipt(kind: str) -> dict[str, Any]:
    source_candidate = {
        "path": "sources/exact-paper.pdf",
        "sha256": "a" * 64,
        "size": 1234,
        "pages": 10,
    }
    if kind == "source_selection":
        issue_code = "translation.source_selection_required"
        missing_fields = []
        candidates = [
            source_candidate,
            {
                **source_candidate,
                "path": "processing/papers/exact-paper/ocr.pdf",
                "sha256": "b" * 64,
            },
        ]
        candidates_fingerprint = "f" * 64
        question = "Which source should be translated?"
    else:
        issue_code = "translation.configuration_required"
        missing_fields = ["translate_api_key", "translate_model"]
        candidates = []
        candidates_fingerprint = None
        question = "Which translation configuration should be used?"
    return {
        "operation": "translation.prepare",
        "material_key": "translation:paper:exact-paper:zh",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": issue_code,
                "operation": "translation.prepare",
                "summary": "Translation needs one user decision.",
                "user_question": question,
                "retryable": False,
            },
            "gate": {
                "kind": kind,
                "missing_fields": missing_fields,
                "candidates": candidates,
                "candidates_fingerprint": candidates_fingerprint,
            },
        },
    }


@pytest.mark.parametrize(
    ("receipt_kind", "material_gate_kind"),
    [
        ("source_selection", "translation_source"),
        ("configuration_required", "translation_configuration"),
    ],
)
def test_translation_gate_maps_each_exact_receipt_arm(
    receipt_kind: str,
    material_gate_kind: str,
):
    receipt = translation_gate_receipt(receipt_kind)

    gate = run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        receipt,
    )

    assert gate == {
        "kind": material_gate_kind,
        "operation": "translation.prepare",
        "material_key": "translation:paper:exact-paper:zh",
        "question": receipt["terminal"]["issue"]["user_question"],
        "missing_fields": receipt["terminal"]["gate"]["missing_fields"],
        "candidates": receipt["terminal"]["gate"]["candidates"],
        "candidates_fingerprint": receipt["terminal"]["gate"][
            "candidates_fingerprint"
        ],
    }


def test_translation_gate_rejects_issue_and_gate_kind_mismatch():
    receipt = translation_gate_receipt("source_selection")
    receipt["terminal"]["issue"][
        "code"
    ] = "translation.configuration_required"

    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        receipt,
    ) is None


def test_translation_source_gate_binds_unique_candidates_to_its_material():
    foreign = translation_gate_receipt("source_selection")
    foreign["terminal"]["gate"]["candidates"][1]["path"] = (
        "processing/papers/another-paper/ocr.pdf"
    )
    duplicate = translation_gate_receipt("source_selection")
    duplicate["terminal"]["gate"]["candidates"][1] = deepcopy(
        duplicate["terminal"]["gate"]["candidates"][0]
    )

    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        foreign,
    ) is None
    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        duplicate,
    ) is None


def test_complete_material_result_exposes_only_the_closed_public_shape():
    base = {
        "material": {
            "requested": {"kind": "paper", "slug": "exact-paper"},
            "canonical": {"kind": "paper", "slug": "exact-paper"},
        },
        "receipts": [{"legacy_sentinel": "must-not-cross-public-boundary"}],
    }
    artifacts = [{"role": "canonical", "path": "vault/papers/exact-paper.md"}]

    result = run_workflow_export(
        RESULT_MODULE,
        "completeMaterialResult",
        base,
        artifacts,
        None,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        "material": base["material"],
        "terminal": "complete",
        "issue": None,
        "artifacts": artifacts,
        "next": None,
    }


def test_topic_incomplete_result_has_only_closed_pending_rows():
    base = {
        "material": {
            "requested": {"kind": "topic", "slug": "exact-topic"},
            "canonical": {"kind": "topic", "slug": "exact-topic"},
        },
    }
    issue = {
        "code": "topic.round_limit",
        "operation": None,
        "summary": "The bounded round ended with unseen work.",
        "retryable": False,
        "observation_request": None,
    }
    artifacts = [
        {"role": "outline", "path": "vault/topics/exact-topic/outline.md"},
        {"role": "overview", "path": "vault/topics/exact-topic/overview.md"},
        {"role": "resources", "path": "vault/topics/exact-topic/resources.md"},
    ]
    pending = [
        {
            "kind": "material",
            "material_kind": "paper",
            "requested_slug": "next-paper",
            "subq": "sq-1",
            "role": "counterpoint",
            "fingerprint": "f-1",
        },
        {
            "kind": "webcard",
            "card_slug": "next-card",
            "subq": "sq-2",
            "fingerprint": "f-2",
        },
    ]

    result = run_workflow_export(
        RESULT_MODULE,
        "incompleteTopicMaterialResult",
        base,
        issue,
        artifacts,
        pending,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        **base,
        "terminal": "incomplete",
        "issue": issue,
        "artifacts": artifacts,
        "pending_work": pending,
    }


@pytest.mark.parametrize("terminal", ["blocked", "failed"])
def test_stopped_material_result_has_closed_terminal_constructor(terminal: str):
    base = {
        "material": {
            "requested": {"kind": "talk", "slug": "exact-talk"},
            "canonical": None,
        },
    }
    issue = {
        "code": "material.stopped",
        "operation": "talk.prepare",
        "summary": "The material stopped.",
        "retryable": False,
        "observation_request": None,
    }

    result = run_workflow_export(
        RESULT_MODULE,
        f"{terminal}MaterialResult",
        base,
        issue,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        **base,
        "terminal": terminal,
        "issue": issue,
    }
