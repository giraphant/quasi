"""Archive identity evidence comes from PDF pages, including large scans."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import random
import subprocess
import sys
import threading

import fitz
import pytest

from scripts.archive import archive as cli
from test_archive_plan import COMPLETE, IDENTITY, URL
from workflow_test_support import run_generated_workflow
from test_workflow_dispatch import _prompt_request

ROOT = Path(__file__).resolve().parents[1]
TITLE = "Bill Daniels' Illustrated Trade References: 85/86 Video Equipment Buyers Guide"


def pdf_bytes(*, large=False, scanned=False, encrypted=False):
    with fitz.open() as document:
        for number in range(8):
            page = document.new_page()
            if number == 4:
                if scanned:
                    with fitz.open() as image_document:
                        image_page = image_document.new_page()
                        image_page.insert_textbox(fitz.Rect(40, 100, 550, 500), TITLE, fontsize=24)
                        page.insert_image(page.rect, stream=image_page.get_pixmap().tobytes('png'))
                else:
                    page.insert_textbox(fitz.Rect(40, 100, 550, 500), TITLE, fontsize=24)
        document.set_metadata({'title': 'Unverified scanner label', 'creationDate': 'D:20210901120000'})
        if large:
            document.embfile_add('padding.bin', random.Random(7).randbytes(11 * 1024 * 1024))
        options = {'encryption': fitz.PDF_ENCRYPT_AES_256, 'owner_pw': 'owner', 'user_pw': 'reader'} if encrypted else {}
        return document.tobytes(**options)


def mock_response(monkeypatch, content, *, media='application/pdf', length=None):
    class Response:
        url = URL + '/opaque.pdf'
        headers = {'Content-Type': media, **({'Content-Length': str(length)} if length is not None else {})}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size):
            for start in range(0, len(content), size):
                yield content[start:start + size]
    monkeypatch.setattr(cli, 'response', lambda _: Response())


def test_large_http_pdf_reaches_title_page_after_full_download(tmp_path):
    content = pdf_bytes(large=True)
    assert len(content) > 10 * 1024 * 1024
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/opaque.pdf'
        result = cli.inspect(url, root=tmp_path)
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert requests == ['/opaque.pdf']
    assert result['url'] == result['final_url'] == url
    assert result['title'] == 'opaque.pdf'  # No automatic bibliographic judgement.
    pdf = result['pdf']
    assert pdf['size'] == len(content) and pdf['sha256'] == sha256(content).hexdigest()
    assert pdf['page_count'] == 8
    assert pdf['metadata']['title'] == 'Unverified scanner label'
    assert 'creationDate' in pdf['metadata']
    assert 'publication_date' not in pdf
    assert TITLE in ' '.join(pdf['pages'][4]['text'].split())
    assert pdf['pages'][4]['page'] == 5
    assert pdf['cached_pdf'] is None and pdf['source_path'] is None
    assert not list(tmp_path.iterdir())


def test_scanned_pdf_returns_exact_previews_and_reusable_local_copy(tmp_path, monkeypatch):
    content = pdf_bytes(scanned=True)
    mock_response(monkeypatch, content)
    report = cli.inspect(URL, output_dir=Path('.quasi/temp/first'), root=tmp_path)
    evidence = report['pdf']
    assert all(page['text'] == '' for page in evidence['pages'])
    cached = tmp_path / evidence['cached_pdf']
    assert cached.read_bytes() == content
    preview = tmp_path / evidence['pages'][4]['preview_path']
    assert preview.is_file()
    image = fitz.Pixmap(str(preview))
    assert 0 < max(image.width, image.height) <= 1600
    def no_download(*args): pytest.fail('local evidence must not redownload')
    monkeypatch.setattr(cli, 'response', no_download)
    result = cli.inspect_pdf(Path(evidence['cached_pdf']), pages='5', root=tmp_path,
                             output_dir=Path('.quasi/temp/title'))
    assert result['url'] is result['final_url'] is None
    assert result['pdf']['source_path'] == evidence['cached_pdf']
    assert result['pdf']['sha256'] == evidence['sha256']
    assert result['pdf']['partial'] and result['truncated']
    assert [p['page'] for p in result['pdf']['pages']] == [5]
    assert (tmp_path / result['pdf']['pages'][0]['preview_path']).read_bytes() == preview.read_bytes()
    assert cached.read_bytes() == content


@pytest.mark.parametrize('media', ['application/octet-stream', 'text/html'])
def test_pdf_magic_takes_precedence_over_mime(tmp_path, monkeypatch, media):
    mock_response(monkeypatch, pdf_bytes(), media=media)
    assert cli.inspect(URL, root=tmp_path)['pdf']['page_count'] == 8


def test_html_error_page_is_not_pdf_identity(tmp_path, monkeypatch):
    mock_response(monkeypatch, b'<html><title>Access denied</title></html>')
    result = cli.inspect(URL, output_dir=Path('.quasi/temp/error'), root=tmp_path)
    assert 'pdf' not in result and result['media_type'] == 'text/html'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('selection', ['0', '9', '5-3', '1-17', '1,', '../5', '-1', '1-999999999999'])
def test_invalid_page_selection_has_no_retained_output(tmp_path, selection):
    path = tmp_path / 'source.pdf'
    path.write_bytes(pdf_bytes())
    with pytest.raises(ValueError):
        cli.inspect_pdf(path, pages=selection, output_dir=Path('.quasi/temp/invalid'), root=tmp_path)
    assert not (tmp_path / '.quasi/temp/invalid').exists()


def test_pdf_inspection_budgets_and_incomplete_transfer(tmp_path, monkeypatch):
    content = pdf_bytes()
    mock_response(monkeypatch, content, length=len(content) + 1)
    with pytest.raises(ValueError, match='incomplete'):
        cli.inspect(URL, root=tmp_path)
    monkeypatch.setattr(cli, 'MAX_BYTES', len(content) - 1)
    with pytest.raises(ValueError, match='limit'):
        cli.inspect(URL, root=tmp_path)
    mock_response(monkeypatch, content)
    with pytest.raises(ValueError, match='limit'):
        cli.inspect(URL, root=tmp_path)
    monkeypatch.setattr(cli, 'MAX_BYTES', len(content) + 1)
    ticks = iter([0, 301])
    monkeypatch.setattr(cli.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='five minutes'):
        cli.inspect(URL, root=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('content', [b'%PDF-not-a-document', pdf_bytes(encrypted=True)])
def test_unreadable_pdf_has_failed_cli_receipt(tmp_path, content):
    path = tmp_path / 'source.pdf'; path.write_bytes(content)
    result = subprocess.run([sys.executable, '-m', 'scripts.archive.archive', 'inspect', '--path', str(path)],
                            env={**os.environ, 'PYTHONPATH': str(ROOT), 'CLAUDE_PROJECT_DIR': str(tmp_path)},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert json.loads(result.stdout)['status'] == 'failed'
    assert 'Traceback' not in result.stderr
    assert path.read_bytes() == content


def test_inspection_output_is_explicit_scratch_and_never_clobbered(tmp_path):
    path = tmp_path / 'source.pdf'; path.write_bytes(pdf_bytes())
    output = tmp_path / '.quasi/temp/existing'; output.mkdir(parents=True)
    sentinel = output / 'source.pdf'; sentinel.write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        cli.inspect_pdf(path, output_dir=output, root=tmp_path)
    assert sentinel.read_bytes() == b'preserve'
    with pytest.raises(ValueError, match='.quasi/temp'):
        cli.inspect_pdf(path, output_dir=Path('vault/archives/forbidden'), root=tmp_path)
    assert not (tmp_path / 'vault').exists()
    (tmp_path / '.quasi/temp/symlink').symlink_to(output, target_is_directory=True)
    with pytest.raises(OSError):
        cli.inspect_pdf(path, output_dir=Path('.quasi/temp/symlink/new'), root=tmp_path)
    assert not (output / 'new').exists()


def test_preview_failure_cleans_only_new_evidence_directory(tmp_path, monkeypatch):
    path = tmp_path / 'source.pdf'; content = pdf_bytes(); path.write_bytes(content)
    def failed(*args, **kwargs): raise RuntimeError('render failed')
    monkeypatch.setattr(fitz.Page, 'get_pixmap', failed)
    with pytest.raises(ValueError, match='page 1'):
        cli.inspect_pdf(path, output_dir=Path('.quasi/temp/failed'), root=tmp_path)
    assert not (tmp_path / '.quasi/temp/failed').exists()
    assert path.read_bytes() == content


def test_generated_identify_exposes_pdf_evidence_without_changing_seed_or_receipt():
    report = run_generated_workflow('archive', {'seed': {'state': 'provisional', 'url': URL},
        'observation': None, 'options': {'topics': []}}, [{**COMPLETE, 'identity': IDENTITY}], capture_agent_requests=True)
    assert report['agentCalls'] == 1
    assert report['value']['terminal'] == 'needs_observation'
    envelope = _prompt_request(report['agentRequests'][0]['prompt'])
    assert envelope['source_url'] == URL and envelope['effect'] == 'readonly'
    capabilities = envelope['capabilities']
    assert any('inspect --url source_url' in cap and '--output-dir .quasi/temp/' in cap for cap in capabilities)
    assert any('inspect --path EXACT_RETURNED_CACHED_PDF' in cap for cap in capabilities)
    assert any(cap.startswith('Read exact PDF preview paths') for cap in capabilities)
