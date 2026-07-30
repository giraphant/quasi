"""Strict module/mock tests for the bounded Topic vertical slices.

These tests execute ``processTopic`` with the real shared runtime, scripted
Agent replies, and an injected router stub.  They deliberately do not invoke
Claude Workflow, Pi, Codex, the filesystem, or the network.

The contract frozen here is intentionally narrow: ``maxRounds=0`` selects a
bounded, recall-only graph, while explicit ``strict=true`` plus
``maxRounds=1`` adds one Book/Paper discovery and shared Material Loop round.
Both admit only exact typed receipts, use one no-replay writer invocation per
operation, and expose the authoritative ``research_receipt`` while retaining
the legacy result adapter.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOPIC_MODULE = PLUGIN_ROOT / "scripts/workflows" / "research" / "topic.mjs"
RUNTIME_MODULE = PLUGIN_ROOT / "scripts/workflows" / "runtime.mjs"

RESEARCH_RECEIPT_VERSION = "quasi.research.topic.receipt/0.1"
TOPIC = "exact-topic"
DESCRIPTION = "A bounded study of exact Topic contracts"


NODE_HARNESS = r"""
import { processTopic } from __TOPIC_URI__
import { createRuntime } from __RUNTIME_URI__

const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const logs = []
const missing = []
const indexes = new Map()
const barriers = new Map()
let clock = 0

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function balancedObject(text, start) {
  let depth = 0
  let quoted = false
  let escaped = false
  for (let index = start; index < text.length; index += 1) {
    const char = text[index]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === "\\") escaped = true
      else if (char === '"') quoted = false
      continue
    }
    if (char === '"') {
      quoted = true
      continue
    }
    if (char === "{") depth += 1
    if (char === "}") {
      depth -= 1
      if (depth === 0) return text.slice(start, index + 1)
    }
  }
  return null
}

function parseRequest(prompt) {
  const text = String(prompt)
  const fenced = [...text.matchAll(/```json\s*([\s\S]*?)```/g)]
  for (const match of fenced) {
    try {
      const parsed = JSON.parse(match[1])
      if (parsed && typeof parsed === "object") return parsed
    } catch {}
  }
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== "{") continue
    const candidate = balancedObject(text, index)
    if (!candidate) continue
    try {
      const parsed = JSON.parse(candidate)
      if (
        parsed &&
        typeof parsed === "object" &&
        (parsed.operation || parsed.topic_key || parsed.schema_version)
      ) return parsed
    } catch {}
  }
  return null
}

function operationOf(_prompt, request) {
  return typeof request?.operation === "string" ? request.operation : null
}

async function waitAtBarrier(step) {
  if (!step.barrier) return
  const name = String(step.barrier.name)
  const size = Number(step.barrier.size)
  const rank = Number(step.barrier.rank)
  let group = barriers.get(name)
  if (!group) {
    group = { size, arrivals: [] }
    barriers.set(name, group)
  }
  if (group.size !== size) throw new Error(`barrier ${name} size mismatch`)
  await new Promise(resolve => {
    group.arrivals.push({ rank, resolve })
    if (group.arrivals.length === group.size) {
      for (const arrival of [...group.arrivals].sort(
        (left, right) => left.rank - right.rank
      )) arrival.resolve()
    }
  })
}

async function scriptedStep(route, step, call) {
  if (!step) {
    missing.push(call.id)
    call.end = ++clock
    return null
  }
  await waitAtBarrier(step)
  call.end = ++clock
  if (step.throw) throw new Error(String(step.throw))
  return clone(step.result)
}

async function agent(prompt, options = {}) {
  const request = parseRequest(prompt)
  const operation = operationOf(prompt, request)
  // A strict Topic Operation must carry its key in a machine-readable request.
  const route = operation || "__missing_operation__"
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    id: `${route}#${occurrence + 1}`,
    type: "agent",
    route,
    occurrence: occurrence + 1,
    operation,
    label: options.label || null,
    phase: options.phase || null,
    agent_type: options.agentType || null,
    prompt: String(prompt),
    request,
    schema: options.schema || null,
    start: ++clock,
    end: null,
  }
  trace.push(call)
  const steps = config.responses[route]
  return scriptedStep(route, steps && steps[occurrence], call)
}

async function router(kind, args, options = {}) {
  const route = `router:${kind}`
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    id: `${route}#${occurrence + 1}`,
    type: "router",
    route,
    occurrence: occurrence + 1,
    kind,
    args: clone(args),
    options: clone(options),
    start: ++clock,
    end: null,
  }
  trace.push(call)
  const steps = config.router[route]
  return scriptedStep(route, steps && steps[occurrence], call)
}

const primitives = {
  agent,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: name => phases.push(String(name)),
  log: message => logs.push(String(message)),
}
const runtime = createRuntime(primitives)
const requests = config.requests || [{ slug: config.slug, meta: config.meta }]
const result = config.parallel_requests
  ? await Promise.all(requests.map(request =>
      processTopic(runtime, router, request.slug, request.meta)
    ))
  : await processTopic(runtime, router, requests[0].slug, requests[0].meta)

