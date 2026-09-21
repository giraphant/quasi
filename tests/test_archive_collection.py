"""Original collection, provenance and cooperating concurrent writer boundaries."""
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from scripts.archive import archive as cli
from scripts.archive.inventory import load_manifest, observe_collection, revision
from scripts.core import read_frontmatter
from scripts.status.status import archive_status
from scripts.vault.resolve import resolve

URL = 'https://example.org/repair'
SLUG = 'iphone-screen-repair'


def request(root, *, slug=SLUG, topics=None, files=None):
    return {'identity': {'slug': slug, 'title': 'iPhone screen repair', 'kind': 'thread', 'url': URL},
            'topics': topics or ['repair'], 'expected_revision': revision(root, root / 'vault/archives' / slug),
            'files': files or [], 'body': '已核读的整组说明。', 'coverage': '只收录帖子正文与两张配图；未收录评论。'}


def asset(name='001-screen-discoloration.jpg', url='https://example.org/image.jpg', **kwargs):
    return {'name': name, 'url': url, 'method': 'download', **kwargs}


@pytest.fixture
def downloaded(monkeypatch):
    def fake(url, path):
        path.write_bytes(b'actual-original-bytes')
        return ('video/mp4' if path.suffix == '.mp4' else 'image/jpeg'), url
    monkeypatch.setattr(cli, '_download', fake)
    return fake


def test_originals_manifest_inheritance_and_display(tmp_path, downloaded):
    value = request(tmp_path, files=[asset(), asset('002-connector-detail.jpg'),
        asset('003-screen-removal.mp4', source={'url': 'https://other.org/video'})])
    result = cli.collect(tmp_path, value)
    assert result['status'] == 'complete', result
    directory = tmp_path / 'vault/archives' / SLUG
    manifest = load_manifest(directory / 'manifest.yaml')
    assert manifest.source.url == URL
    assert manifest.files[0].source is None
    assert manifest.files[2].source.url == 'https://other.org/video'
    assert [x.path for x in manifest.files] == ['originals/' + x['name'] for x in value['files']]
    assert all(x.sha256 and x.captured_at.tzinfo for x in manifest.files)
    text = (directory / 'archive.md').read_text()
    assert '![' in text and '](originals/003-screen-removal.mp4)' in text
    assert 'url:' not in text and 'source:' not in text
    assert not (directory / 'derived').exists()
    status = archive_status(tmp_path, SLUG)
    assert status['facts']['collection']['usable']
    assert len(status['facts']['collection']['files']) == 3
    owner = resolve(tmp_path, [{'kind': 'archive', 'slug': 'other-topic-name', 'url': URL}])['resolved'][0]
    assert owner['vault_slug'] == SLUG


def test_missing_download_is_coverage_not_collection_failure(tmp_path, downloaded, monkeypatch):
    def partial(url, path):
        if 'absent' in url:
            raise ValueError('404 missing')
        return downloaded(url, path)
    monkeypatch.setattr(cli, '_download', partial)
    result = cli.collect(tmp_path, request(tmp_path, files=[asset(), asset('002-missing.jpg', 'https://example.org/absent')]))
    assert result['status'] == 'complete'
    fact = archive_status(tmp_path, SLUG)['facts']['collection']
    assert fact['usable'] and len(fact['files']) == 1
    assert '未取得 002-missing.jpg' in fact['coverage']


def test_link_only_inventory_and_membership_preserve_user_content(tmp_path):
    assert cli.collect(tmp_path, request(tmp_path))['status'] == 'complete'
    page = tmp_path / 'vault/archives' / SLUG / 'archive.md'
    page.write_text(page.read_text() + '\n用户后来写的注释。\n')
    old = read_frontmatter(page)
    followup = request(tmp_path, topics=['second-topic'])
    followup.update(body='', coverage='')
    assert cli.collect(tmp_path, followup)['status'] == 'complete'
    new = read_frontmatter(page)
    assert new.body == old.body
    assert new.frontmatter['created'] == old.frontmatter['created']
    assert new.frontmatter['topics'] == ['repair', 'second-topic']


def test_legacy_record_enriches_without_rewriting_body(tmp_path, downloaded):
    page = tmp_path / 'vault/archives' / SLUG / 'archive.md'
    page.parent.mkdir(parents=True)
    page.write_text('---\ntype: archive\ntitle: Legacy repair\nkind: thread\ncreated: 2020-01-01\nurl: '+URL+'\n---\nOld prose.\n')
    result = cli.collect(tmp_path, request(tmp_path, files=[asset()]))
    assert result['status'] == 'complete', result
    assert 'Old prose.' in page.read_text() and '2020-01-01' in page.read_text()
    assert '![001-screen-discoloration]' in page.read_text()


