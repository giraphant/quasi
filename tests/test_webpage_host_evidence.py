"""Deterministic contract tests for real-host evidence; never launches Claude."""
from copy import deepcopy
import json
from pathlib import Path
import shlex
from xml.etree import ElementTree

import pytest

from test_webpage_host_e2e import (
    ROOT, PYMUPDF_COMPAT_WARNING, commands, completed_at, events, expected_refs, json_value, paired_starts,
    cli_receipt,
    status_stdout, verify_coordinator, verify_specialists,
)

URL = "http://127.0.0.1:54321/fixture.html"
ROUTE = {"kind": "webpage", "slug": "fixture"}
IDENTITY = {"url": URL, "slug": "fixture", "title": "Fixture", "site": "Fixture Site"}


def status(usable):
    return {"schema_version": "quasi.status/0.2", **ROUTE,
            "identity": deepcopy(IDENTITY) if usable else None, "facts": {"kind": "webpage", "captured_at": "2026-09-21T00:00:00Z" if usable else None,
                **{role: {"path": path, "present": usable, "usable": usable}
                   for role, path in expected_refs("fixture").items()}}}


def call(name, identifier, value):
    return {"message": {"content": [{"type": "tool_use", "name": name,
             "id": identifier, "input": value}]}}


def reply(identifier, value):
    return {"message": {"content": [{"type": "tool_result", "tool_use_id": identifier, "is_error": False}]},
            "toolUseResult": value}


def completion_output(result):
    return {"summary": "fixture", "agentCount": 1, "logs": [], "result": result,
            "workflowProgress": [], "totalTokens": 1, "totalToolCalls": 1}


@pytest.fixture
def evidence():
    seed = {"state": "canonical", "material_slug": "fixture", "identity": deepcopy(IDENTITY)}
    first = {"scriptPath": str(ROOT / "workflows/webpage.mjs"), "runId": "wf_first",
             "args": {"seed": {"state": "provisional", "url": URL}, "observation": None, "options": {}},
             "result": {"schema_version": "quasi.material.result/0.1", "terminal": "needs_observation", "material": {"requested": {"kind": "webpage", "slug": None}, "canonical": ROUTE}, "issue": None, "routes": [ROUTE], "resume_seed": {"route": ROUTE, "seed": seed, "options": {}}}}
    second = {"scriptPath": first["scriptPath"], "runId": "wf_second",
              "args": {"seed": seed, "observation": status(False), "options": {}},
              "result": {"schema_version": "quasi.material.result/0.1", "terminal": "complete", "material": {"requested": {"kind": "webpage", "slug": None}, "canonical": ROUTE}, "issue": None, "next": None, "artifacts": [{"role": role, "path": expected_refs("fixture")[ref]} for role, ref in (("snapshot", "snapshot"), ("normalized_text", "prepared"), ("canonical", "canonical"))]}}
    rows = []
    for i, run in enumerate((first, second)):
        rows.extend([
            call("Workflow", f"wf{i}", {"scriptPath": run["scriptPath"], "args": deepcopy(run["args"])}),
            reply(f"wf{i}", {"runId": run["runId"], "taskId": f"task{i}"}),
            call("TaskOutput", f"wait{i}", {"task_id": f"task{i}"}),
            reply(f"wait{i}", {"retrieval_status": "success", "task": {"task_type": "local_workflow", "description": "fixture", "task_id": f"task{i}", "status": "completed",
                                      "output": json.dumps(completion_output(run["result"]))}}),
            call("Bash", f"status{i}", {"command": "quasi-status --kind webpage --slug fixture --json"}),
            reply(f"status{i}", {"stdout": json.dumps(status(bool(i)))})])
    return rows, [second, first]  # Filesystem sidecar order is deliberately reversed.


def test_coordinator_binds_seed_order_continuation_and_fresh_observation(evidence):
    rows, runs = evidence
    ordered, route = verify_coordinator(rows, runs, URL)
    assert [run["runId"] for run in ordered] == ["wf_first", "wf_second"]
    assert route == ROUTE


@pytest.mark.parametrize("defect", [
    "call_order", "initial_extra", "initial_url", "resume_seed", "resume_options",
    "status_schema", "status_slug", "status_ref", "stale_status", "missing_status",
    "extra_status", "wrong_status_route", "post_before_completion", "duplicate_completion", "wrong_run_id",
])
def test_coordinator_rejects_incomplete_contract(evidence, defect):
    rows, runs = evidence
    second, first = runs
    if defect == "call_order":
        rows[0], rows[6] = rows[6], rows[0]
    elif defect in ("initial_extra", "initial_url"):
        if defect == "initial_extra":
            first["args"]["extra"] = True
        else:
            first["args"]["seed"]["url"] = URL + "wrong"
        rows[0]["message"]["content"][0]["input"]["args"] = deepcopy(first["args"])
    elif defect.startswith("resume_"):
        if defect == "resume_seed":
            second["args"]["seed"] = {**second["args"]["seed"], "material_slug": "wrong"}
        else:
            second["args"]["options"] = {"extra": True}
        rows[6]["message"]["content"][0]["input"]["args"] = deepcopy(second["args"])
    elif defect in ("status_schema", "status_slug", "status_ref"):
        observation = second["args"]["observation"]
        if defect == "status_schema":
            observation["schema_version"] = "quasi.status/0.1"
        elif defect == "status_slug":
            observation["slug"] = "wrong"
        else:
            observation["facts"]["snapshot"]["path"] = "wrong"
        rows[6]["message"]["content"][0]["input"]["args"] = deepcopy(second["args"])
    elif defect == "stale_status":
        rows[5]["toolUseResult"]["stdout"] = json.dumps(status(True))
    elif defect == "missing_status":
        del rows[4:6]
    elif defect == "extra_status":
        rows.append(call("Bash", "extra", {"command": "quasi-status --kind webpage --slug fixture --json"}))
    elif defect == "wrong_status_route":
        rows[4]["message"]["content"][0]["input"]["command"] = "quasi-status --kind webpage --slug wrong --json"
    elif defect == "post_before_completion":
        rows[9], rows[10] = rows[10], rows[9]
    elif defect == "duplicate_completion":
        rows.append(deepcopy(rows[9]))
    else:
        rows[1]["toolUseResult"]["runId"] = "wf_wrong"
    with pytest.raises(pytest.fail.Exception):
        verify_coordinator(rows, runs, URL)


