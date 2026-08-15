from __future__ import annotations

import json
import os
import shutil
import subprocess
from copy import deepcopy
from typing import Any

import pytest

from workflow_test_support import ROOT


PLAN_HARNESS = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const config = JSON.parse(process.argv[1]);
if (config.projectDir !== undefined && config.projectDir !== null)
  process.env.CLAUDE_PROJECT_DIR = config.projectDir;

async function load(source) {
  const built = await build({
    absWorkingDir: root,
    bundle: true,
    entryPoints: [resolve(root, source)],
    format: "esm",
    legalComments: "none",
    logLevel: "silent",
    platform: "node",
    target: ["es2022"],
    treeShaking: true,
    write: false,
  });
  const code = built.outputFiles[0].text;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}

const kind = config.kind || "paper";
const title = kind[0].toUpperCase() + kind.slice(1);
const plan = await load(`scripts/workflows/plans/${kind}.mts`);
const contract = await load(`scripts/workflows/contracts/${kind}.mts`);
const parsed = contract[`parse${title}RunInput`](config.input);
if (!parsed.ok) {
  process.stdout.write(JSON.stringify({
    result: parsed.result,
    calls: [],
    settled: [],
    pipelineCalls: 0,
    pipelineLabels: [],
    remaining: config.outputs.length,
  }));
  process.exit(0);
}

const calls = [];
const settled = [];
const outputs = [...config.outputs];
let pipelineCalls = 0;
const pipelineLabels = [];
const runtime = {
  agent: async (prompt, options) => {
    const blocks = [...prompt.matchAll(/```json\n([\s\S]*?)\n```/g)];
    const request = blocks.length > 0
      ? JSON.parse(blocks.at(-1)[1])
      : JSON.parse(prompt.slice(prompt.indexOf("{")));
    calls.push({ request, options });
    const spec = outputs.shift();
    const delay = spec && typeof spec === "object" && "__delay__" in spec
      ? spec.__delay__
      : 0;
    const output = spec && typeof spec === "object" && "__value__" in spec
      ? spec.__value__
      : spec;
    if (delay) await new Promise((resolveDelay) => setTimeout(resolveDelay, delay));
    settled.push(options.label);
    if (output === "__throw__") throw new Error("agent disappeared");
    return output === "__null__" ? null : output;
  },
  pipeline: async (items, worker) => {
    pipelineCalls += 1;
    pipelineLabels.push(items.map((item) => item.options.label));
    return Promise.all(items.map(worker));
  },
};

