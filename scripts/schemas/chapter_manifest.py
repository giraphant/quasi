"""Shared structural predicates for durable chapter manifests."""


def valid_chapter_page_pair(start: object, end: object) -> bool:
    """Accept absent pagination or one exact, ordered positive integer range."""

    if start is None or end is None:
        return start is None and end is None
    return (
        type(start) is int
        and type(end) is int
        and 1 <= start <= end
    )