@pytest.mark.parametrize("journal", [
    [{"type": "started", "agentId": "a"}],
    [{"type": "started", "agentId": "a"}, {"type": "result", "agentId": "a"}, {"type": "result", "agentId": "a"}],
    [{"type": "started", "agentId": "a"}, {"type": "result", "agentId": "b"}],
    [{"type": "result", "agentId": "a"}, {"type": "started", "agentId": "a"}],
])
def test_journal_requires_unique_later_result(journal):
    with pytest.raises(pytest.fail.Exception):
        paired_starts(journal)


def test_journal_pairs_by_agent_id():
    starts = [{"type": "started", "agentId": "a"}, {"type": "started", "agentId": "b"}]
    assert paired_starts(starts + [{"type": "result", "agentId": "b"}, {"type": "result", "agentId": "a"}]) == starts


def specialist_rows(vault):
    refs = expected_refs("fixture")
    commands = [f"quasi-webpage inspect --url {URL} --json",
                f"quasi-webpage capture --url='{URL}' --expected-final-url {URL} "
                f"--output {refs['snapshot']} --json",
                f"quasi-webpage extract --snapshot {refs['snapshot']} --output {refs['prepared']} --json"]
    calls = [{"cwd": str(vault), **call("Bash", f"bash{i}", {"command": cmd})} for i, cmd in enumerate(commands)]
    results = []
    for i, name in enumerate(("inspect", "capture", "extract")):
        receipt = {"schema_version": f"quasi.webpage.{name}/0.1", "status": "complete", "final_url": URL, "title": "Fixture", "site": "Fixture Site"}
        if name == "inspect":
            receipt["url"] = URL
        else:
            receipt.update(sha256="a" * 64, size=100, write_state="written", output_path=refs["snapshot" if name == "capture" else "prepared"])
            if name == "capture":
                receipt.update(url=URL, captured_at="2026-09-21T12:00:00Z")
            if name == "extract":
                receipt["snapshot_path"] = refs["snapshot"]
        row = {"cwd": str(vault), **reply(f"bash{i}", {})}
        row["message"]["content"][0]["content"] = json.dumps(receipt)
        results.append(row)
    return calls + results


def owned_transcripts(rows):
    """Synthetic fixture ownership; production evidence uses journal labels."""
    owners = {"bash0": "identify", "bash1": "capture", "bash2": "prepare"}
    groups = {"webpage." + name: [{"cwd": rows[0].get("cwd"), "type": "user"}]
              for name in ("identify", "capture", "prepare", "analyse", "audit")}
    for row in rows:
        block = row["message"]["content"][0]
        owner = owners.get(block.get("id", block.get("tool_use_id")), "identify")
        groups["webpage." + owner].append(row)
    vault = rows[0].get("cwd")
    item = [{"kind": "webpage", **IDENTITY}]
    resolver = {"cwd": vault, **call("Bash", "resolver", {"command": "quasi-helpers vault resolve --items-json " + shlex.quote(json.dumps(item))})}
    result = {"cwd": vault, **reply("resolver", {})}
    result["message"]["content"][0]["content"] = json.dumps({"resolved": [{"kind": "webpage", "slug": "fixture", "vault_slug": None, "path": None, "match": None, "suggested_slug": "fixture"}], "scanned": {}})
    groups["webpage.identify"].extend([resolver, result])
    return groups


def test_specialist_literal_commands_preserve_request_relative_refs(tmp_path):
    verify_specialists(owned_transcripts(specialist_rows(tmp_path)), tmp_path, URL, ROUTE)


@pytest.mark.parametrize("defect", ["cwd", "missing_cwd", "url", "expected_url", "snapshot", "source", "duplicate_capture", "wrapper"])
def test_specialist_rejects_wrong_or_ambiguous_evidence(tmp_path, defect):
    rows = specialist_rows(tmp_path)
    if defect == "cwd":
        rows[1]["cwd"] = "/wrong"
    elif defect == "missing_cwd":
        del rows[0]["cwd"]
    else:
        row = rows[2] if defect in ("snapshot", "source") else rows[1]
        value = row["message"]["content"][0]["input"]
        if defect == "url":
            value["command"] = value["command"].replace(f"--url='{URL}'", "--url=https://wrong.example/")
        elif defect == "expected_url":
            value["command"] = value["command"].replace(f"--expected-final-url {URL}", "--expected-final-url https://wrong.example/")
        elif defect in ("snapshot", "source"):
            value["command"] = value["command"].replace("snapshot.webarchive" if defect == "snapshot" else "source.md", "wrong")
        elif defect == "duplicate_capture":
            value["command"] += "; " + value["command"]
        else:
            value["command"] = "echo " + shlex.quote(value["command"])
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert URL not in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_shell_parser_counts_chains_and_rejects_dynamic_arguments():
    parsed = commands("quasi-webpage inspect --url='http://localhost/x?a=1&b=2' --json")
    assert len(parsed) == 1
    assert parsed[0]["options"]["--url"] == "http://localhost/x?a=1&b=2"
    with pytest.raises(pytest.fail.Exception):
        commands('quasi-webpage capture --url "$URL" --json')


@pytest.mark.parametrize("directory", ["quasi-webpage-host-baseline", "quasi-webpage-host-with spaces"])
def test_artifact_existence_check_in_host_vault_is_not_an_opaque_cli(tmp_path, directory):
    vault = tmp_path / directory
    artifact = vault / expected_refs("fixture")["prepared"]
    probe = f"if [ -e {shlex.quote(str(artifact))} ]; then printf present; else printf absent; fi"
    assert commands(probe) == []
    rows = [{"cwd": str(vault), **call("Bash", "probe", {"command": probe})}, *specialist_rows(vault)]
    verify_specialists(owned_transcripts(rows), vault, URL, ROUTE)


@pytest.mark.parametrize("wrapper", [
    'echo "quasi-webpage capture --url https://example.org/ --json"',
    'bash -c "quasi-webpage capture --url https://example.org/ --json"',
    'bash -c "/source/bin/quasi-webpage inspect --url https://example.org/ --json"',
    'echo "quasi-status"',
    'bash -c "true;quasi-status --kind webpage --slug fixture --json"',
    "bash -c \"'/source/bin/quasi-webpage' inspect --url https://example.org/ --json\"",
])
def test_complete_cli_names_inside_opaque_wrappers_remain_rejected(wrapper):
    with pytest.raises(pytest.fail.Exception) as error:
        commands(wrapper)
    assert wrapper not in str(error.value)


@pytest.mark.parametrize("warning", [False, True])
@pytest.mark.parametrize("pretty", [False, True])
def test_status_stdout_accepts_only_optional_exact_warning_and_one_payload(warning, pretty):
    payload = status(True)
    raw = json.dumps(payload, indent=2 if pretty else None)
    if warning:
        raw = PYMUPDF_COMPAT_WARNING + "\n" + raw
    assert status_stdout(raw + "\n") == payload


