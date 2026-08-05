#!/usr/bin/env python3
"""
PDF Chapter Splitter

Two modes:
1. Auto mode (default): tries TOC → pattern → full document fallback
2. Manual mode (--chapters JSON): coordinator specifies exact page ranges

Usage:
    # Auto mode
    python split_chapters.py input.pdf -o ./chapters/

    # Manual mode — coordinator reads PDF TOC page and specifies chapters
    python split_chapters.py input.pdf -o ./chapters/ --chapters '[
      {"title": "Introduction", "start": 1, "end": 15},
      {"title": "Chapter 1 - Networks", "start": 16, "end": 45}
    ]'

    # Manual mode from file
    python split_chapters.py input.pdf -o ./chapters/ --chapters-file chapters.json

    # Extract single page range (utility)
    python split_chapters.py input.pdf -o ./chapters/ --pages 10-25 --title "Chapter 1"
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import re
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chapter_commit import (
    ChapterFailure,
    commit_chapter_set,
    emit_receipt,
    failure_receipt,
    verify_expected_manifest,
)
from toc_utils import (
    CHAPTER_REF_CONTRACT,
    assign_slots,
    is_skip,
    make_filename,
    make_slug,
)

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    fitz = None
    _FITZ_IMPORT_ERROR = exc
else:
    _FITZ_IMPORT_ERROR = None


DEFAULT_PATTERNS = [
    r'^Chapter\s+\d+',
    r'^CHAPTER\s+\d+',
    r'^第[一二三四五六七八九十百零\d]+章',
    r'^第[一二三四五六七八九十百零\d]+节',
    r'^Part\s+\d+',
    r'^PART\s+\d+',
    r'^[IVX]+\.\s+',
    r'^[一二三四五六七八九十]+、',
]


def extract_text_from_pdf(pdf_path: str) -> list[tuple[int, str]]:
    """Extract text from PDF, returning list of (page_num, text) tuples."""
    doc = fitz.open(pdf_path)
    pages = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        pages.append((page_num, text))
    doc.close()
    return pages


def extract_pages_text(pdf_path: str, start_page: int, end_page: int) -> str:
    """Extract text from a range of pages (1-indexed, inclusive)."""
    doc = fitz.open(pdf_path)
    parts = []
    for i in range(start_page - 1, min(end_page, len(doc))):
        parts.append(doc[i].get_text())
    doc.close()
    return '\n'.join(parts)


def split_by_manual(pdf_path: str, chapter_specs: list[dict]) -> list[dict]:
    """
    Split PDF using manually specified chapter boundaries.
    Each spec: {"title": "...", "start": page_num, "end": page_num}
    Pages are 1-indexed, inclusive.
    """
    chapters = []
    for spec in chapter_specs:
        title = spec['title']
        start = spec['start']
        end = spec['end']
        text = extract_pages_text(pdf_path, start, end)
        chapters.append({
            'title': title,
            'start_page': start,
            'end_page': end,
            'content': text.split('\n'),
        })
    return chapters


def split_by_toc(pdf_path: str, max_level: int = 1) -> list[dict]:
    """Split PDF using embedded TOC bookmarks."""
    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)
    total_pages = len(doc)
    doc.close()

    if not toc:
        return []

    entries = [(title.strip(), page) for level, title, page in toc if level <= max_level and page > 0]
    if not entries:
        return []

    print(f"TOC has {len(toc)} entries, {len(entries)} at level <= {max_level}")

    chapters = []
    for i, (title, start_page) in enumerate(entries):
        end_page = entries[i + 1][1] - 1 if i + 1 < len(entries) else total_pages
        text = extract_pages_text(pdf_path, start_page, end_page)
        chapters.append({
            'title': title,
            'start_page': start_page,
            'end_page': end_page,
            'content': text.split('\n'),
        })
    return chapters


def find_chapter_boundaries(pages: list[tuple[int, str]], patterns: list[str]) -> list[dict]:
    """Find chapter boundaries using regex patterns."""
    combined_pattern = '|'.join(f'({p})' for p in patterns)
    regex = re.compile(combined_pattern, re.MULTILINE)

    chapters = []
    current_chapter = {
        'title': 'Frontmatter',
        'start_page': 1,
        'end_page': 1,
        'content': [],
    }

    for page_num, text in pages:
        for line in text.split('\n'):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if regex.match(line_stripped):
                if current_chapter['content']:
                    chapters.append(current_chapter)
                current_chapter = {
                    'title': line_stripped,
                    'start_page': page_num,
                    'end_page': page_num,
                    'content': [],
                }
            else:
                current_chapter['content'].append(line)
                current_chapter['end_page'] = page_num

    if current_chapter['content']:
        chapters.append(current_chapter)
    return chapters


def filter_and_assign(chapters: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Apply SKIP filter and slot assignment. Returns (kept, skipped).
    Each kept chapter gains a 'slot' key.
    """
    kept = []
    skipped = []
    for ch in chapters:
        if is_skip(ch['title']):
            skipped.append({'title': ch['title'], 'reason': 'non_content'})
        else:
            kept.append(ch)
    assign_slots(kept)
    return kept, skipped


