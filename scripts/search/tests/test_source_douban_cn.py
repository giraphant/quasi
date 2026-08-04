#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import douban_cn


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


def test_search_book_english_title_kagi_path_returns_results():
    """Non-zh search uses Kagi subject discovery and fetches returned subjects."""

    def mock_dd_fetch(url, cookie=None, timeout=20):
        if "subject/3512345" in url:
            return True, SUBJECT_PAGE_ZH_TRANSLATION
        if "subject/36512345" in url:
            return True, SUBJECT_PAGE_EN_ORIGINAL
        return False, "not found"

    with patch("sources.douban_cn._kagi_subject_urls", return_value=([
            ("https://book.douban.com/subject/3512345/", "与麻烦同在 (豆瓣)", ""),
            ("https://book.douban.com/subject/36512345/", "Staying with the Trouble (豆瓣)", ""),
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


def test_search_book_blocked_returns_error():
    blocked_html = "<html><head><title>禁止访问</title></head><body>检测到有异常请求</body></html>"

    def mock_dd_fetch(url, cookie=None, timeout=20):
        return True, blocked_html

    with patch("sources.douban_cn._kagi_subject_urls",
               return_value=([("https://book.douban.com/subject/9999/", "Some Book (豆瓣)", "")], [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=mock_dd_fetch):
        q = search.BookQuery(title="Some Book", limit=5)
        result = douban_cn.search_book(q)

    assert result.success is False
    assert "subject-fetch failed" in (result.error or "")
    assert result.entries == []


# ── Module surface ──

def test_supports():
    assert douban_cn.SUPPORTS == ["book"]


# ── search_book branching ──

def test_general_metadata_query_uses_kagi_book_search():
    """Non-zh queries use Kagi subject discovery without zh filtering."""
    fake_records = [{"title": "X", "year": 2020, "douban_subject_id": "1"}]
    with patch("sources.douban_cn._kagi_book_search", return_value=(fake_records, [])) as mock_kagi, \
         patch("sources.douban_cn._zh_localisation_search") as mock_zh:
        r = douban_cn.search_book(search.BookQuery(title="X"))
    assert r.success is True
    assert len(r.entries) == 1
    assert mock_kagi.called
    assert not mock_zh.called


def test_subject_zh_uses_localisation_path():
    """subject='zh' triggers _zh_localisation_search instead of raw Kagi search."""
    fake_zh = ([{
        "title": "原书中文版",
        "publisher": "河南大学出版社",
        "year": 2012,
        "douban_subject_id": "2",
        "douban_url": "https://book.douban.com/subject/2/",
        "isbn_13": "9787564906962",
    }], [])
    with patch("sources.douban_cn._zh_localisation_search", return_value=fake_zh) as mock_zh, \
         patch("sources.douban_cn._kagi_book_search") as mock_kagi:
        r = douban_cn.search_book(search.BookQuery(title="Original", subject="zh"))
    assert r.success is True
    assert mock_zh.called
    assert not mock_kagi.called
    assert r.entries[0]["title"] == "原书中文版"
    assert r.entries[0]["isbn_13"] == "9787564906962"
    assert r.entries[0]["language"] == "zh"


def test_subject_zh_returns_empty_when_no_chinese_editions():
    """An empty localisation result is success+no entries (not error)."""
    with patch("sources.douban_cn._zh_localisation_search", return_value=([], [])):
        r = douban_cn.search_book(search.BookQuery(title="No Chinese Translation", subject="zh"))
    assert r.success is True
    assert r.entries == []


def test_subject_zh_surfaces_discovery_warning_as_error():
    """Kagi/Douban discovery failures must not look like true no-result searches."""
    with patch("sources.douban_cn._zh_localisation_search",
               return_value=([], [
                   "kagi-search: rc=1: missing credentials",
                   "kagi-search: rc=1: missing credentials",
               ])):
        r = douban_cn.search_book(search.BookQuery(title="Resonance", subject="zh"))
    assert r.success is False
    assert "kagi-search" in (r.error or "")
    assert r.error.count("kagi-search") == 1
    assert r.entries == []


def test_empty_query_returns_error():
    r = douban_cn.search_book(search.BookQuery())
    assert r.success is False


# ── _kagi_subject_urls: strict URL filter, kagi shell invocation ──

def _completed(payload: dict, *, rc: int = 0, stderr: str = ""):
    return type("Completed", (), {
        "returncode": rc,
        "stdout": json.dumps(payload),
        "stderr": stderr,
    })()


def test_kagi_subject_urls_returns_canonical_only():
    """Keeps /subject/{id}/, normalises double-slash + ?_dtcc cruft,
    drops /comments, /blockquotes, /doulists child paths. Returns
    (canonical_url, kagi_title) pairs so callers can pre-filter on
    the page title without a fetch."""
    payload = {"data": [
        {"url": "https://book.douban.com/subject/12345/",
         "title": "性别麻烦 (豆瓣)"},
        {"url": "https://book.douban.com/subject/12345/comments/?sort=time",
         "title": "性别麻烦 短评"},
        {"url": "https://book.douban.com/subject/67890/blockquotes",
         "title": "Gender Trouble 原文摘录"},
        {"url": "https://book.douban.com/subject/67890/",
         "title": "Gender Trouble (豆瓣)"},
        {"url": "https://book.douban.com/subject/99999/doulists",
         "title": "推荐 Gender Trouble 的书单"},
        {"url": "https://book.douban.com/subject/77777//",  # double-slash → normalise
         "title": "消解性别 (豆瓣)"},
        {"url": "https://book.douban.com/subject/55555/?_dtcc=1",  # query → normalise
         "title": "性别是流动的吗？"},
    ]}
    with patch("sources.douban_cn.subprocess.run", return_value=_completed(payload)):
        items, warnings = douban_cn._kagi_subject_urls("Example Book", limit=10)
    assert items == [
        ("https://book.douban.com/subject/12345/", "性别麻烦 (豆瓣)", ""),
        ("https://book.douban.com/subject/67890/", "Gender Trouble (豆瓣)", ""),
        ("https://book.douban.com/subject/77777/", "消解性别 (豆瓣)", ""),
        ("https://book.douban.com/subject/55555/", "性别是流动的吗？", ""),
    ]
    assert warnings == []


def test_kagi_subject_urls_preserves_snippet_for_fetch_fallback():
    payload = {"data": [{
        "url": "https://book.douban.com/subject/36494081/?_dtcc=1",
        "title": "过一种女性主义的生活 (豆瓣)",
        "snippet": "过一种女性主义的生活 作者: [英]萨拉·艾哈迈德 译者: 范语晨 出版社: 上海文艺出版社 出版年: 2023-10 ISBN: 9787532188239 原作名: Living a Feminist Life 豆瓣评分 8.5 634 人评价",
    }]}
    with patch("sources.douban_cn.subprocess.run", return_value=_completed(payload)):
        items, warnings = douban_cn._kagi_subject_urls("Living a Feminist Life", limit=10)
    assert items == [(
        "https://book.douban.com/subject/36494081/",
        "过一种女性主义的生活 (豆瓣)",
        "过一种女性主义的生活 作者: [英]萨拉·艾哈迈德 译者: 范语晨 出版社: 上海文艺出版社 出版年: 2023-10 ISBN: 9787532188239 原作名: Living a Feminist Life 豆瓣评分 8.5 634 人评价",
    )]
    assert warnings == []


def test_canonical_subject_url_normalises_cruft_and_rejects_children():
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832/"
    ) == "https://book.douban.com/subject/2482832/"
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832"
    ) == "https://book.douban.com/subject/2482832/"
    # ── normalise cruft Kagi/Douban routinely append ──
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/55555/?_dtcc=1"
    ) == "https://book.douban.com/subject/55555/"
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/77777//"
    ) == "https://book.douban.com/subject/77777/"
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/88888/#reviews"
    ) == "https://book.douban.com/subject/88888/"
    # ── reject child paths ──
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832/comments"
    ) is None
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832/blockquotes"
    ) is None
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/20384337/annotation"
    ) is None
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832/offers/?offer_id=1"
    ) is None
    assert douban_cn._canonical_subject_url(
        "https://book.douban.com/subject/2482832/buylinks"
    ) is None


