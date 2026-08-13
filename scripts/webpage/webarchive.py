"""Read saved Safari WebArchives and deterministically derive Markdown."""

from __future__ import annotations

import codecs
import hashlib
import os
import plistlib
import re
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class WebArchiveDocument:
    """The saved main resource and stable metadata from a WebArchive."""

    url: str
    title: str
    site: str
    html: str
    subresource_urls: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResult:
    """The immutable result of publishing extracted Markdown."""

    url: str
    title: str
    site: str
    output_path: Path
    sha256: str
    size: int


def normalize_web_url(raw: str) -> str:
    """Return the sole comparison form for credential-free HTTP(S) URLs."""

    if not isinstance(raw, str) or not raw:
        raise ValueError("web URL must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("web URL must not contain control characters")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("web URL has an invalid port") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("web URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("web URL must not contain credentials")
    if not parsed.hostname:
        raise ValueError("web URL must have a host")

    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = "[{}]".format(host)
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else "{}:{}".format(host, port)
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def collision_slug(base_slug: str, normalized_url: str) -> str:
    """Disambiguate an existing material slug with its URL's stable digest."""

    suffix = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:8]
    prefix = base_slug[: 80 - 1 - len(suffix)].rstrip("-")
    return f"{prefix}-{suffix}"


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_parts: list[str] = []
        self.site = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "meta":
            attributes = {key.lower(): value for key, value in attrs}
            property_value = attributes.get("property")
            if (
                isinstance(property_value, str)
                and property_value.lower() == "og:site_name"
            ):
                self.site = attributes.get("content") or self.site

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("WebArchive {} must be a mapping".format(name))
    return value


def _decode_html(data: bytes, encoding_name: Any) -> str:
    if isinstance(encoding_name, str) and encoding_name:
        try:
            codecs.lookup(encoding_name)
            return data.decode(encoding_name)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")


def _metadata_from_html(html: str, url: str) -> tuple[str, str]:
    parser = _MetadataParser()
    parser.feed(html)
    parser.close()
    title = parser.title or url
    site = " ".join(parser.site.split()) or (urlsplit(url).hostname or "")
    return title, site


def _subresource_urls(root: Mapping[str, Any]) -> tuple[str, ...]:
    resources = root.get("WebSubresources", [])
    if not isinstance(resources, list):
        return ()
    urls: list[str] = []
    for resource in resources:
        if not isinstance(resource, Mapping):
            continue
        raw_url = resource.get("WebResourceURL")
        if not isinstance(raw_url, str):
            continue
        try:
            urls.append(normalize_web_url(raw_url))
        except ValueError:
            continue
    return tuple(urls)


def read_webarchive(path: Path) -> WebArchiveDocument:
    """Decode the saved HTML main resource from a binary WebArchive plist."""

    root = _as_mapping(plistlib.loads(path.read_bytes()), "root")
    main_resource = _as_mapping(root.get("WebMainResource"), "WebMainResource")
    mime_type = main_resource.get("WebResourceMIMEType")
    if (
        not isinstance(mime_type, str)
        or mime_type.split(";", 1)[0].strip().lower() != "text/html"
    ):
        raise ValueError("WebArchive main resource must be HTML")
    data = main_resource.get("WebResourceData")
    if not isinstance(data, bytes) or not data:
        raise ValueError("WebArchive main resource must contain non-empty bytes")
    raw_url = main_resource.get("WebResourceURL")
    if not isinstance(raw_url, str):
        raise ValueError("WebArchive main resource must have a usable URL")
    url = normalize_web_url(raw_url)
    html = _decode_html(data, main_resource.get("WebResourceTextEncodingName"))
    title, site = _metadata_from_html(html, url)
    return WebArchiveDocument(
        url=url,
        title=title,
        site=site,
        html=html,
        subresource_urls=_subresource_urls(root),
    )


def nest_markdown_headings(text: str) -> str:
    """Place extracted headings beneath the canonical document's content section."""

    output: list[str] = []
    fence_char = ""
    fence_len = 0
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence_char:
                fence_char, fence_len = token[0], len(token)
            elif token[0] == fence_char and len(token) >= fence_len:
                fence_char, fence_len = "", 0
            output.append(line)
            continue
        heading = None if fence_char else re.match(r"^(#{1,6})(\s+.+)$", line)
        if heading:
            level = min(6, len(heading.group(1)) + 2)
            line = "#" * level + heading.group(2)
        output.append(line)
    return "\n".join(output).strip() + "\n"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_no_clobber(output: Path, payload: bytes) -> None:
    descriptor, stage_name = tempfile.mkstemp(
        prefix=".{}.stage-".format(output.name), dir=str(output.parent)
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(stage, output)
        _fsync_directory(output.parent)
    finally:
        try:
            stage.unlink()
        except FileNotFoundError:
            pass


def extract_webarchive(snapshot: Path, output: Path) -> ExtractionResult:
    """Extract saved HTML only and publish Markdown without replacement."""

    document = read_webarchive(snapshot)
    from trafilatura import extract

    markdown = extract(document.html, url=document.url, output_format="markdown")
    if not markdown or not markdown.strip():
        raise ValueError("WebArchive has no extractable article text")
    payload = nest_markdown_headings(markdown).encode("utf-8")
    _publish_no_clobber(output, payload)
    return ExtractionResult(
        url=document.url,
        title=document.title,
        site=document.site,
        output_path=output,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )
