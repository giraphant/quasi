#!/usr/bin/env python3
"""Unit tests: English book title → Chinese translation metadata via douban_cn.

Tests the full pipeline: query with English title/author → Douban search →
parse subject page → normalise to BookRecord → verify Chinese translation
fields (translators, original_title, publisher, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import douban_cn

# ── Fixtures: realistic Douban HTML fragments ──

SEARCH_RESULTS_HTML = """
<html><head><title>搜索结果</title></head><body>
<div class="result">
  <div class="title"><a href="https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F35erta123%2F&query=Staying+with+the+Trouble">
    与麻烦同在</a></div>
</div>
<div class="result">
  <div class="title"><a href="https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F36512345%2F&query=Staying+with+the+Trouble">
    Staying with the Trouble</a></div>
</div>
</body></html>
"""

SUBJECT_PAGE_ZH_TRANSLATION = """
<html><head><title>与麻烦同在 (豆瓣)</title></head><body>
<div id="wrapper">
  <h1><span property="v:itemreviewed">与麻烦同在</span></h1>
  <div id="info">
    <span class="pl">作者</span>
    <a href="/author/4567/">[美] 唐娜·哈拉维</a>
    <br/>
    <span class="pl">出版社</span>
    华东师范大学出版社
    <br/>
    <span class="pl">原作名:</span> Staying with the Trouble: Making Kin in the Chthulucene
    <br/>
    <span class="pl">译者</span>
    <a href="/search/赵文">赵文</a>
    <br/>
    <span class="pl">出版年:</span> 2024
    <br/>
    <span class="pl">页数:</span> 320
    <br/>
    <span class="pl">ISBN:</span> 9787576048971
    <br/>
    <span class="pl">丛书:</span> 薄荷实验
    <br/>
  </div>
  <div>
    <strong property="v:average">8.6</strong>
    <span property="v:votes">1523</span>
  </div>
  <div id="link-report">
    <div class="intro">
      <p>本书是唐娜·哈拉维最重要的近作之一。哈拉维在本书中提出了"与麻烦同在"的理念。</p>
    </div>
  </div>
</div>
<a class="nbg" href="https://img9.doubanio.com/view/subject/l/public/s34567890.jpg">cover</a>
<script>criteria = '7:哲学|7:女性主义|7:科技研究';</script>
</body></html>
"""

SUBJECT_PAGE_EN_ORIGINAL = """
<html><head><title>Staying with the Trouble (豆瓣)</title></head><body>
<div id="wrapper">
  <h1><span property="v:itemreviewed">Staying with the Trouble</span></h1>
  <div id="info">
    <span class="pl">作者</span>
    <a href="/author/1234/">Donna J. Haraway</a>
    <br/>
    <span class="pl">出版社</span>
    Duke University Press
    <br/>
    <span class="pl">出版年:</span> 2016
    <br/>
    <span class="pl">ISBN:</span> 9780822373780
    <br/>
  </div>
  <div>
    <strong property="v:average">9.1</strong>
    <span property="v:votes">856</span>
  </div>
