from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_VALID_STATUS = {"auto_ok", "needs_user", "unresolved"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _status_from_note(note: dict[str, Any]) -> str:
    status = str(note.get("status") or "")
    if status in _VALID_STATUS:
        return status
    flag = str(note.get("flag") or "")
    if flag == "ok":
        return "auto_ok"
    if flag == "review":
        return "needs_user"
    return "unresolved"


def _flag_from_status(status: str, note: dict[str, Any]) -> str:
    flag = str(note.get("flag") or "")
    if flag in {"ok", "review"}:
        return flag
    return "ok" if status == "auto_ok" else "review"


def _recommended_action(status: str, note: dict[str, Any]) -> str:
    action = str(note.get("recommended_action") or "")
    if action:
        return action
    return "keep" if status == "auto_ok" else "ask_user"


def normalise_note(note: dict[str, Any], batch_id: str) -> dict[str, Any]:
    status = _status_from_note(note)
    return {
        "batch_id": batch_id,
        "key": note.get("key", ""),
        "picked_slug": note.get("picked_slug", ""),
        "status": status,
        "flag": _flag_from_status(status, note),
        "decision_question": note.get("decision_question", ""),
        "draft_context": note.get("draft_context") or {},
        "current_bib": note.get("current_bib") or {},
        "candidates": note.get("candidates") or [],
        "recommended_action": _recommended_action(status, note),
        "confidence": note.get("confidence", ""),
        "missing_evidence": note.get("missing_evidence") or [],
        "note": note.get("note", ""),
    }


def build_review_cards(verdicts_dir: Path) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for path in sorted(verdicts_dir.glob("batch-*.json")):
        payload = _load_json(path)
        batch_id = str(payload.get("batch_id") or path.stem.removeprefix("batch-"))
        if payload.get("error"):
            errors.append({
                "batch_id": batch_id,
                "path": str(path),
                "error": str(payload["error"]),
            })
            continue
        for note in payload.get("notes", []):
            card = normalise_note(note, batch_id)
            if card["key"]:
                cards.append(card)

    summary = {
        "total": len(cards),
        "auto_ok": sum(1 for card in cards if card["status"] == "auto_ok"),
        "needs_user": sum(1 for card in cards if card["status"] == "needs_user"),
        "unresolved": sum(1 for card in cards if card["status"] == "unresolved"),
        "errors": len(errors),
    }
    return {
        "version": 1,
        "summary": summary,
        "cards": cards,
        "errors": errors,
    }
