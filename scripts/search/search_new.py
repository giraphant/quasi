#!/usr/bin/env python3
"""quasi-search — book / paper search across multiple sources.

Two-verb CLI. `quasi-search book` and `quasi-search paper` fan out to
per-platform source adapters in `sources/`, merge results into a fixed
BookRecord / PaperRecord schema, and emit a SearchResponse envelope.

This file is sectioned, top-to-bottom:
    1. SCHEMAS  — BookRecord, PaperRecord, SearchResponse, BookQuery, PaperQuery, AdapterResult
    2. MERGE    — match_and_priority + conflict surfacing
    3. BOOK     — book_search() main function
    4. PAPER    — paper_search() main function
    5. CLI      — argparse, main()

See docs/superpowers/specs/2026-05-17-search-refactor-design.md for design.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# adapter modules imported in Phase 4-9; left blank for skeleton


# ===============================================
# === 1. SCHEMAS
# ===============================================

# (populated by Task 1.2)


# ===============================================
# === 2. MERGE
# ===============================================

# (populated by Task 2.1)


# ===============================================
# === 3. BOOK SEARCH
# ===============================================

# (populated by Task 5.1)


# ===============================================
# === 4. PAPER SEARCH
# ===============================================

# (populated by Task 5.1)


# ===============================================
# === 5. CLI
# ===============================================

# (populated by Task 6.1)


if __name__ == "__main__":
    raise SystemExit("search_new.py: CLI not yet wired (Phase 6 pending)")