def save_chapters(chapters: list[dict], output_dir: Path) -> list[Path]:
    """Save each chapter to a separate file. Chapters must already have 'slot'."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created_files = []

    for ch in chapters:
        filename = make_filename(ch['slot'], ch['title'])
        filepath = output_dir / filename

        content = f"# {ch['title']}\n\n"
        content += f"[Starting page: {ch['start_page']}]\n\n"
        content += '\n'.join(ch['content'])

        filepath.write_text(content, encoding='utf-8')
        created_files.append(filepath)
        print(f"Created: {filepath}")

    return created_files


def create_manifest(chapters: list[dict], skipped: list[dict],
                    output_dir: Path, pdf_name: str, method: str,
                    include_end: bool = False):
    """Create a manifest file listing all chapters."""
    manifest_path = output_dir / "manifest.json"
    manifest = {
        'source_pdf': pdf_name,
        'split_method': method,
        'total_chapters': len(chapters),
        'extracted_count': len(chapters),
        'chapters': [
            {
                'slot': ch['slot'],
                'title': ch['title'],
                'start_page': ch['start_page'],
                **(
                    {'end_page': ch['end_page']}
                    if include_end and ch.get('end_page') is not None else {}
                ),
                'filename': make_filename(ch['slot'], ch['title']),
                'slug': make_slug(ch['slot'], ch['title']),
                'word_count': len('\n'.join(ch['content']).split()),
            }
            for ch in chapters
        ],
        'skipped': skipped,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Created manifest: {manifest_path}")
    return manifest


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _make_parser(json_mode: bool = False) -> argparse.ArgumentParser:
    parser_class = _JsonArgumentParser if json_mode else argparse.ArgumentParser
    parser = parser_class(description='Split PDF into chapter files')
    parser.add_argument('pdf_path', help='Path to the PDF file')
    parser.add_argument('--output-dir', '-o', default='./chapters',
                        help='Output directory for chapter files')

    # Manual mode
    parser.add_argument('--chapters', type=str,
                        help='JSON array of chapter specs: [{"title":"...","start":N,"end":N}, ...]')
    parser.add_argument('--chapters-file', type=str,
                        help='Path to JSON file with chapter specs')

    # Single range utility
    parser.add_argument('--pages', type=str,
                        help='Extract single page range, e.g. "10-25"')
    parser.add_argument('--title', type=str, default='extract',
                        help='Title for --pages mode output')
    parser.add_argument('--slot', type=str,
                        help='Exact manifest slot to repair with --pages')

    # Auto mode options
    parser.add_argument('--method', choices=['auto', 'toc', 'pattern'], default='auto',
                        help='Auto split method: auto (TOC→pattern), toc, or pattern')
    parser.add_argument('--toc-level', type=int, default=1,
                        help='Max TOC depth (default: 1)')
    parser.add_argument('--patterns', '-p',
                        help='Comma-separated chapter heading patterns (regex)')
    parser.add_argument('--min-chapter-length', type=int, default=100,
                        help='Min characters per chapter (default: 100)')
    parser.add_argument('--max-chapters', type=int, default=50,
                        help='Max chapters before flagging over-split (default: 50)')
    parser.add_argument(
        '--expected-manifest-fingerprint',
        help='Require the current manifest to match this SHA-256 before writing',
    )
    parser.add_argument('--json', action='store_true',
                        help='Emit one structured receipt on stdout')
    return parser


def _legacy_run(args) -> int:
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        return 1

    output_dir = Path(args.output_dir)
    try:
        page_count = _page_count(pdf_path)
        if args.chapters or args.chapters_file:
            specs = _load_manual_specs(args, page_count)
            render_mode = 'manual'
            commit_mode = 'manual'
            options = {
                'chapters': specs,
                'min_chapter_length': args.min_chapter_length,
            }
            builder = _json_full_build(args, pdf_path, commit_mode, specs)
            print(f"Manual mode: {len(specs)} chapters specified")
        elif args.pages:
            start, end = _validate_range(args.pages, page_count)
            render_mode = 'pages'
            commit_mode = 'manual'
            options = {
                'pages': [start, end],
                'title': args.title,
                'legacy_single_range': True,
            }
            builder = _legacy_pages_build(args, pdf_path, start, end)
        else:
            render_mode = 'auto'
            commit_mode = (
                args.method if args.method in {'toc', 'pattern'} else 'pattern'
            )
            options = {
                'method': args.method,
                'toc_level': args.toc_level,
                'patterns': args.patterns,
                'min_chapter_length': args.min_chapter_length,
            }
            builder = _legacy_auto_build(args, pdf_path)
            if args.method in {'auto', 'toc'}:
                print(
                    f"Trying TOC-based splitting (level <= {args.toc_level})..."
                )
            if args.method == 'pattern':
                print("Using pattern-based splitting...")

        options['chapter_ref_contract'] = CHAPTER_REF_CONTRACT

        # The legacy surface is only a prose renderer.  Its chapter writes use
        # the exact same lock, staging, validation, and manifest-last commit as
        # JSON mode; suppress builder paths because they name private staging.
        with redirect_stdout(io.StringIO()):
            exit_code, receipt = commit_chapter_set(
                input_path=pdf_path,
                output_dir=output_dir,
                mode=commit_mode,
                options=options,
                max_chapters=args.max_chapters,
                build_stage=builder,
            )
    except ChapterFailure as error:
        print(f"Error: {error.message}")
        return error.exit_code

    if exit_code != 0:
        failure = receipt.get('failure') or {}
        print(f"Error: {failure.get('message', 'chapter extraction failed')}")
        return exit_code

    chapters = receipt['chapters']
    if render_mode == 'manual':
        print(f"Extracted {len(chapters)} chapters")
        for row in chapters:
            print(f"Created: {output_dir / row['filename']}")
        print(f"Created manifest: {output_dir / 'manifest.json'}")
        print("\nDone!")
    elif render_mode == 'pages':
        row = chapters[0]
        print(
            f"Extracted pages {row['start_page']}-{row['end_page']} "
            f"→ {output_dir / row['filename']}"
        )
    else:
        manifest = json.loads(
            (output_dir / 'manifest.json').read_text(encoding='utf-8')
        )
        method_used = manifest.get('split_method', commit_mode)
        if args.method == 'auto' and method_used == 'pattern':
            print("No TOC found in PDF")
            print("Using pattern-based splitting...")
        print(f"\nFinal: {len(chapters)} chapters via {method_used}")
        for row in chapters:
            print(f"Created: {output_dir / row['filename']}")
        print(f"Created manifest: {output_dir / 'manifest.json'}")
        print("\nDone! Chapter files are ready for processing.")
    return 0


def _legacy_pages_build(
    args,
    pdf_path: Path,
    start: int,
    end: int,
):
    """Build the historical single-range filename inside a full transaction."""

    def build(stage_dir: Path, _previous_manifest: dict | None) -> dict:
        text = extract_pages_text(str(pdf_path), start, end)
        safe_title = re.sub(r'[^\w\s-]', '', args.title)[:50].replace(' ', '_')
        filename = f"{safe_title}.txt"
        (stage_dir / filename).write_text(
            f"# {args.title}\n\n[Pages {start}-{end}]\n\n{text}",
            encoding='utf-8',
        )
        return {
            'source_pdf': pdf_path.name,
            'split_method': 'manual',
            'total_chapters': 1,
            'extracted_count': 1,
            'chapters': [{
                'slot': '01',
                'title': args.title,
                'start_page': start,
                'end_page': end,
                'filename': filename,
                'slug': make_slug('01', args.title),
                'word_count': len(text.split()),
            }],
            'skipped': [],
        }

    return build


def _legacy_auto_build(args, pdf_path: Path):
    """Preserve legacy auto routing while staging its complete result."""

    def build(stage_dir: Path, _previous_manifest: dict | None) -> dict:
        chapters: list[dict] = []
        method_used = args.method

        if args.method in {'auto', 'toc'}:
            chapters = split_by_toc(
                str(pdf_path), max_level=args.toc_level
            )
            if chapters:
                chapters = [
                    chapter for chapter in chapters
                    if len('\n'.join(chapter['content']))
                    >= args.min_chapter_length
                ]
                method_used = 'toc'
                if (
                    len(chapters) > args.max_chapters
                    and args.toc_level > 1
                ):
                    chapters = split_by_toc(str(pdf_path), max_level=1)
                    chapters = [
                        chapter for chapter in chapters
                        if len('\n'.join(chapter['content']))
                        >= args.min_chapter_length
                    ]
            if not chapters and args.method == 'toc':
                raise ChapterFailure(
                    'no_toc',
                    '--method toc but no TOC in PDF',
                )

        if not chapters and args.method in {'auto', 'pattern'}:
            patterns = (
                [pattern.strip() for pattern in args.patterns.split(',')]
                if args.patterns else DEFAULT_PATTERNS
            )
            try:
                re.compile('|'.join(f'({pattern})' for pattern in patterns))
            except re.error as exc:
                raise ChapterFailure(
                    'invalid_pattern',
                    f'invalid chapter pattern: {exc}',
                    exit_code=2,
                ) from exc
            pages = extract_text_from_pdf(str(pdf_path))
            chapters = find_chapter_boundaries(pages, patterns)
            chapters = [
                chapter for chapter in chapters
                if len('\n'.join(chapter['content']))
                >= args.min_chapter_length
            ]
            method_used = 'pattern'
            if len(chapters) > args.max_chapters:
                toc_chapters = split_by_toc(str(pdf_path), max_level=1)
                toc_chapters = [
                    chapter for chapter in toc_chapters
                    if len('\n'.join(chapter['content']))
                    >= args.min_chapter_length
                ]
                if toc_chapters and len(toc_chapters) <= args.max_chapters:
                    chapters = toc_chapters
                    method_used = 'toc'

        if not chapters:
            raise ChapterFailure(
                'no_chapters',
                'no chapters found via any method',
            )

        chapters, skipped = filter_and_assign(chapters)
        save_chapters(chapters, stage_dir)
        return create_manifest(
            chapters,
            skipped,
            stage_dir,
            pdf_path.name,
            method_used,
            include_end=True,
        )

    return build


def _page_count(pdf_path: Path) -> int:
    if fitz is None:
        raise ChapterFailure(
            'dependency_missing',
            f'PyMuPDF is not installed: {_FITZ_IMPORT_ERROR}',
            exit_code=1,
        )
    try:
        with fitz.open(pdf_path) as doc:
            return len(doc)
    except Exception as exc:
        raise ChapterFailure(
            'invalid_pdf',
            f'cannot open PDF: {exc}',
            exit_code=2,
        ) from exc


def _validate_range(value: object, page_count: int) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ChapterFailure(
            'invalid_range',
            'page range must use START-END',
            exit_code=2,
        )
    match = re.fullmatch(r'([1-9]\d*)-([1-9]\d*)', value)
    if not match:
        raise ChapterFailure(
            'invalid_range',
            f'invalid page range: {value!r}',
            exit_code=2,
        )
    start, end = int(match.group(1)), int(match.group(2))
    if start > end or end > page_count:
        raise ChapterFailure(
            'invalid_range',
            f'page range {start}-{end} is outside 1-{page_count}',
            exit_code=2,
        )
    return start, end


def _load_manual_specs(args, page_count: int) -> list[dict]:
    if bool(args.chapters) == bool(args.chapters_file):
        raise ChapterFailure(
            'invalid_arguments',
            'provide exactly one of --chapters or --chapters-file',
            exit_code=2,
        )
    try:
        raw = (
            json.loads(args.chapters)
            if args.chapters
            else json.loads(Path(args.chapters_file).read_text(encoding='utf-8'))
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChapterFailure(
            'invalid_chapters_json',
            f'cannot read chapter specification JSON: {exc}',
            exit_code=2,
        ) from exc
    if not isinstance(raw, list) or not raw:
        raise ChapterFailure(
            'invalid_chapters',
            'chapter specifications must be a non-empty JSON array',
            exit_code=2,
        )
    specs: list[dict] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ChapterFailure(
                'invalid_chapters',
                f'chapter specification {index} must be an object',
                exit_code=2,
            )
        title = row.get('title')
        start = row.get('start')
        end = row.get('end')
        if (
            not isinstance(title, str)
            or not title.strip()
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            raise ChapterFailure(
                'invalid_chapters',
                f'chapter specification {index} requires title/start/end',
                exit_code=2,
            )
        _validate_range(f'{start}-{end}', page_count)
        specs.append({'title': title, 'start': start, 'end': end})
    return specs


def _filtered(chapters: list[dict], min_length: int) -> tuple[list[dict], list[dict]]:
    chapters = [
        chapter
        for chapter in chapters
        if len('\n'.join(chapter['content'])) >= min_length
    ]
    return filter_and_assign(chapters)


def _json_full_build(args, pdf_path: Path, mode: str, specs: list[dict] | None):
    def build(stage_dir: Path, _previous_manifest: dict | None) -> dict:
        if mode == 'manual':
            chapters = split_by_manual(str(pdf_path), specs or [])
        elif mode == 'toc':
            chapters = split_by_toc(str(pdf_path), max_level=args.toc_level)
            if not chapters:
                raise ChapterFailure(
                    'no_toc',
                    'PDF has no usable TOC entries at the requested level',
                )
        else:
            patterns = (
                [pattern.strip() for pattern in args.patterns.split(',')]
                if args.patterns else DEFAULT_PATTERNS
            )
            try:
                # Compile before reading the whole PDF so malformed caller input
                # is a classified argument failure.
                re.compile('|'.join(f'({pattern})' for pattern in patterns))
            except re.error as exc:
                raise ChapterFailure(
                    'invalid_pattern',
                    f'invalid chapter pattern: {exc}',
                    exit_code=2,
                ) from exc
            chapters = find_chapter_boundaries(
                extract_text_from_pdf(str(pdf_path)), patterns
            )
        chapters, skipped = _filtered(chapters, args.min_chapter_length)
        if not chapters:
            raise ChapterFailure(
                'no_chapters',
                f'{mode} extraction produced no chapters',
            )
        save_chapters(chapters, stage_dir)
        return create_manifest(
            chapters, skipped, stage_dir, pdf_path.name, mode,
            include_end=True,
        )

    return build


def _json_repair_build(
    args,
    pdf_path: Path,
    start: int,
    end: int,
):
    def build(stage_dir: Path, previous_manifest: dict | None) -> dict:
        assert previous_manifest is not None
        rows = previous_manifest.get('chapters', [])
        matches = [row for row in rows if row.get('slot') == args.slot]
        if len(matches) != 1:
            code = 'slot_not_found' if not matches else 'slot_duplicated'
            raise ChapterFailure(
                code,
                f'manifest must contain exactly one slot {args.slot!r}',
                exit_code=2,
            )

        manifest = copy.deepcopy(previous_manifest)
        for row in manifest['chapters']:
            source = Path(args.output_dir) / row['filename']
            shutil.copy2(source, stage_dir / row['filename'])

        target = next(row for row in manifest['chapters'] if row.get('slot') == args.slot)
        old_filename = target['filename']
        new_filename = make_filename(args.slot, args.title)
        if any(
            row is not target and row.get('filename') == new_filename
            for row in manifest['chapters']
        ):
            raise ChapterFailure(
                'filename_conflict',
                f'repair filename collides with another chapter: {new_filename}',
                exit_code=2,
            )
        text = extract_pages_text(str(pdf_path), start, end)
        (stage_dir / new_filename).write_text(
            f"# {args.title}\n\n[Pages {start}-{end}]\n\n{text}",
            encoding='utf-8',
        )
        if new_filename != old_filename:
            (stage_dir / old_filename).unlink()
        target.update({
            'title': args.title,
            'start_page': start,
            'end_page': end,
            'filename': new_filename,
            'slug': make_slug(args.slot, args.title),
            'word_count': len(text.split()),
        })
        target.pop('sha256', None)
        (stage_dir / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return manifest

    return build


def _argv_value(argv: list[str], *names: str, default: str = '') -> str:
    for index, item in enumerate(argv):
        for name in names:
            if item == name and index + 1 < len(argv):
                return argv[index + 1]
            if item.startswith(name + '='):
                return item.split('=', 1)[1]
    return default


def _json_error_from_argv(argv: list[str], message: str) -> int:
    input_path = Path(argv[0]) if argv and not argv[0].startswith('-') else Path('')
    output_dir = Path(_argv_value(argv, '--output-dir', '-o', default='./chapters'))
    max_value = _argv_value(argv, '--max-chapters', default='50')
    try:
        max_chapters = int(max_value)
    except ValueError:
        max_chapters = 50
    mode = (
        'repair' if '--pages' in argv
        else 'manual' if '--chapters' in argv or '--chapters-file' in argv
        else _argv_value(argv, '--method', default='pattern')
    )
    error = ChapterFailure(
        'invalid_arguments',
        message,
        exit_code=2,
    )
    emit_receipt(failure_receipt(
        input_path=input_path,
        output_dir=output_dir,
        mode=mode if mode in {'toc', 'pattern', 'manual', 'repair'} else 'pattern',
        max_chapters=max_chapters,
        error=error,
    ))
    return error.exit_code


def _json_run(args, argv: list[str]) -> int:
    pdf_path = Path(args.pdf_path)
    output_dir = Path(args.output_dir)
    if args.max_chapters < 1:
        error = ChapterFailure(
            'invalid_arguments',
            '--max-chapters must be at least 1',
            exit_code=2,
        )
        emit_receipt(failure_receipt(
            input_path=pdf_path,
            output_dir=output_dir,
            mode='repair' if args.pages else 'manual' if args.chapters or args.chapters_file else args.method,
            max_chapters=args.max_chapters,
            error=error,
        ))
        return error.exit_code

    try:
        verify_expected_manifest(
            output_dir, args.expected_manifest_fingerprint
        )
        page_count = _page_count(pdf_path)
        manual = bool(args.chapters or args.chapters_file)
        repair = bool(args.pages)
        if manual and repair:
            raise ChapterFailure(
                'invalid_arguments',
                '--pages cannot be combined with manual chapter specifications',
                exit_code=2,
            )
        if repair:
            title_explicit = any(
                item == '--title' or item.startswith('--title=') for item in argv
            )
            if not title_explicit or not args.title.strip() or not args.slot:
                raise ChapterFailure(
                    'invalid_arguments',
                    'repair requires --pages, --title, and --slot',
                    exit_code=2,
                )
            start, end = _validate_range(args.pages, page_count)
            mode = 'repair'
            options = {
                'pages': [start, end],
                'title': args.title,
                'slot': args.slot,
            }
            builder = _json_repair_build(args, pdf_path, start, end)
            require_previous = True
            disposition = 'repaired'
        elif manual:
            specs = _load_manual_specs(args, page_count)
            mode = 'manual'
            options = {
                'chapters': specs,
                'min_chapter_length': args.min_chapter_length,
            }
            builder = _json_full_build(args, pdf_path, mode, specs)
            require_previous = False
            disposition = None
        else:
            if args.method not in {'toc', 'pattern'}:
                raise ChapterFailure(
                    'invalid_arguments',
                    '--json requires an exact --method toc or --method pattern',
                    exit_code=2,
                )
            mode = args.method
            options = {
                'method': mode,
                'toc_level': args.toc_level,
                'patterns': args.patterns,
                'min_chapter_length': args.min_chapter_length,
            }
            builder = _json_full_build(args, pdf_path, mode, None)
            require_previous = False
            disposition = None

        options['chapter_ref_contract'] = CHAPTER_REF_CONTRACT

        with redirect_stdout(sys.stderr):
            exit_code, receipt = commit_chapter_set(
                input_path=pdf_path,
                output_dir=output_dir,
                mode=mode,
                options=options,
                max_chapters=args.max_chapters,
                build_stage=builder,
                success_disposition=disposition,
                require_previous=require_previous,
                expected_manifest_fingerprint=args.expected_manifest_fingerprint,
            )
        emit_receipt(receipt)
        return exit_code
    except ChapterFailure as error:
        mode = (
            'repair' if args.pages
            else 'manual' if args.chapters or args.chapters_file
            else args.method
        )
        emit_receipt(failure_receipt(
            input_path=pdf_path,
            output_dir=output_dir,
            mode=mode if mode in {'toc', 'pattern', 'manual', 'repair'} else 'pattern',
            max_chapters=args.max_chapters,
            error=error,
        ))
        return error.exit_code


def main() -> int:
    argv = sys.argv[1:]
    json_mode = '--json' in argv
    if json_mode and any(item in {'-h', '--help'} for item in argv):
        return _json_error_from_argv(argv, '--help cannot be combined with --json')
    parser = _make_parser(json_mode=json_mode)
    try:
        args = parser.parse_args(argv)
    except (ValueError, argparse.ArgumentError) as exc:
        return _json_error_from_argv(argv, str(exc))
    if args.json:
        return _json_run(args, argv)
    if args.expected_manifest_fingerprint is not None:
        print(
            "Error: --expected-manifest-fingerprint requires --json",
            file=sys.stderr,
        )
        return 2
    if fitz is None:
        print("Error: PyMuPDF not installed. Run: pip install pymupdf")
        return 1
    return _legacy_run(args)


if __name__ == '__main__':
    sys.exit(main())
