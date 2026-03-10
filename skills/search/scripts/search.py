#!/usr/bin/env python3
"""Unified academic search — books + papers + metadata.

Usage:
    # Search books (metadata sources)
    python3 search.py books "Durkheim social morphology" --limit 10

    # Search books on Anna's Archive (file search)
    python3 search.py books "Durkheim social morphology" --source aa

    # Search papers by DOI (metadata lookup)
    python3 search.py metadata --doi "10.1080/1600910X.2019.1641121"

    # Search papers by title
    python3 search.py metadata --title "Space syntax theory" --author "Liebst"

    # Batch metadata lookup from manifest
    python3 search.py metadata --manifest manifest.json --all

    # Search books by author
    python3 search.py books --author "Katherine Hayles" --limit 15

    # Search books, specific source
    python3 search.py books "body studies" --source google --limit 20

    # Search papers by author (sorted by citations)
    python3 search.py papers --author "Donna Haraway" --limit 10
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# Conditional: AA search needs requests + bs4
try:
    import requests as _requests
    from bs4 import BeautifulSoup as _BS
    _HAS_AA_DEPS = True
except ImportError:
    _HAS_AA_DEPS = False

HEADERS = {"User-Agent": "BTS-Research/1.0 (mailto:research@example.com)"}
DELAY = 0.35

# --- Anna's Archive config ---
AA_CONFIG_PATH = Path.home() / ".claude" / "config" / "anna-archive.json"
AA_DEFAULT_MIRRORS = [
    "https://annas-archive.gl",
    "https://annas-archive.li",
]
AA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}


# ============================================================
# Shared utilities
# ============================================================

def _get_json(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  API error: {e}", file=sys.stderr)
        return None


def _abstract_from_inverted_index(idx: dict) -> str:
    if not idx:
        return ""
    words = []
    for word, positions in idx.items():
        for pos in positions:
            words.append((pos, word))
    words.sort()
    return " ".join(w for _, w in words)


# ============================================================
# Book search (Google Books, OpenLibrary, OpenAlex)
# ============================================================

def search_google_books(query: str, limit: int = 10,
                        year_from: Optional[int] = None, year_to: Optional[int] = None) -> dict:
    url = (f"https://www.googleapis.com/books/v1/volumes"
           f"?q={urllib.parse.quote(query)}&maxResults={min(limit, 40)}"
           f"&printType=books&langRestrict=en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BookSearch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []
        for item in data.get("items", []):
            info = item.get("volumeInfo", {})
            pub_date = info.get("publishedDate", "")
            year = int(pub_date[:4]) if pub_date and len(pub_date) >= 4 else None
            if year_from and year and year < year_from:
                continue
            if year_to and year and year > year_to:
                continue

            isbns = {id.get("type"): id.get("identifier")
                     for id in info.get("industryIdentifiers", [])}

            results.append({
                "title": info.get("title", ""),
                "subtitle": info.get("subtitle", ""),
                "authors": info.get("authors", []),
                "year": year,
                "publisher": info.get("publisher", ""),
                "isbn_13": isbns.get("ISBN_13"),
                "isbn_10": isbns.get("ISBN_10"),
                "description": (info.get("description") or "")[:300],
                "categories": info.get("categories", []),
                "page_count": info.get("pageCount"),
                "preview_link": info.get("previewLink", ""),
                "source": "Google Books",
            })
            if len(results) >= limit:
                break
        return {"success": True, "source": "Google Books", "count": len(results), "results": results}
    except Exception as e:
        return {"success": False, "source": "Google Books", "error": str(e), "results": []}


def search_openlibrary(query: str, limit: int = 10,
                       year_from: Optional[int] = None, year_to: Optional[int] = None) -> dict:
    url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(query)}&limit={limit * 2}&language=eng"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BookSearch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []
        for doc in data.get("docs", []):
            year = doc.get("first_publish_year")
            if year_from and year and year < year_from:
                continue
            if year_to and year and year > year_to:
                continue
            isbns = doc.get("isbn", [])
            isbn_13 = next((i for i in isbns if len(i) == 13), None)
            isbn_10 = next((i for i in isbns if len(i) == 10), None)
            results.append({
                "title": doc.get("title", ""),
                "subtitle": doc.get("subtitle", ""),
                "authors": doc.get("author_name", []),
                "year": year,
                "publisher": doc.get("publisher", [])[:3] if doc.get("publisher") else [],
                "isbn_13": isbn_13,
                "isbn_10": isbn_10,
                "description": "",
                "categories": doc.get("subject", [])[:5] if doc.get("subject") else [],
                "page_count": doc.get("number_of_pages_median"),
                "preview_link": f"https://openlibrary.org{doc.get('key', '')}" if doc.get("key") else "",
                "source": "OpenLibrary",
            })
            if len(results) >= limit:
                break
        return {"success": True, "source": "OpenLibrary", "count": len(results), "results": results}
    except Exception as e:
        return {"success": False, "source": "OpenLibrary", "error": str(e), "results": []}


def search_openalex_books(query: str, limit: int = 10,
                          year_from: Optional[int] = None, year_to: Optional[int] = None) -> dict:
    filters = ["type:book"]
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{year_to}-12-31")
    filter_str = ",".join(filters)
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&filter={filter_str}&per_page={limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BookSearch/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []
        for item in data.get("results", []):
            authors = [a.get("author", {}).get("display_name", "")
                       for a in item.get("authorships", [])[:5]
                       if a.get("author", {}).get("display_name")]
            publisher = ""
            source = item.get("primary_location", {}).get("source", {})
            if source:
                publisher = source.get("display_name", "")
            results.append({
                "title": item.get("title", ""),
                "subtitle": "",
                "authors": authors,
                "year": item.get("publication_year"),
                "publisher": publisher,
                "isbn_13": None, "isbn_10": None,
                "description": "",
                "categories": [c.get("display_name", "") for c in item.get("concepts", [])[:5]],
                "page_count": None,
                "preview_link": item.get("id", ""),
                "doi": item.get("doi", ""),
                "cited_by_count": item.get("cited_by_count", 0),
                "source": "OpenAlex",
            })
        return {"success": True, "source": "OpenAlex", "count": len(results), "results": results}
    except Exception as e:
        return {"success": False, "source": "OpenAlex", "error": str(e), "results": []}


def search_books(query: str = "", author: str = None, title: str = None, subject: str = None,
                 sources: list = None, limit: int = 10,
                 year_from: int = None, year_to: int = None) -> list:
    """Search books across multiple APIs in parallel."""
    if sources is None:
        sources = ["google", "openlibrary", "openalex"]

    if not query:
        parts = []
        if subject:
            parts.append(subject)
        if author:
            parts.append(author)
        if title:
            parts.append(title)
        query = " ".join(parts)

    # Build Google-specific query
    google_parts = []
    if subject:
        google_parts.append(f"subject:{subject}")
    if author:
        google_parts.append(f"inauthor:{author}")
    if title:
        google_parts.append(f"intitle:{title}")
    google_query = "+".join(google_parts) if google_parts else query

    all_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        if "google" in sources:
            futures[executor.submit(search_google_books, google_query, limit, year_from, year_to)] = "google"
        if "openlibrary" in sources:
            futures[executor.submit(search_openlibrary, query, limit, year_from, year_to)] = "openlibrary"
        if "openalex" in sources:
            futures[executor.submit(search_openalex_books, query, limit, year_from, year_to)] = "openalex"
        for future in as_completed(futures):
            all_results.append(future.result())

    source_order = {"Google Books": 0, "OpenLibrary": 1, "OpenAlex": 2}
    all_results.sort(key=lambda x: source_order.get(x.get("source", ""), 99))
    return all_results


# ============================================================
# Anna's Archive book search (HTML scraping)
# ============================================================

def _load_aa_config():
    """Load AA config (donator key + mirrors)."""
    if not AA_CONFIG_PATH.exists():
        return None
    with open(AA_CONFIG_PATH) as f:
        config = json.load(f)
    if not config.get("donator_key"):
        return None
    return config


def _get_aa_base_url(config):
    """Find a reachable AA mirror."""
    config_mirrors = config.get("mirrors", [])
    seen = set()
    all_mirrors = []
    for m in config_mirrors + AA_DEFAULT_MIRRORS:
        m = m.rstrip("/")
        if m not in seen:
            seen.add(m)
            all_mirrors.append(m)

    for mirror in all_mirrors:
        try:
            r = _requests.head(mirror, headers=AA_HEADERS, timeout=10, allow_redirects=True)
            if r.status_code < 400:
                return mirror
        except _requests.RequestException:
            print(f"  {mirror} -- unreachable", file=sys.stderr)
            continue

    print("Error: No AA mirror reachable.", file=sys.stderr)
    return None


def _aa_cell_text(cells, idx):
    """Safely extract text from AA table cell."""
    if idx >= len(cells):
        return ""
    span = cells[idx].find("span")
    if span:
        return span.get_text(strip=True)
    return cells[idx].get_text(strip=True)


def _parse_aa_div_results(soup):
    """Fallback parser for non-table AA search results."""
    results = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/md5/" not in href:
            continue
        md5 = href.split("/md5/")[-1].split("?")[0].split("#")[0]
        if not md5 or len(md5) < 10:
            continue
        text = link.get_text(separator=" ", strip=True)
        results.append({
            "md5": md5,
            "title": text[:100] if text else md5,
            "author": "",
            "publisher": "",
            "year": "",
            "language": "",
            "format": "",
            "size": "",
            "source": "Anna's Archive",
        })
    return results


def search_aa(query: str, fmt: str = "pdf", lang: str = None,
              limit: int = 20) -> dict:
    """Search Anna's Archive via HTML table scraping. Returns source result dict."""
    if not _HAS_AA_DEPS:
        return {"success": False, "source": "Anna's Archive",
                "error": "Missing deps: pip install requests beautifulsoup4", "results": []}

    config = _load_aa_config()
    if not config:
        return {"success": False, "source": "Anna's Archive",
                "error": f"AA config not found or missing donator_key. Create: {AA_CONFIG_PATH}",
                "results": []}

    base_url = _get_aa_base_url(config)
    if not base_url:
        return {"success": False, "source": "Anna's Archive",
                "error": "No AA mirror reachable", "results": []}

    print(f"  AA mirror: {base_url}", file=sys.stderr)

    url = (
        f"{base_url}/search?index=&page=1&display=table"
        f"&acc=aa_download&acc=external_download"
        f"&ext={fmt}"
        f"&q={urllib.parse.quote_plus(query)}"
    )
    if lang:
        url += f"&lang={lang}"

    try:
        r = _requests.get(url, headers=AA_HEADERS, timeout=30)
    except _requests.RequestException as e:
        return {"success": False, "source": "Anna's Archive",
                "error": f"Request failed: {e}", "results": []}

    if r.status_code != 200:
        msg = f"HTTP {r.status_code}"
        if r.status_code == 403:
            msg += " (Cloudflare block — use --md5 with download.py instead)"
        return {"success": False, "source": "Anna's Archive", "error": msg, "results": []}

    soup = _BS(r.text, "html.parser")

    # Check for CF challenge page
    title_tag = soup.find("title")
    if title_tag and "just a moment" in title_tag.get_text().lower():
        return {"success": False, "source": "Anna's Archive",
                "error": "Cloudflare challenge — use --md5 with download.py instead",
                "results": []}

    # AA uses a table with display=table mode
    table = soup.find("table")
    if not table:
        results = _parse_aa_div_results(soup)
    else:
        rows = table.find_all("tr")
        results = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            links = row.find_all("a")
            if not links:
                continue
            href = links[0].get("href", "")
            md5 = href.split("/")[-1] if href else ""
            if not md5:
                continue

            results.append({
                "md5": md5,
                "title": _aa_cell_text(cells, 1),
                "author": _aa_cell_text(cells, 2),
                "publisher": _aa_cell_text(cells, 3),
                "year": _aa_cell_text(cells, 4),
                "language": _aa_cell_text(cells, 7),
                "format": _aa_cell_text(cells, 9).lower(),
                "size": _aa_cell_text(cells, 10),
                "source": "Anna's Archive",
            })

    return {
        "success": True,
        "source": "Anna's Archive",
        "count": len(results[:limit]),
        "results": results[:limit],
    }


