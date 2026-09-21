from __future__ import annotations

from copy import deepcopy

from test_archive_plan import IDENTITY, URL, SLUG, PATH, COMPLETE, archive_observation
from test_topic_plan import (QUERY, SUBQUESTION, topic_input, topic_observation, paper_member,
    run_topic, recall_complete, steer_complete, web_task, webcard_complete, synthesis_complete)
from test_material_plans import audit_complete
from workflow_test_support import run_generated_workflow


def ops(report):
    return [call["request"]["operation"] for call in report["calls"]]


def test_topic_collects_archive_before_card_and_resumes_without_rediscovery():
    gap = {**SUBQUESTION, "coverage": "gap", "channel": "web"}
    observation = topic_observation(subquestions=[gap], members=[paper_member()])
    initial = topic_input(observation=observation)
    first = run_topic(initial, [recall_complete(), steer_complete(signal="continue", subquestions=[gap],
        items=[{"kind": "paper", "slug": "exact-paper", "role": "evidence"}], tasks=[web_task()]),
        {**COMPLETE, "urls": [URL], "note": "Official repair manual."}, {**COMPLETE, "identity": IDENTITY}])
    assert ops(first) == ["topic.recall", "topic.steer", "topic.discover-archives", "archive.identify"]
    assert first["result"]["terminal"] == "needs_observation"
    route = {"kind": "archive", "slug": SLUG}
    assert first["result"]["routes"] == [route]
    second_input = topic_input(observation=observation, children=[(route, archive_observation())], resume={"resume_seed": first["result"]["resume_seed"]})
    second = run_topic(second_input, [recall_complete(), COMPLETE])
    assert ops(second) == ["topic.recall", "archive.collect"]
    collect = second["calls"][1]["request"]
    assert collect["exact_output"] == PATH
    assert collect["topics"] == [QUERY["slug"]]
    assert second["result"]["terminal"] == "needs_observation"
    third_input = topic_input(observation=observation, children=[(route, archive_observation(usable=True, topics=[QUERY["slug"]]))], resume={"resume_seed": second["result"]["resume_seed"]})
    final_outputs = [recall_complete(), audit_complete(), webcard_complete(),
        steer_complete(signal="saturated", subquestions=[SUBQUESTION], items=[{"kind":"paper","slug":"exact-paper","role":"evidence"}], cards=["exact-card"]),
        audit_complete(), synthesis_complete(), synthesis_complete(), audit_complete(), audit_complete()]
    third = run_topic(third_input, final_outputs)
    assert third["result"]["terminal"] == "complete"
    assert ops(third)[:4] == ["topic.recall", "archive.audit", "topic.webcard", "topic.steer"]
    card = third["calls"][2]["request"]
    assert card["archive_paths"] == [PATH]
    assert all("WebFetch" not in cap for cap in card["capabilities"])
    assert not any(op.startswith("webpage.") for op in ops(first) + ops(second) + ops(third))
    generated = run_generated_workflow("topic", third_input, final_outputs)
    assert generated["value"]["terminal"] == "complete"


def continuation():
    task = web_task()
    import json
    return {"kind":"archive_work", "topic":QUERY, "task":task,
        "fingerprint":json.dumps([task["card_slug"],task["subq"],task["query"],task["note"]],separators=(",",":")),
        "sources":[{"state":"canonical","material_slug":SLUG,"identity":IDENTITY}]}


def test_topic_archive_unknown_outcome_never_writes_card():
    gap={**SUBQUESTION,"coverage":"gap"}
    value=topic_input(observation=topic_observation(subquestions=[gap]),children=[({"kind":"archive","slug":SLUG},archive_observation())],resume={"resume_seed":continuation()})
    result=run_topic(value,[recall_complete(),"__throw__"])
    assert ops(result)==["topic.recall","archive.collect"]
    assert result["result"]["terminal"]=="blocked"


