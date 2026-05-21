from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CITATION = PLUGIN_ROOT / "scripts" / "citation" / "citation.py"


def run_citation(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CITATION), *args],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_review_cards_merges_new_card_fields(tmp_path: Path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    out = tmp_path / "review-cards.json"
    (verdicts / "batch-001.json").write_text(
        json.dumps(
            {
                "batch_id": "001",
                "notes": [
                    {
                        "key": "verbeek-2015",
                        "picked_slug": "rosenberger-verbeek-postphenomenological-investigations-2015",
                        "status": "needs_user",
                        "flag": "review",
                        "decision_question": "这里应保留 Interactions 文章，还是替换为 2015 edited volume?",
                        "draft_context": {
                            "section": "2.3",
                            "quote": "Verbeek 的 mediation theory 说明技术中介身体经验。",
                            "use_summary": "正文在概括 postphenomenology 的框架性论点。",
                        },
                        "current_bib": {
                            "entry_type": "article",
                            "display": "Verbeek, Peter-Paul (2015) Beyond Interaction.",
                            "concern": "当前条目是短文，可能不足以支撑框架性表述。",
                        },
                        "candidates": [
                            {
                                "slug": "rosenberger-verbeek-postphenomenological-investigations-2015",
                                "display": "Rosenberger and Verbeek (eds.) (2015) Postphenomenological Investigations.",
                                "fit": "strong",
                                "evidence": ["vault overview 明确讨论 human-technology relations 和 mediation。"],
                                "problem": "",
                            }
                        ],
                        "recommended_action": "replace",
                        "confidence": "medium",
                        "missing_evidence": [],
                        "note": "正文像是在引用整本编著的框架，而不是短文介绍。",
                    },
                    {
                        "key": "shilling-2003",
                        "picked_slug": "shilling-body-and-social-theory-2003",
                        "status": "auto_ok",
                        "flag": "ok",
                        "decision_question": "",
                        "draft_context": {
                            "section": "1.1",
                            "quote": "身体社会学将身体作为社会理论问题。",
                            "use_summary": "正文概括该书的核心论点。",
                        },
                        "current_bib": {
                            "entry_type": "book",
                            "display": "Shilling, Chris (2003) The Body and Social Theory.",
                            "concern": "",
                        },
                        "candidates": [],
                        "recommended_action": "keep",
                        "confidence": "high",
                        "missing_evidence": [],
                        "note": "正文语义和 vault 候选契合。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_citation(tmp_path, "review-cards", str(verdicts), "-o", str(out))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "total": 2,
        "auto_ok": 1,
        "needs_user": 1,
        "unresolved": 0,
        "errors": 0,
    }
    assert payload["cards"][0]["key"] == "verbeek-2015"
    assert payload["cards"][0]["decision_question"].startswith("这里应保留")
    assert payload["cards"][0]["recommended_action"] == "replace"
    assert payload["cards"][1]["status"] == "auto_ok"
    assert "wrote" in result.stdout


def test_review_cards_normalises_legacy_notes(tmp_path: Path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    out = tmp_path / "review-cards.json"
    (verdicts / "batch-001.json").write_text(
        json.dumps(
            {
                "batch_id": "001",
                "notes": [
                    {
                        "key": "haraway-2016",
                        "picked_slug": "haraway-staying-with-the-trouble-2016",
                        "flag": "ok",
                        "note": "mention 上下文和 making kin / Chthulucene 契合。",
                    },
                    {
                        "key": "fausto-sterling-2000",
                        "picked_slug": "fausto-sterling-five-sexes-revisited-2000",
                        "flag": "review",
                        "note": "候选是短文，但正文像是在谈同年专著。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_citation(tmp_path, "review-cards", str(verdicts), "-o", str(out))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    by_key = {card["key"]: card for card in payload["cards"]}
    assert payload["summary"]["auto_ok"] == 1
    assert payload["summary"]["needs_user"] == 1
    assert by_key["haraway-2016"]["status"] == "auto_ok"
    assert by_key["haraway-2016"]["recommended_action"] == "keep"
    assert by_key["fausto-sterling-2000"]["status"] == "needs_user"
    assert by_key["fausto-sterling-2000"]["recommended_action"] == "ask_user"
    assert by_key["fausto-sterling-2000"]["draft_context"] == {}
    assert by_key["fausto-sterling-2000"]["candidates"] == []