def test_kagi_subject_urls_respects_limit():
    payload = {"data": [
        {"url": f"https://book.douban.com/subject/{i}/", "title": f"Book {i}"}
        for i in range(1, 20)
    ]}
    with patch("sources.douban_cn.subprocess.run", return_value=_completed(payload)):
        items, _ = douban_cn._kagi_subject_urls("Example", limit=5)
    assert len(items) == 5


def test_kagi_subject_urls_dedupes_repeats():
    payload = {"data": [
        {"url": "https://book.douban.com/subject/100/", "title": "Book 100"},
        {"url": "https://book.douban.com/subject/100/", "title": "Book 100 dup"},
        {"url": "https://book.douban.com/subject/100//", "title": "Book 100 cruft"},
    ]}
    with patch("sources.douban_cn.subprocess.run", return_value=_completed(payload)):
        items, _ = douban_cn._kagi_subject_urls("Example", limit=10)
    assert items == [("https://book.douban.com/subject/100/", "Book 100", "")]


def test_kagi_subject_urls_invokes_kagi_with_site_limiter():
    payload = {"data": []}
    with patch("sources.douban_cn.subprocess.run",
               return_value=_completed(payload)) as mock_run:
        douban_cn._kagi_subject_urls('"Strange Encounters" 原作名')
    args = mock_run.call_args[0][0]
    assert args[0] == "kagi"
    assert "--format" in args and "json" in args
    assert any("site:book.douban.com/subject" in a for a in args)
    assert any('"Strange Encounters" 原作名' in a for a in args)