# ============================================================
# Paper metadata search (OpenAlex, Unpaywall, Semantic Scholar)
# ============================================================

def query_openalex_doi(doi: str) -> dict | None:
    url = f"https://api.openalex.org/works/doi:{doi}?mailto=research@example.com"
    data = _get_json(url)
    if not data or "title" not in data:
        return None
    authors = ", ".join(
        a.get("author", {}).get("display_name", "Unknown")
        for a in data.get("authorships", [])
    )
    abstract = _abstract_from_inverted_index(data.get("abstract_inverted_index"))
    return {
        "title": data.get("title", ""),
        "authors": authors,
        "year": data.get("publication_year"),
        "doi": (data.get("doi") or "").replace("https://doi.org/", ""),
        "openalex_id": data.get("id", ""),
        "oa_url": data.get("open_access", {}).get("oa_url"),
        "is_oa": data.get("open_access", {}).get("is_oa", False),
        "cited_by_count": data.get("cited_by_count", 0),
        "abstract": abstract[:500] if abstract else None,
    }


def query_openalex_title(title: str, author: str = None) -> dict | None:
    params = {"filter": f"title.search:{title}", "mailto": "research@example.com"}
    if author:
        params["filter"] += f",author.search:{author}"
    url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
    data = _get_json(url)
    if not data:
        return None
    results = data.get("results", [])
    if not results:
        return None
    r = results[0]
    doi = (r.get("doi") or "").replace("https://doi.org/", "")
    authors = ", ".join(
        a.get("author", {}).get("display_name", "Unknown")
        for a in r.get("authorships", [])
    )
    abstract = _abstract_from_inverted_index(r.get("abstract_inverted_index"))
    return {
        "title": r.get("title", ""),
        "authors": authors,
        "year": r.get("publication_year"),
        "doi": doi,
        "openalex_id": r.get("id", ""),
        "oa_url": r.get("open_access", {}).get("oa_url"),
        "is_oa": r.get("open_access", {}).get("is_oa", False),
        "cited_by_count": r.get("cited_by_count", 0),
        "abstract": abstract[:500] if abstract else None,
    }