</div>
</body></html>
"""


# ── Tests: HTML parsing ──

def test_parse_subject_page_zh_translation_fields():
    """Verify _parse_dd_subject_page extracts all Chinese translation metadata."""
    url = "https://book.douban.com/subject/35erta123/"
    result = douban_cn._parse_dd_subject_page(
        SUBJECT_PAGE_ZH_TRANSLATION, url
    )
    assert result is not None
    assert result["title"] == "与麻烦同在"
    assert result["original_title"] == "Staying with the Trouble: Making Kin in the Chthulucene"
    assert "赵文" in result["translators"]
    assert "华东师范大学出版社" in result["publisher"]
    assert result["year"] == 2024
    assert result["isbn_13"] == "9787576048971"
    assert result["douban_rating"] == 8.6
    assert result["ratings_count"] == 1523
    assert result["series"] == "薄荷实验"
    assert "哲学" in result["categories"]
    assert "女性主义" in result["categories"]


def test_parse_subject_page_en_original():
    """Verify parsing an original English edition returns no translators."""
    url = "https://book.douban.com/subject/36512345/"
    result = douban_cn._parse_dd_subject_page(
        SUBJECT_PAGE_EN_ORIGINAL, url
    )
    assert result is not None
    assert result["title"] == "Staying with the Trouble"
    assert "Donna J. Haraway" in result["authors"]
    assert result["translators"] == []
    assert result["publisher"] == "Duke University Press"
    assert result["year"] == 2016
    assert result["original_title"] == ""


# ── Tests: normalisation ──

def test_normalise_zh_translation_to_book_record():
    """Verify _normalise maps raw douban result to BookRecord schema with language=zh."""
    raw = {
        "title": "与麻烦同在",
        "authors": ["[美] 唐娜·哈拉维"],
        "translators": ["赵文"],
        "original_title": "Staying with the Trouble",
        "year": 2024,
        "publisher": "华东师范大学出版社",
        "isbn": "9787576048971",
        "douban_url": "https://book.douban.com/subject/35erta123/",
        "douban_id": "35erta123",
        "ratings_count": 1523,
        "douban_rating": 8.6,
    }
    norm = douban_cn._normalise(raw)
    assert norm["title"] == "与麻烦同在"
    assert norm["language"] == "zh"
    assert norm["original_title"] == "Staying with the Trouble"
    assert norm["translators"] == ["赵文"]
    assert norm["authors"] == ["[美] 唐娜·哈拉维"]
    assert norm["isbn_13"] == "9787576048971"
    assert norm["publisher"] == "华东师范大学出版社"
    assert norm["source_ids"]["douban_cn"] == "35erta123"
    assert norm["ratings"]["count"] == 1523
    assert norm["ratings"]["average"] == 8.6
    assert "douban_cn" in norm["_sources"]


def test_normalise_keeps_isbn_from_direct_path():
    """_normalise preserves ISBN from both direct and cndouban paths."""
    raw_from_direct = {
        "title": "与麻烦同在",
        "isbn_13": "9787576048971",
        "isbn_10": None,
        "douban_subject_id": "123",
    }
    norm = douban_cn._normalise(raw_from_direct)
    assert norm["isbn_13"] == "9787576048971"

    # Contrast: cndouban path uses "isbn" key — this works
    raw_from_cndouban = {
        "title": "与麻烦同在",
        "isbn": "9787576048971",
        "douban_id": "123",
    }
    norm2 = douban_cn._normalise(raw_from_cndouban)
    assert norm2["isbn_13"] == "9787576048971"


def test_normalise_handles_missing_fields():
    """_normalise should not crash on sparse raw dicts."""
    raw = {"title": "测试书", "douban_id": "999"}
    norm = douban_cn._normalise(raw)
    assert norm["title"] == "测试书"
    assert norm["translators"] == []
    assert norm["authors"] == []
    assert norm["isbn_13"] is None
    assert norm["language"] == "zh"


# ── Tests: end-to-end search_book with mocked HTTP ──

def test_search_book_english_title_returns_zh_translation():
    """Full pipeline: English title → direct search → parse → normalised BookRecord."""
    call_count = {"n": 0}

    def mock_dd_fetch(url, cookie=None, timeout=20):
        call_count["n"] += 1
        if "douban.com/search" in url:
            return True, SEARCH_RESULTS_HTML
        if "subject/35erta123" in url:
            return True, SUBJECT_PAGE_ZH_TRANSLATION
        if "subject/36512345" in url:
            return True, SUBJECT_PAGE_EN_ORIGINAL
        return False, "not found"

    with patch("sources.douban_cn._dd_fetch", side_effect=mock_dd_fetch):
        q = search.BookQuery(
            title="Staying with the Trouble",
            author="Donna Haraway",
            limit=5,
        )
        result = douban_cn.search_book(q)

    assert result.success is True
    assert len(result.entries) >= 1

    zh_entries = [e for e in result.entries if e.get("language") == "zh"]
    assert len(zh_entries) >= 1

    zh = zh_entries[0]
    assert "与麻烦同在" in zh["title"]
    assert zh["original_title"] == "Staying with the Trouble: Making Kin in the Chthulucene"
    assert len(zh["translators"]) > 0
    assert zh["isbn_13"] == "9787576048971"


def test_search_book_with_subject_zh_triggers_works_fallback():
    """When subject='zh' and direct returns empty, works-page fallback is tried."""
    works_result = [{
        "title": "类人猿、赛博格和女人",
        "year": 2022,
        "douban_subject_id": "9999",
        "translator": "翻译者A",
        "publisher": "南京大学出版社",
    }]

    with patch("sources.douban_cn._direct_search", return_value=[]), \
         patch("sources.douban_cn._cndouban_works_page", return_value=works_result) as mock_fb:
        q = search.BookQuery(title="Simians Cyborgs and Women", subject="zh", limit=5)
        result = douban_cn.search_book(q)

    assert mock_fb.called
    assert result.success is True
    assert len(result.entries) >= 1
    assert result.entries[0]["title"] == "类人猿、赛博格和女人"


def test_search_book_empty_query_returns_no_results():
    """No query params → no results, no crash."""
    result = douban_cn.search_book(search.BookQuery())
    assert result.success is False or len(result.entries) == 0


def test_search_book_blocked_returns_empty():
    """When Douban blocks the request, should return empty results gracefully."""
    blocked_html = "<html><head><title>禁止访问</title></head><body>检测到有异常请求</body></html>"

    def mock_dd_fetch(url, cookie=None, timeout=20):
        return True, blocked_html

    with patch("sources.douban_cn._dd_fetch", side_effect=mock_dd_fetch):
        q = search.BookQuery(title="Some Book", limit=5)
        result = douban_cn.search_book(q)

    assert result.success is True
    assert len(result.entries) == 0


# ── Tests: helper functions ──

def test_has_cjk_detects_chinese():
    assert douban_cn._has_cjk("华东师范大学出版社") is True
    assert douban_cn._has_cjk("Duke University Press") is False
    assert douban_cn._has_cjk("Mixed 中英 text") is True
    assert douban_cn._has_cjk("") is False


def test_is_blocked_detects_ban():
    assert douban_cn._is_blocked("<title>禁止访问</title>") is True
    assert douban_cn._is_blocked("检测到有异常请求 blah") is True
    assert douban_cn._is_blocked("<title>搜索结果</title>") is False


def test_calc_url_extracts_subject():
    href = "https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F12345%2F&query=test"
    assert douban_cn._calc_url(href) == "https://book.douban.com/subject/12345/"


def test_calc_url_returns_none_for_non_subject():
    href = "https://www.douban.com/link2/?url=https%3A%2F%2Fwww.example.com&query=test"
    assert douban_cn._calc_url(href) is None


def test_get_text_after_label():
    html = '<span class="pl">出版社:</span>华东师范大学出版社<br/>'
    assert "华东师范大学出版社" in douban_cn._get_text_after_label(html, "出版社")


def test_get_authors_from_block():
    html = '''<span class="pl">译者</span>
    <a href="/search/赵文">赵文</a> /
    <a href="/search/李明">李明</a>
    <br/>'''
    authors = douban_cn._get_authors_from_block(html, "译者")
    assert "赵文" in authors
    assert "李明" in authors


# ── Tests: cndouban works-page pipeline ──

def test_find_cndouban_no_inputs():
    """No inputs returns error status."""
    result = douban_cn._find_cndouban()
    assert result["status"] == "error"
    assert result["primary_subject"] is None


def test_find_cndouban_with_dokobot_unavailable():
    """When dokobot is not available, should fallback gracefully."""
    with patch("shutil.which", return_value=None):
        result = douban_cn._find_cndouban(
            title="Staying with the Trouble",
            author="Donna Haraway",
        )
    assert result["status"] == "no-douban-entry"
    assert "DOKO_NOT_AVAILABLE" in str(result["diagnostics"]["warnings"])


def test_parse_cn_subject_page_from_doko_text():
    """Verify _parse_cn_subject_page extracts from dokobot-rendered plain text."""
    body = """
