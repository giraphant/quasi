"""Read-only inventory shared by status, collection and URL resolution."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from scripts.schemas.archive_manifest import ArchiveManifest
from scripts.webpage.paths import path_state
from scripts.webpage.webarchive import normalize_web_url


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("manifest mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_manifest(path: Path) -> ArchiveManifest:
    return ArchiveManifest.model_validate(yaml.load(path.read_text(), Loader=UniqueLoader))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def revision(root: Path, directory: Path) -> str:
    value = hashlib.sha256()
    for name in ('archive.md', 'manifest.yaml'):
        path = directory / name
        state = path_state(root, path)
        if state not in ('missing', 'regular'):
            raise ValueError('unsafe Archive metadata path')
        value.update(name.encode())
        value.update((digest(path) if state == 'regular' else 'missing').encode())
    return value.hexdigest()


def observe_collection(root: Path, directory: Path) -> dict:
    path = directory / 'manifest.yaml'
    state = path_state(root, path)
    result = {'path': path.relative_to(root).as_posix(), 'present': state != 'missing',
              'usable': False, 'revision': None, 'source_url': None, 'files': [], 'coverage': None}
    try:
        result['revision'] = revision(root, directory)
        if state != 'regular':
            return result
        manifest = load_manifest(path)
        normalize_web_url(manifest.source.url)
        result['source_url'] = manifest.source.url
        result['coverage'] = manifest.coverage
        usable = True
        for item in manifest.files:
            normalize_web_url(item.url)
            if item.source is not None:
                normalize_web_url(item.source.url)
            original = directory / item.path
            file_state = path_state(root, original)
            valid = (file_state == 'regular' and original.stat().st_size == item.size
                     and digest(original) == item.sha256)
            result['files'].append({'path': original.relative_to(root).as_posix(),
                                    'present': file_state != 'missing', 'usable': valid,
                                    'media_type': item.media_type})
            usable = usable and valid
        originals = directory / 'originals'
        original_state = path_state(root, originals)
        if original_state not in ('missing', 'directory'):
            usable = False
        elif original_state == 'directory':
            declared = {Path(item.path).name for item in manifest.files}
            # Detect a partially published additive transaction (or manual additions)
            # instead of treating unlisted originals as an already completed collection.
            if {path.name for path in originals.iterdir()} != declared:
                usable = False
        result['usable'] = usable
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        pass
    return result