def query_unpaywall(doi: str) -> str | None:
    url = f"https://api.unpaywall.org/v2/{doi}?email=research@example.com"
    data = _get_json(url)
    if not data:
        return None
    best = data.get("best_oa_location")
    if best:
        return best.get("url_for_pdf") or best.get("url")
    return None


def query_semantic_scholar(doi: str) -> dict | None:
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        f"?fields=title,authors,year,abstract,openAccessPdf,citationCount"
    )
    data = _get_json(url)
    if not data or "title" not in data:
        return None
    oa_pdf = data.get("openAccessPdf")
    return {
        "title": data.get("title", ""),
        "authors": ", ".join(a.get("name", "") for a in data.get("authors", [])),
        "year": data.get("year"),
        "abstract": (data.get("abstract") or "")[:500] or None,
        "oa_url": oa_pdf.get("url") if oa_pdf else None,
        "cited_by_count": data.get("citationCount", 0),
    }


def check_wayback(url: str) -> str | None:
    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(url, safe='')}"
        f"&output=json&limit=1&fl=timestamp,original"
    )
    data = _get_json(cdx_url)
    if data and len(data) > 1:
        timestamp, original = data[1]
        return f"https://web.archive.org/web/{timestamp}id_/{original}"
    return None


def search_paper_metadata(doi: str = None, title: str = None, author: str = None) -> dict:
    """Search for paper metadata across multiple APIs."""
    result = {
        "title": title or "",
        "authors": author or "",
        "year": None,
        "doi": doi or "",
        "oa_url": None,
        "is_oa": False,
        "cited_by_count": 0,
        "abstract": None,
        "wayback_url": None,
        "status": "not_found",
    }

    # 1. OpenAlex
    oa_data = None
    if doi:
        oa_data = query_openalex_doi(doi)
        time.sleep(DELAY)
    if not oa_data and title:
        oa_data = query_openalex_title(title, author)
        time.sleep(DELAY)
    if oa_data:
        for k, v in oa_data.items():
            if v and k in result:
                result[k] = v

    # 2. Unpaywall
    if doi and not result["oa_url"]:
        unpaywall_url = query_unpaywall(doi)
        if unpaywall_url:
            result["oa_url"] = unpaywall_url
            result["is_oa"] = True
        time.sleep(DELAY)

    # 3. Semantic Scholar
    if doi:
        ss_data = query_semantic_scholar(doi)
        if ss_data:
            if not result["abstract"] and ss_data.get("abstract"):
                result["abstract"] = ss_data["abstract"]
            if not result["oa_url"] and ss_data.get("oa_url"):
                result["oa_url"] = ss_data["oa_url"]
                result["is_oa"] = True
            if not result["cited_by_count"]:
                result["cited_by_count"] = ss_data.get("cited_by_count", 0)
        time.sleep(DELAY)

    # 4. Wayback
    if doi and not result["oa_url"]:
        pdf_urls = []
        if doi.startswith("10.1145/"):
            pdf_urls.append(f"https://dl.acm.org/doi/pdf/{doi}")
        elif doi.startswith("10.1007/"):
            pdf_urls.append(f"https://link.springer.com/content/pdf/{doi}.pdf")
        elif doi.startswith("10.1353/"):
            pdf_urls.append(f"https://muse.jhu.edu/pub/{doi.split('/')[-1]}")
        pdf_urls.append(f"https://doi.org/{doi}")
        for pdf_url in pdf_urls:
            wb_url = check_wayback(pdf_url)
            if wb_url:
                result["wayback_url"] = wb_url
                break
            time.sleep(DELAY)

    result["status"] = "metadata_found" if result["title"] else "not_found"
    return result


