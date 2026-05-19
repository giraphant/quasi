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
        ("https://book.douban.com/subject/12345/", "性别麻烦 (豆瓣)"),
        ("https://book.douban.com/subject/67890/", "Gender Trouble (豆瓣)"),
        ("https://book.douban.com/subject/77777/", "消解性别 (豆瓣)"),
        ("https://book.douban.com/subject/55555/", "性别是流动的吗？"),
    ]
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
    assert items == [("https://book.douban.com/subject/100/", "Book 100")]


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
        ("https://book.douban.com/subject/2/", "规训与惩罚 (豆瓣)"),  # ZH page title
        # No EN item — cjk_title_only=True would skip it pre-fetch.
        # Add one to also exercise the pre-filter:
        ("https://book.douban.com/subject/1/", "Discipline and Punish (豆瓣)"),  # EN, skipped
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


def test_zh_localisation_search_sorts_by_ratings_count():
    items = [
        (f"https://book.douban.com/subject/{i}/", f"书{i} (豆瓣)")
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
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
