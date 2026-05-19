#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import douban_cn


def test_supports():
    assert douban_cn.SUPPORTS == ["book"]


def test_general_metadata_query_uses_direct_path_first():
    """General metadata lookup keeps direct path first."""
    fake_direct = [{"title": "X", "year": 2020, "douban_subject_id": "1"}]
    with patch("sources.douban_cn._direct_search", return_value=fake_direct), \
         patch("sources.douban_cn._cndouban_works_page", return_value=[]) as mock_fb, \
         patch("sources.douban_cn._related_version_search", return_value=[]) as mock_related:
        r = douban_cn.search_book(search.BookQuery(title="X"))
    assert r.success is True
    assert len(r.entries) == 1
    assert not mock_fb.called
    assert not mock_related.called


def test_cjk_author_triggers_works_page():
    """When --author contains CJK, also enumerate works page for translations."""
    with patch("sources.douban_cn._direct_search", return_value=[]), \
         patch("sources.douban_cn._cndouban_works_page", return_value=[
             {"title": "原书中文版", "year": 2022, "douban_subject_id": "2"}
         ]) as mock_fb:
        r = douban_cn.search_book(search.BookQuery(author="哈拉维"))
    assert r.success is True
    assert mock_fb.called
    assert r.entries[0]["title"] == "原书中文版"


def test_subject_zh_uses_cndouban_subject_page_first():
    """--subject zh uses Doko subject-page lookup before the direct scraper."""
    fake_works = [{
        "title": "原书中文版",
        "publisher": "河南大学出版社",
        "year": 2012,
        "douban_subject_id": "2",
        "douban_url": "https://book.douban.com/subject/2/",
        "isbn_13": "9787564906962",
    }]
    with patch("sources.douban_cn._direct_search", return_value=[]) as mock_direct, \
         patch("sources.douban_cn._related_version_search", return_value=[]) as mock_related, \
         patch("sources.douban_cn._cndouban_works_payload", return_value={"status": "ok", "translations": fake_works}) as mock_fb:
        r = douban_cn.search_book(search.BookQuery(title="Original", subject="zh"))
    assert r.success is True
    assert mock_fb.called
    assert not mock_direct.called
    assert not mock_related.called
    assert len(r.entries) == 1
    assert r.entries[0]["title"] == "原书中文版"
    assert r.entries[0]["isbn_13"] == "9787564906962"


def test_find_cndouban_uses_kagi_site_before_douban_search():
    """Title/author localisation discovers Douban subjects through Kagi first."""
    urls: list[str] = []

    def fake_doko_read(url, timeout=60):
        urls.append(url)
        if "book.douban.com/subject/2/" in url:
            return True, """
原书中文版
作者: Example Author
译者: 译者甲
出版社: 河南大学出版社
出版年: 2012
ISBN: 9787564906962
"""
        return False, "unexpected"

    with patch("sources.douban_cn._kagi_site_subject_urls",
               return_value=(["https://book.douban.com/subject/2/"], [])) as mock_kagi, \
         patch("sources.douban_cn._doko_read", side_effect=fake_doko_read):
        result = douban_cn._find_cndouban(title="Original", author="Example Author")

    assert result["status"] == "ok"
    assert result["translations"][0]["douban_id"] == "2"
    assert result["diagnostics"]["doko_calls"] == 1
    mock_kagi.assert_called_once()
    assert any("book.douban.com/subject/2/" in url for url in urls)
    assert not any("search.douban.com" in url for url in urls)


def test_find_cndouban_follows_related_version_link_after_kagi_subject():
    """After Kagi finds the original subject, localisation follows version links directly."""
    urls: list[str] = []

    def fake_doko_read(url, timeout=60):
        urls.append(url)
        if "book.douban.com/subject/1/" in url:
            return True, """
# Original (豆瓣)
作者: Example Author
出版社: Example Press
出版年: 2001
ISBN: 9780000000001
其他版本
原书中文版 [2]
[2] https://book.douban.com/subject/2/
"""
        if "book.douban.com/subject/2/" in url:
            return True, """
# 原书中文版 (豆瓣)
作者: Example Author
译者: 译者甲
出版社: 河南大学出版社
出版年: 2012
ISBN: 9787564906962
123人评价
"""
        return False, "unexpected"

    with patch("sources.douban_cn._kagi_site_subject_urls",
               return_value=(["https://book.douban.com/subject/1/"], [])) as mock_kagi, \
         patch("sources.douban_cn._doko_read", side_effect=fake_doko_read):
        result = douban_cn._find_cndouban(title="Original", author="Example Author")

    assert result["status"] == "ok"
    assert result["translations"][0]["douban_id"] == "2"
    assert result["diagnostics"]["routing"] == [
        "kagi-site-title-author",
        "related-version-links",
    ]
    assert result["diagnostics"]["doko_calls"] == 2
    mock_kagi.assert_called_once()
    assert any("book.douban.com/subject/1/" in url for url in urls)
    assert any("book.douban.com/subject/2/" in url for url in urls)
    assert not any("search.douban.com" in url for url in urls)