const unused = {}
for (const [route, steps] of Object.entries({
  ...config.responses,
  ...config.router,
})) {
  const remaining = steps.length - (indexes.get(route) || 0)
  if (remaining !== 0) unused[route] = remaining
}
process.stdout.write(JSON.stringify({
  result,
  trace,
  phases,
  logs,
  missing,
  unused,
}))
"""


def reply(
    result: Any,
    *,
    barrier: tuple[str, int, int] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {"result": result}
    if barrier is not None:
        name, size, rank = barrier
        step["barrier"] = {"name": name, "size": size, "rank": rank}
    return step


def run_topic(
    tmp_path: Path,
    *,
    slug: str = TOPIC,
    meta: dict[str, Any] | None = None,
    responses: dict[str, list[dict[str, Any]]] | None = None,
    router: dict[str, list[dict[str, Any]]] | None = None,
    requests: list[dict[str, Any]] | None = None,
    parallel_requests: bool = False,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace(
        "__TOPIC_URI__", json.dumps(TOPIC_MODULE.as_uri())
    ).replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
    config = {
        "slug": slug,
        "meta": meta or topic_meta(),
        "responses": responses or {},
        "router": router or {},
        "requests": requests,
        "parallel_requests": parallel_requests,
    }
    try:
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script, json.dumps(config)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Topic graph did not satisfy a deterministic barrier within 20s")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["missing"] == [], report
    if not allow_unused:
        assert report["unused"] == {}, report
    return report


def topic_meta(**overrides: Any) -> dict[str, Any]:
    value = {
        "desc": DESCRIPTION,
        "maxRounds": 0,
        "maxPerRound": 3,
        "minItems": 1,
        "seeds": ["existing exact materials"],
    }
    value.update(overrides)
    return value


def member(kind: str, slug: str) -> dict[str, str]:
    path = {
        "book": f"vault/books/{slug}/00-overview.md",
        "paper": f"vault/papers/{slug}.md",
        "talk": f"vault/talks/{slug}/talk.md",
    }[kind]
    return {"kind": kind, "slug": slug, "path": path}


def member_key(value: dict[str, str]) -> str:
    return f"{value['kind']}:{value['slug']}"


def recall_receipt(
    items: list[dict[str, str]],
    *,
    topic_slug: str = TOPIC,
    status: str = "succeeded",
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.topic.recall.receipt/0.1",
        "key": "topic.recall",
        "effect": "readonly",
        "status": status,
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "query": DESCRIPTION,
        "max_items": 3,
        "items": [
            {"kind": item["kind"], "slug": item["slug"], "path": item["path"]}
            for item in items
        ],
        "failure": failure,
    }


def steer_receipt(
    *,
    action: str,
    topic_slug: str = TOPIC,
    members: list[dict[str, str]] | None = None,
    output_path: str | None = None,
    status: str = "succeeded",
    signal: str = "continue",
    candidate_demands: list[dict[str, str]] | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = members or []
    return {
        "schema_version": "quasi.operation.topic.steer.receipt/0.1",
        "key": "topic.steer",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "member_refs": values,
        "input_paths": [item["path"] for item in values],
        "output_path": output_path or f"vault/topics/{topic_slug}/02-outline.md",
        "action": action,
        "signal": signal,
        "subquestions": [
            {
                "id": "sq-contract",
                "question": "Which exact materials support the Topic contract?",
                "coverage": "thin",
                "channel": "academic",
                "dossier": False,
                "page": None,
                "theory_used": 0,
                "items": [],
                "cards": [],
            }
        ],
        "candidate_demands": candidate_demands or [],
        "web_tasks": [],
        "dirty": [],
        "suggested_queries": [],
        "failure": failure,
    }


def membership_receipt(
    requested: list[dict[str, str]],
    resolved: list[dict[str, str]] | None = None,
    *,
    topic_slug: str = TOPIC,
    status: str = "succeeded",
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = requested if resolved is None else resolved
    projected = []
    for index, item in enumerate(rows):
        if "requested_slug" in item:
            projected.append(item)
            continue
        request = requested[index] if index < len(requested) else item
        projected.append(
            {
                "kind": item["kind"],
                "requested_slug": request["slug"],
                "resolved_slug": item["slug"],
                "path": item["path"],
                "match": "slug",
            }
        )
    return {
        "schema_version": "quasi.operation.topic.resolve-membership.receipt/0.1",
        "key": "topic.resolve-membership",
        "effect": "readonly",
        "status": status,
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "requests": [
            {"kind": item["kind"], "slug": item["slug"]} for item in requested
        ],
        "resolved": projected,
        "failure": failure,
    }


def paper_candidate(slug: str = "new-paper-2026") -> dict[str, Any]:
    return {
        "kind": "paper",
        "slug": slug,
        "title": "New exact paper",
        "authors": ["Ada Example"],
        "year": 2026,
        "doi": "10.1000/new-paper",
        "oa_url": None,
        "url": None,
        "journal": "Journal of Exact Contracts",
        "confidence": "high",
    }


def discovery_receipt(
    demand: dict[str, str],
    candidate: dict[str, Any],
    *,
    demand_id: str = "r1-d01",
    topic_slug: str = TOPIC,
) -> dict[str, Any]:
    return {
        "schema_version": (
            f"quasi.operation.topic.discover-{demand['kind']}.receipt/0.1"
        ),
        "key": f"topic.discover-{demand['kind']}",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "demand_id": demand_id,
        "demand": demand,
        "candidate": candidate,
        "failure": None,
    }


def paper_child_result(slug: str) -> dict[str, Any]:
    canonical = f"vault/papers/{slug}.md"
    return {
        "slug": slug,
        "status": "ok",
        "material_receipt": {
            "schema_version": "quasi.material-loop.receipt/0.1",
            "material_key": f"paper:{slug}",
            "kind": "paper",
            "id": slug,
            "status": "complete",
            "disposition": "created",
            "stage": "audit",
            "artifacts": [
                {
                    "role": "canonical",
                    "path": canonical,
                    "exists": True,
                    "usable": True,
                    "producer": "paper.analyse",
                }
            ],
            "operations": [{"key": "paper.synthetic"}],
            "audit": {
                "schema_version": (
                    "quasi.operation.paper.audit.agent-receipt/0.1"
                ),
                "key": "paper.audit",
                "effect": "writer",
                "status": "clean",
                "attempt": 1,
                "target_path": canonical,
                "remaining_violations": 0,
                "escalated": [],
            },
            "freshness": {
                "observation": "unknown",
                "basis": "operation-receipts-and-final-audit",
            },
            "warnings": [],
            "failure": None,
            "resume": None,
        },
    }


def failed_paper_child_result(slug: str) -> dict[str, Any]:
    value = paper_child_result(slug)
    value["status"] = "download_failed"
    material = value["material_receipt"]
    material["status"] = "failed"
    material["disposition"] = None
    material["stage"] = "download"
    material["artifacts"] = []
    material["audit"] = None
    material["failure"] = {
        "code": "paper.download_failed",
        "operation_key": "paper.acquire",
        "outcome": "known",
        "retryable": False,
        "message": "all bounded sources failed",
    }
    return value


def synthesis_receipt(
    page: str,
    members: list[dict[str, str]],
    *,
    topic_slug: str = TOPIC,
    action: str = "create",
    status: str = "succeeded",
    output_path: str | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = f"topic.synthesise.{page}"
    filename = "00-overview.md" if page == "overview" else "01-resources.md"
    return {
        "schema_version": f"quasi.operation.{key}.receipt/0.1",
        "key": key,
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "member_refs": members,
        "input_paths": [item["path"] for item in members],
        "outline_path": f"vault/topics/{topic_slug}/02-outline.md",
        "output_path": output_path or f"vault/topics/{topic_slug}/{filename}",
        "artifact_roles": [page],
        "action": action,
        "members_analyzed": len(members),
        "failure": failure,
    }


def audit_receipt(
    target_path: str,
    *,
    topic_slug: str = TOPIC,
    status: str = "clean",
    escalated: list[dict[str, str]] | None = None,
    mutated_paths: list[str] | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = escalated or []
    return {
        "schema_version": "quasi.operation.topic.audit.legacy.receipt/0.1",
        "key": "topic.audit.legacy",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "research_key": f"topic:{topic_slug}",
        "target_path": target_path,
        "remaining_violations": len(diagnostics),
        "escalated": diagnostics,
        "mutated_paths": mutated_paths or [],
        "failure": failure,
    }


def base_responses(
    members: list[dict[str, str]] | None = None,
    *,
    topic_slug: str = TOPIC,
) -> dict[str, list[dict[str, Any]]]:
    values = (
        [
            member("book", "exact-book-2024"),
            member("paper", "exact-paper-2025"),
            member("talk", "exact-talk-2026"),
        ]
        if members is None
        else members
    )
    overview = f"vault/topics/{topic_slug}/00-overview.md"
    resources = f"vault/topics/{topic_slug}/01-resources.md"
    outline = f"vault/topics/{topic_slug}/02-outline.md"
    return {
        "topic.recall": [reply(recall_receipt(values, topic_slug=topic_slug))],
        "topic.steer": [
            reply(steer_receipt(action="create", topic_slug=topic_slug)),
            reply(
                steer_receipt(
                    action="refresh", members=values, topic_slug=topic_slug
                )
            ),
        ],
        "topic.resolve-membership": [
            reply(membership_receipt(values, topic_slug=topic_slug))
        ],
        "topic.synthesise.overview": [
            reply(synthesis_receipt("overview", values, topic_slug=topic_slug))
        ],
        "topic.synthesise.resources": [
            reply(synthesis_receipt("resources", values, topic_slug=topic_slug))
        ],
        "topic.audit.legacy": [
            reply(audit_receipt(overview, topic_slug=topic_slug)),
            reply(audit_receipt(resources, topic_slug=topic_slug)),
            reply(audit_receipt(outline, topic_slug=topic_slug)),
        ],
    }


def calls(report: dict[str, Any], route: str) -> list[dict[str, Any]]:
    return [call for call in report["trace"] if call["route"] == route]


def receipt(result: dict[str, Any]) -> dict[str, Any]:
    value = result["research_receipt"]
    assert value["schema_version"] == RESEARCH_RECEIPT_VERSION
    assert value["research_key"] == f"topic:{result['slug']}"
    assert value["kind"] == "topic"
    assert value["id"] == result["slug"]
    return value


def assert_flat_schema(schema: Any) -> None:
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    for forbidden in ("oneOf", "allOf", "anyOf"):
        assert forbidden not in schema


def test_recall_only_happy_path_is_ordered_by_dependencies_not_clock_time(
    tmp_path: Path,
) -> None:
    members = [
        member("book", "exact-book-2024"),
        member("paper", "exact-paper-2025"),
        member("talk", "exact-talk-2026"),
    ]
    responses = base_responses(members)
    responses["topic.recall"] = [
        reply(recall_receipt(members), barrier=("opening", 2, 1))
    ]
    responses["topic.steer"][0] = reply(
        steer_receipt(action="create"), barrier=("opening", 2, 0)
    )
    responses["topic.synthesise.overview"] = [
        reply(synthesis_receipt("overview", members), barrier=("pages", 2, 1))
    ]
    responses["topic.synthesise.resources"] = [
        reply(synthesis_receipt("resources", members), barrier=("pages", 2, 0))
    ]

    report = run_topic(tmp_path, responses=responses)
    result = report["result"]
    research = receipt(result)
    recall = calls(report, "topic.recall")[0]
    initial, closing = calls(report, "topic.steer")
    resolve = calls(report, "topic.resolve-membership")[0]
    overview = calls(report, "topic.synthesise.overview")[0]
    resources = calls(report, "topic.synthesise.resources")[0]
    audits = calls(report, "topic.audit.legacy")

    assert result["status"] == "ok"
    assert research["status"] == "complete"
    assert research["stage"] == "complete"
    assert research["failure"] is None
    assert research["resume"] is None
    assert result["members"] == members
    assert [
        {
            "member_key": entry["member_key"],
            "kind": entry["kind"],
            "id": entry["id"],
            "path": entry["path"],
        }
        for entry in research["members"]
    ] == [
        {
            "member_key": member_key(item),
            "kind": item["kind"],
            "id": item["slug"],
            "path": item["path"],
        }
        for item in members
    ]
    assert recall["start"] < initial["end"]
    assert initial["start"] < recall["end"]
    assert resolve["start"] > max(recall["end"], initial["end"])
    assert closing["start"] > resolve["end"]
    assert overview["start"] > closing["end"]
    assert resources["start"] > closing["end"]
    assert overview["start"] < resources["end"]
    assert resources["start"] < overview["end"]
    assert len(audits) == 3
    assert all(audit["start"] > max(overview["end"], resources["end"]) for audit in audits)
    assert [audit["request"]["exact_output"] for audit in audits] == [
        f"vault/topics/{TOPIC}/00-overview.md",
        f"vault/topics/{TOPIC}/01-resources.md",
        f"vault/topics/{TOPIC}/02-outline.md",
    ]
    assert not any(call["type"] == "router" for call in report["trace"])
    assert report["phases"] == ["Topic"]
    for call in report["trace"]:
        if call["type"] == "agent":
            assert call["request"]["operation"] == call["route"]
            assert_flat_schema(call["schema"])


@pytest.mark.parametrize(
    ("slug", "meta", "failure_code"),
    [
        ("../escape", topic_meta(), "topic.slug_invalid"),
        ("Exact Topic", topic_meta(), "topic.slug_invalid"),
        (TOPIC, topic_meta(maxPerRound=0), "topic.budget_invalid"),
        (TOPIC, topic_meta(maxPerRound=99), "topic.budget_invalid"),
        (TOPIC, topic_meta(maxPerRound=1.5), "topic.budget_invalid"),
        (TOPIC, topic_meta(minItems=0), "topic.budget_invalid"),
        (TOPIC, topic_meta(minItems=99), "topic.budget_invalid"),
    ],
)
def test_strict_identity_and_bounded_recall_budget_precede_agents(
    tmp_path: Path,
    slug: str,
    meta: dict[str, Any],
    failure_code: str,
) -> None:
    report = run_topic(tmp_path, slug=slug, meta=meta)
    assert report["trace"] == []
    result = report["result"]
    assert result["status"] == "blocked"
    research = receipt(result)
    assert research["status"] == "blocked"
    assert research["stage"] == "identity"
    assert research["failure"]["code"] == failure_code
    assert research["resume"] == {"operation_key": "topic.reconcile"}


def test_zero_rounds_is_the_explicit_strict_recall_only_selector() -> None:
    source = TOPIC_MODULE.read_text(encoding="utf-8")

    assert "meta.maxRounds === 0" in source
    assert "meta.strict === true && meta.maxRounds === 1" in source
    assert "return processTopicStrict(runtime, router, slug, meta)" in source
    assert "return processTopicLegacy(runtime, router, slug, meta)" in source


def test_one_round_strict_material_router_admits_only_exact_child_receipt(
    tmp_path: Path,
) -> None:
    recalled = member("paper", "existing-paper-2025")
    candidate = paper_candidate()
    discovered = member("paper", candidate["slug"])
    demand = {
        "kind": "paper",
        "query": "one exact new paper",
        "subq": "sq-contract",
        "role": "evidence",
        "reason": "fill the exact evidence gap",
    }
    members = [recalled, discovered]
    responses = {
        "topic.recall": [reply(recall_receipt([recalled]))],
        "topic.steer": [
            reply(steer_receipt(action="create")),
            reply(
                steer_receipt(
                    action="refresh",
                    members=[recalled],
                    candidate_demands=[demand],
                )
            ),
            reply(steer_receipt(action="refresh", members=members)),
        ],
        "topic.resolve-membership": [
            reply(membership_receipt([recalled])),
            reply(membership_receipt([discovered])),
        ],
        "topic.discover-paper": [
            reply(discovery_receipt(demand, candidate))
        ],
        "topic.synthesise.overview": [
            reply(synthesis_receipt("overview", members))
        ],
        "topic.synthesise.resources": [
            reply(synthesis_receipt("resources", members))
        ],
        "topic.audit.legacy": [
            reply(audit_receipt(f"vault/topics/{TOPIC}/00-overview.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/01-resources.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/02-outline.md")),
        ],
    }
    report = run_topic(
        tmp_path,
        meta=topic_meta(
            strict=True,
            maxRounds=1,
            maxCardsPerRound=0,
        ),
        responses=responses,
        router={
            "router:paper": [reply(paper_child_result(candidate["slug"]))]
        },
    )
    result = report["result"]
    assert result["status"] == "ok"
    assert result["rounds"] == 1
    assert result["recalled"] == 1
    assert result["members"] == members
    assert receipt(result)["status"] == "complete"
    assert receipt(result)["material_results"][0]["status"] == "complete"
    assert len(calls(report, "topic.discover-paper")) == 1
    assert len(calls(report, "router:paper")) == 1
    assert not any("webcard" in call["route"] for call in report["trace"])
    assert not any("dossier" in call["route"] for call in report["trace"])


def test_one_round_can_start_from_discovery_when_recall_is_empty(
    tmp_path: Path,
) -> None:
    candidate = paper_candidate("discovery-only-paper-2026")
    discovered = member("paper", candidate["slug"])
    demand = {
        "kind": "paper",
        "query": "discover one exact paper",
        "subq": "sq-contract",
        "role": "evidence",
        "reason": "the vault has no recalled material",
    }
    responses = {
        "topic.recall": [reply(recall_receipt([]))],
        "topic.steer": [
            reply(
                steer_receipt(
                    action="create",
                    candidate_demands=[demand],
                )
            ),
            reply(
                steer_receipt(
                    action="refresh",
                    members=[discovered],
                )
            ),
        ],
        "topic.discover-paper": [
            reply(discovery_receipt(demand, candidate))
        ],
        "topic.resolve-membership": [
            reply(membership_receipt([discovered]))
        ],
        "topic.synthesise.overview": [
            reply(synthesis_receipt("overview", [discovered]))
        ],
        "topic.synthesise.resources": [
            reply(synthesis_receipt("resources", [discovered]))
        ],
        "topic.audit.legacy": [
            reply(audit_receipt(f"vault/topics/{TOPIC}/00-overview.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/01-resources.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/02-outline.md")),
        ],
    }
    report = run_topic(
        tmp_path,
        meta=topic_meta(
            strict=True,
            maxRounds=1,
            maxCardsPerRound=0,
        ),
        responses=responses,
        router={
            "router:paper": [
                reply(paper_child_result(candidate["slug"]))
            ]
        },
    )

    result = report["result"]
    assert result["status"] == "ok"
    assert result["recalled"] == 0
    assert result["members"] == [discovered]
    assert receipt(result)["status"] == "complete"
    assert len(calls(report, "topic.resolve-membership")) == 1
    assert len(calls(report, "topic.steer")) == 2


def test_malformed_discovery_receipt_blocks_before_material_router(
    tmp_path: Path,
) -> None:
    recalled = member("paper", "existing-paper-2025")
    candidate = paper_candidate()
    demand = {
        "kind": "paper",
        "query": "one exact new paper",
        "subq": "sq-contract",
        "role": "evidence",
        "reason": "fill the exact evidence gap",
    }
    malformed = discovery_receipt(demand, candidate)
    malformed["demand_id"] = "r1-foreign"
    responses = {
        "topic.recall": [reply(recall_receipt([recalled]))],
        "topic.steer": [
            reply(steer_receipt(action="create")),
            reply(
                steer_receipt(
                    action="refresh",
                    members=[recalled],
                    candidate_demands=[demand],
                )
            ),
        ],
        "topic.resolve-membership": [
            reply(membership_receipt([recalled]))
        ],
        "topic.discover-paper": [reply(malformed)],
    }
    report = run_topic(
        tmp_path,
        meta=topic_meta(
            strict=True,
            maxRounds=1,
            maxCardsPerRound=0,
        ),
        responses=responses,
    )

    result = report["result"]
    assert result["status"] == "blocked"
    assert receipt(result)["stage"] == "discovery"
    assert receipt(result)["failure"]["code"] == (
        "topic.discovery_receipt_invalid"
    )
    assert calls(report, "router:paper") == []
    assert len(calls(report, "topic.resolve-membership")) == 1


def test_failed_child_is_excluded_and_clean_recalled_corpus_is_partial(
    tmp_path: Path,
) -> None:
    recalled = member("paper", "existing-paper-2025")
    candidate = paper_candidate()
    discovered = member("paper", candidate["slug"])
    demand = {
        "kind": "paper",
        "query": "one exact new paper",
        "subq": "sq-contract",
        "role": "evidence",
        "reason": "fill the exact evidence gap",
    }
    responses = {
        "topic.recall": [reply(recall_receipt([recalled]))],
        "topic.steer": [
            reply(steer_receipt(action="create")),
            reply(
                steer_receipt(
                    action="refresh",
                    members=[recalled],
                    candidate_demands=[demand],
                )
            ),
            reply(steer_receipt(action="refresh", members=[recalled])),
        ],
        "topic.resolve-membership": [
            reply(membership_receipt([recalled])),
            reply(membership_receipt([discovered])),
        ],
        "topic.discover-paper": [
            reply(discovery_receipt(demand, candidate))
        ],
        "topic.synthesise.overview": [
            reply(synthesis_receipt("overview", [recalled]))
        ],
        "topic.synthesise.resources": [
            reply(synthesis_receipt("resources", [recalled]))
        ],
        "topic.audit.legacy": [
            reply(audit_receipt(f"vault/topics/{TOPIC}/00-overview.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/01-resources.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/02-outline.md")),
        ],
    }
    report = run_topic(
        tmp_path,
        meta=topic_meta(
            strict=True,
            maxRounds=1,
            maxCardsPerRound=0,
        ),
        responses=responses,
        router={
            "router:paper": [
                reply(failed_paper_child_result(candidate["slug"]))
            ]
        },
    )

    result = report["result"]
    research = receipt(result)
    assert result["status"] == "ok"
    assert result["members"] == [recalled]
    assert research["status"] == "partial"
    assert research["material_results"][0]["status"] == "failed"
    assert calls(report, "topic.synthesise.overview")[0]["request"][
        "members"
    ] == [recalled]


def test_duplicate_demands_resolving_to_one_identity_dispatch_one_material(
    tmp_path: Path,
) -> None:
    recalled = member("paper", "existing-paper-2025")
    candidate = paper_candidate()
    discovered = member("paper", candidate["slug"])
    demands = [
        {
            "kind": "paper",
            "query": "first query for the same paper",
            "subq": "sq-contract",
            "role": "evidence",
            "reason": "first evidence gap",
        },
        {
            "kind": "paper",
            "query": "second query for the same paper",
            "subq": "sq-contract",
            "role": "theory",
            "reason": "second framing gap",
        },
    ]
    members = [recalled, discovered]
    responses = {
        "topic.recall": [reply(recall_receipt([recalled]))],
        "topic.steer": [
            reply(steer_receipt(action="create")),
            reply(
                steer_receipt(
                    action="refresh",
                    members=[recalled],
                    candidate_demands=demands,
                )
            ),
            reply(steer_receipt(action="refresh", members=members)),
        ],
        "topic.resolve-membership": [
            reply(membership_receipt([recalled])),
            reply(membership_receipt([discovered, discovered])),
        ],
        "topic.discover-paper": [
            reply(discovery_receipt(demands[0], candidate)),
            reply(
                discovery_receipt(
                    demands[1],
                    candidate,
                    demand_id="r1-d02",
                )
            ),
        ],
        "topic.synthesise.overview": [
            reply(synthesis_receipt("overview", members))
        ],
        "topic.synthesise.resources": [
            reply(synthesis_receipt("resources", members))
        ],
        "topic.audit.legacy": [
            reply(audit_receipt(f"vault/topics/{TOPIC}/00-overview.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/01-resources.md")),
            reply(audit_receipt(f"vault/topics/{TOPIC}/02-outline.md")),
        ],
    }
    report = run_topic(
        tmp_path,
        meta=topic_meta(
            strict=True,
            maxRounds=1,
            maxCardsPerRound=0,
        ),
        responses=responses,
        router={
            "router:paper": [
                reply(paper_child_result(candidate["slug"]))
            ]
        },
    )

    assert report["result"]["members"] == members
    assert len(calls(report, "topic.discover-paper")) == 2
    assert len(calls(report, "router:paper")) == 1
    assert len(receipt(report["result"])["material_results"]) == 1


def test_operation_receipts_are_bound_to_the_requested_topic_identity(
    tmp_path: Path,
) -> None:
    slug = "other-exact-topic"
    members = [member("talk", "exact-talk-2026")]
    report = run_topic(
        tmp_path,
        slug=slug,
        responses=base_responses(members, topic_slug=slug),
    )

    assert receipt(report["result"])["status"] == "complete"
    for call in report["trace"]:
        if call["type"] != "agent":
            continue
        if call["route"] == "topic.audit.legacy":
            assert call["request"]["exact_output"].startswith(
                f"vault/topics/{slug}/"
            )
        else:
            assert call["request"]["research_key"] == f"topic:{slug}"


def test_foreign_topic_key_in_a_readonly_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    responses = base_responses(members)
    responses["topic.recall"][0]["result"]["research_key"] = "topic:foreign"
    responses["topic.steer"] = [responses["topic.steer"][0]]
    responses.pop("topic.resolve-membership")
    responses.pop("topic.synthesise.overview")
    responses.pop("topic.synthesise.resources")
    responses.pop("topic.audit.legacy")
    report = run_topic(tmp_path, responses=responses)

    research = receipt(report["result"])
    assert report["result"]["status"] == "blocked"
    assert research["status"] == "blocked"
    assert research["stage"] == "recall"
    assert research["failure"]["operation_key"] == "topic.recall"
    assert research["failure"]["outcome"] == "unknown"
    assert research["resume"] == {"operation_key": "topic.reconcile"}


def test_membership_receipt_admits_only_exact_canonical_member_refs(
    tmp_path: Path,
) -> None:
    members = [
        member("book", "exact-book-2024"),
        member("paper", "exact-paper-2025"),
        member("talk", "exact-talk-2026"),
    ]
    responses = base_responses(members)
    report = run_topic(tmp_path, responses=responses)

    resolve = calls(report, "topic.resolve-membership")[0]
    assert resolve["request"]["requests"] == [
        {"kind": entry["kind"], "slug": entry["slug"]} for entry in members
    ]
    for page in ("overview", "resources"):
        synth = calls(report, f"topic.synthesise.{page}")[0]
        assert synth["request"]["members"] == members
        assert synth["request"]["input_paths"] == [
            entry["path"] for entry in members
        ]


@pytest.mark.parametrize(
    "resolved",
    [
        [
            {
                **member("book", "exact-book-2024"),
                "path": "vault/books/exact-book-2024/01-chapter.md",
            }
        ],
        [member("paper", "exact-book-2024")],
        [member("book", "exact-book-2024"), member("book", "exact-book-2024")],
    ],
)
def test_membership_path_or_identity_drift_fails_closed(
    tmp_path: Path,
    resolved: list[dict[str, str]],
) -> None:
    requested = [member("book", "exact-book-2024")]
    responses = {
        "topic.recall": [reply(recall_receipt(requested))],
        "topic.steer": [reply(steer_receipt(action="create"))],
        "topic.resolve-membership": [reply(membership_receipt(requested, resolved))],
    }
    report = run_topic(tmp_path, responses=responses)

    result = report["result"]
    assert result["status"] == "blocked"
    research = receipt(result)
    assert research["stage"] == "membership"
    assert research["failure"]["code"] == "topic.membership_receipt_invalid"
    assert research["resume"] == {"operation_key": "topic.reconcile"}
    assert calls(report, "topic.synthesise.overview") == []
    assert calls(report, "topic.synthesise.resources") == []


def test_readonly_unknown_is_retried_once_before_strict_receipt_is_used(
    tmp_path: Path,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    responses = base_responses(members)
    responses["topic.recall"] = [reply(None), reply(recall_receipt(members))]
    report = run_topic(tmp_path, responses=responses)

    assert len(calls(report, "topic.recall")) == 2
    assert receipt(report["result"])["status"] == "complete"


def test_readonly_retry_exhaustion_blocks_after_two_unknown_outcomes(
    tmp_path: Path,
) -> None:
    responses = {
        "topic.recall": [reply(None), reply(None)],
        "topic.steer": [reply(steer_receipt(action="create"))],
    }
    report = run_topic(tmp_path, responses=responses)

    research = receipt(report["result"])
    assert report["result"]["status"] == "blocked"
    assert research["status"] == "blocked"
    assert research["stage"] == "recall"
    assert research["failure"]["operation_key"] == "topic.recall"
    assert research["failure"]["outcome"] == "unknown"
    assert research["resume"] == {"operation_key": "topic.reconcile"}
    assert len(calls(report, "topic.recall")) == 2
    assert len(calls(report, "topic.steer")) == 1


@pytest.mark.parametrize(
    ("writer", "bad"),
    [
        ("topic.steer", None),
        ("topic.steer", {"status": "cancelled"}),
        ("topic.steer", {"status": "succeeded"}),
        (
            "topic.steer",
            steer_receipt(action="create", output_path="vault/topics/foreign/02-outline.md"),
        ),
        ("topic.synthesise.overview", None),
        ("topic.synthesise.overview", {"status": "cancelled"}),
        ("topic.synthesise.overview", {"status": "succeeded"}),
        (
            "topic.synthesise.overview",
            synthesis_receipt(
                "overview",
                [member("paper", "exact-paper-2025")],
                output_path="vault/topics/foreign/00-overview.md",
            ),
        ),
        ("topic.synthesise.resources", None),
        ("topic.synthesise.resources", {"status": "cancelled"}),
        ("topic.synthesise.resources", {"status": "succeeded"}),
        (
            "topic.synthesise.resources",
            synthesis_receipt(
                "resources",
                [member("paper", "exact-paper-2025")],
                output_path="vault/topics/foreign/01-resources.md",
            ),
        ),
        ("topic.audit.legacy", None),
        ("topic.audit.legacy", {"status": "cancelled"}),
        ("topic.audit.legacy", {"status": "clean"}),
        (
            "topic.audit.legacy",
            audit_receipt("vault/topics/foreign/00-overview.md"),
        ),
    ],
)
def test_each_writer_unknown_or_invalid_outcome_blocks_without_replay(
    tmp_path: Path,
    writer: str,
    bad: dict[str, Any] | None,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    responses = base_responses(members)
    if writer == "topic.steer":
        responses[writer] = [reply(bad)]
        responses.pop("topic.resolve-membership")
        responses.pop("topic.synthesise.overview")
        responses.pop("topic.synthesise.resources")
        responses.pop("topic.audit.legacy")
    elif writer.startswith("topic.synthesise"):
        responses[writer] = [reply(bad)]
        responses.pop("topic.audit.legacy")
    else:
        responses[writer][0] = reply(bad)

    report = run_topic(tmp_path, responses=responses)
    result = report["result"]
    research = receipt(result)
    assert result["status"] == "blocked"
    assert research["status"] == "blocked"
    assert research["failure"]["operation_key"] == writer
    assert research["failure"]["outcome"] == "unknown"
    assert research["failure"]["retryable"] is False
    assert research["resume"] == {"operation_key": "topic.reconcile"}
    if writer == "topic.audit.legacy":
        expected_target = f"vault/topics/{TOPIC}/00-overview.md"
        assert len(
            [
                call
                for call in calls(report, writer)
                if call["request"]["exact_output"] == expected_target
            ]
        ) == 1
        # The three initial exact audits may already be in flight together, but
        # a terminal unknown outcome must not cause repair or re-audit work.
        assert len(calls(report, writer)) == 3
        assert len(calls(report, "topic.steer")) == 2
        assert len(calls(report, "topic.synthesise.overview")) == 1
        assert len(calls(report, "topic.synthesise.resources")) == 1
    else:
        assert len(calls(report, writer)) == 1


def test_foreign_audit_diagnostic_never_guesses_a_writer_owner(
    tmp_path: Path,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    responses = base_responses(members)
    foreign = {
        "path": "vault/topics/foreign/00-overview.md",
        "kind": "foreign_owner",
        "reason": "outside Topic exact outputs",
    }
    responses["topic.audit.legacy"][0] = reply(
        audit_receipt(
            f"vault/topics/{TOPIC}/00-overview.md",
            status="partial",
            escalated=[foreign],
        )
    )
    report = run_topic(tmp_path, responses=responses)

    result = report["result"]
    research = receipt(result)
    assert result["status"] == "audit_escalated"
    assert research["status"] == "failed"
    assert research["failure"]["code"] == "topic.repair_owner_unknown"
    assert len(calls(report, "topic.synthesise.overview")) == 1
    assert len(calls(report, "topic.synthesise.resources")) == 1
    assert len(calls(report, "topic.audit.legacy")) == 3


@pytest.mark.parametrize(
    ("page", "writer"),
    [
        ("overview", "topic.synthesise.overview"),
        ("resources", "topic.synthesise.resources"),
        ("outline", "topic.steer"),
    ],
)
def test_one_exact_audit_diagnostic_repairs_its_single_owner_then_reaudits_once(
    tmp_path: Path,
    page: str,
    writer: str,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    filename = {
        "overview": "00-overview.md",
        "resources": "01-resources.md",
        "outline": "02-outline.md",
    }[page]
    target = f"vault/topics/{TOPIC}/{filename}"
    diagnostic = {
        "path": target,
        "kind": "section_shape",
        "reason": f"{page} needs semantic producer repair",
    }
    responses = base_responses(members)
    if page in {"overview", "resources"}:
        responses[writer] = [
            reply(synthesis_receipt(page, members)),
            reply(synthesis_receipt(page, members, action="repair")),
        ]
    else:
        responses["topic.steer"].append(
            reply(steer_receipt(action="repair", members=members))
        )
    audit_paths = [
        f"vault/topics/{TOPIC}/00-overview.md",
        f"vault/topics/{TOPIC}/01-resources.md",
        f"vault/topics/{TOPIC}/02-outline.md",
    ]
    responses["topic.audit.legacy"] = [
        reply(
            audit_receipt(path, status="partial", escalated=[diagnostic])
            if path == target
            else audit_receipt(path)
        )
        for path in audit_paths
    ] + [reply(audit_receipt(target))]
    report = run_topic(tmp_path, responses=responses)

    writer_calls = calls(report, writer)
    audits = calls(report, "topic.audit.legacy")
    research = receipt(report["result"])
    assert len(writer_calls) == (3 if writer == "topic.steer" else 2)
    assert writer_calls[-1]["request"]["mode"] == "repair"
    assert writer_calls[-1]["request"]["repair_diagnostics"] == [diagnostic]
    assert len(audits) == 4
    assert audits[-1]["request"]["exact_output"] == target
    assert audits[-1]["start"] > writer_calls[-1]["end"]
    assert research["status"] == "complete"
    assert research["disposition"] == "repaired"


def test_residual_violation_after_one_repair_is_terminal_and_never_repaired_twice(
    tmp_path: Path,
) -> None:
    members = [member("paper", "exact-paper-2025")]
    overview_path = f"vault/topics/{TOPIC}/00-overview.md"
    diagnostic = {
        "path": overview_path,
        "kind": "section_shape",
        "reason": "overview needs repair",
    }
    residual = {**diagnostic, "reason": "repair did not resolve the issue"}
    responses = base_responses(members)
    responses["topic.synthesise.overview"] = [
        reply(synthesis_receipt("overview", members)),
        reply(synthesis_receipt("overview", members, action="repair")),
    ]
    responses["topic.audit.legacy"] = [
        reply(audit_receipt(overview_path, status="partial", escalated=[diagnostic])),
        reply(audit_receipt(f"vault/topics/{TOPIC}/01-resources.md")),
        reply(audit_receipt(f"vault/topics/{TOPIC}/02-outline.md")),
        reply(audit_receipt(overview_path, status="partial", escalated=[residual])),
    ]
    report = run_topic(tmp_path, responses=responses)

    research = receipt(report["result"])
    assert report["result"]["status"] == "audit_escalated"
    assert research["status"] == "failed"
    assert research["failure"]["code"] == "topic.audit_repair_exhausted"
    assert len(calls(report, "topic.synthesise.overview")) == 2
    assert len(calls(report, "topic.synthesise.resources")) == 1
    assert len(calls(report, "topic.audit.legacy")) == 4


def test_same_runtime_identical_strict_requests_coalesce_one_graph(
    tmp_path: Path,
) -> None:
    responses = base_responses()
    report = run_topic(
        tmp_path,
        responses=responses,
        requests=[
            {"slug": TOPIC, "meta": topic_meta()},
            {"slug": TOPIC, "meta": topic_meta()},
        ],
        parallel_requests=True,
    )

    first, second = report["result"]
    assert first == second
    for route in [
        "topic.recall",
        "topic.steer",
        "topic.resolve-membership",
        "topic.synthesise.overview",
        "topic.synthesise.resources",
        "topic.audit.legacy",
    ]:
        expected = 2 if route == "topic.steer" else 3 if route == "topic.audit.legacy" else 1
        assert len(calls(report, route)) == expected


def test_same_runtime_conflicting_topic_identity_blocks_before_second_writer(
    tmp_path: Path,
) -> None:
    responses = base_responses()
    report = run_topic(
        tmp_path,
        responses=responses,
        requests=[
            {"slug": TOPIC, "meta": topic_meta(desc=DESCRIPTION)},
            {"slug": TOPIC, "meta": topic_meta(desc="conflicting description")},
        ],
        parallel_requests=True,
    )

    statuses = [result["status"] for result in report["result"]]
    assert statuses.count("ok") == 1
    assert statuses.count("blocked") == 1
    blocked = next(result for result in report["result"] if result["status"] == "blocked")
    assert receipt(blocked)["failure"]["code"] == "topic.identity_conflict"
    assert len(calls(report, "topic.synthesise.overview")) == 1
    assert len(calls(report, "topic.synthesise.resources")) == 1


@pytest.mark.parametrize(
    ("members", "meta", "status", "research_status", "stage", "expected_calls"),
    [
        ([], topic_meta(), "no_works", "failed", "recall", {"topic.steer": 1}),
        (
            [member("paper", "exact-paper-2025")],
            topic_meta(minItems=2),
            "needs_seeds",
            "needs_input",
            "membership",
            {
                "topic.steer": 2,
                "topic.resolve-membership": 1,
            },
        ),
    ],
)
def test_recall_only_terminal_matrices_preserve_typed_receipts(
    tmp_path: Path,
    members: list[dict[str, str]],
    meta: dict[str, Any],
    status: str,
    research_status: str,
    stage: str,
    expected_calls: dict[str, int],
) -> None:
    responses: dict[str, list[dict[str, Any]]] = {
        "topic.recall": [reply(recall_receipt(members))],
        "topic.steer": [reply(steer_receipt(action="create"))],
    }
    if members:
        responses["topic.steer"].append(
            reply(steer_receipt(action="refresh", members=members))
        )
        responses["topic.resolve-membership"] = [reply(membership_receipt(members))]
    report = run_topic(tmp_path, meta=meta, responses=responses)

    result = report["result"]
    research = receipt(result)
    assert result["status"] == status
    assert research["status"] == research_status
    assert research["stage"] == stage
    assert not any(call["type"] == "router" for call in report["trace"])
    for route, count in expected_calls.items():
        assert len(calls(report, route)) == count
    assert calls(report, "topic.synthesise.overview") == []
    assert calls(report, "topic.synthesise.resources") == []


def test_legacy_adapter_is_derived_from_authoritative_research_receipt(
    tmp_path: Path,
) -> None:
    members = [member("book", "exact-book-2024"), member("talk", "exact-talk-2026")]
    report = run_topic(tmp_path, responses=base_responses(members))
    result = report["result"]
    research = receipt(result)

    adapter = {
        "slug": TOPIC,
        "status": "ok",
        "members": members,
        "recalled": len(members),
        "rounds": 0,
        "outline": f"vault/topics/{TOPIC}/02-outline.md",
        "overview": f"vault/topics/{TOPIC}/00-overview.md",
        "resources": f"vault/topics/{TOPIC}/01-resources.md",
    }
    assert research["status"] == "complete"
    assert {key: result[key] for key in adapter} == adapter
    assert result["members"] == [
        {
            "kind": entry["kind"],
            "slug": entry["id"],
            "path": entry["path"],
        }
        for entry in research["members"]
    ]
    assert result["recalled"] == len(research["members"])
    assert {
        artifact["role"]: artifact["path"] for artifact in research["artifacts"]
    } == {
        "outline": result["outline"],
        "overview": result["overview"],
        "resources": result["resources"],
    }
