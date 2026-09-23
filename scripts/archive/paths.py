"""Archive locations: root objects or one directory collection with collection.md."""
from pathlib import Path
import re

from scripts.webpage.paths import path_state

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def archive_pages(root: Path, *, strict: bool = True) -> list[Path]:
    base = root / 'vault/archives'
    state = path_state(root, base)
    if state == 'missing':
        return []
    if state != 'directory':
        if strict:
            raise ValueError('unsafe Archive root')
        return []
    pages = []
    for directory in sorted(base.iterdir()):
        if directory.name.startswith('.'):
            continue
        state = path_state(root, directory)
        if state != 'directory':
            if state != 'regular':
                if strict:
                    raise ValueError('unsafe Archive directory')
            continue
        page = directory / 'archive.md'
        marker = directory / 'collection.md'
        page_state, marker_state = path_state(root, page), path_state(root, marker)
        if page_state not in ('missing', 'regular') or marker_state not in ('missing', 'regular'):
            if strict:
                raise ValueError('unsafe Archive/Collection marker')
            continue
        if page_state == marker_state == 'regular':
            if strict:
                raise ValueError('ambiguous Archive/Collection directory')
            continue
        if page_state == 'regular':
            if SLUG.fullmatch(directory.name):
                pages.append(page)
        elif marker_state == 'regular':
            if re.search(r'[\\\x00-\x1f]', directory.name):
                if strict:
                    raise ValueError('unsafe Collection directory name')
                continue
            for member in sorted(directory.iterdir()):
                if member.name.startswith('.'):
                    continue
                member_state = path_state(root, member)
                if member_state == 'regular':
                    continue
                if member_state != 'directory':
                    if strict:
                        raise ValueError('unsafe Collection member')
                    continue
                if path_state(root, member / 'collection.md') != 'missing':
                    if strict:
                        raise ValueError('nested Collection is unsupported')
                    continue
                candidate = member / 'archive.md'
                state = path_state(root, candidate)
                if state not in ('missing', 'regular'):
                    if strict:
                        raise ValueError('unsafe Archive member')
                    continue
                if state == 'regular' and SLUG.fullmatch(member.name):
                    pages.append(candidate)
    slugs = [page.parent.name for page in pages]
    if len(set(slugs)) != len(slugs):
        if strict:
            raise ValueError('duplicate Archive slug across root/collections')
        pages = [page for page in pages if slugs.count(page.parent.name) == 1]
    return pages


def archive_path(root: Path, slug: str) -> Path:
    if not SLUG.fullmatch(slug):
        raise ValueError('invalid Archive slug')
    for page in archive_pages(root):
        if page.parent.name == slug:
            return page
    # A new object is always created at the archive root, never inside a group.
    directory = root / 'vault/archives' / slug
    if path_state(root, directory / 'collection.md') != 'missing':
        raise ValueError('Archive slug is occupied by a Collection')
    return directory / 'archive.md'
