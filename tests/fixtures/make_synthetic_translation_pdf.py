#!/usr/bin/env python3
"""Create a deterministic three-page text PDF for Translate E2E tests.

The generator intentionally uses only the Python standard library. It writes
an ordinary PDF 1.4 text layer with a base-14 font, so translation coverage
can measure every source page without OCR or a binary fixture in git.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import textwrap


SENTINELS = ("ALPHA", "BETA", "GAMMA")
PARAGRAPHS = (
    (
        "Stable source identity is the first boundary in a reproducible "
        "translation workflow. The derivative must record the exact input "
        "bytes, language, configured backend, output target, and manifest "
        "generation before any remote work begins. A missing receipt never "
        "proves that a writer was harmless, because a provider can finish "
        "after the host loses its response. This page gives the translator "
        "enough continuous scholarly prose to exercise a real layout model."
    ),
    (
        "Bounded recovery separates semantic evidence from loop control. "
        "Coverage can report that translated body text is missing, but the "
        "graph alone owns the decision to create one layout OCR source and "
        "make one second translation attempt. The command owns locking, "
        "staging, validation, and publication, while the agent only relays "
        "one exact invocation. This arrangement keeps retries observable and "
        "prevents two uncertain writers from racing the same canonical PDF."
    ),
    (
        "Independent verification closes the derivative contract. It checks "
        "the source and manifest hashes, alternating page count, bookmark "
        "mapping, repaired character map, and measured translation coverage "
        "without changing the artifact. A successful terminal receipt must "
        "therefore identify one coherent generation rather than trust a path "
        "that merely exists. The three unique sentinels make it possible to "
        "trace every original page through the bilingual output and report."
    ),
)


def pdf_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def page_stream(slug: str, index: int) -> bytes:
    sentinel = f"{SENTINELS[index]}_TRANSLATE_E2E"
    heading = (
        f"Quasi Translation Native Fixture - Page {index + 1} - {sentinel}"
    )
    body = (
        f"{heading}. Fixture slug {slug}. {PARAGRAPHS[index]} "
        f"The exact page marker is {sentinel}, and it must remain visible "
        "on the original side of the final alternating bilingual PDF."
    )
    lines = [heading, ""] + textwrap.wrap(
        body,
        width=82,
        break_long_words=False,
        break_on_hyphens=False,
    )
    commands = [
        "BT",
        "/F1 11 Tf",
        "50 790 Td",
        "15 TL",
    ]
    for line in lines:
        commands.append(f"({pdf_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    return ("\n".join(commands) + "\n").encode("ascii")


def build_pdf(slug: str) -> bytes:
    streams = [page_stream(slug, index) for index in range(3)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Count 3 "
            b"/Kids [5 0 R 7 0 R 9 0 R] >>"
        ),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: (
            b"<< /Title (Quasi Translation Native E2E Fixture) "
            b"/Author (Quasi Integration Test Collective) "
            b"/Subject (Deterministic three-page translation fixture) "
            b"/Creator (make_synthetic_translation_pdf.py) "
            b"/Producer (Python standard library) "
            b"/CreationDate (D:20260730000000Z) >>"
        ),
    }
    for index, stream in enumerate(streams):
        page_object = 5 + index * 2
        content_object = page_object + 1
        objects[page_object] = (
            b"<< /Type /Page /Parent 2 0 R "
            b"/MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> "
            + f"/Contents {content_object} 0 R >>".encode("ascii")
        )
        objects[content_object] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for object_number in sorted(objects):
        offsets[object_number] = len(output)
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(objects[object_number])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(
        f"xref\n0 {len(offsets)}\n".encode("ascii")
    )
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R "
            f"/Info 4 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    if not args.slug or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in args.slug
    ):
        parser.error("--slug must be lowercase ASCII kebab text")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build_pdf(args.slug))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