def test_kagi_subject_urls_passes_plugin_session_token_env():
    payload = {"data": []}
    with patch.dict(os.environ, {"QUASI_KAGI_SESSION_TOKEN": "session-token"}, clear=False), \
         patch("sources.douban_cn.subprocess.run",
               return_value=_completed(payload)) as mock_run:
        douban_cn._kagi_subject_urls("Example")
    env = mock_run.call_args.kwargs["env"]
    assert env["KAGI_SESSION_TOKEN"] == "session-token"


def test_kagi_subject_urls_missing_cli_returns_warning():
    with patch("sources.douban_cn.subprocess.run", side_effect=FileNotFoundError):
        urls, warnings = douban_cn._kagi_subject_urls("anything")
    assert urls == []
    assert any("not on PATH" in w for w in warnings)


def test_kagi_subject_urls_nonzero_rc_returns_warning():
    with patch("sources.douban_cn.subprocess.run",
               return_value=_completed({}, rc=2, stderr="\x1b[31mERROR\x1b[0m auth required")):
        urls, warnings = douban_cn._kagi_subject_urls("anything")
    assert urls == []
    assert any("rc=2" in w for w in warnings)
    assert all("\x1b" not in w for w in warnings)


# ── _compact_external_book_query ──

def test_external_book_queries_search_exact_title_before_author():
    q = douban_cn._compact_external_book_query(
        title="Strange Encounters: Embodied Others in\n         Post-Coloniality",
        author="Sara Ahmed",
    )
    assert q == '"Strange Encounters: Embodied Others in Post-Coloniality"'
    assert "\n" not in q
    variants = douban_cn._external_book_queries(
        title="My Mother Was a Computer",
        author="N. Katherine Hayles",
    )
    assert variants[:3] == [
        '"My Mother Was a Computer"',
        '"My Mother Was a Computer" 原作名',
        '"My Mother Was a Computer" 译者',
    ]
    assert '"My Mother Was a Computer" "N. Katherine Hayles"' in variants
    assert '"My Mother Was a Computer" Hayles' in variants


def test_external_book_queries_include_title_head_fallback():
    variants = douban_cn._external_book_queries(
        title="Strange Encounters: Embodied Others in Post-Coloniality",
        author="Sara Ahmed",
    )
    assert '"Strange Encounters"' in variants
    assert '"Strange Encounters" 原作名' in variants


def test_external_book_queries_do_not_use_bare_author_tail_as_author_only_fallback():
    variants = douban_cn._external_book_queries(
        title="Politics of Life Itself",
        author="Nikolas Rose",
    )
    assert '"Nikolas Rose"' in variants
    assert "Nikolas Rose" in variants
    assert "Rose" not in variants


