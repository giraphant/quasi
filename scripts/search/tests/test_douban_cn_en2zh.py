#!/usr/bin/env python3
"""Unit tests: English book title → Chinese translation metadata via douban_cn.

Tests the full pipeline: query with English title/author → Kagi
discovery + BeautifulSoup parsing → normalised BookRecord → verify
Chinese translation fields (translators, original_title, publisher,
ISBN agency prefix, etc.).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

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


# ── HTML parsing (direct path) ──

def test_parse_subject_page_zh_translation_fields():
    url = "https://book.douban.com/subject/3512345/"
    with patch("sources.douban_cn._dd_fetch", return_value=(True, SUBJECT_PAGE_ZH_TRANSLATION)):
        result = douban_cn._fetch_subject_via_bs4(url)
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


def test_parse_subject_page_en_original():
    url = "https://book.douban.com/subject/36512345/"
    with patch("sources.douban_cn._dd_fetch", return_value=(True, SUBJECT_PAGE_EN_ORIGINAL)):
        result = douban_cn._fetch_subject_via_bs4(url)
    assert result is not None
    assert result["title"] == "Staying with the Trouble"
    assert "Donna J. Haraway" in result["authors"]
    assert result["translators"] == []
    assert result["publisher"] == "Duke University Press"
    assert result["year"] == 2016
    assert result["original_title"] == ""


# ── Normalisation ──

def test_normalise_zh_translation_to_book_record():
    raw = {
        "title": "与麻烦同在",
        "authors": ["[美] 唐娜·哈拉维"],
        "translators": ["赵文"],
        "original_title": "Staying with the Trouble",
        "year": 2024,
        "publisher": "华东师范大学出版社",
        "isbn_13": "9787576048971",
        "douban_url": "https://book.douban.com/subject/35erta123/",
        "douban_subject_id": "35erta123",
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


def test_normalise_handles_missing_fields():
    raw = {"title": "测试书", "douban_subject_id": "999"}
    norm = douban_cn._normalise(raw)
    assert norm["title"] == "测试书"
    assert norm["translators"] == []
    assert norm["authors"] == []
    assert norm["isbn_13"] is None
    assert norm["language"] == "zh"


# ── End-to-end search_book with mocked HTTP ──

def test_search_book_english_title_kagi_path_returns_results():
    """Non-zh search uses Kagi subject discovery and fetches returned subjects."""

    def mock_dd_fetch(url, cookie=None, timeout=20):
        if "subject/3512345" in url:
            return True, SUBJECT_PAGE_ZH_TRANSLATION
        if "subject/36512345" in url:
            return True, SUBJECT_PAGE_EN_ORIGINAL
        return False, "not found"

    with patch("sources.douban_cn._kagi_subject_urls", return_value=([
            ("https://book.douban.com/subject/3512345/", "与麻烦同在 (豆瓣)"),
            ("https://book.douban.com/subject/36512345/", "Staying with the Trouble (豆瓣)"),
         ], [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=mock_dd_fetch), \
         patch("sources.douban_cn.time.sleep"):
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
    assert zh["isbn_13"] == "9787576048971"


def test_search_book_with_subject_zh_uses_kagi_then_bs4():
    """When subject='zh' is set, the Kagi-driven localisation path runs."""

    def mock_kagi(query, limit=20):
        return ([("https://book.douban.com/subject/9999/", "类人猿、赛博格和女人 (豆瓣)")], [])

    def mock_fetch(url, cookie=None, timeout=20):
        if "subject/9999" in url:
            return True, """
            <html><h1><span property="v:itemreviewed">类人猿、赛博格和女人</span></h1>
            <div id="info">
              <span class="pl">作者:</span> 唐娜·哈拉维<br/>
              <span class="pl">译者:</span> 翻译者A<br/>
              <span class="pl">出版社:</span> 南京大学出版社<br/>
              <span class="pl">出版年:</span> 2022<br/>
              <span class="pl">ISBN:</span> 9787305256240<br/>
            </div></html>
            """
        return False, "not found"

    with patch("sources.douban_cn._kagi_subject_urls", side_effect=mock_kagi), \
         patch("sources.douban_cn._dd_fetch", side_effect=mock_fetch), \
         patch("sources.douban_cn.time.sleep"):
        q = search.BookQuery(title="Simians Cyborgs and Women", subject="zh", limit=5)
        result = douban_cn.search_book(q)

    assert result.success is True
    assert len(result.entries) >= 1
    assert result.entries[0]["title"] == "类人猿、赛博格和女人"
    assert result.entries[0]["translators"] == ["翻译者A"]
    assert result.entries[0]["isbn_13"] == "9787305256240"


def test_search_book_empty_query_returns_error():
    result = douban_cn.search_book(search.BookQuery())
    assert result.success is False or len(result.entries) == 0


def test_search_book_blocked_returns_empty():
    blocked_html = "<html><head><title>禁止访问</title></head><body>检测到有异常请求</body></html>"

    def mock_dd_fetch(url, cookie=None, timeout=20):
        return True, blocked_html

    with patch("sources.douban_cn._dd_fetch", side_effect=mock_dd_fetch):
        q = search.BookQuery(title="Some Book", limit=5)
        result = douban_cn.search_book(q)

    assert result.success is True
    assert len(result.entries) == 0


# ── Helper functions ──

def test_has_cjk_detects_chinese():
    assert douban_cn._has_cjk("华东师范大学出版社") is True
    assert douban_cn._has_cjk("Duke University Press") is False
    assert douban_cn._has_cjk("Mixed 中英 text") is True
    assert douban_cn._has_cjk("") is False


def test_is_blocked_detects_ban():
    assert douban_cn._is_blocked("<title>禁止访问</title>") is True
    assert douban_cn._is_blocked("检测到有异常请求 blah") is True
    assert douban_cn._is_blocked("<title>搜索结果</title>") is False


def test_canonical_subject_url_exact_policy():
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/12345/"
    ) == "https://book.douban.com/subject/12345/"
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/12345/comments"
    ) is None
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/12345/blockquotes"
    ) is None


def test_external_book_queries_prefer_exact_original_title():
    variants = douban_cn._external_book_queries(
        title="My Mother Was a Computer",
        author="N. Katherine Hayles",
    )
    assert variants[:3] == [
        '"My Mother Was a Computer"',
        '"My Mother Was a Computer" 原作名',
        '"My Mother Was a Computer" 译者',
    ]


# ── Runner ──

def main():
    import inspect
    tests = [obj for name, obj in inspect.getmembers(sys.modules[__name__])
             if name.startswith("test_") and callable(obj)]
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