与麻烦同在
作者: [美] 唐娜·哈拉维
译者: 赵文
出版社: 华东师范大学出版社
出版年: 2024
ISBN: 9787576048971
原作名: Staying with the Trouble
1523人评价
"""
    result = douban_cn._parse_cn_subject_page(body, "35erta123")
    assert result["title"] == "与麻烦同在"
    assert result["author"] == "[美] 唐娜·哈拉维"
    assert result["translator"] == "赵文"
    assert result["publisher"] == "华东师范大学出版社"
    assert result["year"] == 2024
    assert result["isbn"] == "9787576048971"
    assert result["original_title"] == "Staying with the Trouble"
    assert result["ratings_count"] == 1523


def test_extract_manifestations_from_works_page():
    """Verify works-page parsing extracts subject IDs with publisher/year hints."""
    body = """
全部版本(5)
上海人民出版社 (2022)
https://book.douban.com/subject/11111111/
Duke University Press (2016)
https://book.douban.com/subject/22222222/
华东师范大学出版社 (2024)
https://book.douban.com/subject/33333333/
"""
    results = douban_cn._extract_manifestations_from_works_page(body)
    assert len(results) == 3
    ids = [r["subject_id"] for r in results]
    assert "11111111" in ids
    assert "22222222" in ids
    assert "33333333" in ids


def test_direct_search_impl_year_filter():
    """_direct_search_impl respects year_from/year_to filters."""
    search_html = '<a href="https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F111%2F&query=test">x</a>'

    def mock_fetch(url, cookie=None, timeout=20):
        if "search" in url:
            return True, search_html
        return True, SUBJECT_PAGE_EN_ORIGINAL  # year=2016

    with patch("sources.douban_cn._dd_fetch", side_effect=mock_fetch):
        result = douban_cn._direct_search_impl("test", limit=5, year_from=2020)

    assert result["count"] == 0


def test_direct_search_impl_returns_results():
    """_direct_search_impl returns parsed results for valid pages."""
    search_html = '<a href="https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F35erta123%2F&query=test">x</a>'

    def mock_fetch(url, cookie=None, timeout=20):
        if "search" in url:
            return True, search_html
        return True, SUBJECT_PAGE_ZH_TRANSLATION

    with patch("sources.douban_cn._dd_fetch", side_effect=mock_fetch):
        result = douban_cn._direct_search_impl("与麻烦同在", limit=5)

    assert result["success"] is True
    assert result["count"] >= 1
    assert result["results"][0]["title"] == "与麻烦同在"
    assert result["results"][0]["original_title"] == "Staying with the Trouble: Making Kin in the Chthulucene"
    assert "赵文" in result["results"][0]["translators"]


# ── Runner ──

def main():
    tests = [
        test_parse_subject_page_zh_translation_fields,
        test_parse_subject_page_en_original,
        test_normalise_zh_translation_to_book_record,
        test_normalise_drops_isbn_from_direct_path,
        test_normalise_handles_missing_fields,
        test_search_book_english_title_returns_zh_translation,
        test_search_book_with_subject_zh_triggers_works_fallback,
        test_search_book_empty_query_returns_no_results,
        test_search_book_blocked_returns_empty,
        test_has_cjk_detects_chinese,
        test_is_blocked_detects_ban,
        test_calc_url_extracts_subject,
        test_calc_url_returns_none_for_non_subject,
        test_get_text_after_label,
        test_get_authors_from_block,
        test_find_cndouban_no_inputs,
        test_find_cndouban_with_dokobot_unavailable,
        test_parse_cn_subject_page_from_doko_text,
        test_extract_manifestations_from_works_page,
        test_direct_search_impl_year_filter,
        test_direct_search_impl_returns_results,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