def test_external_book_queries_skip_isbn_when_title_present():
    """Original-language ISBN poisons Douban search — Douban indexes the
    Chinese-edition ISBN, not the original. When title is present, drop
    the ISBN variant; when title is absent, keep it as the only signal."""
    with_title = douban_cn._external_book_queries(
        title="Living a Feminist Life",
        author="Sara Ahmed",
        isbn="9780822373377",
    )
    assert "9780822373377" not in with_title

    isbn_only = douban_cn._external_book_queries(isbn="9780822373377")
    assert isbn_only == ["9780822373377"]


# ── _is_chinese_edition: registry + CJK signals ──

def test_is_chinese_edition_accepts_mainland_isbn():
    assert douban_cn._is_chinese_edition({"isbn_13": "9787108017949"}) is True


def test_is_chinese_edition_accepts_tw_isbn():
    assert douban_cn._is_chinese_edition({"isbn_13": "9789866525605"}) is True


def test_is_chinese_edition_accepts_hk_isbn():
    assert douban_cn._is_chinese_edition({"isbn_13": "9789881555540"}) is True


def test_is_chinese_edition_rejects_japanese_isbn_even_with_kanji():
    """ISBN 978-4 (Japan) must reject even when title/translator are kanji."""
    assert douban_cn._is_chinese_edition({
        "isbn_13": "9784753103171",
        "title": "伴侶種宣言",
        "translators": ["永野 文香"],
    }) is False


def test_is_chinese_edition_rejects_korean_isbn():
    assert douban_cn._is_chinese_edition({"isbn_13": "9788932917337"}) is False


def test_is_chinese_edition_rejects_kana_in_title():
    assert douban_cn._is_chinese_edition({
        "title": "サイボーグ宣言",
        "publisher": "東京大学出版会",
    }) is False


def test_is_chinese_edition_rejects_hangul():
    assert douban_cn._is_chinese_edition({
        "title": "사이보그 선언",
        "publisher": "민음사",
    }) is False


def test_is_chinese_edition_accepts_cjk_publisher_without_isbn():
    assert douban_cn._is_chinese_edition({
        "title": "regional title",
        "publisher": "商务印书馆",
    }) is True


def test_is_chinese_edition_accepts_cjk_translator_without_isbn():
    assert douban_cn._is_chinese_edition({
        "title": "regional title",
        "translators": ["王宇根"],
    }) is True


def test_is_chinese_edition_rejects_non_cjk_translator():
    """A French/English translator alone is not evidence of Chinese."""
    assert douban_cn._is_chinese_edition({
        "title": "Queer Phenomenology",
        "publisher": "Éditions Le Manuscrit",
        "translators": ["Laurence Brottier"],
        "isbn_13": "9782304052824",
    }) is False


def test_is_chinese_edition_accepts_cjk_title():
    assert douban_cn._is_chinese_edition({"title": "性别麻烦"}) is True


def test_is_chinese_edition_rejects_no_signal():
    assert douban_cn._is_chinese_edition({
        "title": "Random English Book",
        "publisher": "Penguin",
        "translators": [],
    }) is False


# ── _fetch_subject_via_bs4: BeautifulSoup parsing of #info block ──

_SUBJECT_HTML_ZH = """
<html><head><title>性别麻烦 (豆瓣)</title></head><body>
<h1><span property="v:itemreviewed">性别麻烦</span></h1>
<div id="info">
  <span class="pl">作者:</span> <a>朱迪斯·巴特勒</a><br/>
  <span class="pl">出版社:</span> 上海三联书店<br/>
  <span class="pl">译者:</span> <a>宋素凤</a><br/>
  <span class="pl">出版年:</span> 2009-1<br/>
  <span class="pl">页数:</span> 286<br/>
  <span class="pl">定价:</span> 28.00元<br/>
  <span class="pl">ISBN:</span> 9787542628893<br/>
  <span class="pl">原作名:</span> Gender Trouble: Feminism and the Subversion of Identity<br/>
</div>
<div><strong property="v:average">8.4</strong>
     <span property="v:votes">1234</span></div>
</body></html>
"""


