from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = PLUGIN_ROOT / "scripts" / "download" / "download.py"
COOKIECLOUD = PLUGIN_ROOT / "scripts" / "download" / "cookiecloud.py"


def run_download(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOWNLOAD), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_download_help_exposes_agent_contract():
    top = run_download("--help")
    assert top.returncode == 0
    assert "{book,paper,accept}" in top.stdout

    for args in [
        ("book", "candidates", "--help"),
        ("book", "fetch", "--help"),
        ("paper", "fetch", "--help"),
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
    doi = "10.1287/ijoc.2024.0736"

    urls = [
        f"https://pubsonline-informs-org.eux.idm.oclc.org{pattern.format(doi=doi)}"
        for hint, pattern in mod.PUBLISHER_PDF_PATTERNS
        if hint in final_url
    ]

    assert urls == [
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


def test_dokobot_read_url_falls_back_when_local_bridge_is_unavailable(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_dokobot_fallback_under_test")
    calls: list[list[str]] = []

    def fake_run(args, capture_output, text, timeout, check):
        calls.append(args)
        if "--local" in args:
            return subprocess.CompletedProcess(args, 1, "", "local bridge unavailable")
        body = "Making sense of conduct\nTherapist formulation\n" + "article body " * 120
        return subprocess.CompletedProcess(args, 0, body, "")

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/dokobot")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    text = mod._dokobot_read_url(
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025",
        timeout=5,
    )

    assert text.startswith("Making sense of conduct")
    assert calls == [
        [
            "dokobot",
            "read",
            "--local",
            "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025",
        ],
        [
            "dokobot",
            "read",
            "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025",
        ],
    ]


def test_dokobot_read_url_rejects_short_text(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_dokobot_short_text_under_test")

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/dokobot")
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "too short", ""),
    )

    assert mod._dokobot_read_url("https://www.sciencedirect.com/science/article/pii/S0378216626001025") is None


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


def test_download_paper_uses_sciencedirect_text_after_pdf_sources_fail(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_sciencedirect_text_flow_under_test")
    article_url = "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"

    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "find_oa_url", lambda doi: None)
    monkeypatch.setattr(mod, "try_scihub_download", lambda *args: False)
    monkeypatch.setattr(mod, "_try_publisher_direct", lambda *args: False)
    monkeypatch.setattr(mod, "find_wayback_url", lambda doi: None)
    monkeypatch.setattr(mod, "_kagi_discover_paper", lambda title, author=None: ([], []))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)

    def fake_ezproxy(doi, output_path, sciencedirect_urls=None):
        if sciencedirect_urls is not None:
            sciencedirect_urls.append(article_url)
        return False

    monkeypatch.setattr(mod, "_try_ezproxy_with_refresh", fake_ezproxy)
    dokobot_calls = []

    def fake_dokobot_read_url(url):
        dokobot_calls.append(url)
        if url != article_url:
            return None
        return (
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children\n"
            + "therapist formulation autistic children " * 80
        )

    monkeypatch.setattr(mod, "_dokobot_read_url", fake_dokobot_read_url)

    result = mod.download_paper(
        doi="10.1016/j.pragma.2026.04.009",
        output_dir=str(tmp_path),
        filename="making-sense-conduct-2026",
        verify_title=(
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children"
        ),
    )

    assert result == str(tmp_path / "making-sense-conduct-2026.txt")
    assert (tmp_path / "making-sense-conduct-2026.txt").read_text(encoding="utf-8").startswith(
        "Making sense of conduct"
    )
    assert not (tmp_path / "making-sense-conduct-2026.pdf").exists()
    assert dokobot_calls == [article_url]


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
