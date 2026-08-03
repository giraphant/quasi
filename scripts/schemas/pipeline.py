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
                "artifacts": {"output": "sources/{slug}.pdf"},
            },
            {
                "stage": "prepare",
                "operation": "paper.prepare",
                "phase": "Prepare",
                "effect": "writer",
                "agent": "quasi:extract-agent",
                "artifacts": {
                    "source": "sources/{slug}.pdf",
                    "normalized": "processing/papers/{slug}/source.txt",
                    "recoverySource": "processing/papers/{slug}/ocr.pdf",
                    "recoveryText": "processing/papers/{slug}/ocr.txt",
                },
            },
            {
                "stage": "analyse",
                "operation": "paper.analyse",
                "phase": "Analyse",
                "effect": "writer",
                "agent": "quasi:analyse-agent",
                "artifacts": {"output": "vault/papers/{slug}.md"},
            },
            {
                "stage": "audit",
                "operation": "paper.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
                "artifacts": {"target": "vault/papers/{slug}.md"},
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
                "artifacts": {
                    "source": "sources/{slug}.{format}",
                    "normalized": "processing/chapters/{slug}/source.txt",
                    "recoverySource": "processing/chapters/{slug}/ocr.pdf",
                    "recoveryText": "processing/chapters/{slug}/ocr.txt",
                    "outputDir": "processing/chapters/{slug}",
                    "manifest": "processing/chapters/{slug}/manifest.json",
                },
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
                "artifacts": {"output": "vault/books/{slug}/00-overview.md"},
            },
            {
                "stage": "audit",
                "operation": "book.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
                "artifacts": {"target": "vault/books/{slug}"},
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
                "artifacts": {
                    "processingDir": "processing/talks/{slug}",
                    "manifest": "processing/talks/{slug}/manifest.json",
                    "prepared": "vault/talks/{slug}/recording.mp4",
                    "transcript": "vault/talks/{slug}/transcript.md",
                    "subtitle": "vault/talks/{slug}/recording.srt",
                    "canonical": "vault/talks/{slug}/talk.md",
                },
            },
            {
                "stage": "analyse",
                "operation": "talk.analyse",
                "phase": "Analyse",
                "effect": "writer",
                "agent": "quasi:analyse-agent",
                "artifacts": {"output": "vault/talks/{slug}/talk.md"},
            },
            {
                "stage": "audit",
                "operation": "talk.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
                "artifacts": {"target": "vault/talks/{slug}/talk.md"},
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
                "artifacts": {
                    "source": "sources/{slug}.pdf",
                    "derivatives": "processing/translations/{slug}-*.pdf",
                    "output": "processing/translations/{slug}-{target}.pdf",
                    "manifest": "processing/translations/{slug}-{target}.manifest.json",
                    "recoverySource": "processing/translations/{slug}-{target}-reocr.pdf",
                },
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
                "artifacts": {"outputPath": "vault/topics/{slug}/02-outline.md"},
            },
            {
                "stage": "webcard",
                "operation": "topic.webcard",
                "phase": "Search",
                "effect": "writer",
                "agent": "quasi:webcard-agent",
                "artifacts": {
                    "cardPath": "vault/topics/{slug}/cards/{target}.md"
                },
            },
            {
                "stage": "synthesise-overview",
                "operation": "topic.synthesise.overview",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
                "artifacts": {
                    "outlinePath": "vault/topics/{slug}/02-outline.md",
                    "outputPath": "vault/topics/{slug}/00-overview.md",
                },
            },
            {
                "stage": "synthesise-resources",
                "operation": "topic.synthesise.resources",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
                "artifacts": {
                    "outlinePath": "vault/topics/{slug}/02-outline.md",
                    "outputPath": "vault/topics/{slug}/01-resources.md",
                },
            },
            {
                "stage": "audit",
                "operation": "topic.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
                "artifacts": {"target": "{target}"},
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
                "artifacts": {"output": "vault/authors/{slug}.md"},
            },
            {
                "stage": "synthesise",
                "operation": "author.synthesise",
                "phase": "Synthesise",
                "effect": "writer",
                "agent": "quasi:synthesis-agent",
                "artifacts": {"output": "vault/authors/{slug}.md"},
            },
            {
                "stage": "audit",
                "operation": "author.audit",
                "phase": "Audit",
                "effect": "writer",
                "agent": "quasi:audit-agent",
                "artifacts": {"target": "vault/authors/{slug}.md"},
            },
        ],
    },
}