def test_find_cndouban_degrades_isbn_to_kagi_to_related_version():
    """Full fallback order: ISBN direct, Kagi subject discovery, then direct related-version links."""
    urls: list[str] = []

    def fake_doko_read(url, timeout=60):
        urls.append(url)
        if "book.douban.com/isbn/" in url:
            return False, "isbn miss"
        if "book.douban.com/subject/1/" in url:
            return True, """
# Original (豆瓣)
作者: Example Author
出版社: Example Press
出版年: 2001
ISBN: 9780000000001
其他版本
原书中文版 [2]
[2] https://book.douban.com/subject/2/
"""
        if "book.douban.com/subject/2/" in url:
            return True, """
# 原书中文版 (豆瓣)
作者: Example Author
译者: 译者甲
出版社: 河南大学出版社
出版年: 2012
ISBN: 9787564906962
123人评价
"""
        return False, "unexpected"

    with patch("sources.douban_cn._kagi_site_subject_urls",
               return_value=(["https://book.douban.com/subject/1/"], [])) as mock_kagi, \
         patch("sources.douban_cn._doko_read", side_effect=fake_doko_read):
        result = douban_cn._find_cndouban(
            isbn="9780000000001",
            title="Original",
            author="Example Author",
        )

    assert result["status"] == "ok"
    assert result["translations"][0]["douban_id"] == "2"
    assert result["diagnostics"]["routing"] == [
        "isbn-direct",
        "kagi-site-title-author",
        "related-version-links",
    ]
    assert result["diagnostics"]["doko_calls"] == 3
    mock_kagi.assert_called_once()
    assert any("book.douban.com/isbn/" in url for url in urls)
    assert any("book.douban.com/subject/1/" in url for url in urls)
    assert any("book.douban.com/subject/2/" in url for url in urls)
    assert not any("search.douban.com" in url for url in urls)


def test_subject_zh_falls_back_to_related_versions_when_cndouban_empty():
    """If Doko subject-page lookup is empty, Kagi-seeded related probe runs before direct search."""
    fake_related = [{
        "title": "原书中文版",
        "publisher": "河南大学出版社",
        "year": 2012,
        "douban_subject_id": "2",
        "douban_url": "https://book.douban.com/subject/2/",
    }]
    with patch("sources.douban_cn._cndouban_works_payload", return_value={"status": "no-translations", "translations": []}) as mock_fb, \
         patch("sources.douban_cn._direct_search", return_value=[]) as mock_direct, \
         patch("sources.douban_cn._related_version_search", return_value=fake_related) as mock_related:
        r = douban_cn.search_book(search.BookQuery(title="Original", subject="zh"))
    assert r.success is True
    assert mock_fb.called
    assert not mock_direct.called
    assert mock_related.called
    assert r.entries[0]["title"] == "原书中文版"


def test_related_version_search_uses_kagi_seed_before_douban_search():
    urls: list[str] = []

    def fake_doko_read(url, timeout=60):
        urls.append(url)
        if "book.douban.com/subject/1/" in url:
            return True, """
# Original (豆瓣)
作者: Example Author 出版社: Example Press 出版年: 2001 ISBN: 9780000000001
其他版本
原书中文版 [2]
[2] https://book.douban.com/subject/2/
"""
        if "book.douban.com/subject/2/" in url:
            return True, """
# 原书中文版 (豆瓣)
作者: Example Author 译者: 译者甲 出版社: 河南大学出版社 出版年: 2012 ISBN: 9787564906962
123人评价
"""
        return False, "unexpected"

    with patch("sources.douban_cn._dd_fetch", return_value=(False, "skip direct")), \
         patch("sources.douban_cn._kagi_site_subject_urls",
               return_value=(["https://book.douban.com/subject/1/"], [])) as mock_kagi, \
         patch("sources.douban_cn._doko_read", side_effect=fake_doko_read):
        results = douban_cn._related_version_search(
            search.BookQuery(title="Original", author="Example Author", limit=5),
            direct_hits=[],
        )

    assert results[0]["douban_subject_id"] == "2"
    mock_kagi.assert_called_once()
    assert not any("search.douban.com" in url for url in urls)


def test_kagi_site_subject_urls_never_uses_doko():
    payload = {"data": [{"url": "https://book.douban.com/subject/12345/"}]}
    completed = type("Completed", (), {
        "returncode": 0,
        "stdout": json.dumps(payload),
        "stderr": "",
    })()
    with patch("sources.douban_cn.shutil.which", return_value="/bin/kagi"), \
         patch("sources.douban_cn.subprocess.run", return_value=completed) as mock_run, \
         patch("sources.douban_cn._doko_read") as mock_doko:
        urls, warnings = douban_cn._kagi_site_subject_urls("Example Book")

    assert urls == ["https://book.douban.com/subject/12345/"]
    assert warnings == []
    mock_run.assert_called_once()
    mock_doko.assert_not_called()


