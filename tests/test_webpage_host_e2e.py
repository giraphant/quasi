"""Paid, real-host regression. Never runs unless explicitly opted in."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
from urllib.parse import urlsplit
from tempfile import TemporaryDirectory
from uuid import uuid4
from xml.etree import ElementTree

import pytest

from webpage_test_support import delayed_webpage

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {f"webpage.{stage}" for stage in
              ("identify", "capture", "prepare", "analyse", "audit")}


def records(path):
    """Only parse this fresh session's files; never print transcript contents."""
    __tracebackhide__ = True
    try:
        return [strict_json(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        pytest.fail("Unreadable host evidence JSONL; raw contents withheld", pytrace=False)


def read_json(path):
    __tracebackhide__ = True
    try:
        return strict_json(path.read_text())
    except (OSError, ValueError):
        pytest.fail("Unreadable Workflow run JSON; raw contents withheld", pytrace=False)


def tool_calls(rows, name):
    __tracebackhide__ = True
    return [event["input"] for event in events(rows, name)]


def stop_group(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        if sig == signal.SIGTERM:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    process.wait(timeout=5)


def require(condition, message):
    __tracebackhide__ = True
    # Do not expose assertion locals, host prose, credentials, or raw Bash commands.
    if not condition:
        pytest.fail(message[:500], pytrace=False)


def events(rows, name):
    """Deduplicate replayed tool blocks while retaining session order and call ids."""
    __tracebackhide__ = True
    found = {}
    for index, row in enumerate(rows):
        content = row.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                identifier = block["id"]
                signature = {"name": block.get("name"), "input": block.get("input")}
                if identifier in found:
                    require(found[identifier]["signature"] == signature,
                            "Conflicting duplicate tool id; contents withheld")
                else:
                    found[identifier] = {"index": index, "id": identifier,
                                         "input": block["input"], "signature": signature}
    return [{k: value for k, value in event.items() if k != "signature"}
            for event in found.values() if event["signature"]["name"] == name]


def result_row(rows, event):
    __tracebackhide__ = True
    matches = []
    for index, row in enumerate(rows):
        content = row.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") == event["id"]:
                    matches.append((index, row))
    require(len(matches) == 1 and matches[0][0] > event["index"], "Missing or duplicate tool result")
    matched = next(block for block in matches[0][1]["message"]["content"]
                   if isinstance(block, dict) and block.get("type") == "tool_result"
                   and block.get("tool_use_id") == event["id"])
    require(matched.get("is_error", False) is False,
            "Tool result reports failure; contents withheld")
    return matches[0]


def json_value(raw):
    __tracebackhide__ = True
    try:
        return strict_json(raw)
    except (TypeError, ValueError):
        pytest.fail("Invalid evidence JSON; contents withheld", pytrace=False)


PYMUPDF_COMPAT_WARNING = (
    "warning: The `fitz` API is deprecated and will be removed in future. "
    "Use `import pymupdf` instead."
)


def status_stdout(raw):
    """One status JSON object, optionally preceded by one exact compatibility line."""
    __tracebackhide__ = True
    require(isinstance(raw, str), "Invalid status stdout; contents withheld")
    lines = [line for line in raw.splitlines() if line.strip()]
    if lines and lines[0] == PYMUPDF_COMPAT_WARNING:
        lines = lines[1:]
    try:
        payload = strict_json("\n".join(lines))
    except (TypeError, ValueError):
        pytest.fail("Invalid status stdout; contents withheld", pytrace=False)
    require(isinstance(payload, dict) and bool(payload), "Invalid status stdout; contents withheld")
    return payload


def commands(command):
    """Parse literal CLI invocations, failing closed on wrappers/substitutions.

    This is evidence parsing, never shell execution. Only a single bare shim
    invocation proves capability execution under the controlled Host PATH.
    """
    __tracebackhide__ = True
    require(not re.search(r"(?:scripts[./]webpage(?:[./]|\b)|(?:^|[\s/'\"])webpage(?:_capture)?\.(?:py|swift)\b|quasi-webpage-webkit(?:-|\b))", command),
            "Direct implementation entrypoint forbidden; command withheld")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except (TypeError, ValueError):
        pytest.fail("Unparseable Bash evidence; command withheld", pytrace=False)
    segments, current = [], []
    for token in tokens + [";"]:
        if token and set(token) <= set(";&|\n") and token != "&":
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    found = []
    for segment_index, segment in enumerate(segments):
        require(segment[0] != "cd", "Bash evidence changes the specialist cwd")
        targets = [t for t in segment if Path(t).name in ("quasi-webpage", "quasi-status", "quasi-helpers")]
        if not targets:
            # A vault/artifact component such as quasi-webpage-host-* is not
            # an executable. Still reject complete CLI names inside wrappers.
            cli_name = r"(?:^|[\s/\"';|&()])quasi-(?:webpage|status|helpers)(?=$|[\s\"';|&()])"
            require(not any(re.search(cli_name, token) for token in segment),
                    "Opaque CLI wrapper in Bash evidence")
            continue
        require(len(segments) == 1 and segment_index == 0 and
                segment[0] in ("quasi-webpage", "quasi-status", "quasi-helpers"),
                "CLI must be a single bare simple command; command withheld")
        require(not any(t and set(t) <= set(";&|()<>\n") for t in tokens),
                "CLI shell operators cannot prove execution; command withheld")
        prefix = 0
        args = segment[1:]
        require(not any(t in ("(", ")", "<", "&") or "$" in t or "`" in t for t in args),
                "Dynamic CLI arguments cannot prove exact refs")
        options = {}
        operation = args.pop(0) if Path(segment[prefix]).name == "quasi-webpage" and args else None
        if segment[0] == "quasi-helpers":
            require(args[:2] == ["vault", "resolve"], "Unexpected specialist helper; contents withheld")
            operation = "vault resolve"
            args = args[2:]
        while args:
            flag = args.pop(0)
            require(flag.startswith("--"), "Unexpected CLI positional argument")
            if "=" in flag:
                flag, value = flag.split("=", 1)
            elif flag == "--json":
                value = True
            else:
                require(bool(args) and not args[0].startswith("--"), "Missing CLI argument value")
                value = args.pop(0)
            require(flag not in options, "Duplicate CLI option")
            options[flag] = value
        found.append({"executable": segment[prefix], "operation": operation, "options": options})
    return found


def bash_commands(rows):
    __tracebackhide__ = True
    return [{**command, "event": event} for event in events(rows, "Bash")
            for command in commands(event["input"].get("command", ""))]


def expected_refs(slug):
    return {"snapshot": f"vault/webpages/{slug}/snapshot.webarchive",
            "prepared": f"processing/webpages/{slug}/source.md",
            "canonical": f"vault/webpages/{slug}/webpage.md"}


def whole_second(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%dT%H:%M:%SZ") == value
    except ValueError:
        return False


def js_length(value):
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def public_url(value):
    if type(value) is not str or not 1 <= js_length(value) <= 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        parsed = urlsplit(value.strip(" "))
        return (parsed.scheme in ("http", "https") and bool(parsed.hostname)
                and (bool(re.fullmatch(r'[0-9a-f:.]+', parsed.hostname)) if parsed.netloc.startswith('[') else not any(c in parsed.hostname for c in ' "#%/:<>?@[\\]^|'))
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 0 <= parsed.port <= 65535))
    except ValueError:
        return False


def check_status(status, route, *, usable, expected_identity=None):
    __tracebackhide__ = True
    require(type(status) is dict and set(status) == {"schema_version", "kind", "slug", "identity", "facts"},
            "Status closed keys mismatch; contents withheld")
    require(status["schema_version"] == "quasi.status/0.2" and status["kind"] == route["kind"] == "webpage"
            and status["slug"] == route["slug"] and type(status["slug"]) is str
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", status["slug"]), "Status route mismatch; contents withheld")
    identity = status["identity"]
    if identity is not None:
        require(type(identity) is dict and set(identity) == {"slug", "title", "url", "site"},
                "Status identity keys mismatch; contents withheld")
        require(identity["slug"] == route["slug"] and public_url(identity["url"])
                and type(identity["title"]) is str and 1 <= js_length(identity["title"]) <= 500
                and type(identity["site"]) is str and 1 <= js_length(identity["site"]) <= 200,
                "Status identity mismatch; contents withheld")
    require(not usable or identity is not None, "Usable status lacks identity; contents withheld")
    if usable and expected_identity is not None:
        require(identity == expected_identity, "Status identity provenance mismatch; contents withheld")
    facts = status["facts"]
    require(type(facts) is dict and set(facts) == {"kind", "snapshot", "prepared", "canonical", "captured_at"}
            and facts["kind"] == "webpage", "Status facts keys mismatch; contents withheld")
    for role, ref in expected_refs(route["slug"]).items():
        fact = facts[role]
        require(type(fact) is dict and set(fact) == {"path", "present", "usable"}
                and fact["path"] == ref and type(fact["present"]) is bool and type(fact["usable"]) is bool
                and (not fact["usable"] or fact["present"])
                and fact["present"] is usable and fact["usable"] is usable,
                "Status artifact mismatch; contents withheld")
    require(whole_second(facts["captured_at"]) if facts["snapshot"]["usable"] else facts["captured_at"] is None,
            "Status captured_at mismatch; contents withheld")


def consumed_notification(row):
    """Only SDK user delivery proves consumption; queue records are not evidence."""
    __tracebackhide__ = True
    message = row.get("message", {})
    if not (row.get("type") == "user" and row.get("origin") == {"kind": "task-notification"}
            and row.get("promptSource") == "sdk" and isinstance(message, dict)
            and message.get("role") == "user"):
        return None
    content = message.get("content")
    require(isinstance(content, str), "Invalid task-notification XML; contents withheld")
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, ValueError):
        pytest.fail("Invalid task-notification XML; contents withheld", pytrace=False)
    require(root.tag == "task-notification" and not root.attrib,
            "Invalid task-notification root; contents withheld")
    require(not (root.text or "").strip() and all(not (child.tail or "").strip() for child in root),
            "Ambiguous task-notification text; contents withheld")
    fields = {}
    for name in ("task-id", "tool-use-id", "status", "result"):
        nodes = list(root.iter(name))
        require(len(nodes) == 1 and nodes[0] in list(root),
                "Missing, duplicate or nested notification binding field; contents withheld")
        node = nodes[0]
        require(not node.attrib and len(node) == 0 and isinstance(node.text, str) and bool(node.text.strip()),
                "Invalid notification binding field; contents withheld")
        fields[name] = node.text
    return fields


def completed_at(rows, event, run):
    __tracebackhide__ = True
    index, row = result_row(rows, event)
    launch = row.get("toolUseResult", {})
    require(launch.get("runId") == run["runId"], "Workflow call/runId mismatch")
    matches = []
    if "result" in launch:
        require(launch["result"] == run["result"], "Inline Workflow result/sidecar mismatch")
        matches.append(index)  # Synchronous completion is the launch result itself.
    task_id = launch.get("taskId")
    retrieval_indices = set()
    retrievals = [call for call in events(rows, "TaskOutput")
                  if task_id and call["input"].get("task_id") == task_id]
    require(len(retrievals) <= 1, "Duplicate TaskOutput calls; contents withheld")
    for call in retrievals:
        require(call["index"] > index, "TaskOutput call precedes Workflow launch result")
        retrieval_index, retrieval = result_row(rows, call)
        envelope = retrieval.get("toolUseResult", {})
        require(type(envelope) is dict and set(envelope) == {"retrieval_status", "task"}
                and envelope["retrieval_status"] == "success", "TaskOutput envelope mismatch; contents withheld")
        task = envelope["task"]
        require(type(task) is dict and set(task) == {"task_id", "task_type", "status", "description", "output"}
                and task["task_type"] == "local_workflow" and type(task["description"]) is str
                and task.get("task_id") == task_id
                and task.get("status") == "completed", "TaskOutput task binding mismatch; contents withheld")
        output = json_value(task.get("output"))
        require(type(output) is dict and set(output) == {"summary", "agentCount", "logs", "result", "workflowProgress", "totalTokens", "totalToolCalls"}
                and type(output["summary"]) is str and type(output["logs"]) is list and type(output["workflowProgress"]) is list
                and all(type(output[key]) is int and output[key] >= 0 for key in ("agentCount", "totalTokens", "totalToolCalls"))
                and output.get("result") == run["result"],
                "Retrieved Workflow result/sidecar mismatch")
        require(all(value.get("runId", run["runId"]) == run["runId"]
                    for value in (task, output, retrieval.get("toolUseResult", {}))),
                "TaskOutput run binding mismatch; contents withheld")
        matches.append(retrieval_index)
        retrieval_indices.add(retrieval_index)
    # Orphan result payloads are never a completion channel.
    for i, row in enumerate(rows):
        task = row.get("toolUseResult", {}).get("task", {}) if isinstance(row.get("toolUseResult"), dict) else {}
        if isinstance(task, dict) and task_id and task.get("task_id") == task_id:
            require(i in retrieval_indices, "Orphan TaskOutput result; contents withheld")
        notification = consumed_notification(row)
        if notification is not None and (notification["task-id"] == task_id or notification["tool-use-id"] == event["id"]):
            require(bool(task_id) and notification["task-id"] == task_id
                    and notification["tool-use-id"] == event["id"],
                    "Notification task/call binding mismatch; contents withheld")
            require(i > index, "Consumed notification precedes launch result")
            require(notification["status"] == "completed", "Notification is not completed")
            require(json_value(notification["result"]) == run["result"],
                    "Notification result/sidecar mismatch; contents withheld")
            matches.append(i)
    require(len(matches) == 1, "Missing unique completed Workflow retrieval or delivery")
    return matches[0]


def validate_material(result, route, seed, *, complete):
    __tracebackhide__ = True
    common = {"schema_version", "terminal", "material", "issue"}
    keys = common | ({"artifacts", "next"} if complete else {"routes", "resume_seed"})
    require(type(result) is dict and set(result) == keys, "Material result keys mismatch; contents withheld")
    require(result["schema_version"] == "quasi.material.result/0.1"
            and result["terminal"] == ("complete" if complete else "needs_observation")
            and result["issue"] is None
            and result["material"] == {"requested": {"kind": "webpage", "slug": None}, "canonical": route},
            "Material identity/terminal mismatch; contents withheld")
    require(type(route) is dict and set(route) == {"kind", "slug"} and route["kind"] == "webpage"
            and type(route["slug"]) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", route["slug"]),
            "Material route mismatch; contents withheld")
    require(type(seed) is dict and set(seed) == {"state", "material_slug", "identity"}
            and seed["state"] == "canonical" and seed["material_slug"] == route["slug"],
            "Material continuation mismatch; contents withheld")
    identity = seed["identity"]
    require(type(identity) is dict and set(identity) == {"slug", "title", "url", "site"}
            and identity["slug"] == route["slug"] and public_url(identity["url"])
            and type(identity["title"]) is str and 1 <= js_length(identity["title"]) <= 500
            and type(identity["site"]) is str and 1 <= js_length(identity["site"]) <= 200,
            "Material identity mismatch; contents withheld")
    if complete:
        refs = expected_refs(route["slug"])
        require(result["next"] is None and result["artifacts"] == [
            {"role": "snapshot", "path": refs["snapshot"]},
            {"role": "normalized_text", "path": refs["prepared"]},
            {"role": "canonical", "path": refs["canonical"]}],
            "Material artifacts/next mismatch; contents withheld")
    else:
        require(result["routes"] == [route] and result["resume_seed"] == {"route": route, "seed": seed, "options": {}},
                "Material observation continuation mismatch; contents withheld")


def verify_agent_metadata(directory, entry, operation):
    __tracebackhide__ = True
    identifier = entry.get("agentId")
    require(type(identifier) is str and re.fullmatch(r"[A-Za-z0-9_-]+", identifier), "Invalid specialist id")
    path = directory / f"agent-{identifier}.meta.json"
    require(path.is_file(), "Missing specialist metadata; contents withheld")
    metadata = read_json(path)
    expected_type = "quasi:" + ({"webpage.analyse": "analyse-agent", "webpage.audit": "audit-agent"}.get(operation, "webpage-agent"))
    require(type(metadata) is dict and set(metadata) == {"agentType", "description", "workflowPhase", "spawnDepth", "requestShape", "requestNonInteractive"}
            and metadata.get("workflowPhase") == {"webpage.identify": "Search", "webpage.capture": "Acquire", "webpage.prepare": "Prepare", "webpage.analyse": "Analyse", "webpage.audit": "Audit"}[operation]
            and type(metadata.get("spawnDepth")) is int and metadata["spawnDepth"] == 1
            and metadata.get("requestShape") == "foreground" and metadata.get("requestNonInteractive") is True
            and metadata.get("agentType") == expected_type
            and metadata.get("description") == entry.get("label"), "Specialist owner metadata mismatch; contents withheld")


def verify_run_agents(directory, launched, session_id):
    __tracebackhide__ = True
    require({p.name for p in directory.glob("*.meta.json")} == {f"agent-{entry['agentId']}.meta.json" for entry in launched},
            "Unexpected specialist metadata files; contents withheld")
    transcripts = {}
    for entry in launched:
        operation = str(entry.get("label", "")).rsplit(":", 1)[-1]
        require(operation in OPERATIONS and operation not in transcripts, "Invalid specialist operation; contents withheld")
        verify_agent_metadata(directory, entry, operation)
        transcript = directory / f"agent-{entry['agentId']}.jsonl"
        require(transcript.is_file(), "Missing specialist transcript; contents withheld")
        rows = records(transcript)
        require(bool(rows) and all(row.get("agentId") == entry["agentId"] and row.get("sessionId") == session_id for row in rows),
                "Specialist transcript identity mismatch; contents withheld")
        transcripts[operation] = rows
    return transcripts


def verify_coordinator(rows, sidecars, url):
    __tracebackhide__ = True
    calls = events(rows, "Workflow")
    require(len(calls) == len(sidecars) == 2, "Expected exactly two named Workflow calls and sidecars")
    ordered = []
    for state in ("provisional", "canonical"):
        matches = [r for r in sidecars if r.get("args", {}).get("seed", {}).get("state") == state]
        require(len(matches) == 1, "Expected one provisional and one canonical sidecar")
        ordered.append(matches[0])
    for call, run in zip(calls, ordered):
        require(call["input"].get("scriptPath") == run.get("scriptPath") == str(ROOT / "workflows/webpage.mjs"),
                "Workflow script path mismatch")
        require(call["input"].get("args") == run["args"], "Workflow order/args do not match seed order")
    first, second = ordered
    require(first["runId"] != second["runId"], "Workflow run ids must be distinct")
    require(all(type(run.get("result")) is dict for run in ordered), "Invalid material result; contents withheld")
    require(all(run["result"].get("schema_version") == "quasi.material.result/0.1" for run in ordered),
            "Unexpected material result schema")
    require(first["args"] == {"seed": {"state": "provisional", "url": url}, "observation": None, "options": {}},
            "Initial Workflow envelope is not the exact provisional request")
    require(first["result"].get("terminal") == "needs_observation", "Initial result must need observation")
    continuation = first["result"].get("resume_seed", {})
    require(type(continuation) is dict and set(continuation) == {"route", "seed", "options"}, "Invalid continuation; contents withheld")
    route = continuation.get("route", {})
    require(type(route) is dict and type(route.get("slug")) is str, "Invalid canonical route; contents withheld")
    require(route.get("kind") == "webpage" and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", route.get("slug", ""))),
            "Invalid canonical route")
    seed = continuation.get("seed", {})
    require(type(seed) is dict and type(seed.get("identity")) is dict, "Invalid canonical seed; contents withheld")
    require(seed.get("state") == "canonical" and seed.get("material_slug") == route["slug"] and
            seed.get("identity", {}).get("url") == url and seed.get("identity", {}).get("slug") == route["slug"], "Continuation seed does not bind fixture route")
    require(set(second["args"]) == {"seed", "options", "observation"} and
            second["args"]["seed"] == seed and second["args"]["options"] == continuation.get("options"),
            "Canonical invocation changed the continuation seed/options")
    validate_material(first["result"], route, seed, complete=False)
    validate_material(second["result"], route, seed, complete=True)
    check_status(second["args"]["observation"], route, usable=False)
    require(second["result"].get("terminal") == "complete", "Canonical Workflow did not complete")
    require(second["result"].get("material", {}).get("canonical") == route, "Complete result changed canonical route")
    completed = [completed_at(rows, c, r) for c, r in zip(calls, ordered)]
    cli = bash_commands(rows)
    require(all(Path(c["executable"]).name == "quasi-status" for c in cli), "Coordinator invoked a specialist CLI")
    require(len(cli) == 2, "Coordinator must invoke fresh quasi-status exactly twice")
    require(completed[0] < cli[0]["event"]["index"] < calls[1]["index"] and
            completed[1] < cli[1]["event"]["index"], "Status calls are not before capture and after completion")
    for i, command in enumerate(cli):
        require(command["options"] == {"--kind": "webpage", "--slug": route["slug"], "--json": True},
                "Coordinator status command does not name the exact canonical route")
        result_index, row = result_row(rows, command["event"])
        status = status_stdout(row.get("toolUseResult", {}).get("stdout"))
        check_status(status, route, usable=bool(i), expected_identity=seed["identity"])
        if i == 0:
            require(result_index < calls[1]["index"] and status == second["args"]["observation"],
                    "Canonical observation is not the fresh pre-capture status")
    return ordered, route


def paired_starts(journal):
    __tracebackhide__ = True
    starts = [(i, row) for i, row in enumerate(journal) if row.get("type") == "started"]
    results = [(i, row) for i, row in enumerate(journal) if row.get("type") == "result"]
    ids = [row.get("agentId") for _, row in starts]
    require(len(ids) == len(set(ids)) and len(results) == len(starts), "Duplicate or unpaired journal dispatch")
    for index, start in starts:
        matches = [(i, row) for i, row in results if row.get("agentId") == start.get("agentId")]
        require(len(matches) == 1 and matches[0][0] > index, "Started operation lacks exactly one later result")
    return [row for _, row in starts]


def strict_json(raw):
    """All evidence JSON shares recursive duplicate/constant rejection."""
    __tracebackhide__ = True
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Invalid evidence JSON; contents withheld")
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError("Invalid evidence JSON; contents withheld")
    try:
        def finite_float(token):
            value = float(token)
            if not math.isfinite(value):
                invalid_constant(token)
            return value
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant,
                          parse_float=finite_float)
    except (TypeError, ValueError):
        raise ValueError("Invalid evidence JSON; contents withheld") from None


def cli_receipt(raw):
    __tracebackhide__ = True
    result = json_value(raw)
    require(isinstance(raw, str) and isinstance(result, dict), "Invalid CLI receipt; contents withheld")
    return result


def validate_cli_receipt(receipt, command, expected):
    __tracebackhide__ = True
    keys = {"schema_version", "status", "final_url", "title", "site"}
    if command in ("inspect", "capture"):
        keys.add("url")
    if command != "inspect":
        keys.update(("output_path", "sha256", "size", "write_state"))
    if command == "capture":
        keys.add("captured_at")
    if command == "extract":
        keys.add("snapshot_path")
    require(set(receipt) == keys, "CLI receipt closed key set mismatch; contents withheld")
    require(all(type(receipt[key]) is str and bool(receipt[key]) for key in keys - {"size"}),
            "CLI receipt string type/value mismatch; contents withheld")
    require(all(receipt.get(key) == value for key, value in expected.items()),
            "Specialist CLI receipt contract mismatch; contents withheld")
    require(all(receipt[key] == " ".join(receipt[key].split()) for key in ("title", "site")),
            "CLI receipt metadata normalization mismatch; contents withheld")
    if command != "inspect":
        require(type(receipt["size"]) is int and receipt["size"] > 0
                and re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is not None,
                "CLI receipt digest/size mismatch; contents withheld")
    if command == "capture":
        try:
            stamp = datetime.strptime(receipt["captured_at"], "%Y-%m-%dT%H:%M:%SZ")
            valid = stamp.strftime("%Y-%m-%dT%H:%M:%SZ") == receipt["captured_at"]
        except ValueError:
            valid = False
        require(valid, "CLI receipt timestamp mismatch; contents withheld")


def verify_specialists(transcripts, vault, url, route, identity=None):
    __tracebackhide__ = True
    require(set(transcripts) == OPERATIONS, "Missing or duplicate specialist operation ownership")
    refs = expected_refs(route["slug"])
    expected = {
        "identify": ("inspect", {"--url": url, "--json": True}, {"url": url, "final_url": url}),
        "capture": ("capture", {"--url": url, "--expected-final-url": url, "--output": refs["snapshot"], "--json": True},
                    {"write_state": "written", "url": url, "output_path": refs["snapshot"], "final_url": url}),
        "prepare": ("extract", {"--snapshot": refs["snapshot"], "--output": refs["prepared"], "--json": True},
                    {"write_state": "written", "snapshot_path": refs["snapshot"], "output_path": refs["prepared"], "final_url": url}),
    }
    receipts = {}
    for operation, rows in transcripts.items():
        require(bool(rows) and all(row.get("cwd") == str(vault) for row in rows), "Specialist transcript cwd mismatch")
        all_cli = bash_commands(rows)
        require(not any(c["executable"] == "quasi-status" for c in all_cli), "Specialist status observation forbidden")
        cli = [c for c in all_cli if c["executable"] == "quasi-webpage"]
        stage = operation.removeprefix("webpage.")
        resolvers = [c for c in all_cli if c["executable"] == "quasi-helpers"]
        require(len(resolvers) == (1 if stage == "identify" else 0), "Resolver count/owner mismatch")
        if resolvers:
            resolver = resolvers[0]
            require(set(resolver["options"]) == {"--items-json"}, "Resolver input must be literal JSON evidence")
            items = json_value(resolver["options"]["--items-json"])
            require(type(items) is list and len(items) == 1 and type(items[0]) is dict,
                    "Resolver input shape mismatch; contents withheld")
            item = items[0]
            require(set(item) <= {"kind", "slug", "url", "title", "site"} and item.get("kind") == "webpage"
                    and item.get("url") == url and item.get("slug") == route["slug"], "Resolver input identity mismatch; contents withheld")
            _, row = result_row(rows, resolver["event"])
            block = next(b for b in row["message"]["content"] if b.get("tool_use_id") == resolver["event"]["id"])
            resolved = cli_receipt(block.get("content"))
            require(resolved == {"resolved": [{"kind": "webpage", "slug": route["slug"], "vault_slug": None,
                        "path": None, "match": None, "suggested_slug": route["slug"]}], "scanned": {}},
                    "Fresh resolver receipt/owner mismatch; contents withheld")
        if stage in ("analyse", "audit"):
            require(not cli, "Non-owner specialist invoked quasi-webpage")
            continue
        command_name, options, evidence = expected[stage]
        require(len(cli) == 1 and cli[0]["operation"] == command_name,
                "Specialist CLI count/operation owner mismatch")
        command = cli[0]
        # This E2E request names relative refs: equivalent absolute paths are not
        # the request spelling and must not be silently normalized into evidence.
        require(command["options"] == options, "Specialist literal URL/ref spelling mismatch")
        receipt_index, result = result_row(rows, command["event"])
        block = next(block for block in result["message"]["content"]
                     if isinstance(block, dict) and block.get("type") == "tool_result"
                     and block.get("tool_use_id") == command["event"]["id"])
        require(block.get("is_error") is not True, "Specialist CLI tool result reports failure; contents withheld")
        receipt = cli_receipt(block.get("content"))
        expected_receipt = {"schema_version": f"quasi.webpage.{command_name}/0.1",
                            "status": "complete", **evidence}
        validate_cli_receipt(receipt, command_name, expected_receipt)
        if stage == "identify":
            require(receipt_index < resolver["event"]["index"], "Resolver precedes inspect testimony; contents withheld")
            require(item == {"kind": "webpage", "slug": route["slug"], "url": receipt["final_url"],
                             "title": receipt["title"], "site": receipt["site"]},
                    "Resolver metadata/inspect mismatch; contents withheld")
        receipts[command_name] = receipt
    if identity is not None:
        require(identity == {"slug": route["slug"], "url": url, "title": receipts["inspect"]["title"], "site": receipts["inspect"]["site"]},
                "Resolver/final Workflow identity mismatch; contents withheld")
    require(all(receipts["inspect"][key] == receipts["capture"][key] == receipts["extract"][key] for key in ("title", "site")),
            "Snapshot/extract metadata contradiction; contents withheld")


@pytest.mark.host_e2e
@pytest.mark.skipif(os.environ.get("QUASI_RUN_CLAUDE_WEBPAGE_E2E") != "1",
                    reason="set QUASI_RUN_CLAUDE_WEBPAGE_E2E=1 to run the paid real host")
def test_real_named_webpage_workflow():
    __tracebackhide__ = True
    require(sys.platform == "darwin", "Host E2E requires macOS WKWebView")
    for executable in ("claude", "swiftc", "node"):
        require(shutil.which(executable), f"Host E2E missing dependency: {executable}")
    for module in ("trafilatura", "yaml", "pydantic", "pymupdf", "requests",
                   "bs4", "curl_cffi", "bibtexparser", "lxml_html_clean"):
        require(importlib.util.find_spec(module), f"Host E2E missing Python dependency: {module}")
    require((Path(sys.prefix) / "bin/python").is_file(),
            "Host E2E requires a provisioned virtualenv with bin/python")
    require((ROOT / "workflows/webpage.mjs").is_file(), "Missing named webpage bundle")
    from scripts.webpage.webarchive import read_webarchive

    session_id = str(uuid4())
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).resolve()
    # resolve() is essential on macOS: /var and /private/var are different spellings.
    with TemporaryDirectory(prefix="quasi-webpage-host-") as temporary, delayed_webpage() as (url, sentinel):
        vault = Path(temporary).resolve()
        data = vault / ".plugin-data"
        data.mkdir()
        (data / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("QUA_PROJECT_ROOT", None)
        env["PYMUPDF_MESSAGE"] = "fd:2"  # Keep dependency diagnostics out of CLI JSON.
        env["CLAUDE_PROJECT_DIR"] = ""  # Reproduce the specialist empty-root case.
        env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
        env["CLAUDE_PLUGIN_DATA"] = str(data)
        env["PATH"] = str(ROOT / "bin") + os.pathsep + env.get("PATH", "")
        prompt = (
            f"Use quasi:collect-material to preserve this exact webpage: {url}. "
            f"The disposable project root is your current cwd {vault}. "
            "Use the real named Workflow at " + str(ROOT / "workflows/webpage.mjs") + ". "
            "Start with provisional seed, observation:null, options:{}. Follow its returned "
            "exact route with fresh quasi-status, then resume the same named Workflow. "
            "After completion obtain fresh exact status. Do not inline or synthesize a Workflow, "
            "do not substitute direct agents or fake receipts, and do not retry unknown writers. "
            "Specialist CLI URL/path arguments must be literal exact refs, never shell-derived variables or substitutions. "
            "Preserve all source paragraphs verbatim in the canonical Content section. "
            "The loopback fixture is intentionally public to this machine and authorized. "
            "Do not access other projects, send messages, commit, or install dependencies."
        )
        # Disable startup/user hooks so this test cannot bootstrap/install packages.
        # Bare shims get the checkout PATH and disposable data env directly.
        # Files avoid unbounded PIPE buffering and are deleted with the disposable vault.
        with (vault / "host.stdout").open("wb") as stdout, (vault / "host.stderr").open("wb") as stderr:
            process = subprocess.Popen(
                [shutil.which("claude"), "-p", "--output-format", "json",
                 "--session-id", session_id, "--plugin-dir", str(ROOT),
                 "--setting-sources", "project", "--no-chrome",
                 "--settings", '{"disableAllHooks":true}',
                 "--permission-mode", "bypassPermissions", prompt],
                cwd=vault, env=env, stdout=stdout, stderr=stderr, start_new_session=True,
            )
            try:
                try:
                    code = process.wait(timeout=900)
                except subprocess.TimeoutExpired:
                    pytest.fail("Host E2E exceeded 900s; process group terminated", pytrace=False)
            finally:
                stop_group(process)
        require(code == 0, f"Claude host exited {code}; raw output withheld")
        # Discover exact session by UUID, not by guessed project encoding or prior runs.
        sessions = list((config / "projects").glob(f"*/{session_id}.jsonl"))
        require(len(sessions) == 1, "Expected exactly one fresh session JSONL")
        session = sessions[0]
        rows = records(session)
        run_root = session.with_suffix("")
        sidecars = [read_json(p) for p in (run_root / "workflows").glob("*.json")]
        sidecars, route = verify_coordinator(rows, sidecars, url)
        observed = []
        specialist_transcripts = {}
        for run in sidecars:
            require(Path(run.get("scriptPath", "")).resolve() == ROOT / "workflows/webpage.mjs",
                    "Run record does not bind named webpage bundle")
            run_id = run.get("runId", "")
            require(bool(re.fullmatch(r"wf_[A-Za-z0-9_-]+", run_id)), "Invalid Workflow run id")
            directory = run_root / "subagents" / "workflows" / run_id
            journal = directory / "journal.jsonl"
            require(journal.is_file(), "Missing Workflow run journal")
            launched = paired_starts(records(journal))
            run_transcripts = verify_run_agents(directory, launched, run_root.name)
            require(not set(run_transcripts) & set(specialist_transcripts), "Duplicate specialist operation")
            observed.extend(run_transcripts)
            specialist_transcripts.update(run_transcripts)
        require(Counter(observed) == Counter(OPERATIONS),
                f"Expected five operations once each; counts={dict(Counter(observed))}")
        verify_specialists(specialist_transcripts, vault, url, route, sidecars[1]["args"]["seed"]["identity"])
        page = vault / expected_refs(route["slug"])["canonical"]
        # Independent acceptance through the source CLI, in the actual disposable cwd.
        status_process = subprocess.run(
            [str(ROOT / "bin/quasi-status"), "--kind", "webpage", "--slug", route["slug"], "--json"],
            cwd=vault, env=env, capture_output=True, text=True, timeout=30,
        )
        require(status_process.returncode == 0, "Independent source quasi-status failed; output withheld")
        fresh = status_stdout(status_process.stdout)
        check_status(fresh, route, usable=True, expected_identity=sidecars[1]["args"]["seed"]["identity"])
        completed = next(run["result"] for run in sidecars if run["result"]["terminal"] == "complete")
        returned_paths = {artifact["path"] for artifact in completed["artifacts"]}
        for role in ("snapshot", "prepared", "canonical"):
            fact = fresh["facts"][role]
            require(fact["path"] in returned_paths, f"Complete result omitted exact {role} ref")
            require(fact.get("present") is True and fact.get("usable") is True,
                    f"Fresh {role} status is not present and usable")
        require(sentinel in read_webarchive(page.parent / "snapshot.webarchive").html,
                "Delayed sentinel missing from archive main resource")
        require(sentinel in (vault / "processing/webpages" / page.parent.name / "source.md").read_text(),
                "Delayed sentinel missing from prepared source")
        content = re.search(r"^## Content\s*\n(.*?)(?=^## |\Z)", page.read_text(), re.M | re.S)
        require(content is not None and sentinel in content.group(1),
                "Delayed sentinel missing from canonical Content")
