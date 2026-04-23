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

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from toc_utils import is_skip, assign_slots, make_filename

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF not installed. Run: pip install pymupdf")
    sys.exit(1)


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
            'content': text.split('\n'),
        })
    return chapters


def find_chapter_boundaries(pages: list[tuple[int, str]], patterns: list[str]) -> list[dict]:
    """Find chapter boundaries using regex patterns."""
    combined_pattern = '|'.join(f'({p})' for p in patterns)
    regex = re.compile(combined_pattern, re.MULTILINE)

    chapters = []
    current_chapter = {'title': 'Frontmatter', 'start_page': 1, 'content': []}

    for page_num, text in pages:
        for line in text.split('\n'):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if regex.match(line_stripped):
                if current_chapter['content']:
                    chapters.append(current_chapter)
                current_chapter = {'title': line_stripped, 'start_page': page_num, 'content': []}
            else:
                current_chapter['content'].append(line)

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
                    output_dir: Path, pdf_name: str, method: str):
    """Create a manifest file listing all chapters."""
    manifest_path = output_dir / "manifest.json"
    manifest = {
        'source_pdf': pdf_name,
        'split_method': method,
        'total_chapters': len(chapters),
        'chapters': [
            {
                'slot': ch['slot'],
                'title': ch['title'],
                'start_page': ch['start_page'],
                'file': make_filename(ch['slot'], ch['title']),
            }
            for ch in chapters
        ],
        'skipped': skipped,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Created manifest: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description='Split PDF into chapter files')
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

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)

    # --- Mode 1: Manual chapters ---
    if args.chapters or args.chapters_file:
        if args.chapters_file:
            specs = json.loads(Path(args.chapters_file).read_text())
        else:
            specs = json.loads(args.chapters)

        print(f"Manual mode: {len(specs)} chapters specified")
        chapters = split_by_manual(str(pdf_path), specs)
        chapters = [ch for ch in chapters
                    if len('\n'.join(ch['content'])) >= args.min_chapter_length]
        print(f"Extracted {len(chapters)} chapters")
        chapters, skipped = filter_and_assign(chapters)
        save_chapters(chapters, output_dir)
        create_manifest(chapters, skipped, output_dir, pdf_path.name, 'manual')
        print("\nDone!")
        return

    # --- Mode 2: Single page range ---
    if args.pages:
        parts = args.pages.split('-')
        start, end = int(parts[0]), int(parts[1])
        text = extract_pages_text(str(pdf_path), start, end)
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r'[^\w\s-]', '', args.title)[:50].replace(' ', '_')
        out_file = output_dir / f"{safe_title}.txt"
        out_file.write_text(f"# {args.title}\n\n[Pages {start}-{end}]\n\n{text}")
        print(f"Extracted pages {start}-{end} → {out_file}")
        return

    # --- Mode 3: Auto split ---
    chapters = []
    method_used = args.method

    if args.method in ('auto', 'toc'):
        print(f"Trying TOC-based splitting (level <= {args.toc_level})...")
        chapters = split_by_toc(str(pdf_path), max_level=args.toc_level)
        if chapters:
            chapters = [ch for ch in chapters
                        if len('\n'.join(ch['content'])) >= args.min_chapter_length]
            print(f"TOC split: {len(chapters)} chapters")
            method_used = 'toc'
            if len(chapters) > args.max_chapters and args.toc_level > 1:
                print(f"Too many ({len(chapters)}), retrying toc-level=1...")
                chapters = split_by_toc(str(pdf_path), max_level=1)
                chapters = [ch for ch in chapters
                            if len('\n'.join(ch['content'])) >= args.min_chapter_length]
        else:
            print("No TOC found in PDF")
        if not chapters and args.method == 'toc':
            print("Error: --method toc but no TOC in PDF")
            sys.exit(1)

    if not chapters and args.method in ('auto', 'pattern'):
        print("Using pattern-based splitting...")
        patterns = ([p.strip() for p in args.patterns.split(',')] if args.patterns
                    else DEFAULT_PATTERNS)
        pages = extract_text_from_pdf(str(pdf_path))
        print(f"Extracted {len(pages)} pages")
        chapters = find_chapter_boundaries(pages, patterns)
        chapters = [ch for ch in chapters
                    if len('\n'.join(ch['content'])) >= args.min_chapter_length]
        method_used = 'pattern'

        if len(chapters) > args.max_chapters:
            print(f"WARNING: {len(chapters)} chapters detected (likely over-split)")
            print("Recommend: let coordinator read PDF TOC page and use --chapters mode")
            toc_ch = split_by_toc(str(pdf_path), max_level=1)
            if toc_ch:
                toc_ch = [ch for ch in toc_ch
                          if len('\n'.join(ch['content'])) >= args.min_chapter_length]
                if toc_ch and len(toc_ch) <= args.max_chapters:
                    print(f"Recovered via TOC: {len(toc_ch)} chapters")
                    chapters = toc_ch
                    method_used = 'toc'

    if not chapters:
        print("ERROR: No chapters found via any method.")
        print("Recommend: coordinator should read PDF, identify TOC page, and re-run with --chapters")
        sys.exit(1)

    print(f"\nFinal: {len(chapters)} chapters via {method_used}")
    chapters, skipped = filter_and_assign(chapters)
    save_chapters(chapters, output_dir)
    create_manifest(chapters, skipped, output_dir, pdf_path.name, method_used)
    print("\nDone! Chapter files are ready for processing.")


if __name__ == '__main__':
    main()
