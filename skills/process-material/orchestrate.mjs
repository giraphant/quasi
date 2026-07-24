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
//    每个脚本真正读字段的回执都要加;只有纯 fire-and-forget 的重投可以不加。
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
// analyse / synth 回执:0.45.0 的 Bowker E2E 证明"agent 报 success 却没写文件"会静默传播
// (9 章只落 2 章,synth 照 2 章写概览,图仍报 book_failures:0)。所以这两个回执也要读。
// analyse 的 status/notes 承载扫描版 PDF 的 OCR 兜底信号(契约见 agents/analyse-agent.md Step 1);
// synth 的 chapters_analyzed 是**另一个 agent 实际 Glob 过磁盘**得出的数 —— 拿它跟 extract 出的
// 章数对账,比信 analyse 自报可靠得多(自报正是上面骗过图的那一环)。
const AN_SCHEMA = { type: 'object', required: ['status'], properties: {
  status: { type: 'string' }, notes: { type: 'string' }, output: { type: 'string' } } }
const SY_SCHEMA = { type: 'object', properties: {
  status: { type: 'string' }, inputs_analyzed: { type: 'number' }, chapters_analyzed: { type: 'number' } } }
const OCR_SCHEMA = { type: 'object', required: ['status'], properties: {
  status: { type: 'string' }, chars: { type: 'number' }, note: { type: 'string' } } }

