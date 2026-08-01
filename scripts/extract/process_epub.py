#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB处理工具 v2
正确解压和提取epub中的所有章节
"""

from __future__ import annotations

import argparse
import io
import os
import posixpath
import re
import sys
import json
import zipfile
from contextlib import redirect_stdout
from html.parser import HTMLParser
from pathlib import Path

from chapter_commit import (
    ChapterFailure,
    commit_chapter_set,
    emit_receipt,
    failure_receipt,
)
from toc_utils import (
    CHAPTER_REF_CONTRACT,
    assign_slots,
    is_skip,
    make_filename,
    make_slug,
)


HTML_SUFFIXES = {'.htm', '.html', '.xhtml'}


def _is_html_member(name: str) -> bool:
    return Path(name).suffix.lower() in HTML_SUFFIXES


class HTMLTextExtractor(HTMLParser):
    """从HTML中提取纯文本"""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.current_tag = None
        self.skip_tags = {'script', 'style', 'head', 'meta', 'link'}
        self.block_tags = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                          'li', 'blockquote', 'br', 'tr'}
        self.in_skip = False

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()
        if self.current_tag in self.skip_tags:
            self.in_skip = True
        if self.current_tag in self.block_tags:
            self.text_parts.append('\n')

    def handle_endtag(self, tag):
        if tag.lower() in self.skip_tags:
            self.in_skip = False
        if tag.lower() in self.block_tags:
            self.text_parts.append('\n')
        self.current_tag = None

    def handle_data(self, data):
        if not self.in_skip:
            text = data.strip()
            if text:
                self.text_parts.append(text + ' ')

    def get_text(self):
        text = ''.join(self.text_parts)
        # 清理多余空白
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()


def extract_text_from_html(html_content):
    """从HTML内容提取纯文本"""
    parser = HTMLTextExtractor()
    parser.feed(html_content)
    return parser.get_text()


def parse_toc_from_ncx(ncx_content):
    """解析toc.ncx获取章节信息"""
    chapters = []
    # 正则解析navPoint (处理标签间的空白)
    pattern = r'<navPoint[^>]*>.*?<navLabel>\s*<text>([^<]+)</text>\s*</navLabel>.*?<content\s+src="([^"]+)"'
    matches = re.findall(pattern, ncx_content, re.DOTALL)

    for title, src in matches:
        # 解码HTML实体
        title = title.replace('&#x2019;', "'").replace('&#x2018;', "'")
        title = title.replace('&amp;', '&').replace('&#x2013;', '–')
        title = ' '.join(title.split())
        chapters.append({
            'title': title,
            'src': src.strip()
        })

    return chapters


def _tag_attribute(tag: str, name: str) -> str | None:
    """Return one XML-ish tag attribute without assuming attribute order."""
    match = re.search(
        rf'\b{re.escape(name)}\s*=\s*(["\'])(.*?)\1',
        tag,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(2).strip() if match else None


def _resolve_member_reference(ref: str, base_path: str, all_files: list[str]) -> str:
    """Resolve an EPUB-relative reference, with an archive-wide basename fallback."""
    ref_clean = ref.split('#', 1)[0].replace('\\', '/').lstrip('/')
    relative = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), ref_clean))
    archive_relative = posixpath.normpath(ref_clean)
    for candidate in (relative, archive_relative):
        if candidate in all_files:
            return candidate

    basename = posixpath.basename(ref_clean)
    for member in all_files:
        if posixpath.basename(member) == basename:
            return member
    return relative


def _first_heading(html_content: str) -> str | None:
    """Extract normalized text from the first h1-h4 element."""
    match = re.search(
        r'<h[1-4]\b[^>]*>(.*?)</h[1-4]\s*>',
        html_content,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    title = ' '.join(extract_text_from_html(match.group(1)).split())
    return title or None


def process_epub(epub_path, output_dir, *, structured=False):
    """处理epub文件"""
    epub_path = Path(epub_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"处理 EPUB: {epub_path}")
    print(f"输出目录: {output_dir}")
    print()

    # 打开epub (它就是一个zip文件)
    with zipfile.ZipFile(epub_path, 'r') as zf:
        # 列出所有文件
        all_files = zf.namelist()

        # 找到内容目录前缀 (OEBPS/, OPS/, Text/, 或无前缀)
        content_prefix = ''
        for f in all_files:
            if 'OEBPS/' in f:
                content_prefix = 'OEBPS/'
                break
            elif 'OPS/' in f:
                content_prefix = 'OPS/'
                break
            elif f.startswith('Text/') and _is_html_member(f):
                content_prefix = 'Text/'
                break

        chapters = []
        skipped: list[dict] = []
        used_spine = False
        total_chapters_in_toc = 0

        # Prefer the OPF spine: it is the reading-order authority and may contain
        # content omitted from the NCX navigation map.
        opf_path = None
        if 'META-INF/container.xml' in all_files:
            container_content = zf.read('META-INF/container.xml').decode('utf-8')
            rootfile = re.search(r'<rootfile\b[^>]*>', container_content, re.IGNORECASE)
            if rootfile:
                candidate = _tag_attribute(rootfile.group(0), 'full-path')
                if candidate in all_files:
                    opf_path = candidate

        if opf_path:
            opf_content = zf.read(opf_path).decode('utf-8')
            manifest_items: dict[str, dict[str, str]] = {}
            for item_match in re.finditer(r'<item\b[^>]*>', opf_content, re.IGNORECASE):
                item_tag = item_match.group(0)
                item_id = _tag_attribute(item_tag, 'id')
                href = _tag_attribute(item_tag, 'href')
                media_type = _tag_attribute(item_tag, 'media-type') or ''
                if item_id and href:
                    manifest_items[item_id] = {
                        'href': href,
                        'path': _resolve_member_reference(href, opf_path, all_files),
                        'media_type': media_type,
                    }

            spine_match = re.search(
                r'<spine\b[^>]*>(.*?)</spine\s*>',
                opf_content,
                re.IGNORECASE | re.DOTALL,
            )
            spine_members = []
            if spine_match:
                for itemref_match in re.finditer(
                    r'<itemref\b[^>]*>', spine_match.group(1), re.IGNORECASE
                ):
                    itemref_tag = itemref_match.group(0)
                    if (_tag_attribute(itemref_tag, 'linear') or '').lower() == 'no':
                        continue
                    idref = _tag_attribute(itemref_tag, 'idref')
                    item = manifest_items.get(idref or '')
                    if item and _is_html_member(item['path']):
                        spine_members.append(item['path'])

            if spine_members:
                used_spine = True
                total_chapters_in_toc = len(spine_members)

                ncx_path = None
                for item in manifest_items.values():
                    if (
                        item['media_type'].lower() == 'application/x-dtbncx+xml'
                        or item['href'].lower().endswith('.ncx')
                    ):
                        ncx_path = item['path']
                        break
                if ncx_path not in all_files:
                    ncx_path = next(
                        (member for member in all_files if member.lower().endswith('.ncx')),
                        None,
                    )

                labels_by_path: dict[str, str] = {}
                if ncx_path:
                    ncx_content = zf.read(ncx_path).decode('utf-8')
                    for navpoint in parse_toc_from_ncx(ncx_content):
                        member = _resolve_member_reference(
                            navpoint['src'], ncx_path, all_files
                        )
                        labels_by_path.setdefault(member, navpoint['title'])

                for member in spine_members:
                    title = labels_by_path.get(member)
                    if title:
                        if is_skip(title):
                            skipped.append({'title': title, 'reason': 'non_content'})
                            continue
                    else:
                        html_content = zf.read(member).decode('utf-8', errors='replace')
                        title = _first_heading(html_content)
                        if not title:
                            skipped.append({
                                'title': Path(member).stem,
                                'reason': 'furniture',
                            })
                            continue
                        if is_skip(title):
                            skipped.append({'title': title, 'reason': 'non_content'})
                            continue
                    chapters.append({'title': title, 'src': member})

                print(f"从 OPF spine 读取到 {len(spine_members)} 个HTML条目")

        # Without a usable OPF spine, retain the NCX-order behavior but discover
        # any NCX member rather than relying on a handful of literal paths.
        if not used_spine:
            ncx_path = next(
                (member for member in all_files if member.lower().endswith('.ncx')),
                None,
            )
            if ncx_path:
                ncx_content = zf.read(ncx_path).decode('utf-8')
                chapters = parse_toc_from_ncx(ncx_content)
                print(f"从toc.ncx读取到 {len(chapters)} 个导航点")

            # 如果没有ncx或解析失败，直接按文件名排序
            if not chapters:
                html_files = sorted([f for f in all_files if _is_html_member(f)])
                chapters = [{'title': Path(f).stem, 'src': Path(f).name} for f in html_files]
                print(f"直接从文件列表读取到 {len(chapters)} 个HTML文件")
            total_chapters_in_toc = len(chapters)

        # Pass 1: 过滤 + 读取 HTML + 提取文本。
        # slot 分配要基于"实际有内容的条目"，所以先把 HTML 全读完。
        entries: list[dict] = []

        for chapter in chapters:
            src = chapter['src']
            title = chapter['title']

            if is_skip(title):
                skipped.append({'title': title, 'reason': 'non_content'})
                continue

            # 去掉 fragment identifier
            src_clean = src.split('#')[0] if '#' in src else src
            full_path = content_prefix + src_clean if not src_clean.startswith(content_prefix) else src_clean

            if full_path not in all_files:
                possible_paths = [src_clean, content_prefix + src_clean,
                                  'OEBPS/' + src_clean, 'OPS/' + src_clean, 'Text/' + src_clean]
                found = False
                for pp in possible_paths:
                    if pp in all_files:
                        full_path = pp
                        found = True
                        break
                if not found:
                    print(f"  ✗ 找不到文件: {src}")
                    skipped.append({'title': title, 'reason': 'file_not_found'})
                    continue

            try:
                html_content = zf.read(full_path).decode('utf-8')
                text = extract_text_from_html(html_content)
            except Exception as e:
                print(f"  ✗ 错误处理 {src}: {e}")
                skipped.append({'title': title, 'reason': f'extract_error: {e}'})
                continue

            if len(text) < 100:
                skipped.append({'title': title, 'reason': 'too_short'})
                continue

            entries.append({'title': title, 'text': text})

        # Pass 2: 分配 slot
        assign_slots(entries)

        # Pass 3: 写文件 + 建 manifest
        manifest = {
            'book_title': epub_path.stem,
            'total_chapters_in_toc': total_chapters_in_toc,
            'chapters': [],
            'skipped': skipped,
        }
        if structured:
            manifest.update({
                'source_epub': epub_path.name,
                'split_method': 'epub',
            })

        for e in entries:
            filename = make_filename(e['slot'], e['title'])
            output_path = output_dir / filename
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# {e['title']}\n\n")
                f.write(e['text'])

            manifest['chapters'].append({
                'slot': e['slot'],
                'title': e['title'],
                'filename': filename,
                'slug': make_slug(e['slot'], e['title']),
                'word_count': len(e['text'].split()),
            })

            print(f"  ✓ {e['slot']}: {e['title'][:45]}... ({len(e['text'].split())} words)")

    extracted_count = len(manifest['chapters'])
    manifest['extracted_count'] = extracted_count

    # 保存manifest
    manifest_path = output_dir / 'manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n完成！共提取 {extracted_count} 个章节")
    print(f"Manifest: {manifest_path}")

    return manifest


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _make_parser(json_mode: bool = False) -> argparse.ArgumentParser:
    parser_class = _JsonArgumentParser if json_mode else argparse.ArgumentParser
    parser = parser_class(description='Extract chapter text from an EPUB')
    parser.add_argument('epub_path', help='Path to the EPUB file')
    parser.add_argument('output_dir', help='Output directory for chapter files')
    parser.add_argument(
        '--max-chapters',
        type=int,
        default=50,
        help='Receipt threshold only; extraction is never changed (default: 50)',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Emit one structured receipt on stdout',
    )
    parser.add_argument(
        '--expected-manifest-fingerprint',
        help='Require the current manifest to match this SHA-256 before writing',
    )
    return parser


def _json_parse_failure(argv: list[str], message: str) -> int:
    positional = [item for item in argv if not item.startswith('-')]
    input_path = Path(positional[0]) if positional else Path('')
    output_dir = Path(positional[1]) if len(positional) > 1 else Path('')
    max_chapters = 50
    for index, item in enumerate(argv):
        if item == '--max-chapters' and index + 1 < len(argv):
            try:
                max_chapters = int(argv[index + 1])
            except ValueError:
                pass
        elif item.startswith('--max-chapters='):
            try:
                max_chapters = int(item.split('=', 1)[1])
            except ValueError:
                pass
    error = ChapterFailure(
        'invalid_arguments',
        message,
        exit_code=2,
    )
    emit_receipt(failure_receipt(
        input_path=input_path,
        output_dir=output_dir,
        mode='epub',
        max_chapters=max_chapters,
        error=error,
    ))
    return error.exit_code


def _json_run(args) -> int:
    exit_code, receipt = _commit_epub(args, progress_stream=sys.stderr)
    emit_receipt(receipt)
    return exit_code


def _commit_epub(args, *, progress_stream) -> tuple[int, dict]:
    input_path = Path(args.epub_path)
    output_dir = Path(args.output_dir)
    if args.max_chapters < 1:
        error = ChapterFailure(
            'invalid_arguments',
            '--max-chapters must be at least 1',
            exit_code=2,
        )
        receipt = failure_receipt(
            input_path=input_path,
            output_dir=output_dir,
            mode='epub',
            max_chapters=args.max_chapters,
            error=error,
        )
        return error.exit_code, receipt

    def build(stage_dir: Path, _previous_manifest: dict | None) -> dict:
        try:
            return process_epub(input_path, stage_dir, structured=True)
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
            raise ChapterFailure(
                'invalid_epub',
                f'cannot extract EPUB: {exc}',
                exit_code=2,
            ) from exc

    with redirect_stdout(progress_stream):
        exit_code, receipt = commit_chapter_set(
            input_path=input_path,
            output_dir=output_dir,
            mode='epub',
            options={
                'extractor': 'epub',
                'chapter_ref_contract': CHAPTER_REF_CONTRACT,
            },
            max_chapters=args.max_chapters,
            build_stage=build,
            expected_manifest_fingerprint=args.expected_manifest_fingerprint,
        )
    return exit_code, receipt


def _render_legacy(
    input_path: Path,
    output_dir: Path,
    receipt: dict,
) -> None:
    """Render the historical EPUB prose from a committed transaction."""

    print(f"处理 EPUB: {input_path}")
    print(f"输出目录: {output_dir}")
    print()
    for row in receipt['chapters']:
        print(
            f"  ✓ {row['slot']}: {row['title'][:45]}... "
            f"({row['word_count']} words)"
        )
    print(f"\n完成！共提取 {receipt['chapter_count']} 个章节")
    print(f"Manifest: {output_dir / 'manifest.json'}")


def main() -> int:
    argv = sys.argv[1:]
    json_mode = '--json' in argv
    if json_mode and any(item in {'-h', '--help'} for item in argv):
        return _json_parse_failure(argv, '--help cannot be combined with --json')
    parser = _make_parser(json_mode=json_mode)
    try:
        args = parser.parse_args(argv)
    except (ValueError, argparse.ArgumentError) as exc:
        return _json_parse_failure(argv, str(exc))
    if args.json:
        return _json_run(args)
    if args.expected_manifest_fingerprint is not None:
        print(
            "Error: --expected-manifest-fingerprint requires --json",
            file=sys.stderr,
        )
        return 2
    exit_code, receipt = _commit_epub(args, progress_stream=io.StringIO())
    if exit_code != 0:
        failure = receipt.get('failure') or {}
        print(
            f"Error: {failure.get('message', 'EPUB extraction failed')}",
            file=sys.stderr,
        )
        return exit_code
    _render_legacy(Path(args.epub_path), Path(args.output_dir), receipt)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