def test_topic_existing_archive_gains_membership_before_card():
    gap={**SUBQUESTION,"coverage":"gap"}
    value=topic_input(observation=topic_observation(subquestions=[gap]),children=[({"kind":"archive","slug":SLUG},archive_observation(usable=True,topics=["older-topic"]))],resume={"resume_seed":continuation()})
    result=run_topic(value,[recall_complete(),COMPLETE])
    assert ops(result)==["topic.recall","archive.collect"]
    request=result["calls"][1]["request"]
    assert request["mode"]=="membership"
    assert request["topics"]==["older-topic",QUERY["slug"]]
    assert result["result"]["terminal"]=="needs_observation"


def test_topic_rejects_tampered_archive_continuation():
    resume=continuation()
    resume["sources"][0]["identity"]=deepcopy(IDENTITY)
    resume["sources"][0]["identity"]["slug"]="other-owner"
    value=topic_input(resume={"resume_seed":resume})
    result=run_topic(value,[])
    assert result["calls"]==[]
    assert result["result"]["issue"]["code"]=="material.invalid_input"


def test_topic_multiple_sources_observes_each_before_writing_card():
    resume = continuation()
    second_identity = {**IDENTITY, "slug": "second-manual", "url": "https://example.org/second"}
    resume["sources"].append({"state": "provisional", "url": second_identity["url"]})
    first_route = {"kind": "archive", "slug": SLUG}
    value = topic_input(
        observation=topic_observation(subquestions=[{**SUBQUESTION, "coverage": "gap"}]),
        children=[(first_route, archive_observation(usable=True, topics=[QUERY["slug"]]))],
        resume={"resume_seed": resume},
    )
    result = run_topic(value, [recall_complete(), audit_complete(), {**COMPLETE, "identity": second_identity}])
    assert ops(result) == ["topic.recall", "archive.audit", "archive.identify"]
    assert result["result"]["routes"] == [first_route, {"kind": "archive", "slug": "second-manual"}]
    next_resume = result["result"]["resume_seed"]
    assert next_resume["sources"][0] == resume["sources"][0]
    assert next_resume["sources"][1]["identity"] == second_identity

    second_observation = archive_observation()
    second_observation["slug"] = "second-manual"
    second_observation["facts"]["collection"]["path"] = "vault/archives/second-manual/manifest.yaml"
    second_observation["facts"]["canonical"]["path"] = "vault/archives/second-manual/archive.md"
    value["resume"]["resume_seed"] = next_resume
    value["child_observations"].append({"route": {"kind": "archive", "slug": "second-manual"}, "observation": second_observation})
    collected = run_topic(value, [recall_complete(), audit_complete(), COMPLETE])
    assert ops(collected) == ["topic.recall", "archive.audit", "archive.collect"]
    assert collected["result"]["terminal"] == "needs_observation"


def test_topic_duplicate_archive_owner_is_rejected_before_dispatch():
    resume = continuation()
    duplicate = deepcopy(resume["sources"][0])
    duplicate["identity"]["url"] = "https://example.org/other"
    resume["sources"].append(duplicate)
    result = run_topic(topic_input(resume={"resume_seed": resume}), [])
    assert result["calls"] == []
    assert result["result"]["issue"]["code"] == "material.invalid_input"


def test_topic_passes_only_observed_originals_to_card_writer():
    gap = {**SUBQUESTION, "coverage": "gap"}
    observed = archive_observation(usable=True, topics=[QUERY["slug"]])
    original = f"vault/archives/{SLUG}/originals/screen-detail.jpg"
    observed["facts"]["collection"]["files"] = [{"path": original, "present": True, "usable": True, "media_type": "image/jpeg"}]
    value = topic_input(observation=topic_observation(subquestions=[gap]),
        children=[({"kind": "archive", "slug": SLUG}, observed)], resume={"resume_seed": continuation()})
    # Stop after the writer to inspect its exact input envelope.
    report = run_topic(value, [recall_complete(), audit_complete(), "__throw__"])
    assert ops(report) == ["topic.recall", "archive.audit", "topic.webcard"]
    card = report["calls"][2]["request"]
    assert card["archive_inputs"] == [f"vault/archives/{SLUG}/manifest.yaml", original]
    assert card["archive_paths"] == [PATH]