def batch_search_manifest(manifest_path: str):
    """Search metadata for all 'discovered' papers in manifest."""
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    discovered = [
        (k, p) for k, p in manifest["papers"].items()
        if p.get("status") == "discovered"
    ]
    print(f"Found {len(discovered)} papers to search", file=sys.stderr)

    for i, (key, paper) in enumerate(discovered, 1):
        doi = paper.get("doi")
        title = paper.get("title")
        author = paper.get("authors", "").split(",")[0].strip() if paper.get("authors") else None
        print(f"\n[{i}/{len(discovered)}] {key}: doi={doi} title={title[:50] if title else 'N/A'}",
              file=sys.stderr)

        result = search_paper_metadata(doi=doi, title=title, author=author)

        for field in ("title", "authors", "year", "doi", "oa_url", "wayback_url",
                      "is_oa", "cited_by_count", "abstract"):
            val = result.get(field)
            if val and (not paper.get(field) or field in ("oa_url", "wayback_url", "is_oa")):
                paper[field] = val

        if result["status"] != "not_found":
            paper["status"] = "metadata_found"
            print(f"  → metadata_found (OA: {result.get('is_oa')}, "
                  f"WB: {'yes' if result.get('wayback_url') else 'no'})", file=sys.stderr)
        else:
            print(f"  → not_found", file=sys.stderr)

        time.sleep(0.2)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    found = sum(1 for _, p in discovered if p.get("status") == "metadata_found")
    print(f"\nDone. {found}/{len(discovered)} found", file=sys.stderr)


