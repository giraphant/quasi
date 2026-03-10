---
name: quasi:extract
type: tool
description: >
  Extracts text from EPUB/PDF academic books into chapter-level plain text
  files. Use when preparing a book for analysis, or when the user says
  "提取章节", "拆分", "extract chapters".
---

# Extract — 文本提取

从 EPUB/PDF 提取章节级纯文本，为 analyze 技能准备输入。

## 接口

```
名称：extract
输入：EPUB 或 PDF 文件路径
参数：
  - output_dir: 章节文本输出目录
  - format: epub/pdf（自动检测）
输出：
  - {output_dir}/manifest.json（章节索引）
  - {output_dir}/*.txt（逐章纯文本）
```

## 使用方法

### EPUB 提取

```bash
python3 scripts/process_epub.py \
    sources/{book-name}.epub \
    processing/chapters/{book-name}/
```

产出：
- `manifest.json`（章节列表：文件名、标题、大小）
- `ch01-title.txt`, `ch02-title.txt`, ...

### PDF 拆分

```bash
# 自动拆分（基于 TOC 或页面分析）
python3 scripts/split_chapters.py \
    sources/{book-name}.pdf \
    --output-dir processing/chapters/{book-name}/

# OCR（扫描版 PDF）
bash quasi/skills/extract/scripts/ocr_pdf.sh \
    sources/{book-name}.pdf \
    sources/{book-name}-ocr.pdf
```

### 手动 manifest

对于 PDF 格式手册，通常需要手动创建 manifest.json（从 TOC 页面提取）：

```json
{
  "book_title": "...",
  "editors": "...",
  "publisher": "...",
  "year": 2022,
  "format": "pdf",
  "pdf_path": "sources/{book-name}.pdf",
  "chapters": [
    {"num": 1, "title": "...", "author": "...", "start_page": 15, "end_page": 32},
    ...
  ]
}
```

## 脚本

| 脚本 | 功能 | 来源 |
|------|------|------|
| `scripts/process_epub.py` | EPUB 提取章节文本 | 迁移自 handbook-processor |
| `scripts/split_chapters.py` | PDF 拆分章节 | 迁移自 handbook-processor |
| `scripts/ocr_pdf.sh` | PDF OCR 处理 | 迁移自 handbook-processor |

## 技能依赖

- 上游：**download** 获取文件
- 下游：extract 产出文本 → **analyze** 分析
- 调用方：**process-book**