def test_kagi_site_subject_query_has_only_site_limiter():
    query = douban_cn._kagi_site_subject_query("Strange Encounters Sara Ahmed")
    assert query == "site:book.douban.com/subject Strange Encounters Sara Ahmed"


def test_compact_external_book_query_removes_subtitle_and_newline():
    q = douban_cn._compact_external_book_query(
        title="Strange Encounters: Embodied Others in\n         Post-Coloniality",
        author="Sara Ahmed",
    )
    assert q == "Strange Encounters Sara Ahmed"
    assert "\n" not in q
    assert "Post-Coloniality" not in q


def test_subject_zh_allows_douban_search_fallback_when_kagi_empty():
    calls: list[str] = []

    def fake_doko_read(url, timeout=60):
        calls.append(url)
        return False, "no hit"

    with patch("sources.douban_cn._cndouban_works_payload", return_value={"status": "no-douban-entry", "translations": []}), \
         patch("sources.douban_cn._kagi_site_subject_urls", return_value=([], ["no kagi hit"])), \
         patch("sources.douban_cn._doko_read", side_effect=fake_doko_read), \
         patch("sources.douban_cn._direct_search", return_value=[]):
        result = douban_cn.search_book(search.BookQuery(title="Original", author="Example Author", subject="zh"))

    assert result.success is True
    assert any("search.douban.com" in url for url in calls)


def test_extract_external_subject_urls_decodes_redirects():
    html = '''
    <a href="/url?q=https%3A%2F%2Fbook.douban.com%2Fsubject%2F12345%2F&sa=U">x</a>
    <a href="https://book.douban.com/subject/67890/">y</a>
    '''
    assert douban_cn._extract_subject_urls_from_external_text(html) == [
        "https://book.douban.com/subject/12345/",
        "https://book.douban.com/subject/67890/",
    ]


def test_subject_zh_reports_doko_unavailable_when_no_fallback_result():
    payload = {
        "status": "error",
        "translations": [],
        "diagnostics": {"warnings": ["isbn-direct: DOKO_NOT_AVAILABLE"]},
    }
    with patch("sources.douban_cn._cndouban_works_payload", return_value=payload), \
         patch("sources.douban_cn._related_version_search", return_value=[]), \
         patch("sources.douban_cn._direct_search", return_value=[]):
        r = douban_cn.search_book(search.BookQuery(title="Original", subject="zh"))
    assert r.success is False
    assert "DOKO_NOT_AVAILABLE" in (r.error or "")


def test_parse_doko_references_decodes_link2_subject_url():
    body = """
    [35] https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F4175504%2F&query=X
    """
    refs = douban_cn._parse_doko_references(body)
    assert refs["35"] == "https://book.douban.com/subject/4175504/"


def test_parse_doko_subject_page_handles_inline_metadata():
    body = """
    # Cyborg Manifesto (豆瓣)
    **Cyborg Manifesto**
    作者: Donna J. Haraway [21]出版社: Feltrinelli出版年: 1995 ISBN: 9788807460012页数: 194装帧: Paperback
    8.7
    199人评价 [3]
    """
    parsed = douban_cn._parse_doko_subject_page(body, "https://book.douban.com/subject/4175504/")
    assert parsed is not None
    assert parsed["title"] == "Cyborg Manifesto"
    assert parsed["authors"] == ["Donna J. Haraway"]
    assert parsed["publisher"] == "Feltrinelli"
    assert parsed["year"] == 1995
    assert parsed["isbn_13"] == "9788807460012"
    assert parsed["ratings_count"] == 199


def main():
    tests = [
        test_supports,
        test_general_metadata_query_uses_direct_path_first,
        test_cjk_author_triggers_works_page,
        test_subject_zh_uses_cndouban_subject_page_first,
        test_find_cndouban_uses_kagi_site_before_douban_search,
        test_find_cndouban_follows_related_version_link_after_kagi_subject,
        test_find_cndouban_degrades_isbn_to_kagi_to_related_version,
        test_subject_zh_falls_back_to_related_versions_when_cndouban_empty,
        test_related_version_search_uses_kagi_seed_before_douban_search,
        test_kagi_site_subject_urls_never_uses_doko,
        test_kagi_site_subject_query_has_only_site_limiter,
        test_compact_external_book_query_removes_subtitle_and_newline,
        test_subject_zh_allows_douban_search_fallback_when_kagi_empty,
        test_extract_external_subject_urls_decodes_redirects,
        test_subject_zh_reports_doko_unavailable_when_no_fallback_result,
        test_parse_doko_references_decodes_link2_subject_url,
        test_parse_doko_subject_page_handles_inline_metadata,
    ]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