# ============================================================
# Author papers search (OpenAlex)
# ============================================================

def search_author_papers(author: str, limit: int = 30,
                         year_from: Optional[int] = None,
                         sort: str = "cited_by_count:desc") -> dict:
    """Search papers by author via OpenAlex, sorted by citations."""
    filters = [f"raw_author_name.search:{urllib.parse.quote(author)}"]
    # Exclude books — we only want articles/chapters
    filters.append("type:article|review|book-chapter")
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    filter_str = ",".join(filters)
    url = (
        f"https://api.openalex.org/works?"
        f"filter={filter_str}"
        f"&sort={sort}&per_page={limit}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BTS-Research/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        results = []
        for item in data.get("results", []):
            authors = [a.get("author", {}).get("display_name", "")
                       for a in item.get("authorships", [])[:5]
                       if a.get("author", {}).get("display_name")]
            doi = item.get("doi", "")
            if doi and doi.startswith("https://doi.org/"):
                doi = doi[len("https://doi.org/"):]
            best_oa = item.get("best_oa_location") or {}
            oa_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url") or ""
            results.append({
                "title": item.get("title", ""),
                "authors": authors,
                "year": item.get("publication_year"),
                "doi": doi,
                "cited_by_count": item.get("cited_by_count", 0),
                "type": item.get("type", ""),
                "oa_url": oa_url,
                "abstract": _abstract_from_inverted_index(item.get("abstract_inverted_index")) or None,
                "source": ((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
            })
        return {"success": True, "count": len(results), "results": results}
    except Exception as e:
        return {"success": False, "error": str(e), "results": []}


# ============================================================
# Output formatting
# ============================================================

def format_books_markdown(all_results: list, query_desc: str = "") -> str:
    lines = [f"## 搜索结果: {query_desc}\n"] if query_desc else []

    for source_result in all_results:
        source = source_result.get("source", "Unknown")
        if not source_result.get("success"):
            lines.append(f"\n### {source} (Error)")
            lines.append(f"Error: {source_result.get('error', 'Unknown error')}\n")
            continue

        results = source_result.get("results", [])
        lines.append(f"\n### {source} ({len(results)} results)\n")

        for i, book in enumerate(results, 1):
            full_title = book.get("title", "Unknown")
            if book.get("subtitle"):
                full_title += f": {book['subtitle']}"
            year = book.get("year", "N/A")
            authors = ", ".join(book.get("authors", [])[:3]) or "Unknown"
            publisher = book.get("publisher", "")
            if isinstance(publisher, list):
                publisher = publisher[0] if publisher else ""
            isbn = book.get("isbn_13") or book.get("isbn_10") or ""

            lines.append(f"{i}. **{full_title}** ({year})")
            lines.append(f"   - Authors: {authors}")
            if publisher:
                lines.append(f"   - Publisher: {publisher}")
            if isbn:
                lines.append(f"   - ISBN: {isbn}")
            if book.get("cited_by_count"):
                lines.append(f"   - Cited by: {book.get('cited_by_count')}")
            lines.append("")

    return "\n".join(lines)


def format_aa_markdown(all_results: list, query_desc: str = "") -> str:
    """Format Anna's Archive results with MD5 for use with download.py --md5."""
    lines = [f"## Anna's Archive: {query_desc}\n"] if query_desc else []

    for source_result in all_results:
        if not source_result.get("success"):
            lines.append(f"Error: {source_result.get('error', 'Unknown error')}\n")
            continue

        results = source_result.get("results", [])
        lines.append(f"Found {len(results)} results:\n")

        for i, book in enumerate(results, 1):
            title = book.get("title", "(no title)")[:70]
            author = book.get("author", "?")[:30]
            year = book.get("year", "")
            lang = book.get("language", "")
            fmt = book.get("format", "")
            size = book.get("size", "")
            md5 = book.get("md5", "")

            lines.append(f"[{i:2d}] **{title}**")
            lines.append(f"     {author} | {year} | {lang} | {fmt} | {size}")
            lines.append(f"     MD5: `{md5}`")
            lines.append(f"     → `download.py --md5 {md5} --filename <name>`")
            lines.append("")

    return "\n".join(lines)


def format_papers_markdown(results: list, author: str) -> str:
    lines = [f"# Papers by {author}", f"", f"**Total**: {len(results)} results", ""]
    lines.append("| # | Title | Year | Citations | DOI | OA |")
    lines.append("|---|-------|------|-----------|-----|-----|")
    for i, r in enumerate(results, 1):
        title = r.get("title", "N/A")
        year = r.get("year", "?")
        cited = r.get("cited_by_count", 0)
        doi = r.get("doi", "")
        oa = "+" if r.get("oa_url") else "-"
        lines.append(f"| {i} | {title} | {year} | {cited} | {doi} | {oa} |")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Unified academic search (books + papers)")
    subparsers = parser.add_subparsers(dest="mode", help="Search mode")

    # Books subcommand
    books_parser = subparsers.add_parser("books", help="Search books")
    books_parser.add_argument("query", nargs="?", default="", help="Search query")
    books_parser.add_argument("--subject", "-s", help="Subject/keyword")
    books_parser.add_argument("--author", "-a", help="Author name")
    books_parser.add_argument("--title", "-t", help="Title")
    books_parser.add_argument("--source", choices=["google", "openlibrary", "openalex", "aa", "all"],
                              default="all", help="Data source (all = google+openlibrary+openalex; aa = Anna's Archive)")
    books_parser.add_argument("--lang", help="Language filter (AA only, e.g., en)")
    books_parser.add_argument("--format", default="pdf", help="File format filter (AA only, default: pdf)")
    books_parser.add_argument("--limit", "-l", type=int, default=10, help="Max results per source")
    books_parser.add_argument("--year-from", type=int, help="Start year")
    books_parser.add_argument("--year-to", type=int, help="End year")
    books_parser.add_argument("--json", action="store_true", help="JSON output")
    books_parser.add_argument("--output", "-o", help="Output file")

    # Metadata subcommand
    meta_parser = subparsers.add_parser("metadata", help="Search paper metadata")
    meta_parser.add_argument("--doi", help="Paper DOI")
    meta_parser.add_argument("--title", help="Paper title")
    meta_parser.add_argument("--author", help="Author name")
    meta_parser.add_argument("--manifest", help="Manifest file path")
    meta_parser.add_argument("--key", help="Key in manifest (single paper)")
    meta_parser.add_argument("--all", action="store_true", help="Process all discovered in manifest")

    # Papers subcommand
    papers_parser = subparsers.add_parser("papers", help="Search papers by author")
    papers_parser.add_argument("--author", required=True, help="Author name")
    papers_parser.add_argument("--limit", type=int, default=30, help="Max results")
    papers_parser.add_argument("--year-from", type=int, default=None, help="Min year")
    papers_parser.add_argument("--sort", default="cited_by_count:desc",
                               help="Sort order (default: cited_by_count:desc)")
    papers_parser.add_argument("-o", "--output", help="Output file path")
    papers_parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()

    if args.mode == "books":
        if not args.query and not any([args.subject, args.author, args.title]):
            books_parser.error("Need a query or --subject/--author/--title")

        if args.source == "aa":
            # Anna's Archive search (separate path)
            query = args.query or " ".join(filter(None, [args.subject, args.author, args.title]))
            result = search_aa(query, fmt=args.format, lang=args.lang, limit=args.limit)
            results = [result]
        else:
            sources = ["google", "openlibrary", "openalex"] if args.source == "all" else [args.source]
            results = search_books(
                query=args.query, author=args.author, title=args.title, subject=args.subject,
                sources=sources, limit=args.limit, year_from=args.year_from, year_to=args.year_to,
            )

        if args.json:
            output = json.dumps(results, indent=2, ensure_ascii=False)
        else:
            query_desc = args.query or " + ".join(filter(None, [args.subject, args.author, args.title]))
            if args.source == "aa":
                output = format_aa_markdown(results, query_desc)
            else:
                output = format_books_markdown(results, query_desc)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Results saved to: {args.output}", file=sys.stderr)
        else:
            print(output)

        total = sum(r.get("count", 0) for r in results if r.get("success"))
        print(f"\nTotal: {total} results", file=sys.stderr)

    elif args.mode == "metadata":
        if args.all and args.manifest:
            batch_search_manifest(args.manifest)
        elif args.doi or args.title:
            result = search_paper_metadata(doi=args.doi, title=args.title, author=args.author)
            if args.manifest and args.key:
                # Update manifest entry
                with open(args.manifest, "r") as f:
                    manifest = json.load(f)
                paper = manifest["papers"].get(args.key, {})
                for field in ("title", "authors", "year", "doi", "oa_url", "wayback_url",
                              "is_oa", "cited_by_count", "abstract"):
                    val = result.get(field)
                    if val and (not paper.get(field) or field in ("oa_url", "wayback_url", "is_oa")):
                        paper[field] = val
                if result["status"] != "not_found":
                    paper["status"] = "metadata_found"
                manifest["papers"][args.key] = paper
                with open(args.manifest, "w") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                print(f"Updated manifest: {args.key}", file=sys.stderr)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            meta_parser.error("Need --doi/--title, or --manifest with --all")

    elif args.mode == "papers":
        result = search_author_papers(
            author=args.author, limit=args.limit,
            year_from=args.year_from, sort=args.sort,
        )
        if not result.get("success"):
            print(f"Error: {result.get('error', 'Unknown')}", file=sys.stderr)
            sys.exit(1)

        if args.json:
            output = json.dumps(result, indent=2, ensure_ascii=False)
        else:
            output = format_papers_markdown(result.get("results", []), args.author)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Results saved to: {args.output}", file=sys.stderr)
        else:
            print(output)

        print(f"\nTotal: {result.get('count', 0)} results", file=sys.stderr)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
