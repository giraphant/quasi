from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from hashlib import sha256
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.filterwarnings(
    r"ignore:urllib3 v2 only supports OpenSSL 1\.1\.1\+.*"
)


@pytest.fixture(autouse=True)
def _webpage_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))


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


def load_webpage_module():
    try:
        return import_module("scripts.webpage.webpage")
    except ModuleNotFoundError:
        pytest.fail("Webpage command capability has not been implemented")


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable bits are unavailable")
def test_quasi_webpage_shim_is_publicly_executable_on_posix() -> None:
    shim = Path("bin/quasi-webpage")

    assert shim.is_file()
    assert stat.S_IMODE(shim.stat().st_mode) & 0o111 == 0o111


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

    try:
        result = load_webarchive_module().extract_webarchive(snapshot, output)
    except Exception as exc:  # RED must report the missing publication behavior as an assertion.
        pytest.fail(f"nested Webpage publication failed: {exc}")

    assert result.url == "https://example.org/page"
    assert result.title == "Saved title"
    assert result.site == "Example Site"
    assert "This text came from the saved snapshot." in output.read_text()
    assert not re.search(r"^#{1,2} ", output.read_text(), re.MULTILINE)


def test_webarchive_ignores_valueless_meta_property(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html="""<html><head><title>Saved title</title><meta property></head>
        <body><main><p>This text remains extractable.</p></main></body></html>""",
    )
    output = tmp_path / "source.md"
    capability = load_webarchive_module()

    document = capability.read_webarchive(snapshot)
    result = capability.extract_webarchive(snapshot, output)

    assert document.title == "Saved title"
    assert document.site == "example.org"
    assert result.title == "Saved title"
    assert result.site == "example.org"
    assert "This text remains extractable." in output.read_text()


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


def test_webarchive_extraction_creates_the_missing_nested_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    snapshot = write_webarchive_fixture(
        project,
        url="https://example.org/page",
        html="<html><body><main><p>Fresh nested projection text.</p></main></body></html>",
    )
    output = project / "processing" / "webpages" / "nested-page" / "source.md"

    try:
        result = load_webpage_module().extract(snapshot, output)
    except Exception as exc:  # RED must report missing publication as an assertion.
        pytest.fail(f"nested Webpage publication failed: {exc}")

    assert result["status"] == "complete"
    assert result["output_path"] == str(output)
    assert output.read_text(encoding="utf-8").strip() == "Fresh nested projection text."


def test_webarchive_explicit_replacement_atomically_changes_a_safe_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    snapshot = write_webarchive_fixture(
        project,
        url="https://example.org/page",
        html="<html><body><main><p>Projection from the fresh snapshot.</p></main></body></html>",
    )
    output = project / "processing" / "webpages" / "saved-page" / "source.md"
    output.parent.mkdir(parents=True)
    output.write_text("stale projection\n", encoding="utf-8")
    webpage = load_webpage_module()
    capability = load_webarchive_module()
    real_replace = capability.os.replace
    replacements: list[tuple[Path, Path]] = []

    def observed_replace(source: str | Path, target: str | Path) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(capability.os, "replace", observed_replace)

    try:
        result = webpage.extract(snapshot, output, replace_existing=True)
    except Exception as exc:  # RED must report the missing replacement API as an assertion.
        pytest.fail(f"explicit Webpage replacement failed: {exc}")

    assert output.read_text(encoding="utf-8").strip() == (
        "Projection from the fresh snapshot."
    )
    assert replacements
    assert replacements == [(replacements[0][0], output)]
    assert replacements[0][0].parent == output.parent
    assert result["sha256"] == sha256(output.read_bytes()).hexdigest()


def test_webarchive_heading_nesting_leaves_fenced_code_unchanged() -> None:
    markdown = "# Main\n## Sub\n```python\n# literal\n## also literal\n```\n###### Deep\n"

    assert load_webarchive_module().nest_markdown_headings(markdown) == (
        "### Main\n#### Sub\n```python\n# literal\n## also literal\n```\n###### Deep\n"
    )