@pytest.mark.parametrize("raw", [
    "", " \n\t", None, PYMUPDF_COMPAT_WARNING,
    PYMUPDF_COMPAT_WARNING + "\n" + PYMUPDF_COMPAT_WARNING + "\n" + json.dumps(status(True)),
    " " + PYMUPDF_COMPAT_WARNING + "\n" + json.dumps(status(True)),
    PYMUPDF_COMPAT_WARNING + " \n" + json.dumps(status(True)),
    PYMUPDF_COMPAT_WARNING.replace("deprecated", "PRIVATE_MARKER") + "\n" + json.dumps(status(True)),
    "PRIVATE_PREFIX\n" + json.dumps(status(True)),
    json.dumps(status(True)) + "\nPRIVATE_SUFFIX",
    json.dumps(status(True)) + "\n" + PYMUPDF_COMPAT_WARNING,
    json.dumps(status(True)) + "\n" + json.dumps(status(True)),
    json.dumps(status(True)) + json.dumps(status(True)),
    PYMUPDF_COMPAT_WARNING + "\n" + json.dumps(status(True)) + "\n{}",
    "null", "[]", "{}", '"PRIVATE_SCALAR"',
])
def test_status_stdout_rejects_other_output_without_echoing_it(raw):
    with pytest.raises(pytest.fail.Exception) as error:
        status_stdout(raw)
    assert str(error.value) == "Invalid status stdout; contents withheld"


def test_generic_task_output_json_remains_strict_and_accepts_pretty_json():
    raw = json.dumps({"result": {"terminal": "complete"}}, indent=2)
    assert json_value(raw)["result"]["terminal"] == "complete"
    with pytest.raises(pytest.fail.Exception):
        json_value(PYMUPDF_COMPAT_WARNING + "\n" + raw)


def test_coordinator_accepts_exact_compatibility_line_in_both_status_outputs(evidence):
    rows, runs = evidence
    for index in (5, 11):
        value = rows[index]["toolUseResult"]
        value["stdout"] = PYMUPDF_COMPAT_WARNING + "\n" + value["stdout"]
    assert verify_coordinator(rows, runs, URL)[1] == ROUTE


@pytest.mark.parametrize("operation", [0, 1, 2], ids=["inspect", "capture", "extract"])
@pytest.mark.parametrize("defect", ["missing", "duplicate_row", "duplicate_block", "error", "before_call"])
def test_specialist_requires_unique_later_nonerror_tool_result(tmp_path, operation, defect):
    rows = specialist_rows(tmp_path)
    result_index = 3 + operation
    if defect == "missing":
        del rows[result_index]
    elif defect == "duplicate_row":
        rows.append(deepcopy(rows[result_index]))
    elif defect == "duplicate_block":
        content = rows[result_index]["message"]["content"]
        content.append(deepcopy(content[0]))
    elif defect == "error":
        rows[result_index]["message"]["content"][0].update(is_error=True, content="PRIVATE_TOOL_ERROR")
    else:
        rows.insert(0, rows.pop(result_index))
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert "PRIVATE_TOOL_ERROR" not in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_specialist_allows_tool_result_without_optional_is_error(tmp_path):
    rows = specialist_rows(tmp_path)
    for row in rows[3:]:
        del row["message"]["content"][0]["is_error"]
    verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)


PRIVATE_NOTIFICATION_MARKER = "PRIVATE_NOTIFICATION_CONTENT"


def notification(task_id, event_id, result):
    root = ElementTree.Element("task-notification")
    for name, text in {"task-id": task_id, "tool-use-id": event_id,
                       "status": "completed", "result": json.dumps(result)}.items():
        ElementTree.SubElement(root, name).text = text
    return {"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "sdk",
            "message": {"role": "user", "content": ElementTree.tostring(root, encoding="unicode")}}


@pytest.fixture
def notification_evidence(evidence):
    rows, runs = evidence
    converted = []
    for offset, run in zip((0, 6), reversed(runs)):
        converted.extend([rows[offset], rows[offset + 1],
                          notification(f"task{offset // 6}", f"wf{offset // 6}", run["result"]),
                          rows[offset + 4], rows[offset + 5]])
    return converted, runs


def test_consumed_notification_proves_completion_at_user_row(notification_evidence):
    rows, runs = notification_evidence
    queued = deepcopy(rows[2])
    queued["type"] = "queue-operation"
    rows.insert(2, queued)
    calls = events(rows, "Workflow")
    assert completed_at(rows, calls[0], runs[1]) == 3
    assert completed_at(rows, calls[1], runs[0]) == 8
    assert verify_coordinator(rows, runs, URL)[1] == ROUTE


def test_notification_allows_nonbinding_diagnostics_and_usage(notification_evidence):
    rows, runs = notification_evidence
    root = ElementTree.fromstring(rows[2]["message"]["content"])
    diagnostics = ElementTree.SubElement(root, "diagnostics", {"format": "future"})
    ElementTree.SubElement(diagnostics, "message").text = "additional diagnostic"
    ElementTree.SubElement(root, "usage", {"tokens": "123"})
    rows[2]["message"]["content"] = ElementTree.tostring(root, encoding="unicode")
    assert verify_coordinator(rows, runs, URL)[1] == ROUTE


@pytest.mark.parametrize("field", ["task-id", "tool-use-id", "status", "result"])
@pytest.mark.parametrize("defect", ["wrong", "missing", "duplicate", "attribute", "nested", "child_bearing", "nested_duplicate", "empty"])
def test_notification_rejects_ambiguous_or_wrong_binding(notification_evidence, field, defect):
    rows, runs = notification_evidence
    root = ElementTree.fromstring(rows[2]["message"]["content"])
    node = root.find(field)
    if defect == "wrong":
        node.text = json.dumps({"private": PRIVATE_NOTIFICATION_MARKER}) if field == "result" else PRIVATE_NOTIFICATION_MARKER
    elif defect == "missing":
        root.remove(node)
    elif defect == "duplicate":
        root.append(deepcopy(node))
    elif defect == "attribute":
        node.set("private", PRIVATE_NOTIFICATION_MARKER)
    elif defect == "nested":
        root.remove(node)
        ElementTree.SubElement(root, "diagnostics").append(node)
    elif defect == "child_bearing":
        text = node.text
        node.text = None
        ElementTree.SubElement(node, "nested").text = text
    elif defect == "nested_duplicate":
        ElementTree.SubElement(root, "diagnostics").append(deepcopy(node))
    else:
        node.text = ""
    rows[2]["message"]["content"] = ElementTree.tostring(root, encoding="unicode")
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert PRIVATE_NOTIFICATION_MARKER not in str(error.value)


