#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB处理工具 v2
正确解压和提取epub中的所有章节
"""

import os
import re
import sys
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from toc_utils import is_skip, assign_slots, make_filename


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
        chapters.append({
            'title': title.strip(),
            'src': src.strip()
        })

    return chapters


def process_epub(epub_path, output_dir):
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
            elif f.startswith('Text/') and f.endswith('.xhtml'):
                content_prefix = 'Text/'
                break

        # 读取toc.ncx (可能在不同位置)
        ncx_candidates = ['toc.ncx', content_prefix + 'toc.ncx', 'OEBPS/toc.ncx', 'OPS/toc.ncx']
        ncx_path = None
        for candidate in ncx_candidates:
            if candidate in all_files:
                ncx_path = candidate
                break

        chapters = []
        if ncx_path:
            ncx_content = zf.read(ncx_path).decode('utf-8')
            chapters = parse_toc_from_ncx(ncx_content)
            print(f"从toc.ncx读取到 {len(chapters)} 个导航点")

        # 如果没有ncx或解析失败，直接按文件名排序
        if not chapters:
            html_files = sorted([f for f in all_files if f.endswith('.html') or f.endswith('.xhtml')])
            chapters = [{'title': Path(f).stem, 'src': Path(f).name} for f in html_files]
            print(f"直接从文件列表读取到 {len(chapters)} 个HTML文件")

        # Pass 1: 过滤 + 读取 HTML + 提取文本。
        # slot 分配要基于"实际有内容的条目"，所以先把 HTML 全读完。
        entries: list[dict] = []
        skipped: list[dict] = []

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
            'total_chapters_in_toc': len(chapters),
            'chapters': [],
            'skipped': skipped,
        }

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


def main():
    if len(sys.argv) < 3:
        print("用法: python process_epub.py <epub文件> <输出目录>")
        print("示例: python process_epub.py book.epub ./chapters")
        sys.exit(1)

    epub_path = sys.argv[1]
    output_dir = sys.argv[2]

    process_epub(epub_path, output_dir)


if __name__ == '__main__':
    main()
