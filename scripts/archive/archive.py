"""Public Archive acquisition: original files, provenance and a Markdown display page."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import hashlib
from itertools import chain
import math
import time
import mimetypes
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import unquote, urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

from scripts.core import dump_frontmatter, print_json, project_root, read_frontmatter
from scripts.schemas.archive import ArchiveSchema
from scripts.schemas.archive_manifest import ArchiveManifest, ArchiveFile, ArchiveSource
from scripts.webpage.paths import lexical_project_path, path_state
from scripts.webpage.webarchive import normalize_web_url
from .inventory import digest, load_manifest, observe_collection, revision

MAX_BYTES = 1024 * 1024 * 1024
PDF_PAGE_LIMIT = 16
PDF_TEXT_LIMIT = 6000
NAME = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+$')
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


class Conflict(ValueError):
    pass


def response(url):
    url = normalize_web_url(url)
    result = requests.get(url, stream=True, timeout=(15, 60), headers={'User-Agent': 'quasi-archive/0.1'})
    try:
        result.raise_for_status()
        normalize_web_url(result.url)
    except Exception:
        result.close()
        raise
    return result


def _pdf_pages(selection: str | None, count: int) -> list[int]:
    """Physical, one-based pages; the caller chooses what to inspect next."""
    if selection is None:
        return list(range(1, min(8, count) + 1))
    selected = set()
    for part in selection.split(','):
        if not re.fullmatch(r'[1-9][0-9]*(?:-[1-9][0-9]*)?', part):
            raise ValueError('PDF pages must be numbers or ranges, e.g. 1-8 or 5,19')
        ends = [int(value) for value in part.split('-')]
        first, last = ends[0], ends[-1]
        if first > last or last > count or last - first >= PDF_PAGE_LIMIT:
            raise ValueError('PDF page range is outside the document or exceeds 16 pages')
        selected.update(range(first, last + 1))
        if len(selected) > PDF_PAGE_LIMIT:
            raise ValueError('inspect accepts at most 16 PDF pages per invocation')
    return sorted(selected)


@contextmanager
def _inspection_output(root: Path, output_dir: Path | None):
    """Only an explicit, new scratch directory may retain PDF evidence."""
    if output_dir is None:
        yield None, None
        return
    path = lexical_project_path(root, output_dir)
    relative = path.relative_to(root)
    if relative.parts[:2] != ('.quasi', 'temp') or len(relative.parts) < 3:
        raise ValueError('inspection output must be a new directory under .quasi/temp/')
    with _directory(root, relative.parent, True) as parent:
        os.mkdir(relative.name, mode=0o700, dir_fd=parent)  # Never reuse or overwrite.
        try:
            with _directory(root, relative) as directory:
                try:
                    yield relative.as_posix(), directory
                    _same_directory(root, path, directory)
                    os.fsync(directory)
                except BaseException:
                    for name in os.listdir(directory):
                        os.unlink(name, dir_fd=directory)
                    raise
        except BaseException:
            os.rmdir(relative.name, dir_fd=parent)
            raise


def _pdf_evidence(chunks, *, pages=None, output_dir=None, root=None, source_path=None,
                  expected_size=None, started=None) -> dict:
    """Spool complete bytes to disk, then expose bounded text and optional images.

    PDF xref tables can be at EOF: a response prefix is not a PDF inspection.
    Scratch source.pdf is evidence only; collect still owns canonical originals.
    """
    import fitz
    started = time.monotonic() if started is None else started
    if expected_size is not None and expected_size > MAX_BYTES:
        raise ValueError('PDF exceeds the 1 GiB inspection limit')
    with tempfile.TemporaryDirectory(prefix='quasi-archive-pdf-') as temporary:
        source = Path(temporary) / 'source.pdf'
        size, sha = 0, hashlib.sha256()
        with source.open('xb') as stream:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('PDF exceeds the 1 GiB inspection limit')
                if time.monotonic() - started > 300:
                    raise ValueError('PDF inspection download exceeded five minutes')
                sha.update(chunk)
                stream.write(chunk)
        if expected_size is not None and size != expected_size:
            raise ValueError('incomplete PDF response; Content-Length does not match received bytes')
        try:
            document = fitz.open(source)
        except RuntimeError as exc:
            raise ValueError('cannot open PDF for inspection') from exc
        with document:
            if not document.is_pdf or document.needs_pass or document.page_count == 0:
                raise ValueError('inspection requires a readable, unencrypted, non-empty PDF')
            selected = _pdf_pages(pages, document.page_count)
            evidence = {'source_path': source_path, 'cached_pdf': None,
                        'size': size, 'sha256': sha.hexdigest(), 'page_count': document.page_count,
                        'metadata': {key: value[:2000] for key, value in document.metadata.items()
                                     if isinstance(value, str) and value},
                        'pages': [], 'partial': len(selected) < document.page_count}
            with _inspection_output(root or project_root(), output_dir) as (directory, fd):
                def save(name, chunks):
                    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    with os.fdopen(out, 'wb') as stream:
                        for chunk in chunks:
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                if fd is not None:
                    with source.open('rb') as stream:
                        save('source.pdf', iter(lambda: stream.read(1024 * 1024), b''))
                    evidence['cached_pdf'] = directory + '/source.pdf'
                for number in selected:
                    try:
                        page = document[number - 1]
                        text = page.get_text(sort=True)
                        item = {'page': number, 'text': text[:PDF_TEXT_LIMIT],
                                'text_truncated': len(text) > PDF_TEXT_LIMIT, 'preview_path': None}
                        if fd is not None:
                            extent = max(page.rect.width, page.rect.height)
                            if not math.isfinite(extent) or extent <= 0:
                                raise ValueError(f'invalid dimensions for PDF page {number}')
                            scale = min(2, 1600 / extent)
                            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                            name = f'page-{number:04d}.png'
                            save(name, [pixmap.tobytes('png')])
                            item['preview_path'] = directory + '/' + name
                    except RuntimeError as exc:
                        raise ValueError(f'cannot inspect PDF page {number}') from exc
                    evidence['pages'].append(item)
                    evidence['partial'] |= item['text_truncated']
            return evidence


def inspect_pdf(path: Path, *, pages=None, output_dir=None, root=None) -> dict:
    """Read a caller-named local PDF; do not invent a remote URL association."""
    root = root or project_root()
    source = path if path.is_absolute() else root / path
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('PDF inspection input must be a regular file')
        evidence = _pdf_evidence(iter(lambda: stream.read(1024 * 1024), b''), pages=pages,
                                 output_dir=output_dir, root=root, source_path=str(path), expected_size=info.st_size)
    return {'schema_version': 'quasi.archive.inspect/0.1', 'status': 'complete',
            'url': None, 'final_url': None, 'media_type': 'application/pdf', 'title': path.name,
            'metadata_evidence': [], 'candidates': [], 'pdf': evidence, 'truncated': evidence['partial']}


def inspect(url: str, *, pages=None, output_dir=None, root=None) -> dict:
    """Inspect one source; links are candidates, never automatic collection scope."""
    started = time.monotonic()
    with response(url) as result:
        media = result.headers.get('Content-Type', '').split(';')[0].lower()
        filename = unquote(Path(urlsplit(result.url).path).name)
        data = bytearray()
        chunks = iter(result.iter_content(65536))
        for chunk in chunks:
            data.extend(chunk)
            if len(data) >= 2 * 1024 * 1024:
                break
        html = media in ('text/html', 'application/xhtml+xml') or bytes(data).lstrip().lower().startswith((b'<!doctype html', b'<html'))
        if bytes(data).lstrip().startswith(b'%PDF-') or (media == 'application/pdf' and not html):
            length = result.headers.get('Content-Length', '')
            expected_size = int(length) if length.isdigit() and result.headers.get('Content-Encoding', 'identity') == 'identity' else None
            evidence = _pdf_evidence(chain([data], chunks), pages=pages, output_dir=output_dir,
                                     root=root, expected_size=expected_size, started=started)
            return {'schema_version': 'quasi.archive.inspect/0.1', 'status': 'complete',
                    'url': url, 'final_url': result.url, 'media_type': 'application/pdf', 'title': filename,
                    'metadata_evidence': [], 'candidates': [], 'pdf': evidence, 'truncated': evidence['partial']}
        title, candidates, metadata_evidence = filename, [], []
        if html:
            soup = BeautifulSoup(bytes(data), 'html.parser')
            title = soup.title.get_text(' ', strip=True) if soup.title else filename
            # Return source-labelled evidence; the specialist distinguishes publication
            # from modification and rejects unrelated comments/site copyright dates.
            for tag in soup.select('meta[content], time[datetime]'):
                key = tag.get('property') or tag.get('name') or tag.get('itemprop') or 'time'
                if tag.name == 'time' or any(x in key.lower() for x in ('date', 'published', 'modified', 'author', 'site_name')):
                    metadata_evidence.append({'field': key, 'value': (tag.get('content') or tag.get('datetime') or '')[:1000],
                                              'context': tag.get_text(' ', strip=True)[:300]})
            for tag in soup.select('script[type="application/ld+json"]'):
                try:
                    data_ld = json.loads(tag.get_text())
                except (ValueError, TypeError):
                    continue
                nodes = data_ld if isinstance(data_ld, list) else [data_ld]
                for node in nodes:
                    if isinstance(node, dict):
                        graph = node.get('@graph', [])
                        for item in [node, *(graph if isinstance(graph, list) else [])]:
                            if isinstance(item, dict):
                                fields = {k: item[k] for k in ('@type', 'headline', 'name', 'url', 'datePublished', 'dateModified', 'author', 'publisher') if k in item}
                                if fields:
                                    metadata_evidence.append({'field': 'json-ld', 'value': json.dumps(fields, ensure_ascii=False)[:6000]})
            seen = set()
            for tag in soup.select('a[href], img[src], video[src], audio[src], source[src]'):
                raw = tag.get('href') or tag.get('src')
                try:
                    target = normalize_web_url(urljoin(result.url, raw))
                except ValueError:
                    continue
                if target in seen:
                    continue
                seen.add(target)
                candidates.append({'url': target, 'element': tag.name,
                                   'label': tag.get('alt') or tag.get_text(' ', strip=True)[:280]})
        return {'schema_version': 'quasi.archive.inspect/0.1', 'status': 'complete',
                'url': url, 'final_url': result.url, 'media_type': 'text/html' if html else media,
                'title': title, 'metadata_evidence': metadata_evidence[:60], 'candidates': candidates[:200],
                'truncated': len(data) >= 2 * 1024 * 1024 or len(candidates) > 200 or len(metadata_evidence) > 60}


def _download(url: str, output: Path) -> tuple[str, str]:
    with response(url) as result:
        media = result.headers.get('Content-Type', '').split(';')[0].lower()
        total, prefix = 0, b''
        started = time.monotonic()
        with output.open('xb') as stream:
            for chunk in result.iter_content(1024 * 1024):
                total += len(chunk)
                if time.monotonic() - started > 300:
                    raise ValueError('original download exceeded five minutes')
                if total > MAX_BYTES:
                    raise ValueError('original exceeds the 1 GiB per-file download limit')
                if len(prefix) < 1024:
                    prefix += chunk[:1024 - len(prefix)]
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if not total:
            raise ValueError('empty original')
        # Do not silently publish a login/error HTML page as an image, PDF or video.
        if media in ('text/html', 'application/xhtml+xml') or prefix.lstrip().lower().startswith((b'<!doctype html', b'<html')):
            raise ValueError('download returned HTML; use webarchive for a webpage')
        suffix = output.suffix.lower()
        magic = {'.pdf': prefix.startswith(b'%PDF-'), '.jpg': prefix.startswith(b'\xff\xd8\xff'),
                 '.jpeg': prefix.startswith(b'\xff\xd8\xff'), '.png': prefix.startswith(b'\x89PNG\r\n\x1a\n'),
                 '.gif': prefix.startswith((b'GIF87a', b'GIF89a')),
                 '.webp': prefix.startswith(b'RIFF') and prefix[8:12] == b'WEBP'}
        if suffix in magic and not magic[suffix]:
            raise ValueError('download bytes do not match the requested file format')
        guessed = mimetypes.guess_type(output.name)[0]
        if media in ('', 'application/octet-stream'):
            media = guessed or 'application/octet-stream'
        if not (media == 'application/pdf' or media.startswith(('image/', 'video/', 'audio/'))):
            raise ValueError('unsupported original format; retain its source link')
        return media, result.url


def _capture(url: str, output: Path) -> tuple[str, str]:
    from scripts.webpage.webpage import capture, inspect as inspect_page
    identity = inspect_page(url)
    if identity.get('status') != 'complete':
        raise ValueError('webpage inspection failed')
    receipt = capture(url, identity['final_url'], output)
    if receipt.get('status') != 'complete':
        raise ValueError('webarchive capture failed: ' + str(receipt.get('issue') or receipt.get('error')))
    return 'application/x-webarchive', identity['final_url']


@contextmanager
def _directory(root: Path, relative: Path, create: bool = False):
    """Pin each directory component; never use symlinked output ancestry."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts:
            if part in ('.', '..'):
                raise Conflict('unsafe directory component')
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _lock(root, identity):
    # Different objects can collect concurrently; either same slug OR same source
    # serializes publication. Lock files are synchronization only, never run state.
    keys = sorted({hashlib.sha256(value.encode()).hexdigest() for value in (
        'slug:' + identity['slug'], 'url:' + normalize_web_url(identity['url']))})
    descriptors = []
    try:
        # Readers/writers of different Archives may coexist; a Marple directory
        # move requires the exclusive side of this same lock.
        with _directory(root, Path('.marple'), True) as shared:
            fd = os.open('archive-collections.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=shared)
            descriptors.append(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Conflict('Archive collection move in progress; obtain fresh status') from exc
        pending = root / '.marple/collection-operations'
        pending_state = path_state(root, pending)
        if pending_state not in ('missing', 'directory'):
            raise Conflict('unsafe Marple collection operation journal')
        if pending_state == 'directory':
            for record in pending.glob('*.json'):
                if path_state(root, record) != 'regular':
                    raise Conflict('unsafe Marple collection operation journal')
                try:
                    operation = json.loads(record.read_text())
                except (OSError, ValueError) as exc:
                    raise Conflict('unreadable Marple collection operation requires recovery') from exc
                if not isinstance(operation, dict) or operation.get('result') is None:
                    raise Conflict('incomplete Marple collection operation requires recovery')
        with _directory(root, Path('.quasi/locks'), True) as directory:
            for key in keys:
                fd = os.open(f'archive-{key}.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                descriptors.append(fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise Conflict('this Archive has an active collector; obtain fresh status before resuming') from exc
            yield
    finally:
        for fd in descriptors:
            os.close(fd)


def _same_directory(root, path, fd):
    if path_state(root, path) != 'directory':
        raise Conflict('Archive directory changed during collection')
    stat = path.stat()
    pinned = os.fstat(fd)
    if (stat.st_dev, stat.st_ino) != (pinned.st_dev, pinned.st_ino):
        raise Conflict('Archive directory changed during collection')


def _replace_text(fd, name, text):
    temporary = f'.{name}-{os.urandom(8).hex()}'
    out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(out, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _validate_request(request):
    required = {'identity', 'topics', 'expected_revision', 'files', 'body', 'coverage'}
    if not isinstance(request, dict) or not required <= set(request) or set(request) - required - {'metadata'}:
        raise ValueError('collect request requires identity/topics/expected_revision/files/body/coverage, with optional metadata')
    identity = request['identity']
    if not isinstance(identity, dict) or set(identity) != {'slug', 'title', 'kind', 'url'}:
        raise ValueError('invalid Archive identity')
    if not isinstance(identity['slug'], str) or not SLUG.fullmatch(identity['slug']) or len(identity['slug']) > 80:
        raise ValueError('invalid Archive slug')
    normalize_web_url(identity['url'])
    ArchiveSchema.model_validate({'type': 'archive', 'title': identity['title'], 'kind': identity['kind'], 'created': '2000-01-01'})
    metadata = request.get('metadata', {})
    if not isinstance(metadata, dict) or set(metadata) - {'creator', 'date', 'source'}:
        raise ValueError('metadata permits only creator/date/source; omit unknown fields')
    if any(value is None or value == '' or value == [] for value in metadata.values()):
        raise ValueError('omit unknown metadata instead of supplying empty values')
    ArchiveSchema.model_validate({'type': 'archive', 'title': identity['title'], 'kind': identity['kind'],
                                  'created': '2000-01-01', **metadata})
    if not isinstance(request['expected_revision'], str) or not re.fullmatch('[0-9a-f]{64}', request['expected_revision']):
        raise ValueError('expected_revision must come from fresh Archive status')
    if not isinstance(request['topics'], list) or not all(isinstance(x, str) and SLUG.fullmatch(x) and len(x) <= 80 for x in request['topics']):
        raise ValueError('invalid Topic membership')
    if not all(isinstance(request[x], str) for x in ('body', 'coverage')):
        raise ValueError('body and coverage must be strings')
    if not isinstance(request['files'], list) or len(request['files']) > 200:
        raise ValueError('files must be a bounded list of selected originals')
    names = set()
    for item in request['files']:
        if not isinstance(item, dict) or not {'name', 'url', 'method', 'title', 'description'} <= set(item) or set(item) - {'name', 'url', 'method', 'title', 'description', 'source'}:
            raise ValueError('file requires name/url/method/title/description, with optional source override')
        if not isinstance(item['name'], str) or not NAME.fullmatch(item['name']) or len(item['name']) > 160 or item['name'] in names:
            raise ValueError('original filenames must be unique descriptive kebab-case filenames')
        for field in ('title', 'description'):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f'original {field} must be a nonblank string')
        names.add(item['name'])
        normalize_web_url(item['url'])
        if item['method'] not in ('download', 'webarchive') or (item['method'] == 'webarchive' and not item['name'].endswith('.webarchive')):
            raise ValueError('invalid acquisition method or webarchive filename')
        if 'source' in item:
            ArchiveSource.model_validate(item['source'])
            normalize_web_url(item['source']['url'])


def collect(root: Path, request: dict) -> dict:
    """One serialized, optimistic transaction. Unknown publication never retries."""
    publishing = False
    try:
        _validate_request(request)
        identity = request['identity']
        from scripts.archive.paths import archive_path
        with _lock(root, identity):
            directory = archive_path(root, identity['slug']).parent
            if revision(root, directory) != request['expected_revision']:
                raise Conflict('Archive changed since observation; obtain fresh status')
            collection = observe_collection(root, directory)
            if collection['present'] and not collection['usable']:
                raise Conflict('existing inventory or original is damaged; reconcile explicitly')
            # Recheck URL ownership inside the writer lock, including different proposed slugs.
            from scripts.vault.resolve import resolve
            row = resolve(root, [{'kind': 'archive', 'slug': identity['slug'], 'url': identity['url']}])['resolved'][0]
            if row.get('error') or (row.get('vault_slug') and row['vault_slug'] != identity['slug']):
                raise Conflict('Archive URL/slug ownership changed; obtain fresh status and resolve again')
            page = directory / 'archive.md'
            existing = path_state(root, page) == 'regular'
            if existing:
                document = read_frontmatter(page)
                metadata = document.frontmatter
                record = ArchiveSchema.model_validate(metadata)
                if record.kind != identity['kind']:
                    raise Conflict('Archive kind changed')
                body = document.body
            else:
                metadata = {'type': 'archive', 'title': identity['title'], 'kind': identity['kind'],
                            'created': datetime.now(timezone.utc).date().isoformat()}
                body = request['body'].strip() + '\n'
                if not re.match(r'^# ', body):
                    body = f'# {identity["title"]}\n\n' + body
            for key, value in request.get('metadata', {}).items():
                if key in metadata and metadata[key] not in (None, '', []) and str(metadata[key]) != str(value):
                    raise Conflict(f'existing Archive {key} differs; reconcile explicitly')
                metadata[key] = value
            if not existing or request.get('metadata'):
                metadata.setdefault('url', identity['url'])
            ArchiveSchema.model_validate(metadata)
            metadata['topics'] = list(dict.fromkeys([*metadata.get('topics', []), *request['topics']]))
            manifest = load_manifest(directory / 'manifest.yaml') if collection['present'] else ArchiveManifest(
                source=ArchiveSource(url=identity['url'], title=identity['title']))
            if normalize_web_url(manifest.source.url) != normalize_web_url(identity['url']):
                raise Conflict('manifest source differs from requested identity')
            prior_paths = {item.path for item in manifest.files}
            originals = directory / 'originals'
            if path_state(root, originals) not in ('missing', 'directory'):
                raise Conflict('unsafe originals directory')
            if originals.exists() and {x.name for x in originals.iterdir()} != {Path(x).name for x in prior_paths}:
                raise Conflict('unlisted originals require reconciliation before collection')
            for item in request['files']:
                relative = 'originals/' + item['name']
                if relative in prior_paths or path_state(root, directory / relative) != 'missing':
                    raise Conflict('original already exists; never overwrite or silently adopt it')
            # Stage all remote writes outside canonical storage. A process death here has no
            # published outcome; no stage is ever treated as a resumable acquisition cursor.
            with _directory(root, Path('.quasi/temp'), True):
                pass
            with tempfile.TemporaryDirectory(prefix='archive-', dir=root / '.quasi/temp') as temporary:
                staged = Path(temporary)
                additions, notes = [], []
                for item in request['files']:
                    output = staged / item['name']
                    try:
                        media, final_url = (_capture if item['method'] == 'webarchive' else _download)(item['url'], output)
                        asset = ArchiveFile(path='originals/' + item['name'], title=item['title'],
                            description=item['description'], media_type=media,
                            captured_at=datetime.now(timezone.utc), size=output.stat().st_size,
                            sha256=digest(output), url=final_url, source=item.get('source'))
                        additions.append(asset)
                    except (OSError, ValueError, requests.RequestException) as exc:
                        output.unlink(missing_ok=True)
                        notes.append(f"未取得 {item['name']}（{item['url']}）：{exc}")
                manifest.files.extend(additions)
                manifest.coverage = '\n'.join(x for x in [manifest.coverage, request['coverage'], *notes] if x)
                manifest = ArchiveManifest.model_validate(manifest.model_dump())
                if additions:
                    body += '\n## 本地原件\n'
                for asset in additions:
                    name = asset.title.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
                    if asset.media_type.startswith('image/'):
                        body += f'\n![{name}]({asset.path})\n'
                    else:
                        body += f'\n[{name}]({asset.path})\n'
                if not existing and not body.strip():
                    body = f'# {identity["title"]}\n'
                text = f'---\n{dump_frontmatter(metadata)}\n---\n{body}'
                inventory = yaml.safe_dump(manifest.model_dump(mode='json', exclude_none=True), allow_unicode=True, sort_keys=False)
                with _directory(root, directory.relative_to(root), True) as destination:
                    _same_directory(root, directory, destination)
                    if revision(root, directory) != request['expected_revision']:
                        raise Conflict('Archive changed during acquisition; publication cancelled')
                    publishing = True
                    if additions:
                        with _directory(root, (directory / 'originals').relative_to(root), True) as originals:
                            for asset in additions:
                                os.link(staged / Path(asset.path).name, Path(asset.path).name, dst_dir_fd=originals, follow_symlinks=False)
                            os.fsync(originals)
                    _same_directory(root, directory, destination)
                    _replace_text(destination, 'archive.md', text)
                    # Inventory is the final publication marker, not a workflow state file.
                    _replace_text(destination, 'manifest.yaml', inventory)
                return {'schema_version': 'quasi.archive.collect/0.1', 'status': 'complete',
                        'path': page.relative_to(root).as_posix(), 'files_saved': len(additions),
                        'notes': notes, 'revision': revision(root, directory)}
    except (OSError, ValueError, TypeError, requests.RequestException, yaml.YAMLError) as exc:
        return {'schema_version': 'quasi.archive.collect/0.1', 'status': 'blocked' if publishing or isinstance(exc, Conflict) else 'failed',
                'code': 'archive.outcome_unknown' if publishing else 'archive.conflict' if isinstance(exc, Conflict) else 'archive.collect_failed',
                'message': str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect_parser = commands.add_parser('inspect')
    source = inspect_parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--url')
    source.add_argument('--path', type=Path, help='exact caller-named local PDF (no remote URL claim)')
    inspect_parser.add_argument('--pages', help='physical PDF pages, e.g. 1-8 or 5,19; default first 8, maximum 16')
    inspect_parser.add_argument('--output-dir', type=Path, help='new .quasi/temp/ directory for source.pdf and selected page PNGs')
    read_parser = commands.add_parser('read')
    read_parser.add_argument('--path', required=True)
    collect_parser = commands.add_parser('collect')
    collect_parser.add_argument('--request-file', required=True)
    args = parser.parse_args()
    try:
        root = project_root().resolve()
        if args.command == 'inspect':
            options = {'pages': args.pages, 'output_dir': args.output_dir, 'root': root}
            result = inspect(args.url, **options) if args.url else inspect_pdf(args.path, **options)
        elif args.command == 'read':
            from scripts.webpage.webarchive import read_webarchive
            path = Path(args.path)
            if not path.is_absolute():
                path = root / path
            if path_state(root, path) != 'regular' or path.suffix != '.webarchive':
                raise ValueError('read requires an exact safe Webarchive original')
            document = read_webarchive(path)
            soup = BeautifulSoup(document.html, 'html.parser')
            for tag in soup(['script', 'style']):
                tag.decompose()
            text = soup.get_text('\n', strip=True)
            result = {'status': 'complete', 'path': args.path, 'url': document.url,
                      'text': text[:200000], 'truncated': len(text) > 200000}
        else:
            request = Path(args.request_file)
            if not request.is_absolute():
                request = root / request
            if path_state(root, request) != 'regular':
                raise ValueError('request file must be an exact safe project-local file')
            result = collect(root, json.loads(request.read_text()))
    except (OSError, ValueError, requests.RequestException) as exc:
        result = {'status': 'failed', 'message': str(exc)}
    print_json(result)
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