@pytest.mark.parametrize("defect", [
    "queue_only", "wrong_origin", "extra_origin", "missing_origin", "wrong_role", "non_user",
    "wrong_source", "non_string", "before_launch_result", "duplicate_consumed", "malformed_xml",
    "arbitrary_text", "wrong_root", "root_attribute", "mixed_text", "status_before_delivery",
])
def test_notification_requires_unambiguous_consumed_sdk_user_delivery(notification_evidence, defect):
    rows, runs = notification_evidence
    row = rows[2]
    if defect == "queue_only":
        row["type"] = "queue-operation"
    elif defect == "wrong_origin":
        row["origin"] = {"kind": "other"}
    elif defect == "extra_origin":
        row["origin"]["extra"] = True
    elif defect == "missing_origin":
        del row["origin"]
    elif defect == "wrong_role":
        row["message"]["role"] = "assistant"
    elif defect == "non_user":
        row["type"] = "assistant"
    elif defect == "wrong_source":
        row["promptSource"] = "other"
    elif defect == "non_string":
        row["message"]["content"] = [{"type": "text", "text": row["message"]["content"]}]
    elif defect == "before_launch_result":
        rows[1], rows[2] = rows[2], rows[1]
    elif defect == "duplicate_consumed":
        rows.insert(3, deepcopy(row))
    elif defect == "malformed_xml":
        row["message"]["content"] = "<task-notification>" + PRIVATE_NOTIFICATION_MARKER
    elif defect == "arbitrary_text":
        row["message"]["content"] = PRIVATE_NOTIFICATION_MARKER
    elif defect == "status_before_delivery":
        rows[2], rows[3] = rows[3], rows[2]
    else:
        root = ElementTree.fromstring(row["message"]["content"])
        if defect == "wrong_root":
            root.tag = "not-a-notification"
        elif defect == "root_attribute":
            root.set("private", PRIVATE_NOTIFICATION_MARKER)
        else:
            root.text = PRIVATE_NOTIFICATION_MARKER
        row["message"]["content"] = ElementTree.tostring(root, encoding="unicode")
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert PRIVATE_NOTIFICATION_MARKER not in str(error.value)
    if defect in ("malformed_xml", "arbitrary_text"):
        assert str(error.value) == "Invalid task-notification XML; contents withheld"


@pytest.mark.parametrize("other_channel", ["inline", "task_output"])
def test_notification_cannot_compete_with_another_completion_channel(notification_evidence, other_channel):
    rows, runs = notification_evidence
    if other_channel == "inline":
        rows[1]["toolUseResult"]["result"] = deepcopy(runs[1]["result"])
    else:
        rows[2:2] = [call("TaskOutput", "extra_wait", {"task_id": "task0"}),
                     reply("extra_wait", {"retrieval_status": "success", "task": {"task_type": "local_workflow", "description": "fixture", "task_id": "task0", "status": "completed",
                          "output": json.dumps(completion_output(runs[1]["result"]))}})]
    with pytest.raises(pytest.fail.Exception, match="Missing unique completed Workflow"):
        verify_coordinator(rows, runs, URL)


def test_inline_result_retains_synchronous_completion_semantics(evidence):
    rows, runs = evidence
    converted = []
    for offset, run in zip((0, 6), reversed(runs)):
        rows[offset + 1]["toolUseResult"]["result"] = deepcopy(run["result"])
        converted.extend([rows[offset], rows[offset + 1], rows[offset + 4], rows[offset + 5]])
    assert completed_at(converted, events(converted, "Workflow")[0], runs[1]) == 1
    assert verify_coordinator(converted, runs, URL)[1] == ROUTE


def test_inline_and_task_output_are_not_two_acceptable_completions(evidence):
    rows, runs = evidence
    rows[1]["toolUseResult"]["result"] = deepcopy(runs[1]["result"])
    with pytest.raises(pytest.fail.Exception, match="Missing unique completed Workflow"):
        verify_coordinator(rows, runs, URL)


@pytest.mark.parametrize("defect", ["both_ids_wrong", "malformed_result_json"])
def test_notification_rejects_unbound_or_malformed_result_without_leaking(notification_evidence, defect):
    rows, runs = notification_evidence
    root = ElementTree.fromstring(rows[2]["message"]["content"])
    if defect == "both_ids_wrong":
        root.find("task-id").text = "PRIVATE_WRONG_TASK_ID"
        root.find("tool-use-id").text = "PRIVATE_WRONG_TOOL_USE_ID"
        expected = "Missing unique completed Workflow retrieval or delivery"
    else:
        root.find("result").text = "{PRIVATE_MALFORMED_RESULT_JSON"
        expected = "Invalid evidence JSON; contents withheld"
    rows[2]["message"]["content"] = ElementTree.tostring(root, encoding="unicode")
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert str(error.value) == expected
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize("output", [
    "$output", "${CLAUDE_PROJECT_DIR:-$PWD}/vault/webpages/fixture/snapshot.webarchive",
    "$root/vault/webpages/fixture/snapshot.webarchive", "$(pwd)/vault/webpages/fixture/snapshot.webarchive",
    "`pwd`/vault/webpages/fixture/snapshot.webarchive",
])
def test_capture_shell_derived_ref_is_rejected_even_with_successful_receipt(tmp_path, output):
    rows = specialist_rows(tmp_path)
    rows[1]["message"]["content"][0]["input"]["command"] = (
        f'quasi-webpage capture --url {URL} --expected-final-url {URL} --output "{output}" --json'
    )
    rows[4]["message"]["content"][0]["content"] = json.dumps({
        "status": "complete", "output_path": str(tmp_path / expected_refs("fixture")["snapshot"]),
    })
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert str(error.value) == "Dynamic CLI arguments cannot prove exact refs"
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize("operation,flag,role", [
    (1, "--output", "snapshot"), (2, "--snapshot", "snapshot"), (2, "--output", "prepared"),
])
def test_equivalent_absolute_argv_is_not_the_request_spelling(tmp_path, operation, flag, role):
    rows = specialist_rows(tmp_path)
    ref = expected_refs("fixture")[role]
    command = rows[operation]["message"]["content"][0]["input"]
    command["command"] = command["command"].replace(f"{flag} {ref}", f"{flag} {tmp_path / ref}")
    with pytest.raises(pytest.fail.Exception, match="literal URL/ref spelling"):
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)


@pytest.mark.parametrize("owner", ["webpage.identify", "webpage.prepare", "webpage.analyse", "webpage.audit"])
def test_capture_in_wrong_owner_transcript_is_rejected(tmp_path, owner):
    groups = owned_transcripts(specialist_rows(tmp_path))
    groups[owner], groups["webpage.capture"] = groups["webpage.capture"], groups[owner]
    with pytest.raises(pytest.fail.Exception):
        verify_specialists(groups, tmp_path, URL, ROUTE)


