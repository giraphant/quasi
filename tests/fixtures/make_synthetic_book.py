#!/usr/bin/env python3
"""Build a deterministic three-chapter EPUB for Book Workflow tests.

The script writes only the positional EPUB path and, when requested, the exact
path passed to ``--metadata-json``.  Parent directories must already exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile


ISBN = "9780000000002"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
COPYRIGHT_NOTICE = "Copyright © 2026 Quasi Test Press."
CHAPTERS = (
    (
        "01",
        "Alpha: Stable Inputs",
        "ALPHA",
        (
            "ALPHA records how a stable input becomes a durable scholarly artifact. "
            "The chapter distinguishes source identity, normalized text, and the "
            "evidence needed to justify each transformation. Its deliberately explicit "
            "argument gives the analyser enough prose to summarize without relying on "
            "outside knowledge or metadata."
        ),
    ),
    (
        "02",
        "Beta: Parallel Chapters",
        "BETA",
        (
            "BETA examines independent chapter work performed in parallel. Each member "
            "owns a distinct output, while a later barrier prevents synthesis from "
            "observing a partial set. The example emphasizes ordered membership without "
            "requiring sibling tasks to finish in their original sequence."
        ),
    ),
    (
        "03",
        "Gamma: Audit and Repair",
        "GAMMA",
        (
            "GAMMA follows exact artifact ownership through audit and bounded repair. "
            "A diagnostic identifies one producer and one path; unknown ownership fails "
            "closed instead of guessing. Re-audit then supplies the final evidence that "
            "the material is complete."
        ),
    ),
)


def zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = (
        zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    )
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def chapter_xhtml(
    title: str,
    sentinel: str,
    body: str,
    *,
    copyright_notice: str | None = None,
) -> str:
    publication_evidence = (
        f"\n    <p>{copyright_notice}</p>" if copyright_notice else ""
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
  <head><title>{title}</title></head>
  <body>
    <h1>{title}</h1>
    <p>{body}</p>
{publication_evidence}
    <p>{sentinel} is the unique verification sentinel for this chapter.</p>
  </body>
</html>
"""


def container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
 xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def content_opf(slug: str) -> str:
    manifest = "\n".join(
        f'    <item id="ch{slot}" href="ch{slot}.xhtml" '
        'media-type="application/xhtml+xml"/>'
        for slot, _title, _sentinel, _body in CHAPTERS
    )
    spine = "\n".join(
        f'    <itemref idref="ch{slot}"/>'
        for slot, _title, _sentinel, _body in CHAPTERS
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
 unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:isbn:{ISBN}</dc:identifier>
    <dc:title>Quasi Synthetic Book: {slug}</dc:title>
    <dc:creator>Ada Example</dc:creator>
    <dc:publisher>Quasi Test Press</dc:publisher>
    <dc:language>en</dc:language>
    <dc:date>2026</dc:date>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx"
      media-type="application/x-dtbncx+xml"/>
{manifest}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>
"""


def toc_ncx(slug: str) -> str:
    points = "\n".join(
        f"""    <navPoint id="nav-{slot}" playOrder="{index}">
      <navLabel><text>{title}</text></navLabel>
      <content src="ch{slot}.xhtml"/>
    </navPoint>"""
        for index, (slot, title, _sentinel, _body) in enumerate(
            CHAPTERS, start=1
        )
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:isbn:{ISBN}"/>
  </head>
  <docTitle><text>Quasi Synthetic Book: {slug}</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
"""


def metadata(output: Path, slug: str) -> dict[str, object]:
    return {
        "kind": "book",
        "slug": slug,
        "meta": {
            "title": f"Quasi Synthetic Book: {slug}",
            "authors": ["Ada Example"],
            "year": 2026,
            "publisher": "Quasi Test Press",
            "isbn": ISBN,
            "category": "monograph",
            "format": "epub",
            "confidence": "verified",
        },
        "source_path": str(output),
        "sentinels": [chapter[2] for chapter in CHAPTERS],
    }


def write_epub(output: Path, slug: str) -> None:
    if not output.parent.is_dir():
        raise FileNotFoundError(
            f"output parent does not exist: {output.parent}"
        )
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            zip_info("mimetype", stored=True),
            "application/epub+zip",
        )
        archive.writestr(
            zip_info("META-INF/container.xml"),
            container_xml(),
        )
        archive.writestr(
            zip_info("OEBPS/content.opf"),
            content_opf(slug),
        )
        archive.writestr(
            zip_info("OEBPS/toc.ncx"),
            toc_ncx(slug),
        )
        for slot, title, sentinel, body in CHAPTERS:
            archive.writestr(
                zip_info(f"OEBPS/ch{slot}.xhtml"),
                chapter_xhtml(
                    title,
                    sentinel,
                    body,
                    copyright_notice=(
                        COPYRIGHT_NOTICE if slot == "01" else None
                    ),
                ),
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--metadata-json",
        type=Path,
        help="optional exact path for the metadata JSON",
    )
    parser.add_argument(
        "--slug",
        help="defaults to the EPUB filename stem",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    slug = args.slug or args.output.stem
    write_epub(args.output, slug)
    payload = metadata(args.output, slug)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.metadata_json is not None:
        if not args.metadata_json.parent.is_dir():
            raise FileNotFoundError(
                "metadata parent does not exist: "
                f"{args.metadata_json.parent}"
            )
        args.metadata_json.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