const result = await plan[`run${title}Plan`](runtime, parsed.value);
process.stdout.write(JSON.stringify({
  result,
  calls,
  settled,
  pipelineCalls,
  pipelineLabels,
  remaining: outputs.length,
}));
"""


PAPER_IDENTITY = {
    "slug": "exact-paper",
    "title": "Exact Paper",
    "authors": ["Ada Example"],
    "year": 2024,
    "doi": "10.1000/exact",
    "oa_url": "https://example.test/exact.pdf",
    "url": "https://example.test/exact",
    "journal": "Exact Joins",
    "confidence": "high",
}

BOOK_IDENTITY = {
    "slug": "exact-book",
    "title": "Exact Book",
    "authors": ["Ada Example"],
    "year": 2024,
    "isbn": "9780000000000",
    "publisher": "Exact Press",
    "category": "monograph",
    "confidence": "high",
}

BOOK_CHAPTERS = [
    {
        "slot": "01",
        "title": "Opening",
        "filename": "01_Opening.txt",
        "slug": "opening",
        "word_count": 120,
        "start_page": None,
        "end_page": None,
    },
    {
        "slot": "02",
        "title": "Closing",
        "filename": "02_Closing.txt",
        "slug": "closing",
        "word_count": 80,
        "start_page": 4,
        "end_page": 7,
    },
]


def book_observation(
    slug: str,
    *,
    source_format: str | None = None,
    manifest: bool = False,
    inventory: list[dict[str, Any]] | None = None,
    chapter_inputs: tuple[bool, ...] = (False, False),
    chapter_outputs: tuple[bool, ...] = (False, False),
    overview: bool = False,
    admitted: bool = False,
) -> dict[str, Any]:
    rows = inventory or BOOK_CHAPTERS
    chapters = []
    if manifest:
        for index, chapter in enumerate(rows):
            chapters.append(
                {
                    **deepcopy(chapter),
                    "input": {
                        "path": (
                            f"processing/chapters/{slug}/{chapter['filename']}"
                        ),
                        "present": chapter_inputs[index],
                        "usable": chapter_inputs[index],
                    },
                    "output": {
                        "path": (
                            f"vault/books/{slug}/"
                            f"ch{chapter['slot']}-{chapter['slug']}.md"
                        ),
                        "present": chapter_outputs[index],
                        "usable": chapter_outputs[index],
                    },
                }
            )
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "book",
        "slug": slug,
        "identity": (
            {
                "title": BOOK_IDENTITY["title"],
                "authors": BOOK_IDENTITY["authors"],
                "year": BOOK_IDENTITY["year"],
            }
            if admitted
            else None
        ),
        "facts": {
            "kind": "book",
            "sources": [
                {
                    "format": format_name,
                    "artifact": {
                        "path": f"sources/{slug}.{format_name}",
                        "present": source_format == format_name,
                        "usable": source_format == format_name,
                    },
                }
                for format_name in ("epub", "pdf")
            ],
            "manifest": {
                "path": f"processing/chapters/{slug}/manifest.json",
                "present": manifest,
                "usable": manifest,
                "valid": manifest,
            },
            "chapters": chapters,
            "overview": {
                "path": f"vault/books/{slug}/00-overview.md",
                "present": overview,
                "usable": overview,
            },
        },
    }


def provisional_book_input(
    requested_slug: str = "request-book",
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "provisional",
            "requested_slug": requested_slug,
            "hints": {"isbn": "9780000000000"},
        },
        "observation": book_observation(requested_slug),
        "options": {},
    }


def canonical_book_input(
    *,
    material_slug: str = "exact-book",
    source_format: str | None = None,
    manifest: bool = False,
    inventory: list[dict[str, Any]] | None = None,
    chapter_inputs: tuple[bool, ...] = (False, False),
    chapter_outputs: tuple[bool, ...] = (False, False),
    overview: bool = True,
    admitted: bool = True,
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": material_slug,
            "identity": deepcopy(BOOK_IDENTITY),
        },
        "observation": book_observation(
            material_slug,
            source_format=source_format,
            manifest=manifest,
            inventory=inventory,
            chapter_inputs=chapter_inputs,
            chapter_outputs=chapter_outputs,
            overview=overview,
            admitted=admitted,
        ),
        "options": {},
    }


def book_search_complete(
    identity: dict[str, Any] = BOOK_IDENTITY,
    *,
    owner_slug: str | None = None,
) -> dict[str, Any]:
    return {
        "identity": deepcopy(identity),
        "local_owner": (
            {
                "identity_slug": identity["slug"],
                "vault_slug": owner_slug,
                "path": f"vault/books/{owner_slug}/00-overview.md",
                "match": "isbn",
            }
            if owner_slug is not None
            else None
        ),
        "confidence": identity["confidence"],
        "observations": [],
        "terminal": {"status": "complete", "issue": None},
    }


def book_search_needs_input() -> dict[str, Any]:
    alternate = {
        **deepcopy(BOOK_IDENTITY),
        "slug": "exact-book-revised",
        "year": 2023,
        "isbn": "9780000000001",
    }
    return {
        "identity": None,
        "local_owner": None,
        "confidence": "low",
        "observations": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "material.identity_conflict",
                "operation": "material.search",
                "summary": "Two editions remain plausible.",
                "user_question": "Which edition is this?",
                "retryable": False,
            },
            "candidates": [
                {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
                {"kind": "book", "identity": alternate},
            ],
            "conflicts": ["edition", "year"],
        },
    }


def book_identity_decision() -> dict[str, Any]:
    gate = book_search_needs_input()["terminal"]
    return {
        "material_key": "book:request-book",
        "operation": "material.search",
        "value": {
            "candidates": deepcopy(gate["candidates"]),
            "conflicts": deepcopy(gate["conflicts"]),
            "selected_candidate": deepcopy(gate["candidates"][0]),
        },
    }


def book_year_evidence(
    year: int = 2024,
    *,
    verdict: str = "MATCH",
    recommended_year: int | None = None,
) -> dict[str, Any]:
    return {
        "slug_year": year,
        "source_years": {"publisher": recommended_year or year},
        "pdf_signals": {
            "first_published": recommended_year or year,
            "copyright_year": year,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": year if verdict == "MATCH" else recommended_year,
        "recommendation_reason": "Publisher evidence is decisive.",
        "verdict": verdict,
    }


def book_acquire_complete(
    slug: str = "exact-book",
    *,
    format_name: str = "epub",
    evidence: dict[str, Any] | None = None,
    tmp_path: str | None = None,
    isbn: str | None = BOOK_IDENTITY["isbn"],
) -> dict[str, Any]:
    return {
        "output_path": f"sources/{slug}.{format_name}",
        "format": format_name,
        "write_state": "written",
        "identity_verified": True,
        "isbn": isbn,
        "attempts": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "source": "publisher",
            "tmp_path": tmp_path,
            "year_evidence": evidence or book_year_evidence(),
        },
    }


def book_acquire_year_gate(
    *,
    year: int = 2024,
    verdict: str = "MISMATCH",
    recommended_year: int | None = 2023,
    tmp_path: str = ".quasi/temp/downloads/exact-book.epub",
) -> dict[str, Any]:
    actions = ["accept-current"]
    if verdict == "MISMATCH":
        actions.append("use-recommended-year")
    return {
        "output_path": None,
        "format": None,
        "write_state": "unknown",
        "identity_verified": False,
        "isbn": BOOK_IDENTITY["isbn"],
        "attempts": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": (
                    "book.year_mismatch"
                    if verdict == "MISMATCH"
                    else "book.year_ambiguous"
                ),
                "operation": "book.acquire",
                "summary": "The downloaded source carries a different year.",
                "user_question": "Which year should own this Book?",
                "retryable": False,
            },
            "tmp_path": tmp_path,
            "year_evidence": book_year_evidence(
                year,
                verdict=verdict,
                recommended_year=recommended_year,
            ),
            "proposed_actions": actions,
        },
    }


def book_year_decision(
    action: str,
    *,
    identity: dict[str, Any] = BOOK_IDENTITY,
) -> dict[str, Any]:
    gate = book_acquire_year_gate(year=identity["year"])["terminal"]
    return {
        "current_identity": deepcopy(identity),
        "tmp_path": gate["tmp_path"],
        "year_evidence": deepcopy(gate["year_evidence"]),
        "action": action,
    }


def book_prepare_complete(
    slug: str = "exact-book",
    *,
    format_name: str = "epub",
    chapters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inventory = deepcopy(chapters or BOOK_CHAPTERS)
    chapter_root = f"processing/chapters/{slug}"
    return {
        "selected_source": f"sources/{slug}.{format_name}",
        "normalized_path": f"{chapter_root}/source.txt",
        "manifest_fingerprint": "a" * 64,
        "mode": "epub" if format_name == "epub" else "toc",
        "disposition": "created",
        "chapter_count": len(inventory),
        "chapters": inventory,
        "artifacts": [
            {
                "role": "chapter_manifest",
                "path": f"{chapter_root}/manifest.json",
                "exists": True,
                "usable": True,
            },
            *[
                {
                    "role": "normalized_chapter",
                    "path": f"{chapter_root}/{chapter['filename']}",
                    "exists": True,
                    "usable": True,
                }
                for chapter in inventory
            ],
        ],
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def book_structure_candidates() -> list[dict[str, Any]]:
    return [
        {
            "key": "short",
            "label": "Two chapters",
            "summary": "Treat the two main divisions as chapters.",
            "chapter_count": 2,
            "chapters": [
                {"title": "Opening", "start": 1, "end": 3},
                {"title": "Closing", "start": 4, "end": 7},
            ],
        },
        {
            "key": "long",
            "label": "Three chapters",
            "summary": "Keep the middle transition separate.",
            "chapter_count": 3,
            "chapters": [
                {"title": "Opening", "start": 1, "end": 2},
                {"title": "Transition", "start": 3, "end": 4},
                {"title": "Closing", "start": 5, "end": 7},
            ],
        },
    ]


def book_prepare_structure_gate(
    slug: str = "exact-book",
    *,
    source_path: str | None = None,
) -> dict[str, Any]:
    source = source_path or f"sources/{slug}.pdf"
    return {
        "selected_source": source,
        "normalized_path": None,
        "manifest_fingerprint": None,
        "mode": None,
        "disposition": None,
        "chapter_count": 0,
        "chapters": [],
        "artifacts": [],
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "book.chapter_structure_ambiguous",
                "operation": "book.prepare",
                "summary": "Two chapter structures are defensible.",
                "user_question": "Which chapter structure should be used?",
                "retryable": False,
            },
            "source_path": source,
            "candidates": book_structure_candidates(),
            "conflicts": ["chapter_boundaries", "included_material"],
        },
    }


def book_structure_decision(
    *,
    source_path: str = "sources/exact-book.pdf",
) -> dict[str, Any]:
    candidates = book_structure_candidates()
    return {
        "source_path": source_path,
        "candidates": candidates,
        "conflicts": ["chapter_boundaries", "included_material"],
        "selected_candidate": deepcopy(candidates[0]),
    }


def chapter_complete(*, reconciled: bool = False) -> dict[str, Any]:
    return {
        "terminal": {
            "status": "complete",
            "issue": None,
            "action": "reconciled" if reconciled else "create",
            "write_state": "not_written" if reconciled else "written",
        }
    }


def chapter_repair_complete() -> dict[str, Any]:
    return {
        "terminal": {
            "status": "complete",
            "issue": None,
            "action": "repair",
            "write_state": "written",
        }
    }


def chapter_blocked() -> dict[str, Any]:
    return {
        "terminal": {
            "status": "blocked",
            "issue": {
                "code": "chapter.input_missing",
                "operation": "chapter.analyse",
                "summary": "The exact chapter input is unavailable.",
                "user_question": None,
                "retryable": False,
            },
            "action": "create",
            "write_state": "unknown",
        }
    }


def book_synthesise_complete(action: str = "create") -> dict[str, Any]:
    return {
        "terminal": {"status": "complete", "issue": None, "action": action}
    }


def run_book(
    value: dict[str, Any],
    outputs: list[Any],
    *,
    project_dir: str | None = None,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    env = dict(os.environ)
    if project_dir is None:
        env.pop("CLAUDE_PROJECT_DIR", None)
    else:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps(
                {
                    "kind": "book",
                    "input": value,
                    "outputs": outputs,
                    "projectDir": project_dir,
                }
            ),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def paper_observation(
    slug: str,
    *,
    source: bool = False,
    prepared: bool = False,
    canonical: bool = False,
    admitted: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "paper",
        "slug": slug,
        "identity": (
            {
                "title": PAPER_IDENTITY["title"],
                "authors": PAPER_IDENTITY["authors"],
                "year": PAPER_IDENTITY["year"],
            }
            if admitted
            else None
        ),
        "facts": {
            "kind": "paper",
            "source": {
                "path": f"sources/{slug}.pdf",
                "present": source,
                "usable": source,
            },
            "prepared": [
                {
                    "path": f"processing/papers/{slug}/source.txt",
                    "present": prepared,
                    "usable": prepared,
                },
                {
                    "path": f"processing/papers/{slug}/ocr.txt",
                    "present": False,
                    "usable": False,
                },
            ],
            "canonical": {
                "path": f"vault/papers/{slug}.md",
                "present": canonical,
                "usable": canonical,
            },
        },
    }


def provisional_input() -> dict[str, Any]:
    return {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper",
            "hints": {"doi": "10.1000/exact"},
        },
        "observation": paper_observation("request-paper"),
        "options": {},
    }


def canonical_input(
    *,
    material_slug: str = "exact-paper",
    source: bool = False,
    prepared: bool = False,
    canonical: bool = False,
    admitted: bool = False,
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": material_slug,
            "identity": deepcopy(PAPER_IDENTITY),
        },
        "observation": paper_observation(
            material_slug,
            source=source,
            prepared=prepared,
            canonical=canonical,
            admitted=admitted,
        ),
        "options": {},
    }


def identity_decision(selected: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
        {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
    ]
    return {
        "material_key": "paper:request-paper",
        "operation": "material.search",
        "value": {
            "candidates": candidates,
            "conflicts": ["publication_type"],
            "selected_candidate": deepcopy(selected),
        },
    }


def search_needs_input() -> dict[str, Any]:
    return {
        "identity": None,
        "local_owner": None,
        "confidence": "low",
        "observations": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "material.identity_conflict",
                "operation": "material.search",
                "summary": "Choose the publication type.",
                "user_question": "Is this the paper or the book?",
                "retryable": False,
            },
            "candidates": [
                {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
                {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
            ],
            "conflicts": ["publication_type"],
        },
    }


def search_complete(
    identity: dict[str, Any] = PAPER_IDENTITY,
    *,
    owner_slug: str | None = None,
) -> dict[str, Any]:
    owner = (
        {
            "identity_slug": identity["slug"],
            "vault_slug": owner_slug,
            "path": f"vault/papers/{owner_slug}.md",
            "match": "doi",
        }
        if owner_slug is not None
        else None
    )
    return {
        "identity": deepcopy(identity),
        "local_owner": owner,
        "confidence": identity["confidence"],
        "observations": [],
        "terminal": {"status": "complete", "issue": None},
    }


def acquire_complete() -> dict[str, Any]:
    return {
        "write_state": "written",
        "identity_verified": True,
        "attempts": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "source": "publisher",
        },
    }


def prepare_complete(slug: str = "exact-paper") -> dict[str, Any]:
    selected = f"processing/papers/{slug}/source.txt"
    return {
        "selected_input": selected,
        "artifacts": [
            {
                "role": "normalized_text",
                "path": selected,
                "exists": True,
                "usable": True,
            }
        ],
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def analyse_complete(action: str = "create") -> dict[str, Any]:
    return {
        "artifact_roles": ["canonical"],
        "terminal": {"status": "complete", "issue": None, "action": action},
    }


def audit_complete(
    *,
    escalated: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    diagnostics = escalated or []
    return {
        "remaining_violations": len(diagnostics),
        "escalated": diagnostics,
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }


def run_paper(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps({"input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_paper_provisional_happy_path_carries_prepare_selected_input() -> None:
    report = run_paper(
        provisional_input(),
        [
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.acquire",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][3]["request"]["input"] == {
        "role": "normalized_text",
        "path": "processing/papers/exact-paper/source.txt",
    }
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == [
        {
            "role": "canonical",
            "path": report["calls"][-1]["request"]["target"]["path"],
        }
    ]
    assert "receipts" not in report["result"]
    assert report["pipelineCalls"] == 0


def test_paper_admitted_canonical_starts_at_audit_and_ignores_stale_search_decision() -> None:
    value = canonical_input(canonical=True, admitted=True)
    value["userDecision"] = {
        "material_key": "paper:exact-paper",
        "operation": "retired.workflow.operation",
        "value": {"stale": True},
    }

    report = run_paper(value, [audit_complete()])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit"
    ]
    assert report["result"]["terminal"] == "complete"


def test_paper_search_lifts_only_the_typed_identity_gate() -> None:
    report = run_paper(provisional_input(), [search_needs_input()])

    assert report["result"]["terminal"] == "needs_input"
    assert report["result"]["resume_seed"] == {
        "route": {"kind": "paper", "slug": "request-paper"},
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper",
            "hints": {"doi": "10.1000/exact"},
        },
        "options": {},
    }
    assert report["result"]["gate"] == {
        "kind": "identity_conflict",
        "operation": "material.search",
        "material_key": "paper:request-paper",
        "question": "Is this the paper or the book?",
        "candidates": [
            {"kind": "paper", "identity": PAPER_IDENTITY},
            {"kind": "book", "identity": BOOK_IDENTITY},
        ],
        "conflicts": ["publication_type"],
    }


def test_paper_unknown_option_blocks_before_dispatch() -> None:
    value = provisional_input()
    value["options"] = {"cursor": "hidden-state"}

    report = run_paper(value, [search_needs_input()])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_paper_same_kind_decision_runs_one_owner_reconcile_search_under_gate_key() -> None:
    selected = {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)}
    value = provisional_input()
    value["userDecision"] = identity_decision(selected)

    report = run_paper(
        value,
        [search_complete(owner_slug="owned-paper"), audit_complete()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.audit",
    ]
    search_request = report["calls"][0]["request"]
    assert search_request["material_key"] == "paper:request-paper"
    assert search_request["requested_slug"] == "exact-paper"
    assert search_request["identity_decision"] == value["userDecision"]["value"]
    assert report["result"]["material"]["canonical"] == {
        "kind": "paper",
        "slug": "owned-paper",
    }


def test_paper_book_decision_returns_typed_next_without_dispatch() -> None:
    selected = {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)}
    value = provisional_input()
    value["userDecision"] = identity_decision(selected)

    report = run_paper(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == []
    assert report["result"]["next"] == selected


def test_paper_matching_but_incoherent_decision_stops_before_dispatch() -> None:
    value = provisional_input()
    value["userDecision"] = identity_decision(
        {
            "kind": "paper",
            "identity": {**deepcopy(PAPER_IDENTITY), "slug": "other-paper"},
        }
    )

    report = run_paper(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.incoherent_gate"


def test_paper_prepared_resume_reconciles_prepare_to_rebuild_selected_input() -> None:
    report = run_paper(
        canonical_input(
            source=True,
            prepared=True,
            canonical=True,
            admitted=False,
        ),
        [
            search_complete(),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][2]["request"]["input"]["path"] == (
        "processing/papers/exact-paper/source.txt"
    )
    assert report["calls"][2]["request"]["mode"] == "repair"


def test_paper_existing_canonical_reconciles_prepare_then_repairs_once() -> None:
    diagnostic = {
        "path": "vault/papers/exact-paper.md",
        "kind": "missing-section",
        "reason": "The Analysis section is absent.",
    }
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][2]["request"]["mode"] == "repair"
    assert report["calls"][2]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["calls"][3]["request"]["pass"] == 2
    assert report["result"]["terminal"] == "complete"


def test_paper_second_audit_escalation_stops_as_repair_exhausted() -> None:
    diagnostic = {
        "path": "vault/papers/exact-paper.md",
        "kind": "missing-section",
        "reason": "The Analysis section is absent.",
    }
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert len(report["calls"]) == 4
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"


def test_paper_unknown_writer_stops_without_later_dispatch() -> None:
    report = run_paper(
        provisional_input(),
        [search_complete(), "__throw__"],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.acquire",
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


def test_paper_foreign_audit_path_stops_without_repair_dispatch() -> None:
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(
                escalated=[
                    {
                        "path": "vault/papers/other-paper.md",
                        "kind": "missing-section",
                        "reason": "The Analysis section is absent.",
                    }
                ]
            )
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit"
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"


def test_book_provisional_happy_path_runs_one_stable_two_chapter_pipeline() -> None:
    report = run_book(
        provisional_book_input(),
        [
            book_search_complete(),
            book_acquire_complete(),
            book_prepare_complete(),
            {"__delay__": 30, "__value__": chapter_complete()},
            {"__delay__": 0, "__value__": chapter_complete()},
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations == [
        "material.search",
        "book.acquire",
        "book.prepare",
        "chapter.analyse",
        "chapter.analyse",
        "book.synthesise",
        "book.audit",
    ]
    chapter_requests = [
        call["request"] for call in report["calls"]
        if call["request"]["operation"] == "chapter.analyse"
    ]
    assert [request["identity"]["chapter_slot"] for request in chapter_requests] == [
        "01",
        "02",
    ]
    assert report["pipelineCalls"] == 1
    assert report["pipelineLabels"] == [
        ["exact-book:analyse:opening", "exact-book:analyse:closing"]
    ]
    assert [
        label for label in report["settled"] if ":analyse:" in label
    ] == ["exact-book:analyse:closing", "exact-book:analyse:opening"]
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == [
        {
            "role": "manifest",
            "path": "processing/chapters/exact-book/manifest.json",
        },
        {"role": "chapter", "path": "vault/books/exact-book/ch01-opening.md"},
        {"role": "chapter", "path": "vault/books/exact-book/ch02-closing.md"},
        {"role": "overview", "path": "vault/books/exact-book/00-overview.md"},
    ]
    assert "receipts" not in report["result"]


def test_book_uses_the_verified_source_isbn_after_acquire() -> None:
    source_isbn = "9780000000001"
    report = run_book(
        provisional_book_input(),
        [
            book_search_complete(),
            book_acquire_complete(isbn=source_isbn),
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    requests = {
        call["request"]["operation"]: call["request"]
        for call in report["calls"]
        if call["request"]["operation"] in {
            "book.acquire",
            "book.prepare",
            "book.synthesise",
        }
    }
    assert requests["book.acquire"]["identity"]["isbn"] == "9780000000000"
    assert requests["book.prepare"]["identity"]["isbn"] == source_isbn
    assert requests["book.synthesise"]["identity"]["isbn"] == source_isbn
    assert requests["book.synthesise"]["frontmatter_seed"]["isbn"] == source_isbn
    assert report["result"]["terminal"] == "complete"


def test_book_clears_an_unobserved_source_isbn_after_acquire() -> None:
    report = run_book(
        provisional_book_input(),
        [
            book_search_complete(),
            book_acquire_complete(isbn=None),
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    prepare = next(
        call["request"]
        for call in report["calls"]
        if call["request"]["operation"] == "book.prepare"
    )
    synthesis = next(
        call["request"]
        for call in report["calls"]
        if call["request"]["operation"] == "book.synthesise"
    )
    assert prepare["identity"]["isbn"] is None
    assert synthesis["frontmatter_seed"]["isbn"] is None


def test_book_preserves_the_verified_source_isbn_across_search_resume() -> None:
    source_isbn = "9780000000001"
    value = canonical_book_input(
        source_format="pdf",
        overview=False,
        admitted=False,
    )
    value["seed"]["identity"]["isbn"] = source_isbn

    report = run_book(
        value,
        [
            book_search_complete(),
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations[:2] == [
        "material.search",
        "book.prepare",
    ]
    assert "book.acquire" not in operations
    prepare = report["calls"][1]["request"]
    synthesis = next(
        call["request"]
        for call in report["calls"]
        if call["request"]["operation"] == "book.synthesise"
    )
    assert prepare["identity"]["isbn"] == source_isbn
    assert synthesis["frontmatter_seed"]["isbn"] == source_isbn


def test_book_search_lifts_only_its_closed_identity_gate() -> None:
    report = run_book(provisional_book_input(), [book_search_needs_input()])

    assert report["calls"][0]["request"]["operation"] == "material.search"
    assert report["result"] == {
        "schema_version": "quasi.material.result/0.1",
        "material": {
            "requested": {"kind": "book", "slug": "request-book"},
            "canonical": None,
        },
        "terminal": "needs_input",
        "issue": {
            "code": "material.identity_conflict",
            "operation": "material.search",
            "summary": "Two editions remain plausible.",
            "retryable": False,
            "observation_request": None,
        },
        "gate": {
            "kind": "identity_conflict",
            "operation": "material.search",
            "material_key": "book:request-book",
            "question": "Which edition is this?",
            "candidates": book_search_needs_input()["terminal"]["candidates"],
            "conflicts": ["edition", "year"],
        },
        "resume_seed": {
            "route": {"kind": "book", "slug": "request-book"},
            "seed": {
                "state": "provisional",
                "requested_slug": "request-book",
                "hints": {"isbn": "9780000000000"},
            },
            "options": {},
        },
    }


def test_book_search_existing_owner_stops_before_acquire() -> None:
    owner_slug = "existing-book"
    report = run_book(
        provisional_book_input(),
        [
            book_search_complete(owner_slug=owner_slug),
            book_acquire_complete(owner_slug),
            book_prepare_complete(owner_slug),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search"
    ]
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["material"]["canonical"]["slug"] == owner_slug
    assert report["result"]["artifacts"] == [
        {
            "role": "overview",
            "path": f"vault/books/{owner_slug}/00-overview.md",
        }
    ]


def test_book_identity_selection_existing_owner_stops_after_reconcile_search() -> None:
    value = provisional_book_input()
    value["observation"] = book_observation(
        "request-book",
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, True),
        overview=True,
        admitted=True,
    )
    value["userDecision"] = book_identity_decision()

    report = run_book(
        value,
        [book_search_complete(owner_slug="request-book")],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
    ]
    search_request = report["calls"][0]["request"]
    assert search_request["material_key"] == "book:request-book"
    assert search_request["requested_slug"] == "exact-book"
    assert search_request["identity_decision"] == value["userDecision"]["value"]
    assert report["result"]["material"]["canonical"] == {
        "kind": "book",
        "slug": "request-book",
    }


def test_book_identity_selection_later_gate_returns_effective_canonical_resume_seed() -> None:
    value = provisional_book_input()
    value["userDecision"] = book_identity_decision()
    tmp_path = ".quasi/temp/downloads/exact-book.pdf"

    report = run_book(
        value,
        [book_search_complete(), book_acquire_year_gate(tmp_path=tmp_path)],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "book.acquire",
    ]
    assert report["result"]["terminal"] == "needs_input"
    resume_seed = report["result"]["resume_seed"]
    assert resume_seed == {
        "route": {"kind": "book", "slug": "exact-book"},
        "seed": {
            "state": "canonical",
            "material_slug": "exact-book",
            "identity": BOOK_IDENTITY,
        },
        "options": {},
    }

    year_gate = report["result"]["gate"]
    year_decision = {
        "current_identity": year_gate["current_identity"],
        "tmp_path": year_gate["tmp_path"],
        "year_evidence": year_gate["year_evidence"],
        "action": "accept-current",
    }
    resumed = run_book(
        {
            "seed": resume_seed["seed"],
            "observation": book_observation(resume_seed["route"]["slug"]),
            "options": resume_seed["options"],
            "userDecision": {
                "material_key": year_gate["material_key"],
                "operation": year_gate["operation"],
                "value": year_decision,
            },
        },
        [
            book_search_complete(),
            book_acquire_complete(
                format_name="pdf",
                evidence=year_decision["year_evidence"],
                tmp_path=tmp_path,
            ),
            book_prepare_structure_gate(),
        ],
    )

    assert [call["request"]["operation"] for call in resumed["calls"]] == [
        "material.search",
        "book.acquire",
        "book.prepare",
    ]
    assert resumed["calls"][1]["request"]["year_decision"] == year_decision
    assert resumed["result"]["gate"]["kind"] == "book_structure"
    assert resumed["result"]["resume_seed"] == resume_seed


def test_book_recommended_year_inner_search_gate_keeps_canonical_resume_seed() -> None:
    value = canonical_book_input()
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": book_year_decision("use-recommended-year"),
    }

    report = run_book(value, [book_search_needs_input()])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search"
    ]
    identity_gate = report["result"]["gate"]
    assert identity_gate["kind"] == "identity_conflict"
    resume_seed = report["result"]["resume_seed"]
    assert resume_seed == {
        "route": {"kind": "book", "slug": "exact-book"},
        "seed": {
            "state": "canonical",
            "material_slug": "exact-book",
            "identity": BOOK_IDENTITY,
        },
        "options": {},
    }

    selected = identity_gate["candidates"][1]
    resumed = run_book(
        {
            "seed": resume_seed["seed"],
            "observation": canonical_book_input()["observation"],
            "options": resume_seed["options"],
            "userDecision": {
                "material_key": identity_gate["material_key"],
                "operation": identity_gate["operation"],
                "value": {
                    "candidates": identity_gate["candidates"],
                    "conflicts": identity_gate["conflicts"],
                    "selected_candidate": selected,
                },
            },
        },
        [
            book_search_complete(selected["identity"]),
            book_acquire_year_gate(
                year=selected["identity"]["year"],
                recommended_year=2022,
                tmp_path=(
                    ".quasi/temp/downloads/exact-book-revised.epub"
                ),
            ),
        ],
    )

    assert [call["request"]["operation"] for call in resumed["calls"]] == [
        "material.search",
        "book.acquire",
    ]
    assert resumed["calls"][0]["request"]["identity_decision"] == {
        "candidates": identity_gate["candidates"],
        "conflicts": identity_gate["conflicts"],
        "selected_candidate": selected,
    }
    acquire_request = resumed["calls"][1]["request"]
    assert acquire_request["material_key"] == "book:exact-book-revised"
    assert acquire_request["identity"]["year"] == selected["identity"]["year"]
    assert acquire_request["identity"]["isbn"] == selected["identity"]["isbn"]
    assert acquire_request["year_decision"] is None
    assert resumed["result"]["resume_seed"]["seed"] == {
        "state": "canonical",
        "material_slug": selected["identity"]["slug"],
        "identity": selected["identity"],
    }


def test_book_rejects_incomplete_year_decision_before_dispatch() -> None:
    value = canonical_book_input()
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": {"action": "accept-current"},
    }

    report = run_book(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.incoherent_gate"


def test_book_accept_current_year_binds_canonical_identity_once() -> None:
    value = provisional_book_input()
    year_gate_receipt = book_acquire_year_gate()
    gated = run_book(
        value,
        [
            book_search_complete(),
            year_gate_receipt,
        ],
    )

    assert [call["request"]["operation"] for call in gated["calls"]] == [
        "material.search",
        "book.acquire",
    ]
    terminal = year_gate_receipt["terminal"]
    assert gated["result"]["terminal"] == "needs_input"
    assert gated["result"]["gate"] == {
        "kind": "book_year",
        "operation": "book.acquire",
        "material_key": "book:exact-book",
        "current_identity": BOOK_IDENTITY,
        "question": "Which year should own this Book?",
        "tmp_path": terminal["tmp_path"],
        "year_evidence": terminal["year_evidence"],
        "proposed_actions": ["accept-current", "use-recommended-year"],
    }
    assert gated["pipelineCalls"] == 0

    decision = {
        "current_identity": gated["result"]["gate"]["current_identity"],
        "tmp_path": gated["result"]["gate"]["tmp_path"],
        "year_evidence": gated["result"]["gate"]["year_evidence"],
        "action": "accept-current",
    }
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": decision,
    }

    report = run_book(
        value,
        [
            book_search_complete(),
            book_acquire_complete(
                "exact-book",
                evidence=decision["year_evidence"],
                tmp_path=decision["tmp_path"],
            ),
            book_prepare_complete("exact-book"),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations[:2] == ["material.search", "book.acquire"]
    assert operations.count("material.search") == 1
    assert operations.count("book.acquire") == 1
    request = report["calls"][1]["request"]
    assert request["material_key"] == "book:exact-book"
    assert request["identity"] == BOOK_IDENTITY
    assert request["current_identity"] == BOOK_IDENTITY
    assert request["year_decision"] == decision
    assert report["result"]["material"]["canonical"]["slug"] == "exact-book"
    assert report["result"]["terminal"] == "complete"


def test_book_recommended_year_search_recanonicalizes_before_one_acquire() -> None:
    value = canonical_book_input(overview=False, admitted=False)
    decision = book_year_decision("use-recommended-year")
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": decision,
    }
    revised = {
        **deepcopy(BOOK_IDENTITY),
        "slug": "exact-book-2023",
        "year": 2023,
    }

    report = run_book(
        value,
        [
            book_search_complete(),
            book_search_complete(revised),
            book_acquire_complete(
                "exact-book-2023",
                evidence=decision["year_evidence"],
                tmp_path=decision["tmp_path"],
            ),
            book_prepare_complete("exact-book-2023"),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations.count("material.search") == 2
    assert operations.count("book.acquire") == 1
    search_requests = [
        call for call in report["calls"]
        if call["request"]["operation"] == "material.search"
    ]
    assert [
        request["request"].get("year_decision") for request in search_requests
    ] == [None, decision]
    search_request = search_requests[1]
    acquire_request = next(
        call for call in report["calls"]
        if call["request"]["operation"] == "book.acquire"
    )
    assert search_request["request"]["material_key"] == "book:exact-book"
    assert search_request["request"]["year_decision"] == decision
    assert acquire_request["request"]["material_key"] == "book:exact-book-2023"
    assert acquire_request["request"]["identity"] == revised
    assert acquire_request["request"]["year_decision"] == decision
    assert report["result"]["material"]["canonical"]["slug"] == (
        "exact-book-2023"
    )


def test_book_unknown_recanonicalization_search_never_starts_acquire() -> None:
    value = canonical_book_input(overview=False, admitted=False)
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": book_year_decision("use-recommended-year"),
    }

    report = run_book(value, [book_search_complete(), "__throw__"])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "material.search"
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


def test_book_fresh_post_acquire_facts_make_an_old_year_decision_stale() -> None:
    value = canonical_book_input()
    value["observation"]["facts"]["sources"][0]["artifact"].update(
        {"present": True, "usable": True}
    )
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": book_year_decision("use-recommended-year"),
    }

    report = run_book(
        value,
        [
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations[0] == "book.prepare"
    assert "material.search" not in operations
    assert "book.acquire" not in operations


def test_book_valid_manifest_resumes_fanout_without_source_or_prepare() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.prepare",
        "value": book_structure_decision(),
    }

    report = run_book(
        value,
        [
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "chapter.analyse",
        "chapter.analyse",
        "book.synthesise",
        "book.audit",
    ]
    assert report["pipelineCalls"] == 1


def test_book_manifest_with_a_missing_input_reconciles_prepare() -> None:
    value = canonical_book_input(
        source_format="epub",
        manifest=True,
        chapter_inputs=(True, False),
    )

    report = run_book(
        value,
        [
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert report["calls"][0]["request"]["operation"] == "book.prepare"
    assert report["calls"][0]["request"]["refs"]["source"] == (
        "sources/exact-book.epub"
    )


def test_book_missing_source_reconciles_acquire_before_prepare() -> None:
    value = canonical_book_input()
    value["options"] = {"allowed_formats": ["pdf", "epub"]}
    report = run_book(
        value,
        [
            book_acquire_complete(),
            book_prepare_complete(),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"][:2]] == [
        "book.acquire",
        "book.prepare",
    ]
    assert report["calls"][0]["request"]["allowed_formats"] == ["pdf", "epub"]


def test_book_rejects_scalar_allowed_formats_before_dispatch() -> None:
    value = canonical_book_input()
    value["options"] = {"allowed_formats": "epub"}

    report = run_book(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_book_pdf_prepare_lifts_structure_gate_before_any_fanout() -> None:
    report = run_book(
        canonical_book_input(source_format="pdf"),
        [book_prepare_structure_gate()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.prepare"
    ]
    terminal = book_prepare_structure_gate()["terminal"]
    assert report["result"]["gate"] == {
        "kind": "book_structure",
        "operation": "book.prepare",
        "material_key": "book:exact-book",
        "question": "Which chapter structure should be used?",
        "source_path": "sources/exact-book.pdf",
        "candidates": terminal["candidates"],
        "conflicts": terminal["conflicts"],
    }
    assert report["pipelineCalls"] == 0


def test_book_structure_decision_binds_the_current_pdf_prepare_once() -> None:
    value = canonical_book_input(source_format="pdf")
    decision = book_structure_decision()
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.prepare",
        "value": decision,
    }

    report = run_book(
        value,
        [
            book_prepare_complete(format_name="pdf"),
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    prepare_request = report["calls"][0]["request"]
    assert prepare_request["operation"] == "book.prepare"
    assert prepare_request["structure_decision"] == decision
    assert report["pipelineCalls"] == 1


def test_book_structure_decision_for_another_pdf_is_not_applied() -> None:
    value = canonical_book_input(source_format="pdf")
    value["userDecision"] = {
        "material_key": "book:exact-book",
        "operation": "book.prepare",
        "value": book_structure_decision(source_path="sources/other-book.pdf"),
    }

    report = run_book(value, [book_prepare_structure_gate()])

    assert report["calls"][0]["request"]["structure_decision"] is None
    assert report["result"]["terminal"] == "needs_input"


def test_book_binds_create_and_reconcile_only_from_initial_disk_outputs() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
    )
    value["observation"]["facts"]["chapters"][0]["output"]["usable"] = False

    report = run_book(
        value,
        [
            chapter_complete(reconciled=True),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    chapter_requests = [
        call["request"] for call in report["calls"]
        if call["request"]["operation"] == "chapter.analyse"
    ]
    assert [request["output_observation"]["exists"] for request in chapter_requests] == [
        True,
        False,
    ]
    assert [request["mode"] for request in chapter_requests] == ["create", "create"]
    assert report["result"]["terminal"] == "complete"


def test_book_incoherent_prepare_inventory_stops_before_fanout() -> None:
    duplicate = [deepcopy(BOOK_CHAPTERS[0]), deepcopy(BOOK_CHAPTERS[0])]
    start_only = deepcopy(BOOK_CHAPTERS)
    start_only[0].update({"start_page": 1, "end_page": None})
    reports = [
        run_book(
            canonical_book_input(source_format="epub"),
            [book_prepare_complete(chapters=inventory)],
        )
        for inventory in (duplicate, start_only)
    ]

    for report in reports:
        assert [call["request"]["operation"] for call in report["calls"]] == [
            "book.prepare"
        ]
        assert report["pipelineCalls"] == 0
        assert report["result"]["terminal"] == "blocked"
        assert report["result"]["issue"]["code"] == "workflow.incoherent_complete"


def test_book_chapter_join_settles_all_and_unknown_dominates() -> None:
    inventory = [
        *deepcopy(BOOK_CHAPTERS),
        {
            "slot": "03",
            "title": "Afterword",
            "filename": "03_Afterword.txt",
            "slug": "afterword",
            "word_count": 40,
            "start_page": 8,
            "end_page": 9,
        },
        {
            "slot": "04",
            "title": "Appendix",
            "filename": "04_Appendix.txt",
            "slug": "appendix",
            "word_count": 30,
            "start_page": 10,
            "end_page": 11,
        },
    ]
    value = canonical_book_input(
        manifest=True,
        inventory=inventory,
        chapter_inputs=(True, True, True, True),
        chapter_outputs=(False, False, False, False),
    )
    failed = {
        "terminal": {
            "status": "failed",
            "issue": {
                "code": "chapter.analysis_failed",
                "operation": "chapter.analyse",
                "summary": "The exact chapter analysis failed.",
                "user_question": None,
                "retryable": False,
            },
            "action": "create",
            "write_state": "not_written",
        }
    }

    report = run_book(
        value,
        [
            {"__delay__": 10, "__value__": chapter_blocked()},
            {"__delay__": 25, "__value__": "__throw__"},
            {"__delay__": 5, "__value__": failed},
            {"__delay__": 0, "__value__": chapter_complete()},
        ],
    )

    assert len(report["calls"]) == 4
    assert len(report["settled"]) == 4
    assert all(
        call["request"]["operation"] == "chapter.analyse"
        for call in report["calls"]
    )
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]
    assert report["remaining"] == 0

    first_blocked = chapter_blocked()
    first_blocked["terminal"]["issue"]["code"] = "chapter.first"
    second_blocked = chapter_blocked()
    second_blocked["terminal"]["issue"]["code"] = "chapter.second"
    ordered = run_book(
        value,
        [
            {"__delay__": 20, "__value__": first_blocked},
            {"__delay__": 0, "__value__": second_blocked},
            failed,
            chapter_complete(),
        ],
    )

    assert len(ordered["settled"]) == 4
    assert ordered["result"]["issue"]["code"] == "chapter.first"
    assert all(
        call["request"]["operation"] == "chapter.analyse"
        for call in ordered["calls"]
    )


def test_book_unknown_chapter_requests_fresh_book_observation() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    report = run_book(value, [chapter_complete(), "__throw__"])

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]
    assert report["result"]["resume_seed"] == {
        "route": {"kind": "book", "slug": "exact-book"},
        "seed": value["seed"],
        "options": {},
    }


def test_book_incoherent_chapter_requests_fresh_book_observation() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    report = run_book(
        value,
        [chapter_complete(), chapter_complete(reconciled=True)],
    )

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]


def test_book_fresh_status_dispatches_only_unusable_chapters() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
    )
    report = run_book(
        value,
        [
            book_search_complete(),
            chapter_complete(),
            book_synthesise_complete(),
            audit_complete(),
        ],
    )

    assert report["calls"][0]["request"]["operation"] == "material.search"
    chapter_calls = [
        call for call in report["calls"]
        if call["request"]["operation"] == "chapter.analyse"
    ]
    assert [call["request"]["output"]["path"] for call in chapter_calls] == [
        "vault/books/exact-book/ch02-closing.md"
    ]
    assert report["result"]["terminal"] == "complete"


def test_book_repairs_a_newly_written_chapter_once_then_reaudits() -> None:
    diagnostic = {
        "path": "vault/books/exact-book/ch01-opening.md",
        "kind": "missing-section",
        "reason": "The chapter analysis is incomplete.",
    }
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )

    report = run_book(
        value,
        [
            chapter_complete(),
            chapter_complete(),
            book_synthesise_complete("repair"),
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(),
        ],
    )

    chapter_requests = [
        call["request"] for call in report["calls"]
        if call["request"]["operation"] == "chapter.analyse"
    ]
    assert len(chapter_requests) == 3
    repair = chapter_requests[-1]
    assert repair["identity"]["chapter_slot"] == "01"
    assert repair["mode"] == "repair"
    assert repair["output_observation"]["exists"] is True
    assert repair["repair_diagnostics"] == [diagnostic]
    audits = [
        call["request"] for call in report["calls"]
        if call["request"]["operation"] == "book.audit"
    ]
    assert [request["pass"] for request in audits] == [1, 2]
    assert report["result"]["terminal"] == "complete"


def test_book_repairs_the_owned_overview_once_then_reaudits() -> None:
    diagnostic = {
        "path": "vault/books/exact-book/00-overview.md",
        "kind": "frontmatter",
        "reason": "The overview metadata is incomplete.",
    }
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(False, False),
        chapter_outputs=(True, True),
    )

    report = run_book(
        value,
        [
            audit_complete(escalated=[diagnostic]),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "book.synthesise",
        "book.audit",
    ]
    repair = report["calls"][1]["request"]
    assert repair["mode"] == "repair"
    assert repair["repair_diagnostics"] == [diagnostic]
    assert report["calls"][2]["request"]["pass"] == 2
    assert report["result"]["terminal"] == "complete"


def test_book_absolute_owned_chapter_audit_path_routes_repair() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/ch01-opening.md"),
        "kind": "block_kind_mismatch_soft",
        "reason": "金句要点 must use a blockquote list.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    repair = report["calls"][1]["request"]
    assert repair["identity"]["chapter_slot"] == "01"
    assert repair["repair_diagnostics"] == [diagnostic]
    assert report["result"]["terminal"] == "complete"


def test_book_configured_project_root_matches_absolute_audit_owner_path() -> None:
    project_root = "/tmp/quasi-book-plan-configured-root"
    diagnostic = {
        "path": f"{project_root}/vault/books/exact-book/ch01-opening.md",
        "kind": "missing-section",
        "reason": "The chapter analysis is incomplete.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(),
        ],
        project_dir=project_root,
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    assert report["result"]["terminal"] == "complete"


def test_book_harness_clears_inherited_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/quasi-ambient-project-root")
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/ch01-opening.md"),
        "kind": "missing-section",
        "reason": "The chapter analysis is incomplete.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    assert report["result"]["terminal"] == "complete"


def test_book_absolute_owned_overview_audit_path_routes_repair() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/00-overview.md"),
        "kind": "frontmatter",
        "reason": "The overview metadata is incomplete.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "book.synthesise",
        "book.audit",
    ]
    assert report["calls"][1]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["result"]["terminal"] == "complete"


def test_book_second_absolute_owned_escalation_is_repair_exhausted() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/ch01-opening.md"),
        "kind": "block_kind_mismatch_soft",
        "reason": "金句要点 still has mixed blocks.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"


def test_book_absolute_foreign_audit_path_remains_owner_ambiguity() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/another-book/ch01-opening.md"),
        "kind": "missing-section",
        "reason": "Foreign Book.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [audit_complete(escalated=[diagnostic])],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit"
    ]
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"


TALK_IDENTITY = {
    "title": "Exact Talk",
    "date": "2024-01-02",
    "media": "sources/exact-talk.mp3",
}
TALK_MEDIA_EXTENSIONS = (
    "mov", "mp4", "m4v", "mkv", "webm", "m4a", "wav", "mp3",
    "aac", "flac", "aiff", "aif", "ogg", "opus",
)


def talk_observation(
    *,
    transcripts: tuple[str, ...] = (),
    canonical: bool = False,
) -> dict[str, Any]:
    slug = "exact-talk"
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "talk",
        "slug": slug,
        "identity": {"title": TALK_IDENTITY["title"]} if canonical else None,
        "facts": {
            "kind": "talk",
            "media": [
                {
                    "path": f"sources/{slug}.{extension}",
                    "present": extension == "mp3",
                    "usable": extension == "mp3",
                }
                for extension in TALK_MEDIA_EXTENSIONS
            ],
            "transcripts": [
                {
                    "path": f"processing/talks/{slug}/{name}",
                    "present": True,
                    "usable": True,
                }
                for name in transcripts
            ],
            "canonical": {
                "path": f"vault/talks/{slug}/talk.md",
                "present": canonical,
                "usable": canonical,
            },
        },
    }


def canonical_talk_input(
    *,
    transcripts: tuple[str, ...] = (),
    canonical: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": "exact-talk",
            "identity": deepcopy(TALK_IDENTITY),
        },
        "observation": talk_observation(
            transcripts=transcripts,
            canonical=canonical,
        ),
        "options": options or {},
    }


def talk_prepare_complete(
    classification: str,
    *,
    canonical_present: bool = False,
    canonical_action: str | None = None,
) -> dict[str, Any]:
    slug = "exact-talk"
    canonical_path = f"vault/talks/{slug}/talk.md"
    artifacts = [
        {
            "role": "transcript",
            "path": f"vault/talks/{slug}/transcript.md",
            "sha256": "a" * 64,
            "size": 100,
        },
        *[
            {
                "role": "engine_transcript",
                "path": f"processing/talks/{slug}/transcript.{engine}.srt",
                "sha256": hash_value * 64,
                "size": 80,
            }
            for engine, hash_value in (
                ("soniox", "b"),
                ("apple", "c"),
                ("parakeet", "d"),
            )
        ],
    ]
    if classification in {"dead", "empty"}:
        canonical_present = True
        canonical_action = canonical_action or "create"
        artifacts.append(
            {
                "role": "canonical",
                "path": canonical_path,
                "sha256": "e" * 64,
                "size": 120,
            }
        )
    return {
        "source_observation": {
            "path": f"sources/{slug}.mp3",
            "sha256": "f" * 64,
        },
        "generation_observation": {
            "manifest_path": f"processing/talks/{slug}/manifest.json",
            "request_fingerprint": "1" * 64,
        },
        "classification": classification,
        "transcript_changed": False,
        "canonical_observation": (
            {"path": canonical_path, "sha256": "e" * 64}
            if canonical_present
            else None
        ),
        "canonical_action": canonical_action,
        "artifacts": artifacts,
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def talk_analyse_complete(action: str = "create") -> dict[str, Any]:
    return {
        "input_paths": [
            "vault/talks/exact-talk/transcript.md",
            "processing/talks/exact-talk/transcript.soniox.srt",
            "processing/talks/exact-talk/transcript.apple.srt",
            "processing/talks/exact-talk/transcript.parakeet.srt",
        ],
        "input_sha256s": ["a" * 64, "b" * 64, "c" * 64, "d" * 64],
        "artifact_roles": ["canonical"],
        "terminal": {"status": "complete", "issue": None, "action": action},
    }


def run_talk(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps({"kind": "talk", "input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_talk_live_uses_current_prepare_generation_then_audits() -> None:
    report = run_talk(
        canonical_talk_input(),
        [talk_prepare_complete("live"), talk_analyse_complete(), audit_complete()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.prepare",
        "talk.analyse",
        "talk.audit",
    ]
    prepare = report["calls"][0]["request"]
    assert prepare["engines"] == ["soniox", "apple", "parakeet"]
    assert prepare["identity"]["language"] == "auto"
    assert prepare["prepare_media"] is False
    assert [item["path"] for item in report["calls"][1]["request"]["inputs"]] == [
        "vault/talks/exact-talk/transcript.md",
        "processing/talks/exact-talk/transcript.soniox.srt",
        "processing/talks/exact-talk/transcript.apple.srt",
        "processing/talks/exact-talk/transcript.parakeet.srt",
    ]
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == [
        {"role": "canonical", "path": "vault/talks/exact-talk/talk.md"}
    ]
    assert report["pipelineCalls"] == 0


@pytest.mark.parametrize("classification", ["dead", "empty"])
def test_talk_silent_classification_uses_prepare_owned_canonical(
    classification: str,
) -> None:
    report = run_talk(
        canonical_talk_input(),
        [talk_prepare_complete(classification), audit_complete()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.prepare",
        "talk.audit",
    ]
    assert report["result"]["terminal"] == "complete"


def test_talk_transcript_status_reconciles_prepare_instead_of_rebuilding_carry() -> None:
    report = run_talk(
        canonical_talk_input(transcripts=("transcript.soniox.srt",)),
        [talk_prepare_complete("live"), talk_analyse_complete(), audit_complete()],
    )

    assert report["calls"][0]["request"]["operation"] == "talk.prepare"
    assert report["calls"][1]["request"]["inputs"][0]["path"] == (
        "vault/talks/exact-talk/transcript.md"
    )


def test_talk_usable_canonical_starts_at_audit() -> None:
    report = run_talk(canonical_talk_input(canonical=True), [audit_complete()])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.audit"
    ]
    assert report["result"]["terminal"] == "complete"


def test_talk_live_audit_reconciles_prepare_then_repairs_analyse_once() -> None:
    diagnostic = {
        "path": "vault/talks/exact-talk/talk.md",
        "kind": "missing-section",
        "reason": "The summary is incomplete.",
    }
    report = run_talk(
        canonical_talk_input(canonical=True),
        [
            audit_complete(escalated=[diagnostic]),
            talk_prepare_complete("live", canonical_present=True),
            talk_analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.audit",
        "talk.prepare",
        "talk.analyse",
        "talk.audit",
    ]
    assert report["calls"][1]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["calls"][2]["request"]["mode"] == "repair"
    assert report["calls"][3]["request"]["pass"] == 2


def test_talk_silent_audit_routes_repair_to_prepare_owner() -> None:
    diagnostic = {
        "path": "vault/talks/exact-talk/talk.md",
        "kind": "frontmatter",
        "reason": "Repair the silent canonical.",
    }
    report = run_talk(
        canonical_talk_input(canonical=True),
        [
            audit_complete(escalated=[diagnostic]),
            talk_prepare_complete("dead", canonical_action="repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.audit",
        "talk.prepare",
        "talk.audit",
    ]
    assert report["calls"][1]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["calls"][2]["request"]["pass"] == 2


def test_talk_foreign_audit_target_stops_before_repair() -> None:
    report = run_talk(
        canonical_talk_input(canonical=True),
        [
            audit_complete(
                escalated=[
                    {
                        "path": "vault/talks/another-talk/talk.md",
                        "kind": "missing-section",
                        "reason": "Foreign Talk.",
                    }
                ]
            )
        ],
    )

    assert len(report["calls"]) == 1
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"


def test_talk_second_audit_residual_stops_as_repair_exhausted() -> None:
    diagnostic = {
        "path": "vault/talks/exact-talk/talk.md",
        "kind": "missing-section",
        "reason": "The summary is incomplete.",
    }
    report = run_talk(
        canonical_talk_input(canonical=True),
        [
            audit_complete(escalated=[diagnostic]),
            talk_prepare_complete("live", canonical_present=True),
            talk_analyse_complete("repair"),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert len(report["calls"]) == 4
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"


def test_talk_unknown_writer_stops_without_later_dispatch() -> None:
    report = run_talk(canonical_talk_input(), ["__throw__"])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "talk.prepare"
    ]
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


def translation_observation_for_plan(
    target_language: str = "zh",
    *,
    source: bool = True,
    output: bool = False,
    manifest: bool = False,
) -> dict[str, Any]:
    target = target_language.lower()
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "translation",
        "slug": "exact-paper",
        "identity": None,
        "facts": {
            "kind": "translation",
            "target_language": target_language,
            "source": {
                "path": "sources/exact-paper.pdf",
                "present": source,
                "usable": source,
            },
            "output": {
                "path": f"processing/translations/exact-paper-{target}.pdf",
                "present": output,
                "usable": output,
            },
            "manifest": {
                "path": (
                    f"processing/translations/exact-paper-{target}.manifest.json"
                ),
                "present": manifest,
                "usable": manifest,
            },
        },
    }


def canonical_translation_input(
    *,
    requested_target: str = "zh-cn",
    observed_target: str = "zh",
    output: bool = False,
    manifest: bool = False,
) -> dict[str, Any]:
    return {
        "seed": {"state": "canonical", "material_slug": "exact-paper"},
        "target_language": requested_target,
        "observation": translation_observation_for_plan(
            observed_target,
            output=output,
            manifest=manifest,
        ),
        "options": {},
    }


def translation_complete(
    source_path: str = "sources/exact-paper.pdf",
) -> dict[str, Any]:
    return {
        "backend": "immersive",
        "source": {
            "path": source_path,
            "sha256": "a" * 64,
            "size": 1000,
            "pages": 10,
        },
        "disposition": "created",
        "recovered": False,
        "validation": {
            "output_sha256": "b" * 64,
            "manifest_sha256": "c" * 64,
            "output_size": 2000,
            "source_pages": 10,
            "output_pages": 20,
            "toc_entries": 0,
            "coverage": {
                "signal": "pass",
                "median": 0.8,
                "measured_pages": 10,
                "minimum_median": 0.5,
                "weakest": [],
                "detail": None,
            },
        },
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def translation_gate(kind: str) -> dict[str, Any]:
    candidates = [
        {
            "path": "sources/exact-paper.pdf",
            "sha256": "a" * 64,
            "size": 1000,
            "pages": 10,
        },
        {
            "path": "processing/papers/exact-paper/ocr.pdf",
            "sha256": "b" * 64,
            "size": 1100,
            "pages": 10,
        },
    ]
    source_gate = kind == "source_selection"
    return {
        "backend": None,
        "source": None,
        "disposition": None,
        "recovered": False,
        "validation": None,
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": (
                    "translation.source_selection_required"
                    if source_gate
                    else "translation.configuration_required"
                ),
                "operation": "translation.prepare",
                "summary": "Translation cannot continue yet.",
                "user_question": (
                    "Which source should be translated?"
                    if source_gate
                    else "Configure the translation provider."
                ),
                "retryable": False,
            },
            "gate": {
                "kind": kind,
                "missing_fields": [] if source_gate else ["translate_api_key"],
                "candidates": candidates if source_gate else [],
                "candidates_fingerprint": "f" * 64 if source_gate else None,
            },
        },
    }


def translation_source_missing() -> dict[str, Any]:
    return {
        "backend": None,
        "source": None,
        "disposition": None,
        "recovered": False,
        "validation": None,
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "failed",
            "issue": {
                "code": "translation.source_missing",
                "operation": "translation.prepare",
                "summary": "No exact source is available.",
                "user_question": None,
                "retryable": False,
            },
        },
    }


def run_translation(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps(
                {"kind": "translation", "input": value, "outputs": outputs}
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_translation_normalises_target_and_dispatches_exactly_once() -> None:
    report = run_translation(
        canonical_translation_input(output=True),
        [translation_complete()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "translation.prepare"
    ]
    request = report["calls"][0]["request"]
    assert request["material_key"] == "translation:paper:exact-paper:zh"
    assert request["identity"]["target_language"] == "zh"
    assert report["result"]["terminal"] == "complete"
    assert report["pipelineCalls"] == 0


def test_translation_rejects_a_different_target_observation_without_dispatch() -> None:
    report = run_translation(
        canonical_translation_input(
            requested_target="fr",
            observed_target="zh",
        ),
        [],
    )

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_translation_exact_output_and_manifest_reconcile_without_dispatch() -> None:
    value = canonical_translation_input(output=True, manifest=True)
    value["userDecision"] = {
        "material_key": "translation:paper:exact-paper:zh",
        "operation": "translation.prepare",
        "value": {"acknowledged": True},
    }
    report = run_translation(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["material"]["canonical"] == {
        "kind": "translation",
        "slug": "exact-paper",
    }
    assert report["result"]["artifacts"] == [
        {
            "role": "translation",
            "path": "processing/translations/exact-paper-zh.pdf",
        },
        {
            "role": "manifest",
            "path": "processing/translations/exact-paper-zh.manifest.json",
        },
    ]


def test_translation_source_gate_binds_its_fingerprint_and_selected_path() -> None:
    value = canonical_translation_input()
    gated = run_translation(value, [translation_gate("source_selection")])
    gate = gated["result"]["gate"]
    decision = {
        "candidates_fingerprint": gate["candidates_fingerprint"],
        "source_path": gate["candidates"][1]["path"],
    }

    assert gated["result"]["terminal"] == "needs_input"
    assert gate["material_key"] == "translation:paper:exact-paper:zh"

    value["userDecision"] = {
        "material_key": gate["material_key"],
        "operation": gate["operation"],
        "value": decision,
    }
    mismatched = run_translation(value, [translation_complete()])
    resumed = run_translation(
        value,
        [translation_complete(source_path=decision["source_path"])],
    )

    assert mismatched["result"]["terminal"] == "blocked"
    assert mismatched["result"]["issue"]["code"] == (
        "workflow.incoherent_complete"
    )
    assert (
        resumed["calls"][0]["request"]["source_request"]["decision"]
        == decision
    )
    assert resumed["result"]["terminal"] == "complete"


def test_translation_source_selection_survives_a_later_configuration_gate() -> None:
    initial = canonical_translation_input()
    source_gated = run_translation(
        initial,
        [translation_gate("source_selection")],
    )
    source_gate = source_gated["result"]["gate"]
    selected_source = source_gate["candidates"][1]["path"]
    first_resume = source_gated["result"]["resume_seed"]
    assert first_resume == {
        "route": {
            "kind": "translation",
            "slug": "exact-paper",
            "target_language": "zh",
        },
        "seed": {"state": "canonical", "material_slug": "exact-paper"},
        "options": {
            "source_file": None,
            "toc_json": None,
            "toc_page_side": "original",
        },
    }

    source_decision = {
        "candidates_fingerprint": source_gate["candidates_fingerprint"],
        "source_path": selected_source,
    }
    configuration_gated = run_translation(
        {
            "seed": first_resume["seed"],
            "target_language": first_resume["route"]["target_language"],
            "observation": translation_observation_for_plan(),
            "options": first_resume["options"],
            "userDecision": {
                "material_key": source_gate["material_key"],
                "operation": source_gate["operation"],
                "value": source_decision,
            },
        },
        [translation_gate("configuration_required")],
    )
    second_resume = configuration_gated["result"]["resume_seed"]
    assert second_resume == {
        **first_resume,
        "options": {
            **first_resume["options"],
            "source_file": selected_source,
        },
    }

    resumed = run_translation(
        {
            "seed": second_resume["seed"],
            "target_language": second_resume["route"]["target_language"],
            "observation": translation_observation_for_plan(),
            "options": second_resume["options"],
        },
        [translation_complete(source_path=selected_source)],
    )

    assert resumed["calls"][0]["request"]["source_request"] == {
        "path": selected_source,
        "decision": None,
    }
    assert resumed["result"]["terminal"] == "complete"


def test_translation_missing_source_stops_as_failed_without_retry() -> None:
    report = run_translation(
        canonical_translation_input(),
        [translation_source_missing()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "translation.prepare"
    ]
    assert report["result"]["terminal"] == "failed"
    assert report["result"]["issue"]["code"] == "translation.source_missing"


def test_translation_configuration_gate_rejects_acknowledgement_decision() -> None:
    value = canonical_translation_input()
    gated = run_translation(value, [translation_gate("configuration_required")])
    gate = gated["result"]["gate"]
    assert gate["kind"] == "translation_configuration"

    value["userDecision"] = {
        "material_key": gate["material_key"],
        "operation": gate["operation"],
        "value": {"acknowledged": True},
    }
    rejected = run_translation(value, [])

    assert rejected["calls"] == []
    assert rejected["result"]["issue"]["code"] == "workflow.incoherent_gate"


def test_translation_unknown_writer_stops_without_retry_or_audit() -> None:
    report = run_translation(canonical_translation_input(), ["__throw__"])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "translation.prepare"
    ]
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


AUTHOR_SEED = {
    "slug": "ada-example",
    "full_name": "Ada Example",
    "topic": "exact systems",
}


def author_observation(
    *,
    present: bool = False,
    usable: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "author",
        "slug": AUTHOR_SEED["slug"],
        "identity": ({"name": AUTHOR_SEED["full_name"]} if usable else None),
        "facts": {
            "kind": "author",
            "canonical": {
                "path": f"vault/authors/{AUTHOR_SEED['slug']}.md",
                "present": present,
                "usable": usable,
            },
        },
    }


def paper_identity(slug: str, title: str) -> dict[str, Any]:
    return {
        **deepcopy(PAPER_IDENTITY),
        "slug": slug,
        "title": title,
        "doi": f"10.1000/{slug}",
    }


def book_identity(slug: str, title: str) -> dict[str, Any]:
    return {
        **deepcopy(BOOK_IDENTITY),
        "slug": slug,
        "title": title,
        "isbn": "9780000000042",
    }


def admitted_paper_observation(identity: dict[str, Any]) -> dict[str, Any]:
    value = paper_observation(identity["slug"], canonical=True, admitted=True)
    value["identity"] = {
        "title": identity["title"],
        "authors": identity["authors"],
        "year": identity["year"],
    }
    return value


def admitted_book_observation(identity: dict[str, Any]) -> dict[str, Any]:
    value = book_observation(
        identity["slug"],
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, True),
        overview=True,
        admitted=True,
    )
    value["identity"] = {
        "title": identity["title"],
        "authors": identity["authors"],
        "year": identity["year"],
    }
    return value


def author_member(
    stable_route: dict[str, str],
    current_route: dict[str, str],
    identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "member_route": deepcopy(stable_route),
        "leaf": {
            "route": deepcopy(current_route),
            "seed": {
                "state": "canonical",
                "material_slug": current_route["slug"],
                "identity": deepcopy(identity),
            },
            "options": {},
        },
    }


def author_compose_input(
    members: list[dict[str, Any]],
    observations: list[tuple[dict[str, str], dict[str, Any]]],
    *,
    decision_member: dict[str, str] | None = None,
    user_decision: dict[str, Any] | None = None,
    author_present: bool = False,
) -> dict[str, Any]:
    value = {
        "observation": author_observation(
            present=author_present,
            usable=author_present,
        ),
        "resume_seed": {
            "kind": "author",
            "seed": deepcopy(AUTHOR_SEED),
            "options": {},
            "members": deepcopy(members),
            "decision_member": deepcopy(decision_member),
        },
        "child_observations": [
            {"route": deepcopy(route), "observation": deepcopy(observation)}
            for route, observation in observations
        ],
    }
    if user_decision is not None:
        value["userDecision"] = deepcopy(user_decision)
    return value


def author_discovery_complete(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "candidates": deepcopy(candidates),
        "terminal": {"status": "complete", "issue": None},
    }


def author_resolve_complete(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "output_exists": False,
        "resolved": [
            {
                "kind": candidate["kind"],
                "requested_slug": candidate["slug"],
                "vault_slug": None,
                "path": None,
                "match": None,
            }
            for candidate in candidates
        ],
        "terminal": {"status": "complete", "issue": None},
    }


def author_synthesise_complete(action: str = "create") -> dict[str, Any]:
    return {
        "terminal": {"status": "complete", "issue": None, "action": action}
    }


def run_author(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps({"kind": "author", "input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout)


def test_author_discovery_freezes_stable_deduplicated_batch_routes() -> None:
    book = {"kind": "book", **book_identity("book-one", "Book One")}
    paper = {"kind": "paper", **paper_identity("paper-one", "Paper One")}
    candidates = [book, paper, deepcopy(paper)]
    report = run_author(
        {
            "seed": deepcopy(AUTHOR_SEED),
            "observation": author_observation(),
            "options": {"maxBooks": 2, "maxPapers": 3},
        },
        [
            author_discovery_complete([book]),
            author_discovery_complete([paper, deepcopy(paper)]),
            author_resolve_complete(candidates),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "author.discover-books",
        "author.discover-papers",
        "author.resolve-membership",
    ]
    assert [report["calls"][0]["request"]["count"], report["calls"][1]["request"]["count"]] == [2, 3]
    assert report["pipelineCalls"] == 0
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "book-one"},
        {"kind": "paper", "slug": "paper-one"},
    ]
    members = report["result"]["resume_seed"]["members"]
    assert [member["member_route"] for member in members] == report["result"]["routes"]
    assert [member["leaf"]["seed"]["identity"]["title"] for member in members] == [
        "Book One",
        "Paper One",
    ]


def test_author_coalesces_canonical_children_and_repairs_once() -> None:
    identity = paper_identity("shared-paper", "Shared Paper")
    current = {"kind": "paper", "slug": "shared-paper"}
    members = [
        author_member({"kind": "paper", "slug": "request-one"}, current, identity),
        author_member({"kind": "paper", "slug": "request-two"}, current, identity),
    ]
    diagnostic = {
        "path": "vault/authors/ada-example.md",
        "kind": "missing-section",
        "reason": "The overview is incomplete.",
    }
    report = run_author(
        author_compose_input(
            members,
            [(current, admitted_paper_observation(identity))],
        ),
        [
            audit_complete(),
            author_synthesise_complete(),
            audit_complete(escalated=[diagnostic]),
            author_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations == [
        "paper.audit",
        "author.synthesise",
        "author.audit",
        "author.synthesise",
        "author.audit",
    ]
    syntheses = [
        call["request"] for call in report["calls"]
        if call["request"]["operation"] == "author.synthesise"
    ]
    assert [request["mode"] for request in syntheses] == ["create", "repair"]
    assert len(syntheses[0]["inputs"]) == 1
    assert syntheses[0]["inputs"][0]["title"] == "Shared Paper"
    assert syntheses[1]["repair_diagnostics"] == [diagnostic]
    assert report["result"]["terminal"] == "complete"


def test_author_paper_to_book_route_survives_a_later_paper_gate() -> None:
    p1 = paper_identity("paper-one", "Original Paper Title")
    p2 = paper_identity("paper-two", "Second Paper")
    b1 = book_identity("book-one", "Rerouted Book Title")
    p1_route = {"kind": "paper", "slug": "paper-one"}
    p2_route = {"kind": "paper", "slug": "paper-two"}
    p1_member = author_member(p1_route, p1_route, p1)
    p2_member = author_member(p2_route, p2_route, p2)
    route_to_book = {
        "material_key": "paper:paper-one",
        "operation": "material.search",
        "value": {
            "candidates": [
                {"kind": "paper", "identity": p1},
                {"kind": "book", "identity": b1},
            ],
            "conflicts": ["publication_type"],
            "selected_candidate": {"kind": "book", "identity": b1},
        },
    }
    routed = run_author(
        author_compose_input(
            [p1_member, p2_member],
            [
                (p1_route, paper_observation("paper-one")),
                (p2_route, paper_observation("paper-two")),
            ],
            decision_member=p1_route,
            user_decision=route_to_book,
        ),
        [],
    )

    assert routed["result"]["terminal"] == "needs_observation"
    assert routed["result"]["routes"] == [
        {"kind": "book", "slug": "book-one"},
        p2_route,
    ]
    routed_seed = routed["result"]["resume_seed"]
    assert routed_seed["members"][0]["member_route"] == p1_route
    assert routed_seed["members"][0]["leaf"]["seed"]["identity"] == b1

    p2_gate_receipt = search_needs_input()
    p2_gate_receipt["terminal"]["candidates"] = [
        {"kind": "paper", "identity": p2},
        {"kind": "book", "identity": b1},
    ]
    gated = run_author(
        author_compose_input(
            routed_seed["members"],
            [
                (
                    {"kind": "book", "slug": "book-one"},
                    admitted_book_observation(b1),
                ),
                (p2_route, paper_observation("paper-two")),
            ],
        ),
        [audit_complete(), p2_gate_receipt],
    )

    assert [call["request"]["operation"] for call in gated["calls"]] == [
        "book.audit",
        "material.search",
    ]
    gate_result = gated["result"]
    assert gate_result["terminal"] == "needs_input"
    assert gate_result["gate"]["gate"]["kind"] == "identity_conflict"
    assert gate_result["resume_seed"]["decision_member"] == p2_route
    assert gate_result["resume_seed"]["members"][0]["leaf"]["seed"]["identity"] == b1

    gate = gate_result["gate"]["gate"]
    decision = {
        "material_key": gate["material_key"],
        "operation": gate["operation"],
        "value": {
            "candidates": gate["candidates"],
            "conflicts": gate["conflicts"],
            "selected_candidate": {"kind": "paper", "identity": p2},
        },
    }
    resumed = run_author(
        author_compose_input(
            gate_result["resume_seed"]["members"],
            [
                (
                    {"kind": "book", "slug": "book-one"},
                    admitted_book_observation(b1),
                ),
                (p2_route, paper_observation("paper-two")),
            ],
            decision_member=p2_route,
            user_decision=decision,
        ),
        [
            audit_complete(),
            search_complete(p2, owner_slug="paper-two"),
            audit_complete(),
            author_synthesise_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in resumed["calls"]] == [
        "book.audit",
        "material.search",
        "paper.audit",
        "author.synthesise",
        "author.audit",
    ]
    synthesis = resumed["calls"][3]["request"]
    assert [item["title"] for item in synthesis["inputs"]] == [
        "Rerouted Book Title",
        "Second Paper",
    ]
    assert resumed["result"]["terminal"] == "complete"


def test_author_unknown_child_outcome_stops_before_later_members_or_writers() -> None:
    b1 = book_identity("book-one", "Book One")
    p2 = paper_identity("paper-two", "Paper Two")
    b1_route = {"kind": "book", "slug": "book-one"}
    p2_route = {"kind": "paper", "slug": "paper-two"}
    report = run_author(
        author_compose_input(
            [
                author_member(b1_route, b1_route, b1),
                author_member(p2_route, p2_route, p2),
            ],
            [
                (b1_route, admitted_book_observation(b1)),
                (p2_route, admitted_paper_observation(p2)),
            ],
        ),
        ["__throw__"],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit"
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


def test_author_lifts_book_gate_with_the_verified_source_isbn() -> None:
    identity = book_identity("book-one", "Book One")
    source_isbn = "9780000000043"
    route = {"kind": "book", "slug": "book-one"}
    member = author_member(route, route, identity)
    member["leaf"]["options"] = {"allowed_formats": ["pdf"]}

    report = run_author(
        author_compose_input(
            [member],
            [(route, book_observation("book-one"))],
        ),
        [
            book_search_complete(identity),
            book_acquire_complete(
                "book-one",
                format_name="pdf",
                isbn=source_isbn,
            ),
            book_prepare_structure_gate(),
        ],
    )

    assert report["result"]["terminal"] == "needs_input"
    assert report["result"]["gate"]["gate"]["kind"] == "book_structure"
    resumed_book = report["result"]["resume_seed"]["members"][0]["leaf"]
    assert resumed_book["seed"]["identity"]["isbn"] == source_isbn


def test_author_lifts_partial_book_observation_request() -> None:
    identity = book_identity("book-one", "Book One")
    route = {"kind": "book", "slug": "book-one"}
    observation = book_observation(
        "book-one",
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
        admitted=True,
    )
    observation["identity"] = {
        "title": identity["title"],
        "authors": identity["authors"],
        "year": identity["year"],
    }
    report = run_author(
        author_compose_input(
            [author_member(route, route, identity)],
            [(route, observation)],
        ),
        [book_search_complete(identity), "__throw__"],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "chapter.analyse",
    ]
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [route]
    assert report["result"]["resume_seed"]["members"][0]["leaf"]["route"] == route