def test_stale_writer_and_same_url_other_slug_do_not_overwrite(tmp_path):
    first = request(tmp_path)
    stale = request(tmp_path, topics=['second-topic'])
    assert cli.collect(tmp_path, first)['status'] == 'complete'
    result = cli.collect(tmp_path, stale)
    assert result['code'] == 'archive.conflict'
    other = request(tmp_path, slug='another-name')
    assert cli.collect(tmp_path, other)['code'] == 'archive.conflict'
    assert not (tmp_path / 'vault/archives/another-name').exists()
    fresh = request(tmp_path, topics=['second-topic'])
    assert cli.collect(tmp_path, fresh)['status'] == 'complete'
    assert archive_status(tmp_path, SLUG)['identity']['topics'] == ['repair', 'second-topic']


def _hold_lock(root, ready, release):
    with cli._lock(Path(root), {'slug': SLUG, 'url': URL}):
        ready.set()
        release.wait(10)


def test_two_processes_serialize_archive_writes(tmp_path):
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_lock, args=(str(tmp_path), ready, release))
    process.start()
    try:
        assert ready.wait(10)
        result = cli.collect(tmp_path, request(tmp_path))
        assert result['code'] == 'archive.conflict'
        assert not (tmp_path / 'vault/archives' / SLUG).exists()
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    assert cli.collect(tmp_path, request(tmp_path))['status'] == 'complete'


def test_tampered_original_is_not_admitted(tmp_path, downloaded):
    cli.collect(tmp_path, request(tmp_path, files=[asset()]))
    original = tmp_path / 'vault/archives' / SLUG / 'originals/001-screen-discoloration.jpg'
    original.write_bytes(b'changed')
    assert not archive_status(tmp_path, SLUG)['facts']['collection']['usable']
    assert cli.collect(tmp_path, request(tmp_path))['code'] == 'archive.conflict'


@pytest.mark.parametrize('name', ['../outside.jpg', '/outside.jpg', 'one/two.jpg', '001.jpg/escape', 'file.jpg?query'])
def test_unsafe_filename_rejected_before_writes(tmp_path, name):
    assert cli.collect(tmp_path, request(tmp_path, files=[asset(name)]))['status'] == 'failed'
    assert not (tmp_path / 'vault').exists()


def test_symlinked_archive_directory_never_writes_outside(tmp_path):
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    parent = tmp_path / 'vault/archives'
    parent.mkdir(parents=True)
    (parent / SLUG).symlink_to(outside, target_is_directory=True)
    value = request(tmp_path, slug='unoccupied')
    value['identity']['slug'] = SLUG
    assert cli.collect(tmp_path, value)['status'] in ('failed', 'blocked')
    assert list(outside.iterdir()) == []


def test_postpublication_error_stops_without_replaying(tmp_path, downloaded, monkeypatch):
    real = cli._replace_text
    def fail_manifest(fd, name, text):
        if name == 'manifest.yaml':
            raise OSError('disk failure')
        return real(fd, name, text)
    monkeypatch.setattr(cli, '_replace_text', fail_manifest)
    result = cli.collect(tmp_path, request(tmp_path, files=[asset()]))
    assert result['code'] == 'archive.outcome_unknown'
    original = tmp_path / 'vault/archives' / SLUG / 'originals/001-screen-discoloration.jpg'
    assert original.read_bytes() == b'actual-original-bytes'


def test_manifest_duplicate_keys_and_paths_rejected(tmp_path):
    cli.collect(tmp_path, request(tmp_path))
    path = tmp_path / 'vault/archives' / SLUG / 'manifest.yaml'
    path.write_text(path.read_text() + '\nfiles: []\n')
    assert not observe_collection(tmp_path, path.parent)['usable']


