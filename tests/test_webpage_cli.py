from __future__ import annotations

import plistlib
import re
from importlib import import_module
from pathlib import Path

import pytest

def webarchive_fixture_bytes(
    url: str,
    html: str,
    subresource_urls: tuple[str, ...] = (),
) -> bytes:
    return plistlib.dumps(
        {
            "WebMainResource": {
                "WebResourceData": html.encode("utf-8"),
                "WebResourceURL": url,
                "WebResourceMIMEType": "text/html",
                "WebResourceTextEncodingName": "UTF-8",
            },
            "WebSubresources": [
                {
                    "WebResourceData": b"fixture",
                    "WebResourceURL": item,
                    "WebResourceMIMEType": "text/plain",
                }
                for item in subresource_urls
            ],
            "WebSubframeArchives": [],
        },
        fmt=plistlib.FMT_BINARY,
    )


def write_webarchive_fixture(tmp_path: Path, *, url: str, html: str) -> Path:
    path = tmp_path / "snapshot.webarchive"
    path.write_bytes(webarchive_fixture_bytes(url, html))
    return path


def load_webarchive_module():
    try:
        return import_module("scripts.webpage.webarchive")
    except ModuleNotFoundError:
        pytest.fail("WebArchive capability package has not been implemented")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443", "https://example.com/"),
        ("http://Example.COM:80/a?q=2#frag", "http://example.com/a?q=2"),
    ],
)
def test_normalize_web_url(raw: str, expected: str) -> None:
    assert load_webarchive_module().normalize_web_url(raw) == expected


def test_normalize_web_url_rejects_credentials_and_control_characters() -> None:
    with pytest.raises(ValueError, match="credential"):
        load_webarchive_module().normalize_web_url(
            "https://alice:secret@example.org/article"
        )
    with pytest.raises(ValueError, match="control"):
        load_webarchive_module().normalize_web_url("https://example.org/article\nnext")


def test_collision_slug_uses_a_stable_eight_hex_url_suffix() -> None:
    normalized_url = "https://example.org/an-article"

    assert (
        load_webarchive_module().collision_slug("saved-article", normalized_url)
        == "saved-article-c8c95681"
    )
    assert (
        load_webarchive_module().collision_slug("a" * 90, normalized_url)
        == "a" * 71 + "-c8c95681"
    )


def test_webarchive_extraction_uses_saved_main_resource(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html="""<html><head><title>Saved title</title>
        <meta property="og:site_name" content="Example Site"></head>
        <body><main><h1>Saved title</h1><h2>Argument</h2>
        <p>This text came from the saved snapshot.</p></main></body></html>""",
    )
    output = tmp_path / "source.md"

    result = load_webarchive_module().extract_webarchive(snapshot, output)

    assert result.url == "https://example.org/page"
    assert result.title == "Saved title"
    assert result.site == "Example Site"
    assert "This text came from the saved snapshot." in output.read_text()
    assert not re.search(r"^#{1,2} ", output.read_text(), re.MULTILINE)


def test_webarchive_rejects_a_credentialed_saved_url(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://reader:secret@example.org/page",
        html="<html><body><p>Saved page.</p></body></html>",
    )

    with pytest.raises(ValueError, match="credential"):
        load_webarchive_module().read_webarchive(snapshot)


def test_webarchive_rejects_non_html_main_resource(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/document",
        html="<html><body><p>Not HTML according to its archive.</p></body></html>",
    )
    archive = plistlib.loads(snapshot.read_bytes())
    archive["WebMainResource"]["WebResourceMIMEType"] = "application/pdf"
    snapshot.write_bytes(plistlib.dumps(archive, fmt=plistlib.FMT_BINARY))

    with pytest.raises(ValueError, match="HTML"):
        load_webarchive_module().read_webarchive(snapshot)


def test_webarchive_extraction_rejects_an_empty_article(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/empty",
        html="<html><head><title>Empty</title></head><body></body></html>",
    )

    with pytest.raises(ValueError, match="extractable"):
        load_webarchive_module().extract_webarchive(snapshot, tmp_path / "source.md")


def test_webarchive_extraction_does_not_clobber_existing_output(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html="<html><body><main><p>Saved article text.</p></main></body></html>",
    )
    output = tmp_path / "source.md"
    output.write_text("existing output\n")

    with pytest.raises(FileExistsError):
        load_webarchive_module().extract_webarchive(snapshot, output)

    assert output.read_text() == "existing output\n"


def test_webarchive_heading_nesting_leaves_fenced_code_unchanged() -> None:
    markdown = "# Main\n## Sub\n```python\n# literal\n## also literal\n```\n###### Deep\n"

    assert load_webarchive_module().nest_markdown_headings(markdown) == (
        "### Main\n#### Sub\n```python\n# literal\n## also literal\n```\n###### Deep\n"
    )
