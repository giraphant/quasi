// process-material — 统一采集→分析编排图(Workflow 脚本)
//
// 设计见 docs/process-material-design.md。要点:
//   - 脚本无文件系统访问:手里只有 agent() 的返回回执(小 JSON)。
//   - 产物内容走文件;下游 agent 按路径读。脚本从不持有正文。
//   - fan-out 的章节列表由 extract-agent 在回执里带回(ex.chapters)。
//   - 续跑 = agent 幂等(output 存在即 no-op),不靠 Workflow 自身 resume。
//   - 人工卡点 = 冒泡一个 {status} 对象,由入口 skill 做 AskUserQuestion。
//
// ⚠ AGENT 接法 SWAP POINT:下面用 agentType:'quasi:*' 起既有 agent。
//   若 spike(设计文档 §8)证明 agentType 在 Workflow 内不解析,把每处
//   { agentType:'quasi:X' } 换成承载 agents/X.md 指令的 inline prompt。
//   下面的图结构两种接法都不变。
//
// v0:只有 processBook 是真的;paper/author/topic 是 stub(见 §7 退役顺序)。

export const meta = {
  name: 'process-material',
  description: 'Unified acquisition→analysis graph: router(kind) → book (v0) | paper|author|topic (stub)',
  phases: [{ title: 'Book' }],
}

// ── 回执 schema:不传 schema 时 agent() 返回散文字符串,脚本读不到字段。
//    只给脚本真正读字段的三个回执(download/extract/audit)加 schema;analyse/synth 回执不读,不加。
const DL_SCHEMA = { type: 'object', required: ['per_item'], properties: {
  per_item: { type: 'array', items: { type: 'object', required: ['status'], properties: {
    slug: { type: 'string' }, status: { type: 'string' }, path: { type: 'string' },
    tmp_path: { type: 'string' }, year_evidence: { type: 'object' } } } } } }
const EX_SCHEMA = { type: 'object', required: ['status'], properties: {
  status: { type: 'string' }, problems: { type: 'array' },
  chapters: { type: 'array', items: { type: 'object', required: ['slot', 'filename', 'slug'], properties: {
    slot: {}, title: { type: 'string' }, filename: { type: 'string' },
    slug: { type: 'string' }, word_count: { type: 'number' } } } } } }
const AU_SCHEMA = { type: 'object', properties: {
  escalated: { type: 'array', items: { type: 'object', properties: {
    path: { type: 'string' }, kind: { type: 'string' }, reason: { type: 'string' } } } } } }

