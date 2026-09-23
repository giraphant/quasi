"""Public Archive acquisition: original files, provenance and a Markdown display page."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import hashlib
import time
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

from scripts.core import dump_frontmatter, print_json, project_root, read_frontmatter
from scripts.schemas.archive import ArchiveSchema
from scripts.schemas.archive_manifest import ArchiveManifest, ArchiveFile, ArchiveSource
from scripts.webpage.paths import path_state
from scripts.webpage.webarchive import normalize_web_url
from .inventory import digest, load_manifest, observe_collection, revision

MAX_BYTES = 1024 * 1024 * 1024
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


def inspect(url: str) -> dict:
    """Inspect one source; links are candidates, never automatic collection scope."""
    with response(url) as result:
        media = result.headers.get('Content-Type', '').split(';')[0].lower()
        filename = unquote(Path(urlsplit(result.url).path).name)
        data = bytearray()
        for chunk in result.iter_content(65536):
            data.extend(chunk)
            if len(data) >= 2 * 1024 * 1024:
                break
        html = media in ('text/html', 'application/xhtml+xml') or bytes(data).lstrip().lower().startswith((b'<!doctype html', b'<html'))
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
    inspect_parser.add_argument('--url', required=True)
    read_parser = commands.add_parser('read')
    read_parser.add_argument('--path', required=True)
    collect_parser = commands.add_parser('collect')
    collect_parser.add_argument('--request-file', required=True)
    args = parser.parse_args()
    try:
        root = project_root().resolve()
        if args.command == 'inspect':
            result = inspect(args.url)
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
