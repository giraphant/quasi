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
// 四个分支都已实现:processBook / processPaper / processAuthor / processTopic。
//   author = parallel(books→processBook + papers→processPaper) → synth(author) → audit。
//   topic  = loop-until-dry(探针 → parallel(items→router) → 滚雪球) → synth(topic) → audit。
// 递归复用是全部价值:author 不再内联抄 book,topic 的每个条目就是同一个 router。

export const meta = {
  name: 'process-material',
  description: 'Unified acquisition→analysis graph: router(kind) → book | paper | author | topic',
  phases: [{ title: 'Book' }, { title: 'Paper' }, { title: 'Author' }, { title: 'Topic' }],
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
// search-agent 回执:author/topic discovery 读 candidates[](每项必须带 canonical slug)。
// author 搜索按 kind 分两次调用、kind 自明;topic 一次调用里混着书和论文,靠每项的 kind 分流。
const SEARCH_SCHEMA = { type: 'object', properties: {
  candidates: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
    kind: { type: 'string' },
    slug: { type: 'string' }, title: { type: 'string' }, authors: { type: 'array' },
    year: {}, isbn: { type: 'string' }, doi: { type: 'string' },
    oa_url: { type: 'string' }, url: { type: 'string' }, journal: { type: 'string' } } } } } }
// 滚雪球回执 = 候选表 + 枯竭时的拓宽建议词(死胡同卡点要把建议原样递给用户)。
const REFS_SCHEMA = { type: 'object', properties: {
  ...SEARCH_SCHEMA.properties, suggested_queries: { type: 'array', items: { type: 'string' } } } }
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
  status: { type: 'string' }, notes: { type: 'string' }, output: { type: 'string' },
  needs_ocr: { type: 'boolean' } } }
const SY_SCHEMA = { type: 'object', properties: {
  status: { type: 'string' }, inputs_analyzed: { type: 'number' }, chapters_analyzed: { type: 'number' } } }
const OCR_SCHEMA = { type: 'object', required: ['status'], properties: {
  status: { type: 'string' }, chars: { type: 'number' }, note: { type: 'string' } } }
// 本地召回回执:主题跑的语料首先是**库里已有的东西**。探针只能跳过"在线搜索找得到的"作品,
// 找不到就等于不存在 —— 0.48.1 的 topic E2E 里 6 部强相关的种子作品只有 1 部被搜索命中,
// 综述最后一个 wikilink 都没指回库内。所以先扫一遍 vault,再去外面搜。
const RECALL_SCHEMA = { type: 'object', properties: {
  items: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
    kind: { type: 'string' }, slug: { type: 'string' } } } } } }

// synth 报的"实际读到的章数"。字段缺失一律按 0 处理 —— 对账要 fail closed,
// 缺信号时宁可多跑一轮(缺的章才会真写,其余 no-op)也不能默认通过。
const analysedCount = (sy) => Number(sy && sy.chapters_analyzed) || 0

// agent() 返回 null = agent 死在终端 API 错误上("Server error mid-response" /
// "stream error: INTERNAL_ERROR"),跟"内容处理失败"不是一回事 —— 原地重投一次。
// 没有这层时,一次瞬时 API 抖动就要靠整轮 refill 兜,而 refill 只有一轮:Bowker
// memory-practices 实测 ch04/ch07 首轮双双死于 API 错误,refill 救回 ch04、ch07 又死一次
// → 全书停在 8/9。
// 写产物的 agent(analyse/synth)重投要带 OVERWRITE:走到这一步就说明上一次没产出,产物按
// 定义不存在;给幂等 no-op 的许可反而让 agent 谎报成功(Bowker biodiversity 2000 实测:
// analyse-ocr 报 success + notes"目标文件已存在,按幂等协议 no-op",紧接着的 audit 却
// target.exists=false)。只读/命令型 agent(download/extract/audit/probe/search)不加。
const OVERWRITE = '\noverwrite: true'
const retryNull = async (prompt, opts, retrySuffix = '') =>
  (await agent(prompt, opts)) ?? agent(prompt + retrySuffix,
    { ...opts, label: `${opts.label}:retry` })