def test_fetch_subject_via_bs4_parses_chinese_edition():
    with patch("sources.douban_cn._dd_fetch", return_value=(True, _SUBJECT_HTML_ZH)):
        rec = douban_cn._fetch_subject_via_bs4("https://book.douban.com/subject/3339862/")
    assert rec is not None
    assert rec["douban_subject_id"] == "3339862"
    assert rec["title"].startswith("性别麻烦")
    assert rec["publisher"] == "上海三联书店"
    assert rec["translators"] == ["宋素凤"]
    assert rec["authors"] == ["朱迪斯·巴特勒"]
    assert rec["year"] == 2009
    assert rec["isbn_13"] == "9787542628893"
    assert rec["original_title"] == "Gender Trouble: Feminism and the Subversion of Identity"
    assert rec["douban_rating"] == 8.4
    assert rec["ratings_count"] == 1234


def test_fetch_subject_via_bs4_returns_none_when_blocked():
    blocked = "<html><head><title>禁止访问</title></head></html>"
    with patch("sources.douban_cn._dd_fetch", return_value=(True, blocked)):
        rec = douban_cn._fetch_subject_via_bs4("https://book.douban.com/subject/1/")
    assert rec is None


def test_fetch_subject_via_bs4_returns_none_on_fetch_failure():
    with patch("sources.douban_cn._dd_fetch", return_value=(False, "HTTP 503")):
        rec = douban_cn._fetch_subject_via_bs4("https://book.douban.com/subject/1/")
    assert rec is None


def test_fetch_subject_via_bs4_isolates_fields_from_inline_metadata():
    """The #info block parser must not bleed `出版年` etc. into earlier fields."""
    inline = """
    <html><head><title>X</title></head><body>
    <h1><span property="v:itemreviewed">规训与惩罚</span></h1>
    <div id="info">
      <span class="pl">作者:</span> 米歇尔·福柯<br/>
      <span class="pl">出版社:</span> 三联书店<br/>
      <span class="pl">出版年:</span> 2003-1<br/>
      <span class="pl">ISBN:</span> 9787108017949<br/>
    </div>
    </body></html>
    """
    with patch("sources.douban_cn._dd_fetch", return_value=(True, inline)):
        rec = douban_cn._fetch_subject_via_bs4("https://book.douban.com/subject/1012307/")
    assert rec["authors"] == ["米歇尔·福柯"]
    assert rec["publisher"] == "三联书店"
    assert rec["year"] == 2003
    assert rec["isbn_13"] == "9787108017949"


# ── _zh_localisation_search: integration ──

def test_zh_localisation_search_filters_to_chinese_only():
    """End-to-end: kagi returns mix of EN+ZH (CJK-dominant title only for
    the ZH one), only ZH survive both the pre-fetch CJK filter and the
    post-fetch publisher-CJK check."""
    items = [
        ("https://book.douban.com/subject/2/", "规训与惩罚 (豆瓣)", ""),  # ZH page title
        # No EN item — cjk_title_only=True would skip it pre-fetch.
        # Add one to also exercise the pre-filter:
        ("https://book.douban.com/subject/1/", "Discipline and Punish (豆瓣)", ""),  # EN, skipped
    ]
    zh_html = """
    <html><h1><span property="v:itemreviewed">规训与惩罚</span></h1>
    <div id="info">
      <span class="pl">作者:</span> 米歇尔·福柯<br/>
      <span class="pl">出版社:</span> 三联书店<br/>
      <span class="pl">译者:</span> 刘北成<br/>
      <span class="pl">出版年:</span> 2003-1<br/>
      <span class="pl">ISBN:</span> 9787108017949<br/>
    </div>
    <div><span property="v:votes">5000</span></div></html>
    """

    def fake_fetch(url, cookie=None, timeout=20):
        if "subject/2/" in url:
            return True, zh_html
        # subject/1 should never be fetched because pre-filter drops it
        raise AssertionError(f"Latin-title URL should not be fetched: {url}")

    with patch("sources.douban_cn._kagi_subject_urls", return_value=(items, [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=fake_fetch):
        out, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="Discipline and Punish", author="Foucault", limit=10)
        )

    assert len(out) == 1
    assert out[0]["douban_subject_id"] == "2"
    assert out[0]["title"] == "规训与惩罚"


