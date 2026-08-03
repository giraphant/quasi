"""Canonical run-stage pipeline identity, order, and receipt carries."""

PIPELINE = {
    "paper": {
        "stages": [
            {
                "stage": "search",
                "operation": "material.search",
                "phase": "Search",
                "effect": "readonly",
                "agent": "quasi:metadata-agent",
            },
            {
                "stage": "acquire",
                "operation": "paper.acquire",
                "phase": "Acquire",
                "effect": "writer",
                "agent": "quasi:download-agent",
            },
            {
                "stage": "prepare",
                "operation": "paper.prepare",
                "phase": "Prepare",
                "effect": "writer",
                "agent": "quasi:extract-agent",
            },
            {
                "stage": "analyse",
                "operation": "paper.analyse",
                "phase": "Analyse",
                "effect": "writer",
                "agent": "quasi:analyse-agent",
            },
            {
                "stage": "audit",
                "operation": "paper.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
            },
        ],
        "chain": {
            "sequence": ["acquire", "prepare", "analyse", "audit"],
            "carries": [
                {
                    "from": "prepare",
                    "field": "selected_input",
                    "to": "input",
                }
            ],
        },
    },
    "book": {
        "stages": [
            {
                "stage": "search",
                "operation": "material.search",
                "phase": "Search",
                "effect": "readonly",
                "agent": "quasi:metadata-agent",
            },
            {
                "stage": "acquire",
                "operation": "book.acquire",
                "phase": "Acquire",
                "effect": "writer",
                "agent": "quasi:download-agent",
            },
            {
                "stage": "prepare",
                "operation": "book.prepare",
                "phase": "Prepare",
                "effect": "writer",
                "agent": "quasi:extract-agent",
            },
            {
                "stage": "analyse",
                "operation": "chapter.analyse",
                "phase": "Analyse",
                "effect": "writer",
                "agent": "quasi:analyse-agent",
            },
            {
                "stage": "synthesise",
                "operation": "book.synthesise",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
            },
            {
                "stage": "audit",
                "operation": "book.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
            },
        ],
    },
    "talk": {
        "stages": [
            {
                "stage": "prepare",
                "operation": "talk.prepare",
                "phase": "Prepare",
                "effect": "writer",
                "agent": "quasi:transcribe-agent",
            },
            {
                "stage": "analyse",
                "operation": "talk.analyse",
                "phase": "Analyse",
                "effect": "writer",
                "agent": "quasi:analyse-agent",
            },
            {
                "stage": "audit",
                "operation": "talk.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
            },
        ],
    },
    "translation": {
        "stages": [
            {
                "stage": "prepare",
                "operation": "translation.prepare",
                "phase": "Prepare",
                "effect": "writer",
                "agent": "quasi:translate-agent",
            }
        ],
    },
    "topic": {
        "stages": [
            {
                "stage": "recall",
                "operation": "topic.recall",
                "phase": "Recall",
                "effect": "readonly",
                "agent": "general-purpose",
            },
            {
                "stage": "steer",
                "operation": "topic.steer",
                "phase": "Search",
                "effect": "writer",
                "agent": "quasi:steer-agent",
            },
            {
                "stage": "webcard",
                "operation": "topic.webcard",
                "phase": "Search",
                "effect": "writer",
                "agent": "quasi:webcard-agent",
            },
            {
                "stage": "synthesise-overview",
                "operation": "topic.synthesise.overview",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
            },
            {
                "stage": "synthesise-resources",
                "operation": "topic.synthesise.resources",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
            },
            {
                "stage": "audit",
                "operation": "topic.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
            },
        ],
    },
    "author": {
        "stages": [
            {
                "stage": "discover-books",
                "operation": "author.discover-books",
                "phase": "Search",
                "effect": "readonly",
                "agent": "quasi:discovery-agent",
            },
            {
                "stage": "discover-papers",
                "operation": "author.discover-papers",
                "phase": "Search",
                "effect": "readonly",
                "agent": "quasi:discovery-agent",
            },
            {
                "stage": "resolve-membership",
                "operation": "author.resolve-membership",
                "phase": "Search",
                "effect": "readonly",
                "agent": "general-purpose",
            },
            {
                "stage": "synthesise",
                "operation": "author.synthesise",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
            },
            {
                "stage": "audit",
                "operation": "author.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
            },
        ],
    },
}
