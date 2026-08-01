import { normalizeLanguage } from "./operations/rows/translation.mjs";

const value = (source, camel, snake = camel) =>
  source[camel] === undefined ? source[snake] : source[camel];

const materialKey = (kind, slug, context) =>
  value(context, "materialKey", "material_key") || `${kind}:${slug}`;

export function makeOperationContext(kind, slug, operation, rawContext) {
  const context = rawContext && typeof rawContext === "object" ? rawContext : {};
  const meta = context.meta || context.identity || context;
  const base = { ...context, slug, meta, materialKey: materialKey(kind, slug, context) };
  const mode = context.mode || "create";
  const diagnostics = context.diagnostics || [];

  switch (operation) {
    case "material.search":
      return {
        ...base,
        kind,
        requestedSlug: slug,
        query: context.query || context.request || meta,
        yearDecision: value(context, "yearDecision", "year_decision") || null,
      };
    case "paper.acquire":
      return { ...base, output: `sources/${slug}.pdf`, doi: meta.doi || null };
    case "paper.prepare":
      return {
        ...base,
        source: `sources/${slug}.pdf`,
        normalized: `processing/papers/${slug}/source.txt`,
        recoverySource: `processing/papers/${slug}/ocr.pdf`,
        recoveryText: `processing/papers/${slug}/ocr.txt`,
      };
    case "paper.analyse":
      return {
        ...base,
        input: context.input || context.selected_input,
        output: `vault/papers/${slug}.md`,
        mode,
        diagnostics,
      };
    case "paper.audit":
      return { ...base, target: `vault/papers/${slug}.md`, pass: context.pass || 1 };
    case "book.acquire": {
      const formats = context.allowed_formats || (meta.format ? [meta.format] : ["epub", "pdf"]);
      return {
        ...base,
        allowedSources: formats.map((format) => ({ format, path: `sources/${slug}.${format}` })),
        expectedYear: meta.year,
        batchAcceptYear: Boolean(value(context, "batchAcceptYear", "batch_accept_year")),
        yearDecision: value(context, "yearDecision", "year_decision") || null,
      };
    }
    case "book.prepare": {
      const format = context.format || meta.format;
      const root = `processing/chapters/${slug}`;
      return {
        ...base,
        identity: meta,
        source: context.source || `sources/${slug}.${format}`,
        format,
        normalized: `${root}/source.txt`,
        recoverySource: `${root}/ocr.pdf`,
        recoveryText: `${root}/ocr.txt`,
        outputDir: root,
        manifest: `${root}/manifest.json`,
      };
    }
    case "chapter.analyse": {
      const chapter = context.chapter;
      return {
        ...base,
        bookSlug: slug,
        chapter,
        input: `processing/chapters/${slug}/${chapter.filename}`,
        output: `vault/books/${slug}/ch${chapter.slot}-${chapter.slug}.md`,
        mode,
        diagnostics,
      };
    }
    case "book.synthesise":
      return {
        ...base,
        inputPaths: value(context, "inputPaths", "input_paths") || [],
        output: `vault/books/${slug}/00-overview.md`,
        mode,
        diagnostics,
      };
    case "book.audit":
      return { ...base, target: `vault/books/${slug}`, pass: context.pass || 1 };
    case "talk.prepare": {
      const vault = `vault/talks/${slug}`;
      const processing = `processing/talks/${slug}`;
      return {
        ...base,
        title: meta.title,
        date: meta.date,
        language: meta.lang || meta.language || "auto",
        engines: meta.engines || [],
        media: meta.media,
        prepareMedia: Boolean(value(meta, "prepareMedia", "prepare_media")),
        processingDir: processing,
        manifest: `${processing}/manifest.json`,
        prepared: `${vault}/recording.mp4`,
        transcript: `${vault}/transcript.md`,
        subtitle: `${vault}/recording.srt`,
        canonical: `${vault}/talk.md`,
        repairDiagnostics: diagnostics,
        repair: mode === "repair",
      };
    }
    case "talk.analyse":
      return {
        ...base,
        title: meta.title,
        date: meta.date,
        media: meta.media,
        inputs: context.inputs || [],
        output: `vault/talks/${slug}/talk.md`,
        mode,
        diagnostics,
      };
    case "talk.audit":
      return { ...base, target: `vault/talks/${slug}/talk.md`, pass: context.pass || 1 };
    case "translation.prepare": {
      const targetLanguage = normalizeLanguage(context.target_language || context.targetLanguage || "zh-CN");
      const stem = `${slug}-${targetLanguage.toLowerCase()}`;
      return {
        ...base,
        materialKey:
          value(context, "materialKey", "material_key") ||
          `translation:paper:${slug}:${targetLanguage}`,
        targetLanguage,
        requestedSource: value(context, "requestedSource", "requested_source") || context.source_file || null,
        sourceDecision: value(context, "sourceDecision", "source_decision") || null,
        output: `processing/translations/${stem}.pdf`,
        manifest: `processing/translations/${stem}.manifest.json`,
        recoverySource: `processing/translations/${stem}-reocr.pdf`,
        tocJson: value(context, "tocJson", "toc_json") || null,
        tocPageSide: value(context, "tocPageSide", "toc_page_side") || "original",
      };
    }
    case "topic.steer":
    case "topic.webcard":
    case "topic.synthesise.overview":
    case "topic.synthesise.resources":
      return {
        ...base,
        researchKey: value(context, "researchKey", "research_key") || `topic:${slug}`,
        topicSlug: slug,
        topic: context.topic || context.query,
        query: context.query,
        memberRefs: value(context, "memberRefs", "member_refs") || [],
        memberAssignments: value(context, "memberAssignments", "member_assignments") || [],
        cardRefs: value(context, "cardRefs", "card_refs") || [],
        task: context.task || context.web_task,
        subquestions: context.subquestions || [],
        mode,
        diagnostics,
      };
    case "topic.audit":
      return { ...base, target: context.target, pass: context.pass || 1 };
    case "author.discover-books":
    case "author.discover-papers":
      return {
        ...base,
        fullName: value(context, "fullName", "full_name"),
        topic: context.topic,
        count: context.count,
      };
    case "author.resolve-membership":
      return {
        ...base,
        name: slug,
        output: `vault/authors/${slug}.md`,
        candidates: context.candidates || [],
      };
    case "member.admission-probe":
      return {
        ...base,
        kind: context.member_kind || context.kind,
        materialKey: value(context, "materialKey", "material_key") || `${context.member_kind || context.kind}:${slug}`,
      };
    default:
      return base;
  }
}