def test_kagi_snippet_parser_does_not_treat_author_bio_as_author_field():
    rec = douban_cn._parse_kagi_snippet_record(
        "https://book.douban.com/subject/26262047/",
        "生命本身的政治 (豆瓣)",
        "生命本身的政治 作者简介 · · · 尼古拉斯•罗斯，伦敦政治经济学院社会学教授。 出版社: 北京大学出版社 出版年: 2014 ISBN: 9787301249574",
    )
    assert rec is not None
    assert rec["authors"] == []
    assert rec["publisher"] == "北京大学出版社"
    assert rec["year"] == 2014
    assert rec["isbn_13"] == "9787301249574"


def test_kagi_snippet_parser_marks_title_only_snippet_as_weak():
    rec = douban_cn._parse_kagi_snippet_record(
        "https://book.douban.com/subject/35948627/",
        "不受掌控 (豆瓣)",
        "不受掌控 · · · 相关讨论和书评",
    )
    assert rec is not None
    assert rec["title"] == "不受掌控"
    assert rec["_weak"] is True
    assert rec["_weak_reason"] == "kagi-snippet-missing-bibliographic-fields"


def test_zh_localisation_search_uses_kagi_snippet_when_douban_fetch_is_blocked():
    snippet = "过一种女性主义的生活 作者: [英]萨拉·艾哈迈德 译者: 范语晨 出版社: 上海文艺出版社 出版年: 2023-10 ISBN: 9787532188239 原作名: Living a Feminist Life 豆瓣评分 8.5 634 人评价"
    items = [(
        "https://book.douban.com/subject/36494081/",
        "过一种女性主义的生活 (豆瓣)",
        snippet,
    )]

    with patch("sources.douban_cn._kagi_subject_urls", return_value=(items, [])), \
         patch("sources.douban_cn._dd_fetch", return_value=(False, "HTTP 403")), \
         patch("sources.douban_cn.time.sleep"):
        out, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="Living a Feminist Life", author="Sara Ahmed", limit=10)
        )

    assert len(out) == 1
    rec = out[0]
    assert rec["douban_subject_id"] == "36494081"
    assert rec["title"] == "过一种女性主义的生活"
    assert rec["authors"] == ["[英]萨拉·艾哈迈德"]
    assert rec["translators"] == ["范语晨"]
    assert rec["publisher"] == "上海文艺出版社"
    assert rec["year"] == 2023
    assert rec["isbn_13"] == "9787532188239"
    assert rec["original_title"] == "Living a Feminist Life"
    assert rec["douban_rating"] == 8.5
    assert rec["ratings_count"] == 634
    assert warnings == []


def test_zh_localisation_search_keeps_weak_cjk_kagi_title_when_fetch_blocked_and_snippet_empty():
    blocked_html = "<html><head><title>禁止访问</title></head><body>检测到有异常请求</body></html>"

    def mock_fetch(url, cookie=None, timeout=20):
        return True, blocked_html

    with patch("sources.douban_cn._kagi_subject_urls",
               return_value=([("https://book.douban.com/subject/35948627/", "不受掌控 (豆瓣)", "")], [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=mock_fetch), \
         patch("sources.douban_cn.time.sleep"):
        records, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="Uncontrollability", author="Hartmut Rosa", subject="zh", limit=5)
        )

    assert warnings == []
    assert len(records) == 1
    assert records[0]["title"] == "不受掌控"
    assert records[0]["douban_subject_id"] == "35948627"
    assert records[0]["douban_url"] == "https://book.douban.com/subject/35948627/"
    assert records[0]["_weak"] is True
    assert records[0]["_weak_reason"] == "douban-fetch-blocked-kagi-title-only"