// synth 报的"实际读到的章数"。字段缺失一律按 0 处理 —— 对账要 fail closed,
// 缺信号时宁可多跑一轮(缺的章才会真写,其余 no-op)也不能默认通过。
const analysedCount = (sy) => Number(sy && sy.chapters_analyzed) || 0

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
      { agentType: 'quasi:analyse-agent', label: `analyse:${slug}:${ch.slot}`, schema: AN_SCHEMA })))

  // synth(book) + 完整性对账 ── synth 只递目录/slug,自己 Glob vault 的 ch*.md,所以回执的
  // chapters_analyzed 是**磁盘上真实的章数**;少于 extract 出的章数 = 有 analyse 空跑没落盘。
  // 补投一轮(幂等提示让已完成的章 no-op,只有缺的章真写)再 synth;仍然少就如实报残缺,不报 ok。
  let sy = await agent(bookSynthPrompt(slug, m),
    { agentType: 'quasi:synthesis-agent', label: `synth:${slug}`, schema: SY_SCHEMA })
  if (analysedCount(sy) < chapters.length) {
    log(`${slug}: 章节残缺 ${analysedCount(sy)}/${chapters.length},补投缺失章`)
    await parallel(chapters.map(ch => () =>
      agent(analyseChapterPrompt(slug, m, ch),
        { agentType: 'quasi:analyse-agent', label: `refill:${slug}:${ch.slot}`, schema: AN_SCHEMA })))
    sy = await agent(bookSynthPrompt(slug, m),
      { agentType: 'quasi:synthesis-agent', label: `synth2:${slug}`, schema: SY_SCHEMA })
    if (analysedCount(sy) < chapters.length)
      return { slug, status: 'chapters_incomplete', analysed: analysedCount(sy), expected: chapters.length }
  }

  // audit + 一次 escalation 回环 ── 章用 chapters(在 scope 内)重投,概览用 synth 重投
  let au = await agent(`path: vault/books/${slug}`,
    { agentType: 'quasi:audit-agent', label: `audit:${slug}`, schema: AU_SCHEMA })
  const esc = (au && au.escalated) || []
  if (esc.length) {
    await parallel(esc.map(e => () => {
      const p = e.path || ''
      if (p.endsWith('/00-overview.md'))
        return agent(bookSynthPrompt(slug, m) + `\nreason: audit escalated ${e.kind}: ${e.reason}`,
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

  let src = item.path
  let an = await agent(paperAnalysePrompt(slug, m, src),
    { agentType: 'quasi:analyse-agent', label: `analyse:${slug}`, schema: AN_SCHEMA })
  // 回执为 null = agent 死在终端 API 错误上(Bowker biodiversity 首跑就是 "Connection closed
  // mid-response")。这跟"内容处理失败"不是一回事,重投一次。书那边不用管:章节残缺会被下面的
  // synth 对账抓到并自动补投。
  if (!an) an = await agent(paperAnalysePrompt(slug, m, src),
    { agentType: 'quasi:analyse-agent', label: `analyse-retry:${slug}`, schema: AN_SCHEMA })

  // 扫描版兜底 ── 无文本层的 PDF,analyse-agent 按契约返回 status:error + notes"需 OCR"
  // (明令不许凭训练知识补完)。书路径早有 quasi-extract ocr,论文路径原来到此直接失败
  // (Bowker biodiversity 2000)。补一段:OCR 出带文本层的 PDF,拿它重跑 analyse。
  if (an && an.status !== 'success' && /OCR|扫描|图像|scan/i.test(an.notes || '')) {
    const ocrPath = `.quasi/temp/${slug}.ocr.pdf`
    const ocr = await agent(ocrPrompt(src, ocrPath),
      { agentType: 'general-purpose', label: `ocr:${slug}`, schema: OCR_SCHEMA })
    if (ocr && ocr.status === 'ok') {
      src = ocrPath
      an = await agent(paperAnalysePrompt(slug, m, src) + `\nreason: 原 PDF 无文本层,已 OCR 后重跑`,
        { agentType: 'quasi:analyse-agent', label: `analyse-ocr:${slug}`, schema: AN_SCHEMA })
    }
  }
  if (!an || an.status !== 'success')
    return { slug, status: 'analyse_failed', notes: (an && an.notes) || null }

  let au = await agent(`path: vault/papers/${slug}.md`,
    { agentType: 'quasi:audit-agent', label: `audit:${slug}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(paperAnalysePrompt(slug, m, src) + `\noverwrite: true\nreason: audit escalated`,
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

  // 3. synth(author):读书概览 + 论文页。回执只用来判死活——没写出 profile 就别接着 audit 一个不存在的文件。
  const sa = await agent(authorSynthPrompt(name, full, topic, okBooks, okPapers),
    { agentType: 'quasi:synthesis-agent', label: `synth-author:${name}`, schema: SY_SCHEMA })
  if (!sa || sa.status === 'error')
    return { name, status: 'synth_failed', books: okBooks.length, papers: okPapers.length,
             notes: sa && sa.notes }

  // 4. audit 作者 profile + 一次 escalation
  let au = await agent(`path: vault/authors/${name}.md`,
    { agentType: 'quasi:audit-agent', label: `audit-author:${name}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(authorSynthPrompt(name, full, topic, okBooks, okPapers) + `\nreason: audit escalated`,
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
// 幂等提示。只给 analyse 用(章节 / 论文)——synth 一律重跑,见 bookSynthPrompt。
// 存在性信号必须**可打印**:bare `test -e` 无 stdout,存在与否 harness 都显示
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
// synth 不幂等,总是重生成:它的回执 chapters_analyzed 是图唯一的"章节真落盘了吗"信号,
// no-op 会让这个数失真;而且续跑时章节集合可能刚补齐,旧概览必须跟着刷新。
function bookSynthPrompt(slug, m) {
  return `mode: book
output_dir: vault/books/${slug}
book_title: ${m.title || ''}
topic: ${m.topic || ''}
overwrite: true   # 即使 00-overview.md 已存在也要重读章节、重新生成。
SYNTHESIS_RESULT 的 chapters_analyzed 必须是你**实际 Glob 到并读了**的 ch*.md 数量,不要估算。`
}
function existsProbePrompt(books, papers) {
  // 判定全在 bin 里(slug 精确 → ISBN/DOI → 标题+作者姓,三级),agent 只跑命令 + 逐字转述——
  // 不靠 `test -f` 的退出码(bare test 无 stdout,harness 也不暴露非零码 → agent 会全判"存在")。
  // title/authors 必须一起传:全库约 9% 的书没 isbn、7% 的论文没 doi,只传标识符对它们必然 miss。
  const items = [
    ...books.map(b => ({ kind: 'book', slug: b.slug, isbn: b.isbn || null,
                         title: b.title || null, authors: b.authors || null })),
    ...papers.map(p => ({ kind: 'paper', slug: p.slug, doi: p.doi || null,
                          title: p.title || null, authors: p.authors || null })),
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
非 null 且与 slug 不同 = 同一作品已在 vault 但 slug 不同(标识符或标题命中),照抄即可。`
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
overwrite: true   # 作者页总是重生成:每跑一次代表作集合都可能扩张,no-op 会让 profile 停在旧版本。`
}

function ocrPrompt(input, output) {
  // 只跑命令 + 转述可打印的结果。判定不能靠退出码:静默失败在 harness 里同样是
  // "(no output), is_error:false" → agent 会一律判成功。所以命令自己打印 OCR_CHARS=N。
  return `task: 给无文本层的扫描版 PDF 加文本层(只跑命令,不分析内容)。原样运行:
\`\`\`bash
mkdir -p .quasi/temp
quasi-extract ocr "${input}" "${output}" 2>&1 | tail -5
N=$([ -s "${output}" ] && pdftotext "${output}" - 2>/dev/null | wc -c | tr -d ' ' || echo 0)
echo "OCR_CHARS=$N"
\`\`\`
按打印出的 OCR_CHARS 返回:≥ 500 → {status:"ok", chars:N};否则 {status:"failed", chars:N, note:最后几行报错}。
不要改写 ${input},不要碰 vault/。`
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