def test_capture_publishes_verified_archive_with_capture_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webpage = load_webpage_module()
    output = tmp_path / "snapshot.webarchive"

    def fake_capture(url: str, staging: Path):
        staging.write_bytes(
            webarchive_fixture_bytes(
                url,
                "<html><head><title>Example</title></head><body><main><p>"
                "Saved page text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult(url, "Example", "example.org")

    monkeypatch.setattr(webpage, "run_native_capture", fake_capture)

    result = webpage.capture(
        "https://example.org/",
        "https://example.org/",
        output,
    )

    assert result["schema_version"] == "quasi.webpage.capture/0.1"
    assert result["status"] == "complete"
    assert result["output_path"] == str(output)
    assert result["final_url"] == "https://example.org/"
    assert result["title"] == "Example"
    assert result["site"] == "example.org"
    assert result["write_state"] == "written"
    assert result["size"] == output.stat().st_size
    assert result["sha256"] == sha256(output.read_bytes()).hexdigest()
    captured_at = datetime.fromisoformat(result["captured_at"].replace("Z", "+00:00"))
    assert captured_at.tzinfo == timezone.utc
    assert output.stat().st_mtime == captured_at.timestamp()


def test_capture_returns_saved_archive_metadata_not_divergent_native_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    webpage = load_webpage_module()
    output = project / "vault" / "webpages" / "saved-page" / "snapshot.webarchive"

    def fake_capture(url: str, staging: Path):
        staging.write_bytes(
            webarchive_fixture_bytes(
                url,
                "<html><head><title>Saved archive title</title>"
                '<meta property="og:site_name" content="Saved archive site"></head>'
                "<body><main><p>Saved page text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult(url, "Divergent native title", "Divergent native site")

    monkeypatch.setattr(webpage, "run_native_capture", fake_capture)

    result = webpage.capture("https://example.org/", "https://example.org/", output)

    assert result["status"] == "complete"
    assert result["title"] == "Saved archive title"
    assert result["site"] == "Saved archive site"


def test_capture_final_url_mismatch_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webpage = load_webpage_module()
    output = tmp_path / "snapshot.webarchive"

    def fake_capture(_url: str, staging: Path):
        staging.write_bytes(
            webarchive_fixture_bytes(
                "https://other.example/",
                "<html><body><main><p>Other text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult("https://other.example/", "Other", "Other")

    monkeypatch.setattr(webpage, "run_native_capture", fake_capture)

    result = webpage.capture(
        "https://example.org/",
        "https://example.org/",
        output,
    )

    assert result["status"] == "failed"
    assert result["issue"]["code"] == "webpage.capture_identity_changed"
    assert not output.exists()


def test_capture_never_overwrites_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webpage = load_webpage_module()
    output = tmp_path / "snapshot.webarchive"
    output.write_bytes(b"existing archive")

    def forbidden_capture(_url: str, _staging: Path):
        raise AssertionError("native capture must not run for an existing output")

    monkeypatch.setattr(webpage, "run_native_capture", forbidden_capture)

    result = webpage.capture(
        "https://example.org/",
        "https://example.org/",
        output,
    )

    assert result["status"] == "failed"
    assert result["issue"]["code"] == "webpage.output_exists"
    assert output.read_bytes() == b"existing archive"


def test_extract_command_exposes_saved_webarchive_projection(tmp_path: Path) -> None:
    webpage = load_webpage_module()
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/saved",
        html="<html><head><title>Saved</title></head><body><main><p>"
        "Projection text from the snapshot.</p></main></body></html>",
    )
    output = tmp_path / "source.md"

    result = webpage.extract(snapshot, output)

    assert result == {
        "schema_version": "quasi.webpage.extract/0.1",
        "status": "complete",
        "snapshot_path": str(snapshot),
        "output_path": str(output),
        "final_url": "https://example.org/saved",
        "title": "Saved",
        "site": "example.org",
        "sha256": sha256(output.read_bytes()).hexdigest(),
        "size": output.stat().st_size,
        "write_state": "written",
    }
    assert "Projection text from the snapshot." in output.read_text()


def test_saved_html_metadata_latches_the_first_title_and_site_elements(
    tmp_path: Path,
) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html=(
            "<html><head><title>First title</title><title>Later title</title>"
            '<meta property="og:site_name" content="First site">'
            '<meta property="og:site_name" content="Later site"></head></html>'
        ),
    )

    document = load_webarchive_module().read_webarchive(snapshot)

    assert document.title == "First title"
    assert document.site == "First site"


def test_saved_html_empty_first_metadata_falls_back_without_using_later_elements(
    tmp_path: Path,
) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html=(
            "<html><head><title></title><title>Later title</title>"
            '<meta property="og:site_name" content="">'
            '<meta property="og:site_name" content="Later site"></head></html>'
        ),
    )

    document = load_webarchive_module().read_webarchive(snapshot)

    assert document.title == "https://example.org/page"
    assert document.site == "example.org"


@pytest.mark.parametrize("command", ["capture", "extract"])
@pytest.mark.parametrize("boundary", ["outside", "symlink"])
def test_webpage_writers_reject_outside_or_unsafe_publication_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    boundary: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    webpage = load_webpage_module()
    snapshot = write_webarchive_fixture(
        project,
        url="https://example.org/page",
        html="<html><body><main><p>Safe snapshot input.</p></main></body></html>",
    )
    if boundary == "outside":
        output = external / ("snapshot.webarchive" if command == "capture" else "source.md")
    else:
        route = project / ("vault" if command == "capture" else "processing") / "webpages"
        route.parent.mkdir(parents=True, exist_ok=True)
        route.symlink_to(external, target_is_directory=True)
        (external / "unsafe-page").mkdir()
        output = route / "unsafe-page" / (
            "snapshot.webarchive" if command == "capture" else "source.md"
        )

    if command == "capture":
        def forbidden_capture(_url: str, _staging: Path):
            raise AssertionError("unsafe output must be rejected before native capture")

        monkeypatch.setattr(webpage, "run_native_capture", forbidden_capture)
        result = webpage.capture("https://example.org/", "https://example.org/", output)
    else:
        result = webpage.extract(snapshot, output)

    assert result["status"] == "failed"
    assert not output.exists()


def test_failed_native_compile_preserves_cached_binary_and_uses_a_unique_sibling_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webpage = load_webpage_module()
    source = tmp_path / "webpage_capture.swift"
    source.write_text("source", encoding="utf-8")
    binary = tmp_path / "bin" / "quasi-webpage-webkit"
    binary.parent.mkdir()
    binary.write_bytes(b"known-good-binary")
    binary.chmod(0o755)
    os.utime(binary, (1, 1))
    os.utime(source, (2, 2))
    compile_targets: list[Path] = []

    def failed_compile(arguments: list[str], **_kwargs: object):
        target = Path(arguments[arguments.index("-o") + 1])
        compile_targets.append(target)
        target.write_bytes(b"partial")
        return SimpleNamespace(returncode=1, stderr="compiler failed")

    monkeypatch.setattr(webpage.sys, "platform", "darwin")
    monkeypatch.setattr(webpage, "_macos_11_or_newer", lambda: True)
    monkeypatch.setattr(webpage, "_native_source", lambda: source)
    monkeypatch.setattr(webpage, "_native_binary", lambda: binary)
    monkeypatch.setattr(webpage.shutil, "which", lambda _name: "/usr/bin/swiftc")
    monkeypatch.setattr(webpage.subprocess, "run", failed_compile)

    with pytest.raises(webpage.WebpageCommandError, match="compiler failed"):
        webpage._ensure_native_binary()

    assert binary.read_bytes() == b"known-good-binary"
    assert stat.S_IMODE(binary.stat().st_mode) & 0o111
    assert len(compile_targets) == 1
    assert compile_targets[0] != binary
    assert compile_targets[0].parent == binary.parent
    assert not compile_targets[0].exists()


def test_successful_native_compile_atomically_publishes_a_complete_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webpage = load_webpage_module()
    source = tmp_path / "webpage_capture.swift"
    source.write_text("source", encoding="utf-8")
    binary = tmp_path / "bin" / "quasi-webpage-webkit"
    replacements: list[tuple[Path, Path]] = []
    real_replace = webpage.os.replace

    def successful_compile(arguments: list[str], **_kwargs: object):
        target = Path(arguments[arguments.index("-o") + 1])
        target.write_bytes(b"complete-binary")
        target.chmod(0o755)
        return SimpleNamespace(returncode=0, stderr="")

    def observed_replace(source_path: str | Path, target_path: str | Path) -> None:
        replacements.append((Path(source_path), Path(target_path)))
        real_replace(source_path, target_path)

    monkeypatch.setattr(webpage.sys, "platform", "darwin")
    monkeypatch.setattr(webpage, "_macos_11_or_newer", lambda: True)
    monkeypatch.setattr(webpage, "_native_source", lambda: source)
    monkeypatch.setattr(webpage, "_native_binary", lambda: binary)
    monkeypatch.setattr(webpage.shutil, "which", lambda _name: "/usr/bin/swiftc")
    monkeypatch.setattr(webpage.subprocess, "run", successful_compile)
    monkeypatch.setattr(webpage.os, "replace", observed_replace)

    result = webpage._ensure_native_binary()

    assert result == binary
    assert binary.read_bytes() == b"complete-binary"
    assert stat.S_IMODE(binary.stat().st_mode) & 0o111
    assert replacements
    assert replacements == [(replacements[0][0], binary)]
    assert replacements[0][0].parent == binary.parent


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="requires macOS WebKit and swiftc",
)
def test_command_capture_smoke_preserves_loopback_subresources(tmp_path: Path) -> None:
    webpage = load_webpage_module()
    (tmp_path / "fixture.html").write_text(
        "<html><head><title>Local fixture</title><link rel=\"stylesheet\" "
        "href=\"/fixture.css\"></head><body><main><p>Local fixture content"
        "</p><img src=\"/pixel.gif\"></main></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "fixture.css").write_text("body { color: black; }", encoding="utf-8")
    (tmp_path / "pixel.gif").write_bytes(
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;"
    )

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args: QuietHandler(*args, directory=str(tmp_path)),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/fixture.html"
        inspected = webpage.inspect(url)
        assert inspected["status"] == "complete"
        captured = webpage.capture(url, inspected["final_url"], tmp_path / "snapshot.webarchive")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert captured["status"] == "complete"
    archive = load_webarchive_module().read_webarchive(tmp_path / "snapshot.webarchive")
    assert archive.url == inspected["final_url"]
    assert "Local fixture content" in archive.html
    assert any(url.endswith("/fixture.css") for url in archive.subresource_urls)


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="requires macOS WebKit and swiftc",
)
def test_native_timeout_wins_when_metadata_never_returns(tmp_path: Path) -> None:
    binary = tmp_path / "webpage-timeout-test"
    source = Path("scripts/webpage/webpage_capture.swift")
    subprocess.run(
        [
            shutil.which("swiftc"),
            "-D",
            "QUASI_WEBPAGE_TESTING",
            "-O",
            "-parse-as-library",
            "-framework",
            "WebKit",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "fixture.html").write_text(
        "<html><head><title>Timeout fixture</title></head><body>ready</body></html>",
        encoding="utf-8",
    )

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args: QuietHandler(*args, directory=str(tmp_path)),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        environment = {
            **os.environ,
            "QUASI_WEBPAGE_TEST_STALL": "metadata",
            "QUASI_WEBPAGE_TEST_TIMEOUT_MS": "100",
        }
        started = time.monotonic()
        completed = subprocess.run(
            [str(binary), "inspect", f"http://127.0.0.1:{server.server_port}/fixture.html"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert elapsed < 3
    assert completed.returncode != 0
    assert json.loads(completed.stdout) == {
        "status": "failed",
        "code": "webpage.capture_timeout",
        "message": "page capture exceeded 60 seconds",
    }


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="requires macOS WebKit and swiftc",
)
def test_native_terminal_race_emits_exactly_one_terminal_json(tmp_path: Path) -> None:
    binary = tmp_path / "webpage-terminal-race-test"
    subprocess.run(
        [
            shutil.which("swiftc"),
            "-D",
            "QUASI_WEBPAGE_TESTING",
            "-O",
            "-parse-as-library",
            "-framework",
            "WebKit",
            "scripts/webpage/webpage_capture.swift",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    completed = subprocess.run(
        [str(binary), "terminal-race"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )

    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    if payload["status"] == "complete":
        assert completed.returncode == 0
        assert payload == {
            "status": "complete",
            "final_url": "https://example.org/",
            "title": "Race success",
            "site": "example.org",
        }
    else:
        assert completed.returncode == 1
        assert payload == {
            "status": "failed",
            "code": "webpage.capture_timeout",
            "message": "page capture exceeded 60 seconds",
        }
