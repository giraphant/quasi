"""Pure capability functions for saved Webpage material."""

from .webarchive import (
    ExtractionResult,
    WebArchiveDocument,
    collision_slug,
    extract_webarchive,
    normalize_web_url,
    read_webarchive,
)

__all__ = [
    "ExtractionResult",
    "WebArchiveDocument",
    "collision_slug",
    "extract_webarchive",
    "normalize_web_url",
    "read_webarchive",
]