def test_http_inspection_and_download(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            image = self.path == '/image.jpg'
            data = b'\xff\xd8\xfffixture' if image else b'<html><title>Repair post</title><img src="/image.jpg" alt="Screen detail"></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg' if image else 'text/html')
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        report = cli.inspect(base)
        assert report['title'] == 'Repair post'
        assert report['candidates'][0]['url'] == base + '/image.jpg'
        mime, final = cli._download(base + '/image.jpg', tmp_path / 'screen.jpg')
        assert mime == 'image/jpeg'
        with pytest.raises(ValueError, match='HTML'):
            cli._download(base, tmp_path / 'wrong.jpg')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_webarchive_collection_reuses_capture_without_webpage_object(tmp_path, monkeypatch):
    import plistlib
    from scripts.webpage import webpage
    monkeypatch.setattr(webpage, 'inspect', lambda url: {'status': 'complete', 'final_url': url})
    calls = []
    def capture(url, expected, output):
        calls.append(output)
        output.write_bytes(plistlib.dumps({'WebMainResource': {'WebResourceURL': url,
            'WebResourceMIMEType': 'text/html', 'WebResourceTextEncodingName': 'UTF-8',
            'WebResourceData': b'<html><title>Repair</title><body>Saved source evidence</body></html>'}}))
        return {'status': 'complete'}
    monkeypatch.setattr(webpage, 'capture', capture)
    item = {'name': 'repair-discussion.webarchive', 'url': URL, 'method': 'webarchive'}
    result = cli.collect(tmp_path, request(tmp_path, files=[item]))
    assert result['status'] == 'complete', result
    assert len(calls) == 1 and '.quasi/temp/' in str(calls[0])
    original = tmp_path / 'vault/archives' / SLUG / 'originals/repair-discussion.webarchive'
    assert original.is_file() and not (tmp_path / 'vault/webpages').exists()
    manifest = load_manifest(original.parent.parent / 'manifest.yaml')
    assert manifest.files[0].media_type == 'application/x-webarchive'


def test_webarchive_read_is_readonly(tmp_path, monkeypatch, capsys):
    import plistlib
    import sys
    path = tmp_path / 'saved.webarchive'
    path.write_bytes(plistlib.dumps({'WebMainResource': {'WebResourceURL': URL,
        'WebResourceMIMEType': 'text/html', 'WebResourceTextEncodingName': 'UTF-8',
        'WebResourceData': b'<html><title>Repair</title><script>untrusted()</script><body>Verified text</body></html>'}}))
    before = path.read_bytes()
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['quasi-archive', 'read', '--path', 'saved.webarchive'])
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert 'Verified text' in result['text'] and 'untrusted()' not in result['text']
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_unlisted_original_marks_interrupted_publication_unusable(tmp_path, downloaded):
    cli.collect(tmp_path, request(tmp_path, files=[asset()]))
    directory = tmp_path / 'vault/archives' / SLUG
    (directory / 'originals/unlisted.jpg').write_bytes(b'partial publication')
    assert not archive_status(tmp_path, SLUG)['facts']['collection']['usable']
    assert cli.collect(tmp_path, request(tmp_path))['code'] == 'archive.conflict'


def test_user_edit_during_acquisition_is_not_overwritten(tmp_path, downloaded, monkeypatch):
    cli.collect(tmp_path, request(tmp_path))
    page = tmp_path / 'vault/archives' / SLUG / 'archive.md'
    def modifying_download(url, output):
        page.write_text(page.read_text() + '\nConcurrent user edit\n')
        return downloaded(url, output)
    monkeypatch.setattr(cli, '_download', modifying_download)
    result = cli.collect(tmp_path, request(tmp_path, files=[asset()]))
    assert result['code'] == 'archive.conflict'
    assert 'Concurrent user edit' in page.read_text()
    assert not (page.parent / 'originals').exists()


def test_distinct_archives_can_collect_concurrently(tmp_path):
    with cli._lock(tmp_path, {'slug': SLUG, 'url': URL}):
        with cli._lock(tmp_path, {'slug': 'different', 'url': 'https://example.org/different'}):
            pass
        with pytest.raises(cli.Conflict):
            with cli._lock(tmp_path, {'slug': 'different', 'url': URL}):
                pass
        with pytest.raises(cli.Conflict):
            with cli._lock(tmp_path, {'slug': SLUG, 'url': 'https://example.org/different'}):
                pass


def test_collect_cli_request_uses_project_root_and_reports_json(tmp_path, monkeypatch, capsys):
    import sys
    folder = tmp_path / '.quasi/temp'
    folder.mkdir(parents=True)
    path = folder / 'unique-request.json'
    path.write_text(json.dumps(request(tmp_path)))
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['quasi-archive', 'collect', '--request-file', '.quasi/temp/unique-request.json'])
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['path'] == f'vault/archives/{SLUG}/archive.md'
    assert report['revision'] == archive_status(tmp_path, SLUG)['facts']['collection']['revision']