@pytest.mark.parametrize("operation", [0, 1, 2], ids=["inspect", "capture", "extract"])
@pytest.mark.parametrize("defect", ["failed", "schema", "malformed", "multiple", "not_object", "wrong_ref", "final_url", "write_state"])
def test_cli_receipt_must_prove_its_exact_success_contract(tmp_path, operation, defect):
    rows = specialist_rows(tmp_path)
    block = rows[3 + operation]["message"]["content"][0]
    receipt = json.loads(block["content"])
    if defect == "failed":
        receipt["status"] = "failed"
    elif defect == "schema":
        receipt["schema_version"] = "PRIVATE_WRONG_SCHEMA"
    elif defect == "wrong_ref":
        receipt["url" if operation == 0 else "output_path"] = "PRIVATE_WRONG_REF"
    elif defect == "final_url":
        receipt["final_url"] = "PRIVATE_WRONG_URL"
    elif defect == "write_state":
        receipt["status" if operation == 0 else "write_state"] = "PRIVATE_WRONG_STATE"
    block["content"] = json.dumps(receipt)
    if defect == "malformed":
        block["content"] = "{PRIVATE_BAD_JSON"
    elif defect == "multiple":
        block["content"] += '\n{"PRIVATE_EXTRA":true}'
    elif defect == "not_object":
        block["content"] = '["PRIVATE_ARRAY"]'
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize("suffix", ["; true", " || true", " && true", " | cat", "; printf done"])
def test_masked_cli_suffix_is_rejected(tmp_path, suffix):
    rows = specialist_rows(tmp_path)
    rows[1]["message"]["content"][0]["input"]["command"] += suffix
    with pytest.raises(pytest.fail.Exception, match="single bare simple command"):
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)


@pytest.mark.parametrize("mutation", ["input", "name"])
def test_events_reject_conflicting_duplicate_ids_across_tool_names(mutation):
    first = call("Workflow", "same-id", {"args": {}})
    duplicate = deepcopy(first)
    block = duplicate["message"]["content"][0]
    if mutation == "input":
        block["input"] = {"PRIVATE_CHANGED": True}
    else:
        block["name"] = "Bash"
    for name in ("Workflow", "Bash"):
        with pytest.raises(pytest.fail.Exception) as error:
            events([first, duplicate], name)
        assert str(error.value) == "Conflicting duplicate tool id; contents withheld"


def test_events_deduplicate_only_identical_host_replay():
    first = call("Bash", "same-id", {"command": "true"})
    assert events([first, deepcopy(first)], "Bash") == events([first], "Bash")


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_cli_receipt_rejects_ambiguous_nonstandard_json(raw):
    with pytest.raises(pytest.fail.Exception, match="Invalid evidence JSON"):
        cli_receipt(raw)


def test_extract_receipt_requires_exact_snapshot_ref(tmp_path):
    rows = specialist_rows(tmp_path)
    block = rows[5]["message"]["content"][0]
    receipt = json.loads(block["content"])
    receipt["snapshot_path"] = "PRIVATE_WRONG_SNAPSHOT"
    block["content"] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize("command", [
    "builtin cd /tmp; quasi-webpage inspect --json",
    "command cd /tmp; quasi-webpage inspect --json",
    "pushd /tmp; quasi-webpage inspect --json",
    "popd; quasi-status --json", "true && quasi-status --json",
    "PATH=/tmp quasi-webpage inspect --json", "env quasi-status --json",
    "/tmp/quasi-webpage inspect --json", "./quasi-status --json",
    "command quasi-status --json", "builtin quasi-status --json",
    "eval 'quasi-status --json'", "source quasi-status --json",
    "bash -c 'quasi-status --json'", "quasi-status --json; true",
    "quasi-status --json > /tmp/output",
])
def test_capability_requires_single_bare_checkout_shim(command):
    with pytest.raises(pytest.fail.Exception):
        commands(command)


@pytest.mark.parametrize("reader", ["json_value", "status_stdout", "cli_receipt", "records", "read_json"])
@pytest.mark.parametrize("raw", [
    '{"outer":{"PRIVATE_DUP":1,"PRIVATE_DUP":2}}',
    '{"outer":[{"v":NaN}]}', '{"outer":{"v":Infinity}}',
    '{"outer":{"v":-Infinity}}', 'PRIVATE_MALFORMED',
])
def test_all_evidence_json_readers_reject_ambiguity_redacted(tmp_path, reader, raw):
    import test_webpage_host_e2e as parser
    target = raw
    if reader in ("records", "read_json"):
        target = tmp_path / "evidence.json"
        target.write_text(raw)
    with pytest.raises(pytest.fail.Exception) as error:
        getattr(parser, reader)(target)
    assert "PRIVATE_" not in str(error.value)
    assert raw not in str(error.value)


def test_strict_json_accepts_nested_distinct_objects():
    from test_webpage_host_e2e import strict_json
    assert strict_json('{"a":{"x":1},"b":[{"x":2}]}') == {"a": {"x": 1}, "b": [{"x": 2}]}


