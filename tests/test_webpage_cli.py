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

from workflow_test_support import run_workflow_export

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


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.chronicle.com/article/the-intellectual-war-on-science/",
        "HTTPS://Example.COM:443",
        "http://Example.COM:80/a?q=2#frag",
        "https://example.org",
        "https://example.org:8443/x?q=1&r=2",
        "https://example.org:/x",
        "https://[2001:db8::1]:8080/x",
        "https://example.org/a/../b",
        "https://example.org/a b",
        "https://example.org/文章",
        "https://例え.jp/a",
        "https://example.org/x?",
    ],
)
def test_web_url_normalizers_agree_across_python_and_workflow(raw: str) -> None:
    """One accepted URL must carry one comparison form on both sides."""

    assert run_workflow_export(
        "scripts/workflows/contracts/webpage.mts", "normalizeWebUrl", raw
    ) == load_webarchive_module().normalize_web_url(raw)


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

    def fake_capture(url: str, staging: Path, **_kwargs):
        staging.write_bytes(
            webarchive_fixture_bytes(
                url,
                "<html><head><title>Example</title></head><body><main><p>"
                "Saved page text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult(url, "Example", "example.org")

    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: Path("/unused"))
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

    def fake_capture(url: str, staging: Path, **_kwargs):
        staging.write_bytes(
            webarchive_fixture_bytes(
                url,
                "<html><head><title>Saved archive title</title>"
                '<meta property="og:site_name" content="Saved archive site"></head>'
                "<body><main><p>Saved page text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult(url, "Divergent native title", "Divergent native site")

    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: Path("/unused"))
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

    def fake_capture(_url: str, staging: Path, **_kwargs):
        staging.write_bytes(
            webarchive_fixture_bytes(
                "https://other.example/",
                "<html><body><main><p>Other text.</p></main></body></html>",
            )
        )
        return webpage.NativeResult("https://other.example/", "Other", "Other")

    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: Path("/unused"))
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


def stub_compiler(tmp_path, monkeypatch):
    webpage = load_webpage_module()
    source = tmp_path / "capture.swift"
    source.write_text("version one")
    compiler = tmp_path / "swiftc"
    control = tmp_path / "compiler-mode"
    control.write_text("ok")
    version = tmp_path / "tool-version"
    version.write_text("Swift fixture 1")
    calls = tmp_path / "compile-calls"
    compiler.write_text(f"#!{sys.executable}\n" +
        "import sys, os\nfrom pathlib import Path\n" +
        f"control=Path({str(control)!r}); version=Path({str(version)!r}); calls=Path({str(calls)!r})\n" +
        "if '--version' in sys.argv: print(version.read_text()); sys.exit(0)\n" +
        "target=Path(sys.argv[sys.argv.index('-o')+1]); source=Path(sys.argv[sys.argv.index('-o')-1])\n" +
        "with calls.open('a') as stream: stream.write(str(target)+'\\n')\n" +
        "target.write_bytes(source.read_bytes()); target.chmod(0o755)\n" +
        "sys.exit(1 if control.read_text() == 'fail' else 0)\n")
    compiler.chmod(0o755)
    monkeypatch.setattr(webpage.sys, "platform", "darwin")
    monkeypatch.setattr(webpage, "_macos_11_or_newer", lambda: True)
    monkeypatch.setattr(webpage, "_native_source", lambda: source)
    monkeypatch.setattr(webpage, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(webpage.shutil, "which", lambda _name: str(compiler))
    return webpage, source, compiler, control, version, calls


def test_failed_native_compile_preserves_cached_binary_and_uses_a_unique_sibling_stage(tmp_path, monkeypatch):
    webpage, source, _, control, _, calls = stub_compiler(tmp_path, monkeypatch)
    old = webpage._ensure_native_binary()
    source.write_text("bad source"); control.write_text("fail")
    with pytest.raises(webpage.WebpageCommandError, match="compiler failed"):
        webpage._ensure_native_binary()
    assert old.read_bytes() == b"version one"
    targets = [Path(line) for line in calls.read_text().splitlines()]
    assert len(targets) == 2 and targets[0] != targets[1]
    assert all(not target.exists() for target in targets)
    assert not list(old.parent.glob('.compile-*'))


def test_successful_native_compile_atomically_publishes_a_complete_executable(tmp_path, monkeypatch):
    webpage, _, _, _, _, calls = stub_compiler(tmp_path, monkeypatch)
    binary = webpage._ensure_native_binary()
    assert binary.read_bytes() == b"version one" and os.access(binary, os.X_OK)
    assert Path(calls.read_text().strip()).parent.parent == binary.parent
    assert not list(binary.parent.glob('.compile-*'))


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
@pytest.mark.parametrize("stall,native_ms,local_ms,expected_code", [
    ("metadata", 1000, 2000, "webpage.capture_timeout"),
    ("fingerprint", 1000, 2000, "webpage.capture_timeout"),
    ("fingerprint", 2000, 100, "webpage.stabilization_failed"),
    ("after-first-fingerprint", 2000, 300, "webpage.stabilization_failed"),
    ("changing", 2000, 900, "complete"),
])
def test_native_timeout_wins_when_metadata_never_returns(
    tmp_path: Path, stall: str, native_ms: int, local_ms: int, expected_code: str,
) -> None:
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
        "<html><head><title>Timeout fixture</title></head><body>ready"
        + ("<script>setInterval(() => document.body.append('x'), 20)</script>" if stall == "changing" else "")
        + "</body></html>",
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
            "QUASI_WEBPAGE_TEST_STALL": stall,
            "QUASI_WEBPAGE_TEST_TIMEOUT_MS": str(native_ms),
            "QUASI_WEBPAGE_TEST_STABILIZE_MIN_MS": "0",
            "QUASI_WEBPAGE_TEST_STABILIZE_QUIET_MS": "600" if stall in ("after-first-fingerprint", "changing") else "0",
            "QUASI_WEBPAGE_TEST_STABILIZE_MAX_MS": str(local_ms),
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
    payload = json.loads(completed.stdout)
    if expected_code == "complete":
        assert completed.returncode == 0
        assert payload["status"] == "complete"
        assert elapsed >= local_ms / 1000
        return
    assert completed.returncode != 0
    assert payload["status"] == "failed"
    assert payload["code"] == expected_code
    if expected_code == "webpage.capture_timeout":
        assert payload["message"] == "page capture exceeded 60 seconds"



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


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="requires macOS WebKit and swiftc",
)
@pytest.mark.parametrize("transport", ["fetch", "xhr", "stream", "tampered-stream", "reload", "fragment", "javascript", "same-url-reload", "redirect", "slow-stream"])
def test_delayed_dom_is_in_main_resource_and_prepared_source(tmp_path, monkeypatch, transport):
    from webpage_test_support import delayed_webpage

    webpage = load_webpage_module()
    binary = tmp_path / "fresh-webkit"
    subprocess.run(
        [shutil.which("swiftc"), "-target", os.uname().machine + "-apple-macos11",
         "-O", "-parse-as-library", "-framework", "WebKit",
         str(webpage._native_source()), "-o", str(binary)],
        check=True, capture_output=True, text=True, timeout=300,
    )
    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: binary)
    # Production compilation must ignore test timing overrides.
    monkeypatch.setenv("QUASI_WEBPAGE_TEST_STABILIZE_MIN_MS", "0")
    monkeypatch.setenv("QUASI_WEBPAGE_TEST_STABILIZE_MAX_MS", "0")
    snapshot = tmp_path / "vault/webpages/hydration/snapshot.webarchive"
    source = tmp_path / "processing/webpages/hydration/source.md"
    with delayed_webpage(transport) as (url, sentinel):
        if transport == "slow-stream":
            started = time.monotonic()
            captured = webpage.capture(url, url, snapshot)
            assert captured["status"] == "failed"
            assert captured["issue"]["code"] == "webpage.stabilization_failed"
            assert time.monotonic() - started < 6.3
            assert not snapshot.exists() and not list(snapshot.parent.glob(".*.capture-*"))
            return
        inspected = webpage.inspect(url)
        assert inspected["status"] == "complete", inspected
        final_url = url + "?second" if transport in ("reload", "redirect") else url
        assert inspected["final_url"] == final_url
        captured = webpage.capture(url, inspected["final_url"], snapshot)
        assert captured["status"] == "complete", captured
        assert captured["final_url"] == final_url
        extracted = webpage.extract(snapshot, source)
        assert extracted["status"] == "complete", extracted
        archive = load_webarchive_module().read_webarchive(snapshot)
        assert archive.url == extracted["final_url"] == final_url
        from test_webpage_host_e2e import validate_cli_receipt
        for name, receipt in (("inspect", inspected), ("capture", captured), ("extract", extracted)):
            validate_cli_receipt(receipt, name, {"status": "complete", "final_url": final_url})
        assert sentinel in archive.html
        assert sentinel in source.read_text()
        if transport == "fragment":
            # CLI URL normalization drops fragments; prove the action occurred
            # through serialized DOM, not a string in the fixture's script.
            from bs4 import BeautifulSoup
            assert BeautifulSoup(archive.html, "html.parser").find("main")["data-fragment-observed"] == "#hydrating"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("leader_exits", [False, True])