// ── processBook:承重节点。author = parallel(books→processBook);topic = pipeline(items→router)。 ──
async function processBook(slug, m) {
  phase('Book')

  // download ── 回执:status/path/year_evidence   产物:PDF 落 sources/
  const dl = await agent(bookDownloadPrompt(slug, m),
    { agentType: 'quasi:download-agent', label: `download:${slug}`, schema: DL_SCHEMA })
  const item = (dl && dl.per_item && dl.per_item[0]) || {}
  if (item.status !== 'ok')
    return { slug, status: item.status || 'download_failed',
             year_evidence: item.year_evidence, tmp_path: item.tmp_path }

  // extract ── 章节列表从回执带回(脚本无 fs,不读 manifest)  产物:manifest+txt 落 processing/
  const ex = await agent(extractPrompt(item.path, slug),
    { agentType: 'quasi:extract-agent', label: `extract:${slug}`, schema: EX_SCHEMA })
  if (!ex || ex.status === 'failed')
    return { slug, status: 'extract_failed', problems: ex && ex.problems }
  const chapters = ex.chapters || []
  if (!chapters.length) return { slug, status: 'no_chapters' }

  // fan-out analyse ── 每章一个 agent;正文在 processing/,分析写 vault/;幂等 agent 自跳过已完成章 = 续跑
  await parallel(chapters.map(ch => () =>
    agent(analyseChapterPrompt(slug, m, ch),
      { agentType: 'quasi:analyse-agent', label: `analyse:${slug}:${ch.slot}` })))

  // synth(book) ── 只递目录/slug;synthesis-agent 自己 Glob vault 的 ch*.md
  await agent(bookSynthPrompt(slug, m),
    { agentType: 'quasi:synthesis-agent', label: `synth:${slug}` })

  // audit + 一次 escalation 回环 ── 章用 chapters(在 scope 内)重投,概览用 synth 重投
  let au = await agent(`path: vault/books/${slug}`,
    { agentType: 'quasi:audit-agent', label: `audit:${slug}`, schema: AU_SCHEMA })
  const esc = (au && au.escalated) || []
  if (esc.length) {
    await parallel(esc.map(e => () => {
      const p = e.path || ''
      if (p.endsWith('/00-overview.md'))
        return agent(bookSynthPrompt(slug, m) + `\noverwrite: true\nreason: audit escalated ${e.kind}: ${e.reason}`,
          { agentType: 'quasi:synthesis-agent', label: `regen-synth:${slug}` })
      const ch = chapters.find(c => p.endsWith(chFilename(c)))
      if (!ch) return Promise.resolve({ status: 'skip', note: `no chapter match for ${p}` })
      return agent(analyseChapterPrompt(slug, m, ch) + `\noverwrite: true\nreason: audit escalated ${e.kind}: ${e.reason}`,
        { agentType: 'quasi:analyse-agent', label: `regen-ch:${slug}:${ch.slot}` })
    }))
    au = await agent(`path: vault/books/${slug}`,
      { agentType: 'quasi:audit-agent', label: `audit2:${slug}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length)
      return { slug, status: 'audit_escalated', escalated: au.escalated }
  }

  const ye = item.year_evidence
  return { slug, status: 'ok', year_warning: ye && ye.verdict !== 'MATCH' ? ye : null }
}

// ── prompt builders:薄,只承载各 agent 期望的契约字段 ──
function bookDownloadPrompt(slug, m) {
  return `kind: book
items:
  - slug: ${slug}
    expected_author: ${(m.authors && m.authors[0]) || m.author || ''}
    expected_title: ${m.title || ''}
    identifiers:
      isbn: ${m.isbn || ''}
output_dir: sources/`
}
function extractPrompt(sourceFile, slug) {
  return `source_file: ${sourceFile}, chapters_dir: processing/chapters/${slug}/
在 EXTRACT_RESULT 里附一个 "chapters" 数组(每项 slot/title/filename/slug/word_count),
让调用方无需读 manifest 就能 fan-out。`
}
// 章节输出文件名 —— extract-agent 回执的 slug 可能已带 chNN- 前缀
// (标题 "Chapter 1: ..." 被 slug 成 "ch01-..."),strip 掉,避免 ch01-ch01- 双前缀。
function chFilename(ch) {
  const s = String(ch.slug || '').replace(/^ch[0-9]+[a-z]?-/i, '')
  return `ch${ch.slot}-${s}.md`
}
function analyseChapterPrompt(slug, m, ch) {
  return `type: A
book_slug: ${slug}
book_title: ${m.title || ''}
slot: ${ch.slot}
chapter_label: ${ch.chapter_label || ch.label || ''}
chapter_title: ${ch.title || ''}
year: ${m.year || ''}
chapter_authors: ${ch.authors || (m.authors || []).join(', ')}
input: processing/chapters/${slug}/${ch.filename}
output: vault/books/${slug}/${chFilename(ch)}
topic: ${m.topic || ''}
若 output 已存在且未设 overwrite,直接 no-op 返回 success。`
}
function bookSynthPrompt(slug, m) {
  return `mode: book
output_dir: vault/books/${slug}
book_title: ${m.title || ''}
topic: ${m.topic || ''}
若 00-overview.md 已存在且未设 overwrite,直接 no-op 返回 success。`
}

// ── router / 入口 ──
async function router(kind, a) {
  switch (kind) {
    case 'book': return processBook(a.slug, a.meta || a)
    case 'paper':
    case 'author':
    case 'topic':
      throw new Error(`process-material v0: kind "${kind}" 未实现(仅 book)。见 docs/process-material-design.md §7`)
    default:
      throw new Error(`process-material: 未知 kind "${kind}"`)
  }
}

const a = args || {}
if (!a.kind) throw new Error('process-material: 需要 args.kind(book|paper|author|topic)')
const result = await router(a.kind, a)
log(`process-material result: ${JSON.stringify(result)}`)
return result
