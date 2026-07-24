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
// 已实现:processBook / processPaper / processAuthor
//   author = parallel(books→processBook + papers→processPaper) → synth(author) → audit。
// topic 仍 stub(见 §7 退役顺序)。

export const meta = {
  name: 'process-material',
  description: 'Unified acquisition→analysis graph: router(kind) → book | paper | author | topic (stub)',
  phases: [{ title: 'Book' }, { title: 'Paper' }, { title: 'Author' }],
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
// search-agent 回执:author discovery 读 candidates[](每项必须带 canonical slug)。
const SEARCH_SCHEMA = { type: 'object', properties: {
  candidates: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
    slug: { type: 'string' }, title: { type: 'string' }, authors: { type: 'array' },
    year: {}, isbn: { type: 'string' }, doi: { type: 'string' },
    oa_url: { type: 'string' }, url: { type: 'string' }, journal: { type: 'string' } } } } } }
// 存在性探针回执:图无 fs,批量前用一个 agent 一次性查哪些产物已在 vault(避免重跑已完成的书/论文,
// 尤其避免对已入库的书做破坏性重 extract)。vault_slug 非 null = 已做过;它可能与候选 slug 不同
// (搜索侧 slug 漂移),下游必须用 vault_slug 读产物,否则会当成新书重跑 → 重复条目。
const PROBE_SCHEMA = { type: 'object', properties: {
  resolved: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
    kind: { type: 'string' }, slug: { type: 'string' },
    vault_slug: { type: ['string', 'null'] }, match: { type: ['string', 'null'] } } } } } }