def test_native_parent_watchdog_kills_helper_and_child(tmp_path, monkeypatch, leader_exits):
    import signal

    webpage = load_webpage_module()
    helper = tmp_path / "hanging-helper"
    pidfile = tmp_path / "pids.json"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, sys, time, json\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = os.fork()\n"
        f"if child and {leader_exits!r}: signal.signal(signal.SIGTERM, signal.SIG_DFL)\n"
        f"if not child and {leader_exits!r}: os.close(1); os.close(2)\n"
        "if child:\n"
        f" Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child]))\n"
        " Path(sys.argv[3]).write_text('partial snapshot')\n"
        "while True: time.sleep(10)\n"
    )
    helper.chmod(0o755)
    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: helper)
    monkeypatch.setattr(webpage, "NATIVE_PARENT_TIMEOUT_SECONDS", 0.7)
    monkeypatch.setattr(webpage, "NATIVE_TERMINATION_GRACE_SECONDS", 0.15)
    # Linux CI may have a PID 1 that does not reap orphans. Adopt and reap the
    # grandchild ourselves there; macOS launchd reaps it normally.
    libc = None
    previous = None
    if sys.platform == "linux":
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
        assert libc.prctl(36, 1, 0, 0, 0) == 0
    pids = []
    try:
        output = tmp_path / "vault/webpages/hang/snapshot.webarchive"
        started = time.monotonic()
        receipt = webpage.capture("https://example.org/", "https://example.org/", output)
        elapsed = time.monotonic() - started
        pids = json.loads(pidfile.read_text())
        assert elapsed < 3
        assert elapsed >= 0.7
        if not leader_exits:
            assert elapsed >= 0.85  # Both processes ignored TERM; grace expired.
        assert receipt["status"] == "failed"
        assert receipt["issue"]["code"] == "webpage.capture_timeout"
        assert not output.exists()
        assert not list(output.parent.glob(".*.capture-*"))
        deadline = time.monotonic() + 3
        for pid in pids:
            while True:
                if libc is not None:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                assert time.monotonic() < deadline, f"process {pid} survived watchdog"
                time.sleep(0.02)
    finally:
        if not pids and pidfile.exists():
            pids = json.loads(pidfile.read_text())
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if libc is not None:
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
        if libc is not None:
            assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def test_host_tool_evidence_reads_structured_calls_and_deduplicates_ids(tmp_path):
    """Deterministic parser check; no host, credential or loopback access."""
    from test_webpage_host_e2e import records, tool_calls

    call = {"type": "tool_use", "id": "capture-1", "name": "Bash",
            "input": {"command": "quasi-webpage capture fixture"}}
    row = {"message": {"content": [{"type": "text", "text": "Bash capture prose"}, call]}}
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(value) for value in [row, row, {"type": "progress"}]))
    assert tool_calls(records(path), "Bash") == [call["input"]]
    assert tool_calls(records(path), "Workflow") == []


