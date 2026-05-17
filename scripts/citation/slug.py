#!/usr/bin/env python3
"""Author-surname → vault-slug normalization.

Vault convention observed in bts/:
    Ahmed             → ahmed
    M'charek          → mcharek
    Costanza-Chock    → costanza-chock
    Bauman & Murray   → bauman   (first surname only)
    Fujimura et al.   → fujimura
    斯特恩 / 拉图尔   → kept verbatim; flagged is_cjk=True for routing

A single citation token like "Browne" / "Fritsch et al." / "Bauman & Murray"
yields a normalised first-surname slug for vault Glob, plus enough metadata
for downstream routing and disambiguation.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# CJK Unified Ideographs blocks — good enough heuristic for "Chinese author name".
_CJK_RE = re.compile(r"[㐀-鿿]")


@dataclass
class AuthorToken:
    """Parsed view of the author portion of a single citation.

    raw            — exactly what appeared between '(' and the year
    first_surname  — surname used to build the vault slug
    slug           — normalised surname for vault Glob
    extra_surnames — additional surnames preserved verbatim (for verification)
    et_al          — True if 'et al.' appeared
    is_cjk         — True if first surname contains CJK characters
    """

    raw: str
    first_surname: str
    slug: str
    extra_surnames: list[str] = field(default_factory=list)
    et_al: bool = False
    is_cjk: bool = False


def _strip_accents(s: str) -> str:
    """Decompose then drop combining marks. M'charek stays "Mcharek"."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalise_surname(surname: str) -> str:
    """Surname → slug. Lowercase, drop accents+apostrophes, collapse spaces to '-'."""
    s = _strip_accents(surname.strip())
    s = s.replace("'", "").replace("’", "").replace("`", "")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-zA-Z0-9-]", "", s)
    return s.lower()


def parse_author_token(raw: str) -> AuthorToken:
    """Turn the author chunk of a citation into an AuthorToken.

    Handles: "Ahmed", "Fujimura et al.", "Bauman & Murray",
             "McRuer & Johnson", "Costanza-Chock", "斯特恩"
    """
    raw_stripped = raw.strip().rstrip(",，").strip()

    et_al = False
    work = raw_stripped
    # Strip et al. variants (English only — Chinese citations don't use it)
    # \b anchors after 'al', then optional trailing '.', so the period is consumed.
    et_al_re = re.compile(r"\bet\s*\.?\s*al\b\.?", re.IGNORECASE)
    if et_al_re.search(work):
        et_al = True
        work = et_al_re.sub("", work)
    # Tidy up: collapse internal whitespace, strip trailing dots/commas/spaces.
    work = re.sub(r"\s+", " ", work).strip(" .,，")

    # Split on '&' or whole-word 'and' or '与' — must use word boundaries on
    # 'and' so it doesn't bite into "Sanders" / "Garland".
    parts = re.split(r"\s*(?:&|\band\b|与)\s*", work)
    parts = [p.strip() for p in parts if p.strip()]
    first = parts[0] if parts else work
    extras = parts[1:]

    is_cjk = bool(_CJK_RE.search(first))
    slug = first if is_cjk else normalise_surname(first)

    return AuthorToken(
        raw=raw_stripped,
        first_surname=first,
        slug=slug,
        extra_surnames=extras,
        et_al=et_al,
        is_cjk=is_cjk,
    )


if __name__ == "__main__":
    # Sanity examples — invoked manually only.
    for sample in [
        "Ahmed", "M'charek", "Costanza-Chock",
        "Bauman & Murray", "Fujimura et al.", "Fritsch et al.,",
        "McRuer & Johnson", "斯特恩", "Quijano",
    ]:
        print(f"{sample!r:30s} → {parse_author_token(sample)}")