// ── processBook:承重节点。author = parallel(books→processBook);topic = pipeline(items→router)。 ──
// opts.batchYear=true(author 批量):year_mismatch/ambiguous 不冒泡卡点,download-agent 直接
// accept 入 sources 并把 year_evidence 作 warning,status 返回 ok(单本 book 入口不传,走卡点)。
async function processBook(slug, m, opts = {}) {
  phase('Book')

  // download ── 回执:status/path/year_evidence   产物:PDF 落 sources/
  const dl = await agent(bookDownloadPrompt(slug, m, opts.batchYear),
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
      const ch = chapters.find(c => p.endsWith(`ch${c.slot}-${c.slug}.md`))
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

// ── processPaper:paper spine(download → analyse type B → audit)。author/topic 复用。 ──
async function processPaper(slug, m) {
  phase('Paper')
  const dl = await agent(paperDownloadPrompt(slug, m),
    { agentType: 'quasi:download-agent', label: `download:${slug}`, schema: DL_SCHEMA })
  const item = (dl && dl.per_item && dl.per_item[0]) || {}
  if (item.status !== 'ok') return { slug, status: item.status || 'download_failed' }

  await agent(paperAnalysePrompt(slug, m, item.path),
    { agentType: 'quasi:analyse-agent', label: `analyse:${slug}` })

  let au = await agent(`path: vault/papers/${slug}.md`,
    { agentType: 'quasi:audit-agent', label: `audit:${slug}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(paperAnalysePrompt(slug, m, item.path) + `\noverwrite: true\nreason: audit escalated`,
      { agentType: 'quasi:analyse-agent', label: `regen:${slug}` })
    au = await agent(`path: vault/papers/${slug}.md`,
      { agentType: 'quasi:audit-agent', label: `audit2:${slug}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length) return { slug, status: 'audit_escalated', escalated: au.escalated }
  }
  return { slug, status: 'ok' }
}

// ── processAuthor:search → parallel(books→processBook + papers→processPaper) → synth(author) → audit。 ──
// 复用已验证的 processBook / processPaper,当场消除 author 内联抄 book 的重复。
async function processAuthor(name, m) {
  phase('Author')
  const topic = m.topic || ''
  const full = m.full_name || m.fullName || name

  // 1. discover:两次 search(默认 book 5 / paper 10;meta.maxBooks/maxPapers 可下调,便于有界跑/测试),只读 candidates[]
  const nBooks = Number(m.maxBooks) || 5
  const nPapers = Number(m.maxPapers) || 10
  const [bk, pp] = await parallel([
    () => agent(authorSearchPrompt(full, topic, 'book', nBooks),
      { agentType: 'quasi:search-agent', label: `search-books:${name}`, schema: SEARCH_SCHEMA }),
    () => agent(authorSearchPrompt(full, topic, 'paper', nPapers),
      { agentType: 'quasi:search-agent', label: `search-papers:${name}`, schema: SEARCH_SCHEMA }),
  ])
  const books = (((bk && bk.candidates) || []).filter(b => b && b.slug)).slice(0, nBooks)
  const papers = (((pp && pp.candidates) || []).filter(p => p && p.slug)).slice(0, nPapers)
  if (!books.length && !papers.length) return { name, status: 'no_works' }

  // 2. 存在性探针:一次 agent 查哪些已在 vault → 跳过(不重跑、不破坏性重 extract),仍计入 synth。
  //    匹配是 slug 精确 + ISBN/DOI 标识符两级,所以搜索侧 slug 漂移(同一本书不同 slug)也认得出;
  //    命中时 done.get(slug) 是 **vault 里真实的 slug**,下游读产物必须用它,否则 synth 读不到文件。
  const probe = await agent(existsProbePrompt(books, papers),
    { agentType: 'general-purpose', label: `probe-done:${name}`, schema: PROBE_SCHEMA })
  const resolved = ((probe && probe.resolved) || []).filter(r => r && r.slug && r.vault_slug)
  const doneB = new Map(resolved.filter(r => r.kind !== 'paper').map(r => [r.slug, r.vault_slug]))
  const doneP = new Map(resolved.filter(r => r.kind === 'paper').map(r => [r.slug, r.vault_slug]))
  const freshBooks = books.filter(b => !doneB.has(b.slug))
  const freshPapers = papers.filter(p => !doneP.has(p.slug))

  // 3. 未完成的代表作全并行:书走 processBook(batchYear:year 歧义不卡点、自动收),论文走 processPaper
  const res = (await parallel([
    ...freshBooks.map(b => () => processBook(b.slug, { ...b, topic }, { batchYear: true }).then(r => ({ kind: 'book', ...r }))),
    ...freshPapers.map(p => () => processPaper(p.slug, { ...p, topic }).then(r => ({ kind: 'paper', ...r }))),
  ])).filter(Boolean)
  const okBooks = [...books.filter(b => doneB.has(b.slug)).map(b => doneB.get(b.slug)),
                   ...res.filter(r => r.kind === 'book' && r.status === 'ok').map(r => r.slug)]
  const okPapers = [...papers.filter(p => doneP.has(p.slug)).map(p => doneP.get(p.slug)),
                    ...res.filter(r => r.kind === 'paper' && r.status === 'ok').map(r => r.slug)]
  const yearWarnings = res.filter(r => r.kind === 'book' && r.year_warning).map(r => ({ slug: r.slug, ...r.year_warning }))
  if (!okBooks.length && !okPapers.length) return { name, status: 'all_failed', tried: res.length }

  // 3. synth(author):读书概览 + 论文页
  await agent(authorSynthPrompt(name, full, topic, okBooks, okPapers),
    { agentType: 'quasi:synthesis-agent', label: `synth-author:${name}` })

  // 4. audit 作者 profile + 一次 escalation
  let au = await agent(`path: vault/authors/${name}.md`,
    { agentType: 'quasi:audit-agent', label: `audit-author:${name}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(authorSynthPrompt(name, full, topic, okBooks, okPapers) + `\noverwrite: true\nreason: audit escalated`,
      { agentType: 'quasi:synthesis-agent', label: `regen-author:${name}` })
    au = await agent(`path: vault/authors/${name}.md`,
      { agentType: 'quasi:audit-agent', label: `audit2-author:${name}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length) return { name, status: 'audit_escalated', escalated: au.escalated }
  }

  return { name, status: 'ok', books: okBooks.length, papers: okPapers.length,
    book_failures: res.filter(r => r.kind === 'book' && r.status !== 'ok').length,
    paper_failures: res.filter(r => r.kind === 'paper' && r.status !== 'ok').length,
    year_warnings: yearWarnings.length ? yearWarnings : null }
}

// ── prompt builders:薄,只承载各 agent 期望的契约字段 ──
function bookDownloadPrompt(slug, m, batchYear) {
  return `kind: book
items:
  - slug: ${slug}
    expected_author: ${(m.authors && m.authors[0]) || m.author || ''}
    expected_title: ${m.title || ''}
    identifiers:
      isbn: ${m.isbn || ''}
output_dir: sources/${batchYear ? `
batch_accept_year: true   # 批量模式:若 year_mismatch/ambiguous,仍 quasi-download accept 入 sources/{slug},
                          # per_item.status 返回 ok 并附 year_evidence 作 warning(不保留为 tmp、不冒泡卡点)。` : ''}`
}
function extractPrompt(sourceFile, slug) {
  return `source_file: ${sourceFile}, chapters_dir: processing/chapters/${slug}/
在 EXTRACT_RESULT 里附一个 "chapters" 数组:逐字复制 manifest.json 的 chapters
(每项 slot/title/filename/slug/word_count),不得改写 slug —— slug 由 extract 脚本
确定性生成,是章节输出文件名的稳定标识。`
}
// 幂等提示。存在性信号必须**可打印**:bare `test -e` 无 stdout,存在与否 harness 都显示
// "(no output), is_error:false" → agent 一律判"已存在"直接空跑。与 0.44.3 的探针同一个 bug,
// 当时只修了探针;0.45.0 Bowker E2E 暴露剩下四处:9 章 analyse 全报 success,实际只落 2 章。
const noopIfExists = (output) => `幂等:先跑 \`test -e ${output} && echo EXISTS || echo MISSING\`。
打印 MISSING → 必须完整生成并写入 ${output};打印 EXISTS 且未设 overwrite → 才可 no-op 返回 success。
没写文件却返回 success 是错误。`

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
output: vault/books/${slug}/ch${ch.slot}-${ch.slug}.md
topic: ${m.topic || ''}
${noopIfExists(`vault/books/${slug}/ch${ch.slot}-${ch.slug}.md`)}`
}
function bookSynthPrompt(slug, m) {
  return `mode: book
output_dir: vault/books/${slug}
book_title: ${m.title || ''}
topic: ${m.topic || ''}
${noopIfExists(`vault/books/${slug}/00-overview.md`)}`
}
function existsProbePrompt(books, papers) {
  // 判定全在 bin 里(slug 精确 + ISBN/DOI 两级匹配),agent 只跑命令 + 逐字转述——
  // 不靠 `test -f` 的退出码(bare test 无 stdout,harness 也不暴露非零码 → agent 会全判"存在")。
  const items = [
    ...books.map(b => ({ kind: 'book', slug: b.slug, isbn: b.isbn || null })),
    ...papers.map(p => ({ kind: 'paper', slug: p.slug, doi: p.doi || null })),
  ]
  return `task: 判断下列候选是否已在 vault(只读检查,不改任何文件)。
**原样运行**下面这条命令,它会打印一个 JSON;把其中的 resolved 数组逐字作为你的返回结果,
不要自行判断存在性、不要改写 vault_slug。
\`\`\`bash
quasi-helpers vault resolve --items-file - <<'JSON'
${JSON.stringify(items)}
JSON
\`\`\`
返回 {resolved:[{kind, slug, vault_slug, match}]}。vault_slug 为 null = 尚未处理;
非 null 且与 slug 不同 = 同一作品已在 vault 但 slug 不同(标识符命中),照抄即可。`
}
function authorSearchPrompt(full, topic, kind, count) {
  return `task: find top ${count} representative ${kind}s by ${full}${topic ? ` on topic ${topic}` : ''}, sorted by citations
context:
  kind: ${kind}
  author: ${full}
  topic: ${topic}
constraints:
  count: ${count}
  sort: citations
输出 candidates[],每项带 canonical slug ({author-surname}-{short-title}-{year})、title、authors、year${kind === 'book' ? '、isbn' : '、doi、oa_url、journal'}。`
}
function paperDownloadPrompt(slug, m) {
  return `kind: paper
items:
  - slug: ${slug}
    expected_author: ${(m.authors && m.authors[0]) || m.author || ''}
    expected_title: ${m.title || ''}
    identifiers:
      doi: ${m.doi || ''}
      oa_url: ${m.oa_url || ''}
      url: ${m.url || ''}
output_dir: sources/`
}
function paperAnalysePrompt(slug, m, sourceFile) {
  return `type: B
title: ${m.title || ''}
authors: ${(m.authors || []).join(', ')}
year: ${m.year || ''}
journal: ${m.journal || ''}
doi: ${m.doi || ''}
input: ${sourceFile}
output: vault/papers/${slug}.md
topic: ${m.topic || ''}
${noopIfExists(`vault/papers/${slug}.md`)}`
}
function authorSynthPrompt(name, full, topic, okBooks, okPapers) {
  const bops = okBooks.map(s => `vault/books/${s}/00-overview.md`)
  const pps = okPapers.map(s => `vault/papers/${s}.md`)
  return `mode: author
author_name: ${name}
full_name: ${full}
topic: ${topic}
output_path: vault/authors/${name}.md
book_overview_paths: ${JSON.stringify(bops)}
paper_paths: ${JSON.stringify(pps)}
${noopIfExists(`vault/authors/${name}.md`)}`
}

// ── router / 入口 ──
async function router(kind, a) {
  switch (kind) {
    case 'book': return processBook(a.slug, a.meta || a)
    case 'paper': return processPaper(a.slug, a.meta || a)
    case 'author': return processAuthor(a.name || a.author_name, a.meta || a)
    case 'topic':
      throw new Error(`process-material: kind "topic" 未实现(book/paper/author 已实现)。见 docs/process-material-design.md §7`)
    default:
      throw new Error(`process-material: 未知 kind "${kind}"`)
  }
}

const a = args || {}
if (!a.kind) throw new Error('process-material: 需要 args.kind(book|paper|author|topic)')
const result = await router(a.kind, a)
log(`process-material result: ${JSON.stringify(result)}`)
return result