@pytest.mark.parametrize("raw", ['{"outer":{"PRIVATE_KEY":1,"PRIVATE_KEY":2}}', '{"outer":[NaN]}'])
def test_taskoutput_strict_json_rejects_nested_ambiguity(evidence, raw):
    rows, runs = evidence
    rows[3]["toolUseResult"]["task"]["output"] = raw
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize("raw", ['{"outer":{"PRIVATE_KEY":1,"PRIVATE_KEY":2}}', '{"outer":[Infinity]}'])
def test_notification_strict_json_rejects_nested_ambiguity(notification_evidence, raw):
    rows, runs = notification_evidence
    root = ElementTree.fromstring(rows[2]["message"]["content"])
    root.find("result").text = raw
    rows[2]["message"]["content"] = ElementTree.tostring(root, encoding="unicode")
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize('defect', [
    'orphan_both', 'wrong_name', 'wrong_call_task', 'wrong_result_task', 'early_call',
    'early_result', 'duplicate_call', 'duplicate_result', 'error_result',
    'wrong_status', 'wrong_output', 'wrong_run',
])
def test_taskoutput_requires_real_bound_call_and_nonerror_result(evidence, defect):
    rows, runs = evidence
    if defect == 'orphan_both':
        rows[:] = [r for r in rows if not any(b.get('name') == 'TaskOutput'
                   for b in r.get('message', {}).get('content', []) if isinstance(b, dict))]
    elif defect == 'wrong_name':
        rows[2]['message']['content'][0]['name'] = 'PRIVATE_NOT_TaskOutput'
    elif defect == 'wrong_call_task':
        rows[2]['message']['content'][0]['input']['task_id'] = 'PRIVATE_WRONG'
    elif defect == 'wrong_result_task':
        rows[3]['toolUseResult']['task']['task_id'] = 'PRIVATE_WRONG'
    elif defect == 'early_call':
        rows[1], rows[2] = rows[2], rows[1]
    elif defect == 'early_result':
        rows[2], rows[3] = rows[3], rows[2]
    elif defect == 'duplicate_call':
        rows.insert(3, call('TaskOutput', 'second-wait', {'task_id': 'task0'}))
    elif defect == 'duplicate_result':
        rows.insert(4, deepcopy(rows[3]))
    elif defect == 'error_result':
        rows[3]['message']['content'][0]['is_error'] = True
    elif defect == 'wrong_status':
        rows[3]['toolUseResult']['task']['status'] = 'running'
    elif defect == 'wrong_output':
        rows[3]['toolUseResult']['task']['output'] = '{"result":"PRIVATE_WRONG"}'
    else:
        rows[3]['toolUseResult']['task']['runId'] = 'PRIVATE_WRONG'
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('index', [1, 5, 7, 11])
def test_coordinator_rejects_error_launch_and_status_even_with_valid_payload(evidence, index):
    rows, runs = evidence
    rows[index]['message']['content'][0].update(is_error=True, content='PRIVATE_ERROR')
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('operation', [0, 1, 2])
@pytest.mark.parametrize('defect', ['extra', 'missing', 'null_title', 'integer_site', 'empty_title', 'unnormalized_site'])
def test_closed_cli_receipt_common_fields(tmp_path, operation, defect):
    rows = specialist_rows(tmp_path)
    block = rows[operation + 3]['message']['content'][0]
    receipt = json.loads(block['content'])
    if defect == 'extra': receipt['PRIVATE_EXTRA'] = 'PRIVATE_CONTENT'
    elif defect == 'missing': del receipt['site']
    elif defect == 'null_title': receipt['title'] = None
    elif defect == 'integer_site': receipt['site'] = 123
    elif defect == 'empty_title': receipt['title'] = ''
    else: receipt['site'] = ' bad  spacing '
    block['content'] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('operation', [1, 2])
@pytest.mark.parametrize('key,value', [('size', True), ('size', 0), ('size', -1), ('size', 1.5),
    ('size', '100'), ('sha256', 'A' * 64), ('sha256', 'a' * 63), ('sha256', None)])
def test_closed_cli_receipt_digest_and_size(tmp_path, operation, key, value):
    rows = specialist_rows(tmp_path)
    block = rows[operation + 3]['message']['content'][0]
    receipt = json.loads(block['content']); receipt[key] = value
    block['content'] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception):
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)


@pytest.mark.parametrize('value', [None, 'PRIVATE_DATE', '2026-02-30T00:00:00Z',
    '2026-09-21T12:00:00+00:00', '2026-9-21T12:00:00Z', '2026-09-21T12:00:00.123Z'])
def test_closed_capture_timestamp(tmp_path, value):
    rows = specialist_rows(tmp_path)
    block = rows[4]['message']['content'][0]
    receipt = json.loads(block['content']); receipt['captured_at'] = value
    block['content'] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('key', ['title', 'site'])
def test_extract_receipt_cannot_contradict_snapshot_metadata(tmp_path, key):
    rows = specialist_rows(tmp_path)
    block = rows[5]['message']['content'][0]
    receipt = json.loads(block['content']); receipt[key] = 'PRIVATE_WRONG'
    block['content'] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(owned_transcripts(rows), tmp_path, URL, ROUTE)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('mutation', [
    'extra', 'missing', 'facts_extra', 'facts_missing', 'present_int', 'usable_int',
    'artifact_extra', 'artifact_missing', 'usable_not_present', 'timestamp_none',
    'timestamp_fraction', 'timestamp_invalid', 'identity_extra', 'identity_missing',
    'identity_slug', 'identity_title', 'identity_site', 'identity_url',
])
def test_status_closed_parser_rejects_mutations(mutation):
    from test_webpage_host_e2e import check_status
    value = status(True)
    value['identity'] = dict(slug='fixture', title='Fixture', site='Fixture', url=URL)
    facts = value['facts']; identity = value['identity']
    if mutation == 'extra': value['PRIVATE_EXTRA'] = 'secret'
    elif mutation == 'missing': del value['identity']
    elif mutation == 'facts_extra': facts['PRIVATE_EXTRA'] = 'secret'
    elif mutation == 'facts_missing': del facts['captured_at']
    elif mutation == 'present_int': facts['snapshot']['present'] = 1
    elif mutation == 'usable_int': facts['snapshot']['usable'] = 1
    elif mutation == 'artifact_extra': facts['snapshot']['PRIVATE_EXTRA'] = 1
    elif mutation == 'artifact_missing': del facts['snapshot']['path']
    elif mutation == 'usable_not_present': facts['snapshot']['present'] = False
    elif mutation == 'timestamp_none': facts['captured_at'] = None
    elif mutation == 'timestamp_fraction': facts['captured_at'] = '2026-09-21T00:00:00.000Z'
    elif mutation == 'timestamp_invalid': facts['captured_at'] = '2026-02-30T00:00:00Z'
    elif mutation == 'identity_extra': identity['PRIVATE_EXTRA'] = 'secret'
    elif mutation == 'identity_missing': del identity['site']
    elif mutation == 'identity_slug': identity['slug'] = 'wrong'
    elif mutation == 'identity_title': identity['title'] = 'x' * 501
    elif mutation == 'identity_site': identity['site'] = None
    else: identity['url'] = 'https://PRIVATE_SECRET@example.org/'
    with pytest.raises(pytest.fail.Exception) as error:
        check_status(value, ROUTE, usable=True)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('command', [
    'python -m scripts.webpage.webpage capture --url x',
    'python scripts/webpage/webpage.py capture --url x',
    '/tmp/quasi-webpage-webkit-abc capture x y',
    'swift scripts/webpage/webpage_capture.swift capture x y',
    'quasi-status --kind webpage --slug fixture --json',
    '/tmp/quasi-webpage capture --url x',
])
def test_specialists_reject_other_writer_and_status_entrypoints(tmp_path, command):
    groups = owned_transcripts(specialist_rows(tmp_path))
    groups['webpage.capture'].append({'cwd': str(tmp_path), **call('Bash', 'hidden', {'command': command})})
    with pytest.raises(pytest.fail.Exception):
        verify_specialists(groups, tmp_path, URL, ROUTE)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'wrong_owner', 'result_error', 'bad_url',
    'bad_slug', 'extra', 'owner', 'suggestion', 'missing_key', 'bad_final_identity'])