def test_host_malformed_evidence_does_not_echo_contents(tmp_path):
    from test_webpage_host_e2e import records

    path = tmp_path / "broken.jsonl"
    path.write_text("PRIVATE_FIXTURE_VALUE is not JSON")
    with pytest.raises(pytest.fail.Exception) as error:
        records(path)
    assert "PRIVATE_FIXTURE_VALUE" not in str(error.value)


def test_native_cache_uses_source_content_not_installed_mtime(tmp_path, monkeypatch):
    webpage, source, compiler, control, version, calls = stub_compiler(tmp_path, monkeypatch)
    old = webpage._ensure_native_binary()
    os.utime(old, (2_000_000_000, 2_000_000_000))
    source.write_text("version two"); os.utime(source, (1, 1))
    new = webpage._ensure_native_binary()
    assert old != new and webpage._ensure_native_binary() == new
    assert len(calls.read_text().splitlines()) == 2
    version.write_text("Swift fixture 2")
    tool_changed = webpage._ensure_native_binary()
    assert tool_changed not in (old, new)
    monkeypatch.setattr(webpage.platform, "machine", lambda: "other-arch")
    arch_changed = webpage._ensure_native_binary()
    assert arch_changed not in (old, new, tool_changed)
    assert webpage._ensure_native_binary() == arch_changed
    monkeypatch.setattr(webpage, "NATIVE_COMPILER_FLAGS", (*webpage.NATIVE_COMPILER_FLAGS, "-g"))
    recipe_changed = webpage._ensure_native_binary()
    assert recipe_changed != arch_changed and webpage._ensure_native_binary() == recipe_changed
    control.write_text("fail"); source.write_text("broken")
    with pytest.raises(webpage.WebpageCommandError): webpage._ensure_native_binary()
    assert old.read_bytes() == b"version one" and new.read_bytes() == b"version two"
    assert not list(old.parent.glob('.compile-*'))


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX sessions")
def test_watchdog_bounds_drain_when_escaped_child_holds_pipes(tmp_path, monkeypatch):
    import signal
    webpage = load_webpage_module()
    helper = tmp_path / "escaped-helper"
    pidfile = tmp_path / "escaped-pids.json"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, sys, time, json\nfrom pathlib import Path\n"
        "ready_read, ready_write = os.pipe()\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        " os.close(ready_read)\n os.setsid()\n"
        " signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        " os.write(ready_write, b'1')\n os.close(ready_write)\n"
        " time.sleep(30)\n os._exit(0)\n"
        "os.close(ready_write)\nos.read(ready_read, 1)\nos.close(ready_read)\n"
        f"Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child]))\n"
        "Path(sys.argv[3]).write_text('partial staging')\n"
        "time.sleep(30)\n"
    )
    helper.chmod(0o755)
    monkeypatch.setattr(webpage, "_ensure_native_binary", lambda: helper)
    monkeypatch.setattr(webpage, "NATIVE_PARENT_TIMEOUT_SECONDS", 0.7)
    monkeypatch.setattr(webpage, "NATIVE_TERMINATION_GRACE_SECONDS", 0.15)
    monkeypatch.setattr(webpage, "NATIVE_DRAIN_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(webpage, "NATIVE_REAP_TIMEOUT_SECONDS", 0.15)
    # Adopt/reap an escaped orphan on Linux CI as well as killing it in finally.
    libc = None
    if sys.platform == "linux":
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
        assert libc.prctl(36, 1, 0, 0, 0) == 0
    try:
        output = tmp_path / "vault/webpages/escape/snapshot.webarchive"
        started = time.monotonic()
        receipt = webpage.capture("https://example.org/", "https://example.org/", output)
        elapsed = time.monotonic() - started
        assert elapsed < 2.5
        assert receipt["status"] == "failed"
        assert receipt["issue"]["code"] == "webpage.capture_timeout"
        leader, child = json.loads(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(leader, 0)
        os.kill(child, 0)  # Deliberately outside the helper group; our finally owns it.
        assert not output.exists()
        assert not list(output.parent.glob(".*.capture-*"))
    finally:
        if pidfile.exists():
            for pid in json.loads(pidfile.read_text()):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if libc is not None:
                        try:
                            os.waitpid(pid, os.WNOHANG)
                        except ChildProcessError:
                            pass
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Escaped test process did not terminate")
        if libc is not None:
            assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def test_network_tracker_accounts_for_pending_and_settles_once():
    source = Path("scripts/webpage/webpage_capture.swift").read_text()
    tracker = re.search(r'static let networkTracker = """\n(.*?)\n    """', source, re.S).group(1)
    tracker = tracker.replace("__HANDLER__", "test").replace("__TOKEN__", "token")
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const requestIds = [];
for (let document = 0; document < 2; document++) {
  const realm = {Response, ReadableStream, ReadableStreamDefaultReader, EventTarget, crypto,
    XMLHttpRequest: class extends EventTarget { send() {} },
    fetch: () => new Promise(() => {}),
    webkit: {messageHandlers: {test: {postMessage(m) {
      if (m.action === 'start') requestIds.push(m.id);
    }}}}};
  realm.window = realm;
  vm.runInNewContext(JSON.parse(process.argv[1]) + '\nfetch();', realm);
}
assert.equal(requestIds.length, 2);
assert.notEqual(requestIds[0], requestIds[1]); // First request in two fresh documents.
globalThis.window = globalThis;
const pending = new Set(); let starts = 0, settles = 0;
window.webkit = {messageHandlers: {test: {postMessage(m) {
  if (m.action === 'start') { starts++; pending.add(m.id); }
  if (m.action === 'settle') { settles++; assert(pending.delete(m.id)); }
}}}};
let mode = 'pending', resolveFetch;
window.fetch = () => {
  if (mode === 'throw') throw new Error('sync');
  if (mode === 'reject') return Promise.reject(new Error('reject'));
  return new Promise(resolve => { resolveFetch = resolve; });
};
globalThis.EventTarget = class {
  listeners = new Map();
  addEventListener(_name, callback, options) { this.listeners.set(callback, options); }
  removeEventListener(_name, callback) { this.listeners.delete(callback); }
};
class XHR extends EventTarget {
  send() { if (mode === 'throw') throw new Error('sync'); }
  end(trusted = true) {
    for (const [callback, options] of [...this.listeners]) {
      if (options && options.once) this.listeners.delete(callback);
      callback({isTrusted: trusted});
    }
  }
}
globalThis.XMLHttpRequest = XHR;
eval(JSON.parse(process.argv[1]));
(async () => {
  let controller;
  const response = new Response(new ReadableStream({start(c) { controller = c; }}));
  const request = fetch(); assert.equal(pending.size, 1);
  resolveFetch(response); assert.equal(await request, response);
  assert.equal(pending.size, 1); // Headers are not body completion.
  controller.enqueue(new Uint8Array([1])); controller.close();
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(pending.size, 0);
  const brokenRequest = fetch();
  resolveFetch(new Response(new ReadableStream({start(c) { c.error(new Error('body rejected')); }})));
  await brokenRequest;
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(pending.size, 0);
  const invalidResponse = fetch(); resolveFetch({}); await invalidResponse;
  assert.equal(pending.size, 0); // Synchronous clone failure also settles once.
  mode = 'throw'; assert.throws(() => fetch());
  mode = 'reject'; await assert.rejects(fetch());
  mode = 'pending'; const xhr = new XHR(); xhr.send();
  assert.equal(pending.size, 1); xhr.end(false); assert.equal(pending.size, 1);
  xhr.end(); xhr.end();
  mode = 'throw'; assert.throws(() => xhr.send()); xhr.end();
  assert.throws(() => XMLHttpRequest.prototype.send.call({}));
  assert.equal(pending.size, 0); assert.equal(starts, settles);
  const locked = fetch; window.fetch = () => {}; assert.equal(fetch, locked);
  const send = XHR.prototype.send; XHR.prototype.send = () => {}; assert.equal(XHR.prototype.send, send);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(["node", "-e", harness, json.dumps(tracker)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit, GeneratorExit, RuntimeError])
def test_native_baseexception_always_cleans_and_propagates(tmp_path, monkeypatch, exception):
    webpage = load_webpage_module()
    stage = tmp_path / '.snapshot.capture-test'
    stage.write_text('partial')
    cleaned = []
    class Process:
        def communicate(self, **_kwargs):
            raise exception()
    process = Process()
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/fake/helper'))
    monkeypatch.setattr(webpage.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(webpage, '_stop_native', lambda child: cleaned.append(child))
    with pytest.raises(exception):
        webpage._run_native('capture', 'https://example.org', stage)
    assert cleaned == [process]
    assert not stage.exists()


@pytest.mark.skipif(sys.platform != 'darwin' or shutil.which('swiftc') is None,
                    reason='requires macOS WebKit and swiftc')
@pytest.mark.parametrize('termination', ['SIGTERM', 'SIGKILL', 'SIGINT', 'SIGHUP'])
def test_native_helper_dies_with_cancelled_or_killed_parent(tmp_path, termination):
    import signal
    from webpage_test_support import delayed_webpage
    binary = tmp_path / 'stall-webkit'
    subprocess.run([shutil.which('swiftc'), '-D', 'QUASI_WEBPAGE_TESTING',
                    '-parse-as-library', '-framework', 'WebKit',
                    'scripts/webpage/webpage_capture.swift', '-o', str(binary)],
                   check=True, capture_output=True, text=True, timeout=300)
    pidfile = tmp_path / 'helper.pid'
    output = tmp_path / 'snapshot.webarchive'
    wrapper = tmp_path / 'wrapper.py'
    wrapper.write_text('''import sys, os
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.webpage import webpage
webpage._ensure_native_binary = lambda: Path(sys.argv[2])
original = webpage.subprocess.Popen
def start(*args, **kwargs):
    child = original(*args, **kwargs)
    Path(sys.argv[3]).write_text(str(child.pid))
    return child
webpage.subprocess.Popen = start
webpage.capture(sys.argv[4], sys.argv[4], Path(sys.argv[5]))
''')
    process = None
    child_pid = None
    try:
        with delayed_webpage() as (url, _sentinel):
            process = subprocess.Popen([sys.executable, str(wrapper), str(Path.cwd()),
                                        str(binary), str(pidfile), url, str(output)],
                                       env={**os.environ, 'QUASI_WEBPAGE_TEST_STALL': 'parent',
                                            'QUASI_WEBPAGE_TEST_STABILIZE_MIN_MS': '0',
                                            'QUASI_WEBPAGE_TEST_STABILIZE_QUIET_MS': '0',
                                            'QUASI_WEBPAGE_TEST_STABILIZE_MAX_MS': '20'},
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 8
            while not pidfile.exists():
                assert process.poll() is None
                assert time.monotonic() < deadline
                time.sleep(.02)
            child_pid = int(pidfile.read_text())
            # Native test-build writes staging only after arming the watcher.
            while not list(tmp_path.glob('.*capture-*')):
                assert process.poll() is None
                assert time.monotonic() < deadline
                time.sleep(.02)
            started = time.monotonic()
            os.kill(process.pid, getattr(signal, termination))
            process.wait(timeout=5)
            assert process.returncode == -getattr(signal, termination)
            while True:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                assert time.monotonic() - started < 5, 'native helper survived parent death'
                time.sleep(.02)
            assert not output.exists()
            assert not list(tmp_path.glob('.*capture-*'))
    finally:
        if process and process.poll() is None:
            process.kill(); process.wait(timeout=5)
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swiftc") is None,
                    reason="requires macOS WebKit and swiftc")
def test_swift_network_state_rejects_queued_previous_navigation_messages(tmp_path):
    binary = tmp_path / "network-protocol"
    subprocess.run([shutil.which("swiftc"), "-D", "QUASI_WEBPAGE_TESTING", "-target",
                    os.uname().machine + "-apple-macos11", "-parse-as-library", "-framework", "WebKit",
                    "scripts/webpage/webpage_capture.swift", "-o", str(binary)],
                   check=True, capture_output=True, text=True, timeout=300)
    result = subprocess.run([str(binary), "network-protocol"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "network protocol PASS"


@pytest.mark.parametrize('defect', ['missing_status', 'unknown_status', 'extra', 'missing_title',
    'title_type', 'site_type', 'url_type', 'url_scheme', 'staging_path', 'missing_staging'])
def test_native_success_protocol_is_closed_before_publish(tmp_path, monkeypatch, defect):
    webpage = load_webpage_module()
    archive = webarchive_fixture_bytes('https://example.org/', '<html><body>complete</body></html>')
    helper = tmp_path / 'fake-native'
    edits = {
        'missing_status': "payload.pop('status')", 'unknown_status': "payload['status']='unknown'",
        'extra': "payload['PRIVATE_EXTRA']='private'", 'missing_title': "payload.pop('title')",
        'title_type': "payload['title']=12", 'site_type': "payload['site']=None",
        'url_type': "payload['final_url']=[]", 'url_scheme': "payload['final_url']='file:///secret'",
        'staging_path': "payload['staging_path']='/wrong'", 'missing_staging': "payload.pop('staging_path')",
    }
    helper.write_text(f'#!{sys.executable}\nimport os,sys,json\n'
        + f'os.write(int(sys.argv[4]), {archive!r})\n'
        + "payload=dict(status='complete',final_url='https://example.org/',title='',site='',staging_path=sys.argv[3])\n"
        + edits[defect] + '\nprint(json.dumps(payload))\n')
    helper.chmod(0o755)
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: helper)
    output = tmp_path / 'snapshot.webarchive'
    result = webpage.capture('https://example.org/', 'https://example.org/', output)
    assert result['issue']['code'] == 'webpage.capture_failed'
    assert not output.exists() and not list(tmp_path.glob('.*capture-*'))


def test_capture_owned_fd_does_not_follow_substituted_symlink(tmp_path, monkeypatch):
    webpage = load_webpage_module()
    outside = tmp_path / 'outside'; outside.write_text('untouched')
    project = tmp_path / 'project'; project.mkdir()
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    def attack(url, staging, *, descriptor, **_kwargs):
        staging.unlink(); staging.symlink_to(outside)
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe fd</body></html>'))
        return webpage.NativeResult(url, '', '')
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    monkeypatch.setattr(webpage, 'run_native_capture', attack)
    result = webpage.capture('https://example.org/', 'https://example.org/', project / 'snapshot.webarchive')
    assert result['issue']['code'] == 'webpage.capture_failed'
    assert outside.read_text() == 'untouched'
    assert not (project / 'snapshot.webarchive').exists()
    assert not list(project.glob('.*capture-*'))


@pytest.mark.parametrize('phase', ['precommit_hash', 'postcommit_fsync', 'postcommit_verify', 'no_postcommit_readback'])
def test_capture_transaction_failure_boundary_and_no_replay(tmp_path, monkeypatch, phase):
    webpage = load_webpage_module(); count = []
    output = tmp_path / 'snapshot.webarchive'
    def writer(url, staging, *, descriptor, **_kwargs):
        count.append(1)
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>data</body></html>'))
        return webpage.NativeResult(url, '', '')
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    def fail(*_args, **_kwargs): raise OSError('injected failure')
    if phase == 'precommit_hash': monkeypatch.setattr(webpage.hashlib, 'sha256', fail)
    elif phase == 'postcommit_fsync':
        original_fsync = os.fsync
        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode): fail()
            return original_fsync(fd)
        monkeypatch.setattr(os, 'fsync', fsync)
    elif phase == 'postcommit_verify':
        original = os.stat
        seen = []
        def checked_stat(path, *a, **k):
            info = original(path, *a, **k)
            if path == output.name and k.get('dir_fd') is not None:
                seen.append(1)
                if len(seen) > 1: raise OSError('post-link verification')
            return info
        monkeypatch.setattr(os, 'stat', checked_stat)
    else:
        original = Path.read_bytes
        def read(path):
            if path == output: raise OSError('must not read published artifact')
            return original(path)
        monkeypatch.setattr(Path, 'read_bytes', read)
    result = webpage.capture('https://example.org/', 'https://example.org/', output)
    assert count == [1] and not list(tmp_path.glob('.*capture-*'))
    if phase == 'precommit_hash':
        assert result['issue']['code'] == 'webpage.capture_failed' and not output.exists()
    elif phase.startswith('postcommit'):
        assert result['issue']['code'] == 'webpage.capture_outcome_unknown' and output.exists()
    else:
        assert result['status'] == 'complete'
    if phase != 'precommit_hash':
        if phase == 'postcommit_verify': monkeypatch.setattr(os, 'stat', original)
        retry = webpage.capture('https://example.org/', 'https://example.org/', output)
        assert retry['issue']['code'] == 'webpage.output_exists' and count == [1]


@pytest.mark.parametrize('sig', ['SIGTERM', 'SIGKILL'])
def test_compiler_supervisor_survives_parent_cancellation(tmp_path, sig):
    import signal
    source = tmp_path / 'source.swift'; source.write_text('stub source')
    compiler = tmp_path / 'swiftc'; pidfile = tmp_path / 'compiler.pid'
    compiler.write_text(f'#!{sys.executable}\nimport os,sys,time,signal\nfrom pathlib import Path\n'
        + "if '--version' in sys.argv: print('Swift fixture'); sys.exit(0)\n"
        + f"Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
        + "signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n")
    compiler.chmod(0o755)
    script = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.webpage import webpage
webpage.sys.platform='darwin'
webpage._macos_11_or_newer=lambda: True
webpage.shutil.which=lambda _:sys.argv[2]
webpage._native_source=lambda:Path(sys.argv[3])
webpage._data_dir=lambda:Path(sys.argv[4])
webpage._ensure_native_binary()
"""
    process = subprocess.Popen([sys.executable, '-c', script, str(Path.cwd()), str(compiler), str(source), str(tmp_path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child = None
    try:
        deadline = time.monotonic() + 8
        while not pidfile.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        child = int(pidfile.read_text())
        os.kill(process.pid, getattr(signal, sig)); process.wait(timeout=5)
        assert process.returncode == -getattr(signal, sig)
        deadline = time.monotonic() + 4
        while True:
            try: os.kill(child, 0)
            except ProcessLookupError: break
            assert time.monotonic() < deadline
            time.sleep(.02)
        while list((tmp_path / 'bin').glob('.compile-*')):
            assert time.monotonic() < deadline; time.sleep(.02)
        assert not list((tmp_path / 'bin').glob('quasi-webpage-webkit-*'))
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=5)
        if child:
            try: os.kill(child, signal.SIGKILL)
            except ProcessLookupError: pass


@pytest.mark.parametrize('postcommit', [False, True, 'allocation'])
def test_capture_signal_covers_validation_and_commit(tmp_path, postcommit):
    import signal
    output = tmp_path / 'snapshot.webarchive'
    script = """import os,sys,signal,plistlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts.webpage import webpage
url='https://example.org/'
def write(url, stage, *, descriptor, **_kwargs):
    data=plistlib.dumps({'WebMainResource':{'WebResourceURL':url,'WebResourceMIMEType':'text/html','WebResourceTextEncodingName':'UTF-8','WebResourceData':b'<html><body>data</body></html>'}})
    os.write(descriptor,data)
    return webpage.NativeResult(url,'','')
def terminate(*args): os.kill(os.getpid(), signal.SIGTERM)
webpage.run_native_capture=write
webpage._ensure_native_binary=lambda: Path("/unused")
if sys.argv[3]=='True':
    import stat
    original_fsync=os.fsync
    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode): terminate()
        return original_fsync(fd)
    os.fsync=fsync
elif sys.argv[3]=='allocation':
    original=webpage.socket.socket.recvmsg
    def allocate(self,*args, **kwargs):
        result=original(self,*args, **kwargs); terminate(); return result
    webpage.socket.socket.recvmsg=allocate
else: webpage._metadata=terminate
webpage.capture(url,url,Path(sys.argv[2]))
"""
    result = subprocess.run([sys.executable, '-c', script, str(Path.cwd()), str(output), str(postcommit)],
                            capture_output=True, timeout=8)
    assert result.returncode == -signal.SIGTERM
    assert output.exists() is (postcommit is True)
    assert not list(tmp_path.glob('.*capture-*'))


@pytest.mark.parametrize('failure', ['write', 'source_fsync', 'binary_fsync'])
def test_compiler_supervisor_cleans_every_creation_failure(tmp_path, monkeypatch, failure):
    from scripts.webpage import compiler_guard
    import base64
    _webpage, _source, compiler, _control, _version, _calls = stub_compiler(tmp_path, monkeypatch)
    # Execute the production job/finally directly, suppressing only handler installation.
    monkeypatch.setattr(compiler_guard.signal, 'signal', lambda *_: None)
    original_write = Path.write_bytes
    original_fsync = os.fsync
    calls = []
    def write(path, data):
        result = original_write(path, data)
        if failure == 'write' and path.name == 'source.swift': raise OSError('partial source write')
        return result
    def sync(fd):
        calls.append(fd)
        if (failure == 'source_fsync' and len(calls) == 1) or (failure == 'binary_fsync' and len(calls) == 2):
            raise OSError('fsync failure')
        return original_fsync(fd)
    monkeypatch.setattr(Path, 'write_bytes', write)
    monkeypatch.setattr(compiler_guard.os, 'fsync', sync)
    target = tmp_path / 'binary'
    with pytest.raises(OSError):
        compiler_guard.run(dict(mode='compile', compiler=str(compiler), flags=[],
                               source=base64.b64encode(b'source').decode(), binary=str(target)), os.getppid())
    assert not target.exists() and not list(tmp_path.glob('.compile-*'))


@pytest.mark.parametrize('failure', ['spawn', 'timeout'])
def test_compiler_parent_reports_typed_failure_and_reaps(tmp_path, monkeypatch, failure):
    webpage = load_webpage_module(); stopped = []
    class Process:
        def communicate(self, *_args, **_kwargs):
            raise subprocess.TimeoutExpired('compiler', 12)
    child = Process()
    def start(*_args, **_kwargs):
        if failure == 'spawn': raise OSError('spawn failure')
        return child
    monkeypatch.setattr(webpage.subprocess, 'Popen', start)
    monkeypatch.setattr(webpage, '_stop_native', lambda process: stopped.append(process))
    with pytest.raises(webpage.WebpageCommandError) as error:
        webpage._compiler_job({'mode': 'version', 'compiler': '/stub'})
    assert error.value.code == 'webpage.capture_unavailable'
    assert stopped == ([child] if failure == 'timeout' else [])


@pytest.mark.parametrize('phase', ['compile', 'validation'])
def test_capture_pins_parent_against_symlink_replacement(tmp_path, monkeypatch, phase):
    webpage = load_webpage_module()
    project = tmp_path / 'project'; project.mkdir()
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    parent = project / 'inside'; parent.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    def swap():
        parent.rename(tmp_path / 'detached'); parent.symlink_to(outside, target_is_directory=True)
    def compile():
        if phase == 'compile': swap()
        return Path('/unused')
    def writer(url, stage, *, descriptor, **kwargs):
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe</body></html>'))
        return webpage.NativeResult(url, '', '')
    original = webpage.read_webarchive
    def read(path):
        value = original(path)
        if phase == 'validation': swap()
        return value
    monkeypatch.setattr(webpage, '_ensure_native_binary', compile)
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    monkeypatch.setattr(webpage, 'read_webarchive', read)
    result = webpage.capture('https://example.org/', 'https://example.org/', parent / 'snapshot.webarchive')
    assert result['status'] == 'failed'
    assert list(outside.iterdir()) == []
    assert list((tmp_path / 'detached').iterdir()) == []


def test_capture_link_side_effect_then_error_is_unknown_not_safe_failure(tmp_path, monkeypatch):
    webpage = load_webpage_module()
    def writer(url, stage, *, descriptor, **kwargs):
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe</body></html>'))
        return webpage.NativeResult(url, '', '')
    link = os.link
    calls = []
    def linked(*args, **kwargs):
        calls.append(1); link(*args, **kwargs); raise OSError('post-side-effect')
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    monkeypatch.setattr(os, 'link', linked)
    output = tmp_path / 'snapshot.webarchive'
    assert webpage.capture('https://example.org/', 'https://example.org/', output)['issue']['code'] == 'webpage.capture_outcome_unknown'
    assert output.is_file() and not list(tmp_path.glob('.capture-*'))
    assert webpage.capture('https://example.org/', 'https://example.org/', output)['issue']['code'] == 'webpage.output_exists'
    assert calls == [1]


@pytest.mark.parametrize('key', ['SDKROOT', 'DEVELOPER_DIR', 'MACOSX_DEPLOYMENT_TARGET', 'TOOLCHAINS'])
def test_compiler_effective_environment_invalidates_cache(tmp_path, monkeypatch, key):
    webpage, _, _, _, _, calls = stub_compiler(tmp_path, monkeypatch)
    monkeypatch.setenv(key, 'PRIVATE_A'); first = webpage._ensure_native_binary()
    monkeypatch.setenv(key, 'PRIVATE_B'); second = webpage._ensure_native_binary()
    assert first != second and first.is_file() and second.is_file()
    assert webpage._ensure_native_binary() == second and len(calls.read_text().splitlines()) == 2
    assert 'PRIVATE_' not in str(first) + str(second)
    monkeypatch.setenv('PRIVATE_SERVICE_SECRET', 'do-not-forward')
    assert 'PRIVATE_SERVICE_SECRET' not in webpage._compiler_environment()


@pytest.mark.parametrize('barrier', ['allocated', 'post_helper'])
def test_capture_guardian_cleans_staging_after_parent_sigkill(tmp_path, barrier):
    import signal
    marker = tmp_path / 'barrier'; pidfile = tmp_path / 'guardian.pid'
    script = '''import os,sys,time,plistlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts.webpage import webpage
original_popen=webpage.subprocess.Popen
def launch(*a,**k):
    child=original_popen(*a,**k)
    if 'capture_guard.py' in str(a[0]): Path(sys.argv[3]).write_text(str(child.pid))
    return child
webpage.subprocess.Popen=launch
webpage._ensure_native_binary=lambda:Path('/unused')
def pause():
    Path(sys.argv[2]).write_text('ready')
    time.sleep(30)
if sys.argv[4]=='allocated':
    original=webpage.socket.socket.recvmsg
    def receive(self,*a,**k):
        result=original(self,*a,**k); pause(); return result
    webpage.socket.socket.recvmsg=receive
else: webpage._metadata=lambda _:pause()
def writer(url,stage,*,descriptor,**kwargs):
    os.write(descriptor,plistlib.dumps({'WebMainResource':{'WebResourceURL':url,'WebResourceMIMEType':'text/html','WebResourceData':b'<html><body>safe</body></html>'}}))
    return webpage.NativeResult(url,'','')
webpage.run_native_capture=writer
webpage.capture('https://example.org/','https://example.org/',Path(sys.argv[5]))
'''
    process = subprocess.Popen([sys.executable, '-c', script, str(Path.cwd()), str(marker), str(pidfile), barrier, str(tmp_path / 'snapshot.webarchive')])
    guardian = None
    try:
        deadline = time.monotonic() + 8
        while not marker.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        guardian = int(pidfile.read_text())
        assert list(tmp_path.glob('.capture-*'))
        process.kill(); process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while list(tmp_path.glob('.capture-*')):
            assert time.monotonic() < deadline; time.sleep(.02)
        while True:
            try: os.kill(guardian, 0)
            except ProcessLookupError: break
            assert time.monotonic() < deadline; time.sleep(.02)
        assert not (tmp_path / 'snapshot.webarchive').exists()
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=3)
        if guardian:
            try: os.kill(guardian, signal.SIGKILL)
            except ProcessLookupError: pass


def test_capture_postcommit_close_error_still_reaps_guardian(tmp_path, monkeypatch):
    webpage = load_webpage_module(); owned = []
    def writer(url, stage, *, descriptor, **kwargs):
        owned.append(descriptor)
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe</body></html>'))
        return webpage.NativeResult(url, '', '')
    original = os.close
    def close(fd):
        original(fd)
        if owned and fd == owned[0]: raise OSError('close side effect then failure')
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    monkeypatch.setattr(os, 'close', close)
    output = tmp_path / 'snapshot.webarchive'
    result = webpage.capture('https://example.org/', 'https://example.org/', output)
    assert result['issue']['code'] == 'webpage.capture_outcome_unknown'
    assert output.exists() and not list(tmp_path.glob('.capture-*'))


@pytest.mark.parametrize('root_mode', ['absolute', 'relative', 'empty', 'unset'])
def test_capture_pins_before_validation_against_project_ancestor_swap(tmp_path, monkeypatch, root_mode):
    from scripts.webpage import paths
    webpage = load_webpage_module()
    ancestor = tmp_path / 'ancestor'; project = ancestor / 'project'; project.mkdir(parents=True)
    external = tmp_path / 'external-parent'; (external / 'project').mkdir(parents=True)
    if root_mode == 'absolute': monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    elif root_mode == 'relative':
        monkeypatch.chdir(tmp_path); monkeypatch.setenv('CLAUDE_PROJECT_DIR', 'ancestor/project')
    else:
        monkeypatch.chdir(project)
        if root_mode == 'empty': monkeypatch.setenv('CLAUDE_PROJECT_DIR', '')
        else: monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    original = paths.lexical_project_path; attacked = []
    def validate(root, candidate):
        path = original(root, candidate)
        if not attacked:
            attacked.append(1)
            ancestor.rename(tmp_path / 'original-ancestor')
            ancestor.symlink_to(external, target_is_directory=True)
        return path
    monkeypatch.setattr(paths, 'lexical_project_path', validate)
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    def writer(url, stage, *, descriptor, **kwargs):
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe</body></html>'))
        return webpage.NativeResult(url, '', '')
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    result = webpage.capture('https://example.org/', 'https://example.org/', Path('snapshot.webarchive'))
    assert attacked == [1] and result['status'] == 'failed'
    assert list((external / 'project').iterdir()) == []
    assert list((tmp_path / 'original-ancestor/project').iterdir()) == []


@pytest.mark.parametrize('root_mode', ['absolute', 'relative', 'empty', 'unset'])
@pytest.mark.parametrize('absolute_ref', [False, True])
def test_capture_secure_anchor_preserves_legal_path_modes(tmp_path, monkeypatch, root_mode, absolute_ref):
    webpage = load_webpage_module(); project = tmp_path / 'project'; project.mkdir()
    if root_mode == 'absolute': monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    elif root_mode == 'relative':
        monkeypatch.chdir(tmp_path); monkeypatch.setenv('CLAUDE_PROJECT_DIR', 'project')
    else:
        monkeypatch.chdir(project)
        if root_mode == 'empty': monkeypatch.setenv('CLAUDE_PROJECT_DIR', '')
        else: monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: Path('/unused'))
    def writer(url, stage, *, descriptor, **kwargs):
        os.write(descriptor, webarchive_fixture_bytes(url, '<html><body>safe</body></html>'))
        return webpage.NativeResult(url, '', '')
    monkeypatch.setattr(webpage, 'run_native_capture', writer)
    ref = project / 'snapshot.webarchive' if absolute_ref else Path('snapshot.webarchive')
    result = webpage.capture('https://example.org/', 'https://example.org/', ref)
    assert result['status'] == 'complete' and result['output_path'] == str(ref)
    assert (project / 'snapshot.webarchive').is_file()


@pytest.mark.skipif(sys.platform != 'darwin' or shutil.which('swiftc') is None,
                    reason='requires macOS WebKit and swiftc')
@pytest.mark.parametrize('transport', ['fetch', 'xhr'])
def test_production_capture_rejects_network_churn_at_local_bound(tmp_path, monkeypatch, transport):
    from webpage_test_support import network_churn_webpage
    webpage = load_webpage_module(); binary = tmp_path / 'production-webkit'
    subprocess.run([shutil.which('swiftc'), '-target', os.uname().machine + '-apple-macos11',
                    '-O', '-parse-as-library', '-framework', 'WebKit', str(webpage._native_source()), '-o', str(binary)],
                   check=True, capture_output=True, text=True, timeout=300)
    monkeypatch.setattr(webpage, '_ensure_native_binary', lambda: binary)
    with network_churn_webpage(transport) as (url, completed):
        started = time.monotonic()
        result = webpage.capture(url, url, tmp_path / 'snapshot.webarchive')
        elapsed = time.monotonic() - started
    assert result['status'] == 'failed' and result['issue']['code'] == 'webpage.stabilization_failed'
    assert 5 <= elapsed < 7
    assert len(completed) > 30 and completed[-1] - completed[0] > 4.5
    assert max(b-a for a,b in zip(completed, completed[1:])) < .6
    assert not (tmp_path / 'snapshot.webarchive').exists() and not list(tmp_path.glob('.capture-*'))
