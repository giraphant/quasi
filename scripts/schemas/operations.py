"""Artifact path templates used by quasi status."""

OPERATION_CATALOG = {
    "archive.collect": {
        "artifacts": {
            "output": "{archiveDirectory}/archive.md",
            "manifest": "{archiveDirectory}/manifest.yaml",
            "originals": "{archiveDirectory}/originals",
        },
    },
    "archive.audit": {
        "artifacts": {
            "target": "{archiveDirectory}/archive.md",
        },
    },
    "webpage.capture": {
        "artifacts": {
            "snapshot": "vault/webpages/{slug}/snapshot.webarchive",
        },
    },
    "webpage.prepare": {
        "artifacts": {
            "snapshot": "vault/webpages/{slug}/snapshot.webarchive",
            "output": "processing/webpages/{slug}/source.md",
        },
    },
    "webpage.analyse": {
        "artifacts": {
            "output": "vault/webpages/{slug}/webpage.md",
        },
    },
    "webpage.audit": {
        "artifacts": {
            "target": "vault/webpages/{slug}/webpage.md",
        },
    },
    "paper.acquire": {
        "artifacts": {
            "outputPdf": "sources/{slug}.pdf",
            "outputText": "sources/{slug}.txt",
        },
    },
    "paper.prepare": {
        "artifacts": {
            "input": "{input}",
            "sourcePdf": "sources/{slug}.pdf",
            "sourceText": "sources/{slug}.txt",
            "normalized": "processing/papers/{slug}/source.txt",
            "legacyRecoverySource": "processing/papers/{slug}/ocr.pdf",
            "legacyRecoveryText": "processing/papers/{slug}/ocr.txt",
        },
    },
    "paper.ocr": {
        "artifacts": {
            "source": "sources/{slug}.pdf",
            "lock": "processing/papers/{slug}/.ocr-generation.lock",
            "workDir": "processing/papers/{slug}/.ocr-work/{generationKey}",
            "progress": "processing/papers/{slug}/.ocr-work/{generationKey}/ocr.progress.json",
            "generationDir": "processing/papers/{slug}/ocr-generations/{generationKey}",
            "recoveryPdf": "processing/papers/{slug}/ocr-generations/{generationKey}/ocr.pdf",
            "recoveryText": "processing/papers/{slug}/ocr-generations/{generationKey}/ocr.txt",
            "manifest": "processing/papers/{slug}/ocr-generations/{generationKey}/manifest.json",
        },
    },
    "paper.analyse": {
        "artifacts": {
            "output": "vault/papers/{slug}.md",
        },
    },
    "paper.audit": {
        "artifacts": {
            "target": "vault/papers/{slug}.md",
        },
    },
    "book.prepare": {
        "artifacts": {
            "input": "{input}",
            "source": "sources/{slug}.{format}",
            "normalized": "processing/chapters/{slug}/source.txt",
            "recoverySource": "processing/chapters/{slug}/ocr.pdf",
            "ocrProgress": "processing/chapters/{slug}/ocr.progress.json",
            "recoveryText": "processing/chapters/{slug}/ocr.txt",
            "outputDir": "processing/chapters/{slug}",
            "manifest": "processing/chapters/{slug}/manifest.json",
        },
    },
    "book.ocr": {
        "artifacts": {
            "source": "sources/{slug}.pdf",
            "lock": "processing/chapters/{slug}/.ocr-generation.lock",
            "workDir": "processing/chapters/{slug}/.ocr-work/{generationKey}",
            "progress": "processing/chapters/{slug}/.ocr-work/{generationKey}/ocr.progress.json",
            "generationDir": "processing/chapters/{slug}/ocr-generations/{generationKey}",
            "recoveryPdf": "processing/chapters/{slug}/ocr-generations/{generationKey}/ocr.pdf",
            "recoveryText": "processing/chapters/{slug}/ocr-generations/{generationKey}/ocr.txt",
            "manifest": "processing/chapters/{slug}/ocr-generations/{generationKey}/manifest.json",
        },
    },
    "book.synthesise": {
        "artifacts": {
            "output": "vault/books/{slug}/00-overview.md",
        },
    },
    "book.audit": {
        "artifacts": {
            "target": "vault/books/{slug}",
        },
    },
    "talk.prepare": {
        "artifacts": {
            "processingDir": "processing/talks/{slug}",
            "manifest": "processing/talks/{slug}/manifest.json",
            "prepared": "vault/talks/{slug}/recording.mp4",
            "transcript": "vault/talks/{slug}/transcript.md",
            "subtitle": "vault/talks/{slug}/recording.srt",
            "canonical": "vault/talks/{slug}/talk.md",
        },
    },
    "talk.analyse": {
        "artifacts": {
            "output": "vault/talks/{slug}/talk.md",
        },
    },
    "talk.audit": {
        "artifacts": {
            "target": "vault/talks/{slug}/talk.md",
        },
    },
    "translation.prepare": {
        "artifacts": {
            "source": "sources/{slug}.pdf",
            "derivatives": "processing/translations/{slug}-*.pdf",
            "output": "processing/translations/{slug}-{target}.pdf",
            "manifest": "processing/translations/{slug}-{target}.manifest.json",
            "recoverySource": "processing/translations/{slug}-{target}-reocr.pdf",
            "layoutRecognition": "processing/translations/{slug}-{target}-recognition.json",
            "layoutReview": "processing/translations/{slug}-{target}-layout-review.json",
        },
    },
    "topic.steer": {
        "artifacts": {
            "outputPath": "vault/topics/{slug}/02-outline.md",
        },
    },
    "topic.webcard": {
        "artifacts": {
            "cardPath": "vault/topics/{slug}/cards/{target}.md",
        },
    },
    "topic.synthesise.overview": {
        "artifacts": {
            "outlinePath": "vault/topics/{slug}/02-outline.md",
            "outputPath": "vault/topics/{slug}/00-overview.md",
        },
    },
    "topic.synthesise.resources": {
        "artifacts": {
            "outlinePath": "vault/topics/{slug}/02-outline.md",
            "outputPath": "vault/topics/{slug}/01-resources.md",
        },
    },
    "topic.audit": {
        "artifacts": {
            "target": "{target}",
        },
    },
    "author.resolve-membership": {
        "artifacts": {
            "output": "vault/authors/{slug}.md",
        },
    },
    "author.synthesise": {
        "artifacts": {
            "output": "vault/authors/{slug}.md",
        },
    },
    "author.audit": {
        "artifacts": {
            "target": "vault/authors/{slug}.md",
        },
    },
}