def test_resolver_is_required_and_bound_to_fresh_identity(tmp_path, defect):
    groups = owned_transcripts(specialist_rows(tmp_path))
    rows = groups['webpage.identify']; callrow, resultrow = rows[-2:]
    identity = dict(slug='fixture', url=URL, title='Fixture', site='Fixture Site')
    if defect == 'missing': del rows[-2:]
    elif defect == 'duplicate':
        duplicate = deepcopy(callrow); duplicate['message']['content'][0]['id'] = 'resolver2'; rows.append(duplicate)
    elif defect == 'wrong_owner': groups['webpage.capture'].extend(rows[-2:]); del rows[-2:]
    elif defect == 'result_error': resultrow['message']['content'][0]['is_error'] = True
    elif defect in ('bad_url', 'bad_slug'):
        item = dict(kind='webpage', slug='fixture', url=URL)
        item['url' if defect == 'bad_url' else 'slug'] = 'PRIVATE_WRONG'
        callrow['message']['content'][0]['input']['command'] = 'quasi-helpers vault resolve --items-json ' + shlex.quote(json.dumps([item]))
    elif defect == 'bad_final_identity': identity['title'] = 'PRIVATE_WRONG'
    else:
        block = resultrow['message']['content'][0]; receipt = json.loads(block['content'])
        if defect == 'extra': receipt['PRIVATE_EXTRA'] = 'secret'
        elif defect == 'owner': receipt['resolved'][0]['vault_slug'] = 'PRIVATE_OWNER'
        elif defect == 'suggestion': receipt['resolved'][0]['suggested_slug'] = 'PRIVATE_WRONG'
        else: del receipt['resolved'][0]['path']
        block['content'] = json.dumps(receipt)
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(groups, tmp_path, URL, ROUTE, identity)
    assert 'PRIVATE_' not in str(error.value)


def test_resolver_receipt_matches_actual_capability(tmp_path):
    from scripts.vault.resolve import resolve
    groups = owned_transcripts(specialist_rows(tmp_path))
    items = [dict(kind='webpage', **IDENTITY)]
    row = groups['webpage.identify'][-1]
    row['message']['content'][0]['content'] = json.dumps(resolve(tmp_path, items))
    command = groups['webpage.identify'][-2]['message']['content'][0]['input']
    command['command'] = "quasi-helpers vault resolve --items-json " + shlex.quote(json.dumps(items))
    verify_specialists(groups, tmp_path, URL, ROUTE, dict(slug='fixture', url=URL, title='Fixture', site='Fixture Site'))


@pytest.mark.parametrize('field', ['null', 'url', 'title', 'site', 'slug'])
def test_completed_status_identity_provenance(evidence, field):
    from test_webpage_host_e2e import check_status
    rows, runs = evidence
    value = status(True)
    if field == 'null': value['identity'] = None
    else: value['identity'][field] = 'https://private.example/' if field == 'url' else 'PRIVATE_WRONG'
    rows[-1]['toolUseResult']['stdout'] = json.dumps(value)
    for check in (lambda: verify_coordinator(rows, runs, URL),
                  lambda: check_status(value, ROUTE, usable=True, expected_identity=IDENTITY)):
        with pytest.raises(pytest.fail.Exception) as error: check()
        assert 'PRIVATE_' not in str(error.value) and 'private.example' not in str(error.value)


@pytest.mark.parametrize('defect', ['before_call', 'before_result', 'wrong_title', 'wrong_site', 'missing_title'])
def test_resolver_requires_prior_exact_inspect_testimony(tmp_path, defect):
    groups = owned_transcripts(specialist_rows(tmp_path)); rows = groups['webpage.identify']
    if defect.startswith('before'):
        resolver = rows.pop(-2)
        rows.insert(1 if defect == 'before_call' else 2, resolver)
    else:
        item = {'kind': 'webpage', **IDENTITY}
        if defect == 'missing_title': del item['title']
        else: item[defect.removeprefix('wrong_')] = 'PRIVATE_SOURCE'
        rows[-2]['message']['content'][0]['input']['command'] = 'quasi-helpers vault resolve --items-json ' + shlex.quote(json.dumps([item]))
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(groups, tmp_path, URL, ROUTE)
    assert 'PRIVATE_SOURCE' not in str(error.value)


@pytest.mark.parametrize('complete', [False, True])
@pytest.mark.parametrize('defect', ['missing', 'extra', 'wrong_type', 'requested', 'canonical', 'issue', 'continuation', 'nested_extra', 'private'])
def test_material_result_closed_variants(evidence, complete, defect):
    rows, runs = evidence
    result = runs[0 if complete else 1]['result']
    if defect == 'missing': del result['material']
    elif defect == 'extra': result['PRIVATE_EXTRA'] = 'secret'
    elif defect == 'wrong_type': result['material'] = []
    elif defect == 'requested': result['material']['requested']['slug'] = 'wrong'
    elif defect == 'canonical': result['material']['canonical'] = {'kind': 'paper', 'slug': 'fixture'}
    elif defect == 'issue': result['issue'] = {'code': 'PRIVATE_ISSUE'}
    elif defect == 'nested_extra': result['material']['requested']['PRIVATE_EXTRA'] = True
    elif defect == 'private': result['artifacts' if complete else 'routes'] = 'PRIVATE_CONTENT'
    elif complete: result['next'] = {'kind': 'webpage', 'url': URL}
    else: result['routes'] = [{'kind': 'webpage', 'slug': 'other'}]
    # Keep delivery equal to sidecar: rejection must be the material contract.
    rows[9 if complete else 3]['toolUseResult']['task']['output'] = json.dumps(completion_output(result))
    with pytest.raises(pytest.fail.Exception) as error:
        verify_coordinator(rows, runs, URL)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('operation,agent_type,phase', [
    ('identify', 'webpage', 'Search'), ('capture', 'webpage', 'Acquire'), ('prepare', 'webpage', 'Prepare'),
    ('analyse', 'analyse', 'Analyse'), ('audit', 'audit', 'Audit')])
