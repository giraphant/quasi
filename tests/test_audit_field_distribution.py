from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from audit import field_distribution  # noqa: E402


def write_doc(path: Path, frontmatter: str | None, body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        content = f"{body}\n"
    else:
        content = f"---\n{frontmatter.rstrip()}\n---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")


def test_audit_path_groups_fields_by_canonical_and_deprecated_type(tmp_path: Path):
    project = tmp_path / "project"
    vault = project / "vault"
    vault.mkdir(parents=True)

    write_doc(
        vault / "papers" / "paper.md",
        frontmatter="type: paper\ntitle: Test Paper\nthemes: [sociology]",
    )
    write_doc(
        vault / "papers" / "deprecated.md",
        frontmatter="type: journal-article\ntitle: Deprecated Type Paper",
    )

    report = field_distribution.audit_path(
        vault, root=project, requested_path="vault", example_limit=2
    )

    assert report["version"] == "quasi-audit.frontmatter-fields.v1"
    assert report["summary"]["files_scanned"] == 2
    assert report["summary"]["frontmatter_files"] == 2
    assert report["summary"]["deprecated_type"] == 1

    types = report["types"]
    assert types["paper"]["files"] == 2
    assert types["paper"]["fields"]["title"]["count"] == 2
    assert types["paper"]["fields"]["title"]["coverage"] == 1.0
    assert types["paper"]["fields"]["themes"]["count"] == 1
    assert types["paper"]["fields"]["themes"]["coverage"] == 0.5

    deprecated = report["problems"]["deprecated_type"]
    assert len(deprecated) == 1
    assert deprecated[0]["path"] == "vault/papers/deprecated.md"
    assert deprecated[0]["raw_type"] == "journal-article"
    assert deprecated[0]["canonical_type"] == "paper"


def test_audit_path_records_frontmatter_problem_buckets(tmp_path: Path):
    project = tmp_path / "project"
    vault = project / "vault"
    vault.mkdir(parents=True)

    write_doc(
        vault / "papers" / "missing-frontmatter.md",
        frontmatter=None,
        body="Some markdown body without frontmatter.",
    )
    write_doc(
        vault / "papers" / "invalid-frontmatter.md",
        frontmatter="type: paper\ntitle: unquoted: colon breaks YAML",
    )
    write_doc(
        vault / "papers" / "missing-type.md",
        frontmatter="title: No Type Field",
    )
    write_doc(
        vault / "papers" / "unknown-type.md",
        frontmatter="type: unknown-type-value\ntitle: Unknown Type",
    )

    report = field_distribution.audit_path(
        vault, root=project, requested_path="vault", example_limit=2
    )

    assert report["summary"]["files_scanned"] == 4
    assert report["summary"]["frontmatter_files"] == 3
    assert report["summary"]["missing_frontmatter"] == 1
    assert report["summary"]["invalid_frontmatter"] == 1
    assert report["summary"]["missing_type"] == 1
    assert report["summary"]["unknown_type"] == 1

    assert report["types"]["_missing_type"]["files"] == 1
    assert report["types"]["_unknown_type"]["files"] == 1

    assert report["problems"]["missing_frontmatter"] == [
        {"path": "vault/papers/missing-frontmatter.md"}
    ]
    assert report["problems"]["invalid_frontmatter"][0]["path"] == (
        "vault/papers/invalid-frontmatter.md"
    )
    assert report["problems"]["missing_type"] == [
        {"path": "vault/papers/missing-type.md"}
    ]
    assert report["problems"]["unknown_type"] == [
        {
            "path": "vault/papers/unknown-type.md",
            "raw_type": "unknown-type-value",
            "python_type": "str",
        }
    ]


def test_audit_path_handles_list_valued_yaml_type_as_unknown(tmp_path: Path):
    project = tmp_path / "project"
    vault = project / "vault"
    vault.mkdir(parents=True)

    write_doc(
        vault / "papers" / "bad-type.md",
        frontmatter="type:\n- paper\ntitle: Bad Type",
    )

    report = field_distribution.audit_path(
        vault, root=project, requested_path="vault", example_limit=2
    )

    assert report["summary"]["unknown_type"] == 1
    assert report["types"]["_unknown_type"]["files"] == 1

    problems = report["problems"]["unknown_type"]
    assert len(problems) == 1
    assert problems[0]["python_type"] == "list"
    assert problems[0]["path"] == "vault/papers/bad-type.md"
    assert "raw_type" in problems[0]


def test_render_markdown_includes_summary_type_table_and_problems(tmp_path: Path):
    project = tmp_path / "project"
    vault = project / "vault"
    vault.mkdir(parents=True)

    write_doc(
        vault / "papers" / "paper.md",
        frontmatter="type: paper\ntitle: Test Paper",
    )
    write_doc(
        vault / "papers" / "missing-frontmatter.md",
        frontmatter=None,
        body="Plain body text.",
    )

    report = field_distribution.audit_path(
        vault, root=project, requested_path="vault", example_limit=2
    )

    markdown = field_distribution.render_markdown(report)

    assert "# Frontmatter field distribution" in markdown
    assert "## Summary" in markdown
    assert "- `files_scanned`: 2" in markdown
    assert "## Type: paper" in markdown
    assert "| Field | Count | Coverage | Examples |" in markdown
    assert "| `title` | 1 | 100.0% | `vault/papers/paper.md` |" in markdown
    assert "## Problems" in markdown
    assert "### missing_frontmatter" in markdown
    assert "vault/papers/missing-frontmatter.md" in markdown
