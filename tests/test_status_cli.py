from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.status import status as status_module


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STATUS = PLUGIN_ROOT / "scripts" / "status" / "status.py"


def run_status(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(
        [sys.executable, str(STATUS), *args],
        cwd=PLUGIN_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


def write(path: Path, content: str | bytes = "content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def frontmatter(kind: str, fields: str = "") -> str:
    return f"---\ntype: {kind}\n{fields}---\n\n# Canonical artifact\n"


def observation(path: str, *, present: bool, usable: bool) -> dict[str, object]:
    return {"path": path, "present": present, "usable": usable}


def write_webarchive(path: Path, *, url: str, title: str = "Saved title", site: str = "Example Site") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        plistlib.dumps(
            {
                "WebMainResource": {
                    "WebResourceData": (
                        f"<html><head><title>{title}</title>"
                        f'<meta property="og:site_name" content="{site}"></head></html>'
                    ).encode("utf-8"),
                    "WebResourceURL": url,
                    "WebResourceMIMEType": "text/html",
                    "WebResourceTextEncodingName": "UTF-8",
                }
            },
            fmt=plistlib.FMT_BINARY,
        )
    )
    stamp = datetime(2026, 8, 13, 12, 34, 56, tzinfo=timezone.utc).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def webpage_canonical(*, url: str, title: str = "Saved title", site: str = "Example Site") -> str:
    return frontmatter(
        "webpage",
        f"title: {title}\nurl: {url}\nsite: {site}\n"
        "captured_at: 2026-08-13T12:34:56Z\n",
    )


def test_empty_webpage_status_is_one_closed_factual_observation(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    slug = "example-org-page"

    result = run_status(project, "--kind", "webpage", "--slug", slug, "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": "quasi.status/0.2",
        "kind": "webpage",
        "slug": slug,
        "identity": None,
        "facts": {
            "kind": "webpage",
            "snapshot": observation(f"vault/webpages/{slug}/snapshot.webarchive", present=False, usable=False),
            "prepared": observation(f"processing/webpages/{slug}/source.md", present=False, usable=False),
            "canonical": observation(f"vault/webpages/{slug}/webpage.md", present=False, usable=False),
            "captured_at": None,
        },
    }


def test_webpage_status_observes_snapshot_only_progress(tmp_path: Path):
    project = tmp_path / "project"
    slug = "example-org-page"
    write_webarchive(
        project / "vault" / "webpages" / slug / "snapshot.webarchive",
        url="https://example.org/page",
    )

    payload = json.loads(run_status(project, "--kind", "webpage", "--slug", slug, "--json").stdout)

    assert payload["facts"]["snapshot"] == observation(
        f"vault/webpages/{slug}/snapshot.webarchive", present=True, usable=True
    )
    assert payload["facts"]["captured_at"] == "2026-08-13T12:34:56Z"
    assert payload["identity"] == {
        "slug": slug, "title": "Saved title", "url": "https://example.org/page", "site": "Example Site"
    }


def test_webpage_status_observes_prepared_utf8_markdown(tmp_path: Path):
    project = tmp_path / "project"
    slug = "example-org-page"
    write(project / "processing" / "webpages" / slug / "source.md", "Prepared source")

    payload = json.loads(run_status(project, "--kind", "webpage", "--slug", slug, "--json").stdout)

    assert payload["facts"]["prepared"] == observation(
        f"processing/webpages/{slug}/source.md", present=True, usable=True
    )


def test_webpage_status_observes_coherent_canonical_completion(tmp_path: Path):
    project = tmp_path / "project"
    slug = "example-org-page"
    snapshot_path = project / "vault" / "webpages" / slug / "snapshot.webarchive"
    source_path = project / "processing" / "webpages" / slug / "source.md"
    canonical_path = project / "vault" / "webpages" / slug / "webpage.md"
    write_webarchive(snapshot_path, url="https://example.org/page")
    write(source_path, "Prepared source")
    write(canonical_path, webpage_canonical(url="https://example.org/page"))

    payload = json.loads(run_status(project, "--kind", "webpage", "--slug", slug, "--json").stdout)

    assert payload["facts"] == {
        "kind": "webpage",
        "snapshot": observation(snapshot_path.relative_to(project).as_posix(), present=True, usable=True),
        "prepared": observation(source_path.relative_to(project).as_posix(), present=True, usable=True),
        "canonical": observation(canonical_path.relative_to(project).as_posix(), present=True, usable=True),
        "captured_at": "2026-08-13T12:34:56Z",
    }
    assert payload["identity"] == {
        "slug": slug, "title": "Saved title", "url": "https://example.org/page", "site": "Example Site"
    }


def test_webpage_status_keeps_snapshot_identity_when_canonical_disagrees(tmp_path: Path):
    project = tmp_path / "project"
    slug = "example-org-page"
    write_webarchive(
        project / "vault" / "webpages" / slug / "snapshot.webarchive",
        url="https://example.org/page",
    )
    write(
        project / "vault" / "webpages" / slug / "webpage.md",
        webpage_canonical(url="https://example.org/other"),
    )

    payload = json.loads(run_status(project, "--kind", "webpage", "--slug", slug, "--json").stdout)

    assert payload["facts"]["canonical"]["present"] is True
    assert payload["facts"]["canonical"]["usable"] is False
    assert payload["identity"]["url"] == "https://example.org/page"


def test_webpage_status_rejects_canonical_frontmatter_outside_the_webpage_schema(tmp_path: Path):
    project = tmp_path / "project"
    slug = "example-org-page"
    write_webarchive(
        project / "vault" / "webpages" / slug / "snapshot.webarchive",
        url="https://example.org/page",
    )
    canonical = project / "vault" / "webpages" / slug / "webpage.md"
    for invalid_field in ("authors: Ada", "unknown: value"):
        write(
            canonical,
            webpage_canonical(url="https://example.org/page").replace(
                "captured_at: 2026-08-13T12:34:56Z\n---",
                f"captured_at: 2026-08-13T12:34:56Z\n{invalid_field}\n---",
            ),
        )

        payload = json.loads(run_status(project, "--kind", "webpage", "--slug", slug, "--json").stdout)

        assert payload["facts"]["canonical"]["present"] is True
        assert payload["facts"]["canonical"]["usable"] is False


def test_status_scan_rejects_a_symlinked_webpage_root(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external-webpages"
    write_webarchive(
        external / "escaped-page" / "snapshot.webarchive",
        url="https://example.org/escaped",
    )
    (project / "vault").mkdir()
    (project / "vault" / "webpages").symlink_to(external, target_is_directory=True)

    payload = json.loads(run_status(project, "--scan", "--json").stdout)

    assert not [item for item in payload["items"] if item["kind"] == "webpage"]


def test_empty_paper_status_is_one_closed_factual_observation(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    result = run_status(
        project,
        "--kind",
        "paper",
        "--slug",
        "missing-paper",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": "quasi.status/0.2",
        "kind": "paper",
        "slug": "missing-paper",
        "identity": None,
        "facts": {
            "kind": "paper",
            "source": observation(
                "sources/missing-paper.pdf", present=False, usable=False
            ),
            "prepared": [
                observation(
                    "processing/papers/missing-paper/source.txt",
                    present=False,
                    usable=False,
                ),
                observation(
                    "processing/papers/missing-paper/ocr.txt",
                    present=False,
                    usable=False,
                ),
            ],
            "canonical": observation(
                "vault/papers/missing-paper.md", present=False, usable=False
            ),
        },
    }


def test_book_status_keeps_complete_manifest_rows_and_observes_each_output(
    tmp_path: Path,
):
    project = tmp_path / "project"
    slug = "exact-book"
    write(project / "sources" / f"{slug}.epub", b"EPUB")
    chapter_root = project / "processing" / "chapters" / slug
    chapters = [
        {
            "slot": "01",
            "title": "Opening",
            "filename": "01_Opening.txt",
            "slug": "opening",
            "word_count": 120,
            "start_page": None,
            "end_page": None,
        },
        {
            "slot": "02",
            "title": "Closing",
            "filename": "02_Closing.txt",
            "slug": "closing",
            "word_count": 80,
            "start_page": 4,
            "end_page": 7,
        },
    ]
    write(chapter_root / "manifest.json", json.dumps({"chapters": chapters}))
    for chapter in chapters:
        write(chapter_root / chapter["filename"], "normalised chapter")
    write(
        project / "vault" / "books" / slug / "ch01-opening.md",
        frontmatter("chapter"),
    )
    write(
        project / "vault" / "books" / slug / "00-overview.md",
        frontmatter(
            "book",
            "title: Exact Book\nauthors:\n  - Ada Example\nyear: 2024\n",
        ),
    )

    result = run_status(project, "--kind", "book", "--slug", slug, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"schema_version", "kind", "slug", "identity", "facts"}
    assert payload["identity"] == {
        "title": "Exact Book",
        "authors": ["Ada Example"],
        "year": 2024,
    }
    assert payload["facts"]["manifest"] == {
        **observation(
            f"processing/chapters/{slug}/manifest.json",
            present=True,
            usable=True,
        ),
        "valid": True,
    }
    assert payload["facts"]["chapters"] == [
        {
            **chapters[0],
            "input": observation(
                f"processing/chapters/{slug}/01_Opening.txt",
                present=True,
                usable=True,
            ),
            "output": observation(
                f"vault/books/{slug}/ch01-opening.md",
                present=True,
                usable=True,
            ),
        },
        {
            **chapters[1],
            "input": observation(
                f"processing/chapters/{slug}/02_Closing.txt",
                present=True,
                usable=True,
            ),
            "output": observation(
                f"vault/books/{slug}/ch02-closing.md",
                present=False,
                usable=False,
            ),
        },
    ]


def test_book_status_rejects_an_unpaired_manifest_page_range(tmp_path: Path):
    project = tmp_path / "project"
    slug = "bad-pages"
    write(
        project / "processing" / "chapters" / slug / "manifest.json",
        json.dumps(
            {
                "chapters": [
                    {
                        "slot": "01",
                        "title": "Opening",
                        "filename": "01_Opening.txt",
                        "slug": "opening",
                        "word_count": 10,
                        "start_page": 1,
                        "end_page": None,
                    }
                ]
            }
        ),
    )

    result = run_status(project, "--kind", "book", "--slug", slug, "--json")

    assert result.returncode == 0, result.stderr
    facts = json.loads(result.stdout)["facts"]
    assert facts["manifest"]["present"] is True
    assert facts["manifest"]["usable"] is True
    assert facts["manifest"]["valid"] is False
    assert facts["chapters"] == []


def test_book_status_rejects_duplicate_canonical_chapter_slugs(tmp_path: Path):
    project = tmp_path / "project"
    slug = "duplicate-chapters"
    chapters = [
        {
            "slot": "01",
            "title": "Opening",
            "filename": "01_Opening.txt",
            "slug": "same-chapter",
            "word_count": 10,
            "start_page": None,
            "end_page": None,
        },
        {
            "slot": "02",
            "title": "Closing",
            "filename": "02_Closing.txt",
            "slug": "same-chapter",
            "word_count": 20,
            "start_page": None,
            "end_page": None,
        },
    ]
    write(
        project / "processing" / "chapters" / slug / "manifest.json",
        json.dumps({"chapters": chapters}),
    )

    result = run_status(project, "--kind", "book", "--slug", slug, "--json")

    assert result.returncode == 0, result.stderr
    facts = json.loads(result.stdout)["facts"]
    assert facts["manifest"]["valid"] is False
    assert facts["chapters"] == []


def test_talk_status_reports_media_transcripts_and_canonical_identity(tmp_path: Path):
    project = tmp_path / "project"
    slug = "exact-talk"
    write(project / "sources" / f"{slug}.mp3", b"audio")
    write(
        project / "processing" / "talks" / slug / "transcript.whisper.srt",
        "transcript",
    )
    write(
        project / "vault" / "talks" / slug / "talk.md",
        frontmatter("talk", "title: Exact Talk\nyear: 2024\n"),
    )

    result = run_status(project, "--kind", "talk", "--slug", slug, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["identity"] == {"title": "Exact Talk", "year": 2024}
    assert [item for item in payload["facts"]["media"] if item["present"]] == [
        observation(f"sources/{slug}.mp3", present=True, usable=True)
    ]
    assert payload["facts"]["transcripts"] == [
        observation(
            f"processing/talks/{slug}/transcript.whisper.srt",
            present=True,
            usable=True,
        )
    ]
    assert payload["facts"]["canonical"] == observation(
        f"vault/talks/{slug}/talk.md", present=True, usable=True
    )


def test_translation_status_requires_and_normalises_one_exact_target(tmp_path: Path):
    project = tmp_path / "project"
    slug = "exact-translation"
    write(project / "sources" / f"{slug}.pdf", b"%PDF-source")
    for tag in ("zh-cn", "fr-fr"):
        write(
            project / "processing" / "translations" / f"{slug}-{tag}.pdf",
            b"%PDF-translation",
        )
        write(
            project
            / "processing"
            / "translations"
            / f"{slug}-{tag}.manifest.json",
            "{}",
        )

    missing_target = run_status(
        project, "--kind", "translation", "--slug", slug, "--json"
    )
    result = run_status(
        project,
        "--kind",
        "translation",
        "--slug",
        slug,
        "--target-language",
        "zh-cn",
        "--json",
    )

    assert missing_target.returncode == 2
    assert json.loads(missing_target.stdout)["error"]["code"] == "invalid_invocation"
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": "quasi.status/0.2",
        "kind": "translation",
        "slug": slug,
        "identity": None,
        "facts": {
            "kind": "translation",
            "target_language": "zh-CN",
            "source": observation(
                f"sources/{slug}.pdf", present=True, usable=True
            ),
            "output": observation(
                f"processing/translations/{slug}-zh-cn.pdf",
                present=True,
                usable=True,
            ),
            "manifest": observation(
                f"processing/translations/{slug}-zh-cn.manifest.json",
                present=True,
                usable=True,
            ),
        },
    }


def test_translation_status_does_not_complete_a_target_from_another_language(
    tmp_path: Path,
):
    project = tmp_path / "project"
    slug = "isolated-translation"
    write(project / "sources" / f"{slug}.pdf", b"%PDF-source")
    write(
        project / "processing" / "translations" / f"{slug}-fr-fr.pdf",
        b"%PDF-translation",
    )
    write(
        project / "processing" / "translations" / f"{slug}-fr-fr.manifest.json",
        "{}",
    )

    result = run_status(
        project,
        "--kind",
        "translation",
        "--slug",
        slug,
        "--target-language",
        "zh-CN",
        "--json",
    )

    facts = json.loads(result.stdout)["facts"]
    assert facts["output"]["present"] is False
    assert facts["manifest"]["present"] is False


def test_translation_source_keeps_the_shared_symlink_observation_semantics(
    tmp_path: Path,
):
    project = tmp_path / "project"
    source = write(tmp_path / "outside.pdf", b"%PDF-source")
    link = project / "sources" / "linked-source.pdf"
    link.parent.mkdir(parents=True)
    link.symlink_to(source)

    result = run_status(
        project,
        "--kind",
        "translation",
        "--slug",
        "linked-source",
        "--target-language",
        "zh-CN",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["facts"]["source"] == observation(
        "sources/linked-source.pdf", present=True, usable=True
    )


def test_author_and_topic_status_use_exact_canonical_paths(tmp_path: Path):
    project = tmp_path / "project"
    author = "ada-example"
    topic = "exact-topic"
    write(
        project / "vault" / "authors" / f"{author}.md",
        frontmatter("author", "name: Ada Example\n"),
    )
    write(
        project / "vault" / "papers" / "exact-paper.md",
        frontmatter("paper", "title: Exact Paper\n"),
    )
    write(
        project / "vault" / "topics" / topic / "cards" / "exact-card.md",
        frontmatter(
            "topic",
            "title: Exact Card\nkind: card\ncreated: 2024-01-01\n",
        ),
    )
    write(
        project / "vault" / "topics" / topic / "02-outline.md",
        frontmatter(
            "topic",
            "title: Exact Topic\n"
            "kind: outline\n"
            "subquestions:\n"
            "  - id: sq-one\n"
            "    question: What is the exact claim?\n"
            "    coverage: thin\n"
            "    channel: mixed\n"
            "    theory_used: 1\n"
            "    items:\n"
            "      - kind: paper\n"
            "        slug: exact-paper\n"
            "        role: evidence\n"
            "    cards:\n"
            "      - exact-card\n",
        ),
    )
    write(
        project / "vault" / "topics" / topic / "00-overview.md",
        frontmatter("topic", "title: Exact Topic\nkind: overview\n"),
    )
    write(
        project / "vault" / "topics" / topic / "01-resources.md",
        frontmatter("topic", "title: Exact Resources\nkind: resources\n"),
    )

    author_result = run_status(
        project, "--kind", "author", "--slug", author, "--json"
    )
    topic_result = run_status(
        project, "--kind", "topic", "--slug", topic, "--json"
    )

    assert author_result.returncode == topic_result.returncode == 0
    assert json.loads(author_result.stdout) == {
        "schema_version": "quasi.status/0.2",
        "kind": "author",
        "slug": author,
        "identity": {"name": "Ada Example"},
        "facts": {
            "kind": "author",
            "canonical": observation(
                f"vault/authors/{author}.md", present=True, usable=True
            ),
        },
    }
    topic_payload = json.loads(topic_result.stdout)
    assert topic_payload["identity"] == {"title": "Exact Topic"}
    assert topic_payload["facts"]["outline"]["valid"] is True
    assert topic_payload["facts"]["outline"]["projection"] == {
        "subquestions": [
            {
                "id": "sq-one",
                "question": "What is the exact claim?",
                "coverage": "thin",
                "channel": "mixed",
                "theory_used": 1,
            }
        ],
        "members": [
            {
                "kind": "paper",
                "slug": "exact-paper",
                "subq": "sq-one",
                "role": "evidence",
                "artifact": observation(
                    "vault/papers/exact-paper.md", present=True, usable=True
                ),
            }
        ],
        "cards": [
            {
                "slug": "exact-card",
                "subq": "sq-one",
                "title": "Exact Card",
                "artifact": observation(
                    f"vault/topics/{topic}/cards/exact-card.md",
                    present=True,
                    usable=True,
                ),
            }
        ],
    }


def test_topic_status_fails_the_whole_projection_for_an_unsafe_member_slug(
    tmp_path: Path,
):
    project = tmp_path / "project"
    topic = "unsafe-topic"
    write(
        project / "vault" / "topics" / topic / "02-outline.md",
        frontmatter(
            "topic",
            "title: Unsafe Topic\n"
            "kind: outline\n"
            "subquestions:\n"
            "  - id: sq-one\n"
            "    question: What escapes the topic?\n"
            "    coverage: gap\n"
            "    items:\n"
            "      - kind: paper\n"
            "        slug: ../escape\n"
            "    cards: []\n",
        ),
    )

    result = run_status(
        project, "--kind", "topic", "--slug", topic, "--json"
    )

    assert result.returncode == 0, result.stderr
    outline = json.loads(result.stdout)["facts"]["outline"]
    assert outline["present"] is True
    assert outline["usable"] is True
    assert outline["valid"] is False
    assert outline["projection"] is None


def test_status_scan_is_compact_sorted_and_deduplicated(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    write(project / "sources" / "paper-scan.pdf", b"%PDF")
    write(project / "processing" / "papers" / "paper-scan" / "source.txt", "text")
    write(project / "sources" / "book-scan.epub", b"EPUB")
    write(project / "sources" / "talk-scan.wav", b"WAV")

    result = run_status(project, "--scan", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": "quasi.status-scan/0.2",
        "items": [
            {"kind": "book", "slug": "book-scan"},
            {"kind": "paper", "slug": "paper-scan"},
            {"kind": "talk", "slug": "talk-scan"},
        ],
    }


def test_status_scan_discovers_one_safe_webpage_slug_from_each_artifact_root(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    write_webarchive(
        project / "vault" / "webpages" / "snapshot-root" / "snapshot.webarchive",
        url="https://example.org/snapshot",
    )
    write(project / "processing" / "webpages" / "prepared-root" / "source.md", "Prepared source")
    write(
        project / "vault" / "webpages" / "canonical-root" / "webpage.md",
        webpage_canonical(url="https://example.org/canonical"),
    )

    payload = json.loads(run_status(project, "--scan", "--json").stdout)

    assert [item for item in payload["items"] if item["kind"] == "webpage"] == [
        {"kind": "webpage", "slug": "canonical-root"},
        {"kind": "webpage", "slug": "prepared-root"},
        {"kind": "webpage", "slug": "snapshot-root"},
    ]


def test_target_language_is_rejected_for_scan(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    result = run_status(
        project, "--scan", "--target-language", "zh-CN", "--json"
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_invocation"


def test_identity_mode_is_removed_because_identity_is_always_returned(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    result = run_status(
        project,
        "--kind",
        "paper",
        "--slug",
        "exact-paper",
        "--identity",
        "--json",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_invocation"


def test_paper_status_uses_live_operation_catalog_artifact_template(
    tmp_path: Path, monkeypatch,
):
    project = tmp_path / "project"
    slug = "manifest-paper"
    source = write(project / "alternate-sources" / f"{slug}.pdf", b"%PDF")
    monkeypatch.setitem(
        status_module.OPERATION_CATALOG["paper.acquire"]["artifacts"],
        "output",
        "alternate-sources/{slug}.pdf",
    )

    payload = status_module.paper_status(project, slug)

    assert payload["facts"]["source"] == observation(
        source.relative_to(project).as_posix(), present=True, usable=True
    )
