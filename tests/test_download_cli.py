from __future__ import annotations

import io
import json
import importlib.util
import urllib.error
import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = PLUGIN_ROOT / "scripts" / "download" / "download.py"
COOKIECLOUD = PLUGIN_ROOT / "scripts" / "download" / "cookiecloud.py"
AA = PLUGIN_ROOT / "scripts" / "download" / "aa.py"


def run_download(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOWNLOAD), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_aa_mirror_defaults_match_current_official_domains():
    mod = _load_module(AA, "aa_mirrors_under_test")

    assert mod.STATIC_AA_MIRRORS == [
        "https://annas-archive.pk",
        "https://annas-archive.gd",
        "https://annas-archive.gl",
    ]


def test_aa_wikipedia_infobox_mirror_parser_prefers_url_row():
    mod = _load_module(AA, "aa_wikipedia_parser_under_test")
    html = """
    <table class="infobox">
      <tr><th>Founded</th><td><a href="https://annas-archive.org/old">old</a></td></tr>
      <tr><th>URL</th><td>
        <a href="https://annas-archive.pk/">annas-archive.pk</a>
        <a href="https://annas-archive.gd/">annas-archive.gd</a>
        <a href="https://annas-archive.gl/">annas-archive.gl</a>
      </td></tr>
    </table>
    <a class="external" href="https://annas-archive.org/old">old</a>
    """

    assert mod._mirrors_from_wikipedia_html(html) == [
        "https://annas-archive.pk",
        "https://annas-archive.gd",
        "https://annas-archive.gl",
    ]


def test_aa_base_url_uses_wikipedia_recovery_after_static_mirrors_fail(monkeypatch):
    mod = _load_module(AA, "aa_wikipedia_recovery_under_test")
    tried: list[str] = []

    def fake_request(method, url, *, timeout=30, stream=False, browser_tls=True):
        if method == "HEAD":
            tried.append(url)
        class Response:
            status_code = 200 if url == "https://annas-archive.wf" else 503
        return Response()

    monkeypatch.setattr(mod, "_request", fake_request)
    monkeypatch.setattr(mod, "wikipedia_aa_mirrors", lambda: ["https://annas-archive.wf"])

    assert mod.get_aa_base_url({"mirrors": []}) == "https://annas-archive.wf"
    assert tried == [
        "https://annas-archive.pk",
        "https://annas-archive.gd",
        "https://annas-archive.gl",
        "https://annas-archive.wf",
    ]


def test_download_help_exposes_agent_contract():
    top = run_download("--help")
    assert top.returncode == 0
    assert "{book,paper,accept}" in top.stdout

    for args in [
        ("book", "candidates", "--help"),
        ("book", "fetch", "--help"),
        ("paper", "fetch", "--help"),
        ("paper", "diagnose", "--help"),
        ("accept", "--help"),
    ]:
        result = run_download(*args)
        assert result.returncode == 0