@pytest.mark.parametrize('defect', [None, 'missing', 'wrong_type', 'conflict', 'extra', 'duplicate_key'])
def test_specialist_metadata_owner_binding(tmp_path, operation, agent_type, phase, defect):
    from test_webpage_host_e2e import verify_agent_metadata
    entry = {'agentId': 'agent1', 'label': 'fixture:webpage.' + operation}
    value = {'agentType': 'quasi:' + agent_type + '-agent', 'description': entry['label'],
             'workflowPhase': phase, 'spawnDepth': 1, 'requestShape': 'foreground', 'requestNonInteractive': True}
    if defect == 'wrong_type': value['agentType'] = 'PRIVATE_AGENT'
    elif defect == 'conflict': value['description'] = 'PRIVATE_WRONG_RUN'
    elif defect == 'extra': value['PRIVATE_EXTRA'] = True
    raw = json.dumps(value)
    if defect == 'duplicate_key': raw = raw[:-1] + ', "agentType":"PRIVATE_DUPLICATE"}'
    if defect != 'missing': (tmp_path / 'agent-agent1.meta.json').write_text(raw)
    if defect is None: verify_agent_metadata(tmp_path, entry, 'webpage.' + operation)
    else:
        with pytest.raises(pytest.fail.Exception) as error:
            verify_agent_metadata(tmp_path, entry, 'webpage.' + operation)
        assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('defect', [None, 'extra_metadata', 'missing_transcript', 'wrong_agent', 'wrong_session'])
def test_run_scoped_metadata_inventory_and_transcript_binding(tmp_path, defect):
    from test_webpage_host_e2e import verify_run_agents
    entry = {'agentId': 'one', 'label': 'fixture:webpage.identify'}
    meta = {'agentType': 'quasi:webpage-agent', 'description': entry['label'], 'workflowPhase': 'Search',
            'spawnDepth': 1, 'requestShape': 'foreground', 'requestNonInteractive': True}
    (tmp_path / 'agent-one.meta.json').write_text(json.dumps(meta))
    if defect == 'extra_metadata': (tmp_path / 'agent-extra.meta.json').write_text(json.dumps(meta))
    row = {'agentId': 'PRIVATE_WRONG' if defect == 'wrong_agent' else 'one',
           'sessionId': 'PRIVATE_WRONG' if defect == 'wrong_session' else 'session'}
    if defect != 'missing_transcript': (tmp_path / 'agent-one.jsonl').write_text(json.dumps(row))
    if defect is None: assert set(verify_run_agents(tmp_path, [entry], 'session')) == {'webpage.identify'}
    else:
        with pytest.raises(pytest.fail.Exception) as error: verify_run_agents(tmp_path, [entry], 'session')
        assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('number', ['1e9999', '-1e9999'])
@pytest.mark.parametrize('channel', ['task_outer', 'task_nested', 'notification', 'status', 'receipt', 'session', 'sidecar', 'metadata'])
def test_all_evidence_rejects_exponent_overflow_redacted(tmp_path, evidence, number, channel):
    from test_webpage_host_e2e import read_json, records, json_value, status_stdout, cli_receipt
    rows, runs = evidence
    raw = '{"PRIVATE_MARKER":[{"nested":' + number + '}]}'
    if channel.startswith('task'):
        result = deepcopy(runs[1]['result'])
        output = completion_output(result)
        if channel == 'task_outer': output['PRIVATE_MARKER'] = 'OVERFLOW'
        else: output['result']['PRIVATE_MARKER'] = [{'nested': 'OVERFLOW'}]
        rows[3]['toolUseResult']['task']['output'] = json.dumps(output).replace('"OVERFLOW"', number)
        check = lambda: verify_coordinator(rows, runs, URL)
    elif channel in ('session', 'sidecar', 'metadata'):
        path = tmp_path / 'evidence.json'; path.write_text(raw)
        check = lambda: records(path) if channel == 'session' else read_json(path)
    else:
        check = lambda: {'notification': json_value, 'status': status_stdout, 'receipt': cli_receipt}[channel](raw)
    with pytest.raises((pytest.fail.Exception, ValueError)) as error: check()
    assert 'PRIVATE_MARKER' not in str(error.value) and number not in str(error.value)


@pytest.mark.parametrize('defect', ['extra', 'missing', 'compact', 'wrong_count', 'task_extra', 'retrieval_extra'])
def test_taskoutput_closed_real_host_envelope(evidence, defect):
    rows, runs = evidence
    value = rows[3]['toolUseResult']; output = json.loads(value['task']['output'])
    if defect == 'extra': output['PRIVATE_EXTRA'] = 1
    elif defect == 'missing': del output['summary']
    elif defect == 'compact': output = {'result': runs[1]['result']}
    elif defect == 'wrong_count': output['agentCount'] = True
    elif defect == 'task_extra': value['task']['PRIVATE_EXTRA'] = 1
    else: value['PRIVATE_EXTRA'] = 1
    value['task']['output'] = json.dumps(output)
    with pytest.raises(pytest.fail.Exception) as error: verify_coordinator(rows, runs, URL)
    assert 'PRIVATE_' not in str(error.value)


@pytest.mark.parametrize('missing_metadata', [False, True])
@pytest.mark.parametrize('attempts', [1, 2])
def test_observed_pipe_resolver_is_rejected_without_replay(tmp_path, missing_metadata, attempts):
    groups = owned_transcripts(specialist_rows(tmp_path))
    rows = groups['webpage.identify']
    item = {'kind': 'webpage', **IDENTITY}
    if missing_metadata:
        del item['title']; del item['site']
    item['url'] = URL + '?PRIVATE_PIPE_EVIDENCE'
    command = "printf '%s\\n' " + shlex.quote(json.dumps([item])) + " | quasi-helpers vault resolve --items-file -"
    # Reject the wrapper itself, independent of item metadata or result binding.
    with pytest.raises(pytest.fail.Exception):
        commands(command)
    rows[-2]['message']['content'][0]['input']['command'] = command
    if attempts == 2:
        retry_call, retry_result = deepcopy(rows[-2:])
        retry_call['message']['content'][0]['id'] = 'resolver-repair'
        retry_result['message']['content'][0]['tool_use_id'] = 'resolver-repair'
        rows.extend([retry_call, retry_result])
    with pytest.raises(pytest.fail.Exception) as error:
        verify_specialists(groups, tmp_path, URL, ROUTE, IDENTITY)
    assert 'PRIVATE_PIPE_EVIDENCE' not in str(error.value)


def test_resolver_stdin_heredoc_is_not_a_direct_literal_argv(tmp_path):
    groups = owned_transcripts(specialist_rows(tmp_path))
    groups['webpage.identify'][-2]['message']['content'][0]['input']['command'] = (
        "quasi-helpers vault resolve --items-file - <<'JSON'\n" + json.dumps([{'kind': 'webpage', **IDENTITY}]) + '\nJSON')
    with pytest.raises(pytest.fail.Exception):
        verify_specialists(groups, tmp_path, URL, ROUTE, IDENTITY)
