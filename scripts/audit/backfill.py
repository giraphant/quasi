"""quasi-audit backfill — vault metadata backfill dispatcher.

Runs sweep scripts from scripts/audit/sweep/ to backfill vault
frontmatter from various sources (Crossref / AA / OpenLibrary /
OpenAlex / dokobot-Douban).

Migrated from scripts/search/search.py:1815-1866 (run_backfill /
_run_one_backfill) and re-rooted under quasi-audit.

CLI surface:
    quasi-audit backfill --strategy {auto|clean|crossref|aa-title|aa-md5|
                                     aa-from-slug|openalex|ol-search|
                                     ol-isbn-reverse}
                          [-- ARGS_TO_SWEEP_SCRIPT...]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SWEEP_DIR = Path(__file__).parent / "sweep"

_STRATEGY_TO_SCRIPT = {
    "clean":            "sweep-book-fm-clean.py",
    "crossref":         "sweep-book-fm-meta.py",   # default chain entry
    "aa-title":         "sweep-book-fm-meta-aa.py",
    "aa-md5":           "sweep-book-fm-meta-aa-by-md5.py",
    "aa-from-slug":     "sweep-book-fm-meta-aa-from-slug.py",
    "openalex":         "sweep-book-fm-meta-oa.py",
    "ol-search":        "sweep-book-fm-meta-ol-fallback.py",
    "ol-isbn-reverse":  "sweep-book-fm-ol-isbn-reverse.py",
}

_AUTO_CHAIN = ["clean", "crossref", "aa-title", "aa-md5", "ol-isbn-reverse"]


def _run_one(strategy: str, extra_argv: list[str]) -> int:
    script = _STRATEGY_TO_SCRIPT.get(strategy)
    if not script:
        print(f"error: unknown strategy '{strategy}'", file=sys.stderr)
        return 2
    path = _SWEEP_DIR / script
    if not path.exists():
        print(f"error: sweep script missing: {path}", file=sys.stderr)
        return 3
    print(f"[backfill] strategy={strategy} script={script}", file=sys.stderr)
    return subprocess.call([sys.executable, str(path), *extra_argv])


def run_backfill(strategy: str, extra_argv: list[str]) -> int:
    if strategy == "auto":
        for s in _AUTO_CHAIN:
            rc = _run_one(s, extra_argv)
            if rc != 0:
                print(f"[backfill] {s} returned rc={rc}, aborting chain", file=sys.stderr)
                return rc
        return 0
    return _run_one(strategy, extra_argv)
