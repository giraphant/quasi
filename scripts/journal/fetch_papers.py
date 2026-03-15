#!/usr/bin/env python3
"""Fetch papers from OpenAlex by journal name."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_URL = "https://api.openalex.org"
HEADERS = {"User-Agent": "Quasi-Research/1.0"}


def search_journal(name: str) -> str:
    """Search journal by name, return OpenAlex source ID."""
    url = f"{BASE_URL}/sources"
    params = {"search": name, "per_page": 5}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        raise ValueError(f"Journal not found: {name}")

    source = results[0]
    source_id = source.get("id", "").split("/")[-1]
    print(f"Found: {source.get('display_name')} (ID: {source_id})")
    return source_id


def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index."""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def fetch_papers(source_id: str, from_date: str) -> list[dict]:
    """Fetch papers from source since from_date."""
    url = f"{BASE_URL}/works"
    params = {
        "filter": f"primary_location.source.id:{source_id},from_publication_date:{from_date},type:article",
        "sort": "publication_date:desc",
        "per_page": 200,
        "page": 1
    }

    all_papers = []
    while True:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            break

        for work in results:
            loc = work.get("primary_location") or {}
            source = loc.get("source") or {}
            authors_list = []
            for a in work.get("authorships", []):
                author = a.get("author", {})
                if author.get("display_name"):
                    authors_list.append(author["display_name"])

            all_papers.append({
                "id": work.get("id", "").split("/")[-1],
                "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
                "title": work.get("title", ""),
                "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
                "authors": ", ".join(authors_list),
                "publication_date": work.get("publication_date", ""),
                "journal_name": source.get("display_name", ""),
                "cited_by_count": work.get("cited_by_count", 0)
            })

        if len(results) < 200:
            break
        params["page"] += 1

    return all_papers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-name", required=True)
    parser.add_argument("--days-back", type=int, default=3650)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from_date = (datetime.now() - timedelta(days=args.days_back)).strftime("%Y-%m-%d")
    print(f"Fetching papers from {args.journal_name} since {from_date}")

    try:
        source_id = search_journal(args.journal_name)
        papers = fetch_papers(source_id, from_date)
        print(f"Fetched {len(papers)} papers")

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2))
        print(f"Saved to {output_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

