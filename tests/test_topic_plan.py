from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from typing import Any

import pytest

from test_material_plans import (
    BOOK_IDENTITY,
    PAPER_IDENTITY,
    TALK_IDENTITY,
    acquire_complete,
    analyse_complete,
    audit_complete,
    book_observation,
    book_prepare_structure_gate,
    book_structure_decision,
    paper_observation,
    prepare_complete,
    search_complete,
    search_needs_input,
    talk_analyse_complete,
    talk_observation,
    talk_prepare_complete,
)
from workflow_test_support import ROOT, run_workflow_export


TOPIC_HARNESS = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const config = JSON.parse(process.argv[1]);

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

const contract = await load("scripts/workflows/contracts/topic.mts");
const parsed = contract.parseTopicRunInput(config.input);
if (!parsed.ok) {
  process.stdout.write(JSON.stringify({
    result: parsed.result,
    calls: [],
    remaining: config.outputs.length,
  }));
  process.exit(0);
}

const plan = await load("scripts/workflows/plans/topic.mts");
const outputs = [...config.outputs];
const calls = [];
const runtime = {
  agent: async (prompt, options) => {
    const blocks = [...prompt.matchAll(/```json\n([\s\S]*?)\n```/g)];
    const request = blocks.length > 0
      ? JSON.parse(blocks.at(-1)[1])
      : JSON.parse(prompt.slice(prompt.indexOf("{")));
    calls.push({ request, options });
    const output = outputs.shift();
    if (output === "__throw__") throw new Error("agent disappeared");
    return output === "__null__" ? null : output;
  },
  pipeline: async (items, worker) => Promise.all(items.map(worker)),
};
try {
  const result = await plan.runTopicPlan(runtime, parsed.value);
  process.stdout.write(JSON.stringify({ result, calls, remaining: outputs.length }));
} catch (error) {
  process.stdout.write(JSON.stringify({
    thrown: { name: error.name, message: error.message },
    calls,
    remaining: outputs.length,
  }));
}
"""


QUERY = {
    "slug": "exact-topic",
    "description": "How do exact systems govern academic visibility?",
}

SUBQUESTION = {
    "id": "sq-one",
    "question": "What is the exact mechanism?",
    "coverage": "covered",
    "channel": "academic",
    "theory_used": 1,
}


def artifact(path: str, usable: bool = False) -> dict[str, Any]:
    return {"path": path, "present": usable, "usable": usable}


def paper_member(slug: str = "exact-paper") -> dict[str, Any]:
    return {
        "kind": "paper",
        "slug": slug,
        "subq": "sq-one",
        "role": "evidence",
        "artifact": artifact(f"vault/papers/{slug}.md", True),
    }


def topic_observation(
    *,
    subquestions: list[dict[str, Any]] | None = None,
    members: list[dict[str, Any]] | None = None,
    cards: list[dict[str, Any]] | None = None,
    overview: bool = False,
    resources: bool = False,
) -> dict[str, Any]:
    projection = None
    if subquestions is not None:
        projection = {
            "subquestions": deepcopy(subquestions),
            "members": deepcopy(members or []),
            "cards": deepcopy(cards or []),
        }
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "topic",
        "slug": QUERY["slug"],
        "identity": ({"title": "Exact Topic"} if overview else None),
        "facts": {
            "kind": "topic",
            "outline": {
                **artifact(
                    f"vault/topics/{QUERY['slug']}/02-outline.md",
                    projection is not None,
                ),
                "valid": projection is not None,
                "projection": projection,
            },
            "overview": artifact(
                f"vault/topics/{QUERY['slug']}/00-overview.md", overview
            ),
            "resources": artifact(
                f"vault/topics/{QUERY['slug']}/01-resources.md", resources
            ),
        },
    }


def topic_input(
    *,
    observation: dict[str, Any] | None = None,
    max_rounds: int = 3,
    max_cards: int = 3,
    seeds: list[dict[str, Any]] | None = None,
    children: list[tuple[dict[str, str], dict[str, Any]]] | None = None,
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {
        "query": deepcopy(QUERY),
        "observation": observation or topic_observation(),
        "options": {"maxRounds": max_rounds, "maxCardsPerRound": max_cards},
        "seed_materials": deepcopy(seeds or []),
        "child_observations": [
            {"route": deepcopy(route), "observation": deepcopy(child)}
            for route, child in (children or [])
        ],
    }
    if resume is not None:
        value["resume"] = deepcopy(resume)
    return value


def recall_complete(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "items": deepcopy(items or []),
        "terminal": {"status": "complete", "issue": None},
    }


def steer_complete(
    *,
    signal: str,
    subquestions: list[dict[str, Any]],
    items: list[dict[str, Any]] | None = None,
    cards: list[str] | None = None,
    demands: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    suggested: list[str] | None = None,
    action: str = "refresh",
) -> dict[str, Any]:
    rows = deepcopy(subquestions)
    for row in rows:
        row["items"] = []
        row["cards"] = []
    rows[0]["items"] = deepcopy(items or [])
    rows[0]["cards"] = deepcopy(cards or [])
    return {
        "signal": signal,
        "subquestions": rows,
        "candidate_demands": deepcopy(demands or []),
        "web_tasks": deepcopy(tasks or []),
        "dirty": [],
        "suggested_queries": deepcopy(suggested or []),
        "terminal": {
            "status": "complete",
            "issue": None,
            "action": action,
        },
    }


def synthesis_complete(action: str = "create") -> dict[str, Any]:
    return {"terminal": {"status": "complete", "issue": None, "action": action}}


def paper_seed(*, provisional: bool = True) -> dict[str, Any]:
    seed = (
        {
            "state": "provisional",
            "requested_slug": "exact-paper",
            "hints": {"doi": PAPER_IDENTITY["doi"]},
        }
        if provisional
        else {
            "state": "canonical",
            "material_slug": "exact-paper",
            "identity": deepcopy(PAPER_IDENTITY),
        }
    )
    return {"kind": "paper", "seed": seed, "options": {}}


def book_seed() -> dict[str, Any]:
    return {
        "kind": "book",
        "seed": {
            "state": "canonical",
            "material_slug": "exact-book",
            "identity": deepcopy(BOOK_IDENTITY),
        },
        "options": {},
    }


def talk_seed() -> dict[str, Any]:
    return {
        "kind": "talk",
        "seed": {
            "state": "canonical",
            "material_slug": "exact-talk",
            "identity": deepcopy(TALK_IDENTITY),
        },
        "options": {
            "engines": ["soniox", "apple", "parakeet"],
            "lang": "auto",
            "prepare_media": False,
        },
    }


def demand(
    *,
    query: str = "find exact paper",
    requested_slug: str = "exact-paper",
) -> dict[str, Any]:
    return {
        "kind": "paper",
        "requested_slug": requested_slug,
        "query": query,
        "subq": "sq-one",
        "role": "evidence",
        "reason": "The exact mechanism needs academic evidence.",
    }


def web_task(card_slug: str = "exact-card") -> dict[str, Any]:
    return {
        "subq": "sq-one",
        "query": "verify the exact public claim",
        "note": "Use a bounded public source.",
        "card_slug": card_slug,
    }


def webcard_complete(*, empty: bool = False) -> dict[str, Any]:
    return {
        "card_status": "empty" if empty else "ok",
        "wrote_card": not empty,
        "card_available": not empty,
        "title": None if empty else "Exact Card",
        "objects": 0 if empty else 1,
        "sources": 0 if empty else 1,
        "evidence": None if empty else "confirmed",
        "note": "No verifiable evidence." if empty else "Verified.",
        "terminal": {"status": "complete", "issue": None},
    }


def run_topic(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", TOPIC_HARNESS, json.dumps({
            "input": value,
            "outputs": outputs,
        })],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-5000:]
    return json.loads(proc.stdout)


def test_topic_contract_binds_nested_exact_paths_and_steer_uses_schema_projection() -> None:
    malformed = topic_observation(
        subquestions=[SUBQUESTION], members=[paper_member()], cards=[]
    )
    malformed["facts"]["outline"]["projection"]["members"][0]["artifact"][
        "path"
    ] = "vault/papers/other-paper.md"

    report = run_topic(topic_input(observation=malformed), [])

    assert report["calls"] == []
    assert report["result"]["issue"]["code"] == "material.invalid_input"

    cross_talk = topic_input()
    cross_talk["resume"] = {
        "resume_seed": {
            "kind": "checkpoint_admission",
            "topic": deepcopy(QUERY),
            "item": "member",
            "source_route": {"kind": "talk", "slug": "talk-one"},
            "ref": {
                "kind": "talk",
                "slug": "talk-two",
                "path": "vault/talks/talk-two/talk.md",
            },
            "assignment": None,
        }
    }
    rejected = run_topic(cross_talk, [])
    assert rejected["calls"] == []
    assert rejected["result"]["issue"]["code"] == "material.invalid_input"

    short_card = topic_input()
    short_card["resume"] = {
        "resume_seed": {
            "kind": "checkpoint_admission",
            "topic": deepcopy(QUERY),
            "item": "card",
            "ref": {
                "slug": "x",
                "path": f"vault/topics/{QUERY['slug']}/cards/x.md",
                "title": None,
            },
            "assignment": {"subq": "sq-one"},
        }
    }
    rejected = run_topic(short_card, [])
    assert rejected["calls"] == []
    assert rejected["result"]["issue"]["code"] == "material.invalid_input"

    prepared = run_workflow_export(
        "scripts/workflows/operations/catalogs/topic.mts",
        "prepareOperation",
        {
            "operation": "topic.steer",
            "slug": QUERY["slug"],
            "context": {
                "materialKey": f"topic:{QUERY['slug']}",
                "researchKey": f"topic:{QUERY['slug']}",
                "query": QUERY["description"],
                "memberRefs": [],
                "memberAssignments": [],
                "cardRefs": [],
                "mode": "create",
                "diagnostics": [],
                "maxCards": 2,
            },
            "label": f"{QUERY['slug']}:topic.steer",
        },
    )
    schema = prepared["options"]["schema"]["properties"]
    demand = schema["candidate_demands"]["items"]
    assert "requested_slug" in demand["required"]
    assert schema["web_tasks"]["maxItems"] == 2


def test_topic_existing_member_finalises_in_owner_order() -> None:
    member = paper_member()
    diagnostic = {
        "path": f"vault/topics/{QUERY['slug']}/02-outline.md",
        "kind": "missing-section",
        "reason": "The outline needs one semantic repair.",
    }
    observation = topic_observation(
        subquestions=[SUBQUESTION], members=[member], cards=[]
    )
    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
            ),
            audit_complete(escalated=[diagnostic]),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                action="repair",
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "topic.recall",
        "topic.steer",
        "topic.audit",
        "topic.steer",
        "topic.audit",
        "topic.synthesise.overview",
        "topic.synthesise.resources",
        "topic.audit",
        "topic.audit",
    ]
    repair = report["calls"][3]["request"]
    assert repair["mode"] == "repair"
    assert repair["repair_diagnostics"] == [diagnostic]
    assert report["calls"][4]["request"]["pass"] == 2
    assert report["result"]["terminal"] == "complete"
    assert report["remaining"] == 0


def test_topic_seed_status_handshake_preserves_work_across_changed_recall() -> None:
    first = run_topic(
        topic_input(seeds=[paper_seed()]),
        [recall_complete([{"kind": "book", "slug": "other-book", "path": None}])],
    )

    assert first["result"]["terminal"] == "needs_observation"
    assert first["result"]["routes"] == [{"kind": "paper", "slug": "exact-paper"}]
    capsule = first["result"]["resume_seed"]

    resumed = run_topic(
        topic_input(
            seeds=[paper_seed()],
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
            resume={"resume_seed": capsule},
        ),
        [recall_complete(), search_needs_input()],
    )

    assert [call["request"]["operation"] for call in resumed["calls"]] == [
        "topic.recall",
        "material.search",
    ]
    assert resumed["result"]["terminal"] == "needs_input"
    assert resumed["result"]["gate"]["kind"] == "child"
    assert resumed["result"]["resume_seed"]["kind"] == "seed_child"


def test_topic_same_owner_provisional_seeds_run_one_leaf() -> None:
    first_seed = paper_seed()
    second_seed = paper_seed()
    second_seed["seed"]["hints"] = {"title": "A second hint for the same owner"}
    report = run_topic(
        topic_input(
            seeds=[first_seed, second_seed],
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
        ),
        [
            recall_complete(),
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations.count("material.search") == 1
    assert operations.count("paper.acquire") == 1
    assert report["result"]["terminal"] == "complete"


def test_topic_recalled_member_resume_consumes_frozen_row_after_changed_recall() -> None:
    recalled = {
        "kind": "paper",
        "slug": "exact-paper",
        "path": "vault/papers/exact-paper.md",
    }
    first = run_topic(topic_input(), [recall_complete([recalled])])

    assert first["result"]["terminal"] == "needs_observation"
    assert first["result"]["resume_seed"]["kind"] == "recalled_member"

    resumed = run_topic(
        topic_input(
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper", canonical=True, admitted=True),
            ), (
                {"kind": "book", "slug": "changed-book"},
                book_observation("changed-book"),
            )],
            resume={"resume_seed": first["result"]["resume_seed"]},
        ),
        [
            recall_complete([{"kind": "book", "slug": "changed-book", "path": None}]),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                action="create",
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in resumed["calls"]]
    assert operations[:2] == ["topic.recall", "topic.steer"]
    assert not any(operation.startswith("paper.") for operation in operations)
    assert resumed["calls"][1]["request"]["members"] == [
        {
            "kind": "paper",
            "slug": "exact-paper",
            "path": "vault/papers/exact-paper.md",
        }
    ]
    assert resumed["result"]["terminal"] == "complete"


def test_topic_discards_stale_material_capsule_after_subquestion_deletion() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    first = run_topic(
        topic_input(observation=topic_observation(subquestions=[gap], members=[], cards=[])),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                demands=[demand()],
            ),
        ],
    )
    assert first["result"]["terminal"] == "needs_observation"

    replacement = {**SUBQUESTION, "id": "sq-new", "coverage": "covered"}
    member = paper_member()
    member["subq"] = "sq-new"
    resumed = run_topic(
        topic_input(
            observation=topic_observation(
                subquestions=[replacement], members=[member], cards=[]
            ),
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
            resume={"resume_seed": first["result"]["resume_seed"]},
        ),
        [
            recall_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[replacement],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in resumed["calls"]]
    assert operations[:2] == ["topic.recall", "topic.steer"]
    assert not any(operation in {
        "material.search", "paper.acquire", "paper.prepare", "paper.analyse", "paper.audit"
    } for operation in operations)
    assert resumed["result"]["terminal"] == "complete"


def test_topic_zero_bound_gates_provisional_seed_but_runs_canonical_book() -> None:
    provisional = run_topic(
        topic_input(max_rounds=0, seeds=[paper_seed()]),
        [recall_complete()],
    )

    assert [call["request"]["operation"] for call in provisional["calls"]] == [
        "topic.recall"
    ]
    assert provisional["result"]["gate"]["kind"] == "topic_seed"

    book_status = book_observation(
        "exact-book", source_format="pdf", admitted=True
    )
    canonical = run_topic(
        topic_input(
            max_rounds=0,
            seeds=[book_seed()],
            children=[({"kind": "book", "slug": "exact-book"}, book_status)],
        ),
        [
            recall_complete(),
            book_prepare_structure_gate(),
        ],
    )

    assert [call["request"]["operation"] for call in canonical["calls"]] == [
        "topic.recall",
        "book.prepare",
    ]
    assert canonical["result"]["terminal"] == "needs_input"
    assert canonical["result"]["gate"]["gate"]["kind"] == "book_structure"


def test_topic_lifts_partial_book_observation_request() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    route = {"kind": "book", "slug": "exact-book"}
    observation = book_observation(
        "exact-book",
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
        admitted=True,
    )
    report = run_topic(
        topic_input(
            observation=topic_observation(subquestions=[gap], members=[], cards=[]),
            seeds=[book_seed()],
            children=[(route, observation)],
        ),
        [recall_complete(), "__throw__"],
    )

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [route]
    assert report["result"]["resume_seed"]["leaf"]["route"] == route


def test_topic_explicit_seed_keeps_effective_leaf_and_never_replays_after_gates() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    starting = topic_observation(subquestions=[gap], members=[], cards=[])
    first = run_topic(
        topic_input(
            observation=starting,
            seeds=[paper_seed()],
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
        ),
        [
            recall_complete(),
            search_needs_input(),
        ],
    )
    paper_gate = first["result"]["gate"]["gate"]
    book_candidate = next(
        item for item in paper_gate["candidates"] if item["kind"] == "book"
    )
    paper_decision = {
        "material_key": paper_gate["material_key"],
        "operation": paper_gate["operation"],
        "value": {
            "candidates": paper_gate["candidates"],
            "conflicts": paper_gate["conflicts"],
            "selected_candidate": book_candidate,
        },
    }
    routed = run_topic(
        topic_input(
            observation=starting,
            seeds=[paper_seed()],
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
            resume={
                "resume_seed": first["result"]["resume_seed"],
                "userDecision": paper_decision,
            },
        ),
        [recall_complete()],
    )
    assert routed["result"]["terminal"] == "needs_observation"
    assert routed["result"]["routes"] == [{"kind": "book", "slug": "exact-book"}]
    assert routed["result"]["resume_seed"]["member_route"] == {
        "kind": "paper", "slug": "exact-paper"
    }

    book_status = book_observation("exact-book", source_format="pdf", admitted=True)
    structure_gated = run_topic(
        topic_input(
            observation=starting,
            seeds=[paper_seed()],
            children=[
                ({"kind": "paper", "slug": "exact-paper"}, paper_observation("exact-paper")),
                ({"kind": "book", "slug": "exact-book"}, book_status),
            ],
            resume={"resume_seed": routed["result"]["resume_seed"]},
        ),
        [recall_complete(), book_prepare_structure_gate()],
    )

    assert structure_gated["result"]["gate"]["gate"]["kind"] == "book_structure"
    assert structure_gated["result"]["resume_seed"]["leaf"] == routed["result"]["resume_seed"]["leaf"]
    assert structure_gated["result"]["resume_seed"]["member_route"] == {
        "kind": "paper", "slug": "exact-paper"
    }

    structure_gate = structure_gated["result"]["gate"]["gate"]
    structure_finished = run_topic(
        topic_input(
            observation=starting,
            seeds=[paper_seed()],
            children=[
                ({"kind": "paper", "slug": "exact-paper"}, paper_observation("exact-paper")),
                ({"kind": "book", "slug": "exact-book"}, book_observation(
                    "exact-book",
                    source_format="pdf",
                    manifest=True,
                    chapter_inputs=(True, True),
                    chapter_outputs=(True, True),
                    overview=True,
                    admitted=True,
                )),
            ],
            resume={
                "resume_seed": structure_gated["result"]["resume_seed"],
                "userDecision": {
                    "material_key": structure_gate["material_key"],
                    "operation": structure_gate["operation"],
                    "value": book_structure_decision(),
                },
            },
        ),
        [
            recall_complete(),
            audit_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "book", "slug": "exact-book", "role": "evidence"}],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [
        call["request"]["operation"] for call in structure_finished["calls"]
    ]
    assert operations.count("material.search") == 0
    assert operations.count("book.audit") == 1
    assert structure_finished["result"]["terminal"] == "complete"


def test_topic_talk_seed_uses_exact_media_and_unusable_media_enters_seed_gate() -> None:
    talk_status = talk_observation()
    completed = run_topic(
        topic_input(
            max_rounds=0,
            seeds=[talk_seed()],
            children=[({"kind": "talk", "slug": "exact-talk"}, talk_status)],
        ),
        [
            recall_complete(),
            talk_prepare_complete("live"),
            talk_analyse_complete(),
            audit_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "talk", "slug": "exact-talk", "role": "evidence"}],
                action="create",
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )
    operations = [call["request"]["operation"] for call in completed["calls"]]
    assert operations[:4] == [
        "topic.recall",
        "talk.prepare",
        "talk.analyse",
        "talk.audit",
    ]
    assert completed["result"]["terminal"] == "complete"

    unusable = talk_observation()
    exact_media = next(
        fact
        for fact in unusable["facts"]["media"]
        if fact["path"] == TALK_IDENTITY["media"]
    )
    exact_media["present"] = exact_media["usable"] = False
    other_media = next(
        fact for fact in unusable["facts"]["media"] if fact is not exact_media
    )
    other_media["present"] = other_media["usable"] = True
    gated = run_topic(
        topic_input(
            max_rounds=0,
            seeds=[talk_seed()],
            children=[({"kind": "talk", "slug": "exact-talk"}, unusable)],
        ),
        [recall_complete()],
    )
    assert gated["result"]["gate"]["kind"] == "topic_seed"


def test_topic_checkpoint_unknown_stops_queue_and_status_resume_never_replays_writer() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    starting = topic_observation(subquestions=[gap], members=[], cards=[])
    opening = steer_complete(
        signal="continue",
        subquestions=[gap],
        demands=[demand()],
        tasks=[web_task()],
    )
    stopped = run_topic(
        topic_input(
            observation=starting,
            children=[(
                {"kind": "paper", "slug": "exact-paper"},
                paper_observation("exact-paper"),
            )],
        ),
        [
            recall_complete(),
            opening,
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
            "__throw__",
        ],
    )

    stopped_ops = [call["request"]["operation"] for call in stopped["calls"]]
    assert stopped_ops[-1] == "topic.steer"
    assert "topic.webcard" not in stopped_ops
    assert stopped["result"]["terminal"] == "needs_observation"
    assert stopped["result"]["routes"] == [{"kind": "topic", "slug": QUERY["slug"]}]

    proved = topic_observation(
        subquestions=[SUBQUESTION], members=[paper_member()], cards=[]
    )
    resumed = run_topic(
        topic_input(
            observation=proved,
            resume={"resume_seed": stopped["result"]["resume_seed"]},
        ),
        [
            recall_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )
    resumed_ops = [call["request"]["operation"] for call in resumed["calls"]]
    assert resumed_ops[0:2] == ["topic.recall", "topic.steer"]
    assert not any(operation.startswith("paper.") for operation in resumed_ops)
    assert resumed["result"]["terminal"] == "complete"


def test_topic_changed_canonical_seed_checkpoint_resume_skips_original_seed() -> None:
    seed = paper_seed()
    seed["seed"]["requested_slug"] = "request-paper"
    request_status = paper_observation("request-paper")
    stopped = run_topic(
        topic_input(
            seeds=[seed],
            children=[(
                {"kind": "paper", "slug": "request-paper"},
                request_status,
            )],
        ),
        [
            recall_complete(),
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
            "__throw__",
        ],
    )

    assert stopped["result"]["terminal"] == "needs_observation"
    assert stopped["result"]["routes"] == [
        {"kind": "topic", "slug": QUERY["slug"]}
    ]
    capsule = stopped["result"]["resume_seed"]
    assert capsule["item"] == "member"
    assert capsule["ref"]["slug"] == "exact-paper"
    assert capsule["source_route"] == {"kind": "paper", "slug": "request-paper"}

    proved = topic_observation(
        subquestions=[SUBQUESTION], members=[paper_member()], cards=[]
    )
    resumed = run_topic(
        topic_input(
            observation=proved,
            seeds=[seed],
            children=[(
                {"kind": "paper", "slug": "request-paper"},
                request_status,
            )],
            resume={"resume_seed": capsule},
        ),
        [
            recall_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in resumed["calls"]]
    assert operations[:2] == ["topic.recall", "topic.steer"]
    assert not any(operation.startswith("paper.") for operation in operations)
    assert "material.search" not in operations
    assert resumed["result"]["terminal"] == "complete"


def test_topic_resumed_material_work_reuses_resolved_owner_for_refined_demand() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    starting = topic_observation(subquestions=[gap], members=[], cards=[])
    requested = demand(requested_slug="request-paper")
    first = run_topic(
        topic_input(
            observation=starting,
            children=[(
                {"kind": "paper", "slug": "request-paper"},
                paper_observation("request-paper"),
            )],
        ),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                demands=[requested],
            ),
            search_needs_input(),
        ],
    )
    gate = first["result"]["gate"]["gate"]
    selected = next(item for item in gate["candidates"] if item["kind"] == "paper")
    refined = deepcopy(requested)
    refined["query"] = "refine the exact paper evidence"
    refined["reason"] = "The same resolved owner still fills this exact gap."

    resumed = run_topic(
        topic_input(
            observation=starting,
            children=[(
                {"kind": "paper", "slug": "request-paper"},
                paper_observation("request-paper"),
            )],
            resume={
                "resume_seed": first["result"]["resume_seed"],
                "userDecision": {
                    "material_key": gate["material_key"],
                    "operation": gate["operation"],
                    "value": {
                        "candidates": gate["candidates"],
                        "conflicts": gate["conflicts"],
                        "selected_candidate": selected,
                    },
                },
            },
        ),
        [
            recall_complete(),
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                demands=[refined],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in resumed["calls"]]
    assert operations.count("material.search") == 1
    assert resumed["result"]["terminal"] == "complete"


def test_topic_empty_webcard_marks_only_fingerprint_and_skips_checkpoint() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    observation = topic_observation(
        subquestions=[gap], members=[paper_member()], cards=[]
    )
    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                tasks=[web_task()],
            ),
            webcard_complete(empty=True),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations.count("topic.steer") == 1
    assert operations.count("topic.webcard") == 1
    assert report["result"]["terminal"] == "complete"

    admitted = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                tasks=[web_task()],
            ),
            webcard_complete(),
            steer_complete(
                signal="saturated",
                subquestions=[SUBQUESTION],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                cards=["exact-card"],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )
    admitted_ops = [call["request"]["operation"] for call in admitted["calls"]]
    assert admitted_ops[2:4] == ["topic.webcard", "topic.steer"]
    checkpoint = admitted["calls"][3]["request"]
    assert checkpoint["cards"] == [
        {
            "slug": "exact-card",
            "path": f"vault/topics/{QUERY['slug']}/cards/exact-card.md",
            "subq": "sq-one",
            "title": "Exact Card",
        }
    ]
    assert admitted["result"]["terminal"] == "complete"


def test_topic_exact_duplicate_empty_web_task_runs_writer_once() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    observation = topic_observation(
        subquestions=[gap], members=[paper_member()], cards=[]
    )
    task = web_task()
    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                tasks=[task, deepcopy(task)],
            ),
            webcard_complete(empty=True),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations.count("topic.webcard") == 1
    assert report["result"]["terminal"] == "complete"


def test_topic_existing_card_can_be_checkpointed_into_a_new_subquestion() -> None:
    second = {
        "id": "sq-two",
        "question": "Where does the public mechanism appear?",
        "coverage": "gap",
        "channel": "web",
        "theory_used": 0,
    }
    existing_card = {
        "slug": "exact-card",
        "subq": "sq-one",
        "title": "Exact Card",
        "artifact": artifact(
            f"vault/topics/{QUERY['slug']}/cards/exact-card.md", True
        ),
    }
    observation = topic_observation(
        subquestions=[SUBQUESTION, second],
        members=[paper_member()],
        cards=[existing_card],
    )
    task = web_task()
    task["subq"] = "sq-two"
    opening = steer_complete(
        signal="continue",
        subquestions=[SUBQUESTION, second],
        items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
        cards=["exact-card"],
        tasks=[task],
    )
    covered_second = {**second, "coverage": "covered"}
    checkpoint = steer_complete(
        signal="saturated",
        subquestions=[SUBQUESTION, covered_second],
        items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
        cards=["exact-card"],
    )
    checkpoint["subquestions"][1]["cards"] = ["exact-card"]

    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            opening,
            checkpoint,
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    operations = [call["request"]["operation"] for call in report["calls"]]
    assert operations[:3] == ["topic.recall", "topic.steer", "topic.steer"]
    assert "topic.webcard" not in operations
    assert report["calls"][2]["request"]["cards"] == [
        {
            "slug": "exact-card",
            "path": f"vault/topics/{QUERY['slug']}/cards/exact-card.md",
            "subq": "sq-one",
            "title": "Exact Card",
        },
        {
            "slug": "exact-card",
            "path": f"vault/topics/{QUERY['slug']}/cards/exact-card.md",
            "subq": "sq-two",
            "title": "Exact Card",
        },
    ]
    assert report["result"]["terminal"] == "complete"


def test_topic_round_limit_returns_ordered_closed_pending_work_after_audit() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    observation = topic_observation(
        subquestions=[gap], members=[paper_member()], cards=[]
    )
    report = run_topic(
        topic_input(observation=observation, max_rounds=0),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                demands=[demand(requested_slug="next-paper")],
                tasks=[web_task()],
            ),
            audit_complete(),
            synthesis_complete(),
            synthesis_complete(),
            audit_complete(),
            audit_complete(),
        ],
    )

    assert report["result"]["terminal"] == "incomplete"
    assert report["result"]["issue"]["code"] == "topic.round_limit"
    assert report["result"]["pending_work"] == [
        {
            "kind": "material",
            "material_kind": "paper",
            "requested_slug": "next-paper",
            "subq": "sq-one",
            "role": "evidence",
            "fingerprint": report["result"]["pending_work"][0]["fingerprint"],
        },
        {
            "kind": "webcard",
            "card_slug": "exact-card",
            "subq": "sq-one",
            "fingerprint": report["result"]["pending_work"][1]["fingerprint"],
        },
    ]


def test_topic_needs_seeds_is_direct_gate_with_receipt_ordered_gaps() -> None:
    gap = {**SUBQUESTION, "coverage": "thin"}
    observation = topic_observation(
        subquestions=[gap], members=[paper_member()], cards=[]
    )
    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="needs_seeds",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                suggested=["find a comparative case"],
            ),
        ],
    )

    assert report["result"]["terminal"] == "needs_input"
    assert report["result"]["gate"] == {
        "kind": "topic_needs_seeds",
        "operation": "topic.steer",
        "question": "Add explicit Topic seeds or revise the outline before continuing.",
        "suggested_queries": ["find a comparative case"],
        "uncovered_subquestions": ["sq-one"],
    }


def test_topic_rejects_exact_writer_collision_before_first_child() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    observation = topic_observation(
        subquestions=[gap], members=[paper_member()], cards=[]
    )
    report = run_topic(
        topic_input(observation=observation),
        [
            recall_complete(),
            steer_complete(
                signal="continue",
                subquestions=[gap],
                items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}],
                demands=[demand(query="first query"), demand(query="second query")],
            ),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "topic.recall",
        "topic.steer",
    ]
    assert report["result"]["issue"]["code"] == "workflow.incoherent_complete"