def test_search_book_preserves_weak_candidate_metadata():
    weak_raw = {
        "douban_subject_id": "35948627",
        "douban_url": "https://book.douban.com/subject/35948627/",
        "title": "不受掌控",
        "authors": [],
        "translators": [],
        "publisher": "",
        "year": None,
        "isbn_13": None,
        "isbn_10": None,
        "original_title": "",
        "ratings_count": 0,
        "douban_rating": None,
        "_weak": True,
        "_weak_reason": "douban-fetch-blocked-kagi-title-only",
    }
    with patch("sources.douban_cn._zh_localisation_search", return_value=([weak_raw], [])):
        result = douban_cn.search_book(search.BookQuery(title="Uncontrollability", subject="zh"))

    assert result.success is True
    assert result.entries[0]["_weak"] is True
    assert result.entries[0]["_weak_reason"] == "douban-fetch-blocked-kagi-title-only"


def test_zh_localisation_search_rejects_latin_kagi_title_when_fetch_blocked_and_snippet_empty():
    blocked_html = "<html><head><title>禁止访问</title></head><body>检测到有异常请求</body></html>"

    def mock_fetch(url, cookie=None, timeout=20):
        return True, blocked_html

    with patch("sources.douban_cn._kagi_subject_urls",
               return_value=([("https://book.douban.com/subject/36512345/", "Staying with the Trouble (豆瓣)", "")], [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=mock_fetch), \
         patch("sources.douban_cn.time.sleep"):
        records, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="Staying with the Trouble", author="Donna Haraway", subject="zh", limit=5)
        )

    assert records == []
    assert warnings == []


def test_zh_localisation_search_uses_author_only_fallback_queries():
    snippet = "加速 作者: [德] 哈特穆特·罗萨 译者: 董璐 出版社: 北京大学出版社 出版年: 2015 isbn: 9787301265181 原作名: Beschleunigung. Die Veränderung der Zeitstrukturen in der Moderne 豆瓣评分 8.3 1000 人评价"
    calls: list[str] = []

    def fake_kagi(q, limit=20):
        calls.append(q)
        if q == '"Hartmut Rosa"':
            return ([('https://book.douban.com/subject/26681330/', '加速 (豆瓣)', snippet)], [])
        return ([], [])

    with patch("sources.douban_cn._kagi_subject_urls", side_effect=fake_kagi), \
         patch("sources.douban_cn._dd_fetch", return_value=(False, "HTTP 403")), \
         patch("sources.douban_cn.time.sleep"):
        out, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="Social Acceleration", author="Hartmut Rosa", limit=10)
        )

    assert len(out) == 1
    assert out[0]["douban_subject_id"] == "26681330"
    assert out[0]["title"] == "加速"
    assert out[0]["isbn_13"] == "9787301265181"
    assert '"Social Acceleration"' in calls
    assert '"Hartmut Rosa"' in calls
    assert calls.index('"Social Acceleration"') < calls.index('"Hartmut Rosa"')
    assert warnings == []


def test_zh_localisation_search_sorts_by_ratings_count():
    items = [
        (f"https://book.douban.com/subject/{i}/", f"书{i} (豆瓣)", "")
        for i in range(1, 4)
    ]

    def fake_fetch(url, cookie=None, timeout=20):
        sid = url.rstrip("/").split("/")[-1]
        ratings = {"1": 10, "2": 5000, "3": 200}[sid]
        return True, f"""
        <html><h1><span property="v:itemreviewed">书{sid}</span></h1>
        <div id="info">
          <span class="pl">出版社:</span> 三联书店<br/>
          <span class="pl">ISBN:</span> 978710801794{sid}<br/>
        </div>
        <div><span property="v:votes">{ratings}</span></div></html>
        """

    with patch("sources.douban_cn._kagi_subject_urls", return_value=(items, [])), \
         patch("sources.douban_cn._dd_fetch", side_effect=fake_fetch), \
         patch("sources.douban_cn.time.sleep"):  # skip the polite delay
        out, _ = douban_cn._zh_localisation_search(
            search.BookQuery(title="x", author="y", limit=10)
        )

    assert [r["douban_subject_id"] for r in out] == ["2", "3", "1"]


def test_zh_localisation_search_returns_warnings_on_kagi_failure():
    with patch("sources.douban_cn._kagi_subject_urls",
               return_value=([], ["kagi-search: timeout"])):
        out, warnings = douban_cn._zh_localisation_search(
            search.BookQuery(title="x", author="y")
        )
    assert out == []
    assert any("timeout" in w for w in warnings)