def test_legacy_flag_mode_is_removed():
    result = run_download("--doi", "10.1/example")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_legacy_batch_mode_is_removed():
    result = run_download("batch", "--manifest", "manifest.json")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_accept_moves_temp_file_to_sources(tmp_path):
    project = tmp_path / "project"
    temp_dir = project / ".quasi" / "temp" / "downloads"
    temp_dir.mkdir(parents=True)
    src = temp_dir / "candidate.pdf"
    src.write_bytes(b"%PDF- test content")

    result = subprocess.run(
        [
            sys.executable,
            str(DOWNLOAD),
            "accept",
            "--path",
            str(src),
            "--slug",
            "author-title-2024",
            "--kind",
            "paper",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["kind"] == "paper"
    assert payload["moved"] is True
    assert Path(payload["path"]).name == "author-title-2024.pdf"
    assert Path(payload["path"]).exists()
    assert not src.exists()


def test_accept_overwrite_uses_one_sibling_atomic_replace(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_atomic_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    replaced: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observing_replace(source, target):
        source_path = Path(source)
        target_path = Path(target)
        assert target_path == dest
        assert dest.read_bytes() == b"old generation"
        assert source_path.parent == dest.parent
        assert source_path.name.startswith(f"{dest.name}.quasi-stage-")
        replaced.append((source_path, target_path))
        real_replace(source, target)

    monkeypatch.setattr(mod.os, "replace", observing_replace)
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["published"] is True
    assert payload["source_removed"] is True
    assert payload["sha256"] == hashlib.sha256(b"new generation").hexdigest()
    assert replaced and dest.read_bytes() == b"new generation"
    assert not src.exists()
    assert not list(output_dir.glob(f"{dest.name}.quasi-stage-*"))


def test_accept_failure_before_replace_preserves_previous_output(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_rollback_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    monkeypatch.setattr(
        mod.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["reason"] == "accept_commit_failed"
    assert payload["published"] is False
    assert payload["previous_output_preserved"] is True
    assert src.read_bytes() == b"new generation"
    assert dest.read_bytes() == b"old generation"
    assert not list(output_dir.glob(f"{dest.name}.quasi-stage-*"))


def test_accept_post_replace_fsync_failure_reports_coherent_unknown(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(DOWNLOAD, "download_accept_fsync_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    monkeypatch.setattr(
        mod,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync failed")),
    )
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["published"] is True
    assert payload["previous_output_preserved"] is False
    assert payload["sha256"] == hashlib.sha256(b"new generation").hexdigest()
    assert dest.read_bytes() == b"new generation"
    assert src.read_bytes() == b"new generation"


def test_accept_serializes_competing_writers_for_one_output(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_lock_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    first = source_dir / "first.pdf"
    second = source_dir / "second.pdf"
    dest = output_dir / "author-title-2024.pdf"
    first.write_bytes(b"first generation")
    second.write_bytes(b"second generation")

    first_inside_replace = threading.Event()
    release_first = threading.Event()
    real_replace = os.replace

    def paused_replace(source, target):
        if not first_inside_replace.is_set():
            first_inside_replace.set()
            assert release_first.wait(timeout=2)
        real_replace(source, target)

    monkeypatch.setattr(mod.os, "replace", paused_replace)
    results: dict[str, tuple[dict, int]] = {}

    def accept(name: str, source: Path) -> None:
        results[name] = mod._accept_to_output(
            source,
            dest,
            kind="paper",
            overwrite=False,
        )

    one = threading.Thread(target=accept, args=("first", first))
    two = threading.Thread(target=accept, args=("second", second))
    one.start()
    assert first_inside_replace.wait(timeout=2)
    two.start()
    time.sleep(0.1)
    assert "second" not in results
    release_first.set()
    one.join(timeout=2)
    two.join(timeout=2)

    assert results["first"][1] == 0
    assert results["second"][1] == 1
    assert results["second"][0]["status"] == "conflict"
    assert dest.read_bytes() == b"first generation"
    assert second.exists()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


class _FakeUrlResponse:
    def __init__(self, url, content, *, status=200, headers=None):
        self._url = url
        self._content = content
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        return self._content if size < 0 else self._content[:size]

    def geturl(self):
        return self._url


def test_ezproxy_base_url_normalises_to_login_prefix():
    mod = _load_module(COOKIECLOUD, "cookiecloud_under_test")

    assert mod._ezproxy_login_url("https://ezproxy.example.edu") == (
        "https://ezproxy.example.edu/login?url="
    )
    assert mod._ezproxy_login_url("ezproxy.example.edu/") == (
        "https://ezproxy.example.edu/login?url="
    )


def test_cookiecloud_domain_filter_keeps_parent_and_subdomain_cookies():
    mod = _load_module(COOKIECLOUD, "cookiecloud_domain_filter_under_test")
    data = {
        "cookie_data": {
            "bucket": [
                {"domain": "oclc.org", "name": "root", "value": "r"},
                {"domain": ".idm.oclc.org", "name": "idm", "value": "i"},
                {
                    "domain": "www-tandfonline-com.eux.idm.oclc.org",
                    "name": "tnf",
                    "value": "t",
                },
                {"domain": "example.org", "name": "other", "value": "x"},
            ]
        }
    }

    records = mod._filter_cookie_records(data, "oclc.org")

    assert [(r["domain"], r["name"]) for r in records] == [
        ("oclc.org", "root"),
        ("idm.oclc.org", "idm"),
        ("www-tandfonline-com.eux.idm.oclc.org", "tnf"),
    ]


def test_ezproxy_cookie_header_uses_only_cookies_matching_request_host():
    mod = _load_module(DOWNLOAD, "download_cookie_header_under_test")
    config = {
        "domain": "oclc.org",
        "cookie_records": [
            {"domain": "oclc.org", "name": "root", "value": "r", "path": "/"},
            {"domain": "idm.oclc.org", "name": "idm", "value": "i", "path": "/"},
            {
                "domain": "journals-sagepub-com.eux.idm.oclc.org",
                "name": "sage",
                "value": "s",
                "path": "/",
            },
        ],
    }

    header = mod._ezproxy_cookie_header(
        config,
        "https://www-tandfonline-com.eux.idm.oclc.org/doi/pdf/10.1/example",
    )

    assert header == "root=r; idm=i"


def test_find_oa_url_accepts_crossref_pdf_url_when_content_type_unspecified(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_crossref_pdf_under_test")

    def fake_get_json(url, timeout=10):
        if "api.crossref.org" in url:
            return {
                "status": "ok",
                "message": {
                    "link": [
                        {
                            "content-type": "unspecified",
                            "URL": "http://academic.oup.com/mind/article-pdf/110/438/504/3033370/1100504.pdf",
                        }
                    ]
                },
            }
        return None

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert mod.find_oa_url("10.1093/mind/110.438.504") == (
        "http://academic.oup.com/mind/article-pdf/110/438/504/3033370/1100504.pdf"
    )


def test_find_oa_url_accepts_cambridge_crossref_content_view_link(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_crossref_cambridge_under_test")

    def fake_get_json(url, timeout=10):
        if "api.crossref.org" in url:
            return {
                "status": "ok",
                "message": {
                    "link": [
                        {
                            "content-type": "unspecified",
                            "URL": "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S0036930622000394",
                        }
                    ]
                },
            }
        return None

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert mod.find_oa_url("10.1017/s0036930622000394") == (
        "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S0036930622000394"
    )


def test_informs_proxied_host_matches_ezproxy_pdf_pattern():
    mod = _load_module(DOWNLOAD, "download_informs_pattern_under_test")
    final_url = "https://pubsonline-informs-org.eux.idm.oclc.org/doi/10.1287/ijoc.2024.0736"

    assert mod._publisher_pdf_urls_from_article_url(final_url) == [
        "https://pubsonline-informs-org.eux.idm.oclc.org/doi/pdf/10.1287/ijoc.2024.0736"
    ]


def test_informs_doi_matches_publisher_direct_pdf_pattern():
    mod = _load_module(DOWNLOAD, "download_informs_direct_under_test")
    doi = "10.1287/ijoc.2024.0736"
    suffix = doi.split("/", 1)[-1]

    urls = [
        pattern.format(doi=doi, suffix=suffix)
        for prefix, pattern in mod._PUBLISHER_DIRECT_URLS
        if doi.startswith(prefix)
    ]

    assert "https://pubsonline.informs.org/doi/pdf/10.1287/ijoc.2024.0736" in urls


def test_annualreviews_doi_has_ezproxy_and_direct_pdf_routes():
    mod = _load_module(DOWNLOAD, "download_annualreviews_routes_under_test")
    doi = "10.1146/annurev-soc-031021-041439"
    final_url = "https://www-annualreviews-org.eux.idm.oclc.org/content/journals/10.1146/annurev-soc-031021-041439"

    proxied = mod._publisher_pdf_urls_from_article_url(final_url)
    direct = [
        pattern.format(doi=doi, suffix=doi.split("/", 1)[-1])
        for prefix, pattern in mod._PUBLISHER_DIRECT_URLS
        if doi.startswith(prefix)
    ]

    assert proxied == [
        "https://www-annualreviews-org.eux.idm.oclc.org/doi/pdf/10.1146/annurev-soc-031021-041439"
    ]
    assert direct == [
        "https://www.annualreviews.org/doi/pdf/10.1146/annurev-soc-031021-041439"
    ]


def test_sciencedirect_article_url_detection_accepts_native_and_ezproxy_urls():
    mod = _load_module(DOWNLOAD, "download_sciencedirect_url_under_test")

    assert mod._is_sciencedirect_article_url(
        "https://www.sciencedirect.com/science/article/pii/S0378216626001025"
    )
    assert mod._is_sciencedirect_article_url(
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://www.sciencedirect.com/topics/social-sciences/conversation-analysis"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://example.org/science/article/pii/S0378216626001025"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://www-sciencedirect-com.example.org/science/article/pii/S0378216626001025"
    )


def test_sciencedirect_article_url_expands_to_pdf_urls():
    mod = _load_module(DOWNLOAD, "download_sciencedirect_pdf_url_under_test")

    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087"
    ) == [
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdfft?isDTMRedir=true&download=true",
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdf",
    ]
    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S1364661326001087"
    )[0] == (
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/"
        "S1364661326001087/pdfft?isDTMRedir=true&download=true"
    )
    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www.sciencedirect.com/topics/social-sciences/conversation-analysis"
    ) == []


def test_cell_fulltext_url_expands_to_pdf_urls():
    mod = _load_module(DOWNLOAD, "download_cell_url_under_test")
    fulltext = "https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7"

    assert mod._is_cell_article_url(fulltext)
    assert mod._cell_pdf_urls_from_article_url(fulltext) == [
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7",
        "https://www.cell.com/trends/cognitive-sciences/pdf/S1364-6613%2826%2900108-7.pdf",
    ]
    assert mod._cell_sciencedirect_urls_from_pii(
        "S1364-6613(26)00108-7"
    ) == [
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087",
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdfft?isDTMRedir=true&download=true",
    ]
    assert mod._cell_pdf_urls_from_article_url(
        "https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7"
    )[1] == (
        "https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/pdf/"
        "S1364-6613%2826%2900108-7.pdf"
    )
    assert mod._cell_pdf_urls_from_article_url(
        "https://www.cell.com/about"
    ) == []


def test_cell_doi_expands_pii_style_suffix_to_show_pdf_url():
    mod = _load_module(DOWNLOAD, "download_cell_doi_under_test")

    assert mod._cell_pdf_urls_from_doi("10.1016/S1364-6613(26)00108-7") == [
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7"
    ]
    assert mod._cell_pdf_urls_from_doi("10.1016/j.pragma.2026.04.009") == []
    assert mod._cell_pdf_urls_from_doi("10.1287/ijoc.2024.0736") == []


def test_cell_pii_resolves_to_doi_via_crossref(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_cell_pii_doi_under_test")

    def fake_get_json_urllib(url, timeout=15):
        assert "filter=alternative-id:S1364661326001087" in url
        return {"message": {"items": [{"DOI": "10.1016/j.tics.2026.05.002"}]}}

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json_urllib)

    assert mod._doi_from_cell_pii("S1364-6613(26)00108-7") == "10.1016/j.tics.2026.05.002"


def test_paper_diagnose_retains_redacted_native_jstor_403(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_jstor_403_diagnose_under_test")
    requested = "https://www.jstor.org/stable/43154235?token=never-print-me"
    seen_headers = []

    def fake_urlopen(request, timeout):
        seen_headers.append(dict(request.header_items()))
        raise urllib.error.HTTPError(
            requested,
            403,
            "Forbidden",
            {"content-type": "text/html"},
            io.BytesIO(b"<html>access denied</html>"),
        )

    monkeypatch.setenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "eux.idm.oclc.org")
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: (_ for _ in ()).throw(AssertionError("direct probe must not fetch CookieCloud")),
    )
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(requested)

    assert report == {
        "schema_version": "quasi.download.diagnose/0.1",
        "requested_url": "https://www.jstor.org/stable/43154235",
        "final_url": "https://www.jstor.org/stable/43154235",
        "mode": "direct",
        "http_status": 403,
        "content_type": "text/html",
        "classification": "access_denied",
        "retryable": False,
        "ezproxy": {
            "configured": True,
            "target_matches_proxy": False,
            "attempted": False,
        },
        "wrote_file": False,
    }
    assert "Cookie" not in seen_headers[0]
    assert "never-print-me" not in json.dumps(report)
    assert list(tmp_path.iterdir()) == []


def test_paper_diagnose_classifies_landing_cloudflare_pdf_and_connection_error(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_classification_under_test")
    url = "https://www.jstor.org/stable/43154235"

    responses = [
        _FakeUrlResponse(url, b"<html>institution login</html>", headers={"content-type": "text/html"}),
        urllib.error.HTTPError(
            url,
            403,
            "Forbidden",
            {"content-type": "text/html", "cf-ray": "abc", "server": "cloudflare"},
            io.BytesIO(b"<title>Just a moment...</title>"),
        ),
        _FakeUrlResponse(url, b"%PDF-1.7", headers={"content-type": "application/pdf"}),
        urllib.error.URLError("offline"),
    ]

    def fake_urlopen(_request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    reports = [mod.diagnose_paper_url(url) for _ in range(4)]

    assert [(report["http_status"], report["classification"]) for report in reports] == [
        (200, "html_landing"),
        (403, "cloudflare_challenge"),
        (200, "pdf"),
        (None, "connection_error"),
    ]
    assert reports[-1]["retryable"] is True
    assert all(report["wrote_file"] is False for report in reports)


def test_paper_diagnose_parser_and_handler_never_start_acquisition(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_diagnose_command_under_test")
    url = "https://www.jstor.org/stable/43154235?signature=do-not-print"
    args = mod._build_parser().parse_args([
        "paper", "diagnose", "--url", url, "--timeout", "12", "--json",
    ])

    def acquisition_called(*_args, **_kwargs):
        raise AssertionError("diagnostic must not start acquisition")

    monkeypatch.setattr(mod, "download_paper", acquisition_called)
    monkeypatch.setattr(mod, "download_pdf_from_url", acquisition_called)
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        lambda _request, timeout: _FakeUrlResponse(url, b"<html>landing</html>", headers={"content-type": "text/html"}),
    )

    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_url"] == "https://www.jstor.org/stable/43154235"
    assert payload["classification"] == "html_landing"
    assert payload["wrote_file"] is False
    assert "do-not-print" not in json.dumps(payload)


def test_paper_diagnose_via_ezproxy_redacts_session_data(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_ezproxy_under_test")
    url = "https://www.jstor.org/stable/43154235?signature=do-not-print"
    config = {
        "domain": "eux.idm.oclc.org",
        "login_url": "https://login.eux.idm.oclc.org/login?url=",
        "cookie": "never-print-cookie",
    }
    calls = []

    class FakeResponse:
        url = "https://www-jstor-org.eux.idm.oclc.org/stable/43154235?session=do-not-print"
        status_code = 200
        headers = {"content-type": "application/pdf"}
        closed = False

        @property
        def content(self):
            raise AssertionError("diagnostic must stream a bounded response prefix")

        def iter_content(self, *, chunk_size):
            assert chunk_size <= mod._DIAGNOSE_BODY_LIMIT
            yield b"%PDF-1.7"

        def close(self):
            self.closed = True

    response = FakeResponse()

    class FakeSession:
        def get(self, request_url, **kwargs):
            calls.append((request_url, kwargs))
            return response

    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: config)
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda _config: FakeSession())
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(url, via_ezproxy=True)

    assert calls == [(
        f"{config['login_url']}{url}",
        {"allow_redirects": True, "timeout": 30, "stream": True},
    )]
    assert response.closed is True
    assert report["mode"] == "ezproxy"
    assert report["classification"] == "pdf"
    assert report["ezproxy"] == {
        "configured": True,
        "target_matches_proxy": False,
        "attempted": True,
    }
    rendered = json.dumps(report)
    assert "never-print-cookie" not in rendered
    assert "do-not-print" not in rendered


def test_paper_diagnose_stream_reader_stays_bounded_for_oversized_chunks():
    mod = _load_module(DOWNLOAD, "download_diagnose_bounded_stream_under_test")

    class OversizedChunkResponse:
        @property
        def content(self):
            raise AssertionError("stream reader must not materialise response.content")

        def iter_content(self, *, chunk_size):
            assert chunk_size <= mod._DIAGNOSE_BODY_LIMIT
            yield b"x" * (mod._DIAGNOSE_BODY_LIMIT + 1)
            raise AssertionError("reader must stop after its bounded prefix")

    content = mod._read_diagnostic_response_body(OversizedChunkResponse())

    assert content == b"x" * mod._DIAGNOSE_BODY_LIMIT


def test_paper_diagnose_observes_retryable_status_once(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_no_retry_under_test")
    url = "https://www.jstor.org/stable/43154235"
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            url,
            503,
            "Service Unavailable",
            {"content-type": "text/html"},
            io.BytesIO(b"<html>try later</html>"),
        )

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: (_ for _ in ()).throw(AssertionError("direct probe must not fetch CookieCloud")),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(url)

    assert calls == [(url, 30)]
    assert report["http_status"] == 503
    assert report["classification"] == "html_landing"
    assert report["retryable"] is True


def test_paper_diagnose_direct_never_injects_proxy_cookies(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_cookie_boundary_under_test")
    url = "https://www.jstor.org/stable/43154235"
    sent_headers = []

    def fake_urlopen(request, timeout):
        sent_headers.append(dict(request.header_items()))
        return _FakeUrlResponse(url, b"<html>landing</html>", headers={"content-type": "text/html"})

    monkeypatch.setenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "jstor.org")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    report = mod.diagnose_paper_url(url)

    assert report["ezproxy"] == {
        "configured": True,
        "target_matches_proxy": True,
        "attempted": False,
    }
    assert all(name.lower() != "cookie" for name in sent_headers[0])


def test_paper_diagnose_reports_unavailable_ezproxy_without_target_request(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_ezproxy_unavailable_under_test")
    url = "https://www.jstor.org/stable/43154235"

    monkeypatch.delenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", raising=False)
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(
        mod,
        "_build_ezproxy_session",
        lambda _config: (_ for _ in ()).throw(AssertionError("no session without config")),
    )

    report = mod.diagnose_paper_url(url, via_ezproxy=True)

    assert report["mode"] == "ezproxy"
    assert report["http_status"] is None
    assert report["classification"] == "ezproxy_unavailable"
    assert report["retryable"] is False
    assert report["ezproxy"] == {
        "configured": False,
        "target_matches_proxy": False,
        "attempted": False,
    }


def test_paper_diagnose_rejects_invalid_or_userinfo_urls(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_diagnose_invalid_url_under_test")
    monkeypatch.setattr(
        mod,
        "diagnose_paper_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid URLs must not be observed")),
    )

    for url in ("ftp://www.jstor.org/stable/43154235", "https://token@www.jstor.org/stable/43154235"):
        args = mod._build_parser().parse_args(["paper", "diagnose", "--url", url])
        assert args.func(args) == 2
        assert "HTTP(S) URL without userinfo" in capsys.readouterr().err


def test_ezproxy_login_detection_does_not_treat_cloudflare_as_cookie_expired():
    mod = _load_module(DOWNLOAD, "download_cloudflare_detection_under_test")
    cloudflare_html = b"""
    <!DOCTYPE html><html><head><title>Just a moment...</title></head>
    <body><script>window._cf_chl_opt = {}</script></body></html>
    """

    assert mod._is_cloudflare_challenge(
        cloudflare_html,
        {"server": "cloudflare", "cf-ray": "abc"},
    )
    mod._raise_if_ezproxy_login_page(
        "https://www-cell-com.eux.idm.oclc.org/action/showPdf",
        "https://login.eux.idm.oclc.org/login?url=",
        cloudflare_html,
        headers={"server": "cloudflare", "cf-ray": "abc"},
    )


def test_ezproxy_login_detection_raises_for_shibboleth_login():
    mod = _load_module(DOWNLOAD, "download_shibboleth_detection_under_test")
    shib_html = b"""
    <html><head><title>Shibboleth Authentication Request</title></head>
    <body><form><input type="password" name="password"></form></body></html>
    """

    try:
        mod._raise_if_ezproxy_login_page(
            "https://login.eux.idm.oclc.org/login?url=https://www.cell.com/action/showPdf",
            "https://login.eux.idm.oclc.org/login?url=",
            shib_html,
            history_len=0,
        )
    except mod.EZProxyCookieExpired:
        pass
    else:
        raise AssertionError("Shibboleth login page should raise EZProxyCookieExpired")


def test_ezproxy_tries_cell_showpdf_candidate_first(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_ezproxy_candidate_under_test")
    calls: list[str] = []

    class FakeSession:
        headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            if "doi.org" in url:
                return SimpleNamespace(
                    url="https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
                    content=b"<html>landing</html>",
                    status_code=200,
                    history=[object()],
                    headers={},
                )
            return SimpleNamespace(
                url="https://www-cell-com.eux.idm.oclc.org/action/showPdf?pii=S1364-6613%2826%2900108-7",
                content=b"%PDF- cell via ezproxy",
                status_code=200,
                history=[object()],
                headers={"content-type": "application/pdf;charset=UTF-8"},
            )

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://login.eux.idm.oclc.org/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    result = mod.try_ezproxy_download(
        "10.1016/j.tics.2026.05.002",
        str(tmp_path / "paper.pdf"),
        cell_pdf_urls=["https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7"],
    )

    assert result is True
    # The rewritten proxy host is tried before the login redirect: the
    # institutional session cookies live on the rewritten host, not on login.
    assert calls[1] == (
        "https://www-cell-com.eux.idm.oclc.org/action/showPdf"
        "?pii=S1364-6613%2826%2900108-7"
    )
    assert (tmp_path / "paper.pdf").read_bytes().startswith(b"%PDF-")


def test_write_text_fallback_from_article_html(tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_text_fallback_under_test")
    html = b"""
    <html><body><article>
    <h1>Timescapes of non-human experience</h1>
    <h2>Abstract</h2><p>Timescapes of non-human experience are discussed here.</p>
    <h2>References</h2><p>Reference content.</p>
    </article></body></html>
    """ + b"article text " * 80
    out = tmp_path / "paper.txt"

    assert mod._write_text_fallback_from_html(
        html,
        str(out),
        headers={"content-type": "text/html"},
        expected_title="Timescapes of non-human experience",
    )
    assert "Timescapes of non-human experience" in out.read_text(encoding="utf-8")


def test_download_paper_adds_cell_pdf_hints_before_fetch(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_hints_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/action/showPdf" in url:
            Path(output_path).write_bytes(b"%PDF- cell")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        url="https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
        output_dir=str(tmp_path),
        filename="cell-paper",
    )

    assert result == str(tmp_path / "cell-paper.pdf")
    assert tried == [
        "https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7",
    ]


def test_ezproxy_sciencedirect_url_tracking_deduplicates(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_ezproxy_sciencedirect_dedupe_under_test")
    article_url = "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"

    class FakeResponse:
        url = article_url
        content = b"<html></html>"
        status_code = 200
        history = [object()]

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://ezproxy.example.edu/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())

    sciencedirect_urls = [article_url]

    assert not mod.try_ezproxy_download(
        "10.1016/j.pragma.2026.04.009",
        str(tmp_path / "paper.pdf"),
        sciencedirect_urls=sciencedirect_urls,
    )
    assert sciencedirect_urls == [article_url]


def test_inspect_downloaded_file_reads_txt_front_text(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_inspect_under_test")
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Making sense of conduct: A conversation analysis of therapist formulation "
        "in interaction with autistic children\n"
        "Doe and Roe discuss therapist formulation in detail. "
        + "article text " * 120,
        encoding="utf-8",
    )

    inspect = mod._inspect_downloaded_file(text_path)

    assert inspect["format"] == "txt"
    assert inspect["readability"] == "text"
    assert inspect["front_text"].startswith("Making sense of conduct")
    assert inspect["fallback_hint"] is None


def test_verify_source_content_accepts_txt_title_match(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_under_test")
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Making sense of conduct: A conversation analysis of therapist formulation "
        "in interaction with autistic children\n"
        + "therapist formulation autistic children " * 40,
        encoding="utf-8",
    )

    assert mod.verify_source_content(
        str(text_path),
        expected_title=(
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children"
        ),
    )


def test_verify_source_content_rejects_weak_partial_title_match(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_weak_title_under_test")
    text_path = tmp_path / "wrong-paper.txt"
    text_path.write_text(
        "Language acquisition across linguistic and cognitive systems\n"
        "Edited by Michèle Kail and Maya Hickmann\n"
        + "language acquisition linguistic cognitive systems " * 40,
        encoding="utf-8",
    )

    assert not mod.verify_source_content(
        str(text_path),
        expected_title=(
            "Some and or in second language acquisition: Exploring linguistic "
            "and cognitive factors"
        ),
    )


def test_verify_source_content_rejects_same_author_related_title(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_related_title_under_test")
    text_path = tmp_path / "related-paper.txt"
    text_path.write_text(
        "We need to talk about hearer's meaning!\n"
        "Maj-Britt Mosegaard Hansen and Marina Terkourafi\n"
        + "hearer's meaning pragmatic theory speaker intentions " * 40,
        encoding="utf-8",
    )

    assert not mod.verify_source_content(
        str(text_path),
        expected_author="Marina Terkourafi",
        expected_title="Hearer's Meaning 2.0: A reply to Li and Xie (2025)",
    )


def test_accept_moves_temp_text_paper_to_sources(tmp_path):
    project = tmp_path / "project"
    temp_dir = project / ".quasi" / "temp" / "downloads"
    temp_dir.mkdir(parents=True)
    src = temp_dir / "candidate.txt"
    src.write_text("Making sense of conduct\n" + "article text " * 120, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(DOWNLOAD),
            "accept",
            "--path",
            str(src),
            "--slug",
            "making-sense-conduct-2026",
            "--kind",
            "paper",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["kind"] == "paper"
    assert Path(payload["path"]).name == "making-sense-conduct-2026.txt"
    assert Path(payload["path"]).read_text(encoding="utf-8").startswith("Making sense")


def test_download_paper_stops_after_pdf_sources_fail(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_sciencedirect_no_text_flow_under_test")
    article_url = "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"

    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "find_oa_url", lambda doi: None)
    monkeypatch.setattr(mod, "try_scihub_download", lambda *args: False)
    monkeypatch.setattr(mod, "_try_publisher_direct", lambda *args: False)
    monkeypatch.setattr(mod, "find_wayback_url", lambda doi: None)
    monkeypatch.setattr(mod, "_kagi_discover_paper", lambda title, author=None: ([], []))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)

    def fake_ezproxy(doi, output_path, sciencedirect_urls=None, **kwargs):
        if sciencedirect_urls is not None:
            sciencedirect_urls.append(article_url)
        return False

    monkeypatch.setattr(mod, "_try_ezproxy_with_refresh", fake_ezproxy)

    result = mod.download_paper(
        doi="10.1016/j.pragma.2026.04.009",
        output_dir=str(tmp_path),
        filename="making-sense-conduct-2026",
        verify_title=(
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children"
        ),
    )

    assert result is None
    assert not hasattr(mod, "_dokobot_read_url")
    assert not (tmp_path / "making-sense-conduct-2026.txt").exists()
    assert not (tmp_path / "making-sense-conduct-2026.pdf").exists()


def test_ezproxy_throttle_first_call_does_not_wait(tmp_path):
    mod = _load_module(DOWNLOAD, "download_throttle_first_under_test")
    state = tmp_path / "ezproxy-throttle.state"
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=30,
        now=lambda: 1000.0,
        sleep=recorded.append,
    )

    assert waited == 0.0
    assert recorded == []
    assert state.read_text().strip() == "1000.0"


def test_ezproxy_throttle_waits_remaining_interval(tmp_path):
    mod = _load_module(DOWNLOAD, "download_throttle_wait_under_test")
    state = tmp_path / "ezproxy-throttle.state"
    state.write_text("1000.0")
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=30,
        now=lambda: 1005.0,
        sleep=recorded.append,
    )

    assert waited == 25.0
    assert recorded == [25.0]
    assert state.read_text().strip() == "1005.0"


def test_ezproxy_throttle_caps_wait_against_future_timestamp(tmp_path):
    mod = _load_module(DOWNLOAD, "download_throttle_cap_under_test")
    state = tmp_path / "ezproxy-throttle.state"
    state.write_text("2000.0")  # far in the future vs. now()
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=30,
        now=lambda: 1000.0,
        sleep=recorded.append,
    )

    assert waited == 30.0
    assert recorded == [30.0]


def test_ezproxy_throttle_zero_interval_is_noop(tmp_path):
    mod = _load_module(DOWNLOAD, "download_throttle_zero_under_test")
    state = tmp_path / "missing.state"
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=0,
        now=lambda: 1000.0,
        sleep=recorded.append,
    )

    assert waited == 0.0
    assert recorded == []
    assert not state.exists()


def test_ezproxy_throttle_treats_corrupt_state_as_no_prior(tmp_path):
    mod = _load_module(DOWNLOAD, "download_throttle_corrupt_under_test")
    state = tmp_path / "ezproxy-throttle.state"
    state.write_text("not-a-number")
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=30,
        now=lambda: 1000.0,
        sleep=recorded.append,
    )

    assert waited == 0.0
    assert recorded == []
    assert state.read_text().strip() == "1000.0"


def test_ezproxy_min_interval_default_is_thirty():
    mod = _load_module(DOWNLOAD, "download_throttle_default_under_test")
    assert mod.EZPROXY_MIN_INTERVAL == 30


def test_ezproxy_throttle_serializes_across_processes(tmp_path):
    """Real cross-process proof: the exclusive lock is held across the sleep,
    so concurrent processes pass the gate at least one interval apart. A version
    that released the lock before sleeping would let all workers pass nearly
    simultaneously and fail this test."""
    import time

    state = tmp_path / "ezproxy-throttle.state"
    worker = tmp_path / "throttle_worker.py"
    worker.write_text(
        "import sys, time, importlib.util\n"
        "from pathlib import Path\n"
        "path = sys.argv[1]\n"
        "sys.path.insert(0, str(Path(path).parent))\n"
        "spec = importlib.util.spec_from_file_location('dl_worker', path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "mod._ezproxy_throttle(state_path=sys.argv[2], interval=1.0)\n"
        "sys.stdout.write(repr(time.time()))\n"
    )

    procs = [
        subprocess.Popen(
            [sys.executable, str(worker), str(DOWNLOAD), str(state)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    times = sorted(float(p.communicate()[0]) for p in procs)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.8 for g in gaps), (
        f"gate passes too close together (lock not held across sleep?): {gaps}"
    )


def test_try_ezproxy_download_skips_throttle_when_unconfigured(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_ezproxy_unconfigured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    out = tmp_path / "out.pdf"
    result = mod.try_ezproxy_download("10.1/example", str(out))

    assert result is False
    assert calls == []  # not configured -> gate never reached


def test_try_ezproxy_download_calls_throttle_when_configured(tmp_path, monkeypatch):
    import requests
    mod = _load_module(DOWNLOAD, "download_ezproxy_configured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {
            "login_url": "https://ezproxy.example.edu/login?url=",
            "cookie_records": [
                {"name": "a", "value": "b", "domain": "ezproxy.example.edu", "path": "/"}
            ],
        },
    )
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    def _boom(*a, **k):
        raise requests.RequestException("no network in test")

    monkeypatch.setattr(mod, "_retry", _boom)

    out = tmp_path / "out.pdf"
    result = mod.try_ezproxy_download("10.1/example", str(out))

    assert result is False
    assert calls == [1]  # gate reached exactly once when configured


def test_jstor_pdf_url_derived_from_stable_url_forms():
    mod = _load_module(DOWNLOAD, "download_jstor_urls_under_test")

    # Bare sequence id, DOI id, and an already-proxied host all resolve, and
    # acceptTC=1 is what separates the PDF from the terms-of-use interstitial.
    assert mod._jstor_pdf_urls_from_article_url(
        "https://www.jstor.org/stable/43154235"
    ) == ["https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1"]
    assert mod._jstor_pdf_urls_from_article_url(
        "https://www.jstor.org/stable/10.1086/691062"
    ) == ["https://www.jstor.org/stable/pdf/10.1086/691062.pdf?acceptTC=1"]
    assert mod._jstor_pdf_urls_from_article_url(
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf"
        "?refreqid=fastly-default%3Aabc&acceptTC=1"
    ) == [
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1"
    ]
    assert mod._jstor_pdf_urls_from_article_url("https://www.jstor.org/") == []
    assert mod._jstor_pdf_urls_from_article_url(
        "https://www.sciencedirect.com/stable/43154235"
    ) == []


def test_publisher_host_match_decodes_ezproxy_rewriting():
    mod = _load_module(DOWNLOAD, "download_publisher_host_under_test")

    # EZProxy packs the whole publisher host into one dash-joined label, so the
    # domain tables need no separate entry per proxied spelling.
    assert mod._unproxy_host("pubsonline-informs-org.eux.idm.oclc.org") == (
        "pubsonline.informs.org"
    )
    assert mod._unproxy_host("www.jstor.org") == "www.jstor.org"
    # A dash in a real publisher host is not proxy encoding.
    assert mod._unproxy_host("link-springer.com") == "link-springer.com"

    assert mod._is_publisher_host("www-jstor-org.eux.idm.oclc.org", "jstor.org")
    assert mod._is_publisher_host("academic.oup.com", "oup.com")
    assert mod._is_publisher_host("direct.mit.edu", "mit.edu")
    assert not mod._is_publisher_host("notjstor.org", "jstor.org")


def test_publisher_pdf_urls_derive_from_doi_carried_in_url_path():
    mod = _load_module(DOWNLOAD, "download_publisher_pdf_urls_under_test")

    assert mod._doi_from_url_path(
        "https://www.tandfonline.com/doi/abs/10.1080/00048402.2019.1618352"
    ) == "10.1080/00048402.2019.1618352"
    assert mod._doi_from_url_path("https://www.jstor.org/stable/43154235") is None

    assert mod._publisher_pdf_urls_from_article_url(
        "https://www.tandfonline.com/doi/abs/10.1080/00048402.2019.1618352"
    ) == [
        "https://www.tandfonline.com/doi/pdf/10.1080/00048402.2019.1618352",
        "https://www.tandfonline.com/doi/pdf/10.1080/00048402.2019.1618352"
        "?download=true",
    ]
    # A host with no pattern entry derives nothing, DOI in the path or not.
    assert mod._publisher_pdf_urls_from_article_url(
        "https://example.org/doi/abs/10.1080/00048402.2019.1618352"
    ) == []


def test_pdf_url_dispatcher_covers_every_derivation_family():
    mod = _load_module(DOWNLOAD, "download_pdf_url_dispatcher_under_test")

    # One entry point, so a platform added to any table reaches all three call
    # sites (hint collection, EZProxy landing, Kagi recovery) at once.
    assert mod._pdf_urls_from_article_url(
        "https://www.jstor.org/stable/43154235"
    ) == ["https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1"]
    assert (
        "https://journals.sagepub.com/doi/pdf/10.1177/0959354319898450"
        in mod._pdf_urls_from_article_url(
            "https://journals.sagepub.com/doi/abs/10.1177/0959354319898450"
        )
    )
    assert mod._pdf_urls_from_article_url("") == []


def test_ezproxy_request_urls_prefer_rewritten_host_over_login():
    mod = _load_module(DOWNLOAD, "download_ezproxy_request_forms_under_test")
    config = {
        "login_url": "https://login.eux.idm.oclc.org/login?url=",
        "domain": "idm.oclc.org",
        "cookie_records": [
            # The suffix the user's own browsing actually issued cookies on.
            {"name": "UUID", "value": "x",
             "domain": "www-jstor-org.eux.idm.oclc.org", "path": "/"},
            {"name": "_clsk", "value": "y", "domain": "idm.oclc.org", "path": "/"},
        ],
    }

    assert mod._ezproxy_host_suffix(config) == "eux.idm.oclc.org"
    assert mod._ezproxy_request_urls(
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1", config
    ) == [
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1",
        "https://login.eux.idm.oclc.org/login?url="
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]
    # An already-proxied URL is requested as-is, never double-wrapped.
    assert mod._ezproxy_request_urls(
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf", config
    ) == ["https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf"]


def test_ezproxy_host_suffix_falls_back_to_login_host_label():
    mod = _load_module(DOWNLOAD, "download_ezproxy_suffix_fallback_under_test")

    # No proxied cookies yet: drop the login service label, OCLC convention.
    assert mod._ezproxy_host_suffix(
        {"login_url": "https://login.eux.idm.oclc.org/login?url="}
    ) == "eux.idm.oclc.org"
    assert mod._ezproxy_host_suffix(
        {"login_url": "https://ezproxy.lib.example.edu/login?url="}
    ) == "lib.example.edu"
    # Nothing to drop: the whole host is the suffix.
    assert mod._ezproxy_host_suffix(
        {"login_url": "https://eux.idm.oclc.org/login?url="}
    ) == "eux.idm.oclc.org"


def test_download_paper_adds_jstor_pdf_hint_before_fetch(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_jstor_hints_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/stable/pdf/" in url:
            Path(output_path).write_bytes(b"%PDF- jstor")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        url="https://www.jstor.org/stable/43154235",
        output_dir=str(tmp_path),
        filename="jstor-paper",
    )

    assert result == str(tmp_path / "jstor-paper.pdf")
    assert tried == [
        "https://www.jstor.org/stable/43154235",
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]


def test_download_paper_routes_url_only_request_through_ezproxy(monkeypatch, tmp_path):
    """A URL-only request must reach the proxy; before this it never did."""
    mod = _load_module(DOWNLOAD, "download_url_only_ezproxy_under_test")
    requested: list[str] = []

    class FakeSession:
        headers: dict = {}

        def get(self, url, **kwargs):
            requested.append(url)
            if "/stable/pdf/" in url:
                return SimpleNamespace(
                    url="https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf",
                    content=b"%PDF- jstor via ezproxy",
                    status_code=200,
                    history=[object()],
                    headers={"content-type": "application/pdf"},
                )
            return SimpleNamespace(
                url="https://www-jstor-org.eux.idm.oclc.org/stable/43154235",
                content=b"<html>paywall</html>",
                status_code=200,
                history=[object()],
                headers={"content-type": "text/html"},
            )

    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *a, **k: False)
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://login.eux.idm.oclc.org/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    result = mod.download_paper(
        url="https://www.jstor.org/stable/43154235",
        output_dir=str(tmp_path),
        filename="jstor-paper",
    )

    assert result == str(tmp_path / "jstor-paper.pdf")
    assert requested == [
        "https://www-jstor-org.eux.idm.oclc.org/stable/43154235",
        "https://login.eux.idm.oclc.org/login?url=https://www.jstor.org/stable/43154235",
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]
    assert (tmp_path / "jstor-paper.pdf").read_bytes().startswith(b"%PDF-")


def test_ezproxy_url_download_keeps_already_proxied_url_unwrapped(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_proxied_url_passthrough_under_test")
    proxied = (
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1"
    )
    requested: list[str] = []

    class FakeSession:
        def get(self, url, **kwargs):
            requested.append(url)
            return SimpleNamespace(
                url=url,
                content=b"%PDF- already proxied",
                status_code=200,
                history=[object()],
                headers={"content-type": "application/pdf"},
            )

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {
            "login_url": "https://login.eux.idm.oclc.org/login?url=",
            "domain": "eux.idm.oclc.org",
            "cookie": "x",
        },
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    assert mod.try_ezproxy_url_download([proxied], str(tmp_path / "paper.pdf")) is True
    assert requested == [proxied]


def test_try_ezproxy_url_download_skips_throttle_when_unconfigured(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_url_ezproxy_unconfigured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    result = mod.try_ezproxy_url_download(
        ["https://www.jstor.org/stable/43154235"], str(tmp_path / "out.pdf")
    )

    assert result is False
    assert calls == []


# --- paper fetch identity gate ---

# The false-positive shape that once cleared verification with `status: ok`:
# a same-subfield paper contains every title keyword and cites the expected
# author, but is a different work under a different DOI.
_WRONG_PAPER_TEXT = (
    "agent causation is not prior to event causation\n"
    "soo lam wong\n"
    "disputatio, 2021. doi: 10.2478/disp-2021-0008\n"
    "keywords: agent causation, event causation, free action, production\n"
    "randolph clarke argues that agents produce free action by causing events.\n"
)

_RIGHT_PAPER_TEXT = (
    "agent causation and event causation in the production of free action\n"
    "author(s): randolph clarke\n"
    "source: philosophical topics, fall 1996, vol. 24, no. 2, pp. 19-48\n"
)

_CLARKE_IDENTITY = {
    "expected_author": "Randolph Clarke",
    "expected_title": (
        "Agent Causation and Event Causation in the Production of Free Action"
    ),
    "expected_doi": "10.5840/philtopics19962427",
}


def test_verify_rejects_same_subfield_paper_despite_full_keyword_overlap():
    mod = _load_module(DOWNLOAD, "verify_gate_wrong_paper_under_test")
    assert mod._verify_text_content(_WRONG_PAPER_TEXT, **_CLARKE_IDENTITY) is False


def test_verify_accepts_contiguous_title_phrase_with_author():
    mod = _load_module(DOWNLOAD, "verify_gate_right_paper_under_test")
    assert mod._verify_text_content(_RIGHT_PAPER_TEXT, **_CLARKE_IDENTITY) is True


def test_verify_accepts_embedded_requested_doi_without_title_phrase():
    mod = _load_module(DOWNLOAD, "verify_gate_doi_under_test")
    text = "untitled scan cover\nhttps://doi.org/10.5840/philtopics19962427\n"
    assert mod._verify_text_content(text, **_CLARKE_IDENTITY) is True


def test_verify_unextractable_text_still_passes():
    mod = _load_module(DOWNLOAD, "verify_gate_empty_under_test")
    assert mod._verify_text_content("", **_CLARKE_IDENTITY) is True


def test_verify_doi_only_request_keeps_old_scan_flow():
    mod = _load_module(DOWNLOAD, "verify_gate_doi_only_under_test")
    assert mod._verify_text_content(
        "an old scan with no printed doi",
        expected_doi="10.5840/philtopics19962427",
    ) is True


def _stub_paper_network(mod, monkeypatch):
    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *a, **k: False)
    monkeypatch.setattr(mod, "find_oa_url", lambda *a, **k: None)
    monkeypatch.setattr(mod, "try_scihub_download", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_publisher_direct", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_ezproxy_with_refresh", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_ezproxy_urls_with_refresh", lambda *a, **k: False)
    monkeypatch.setattr(mod, "find_wayback_url", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_kagi_discover_paper", lambda *a, **k: ([], []))


def test_download_paper_reverifies_and_deletes_wrong_existing_temp(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_exists_reverify_under_test")
    _stub_paper_network(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_extract_pdf_text", lambda *a, **k: _WRONG_PAPER_TEXT
    )
    leftover = tmp_path / "clarke-1996.pdf"
    leftover.write_bytes(b"%PDF- wrong paper " + b"x" * 2000)

    result = mod.download_paper(
        doi="10.5840/philtopics19962427",
        output_dir=str(tmp_path),
        filename="clarke-1996",
        verify_author="Randolph Clarke",
        verify_title=(
            "Agent Causation and Event Causation in the Production of Free Action"
        ),
    )

    assert result is None
    assert not leftover.exists()


def test_download_paper_serves_existing_temp_that_proves_identity(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_exists_proven_under_test")

    def _forbidden(*a, **k):
        raise AssertionError("network path must not run for a proven temp file")

    for name in (
        "download_pdf_from_url", "find_oa_url", "try_scihub_download",
        "_try_publisher_direct", "_try_ezproxy_with_refresh",
        "_try_ezproxy_urls_with_refresh", "find_wayback_url",
        "_kagi_discover_paper",
    ):
        monkeypatch.setattr(mod, name, _forbidden)
    monkeypatch.setattr(
        mod, "_extract_pdf_text", lambda *a, **k: _RIGHT_PAPER_TEXT
    )
    existing = tmp_path / "clarke-1996.pdf"
    existing.write_bytes(b"%PDF- right paper " + b"x" * 2000)

    result = mod.download_paper(
        doi="10.5840/philtopics19962427",
        output_dir=str(tmp_path),
        filename="clarke-1996",
        verify_author="Randolph Clarke",
        verify_title=(
            "Agent Causation and Event Causation in the Production of Free Action"
        ),
    )

    assert result == str(existing)


def test_download_paper_derives_jstor_stable_hint_from_jstor_doi(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_jstor_doi_hint_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/stable/pdf/" in url:
            Path(output_path).write_bytes(b"%PDF- jstor")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        doi="10.2307/43154235",
        output_dir=str(tmp_path),
        filename="jstor-doi-paper",
    )

    assert result == str(tmp_path / "jstor-doi-paper.pdf")
    assert tried == [
        "https://www.jstor.org/stable/43154235",
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]