// ── processBook:承重节点。author = parallel(books→processBook);topic = pipeline(items→router)。 ──
// opts.batchYear=true(author 批量):year_mismatch/ambiguous 不冒泡卡点,download-agent 直接
// accept 入 sources 并把 year_evidence 作 warning,status 返回 ok(单本 book 入口不传,走卡点)。
async function processBook(slug, m, opts = {}) {
  phase('Book')

  // download ── 回执:status/path/year_evidence   产物:PDF 落 sources/
  const dl = await retryNull(bookDownloadPrompt(slug, m, opts.batchYear),
    { agentType: 'quasi:download-agent', label: `download:${slug}`, schema: DL_SCHEMA })
  const item = (dl && dl.per_item && dl.per_item[0]) || {}
  if (item.status !== 'ok')
    return { slug, status: item.status || 'download_failed',
             year_evidence: item.year_evidence, tmp_path: item.tmp_path }

  // extract ── 章节列表从回执带回(脚本无 fs,不读 manifest)  产物:manifest+txt 落 processing/
  const ex = await retryNull(extractPrompt(item.path, slug),
    { agentType: 'quasi:extract-agent', label: `extract:${slug}`, schema: EX_SCHEMA })
  if (!ex || ex.status === 'failed')
    return { slug, status: 'extract_failed', problems: ex && ex.problems }
  const chapters = ex.chapters || []
  if (!chapters.length) return { slug, status: 'no_chapters' }
  log(`${slug}: 提取出 ${chapters.length} 章,开始并行分析`)

  // fan-out analyse ── 每章一个 agent;正文在 processing/,分析写 vault/;幂等 agent 自跳过已完成章 = 续跑
  await parallel(chapters.map(ch => () =>
    retryNull(analyseChapterPrompt(slug, m, ch),
      { agentType: 'quasi:analyse-agent', label: `analyse:${slug}:${ch.slot}`, schema: AN_SCHEMA }, OVERWRITE)))

  // synth(book) + 完整性对账 ── synth 只递目录/slug,自己 Glob vault 的 ch*.md,所以回执的
  // chapters_analyzed 是**磁盘上真实的章数**;少于 extract 出的章数 = 有 analyse 空跑没落盘。
  // 补投一轮(幂等提示让已完成的章 no-op,只有缺的章真写)再 synth;仍然少就如实报残缺,不报 ok。
  let sy = await retryNull(bookSynthPrompt(slug, m),
    { agentType: 'quasi:synthesis-agent', label: `synth:${slug}`, schema: SY_SCHEMA }, OVERWRITE)
  if (analysedCount(sy) < chapters.length) {
    log(`${slug}: 章节残缺 ${analysedCount(sy)}/${chapters.length},补投缺失章`)
    await parallel(chapters.map(ch => () =>
      retryNull(analyseChapterPrompt(slug, m, ch),
        { agentType: 'quasi:analyse-agent', label: `refill:${slug}:${ch.slot}`, schema: AN_SCHEMA }, OVERWRITE)))
    sy = await retryNull(bookSynthPrompt(slug, m),
      { agentType: 'quasi:synthesis-agent', label: `synth2:${slug}`, schema: SY_SCHEMA }, OVERWRITE)
    if (analysedCount(sy) < chapters.length)
      return { slug, status: 'chapters_incomplete', analysed: analysedCount(sy), expected: chapters.length }
  }

  // audit + 一次 escalation 回环 ── 章用 chapters(在 scope 内)重投,概览用 synth 重投
  let au = await retryNull(`path: vault/books/${slug}`,
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
    au = await retryNull(`path: vault/books/${slug}`,
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
  const dl = await retryNull(paperDownloadPrompt(slug, m),
    { agentType: 'quasi:download-agent', label: `download:${slug}`, schema: DL_SCHEMA })
  const item = (dl && dl.per_item && dl.per_item[0]) || {}
  if (item.status !== 'ok') return { slug, status: item.status || 'download_failed' }

  let src = item.path
  let an = await retryNull(paperAnalysePrompt(slug, m, src),
    { agentType: 'quasi:analyse-agent', label: `analyse:${slug}`, schema: AN_SCHEMA }, OVERWRITE)

  // 扫描版兜底 ── 无文本层的 PDF,analyse-agent 按契约返回 status:error + needs_ocr:true
  // (明令不许凭训练知识补完)。书路径早有 quasi-extract ocr,论文路径原来到此直接失败
  // (Bowker biodiversity 2000)。补一段:OCR 出带文本层的 PDF,拿它重跑 analyse。
  // 判据只认结构化的 needs_ocr;自由文本正则是过渡期兜底 ── 0.48.0 topic E2E 里两篇 Star
  // 论文正是"需 OCR"写进了 output、notes 换了措辞,只测 notes 的正则零命中,两篇静默丢失。
  // 故意 fail-open:多跑一次 OCR 只浪费几分钟,漏跑一次是整篇论文无声消失。
  if (an && an.status !== 'success' &&
      (an.needs_ocr === true || /OCR|扫描|图像|scan/i.test(`${an.notes || ''} ${an.output || ''}`))) {
    const ocrPath = `.quasi/temp/${slug}.ocr.pdf`
    log(`${slug}: PDF 无文本层,转 OCR 后重跑分析`)
    const ocr = await retryNull(ocrPrompt(src, ocrPath),
      { agentType: 'general-purpose', label: `ocr:${slug}`, schema: OCR_SCHEMA })
    if (ocr && ocr.status === 'ok') {
      src = ocrPath
      an = await retryNull(paperAnalysePrompt(slug, m, src) + OVERWRITE + `\nreason: 原 PDF 无文本层,已 OCR 后重跑`,
        { agentType: 'quasi:analyse-agent', label: `analyse-ocr:${slug}`, schema: AN_SCHEMA })
    }
  }
  if (!an || an.status !== 'success')
    return { slug, status: 'analyse_failed', notes: (an && an.notes) || null }

  let au = await retryNull(`path: vault/papers/${slug}.md`,
    { agentType: 'quasi:audit-agent', label: `audit:${slug}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(paperAnalysePrompt(slug, m, src) + `\noverwrite: true\nreason: audit escalated`,
      { agentType: 'quasi:analyse-agent', label: `regen:${slug}` })
    au = await retryNull(`path: vault/papers/${slug}.md`,
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
    () => retryNull(authorSearchPrompt(full, topic, 'book', nBooks),
      { agentType: 'quasi:search-agent', label: `search-books:${name}`, schema: SEARCH_SCHEMA }),
    () => retryNull(authorSearchPrompt(full, topic, 'paper', nPapers),
      { agentType: 'quasi:search-agent', label: `search-papers:${name}`, schema: SEARCH_SCHEMA }),
  ])
  const books = (((bk && bk.candidates) || []).filter(b => b && b.slug)).slice(0, nBooks)
  const papers = (((pp && pp.candidates) || []).filter(p => p && p.slug)).slice(0, nPapers)
  if (!books.length && !papers.length) return { name, status: 'no_works' }

  // 2. 存在性探针:一次 agent 查哪些已在 vault → 跳过(不重跑、不破坏性重 extract),仍计入 synth。
  //    匹配是 slug 精确 → ISBN/DOI → 标题+作者姓三级,所以搜索侧 slug 漂移(同一本书不同 slug)也认得出;
  //    命中时 done.get(slug) 是 **vault 里真实的 slug**,下游读产物必须用它,否则 synth 读不到文件。
  //    这一步空回执的代价最大(全批当成没做过 → 对已入库的书做破坏性重 extract),所以必须重投。
  const probe = await retryNull(existsProbePrompt(books, papers),
    { agentType: 'general-purpose', label: `probe-done:${name}`, schema: PROBE_SCHEMA })
  const resolved = ((probe && probe.resolved) || []).filter(r => r && r.slug && r.vault_slug)
  const doneB = new Map(resolved.filter(r => r.kind !== 'paper').map(r => [r.slug, r.vault_slug]))
  const doneP = new Map(resolved.filter(r => r.kind === 'paper').map(r => [r.slug, r.vault_slug]))
  const freshBooks = books.filter(b => !doneB.has(b.slug))
  const freshPapers = papers.filter(p => !doneP.has(p.slug))
  log(`${name}: 代表作 ${books.length} 书 / ${papers.length} 文,库内已有 ${doneB.size}+${doneP.size},新处理 ${freshBooks.length}+${freshPapers.length}`)

  // 3. 未完成的代表作全并行:书走 processBook(batchYear:year 歧义不卡点、自动收),论文走 processPaper
  const res = (await parallel([
    ...freshBooks.map(b => () => processBook(b.slug, { ...b, topic }, { batchYear: true }).then(r => ({ kind: 'book', ...r }))),
    ...freshPapers.map(p => () => processPaper(p.slug, { ...p, topic }).then(r => ({ kind: 'paper', ...r }))),
  ])).filter(Boolean)
  // Set 去重:两个不同 slug 的候选可能被探针解析到**同一个** vault_slug(同一本书两种搜索命名),
  // 不去重就是重复路径进 synth 合同 —— 0.48.3 在 topic 修过的同一类账,author 这边一并结清。
  const okBooks = [...new Set([...books.filter(b => doneB.has(b.slug)).map(b => doneB.get(b.slug)),
                   ...res.filter(r => r.kind === 'book' && r.status === 'ok').map(r => r.slug)])]
  const okPapers = [...new Set([...papers.filter(p => doneP.has(p.slug)).map(p => doneP.get(p.slug)),
                    ...res.filter(r => r.kind === 'paper' && r.status === 'ok').map(r => r.slug)])]
  const yearWarnings = res.filter(r => r.kind === 'book' && r.year_warning).map(r => ({ slug: r.slug, ...r.year_warning }))
  if (!okBooks.length && !okPapers.length) return { name, status: 'all_failed', tried: res.length }

  // 3. synth(author):读书概览 + 论文页。回执只用来判死活——没写出 profile 就别接着 audit 一个不存在的文件。
  const sa = await retryNull(authorSynthPrompt(name, full, topic, okBooks, okPapers),
    { agentType: 'quasi:synthesis-agent', label: `synth-author:${name}`, schema: SY_SCHEMA }, OVERWRITE)
  if (!sa || sa.status === 'error')
    return { name, status: 'synth_failed', books: okBooks.length, papers: okPapers.length,
             notes: sa && sa.notes }

  // 4. audit 作者 profile + 一次 escalation
  let au = await retryNull(`path: vault/authors/${name}.md`,
    { agentType: 'quasi:audit-agent', label: `audit-author:${name}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(authorSynthPrompt(name, full, topic, okBooks, okPapers) + `\nreason: audit escalated`,
      { agentType: 'quasi:synthesis-agent', label: `regen-author:${name}` })
    au = await retryNull(`path: vault/authors/${name}.md`,
      { agentType: 'quasi:audit-agent', label: `audit2-author:${name}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length) return { name, status: 'audit_escalated', escalated: au.escalated }
  }

  return { name, status: 'ok', books: okBooks.length, papers: okPapers.length,
    book_slugs: okBooks,   // 入口 skill 的 LOCALISE 循环按这份名单回填中译本;localise scan 按 ISBN 幂等,重复跑零成本
    book_failures: res.filter(r => r.kind === 'book' && r.status !== 'ok').length,
    paper_failures: res.filter(r => r.kind === 'paper' && r.status !== 'ok').length,
    year_warnings: yearWarnings.length ? yearWarnings : null }
}

// ── processTopic:discover → 滚雪球(探针 → parallel(items→router) → 摘核心引用)→ synth(topic) → audit。 ──
// 老 process-topic 用 `superset agents create` 跨会话 fire-and-forget 派 process-{paper,book,author}:
// 只回一个 sessionId,没有 transcript / status / result,完成与否只能靠 poll-agent 轮询 vault 产物
// + agent 自写哨兵去**猜**。那正是这一整轮在修的 bug 类型(没有可观测信号就默认成功)。
// 图内直接递归调 router,每个条目都有 schema 校验过的回执,于是 poll-agent / sentinel /
// prompt-file / final_status 状态机整套机关一起消失。
async function processTopic(slug, m) {
  phase('Topic')
  const desc = m.desc || m.topic_desc || slug
  const maxRounds = Number(m.maxRounds) || 3
  const perRound = Number(m.maxPerRound) || 8

  // 1. 本地召回 + 在线发现,并行。两件事互不依赖:库里已有什么,与外面还有什么,是两个问题。
  //    本地召回不是可有可无的优化——它是主题综述的**主要语料来源**。一个读书库里之所以有
  //    这些书,正因为它们属于用户关心的主题;探针只覆盖"搜索恰好也找到了"的交集,库里其余
  //    强相关作品会整批漏掉(0.48.1 topic E2E:6 部种子只有 1 部进了综述)。
  const [rc, sr] = await parallel([
    () => retryNull(vaultRecallPrompt(desc, perRound * 2),
      { agentType: 'general-purpose', label: `recall:${slug}`, schema: RECALL_SCHEMA }),
    () => retryNull(topicSearchPrompt(desc, perRound, m.seeds),
      { agentType: 'quasi:search-agent', label: `search-topic:${slug}`, schema: SEARCH_SCHEMA }),
  ])
  // 召回到的作品已经分析过,直接就是语料;它们的「## 核心引用」也参与第 1 轮滚雪球。
  // talk 只可能来自召回(在线发现搜不到你录的讲座),不进 router;book/paper 之外的未知 kind 按 paper 兜底
  const local = ((rc && rc.items) || []).filter(i => i && i.slug)
    .map(i => ({ kind: i.kind === 'book' || i.kind === 'talk' ? i.kind : 'paper', slug: i.slug }))
  let queue = ((sr && sr.candidates) || []).filter(c => c && c.slug)
  if (!queue.length && !local.length) return { slug, status: 'no_works' }

  // 召回到的作品已分析过,直接进语料 —— 即便一轮都没跑起来也不会丢。
  const seen = new Set(local.map(i => i.slug)), ok = [...local], failures = []
  let round = 0, suggested = null
  const isBook = c => (c.kind || 'paper') === 'book'

  // 2. 滚雪球 loop-until-dry:候选枯竭或轮数用尽即停。轮数与每轮条数都有上界——
  //    一个主题的引文网络是发散的,不设界就是无限 fan-out。
  while (queue.length && round < maxRounds) {
    round++
    const batch = queue.filter(c => !seen.has(c.slug)).slice(0, perRound)
    batch.forEach(c => seen.add(c.slug))
    if (!batch.length) break

    // 探针:已入库的直接收编,不重跑(尤其不对已入库的书做破坏性重 extract)。
    // 主题跑跨越已有语料的概率比作者跑更高——同一篇论文常同时属于多个主题。
    const probe = await retryNull(existsProbePrompt(batch.filter(isBook), batch.filter(c => !isBook(c))),
      { agentType: 'general-purpose', label: `probe-done:${slug}:r${round}`, schema: PROBE_SCHEMA })
    const done = new Map(((probe && probe.resolved) || [])
      .filter(r => r && r.slug && r.vault_slug).map(r => [r.slug, r.vault_slug]))

    // 递归:同一个 router、同一批已验证的 processBook / processPaper。书走 batchYear——
    // 批量跑里年份歧义不能卡住整轮,自动收下并记 warning(与 author 批量同策)。
    // author 候选默认不派:一个作者会拖进 5 本书 + 10 篇论文,主题跑会当场爆量;
    // 要连作者一起铺开得显式开 meta.allowAuthors。
    const fresh = batch.filter(c => !done.has(c.slug))
      .filter(c => m.allowAuthors || (c.kind || 'paper') !== 'author')
    const res = (await parallel(fresh.map(c => () => {
      const kind = isBook(c) ? 'book' : (c.kind === 'author' ? 'author' : 'paper')
      return router(kind, { slug: c.slug, name: c.slug, meta: { ...c, topic: slug } }, { batchYear: true })
        .then(r => ({ kind, slug: c.slug, ...r }))
    }))).filter(Boolean)

    const roundOk = [
      ...batch.filter(c => done.has(c.slug))
        .map(c => ({ kind: isBook(c) ? 'book' : 'paper', slug: done.get(c.slug) })),
      ...res.filter(r => r.status === 'ok').map(r => ({ kind: r.kind, slug: r.slug })),
    ].filter(i => !ok.some(o => o.slug === i.slug))
    // ↑ 探针收编返回的 vault_slug 可能正是召回过的那部(seen 只挡候选 slug,挡不住
    //   vault_slug)——0.48.2 E2E 里两条重复路径进了 synth 合同。语料表是给下游的数据,
    //   规范性在源头保证,不留给 synthesis-agent 自行去重。
    ok.push(...roundOk)
    failures.push(...res.filter(r => r.status !== 'ok').map(r => ({ slug: r.slug, status: r.status })))
    // 第 1 轮的滚雪球源并上本地召回:那些正文的「## 核心引用」同样是这个主题的引文网络,
    // 而且它们往往是库里最相关的作品,漏掉等于把雪球起点砍掉一半。
    const snowSrc = round === 1 ? [...local, ...roundOk] : roundOk
    if (!snowSrc.length) break   // 没有正文可摘引用,滚不动了

    // 滚雪球:读本轮落地正文的「## 核心引用」→ 下一轮候选。
    // 交给 search-agent 而不是通用 agent:正文里的引用只有"作者-年-标题",要变成可处理的候选
    // 必须补上 doi/isbn(下游 download 靠它),那正是 search-agent 的活,而且它只读不写。
    const refs = await retryNull(snowballPrompt(desc, snowSrc, [...seen]),
      { agentType: 'quasi:search-agent', label: `snowball:${slug}:r${round}`, schema: REFS_SCHEMA })
    queue = ((refs && refs.candidates) || []).filter(c => c && c.slug && !seen.has(c.slug))
    suggested = (refs && refs.suggested_queries) || null
    log(`${slug}: 第 ${round} 轮 +${roundOk.length} 条(累计 ${ok.length}),下轮候选 ${queue.length}`)
  }

  // 3. 死胡同卡点:候选枯竭且语料太薄 → 不硬写一篇没底子的综述,冒泡让入口 skill 问用户补种子词。
  //    用户不想补时,入口带 meta.final=true 原样重投直接收口(条目全幂等,重跑几乎零成本)。
  const minItems = Number(m.minItems) || 3
  if (!m.final && !queue.length && ok.length < minItems)
    return { slug, status: 'needs_seeds', collected: ok.length, rounds: round,
             suggested_queries: suggested, failures: failures.length }
  if (!ok.length) return { slug, status: 'all_failed', tried: failures.length }

  // 4. synth(topic):综述 + 阅读清单两页。回执判死活,没写出来就别 audit 一个不存在的文件。
  const sy = await retryNull(topicSynthPrompt(slug, desc, ok),
    { agentType: 'quasi:synthesis-agent', label: `synth-topic:${slug}`, schema: SY_SCHEMA }, OVERWRITE)
  if (!sy || sy.status === 'error')
    return { slug, status: 'synth_failed', items: ok.length, notes: sy && sy.notes }

  // 5. audit + 一次 escalation 回环
  let au = await retryNull(`path: vault/topics/${slug}`,
    { agentType: 'quasi:audit-agent', label: `audit-topic:${slug}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await agent(topicSynthPrompt(slug, desc, ok) + `\nreason: audit escalated`,
      { agentType: 'quasi:synthesis-agent', label: `regen-topic:${slug}` })
    au = await retryNull(`path: vault/topics/${slug}`,
      { agentType: 'quasi:audit-agent', label: `audit2-topic:${slug}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length) return { slug, status: 'audit_escalated', escalated: au.escalated }
  }

  return { slug, status: 'ok', items: ok.length, recalled: local.length, rounds: round,
           // topic 落地的书同样要中译本回填;和 author 一致,LOCALISE 循环需要名单不是计数
           book_slugs: [...new Set(ok.filter(i => i.kind === 'book').map(i => i.slug))],
           failures: failures.length, dead_end: !queue.length }
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

// 语料条目 → 产物路径。topic 的语料散在几处,没有单一目录可 glob,所以图直接给精确路径表。
const itemPath = (it) => it.kind === 'book' ? `vault/books/${it.slug}/00-overview.md`
  : it.kind === 'author' ? `vault/authors/${it.slug}.md`
  : it.kind === 'talk' ? `vault/talks/${it.slug}/talk.md` : `vault/papers/${it.slug}.md`

function vaultRecallPrompt(desc, max) {
  // 主题的语料首先是库里已有的东西:一个读书库之所以存了这些书,正因为它们属于用户关心的主题。
  // 在线搜索只覆盖"外面还有什么",探针只能跳过"搜索恰好也找到了的",库内其余强相关作品整批漏掉
  // (0.48.1 topic E2E:6 部种子作品只有 1 部进了综述,末稿一个 wikilink 都没指回库内)。
  // talks 同理:讲座只能从本地来(在线发现永远搜不到你录的讲座),不扫它就是永久盲区。
  // rg -il 会把命中的文件名打出来 —— 有可观测输出,不靠退出码。
  return `task: 在本地 vault 里召回与主题 "${desc}" 相关的、**已经分析过**的作品(书/论文/讲座;只读,不写任何文件)。
1. 给主题拟 6-12 个检索词:中英各半(库是双语的),含同义词与该主题的代表人名/术语。
2. 逐个跑(一次一个 -e 参数堆在同一条命令里即可):
   \`\`\`bash
   rg -il -e '关键词1' -e '关键词2' ... vault/books vault/papers vault/talks | head -120
   \`\`\`
3. 命中路径 → slug:\`vault/books/{slug}/*.md\` 与 \`vault/talks/{slug}/*.md\` 取目录名,
   \`vault/papers/{slug}.md\` 取文件名去掉 .md。同一作品多个文件命中算一条。
4. 逐条 Read 该作品的产物首部(书 \`vault/books/{slug}/00-overview.md\`、论文 \`vault/papers/{slug}.md\`、
   讲座 \`vault/talks/{slug}/talk.md\`)的 frontmatter 与开头几行,确认 title/themes 确实与主题相关;
   只是正文顺带提了一句的丢弃。
5. 按相关度排序,最多返回 ${max} 条。

输出 {items:[{kind:"book"|"paper"|"talk", slug}]}。slug 必须是**磁盘上真实存在的**那个,不要改写、不要新造。
一条都没有就返回 {items:[]}。`
}

function topicSearchPrompt(desc, count, seeds) {
  return `task: find the ${count} most important papers and books on the topic "${desc}", sorted by citations
context:
  kind: paper
  topic: ${desc}${seeds && seeds.length ? `
  extra_queries: ${JSON.stringify(seeds)}   # 用户补的种子检索词,优先照这些搜` : ''}
constraints:
  count: ${count}
  sort: citations
输出 candidates[],每项带 kind(book|paper)、canonical slug ({author-surname}-{short-title}-{year})、
title、authors、year;书带 isbn,论文带 doi、oa_url、journal。查不到标识符的不要输出——
下游要靠标识符下载。`
}
function snowballPrompt(desc, roundOk, seenSlugs) {
  return `task: 从下列已完成的分析里摘出被反复引用的关键文献,作为主题 "${desc}" 的下一轮候选。
1. 逐个 Read 这些文件,**只看正文的 \`## 核心引用\`(书/论文)或 \`## 文献人物\`(讲座)一节**,其余不用读:
   ${JSON.stringify(roundOk.map(itemPath))}
2. 汇总引用条目,按被引次数排序,去掉与主题无关的。
3. 排除已经处理过的 slug:${JSON.stringify(seenSlugs)}
4. 对剩下的用 quasi-search 补标识符(书 isbn,论文 doi/oa_url/journal);补不到的丢弃。
输出 candidates[],每项带 kind(book|paper)、canonical slug、title、authors、year 及标识符。
一条新的都没有就返回空 candidates,并在 suggested_queries[] 给 2-3 个能拓宽该主题的检索词。
只读不写,不要碰 vault/。`
}
function topicSynthPrompt(slug, desc, ok) {
  return `mode: topic
source_name: ${desc}
topic: ${desc}
analysis_paths: ${JSON.stringify(ok.map(itemPath))}
output_path: vault/topics/${slug}/00-overview.md
reading_list_path: vault/topics/${slug}/01-resources.md
两页 frontmatter 都要 type: topic 与 title: ${desc};00-overview 用 kind: overview,
01-resources 用 kind: resources。正文引用语料一律用 [[wikilink]] 指向上面 analysis_paths 里的路径。
overwrite: true   # 主题页总是重生成:每滚一轮语料都会扩张,no-op 会让综述停在旧版本。`
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
// opts 只有 processBook 用(batchYear:批量跑里年份歧义不冒泡卡点)。author / topic 递归下来的书
// 必须带上它,否则一本书的年份存疑就能把整批停住。
async function router(kind, a, opts = {}) {
  switch (kind) {
    case 'book': return processBook(a.slug, a.meta || a, opts)
    case 'paper': return processPaper(a.slug, a.meta || a)
    case 'author': return processAuthor(a.name || a.author_name, a.meta || a)
    case 'topic': return processTopic(a.slug || a.topic_slug, a.meta || a)
    default:
      throw new Error(`process-material: 未知 kind "${kind}"`)
  }
}

const a = args || {}
if (!a.kind) throw new Error('process-material: 需要 args.kind(book|paper|author|topic)')
const result = await router(a.kind, a)
log(`process-material result: ${JSON.stringify(result)}`)
return result
