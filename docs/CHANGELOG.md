# quasi changelog

Newest first. Entries record what changed and why at the time each release shipped; names, flags, and contracts referenced in older entries may since have been removed or renamed. The active contract lives in `CLAUDE.md`, `README.md`, `docs/ARCHITECTURE.md`, and the skill / agent files.

- **0.65.2** (2026-08-05): **三处已验证的 Workflow 摩擦点回到各自 owner。**
  - Paper/Book Acquire 不再把一次写入效果同时编码为 `write_state` 与 `disposition`：前者现在是唯一 effect testimony，已核验的既有 source 可用 `source:"existing_file"` + `not_written` 完成，不会再因冗余字段矛盾停住。
  - Chapter manifest 的页码对规则收回 schema，并由 status 与 extractor 共用；同请求、ownership-safe 的旧单边 range manifest 会在既有锁和 manifest-last transaction 内完整重建，其他不安全或变更状态仍阻断。
  - `collect-material` 对 typed gate 使用唯一的 `{material_key, operation, value}` 决策 wrapper，避免扩张为 per-gate catalogue；不增加 retry、replay、隐藏状态、推断 end page 或书名特例。

- **0.65.1** (2026-08-05): **六种材料各自拥有固定 Workflow，通用 mode engine 正式退出。**
  - Author 现在通过 fresh exact status 组合 Paper/Book leaf；Topic 通过同样的 observation handshake 组合 Paper/Book/Talk，并把 Recall、稳定顺序的有界研究轮次、每项 admission checkpoint、三份产品的 owner-correct Audit/repair 收进 `workflows/topic.mjs`。两条外层 Skill 都只传 closed envelope、opaque continuation 与 typed gate，不再维护另一份业务状态机。
  - 删除无调用者的 `run-stage` source/bundle、universal catalog、dispatch wrapper，以及 single/batch/until compatibility mode。非公共 catalog 直接命名为 `scripts/schemas/operations.py`，其中 25 项事实型 `OPERATION_CATALOG` 只保存 operation 的 eligible kinds、phase、effect、Agent 与 artifact templates；不再保存阶段顺序、carry、alias、chain 或 next pointer。
  - 测试不为退休机制保留兼容博物馆：删除 88 项 mode tests 和重复 bundle harness，只迁移 chapter output testimony、Paper Acquire URL/diagnose、Stage host-stamp partition、四 terminal、Acquire branch-local fields 等仍承重的因果边界。六个生成 bundle 共用一个参数化 ABI harness；Topic 的恢复、gate、checkpoint 与去重仍由 18 条端到端因果 journey 保护。
  - 这次目标是降低变化放大与维护面，不是追求最少行数：Book 仍保留唯一真实的内部 chapter `pipeline()`；Agent 方法、OCR/Translation 的实测恢复知识、Stage StructuredOutput 校验和 exact writer ownership 均未被压扁，也没有新增 lock、reservation、cursor、retry engine 或 cleanup subsystem。
  - 测试维护同样以减少重复 runner、私有实现与任意文案耦合为目的，而非追逐删减比例：各任务 collection 为 686→686→679→678→695→695→692，其中 +17 只是既有纯函数断言参数化后可见的 pytest rows，不是新增防御场景；atomic/no-clobber、crash/unknown fencing、writer serialization、symlink/traversal、PDF/OCR layout、Translation repair/publication、identity/exact refs、schema/terminal closure、Crossref authority、secret-out-of-argv、unknown-writer/no-replay、active CLI rejection 与六条生成 entry ABI 均保留。最终 root collection 为 692，六个 Workflow bundle current 且 `tsc --noEmit` clean，fresh plugin data 下全套 692 passed、0 skipped、0 xfailed、0 xpassed、6 warnings，保护边界抽查 31 passed，mirror 与三层 diff/whitespace 检查全部通过。

- **0.65.0** (2026-08-04): **四种 leaf 材料各自成为一条完整 Workflow，Skill 不再逐阶段编排。**
  - Paper、Book、Talk、Translation 现在分别由生成的 `workflows/{paper,book,talk,translation}.mjs` 从当前磁盘事实运行到完成或 typed gate；一条调用只拥有一个逻辑材料，只有 Book 在内部用宿主 `pipeline()` 并发互不冲突的章节。每条 bundle 只带本材料的 descriptor rows 与专业依赖，不再把全库 operation catalog 塞进同一个运行入口。
  - `collect-material` 的 leaf 路径收敛为薄 driver：一次 exact pre-status、固定 kind→Workflow 映射、material-level terminal、完成后的 exact post-status；不同材料最多五条并发，同一已知 exact key 只合并字节完全相同的请求。不增加锁、canonical reservation、碰撞清洁、cursor 或第二份状态。Author 与 Topic 在这个中间版仍保留 `run-stage` 兼容编排，后续各自迁移。
  - `quasi.material.result/0.1` 只向上暴露 canonical owner、exact artifacts、typed issue/gate 与 Paper→Book route。每个 leaf `needs_input` 同时返回可直接重启的 `{route,seed,options}`：调用方按 route 做 fresh status、原样放回 seed/options，并只附本次选择。Book 连续 identity→year/structure gate 不再依赖旧 decision；Translation 的 source→configuration 路径会把已验证 source 提升到 effective options，不会重复询问或引入隐藏状态。
  - 所有 editable runtime 保持 TypeScript source-of-truth，经 `build:workflows` 生成发布 bundle；输入 parser 继续在零 Agent dispatch 前拒绝不属于该 leaf 的字段，writer unknown outcome 仍停止而不盲目重放。

- **0.64.1** (2026-08-04): **章节 slot 退回纯排序身份，不再泄漏进可见标题。**
  - 0.5x descriptor-rows 重构后，`chapter.analyse` 会在 caller 没有提供章节 label 时把内部 slot 合成为 `第${slot}章`。`01`、`00a`、`99b` 本只用于 `ch{slot}-{slug}.md` 的文件系统排序，却因此变成 frontmatter、H1 与全书概览精读章节链接里的 `第01章` / `第00a章`。
  - 本轮删除 synthetic label fallback：没有 label 时，trim 后的 manifest title 逐字流入 canonical title，`identity.chapter_label` 明确为 `null`；caller 显式提供 `chapter_label` 或 `label` 时，原有的 prefix-once 行为保持不变。Chapter frontmatter 与 H1 合同文字同步改为条件式，没有改变 artifact schema 的 payload shape。
  - `chapter.analyse` envelope probe 覆盖无 label 的 `00a`、显式 `导论` label 与已有前缀三种输入，并对整个 request 断言不含 `第00a章`，防止排序码再次成为展示文本。

- **0.64.0** (2026-08-04): **Stage receipt 0.3 把零信息 bookkeeping 从模型转交宿主，完整回执形状不变。**
  - 实测约 74% 的 StructuredOutput 重试只是在修复 writer 对 operation、stage、exact path 等 bookkeeping 字段的抄写。`quasi.stage.receipt/0.3` 的 model-facing schema 现在删去所有顶层 single-value `const`；模型完成 judgement fields 与整个 terminal 后，`run-stage` 才把这些确定值盖入返回回执。single、batch 与 chain 共用同一盖章边界，chain 的 terminal、carry 与 `complete()` 谓词都消费已经盖章的回执。
  - 分区规则只有一条机械判据：经 `annotateConstTypes` 后含单值 `const` 的顶层 property 必须 host-stamped，其余 enum、boolean、自由字符串和只有 item constraints 的数组必须由模型产生；27 条 kind/stage probe 逐条证明 model keys 与 stamp keys 不相交、并集严格等于 0.2 的完整字段集，且每个 stamp key 在旧 schema 中确为单值 const，因此不存在按语义误分类的判断面。
  - `terminal` 本轮完全不动，连 issue 内嵌的 operation const 也继续由模型产生，留待后续协议处理。Skill、chain、日志与其它下游仍看到与此前逐字段相同的完整回执；只改变字段由谁生产，不改变 terminal union、row envelope、specialist 方法或 artifact 合同。

- **0.63.0** (2026-08-04): **流水线最后一份“三处、两种语言”编码消失：状态观察与 Workflow 现在读取同一份 manifest。**
  - 0.60.0 已把 Stage 顺序收进 `scripts/schemas/pipeline.py`，0.61.0 又把 artifact path template 收进去，但 `scripts/status/status.py` 仍以 Python 字面量各自抄写顺序与路径，形成 manifest、Workflow 投影、status 三处知识。本轮让 status 直接 import 同一个 `PIPELINE`，按各 kind 当前公开的观察 Stage 过滤其顺序，并从 manifest role 展开所有 exact path；Translation 补齐 source 与 derivative wildcard 两个此前缺失的 role。今后改一个 Stage 或路径只需一处编辑。
  - 这不是把观察器改造成 rule DSL 或 generic walker：损坏 manifest 的保守解析、frontmatter 可读性、Book chapter join、Talk media/transcript 枚举、Translation derivative glob 与 scan 去歧义仍是手写且经事故淬炼的 Python 逻辑。六种代表性磁盘状态加一次 `--scan` 的 before/after 原始 JSON byte diff 为空，新增 live-manifest guard 证明改动 template 会真实改变 status evidence 与 refs。

- **0.62.0** (2026-08-04): **Workflow 层从 JSDoc 检查的 JavaScript 正式转换为 TypeScript。**
  - `scripts/workflows/` 下全部手写模块由 `.mjs` 改为 `.mts`，JSDoc 类型替换为真实的 import type、type alias、interface、参数与返回值语法；esbuild 在构建时直接编译这些源码，strict `tsc --noEmit` 继续守住由 generated declarations 提供的 kind/stage/operation literal 边界。
  - 0.61.0 为避免打断直接 import 源文件的 Python/Node 测试 harness，先用 `checkJs` 引入类型检查而保留 JavaScript 语法。本轮让生成 bundle 导出 `PIPELINE`、registry、stage protocol、resolver、context resolver 与 `run`，harness 改为 import 用户实际执行的 `workflows/run-stage.mjs`；这个约束因而消失，测试同时覆盖 shipped artifact。
  - 全部 27 条 kind/stage probe 在转换前后保持相同 registry、resolved identity、prompt 与 schema；只负责旧 JavaScript/build-script ambient types 的 `node-shims.d.ts` 随之删除，没有改变任何 Workflow 行为。

- **0.61.0** (2026-08-04): **Artifact path grammar 与 Workflow 类型边界收口到同一份 Pipeline 来源。**
  - Stage artifact path templates 现在与 kind/stage identity 和 carries 一起住在 `scripts/schemas/pipeline.py`；engine 统一展开模板与 passthrough/default base，真正的 per-operation context 判断回到 owning row，原先 217 行的集中 switch 因而删除，27 条 probe 的 registry、resolved identity、prompt 与 schema 保持逐字节相同。
  - Python exporter 从同一份 manifest 额外生成 Kind/Stage/Operation literal unions 与 Pipeline/receipt declarations；保留 `.mjs` 的整个 `scripts/workflows/` 层现在由 strict `checkJs` + `tsc --noEmit` 检查，operation、stage、carry 名或 terminal access 的拼写错误都会成为编译错误。
  - 两项 registry/row wiring 测试退出：0.60.0 的构建结构校验已经在相同错配下直接失败；生成/runtime parity、registry uniqueness、chain carry parity 与 bundle staleness 检查仍保留。

- **0.60.0** (2026-08-04): **Pipeline 的阶段顺序、operation 身份与 carries 收口为一份 Python manifest。**
  - `scripts/schemas/pipeline.py` 现在唯一拥有 kind/stage 顺序、operation/phase/effect/agent 身份，以及 receipt-to-context carries；现有 Python exporter 像投影 artifact contracts 一样把它生成到 JavaScript，row 只保留 request/receipt schema、exact envelope 与 evidence behavior。
  - `RUN_STAGE_REGISTRY` 和 chain table 都从投影后的 `PIPELINE` 派生，手写 registry literal 与 `scripts/workflows/operations/chains.mjs` 消失。构建时现在会拒绝重复 `(kind, stage)`、manifest/row 缺失或重复 join，以及读取非 required receipt field 的 carry，让错配在 build 中失败，而不是留成 runtime surprise。
  - 这是把 pipeline 在三处、两种语言里的重复编码（registry + chains、context switch、`status.py`）压成一个来源的第一步；本轮只迁移 L0 identity/order/carries，不改变任何 prompt、schema、receipt 或 dispatch behavior，后两处将在后续步骤继续收口。

- **0.59.3** (2026-08-04): **Descriptor row 的共享片段与五条 Audit 合同收口为单一实现。**
  - Row 层已经长出四份私有的同形 schema fragment，以及五份逐渐漂移的 Audit row；同一个边界因复制而分别落在 schema 与 `complete()` 的 JavaScript 复查里，导致某些 kind 会拒绝过长诊断，另一些 kind 却根本没有对应约束。本轮把真正同义的 issue、attempt、prepare-step、action payload 与 audit diagnostic 定义移入 `operations/shared.mts`，保留角色、路径与 outcome vocabulary 确实不同的 kind-specific artifact/step schema。
  - 五个 `paper|book|talk|topic|author.audit` 现在都由一个 factory 生成，原有 refs、artifact roles、request envelope、target scope 与 prompt 原样保留；完成判据统一只数 `remaining_violations` 与 `escalated`，不再让某个 kind 在 schema 之外私自追加文本复查。
  - Audit diagnostic 的 `path` / `kind` / `reason` 统一为 2048 / 200 / 4000 上限且全部非空，`mutated_paths` 统一在 schema 中限制 2048 字符。验证因此只住在一处，过去「一个 kind 用 JS enforce、另一个完全不 enforce」的漂移面被删除。

- **0.59.2** (2026-08-04): **删除无调用方的迁移脚本，并让 Agent 合同回到方法本身。**
  - 0.52 以来的仓库增长测量显示，新增行集中在真实 capability code 与 workflow contract machinery；维护痛点却集中在同一概念同时寄居多处。本轮据此坚持净删除，不压缩仍承重的方法与恢复知识。
  - `scripts/migrations/` 的两支脚本经全仓引用审计确认没有调用方，连同缓存目录整体删除，不再为可从 git 历史恢复的旧迁移承担活跃维护面。仍由 `scripts/core/core.py` 读取的 `QUA_PROJECT_ROOT` 只保留为 legacy compatibility override。
  - Agent prose 删除 row 已经闭合约束的 receipt terminal、payload 与 echo 复述，只保留专业方法、停止判断和本地恢复；receipt semantics 现在只在 descriptor row schema 中定义。0.55.0 前的 graph vocabulary 与 sibling-stage narration 同时退出活跃合同面，后续控制回到 driving skill 与 exact request context。

- **0.59.1** (2026-08-04): **全量审计清掉测试残渣与一条不可达的 Agent 路径。**
  - 全套测试审计显示，现有测试绝大多数确实守住运行合同与 institutional memory；最痛的 skill prose photographs 已在 0.58.5 移除。本轮继续删除审计确认的七项 construction-pinned、mechanism-duplicate 或 tautological 测试，只留下权威层的结构与行为保证，不再让 UI 标签、shell 源码行或内部常量冒充公共合同。
  - `localisation-agent` 没有 descriptor row、`RUN_STAGE_REGISTRY` entry 或 Skill dispatch path，中文版本匹配早已由确定性的 `quasi-helpers localise scan|write` 完成。因此删除这个不可达 Agent，清理现行文档/模块上下文中的消费者叙述，并把名字加入 dead-name quarantine，防止无调用方的模型边界复活。
  - 同时移除 `scripts/workflows/` 下四个已经清空的旧 materials / collections / derivatives / research scaffolding 目录；这些目录不承载生成器、descriptor row 或运行时状态。

- **0.59.0** (2026-08-04): **Paper 的机械前进收进固定链，writer 在入口重证 exact refs。**
  - `run-stage` 新增 `until` 链模式；首条且唯一的链是 Paper `Acquire → Prepare → Analyse → Audit`。它故意从 Acquire 而不是 Search 开始：Search receipt 之后仍有 canonical slug、`local_owner` admission 与 same-identity coalescing，这些 identity 判断属于 driving skill，不能伪装成机械阶段推进。链不分支、不重试、不 join，也不跨 invocation 保存状态。
  - Descriptor row 的 `complete()` 跨字段谓词终于有了运行时归属。链在每个 `terminal.complete` 后调用 owning row predicate；schema 合法却谎称完成的 receipt 以 `incoherent_complete` 确定性停住，不再只靠测试发现。构建器同时校验 chain sequence 对 registry、carry reads 对 receipt required fields 的机械一致性。
  - Workflow 脚本不能读磁盘，所以跨阶段 context 只从已验证 receipt 传递：`paper.prepare.selected_input` 直接成为后续 `paper.analyse.input`。`scripts/workflows/operations/chains.mjs` 只拥有固定顺序和这类声明式 carries，不重新发明 material state。
  - 十一个 writer Agent 在第一次写入前重证 envelope 的 exact refs：所有具名 input 存在且可读，output state 符合 request，存在 `output_observation` 时以它为权威。Mismatch 不写入而返回本 operation 的 typed `blocked`；这项分散式 precondition check 让 unknown outcome 后的 status-first resume 安全——旧 writer 若已落盘，新 invocation 会在入口停住，而不是盲目覆盖或搜索替代路径。
  - `collect-material` 的 Paper 路由从逐 Stage 机械转发收敛为 Search/identity 后一次 `stage:"acquire",until:"audit"`；主线程只消费 chain stop reason、展示 typed gate，并继续拥有 Audit→Analyse repair 与 status-first 断点续跑。Book、Talk、Author 和 Search 的调用形状不变。

- **0.58.5** (2026-08-04): **Orchestration 测试从技能文案快照收回为跨文件合同校验。**
  - `tests/test_skill_orchestration.py` 曾钉住具体中文句子、规则名和工作流叙述；这些断言守住的不是运行合同，而是某一版 skill prose，导致每次简化 skill 都要同步缴纳测试维护税。本轮删除四项 collect/research prose photograph 与三句 owner 文案钉子，保留运行地标、frontmatter routing、container route 和 dead-name quarantine 等真实边界。
  - 新测试从权威来源派生一致性：skill 中的 kind/stage token 必须解析到 `RUN_STAGE_REGISTRY`，Book gate vocabulary 必须同时存在于 row 与 driving skill，共享 receipt 版本必须在 stage module 与 maintainer guide 同步；凡调用 `Workflow()` 的 skill 只能走公开的 `workflows/run-stage.mjs` 并通过 `quasi-status` 观察磁盘，且所有 skill 都不得调用 agent-owned CLI（`quasi-search` / `quasi-download` / `quasi-extract` / `quasi-transcribe` / `quasi-translate` / `quasi-audit`）。这些检查继续守住名字、阶段、版本和 ownership boundary，同时让 prose 自由改写。

- **0.58.4** (2026-08-04): **Workflow 顶部两行让位给运行时叙述行。**
  - `meta.name` / `meta.description` 都是编译期字面量，`slug` 只有运行时才知道，永远进不了这两个槽；能进的只有 stage，而 0.58.3 的 `log()` 叙述行已经在说 stage 了。原 description（"Runs one schema-enforced quasi stage and returns its receipt verbatim"）既重复又冗长，还在跟真正有信息量的那行抢注意力。改为 `Quasi` / `Pipeline`，三行各司其职：是谁 / 是什么 / 正在干什么（`Analyse × 30 — allison-nightwork-1994`）。
  - 考虑过 description 留空，否决：宿主要求 `name` 与 `description` 均必填，空串是否算"有"无法在不真跑一次 workflow 的前提下确认，且该串也是非 bypassPermissions 用户看到的权限对话框那行，空着显示为空行。也考虑过按 stage 拆七个 bundle 让名字带上 stage，同样否决：那只是把叙述行已有的词搬到第一行，是重复而非新信息，代价是七倍构建。`workflowMeta` 是纯展示，无测试或调用路径依赖（bundle 文件名来自 `build-workflows.mjs` 的 `WORKFLOWS` 常量，skill 用显式 scriptPath 调用）。

- **0.58.3** (2026-08-03): **Workflow 显示名改回插件本名；`run-stage` 支持同阶段扇出，30 章的书从 30 次调用变成 1 次。**
  - UI 顶行一直显示 `run-stage`——那是内部调度器的名字，用户看不出正在跑的是哪个插件。`workflowMeta.name` 改为 `quasi`。文件名来自 `scripts/build-workflows.mjs` 的 `WORKFLOWS` 常量而非 meta，故路径与既有引用不变；`description` 本轮不动。
  - 一本 30 章的书此前要发 30 次 `Workflow()`：UI 刷 30 行、主线程被 30 轮工具往返撑满，而这 30 个 specialist 之间本来就没有顺序依赖。`run-stage` 新增可选 `args.units`（1–64 项，每项 `{slug?,label?,context?}`），一次调用解析**同一条** descriptor row，为每个单元各组装 prompt/schema、各派一个 specialist，返回 `quasi.run-stage.batch/0.1` 信封，`receipts` 与输入同下标同顺序、逐字不改。`units` 缺席时行为与此前逐字节等价。
  - 扇出必须对任何 row 都安全，因此护栏是通用的而不是一张可批量 operation 白名单：批内两项序列化 prompt 完全相同即意味着两个 writer 写同一个 exact output，整批以 `run-stage.duplicate_unit` 拒绝且一个 agent 都不派（例如误把 `book.prepare` 当可批量阶段时，30 项 prompt 会完全一样）。单元级 context 非法只让该下标落成自己的 `run-stage.invalid_context` 信封，不牵连同批其它单元。`run-stage` 仍不合并、不汇总、不重试、不 join。
  - 生成器一直把 `parallel` 和 `log` 传进 `run()`，之前只解构了 `agent`。本轮接上这两个现成钩子：派发走 `parallel`（宿主控并发），并在派发前发一行叙述（单件 `Stage — slug`、批量 `Stage × N — slug`）。两者都是可选的，测试 harness 不传时退化为 `Promise.all` 且跳过叙述。
  - `collect-material` 的 Book Analyse 改为：一次 `quasi-status` 观察定出每章的 `output_exists`，再一次 `run-stage` 带上全部章节。逐项消费规则不变（0.58.2 的写入分支权威关系照旧），某项为 `null` 或 error 信封仍是 unknown outcome，按 WRITER-AMBIGUITY RULE 重新观察磁盘，不得盲目重派。「同时在飞至多五个 run-stage」是针对不同材料的约束，未改动。改动由 Codex worker 按配方执行，新增 5 项批量测试，全量 439 测试过。

- **0.58.2** (2026-08-03): **章节 Analyse 由 caller 的磁盘观察定死写入分支；文集专属作品在 Search 得到一条诚实出口。**
  - 事故一：五本书卡在 Analyse 中段。`chapter.analyse` 的 create 分支同时接受 `create/written` 与 `reconciled/not_written`，于是 worker 可以在产物根本不存在时返回 `reconciled/not_written`——receipt 内部自洽、host 校验通过，主线程却在下一次 status 观察里看不到文件。本轮把 caller 刚做完的磁盘观察作为权威传进 envelope（`output_observation{path,exists,authority:"caller"}`），并按它把 row 的 complete payload 收紧成单值 const：`exists:false` 只允许 `create/written`，`exists:true` 只允许 `reconciled/not_written`。analyse-agent 合同同步声明这条权威关系；`collect-material` 每次 dispatch 前须带 `output_exists`。判断权仍在磁盘，不在 worker 的自述。
  - 事故二：只存在于文集里的作品（如 Chisholm "Freedom and Action"，收于 Lehrer 编 *Freedom and Determinism* 1966）没有独立出版形态，metadata-agent 只能把容器题名硬塞进 `journal`、DOI 填 null，凑出一个下游必然获取失败的期刊身份，用户全程没有选择机会。`material.search` 的 `conflicts` 枚举本就有 `publication_type`，缺的只是使用它的方法词汇。本轮不动 schema（该 receipt 序列化已 4898 字节，超 auto 模式 4096 分类上限，加字段只会更糟），只补方法与路由：agent 在证据显示 container-only 时返回 `needs_input`，`issue.user_question` 给出可执行的容器方案（题名/主编/出版社/年份/ISBN + 目标章节）；skill 收到用户改收容器的回答后新建 `kind:"book"` 材料走完整 loop，原 Paper 条目以 redirected 结束而非 failed。判据写死为「该条目是否作为可独立检索取得的出版物流通」，因此学会年刊单篇（Strawson "Freedom and Resentment", PBA 48）与独立讲座小册（Chisholm "Human Freedom and the Self", Lindley Lecture）仍按 Paper 处理，不被误判。
  - 附带：`translate-agent` 的 `model` 由 `inherit` 改为 `sonnet`，与其余 specialist 一致，不再随主线程模型漂移。
  - 两项主改动由不同 Codex worker 按配方执行，共享同一工作树；SKILL.md 同时承载两者，故合并为一个版本发布。全量 433 测试过，`check:workflows` bundle 同步。

- **0.58.1** (2026-08-03): **AA 镜像发现以维基百科为主路径：内容校验探活 + last-good 缓存，不再每次从头探测。**
  - 实测事故：静态镜像表首位的 `annas-archive.pk` 死了一段时间，每次调用先在它身上烧最多 20 秒超时；而已有的维基百科 infobox 提取路径被埋成"三个静态镜像全部不可达才触发"的最后兜底，`.gd` 活着就永远轮不到。探活标准只有"状态码 <400"，停靠页 200 也会被当活镜像选中。
  - 重排为：last-good 镜像先试（缓存在 `aa-mirrors.json`，命中即用，消掉每次的全表探测）→ 维基列表（缓存 TTL 90 天改 7 天，官方域名的权威来源）→ 静态种子表（去 `.pk` 补 `.li`，降级为维基不可用时的兜底）。探活改为单次 GET 且正文须含 Anna's Archive 特征串，堵住停靠页假阳性。发布当天 `.pk` 又活了回来并经维基路径被正确选中——镜像抖动正是这套设计要对付的场景。修改由 Codex worker 按配方执行，新增停靠页拒绝/last-good 优先/维基先于静态/TTL 四类单元测试。

- **0.58.0** (2026-08-01): **Workflow 层收口为唯一 `run-stage` descriptor 路径：删除漂移的 member relay，统一 request envelope tag，并移除零调用 standalone API。**
  - `member.admission-probe` 已与 Skill 现状漂移：`collect-material` 和 `research-topic` 都由主线程直接运行 `quasi-status --identity` 并消费磁盘观察，relay 只剩 row、registry/context 和旧测试自我引用，没有运行调用方。因此以 Skill 现行合同为准删掉整条 member 链，并把死名加入不得复活哨兵；Audit 仍只有当次 receipt 证明，未伪造持久状态。
  - descriptor rows 实测并存 generic、per-stage 和 per-operation 三族 request tag，但旧 per-operation 字面量在 `agents/` 和 `tests/` 零消费者，`steer-agent` / `webcard-agent` 要求的原本就是 `quasi.stage.request/0.2`。本轮就地替换 16 个特化 tag，不加 factory 或注入层；新增的 parity 测试遍历全部已注册 row 的 request envelope，防止再次分叉。
  - 逐个 `rg` 证明 39 个 row 尾 standalone named export 除自身定义与生成物外没有命中，它们只会误示 `run-stage` 之外尚有第二入口，故全部删除并清理失效 import；连同 member row 的 3 个 export，本次共删 42 个 named export。`normalizeLanguage` 仍被 `run-stage-context.mjs` 实际 import，各 `*OperationRows` 仍是唯一注册表面，两者均保留。

- **0.57.9** (2026-08-01): **Talk 分节摘要补入经转写核对的可点击起止时间，同时保留文末详尽时间索引。**
  - 新产物此前只有文末 `时间脉络` 的起始点，阅读摘要时看不到每个内容小节覆盖的录制范围；若直接把时间轴改成区间，又会失去章节内部的重要转折索引。
  - 最小修复只改既有 producer 合同：live Talk 的每个 H3 下首行固定为「时间：`[mm:ss]`–`[mm:ss]`」，两个端点逐项对照同 generation 的 transcript evidence；文末 `时间脉络` 继续使用更细粒度的反引号时间点，不得由分节区间替代。未新增 H2、状态、receipt、helper 或 skill 路由；重建 workflow 投影并用 schema / prompt 回归测试钉住合同。

- **0.57.8** (2026-08-01): **根目录 `core/` 迁入 `scripts/core/`，插件根只剩宿主要加载的组件目录。**
  - 起因：根目录的 `core/` 与 `skills/`、`workflows/`、`agents/`、`bin/` 混排，看起来像宿主组件，实际是纯 Python 管道，已被误判为死代码而误删过一次。迁移后 L0 边界不变，仍靠导入方向执行（`scripts/core/` 不得 import 兄弟域或 `scripts/schemas/`），目录位置不再承担这个语义。
  - 改动面：`git mv` 三文件；`plugin_root()` 无锚分支 `parents[1]`→`parents[2]`；10 个脚本的 `from core import` 统一改 `from scripts.core import`（全部已插 PLUGIN_ROOT 进 sys.path，`scripts.` 命名空间导入既有先例，不新增路径黑客）；`test_core.py` 自身 `parents[2]`→`parents[3]`；CLAUDE.md（=AGENTS.md）与 ARCHITECTURE.md 的三处路径提法同步。全量 510 测试过，`vault resolve`/`audit` shim 冒烟过。修改由 Codex worker 按配方执行。

- **0.57.7** (2026-08-01): **指令文档重构：CLAUDE.md（=AGENTS.md）降为纯维护合同，实测技术记忆整体迁入 `docs/PDF_PIPELINE.md`，README 重写为用户向。**
  - 0.57.6 的瘦身把 OCR/翻译七大段实测长文原地保留在 CLAUDE.md；本轮按「细节归 docs」原则把它们逐字迁出（byte 级校验通过），新家是 `docs/PDF_PIPELINE.md`，CLAUDE.md 原地只留「Extraction and translation invariants」不变量清单加指针，262 行收敛到 133 行。userConfig 映射表与 Keychain 流程段迁入 `docs/ARCHITECTURE.md`，该文件同时补齐 CLI 表漏项（`quasi-status`、`quasi-transcribe`、`vault resolve`）、新增 per-agent 写权属清单与 collect-material 单本/批量、topic 产物的路由细节；维护文档清单加入 PDF_PIPELINE。CLAUDE.md 不再记载「Current version」——版本唯一事实源是 `plugin.json`，少一处同步负担。
  - README 从维护者摘要重写为合格的用户向 README：是什么、安装（marketplace 命令）、配置、可选系统依赖、数据布局；构建命令、agent 依赖表、CLI 清单等维护者内容全部让位给 docs/ 指针。修改由 Codex worker 按配方执行。验收期间发现工作树中 `core/` 三文件被未知来源删除（worker 报告其开工前已存在，非其所为），已从 HEAD 恢复并以全量 510 测试确认仓库健康。

- **0.57.6** (2026-08-01): **CLAUDE.md（=AGENTS.md）与 README 瘦身：去结构性重复与失实内容，技术记忆原样保留。**
  - CLAUDE.md：生成物纪律三处重复合并为一处；receipt 纪律在 Stage UI / Stage Unit model / host-validation 三段间的重复删两处；Skill writing schema 节压缩；Verification 节并入 Change checklist。OCR、翻译、--layout、EZProxy/keychain、metadata 合并这些带测量数据的长段一字未动——它们是防止重犯错误的证据，"清理"不等于压缩它们。
  - README：删 `deprecated/skills/` 失实行（目录已不存在）；删与 CLAUDE.md 重复的宿主适配器行；"Artifact Schema 维护边界"整节压成一段指针；凭据表删 `google_scholar_proxy_url`（不在 `plugin.json#userConfig`，按 CLAUDE.md 自己的规则不得记载）、补 `soniox_api_key`；文库结构树补上 talks/topics/processing。修改由 Codex worker 按配方执行。

- **0.57.5** (2026-08-01): **docs 瘦身：删除九项 0.50–0.55 战役期的陈年设计文档，维护面收敛到四份现行文件。**
  - 删除 process-material-design、workflow-universe-rfc、workflow-modularization-master、operation-layer-design、material-loop-protocol、topic-steering-design、DOUBAN_LOCALISATION_HANDOFF 以及 reviews/、superpowers/ 两个目录（约 2100 行）——全部已落地或过时，git 历史完整保留，不留向下兼容。现行维护文档只剩 CLAUDE.md（=AGENTS.md）、docs/ARCHITECTURE.md、docs/SKILL_ORCHESTRATION.md、docs/GRAPH_COLLABORATION.md，外加 CHANGELOG 作历史。ARCHITECTURE 文末的设计文档索引段替换为一句指向 git 历史的说明；`scripts/schemas/topic.py` docstring 里最后一处失效引用一并清除。
  - README 的 CLI 块与 CLAUDE.md 的 Active CLI surface 对齐（补 `quasi-status` 两行与 `quasi-helpers vault resolve`）。CLAUDE.md 本体经核查全部仍承重（QUA_PROJECT_ROOT 仍被 core 使用；OCR/翻译长段是防止重犯的新鲜教训），本轮不动。首个 worker 因配方自相矛盾（"零残留"与"schemas 不许动"冲突于 topic.py 的一行注释）如实报 failed 而不越界，配方错误由后续微任务修正——两次修改均由 Codex worker 执行。

- **0.57.4** (2026-08-01): **talk.md 时间脉络恢复反引号时间戳的字面模板，时间轴重新可点击。**
  - 实测回归：新流程产出的 talk 时间脉络是裸 `[00:11]`，旧 talk 全是 `` `[00:00]` `` 反引号包裹——用户查看器的播放定位靠反引号代码格式识别，裸格式点不了。根因在 skill→schema 迁移：老 `<talk_mode>`（git 8ebe5b0）给的是转义反引号的字面行模板，迁进 `body.py` 后 description 只剩"带起始 `[mm:ss]`"，弱模型把反引号读成描述自身的排版而不是输出要求。transcript、silent 模板、schema 测试样例始终是反引号方言，唯独这一处合同投影丢了。
  - 修复：description 改为字面行模板「- `[mm:ss]` 主题 — 概括」并明说反引号必须按字面保留、超一小时用 `[h:mm:ss]`；重建 workflows 生成物；新增 registry 测试钉住模板不再在迁移中丢失。修改由 Codex worker 按配方执行。

- **0.57.3** (2026-08-01): **`quasi-academic` 输出风格随插件启用强制生效（`force-for-plugin: true`）。**
  - 普通插件样式永远不会自动激活，只能在 `/config` 里手选（`/output-style` 命令已在 Claude Code v2.1.91 移除）；实测装了 0.57.1 后样式一直未启用。加 `force-for-plugin` 后，quasi 启用期间样式自动应用并覆盖用户的 `outputStyle` 设置；若多个已启用插件都强制样式，先加载者生效。

- **0.57.2** (2026-08-01): **润色 `quasi-academic` 输出风格的中文表达约束与 Markdown 结构。**
  - 明确主会话使用自然流畅的中文和中文引号，保留结论先行、证据纪律、语言跟随与交付物例外；同时补齐标题与列表之间的空行，避免不同 Markdown 渲染器把段落结构粘连。

- **0.57.1** (2026-08-01): **extract-agent 合同补 Book Prepare 的 reuse 资格判据，坏的旧章节代不能再靠"文件都在"过关。**
  - 实测事故：Sen 的旧章节 generation 是 0.56.4 之前的字母序垃圾（标题全是内部资源标识符、版权页/目录/宣传页被当章节、Preface 排在正文后），重派 book.prepare 时 specialist 看到"文件存在、可读、fingerprint 匹配"就返回 `complete/reused`，新的 spine 提取器从未被触发。授权其实早已齐备——envelope 的 objective 写着 semantically verify，读 manifest/章节文本、fingerprint 门控换代都在能力表——缺的是判据词汇：合同点名的缺陷全是正文内容向（串章、截断、乱码、页眉页脚），清单语义向的缺陷没有名字，钉在 sonnet 上的 specialist 便放行了。与 0.55.1 同一课：对弱模型要把判据写实，不能指望它从一个动词短语里推出全部标准。
  - 修复只在 `agents/extract-agent.md`：复用与新建同一个证明标准（必须实际读 manifest 和代表性章节文本），并列出三类取消复用资格的观察——标题是内部资源名/文件名 stem、章节集合混入非阅读材料（封面/书名页/版权/目录/宣传/作者介绍/他作列表/插图清单）、阅读顺序破损。修改由 Codex worker 按配方执行。

- **0.57.0** (2026-08-01): **新增 `output-styles/quasi-academic.md` 学术对话输出风格组件。**
  - 插件根级 `output-styles/` 是 Claude Code 会加载的组件目录，CLAUDE.md/AGENTS.md 的组件清单同步补上这一项。
  - 该风格只约束主会话的对话表达（结论先行、证据可定位、砍冗余不砍内容、证据与推断分开），不影响 skills/agents/schemas 规定的产物合同；交付物的长度与结构仍跟随任务要求。组件由并行会话调研并写成，本次随版本收编发布。

- **0.56.4** (2026-08-01): **`quasi-extract epub` 以 OPF spine 为章节清单权威，Random House 形状的 EPUB 不再产出乱序垃圾 manifest。**
  - 实测事故（Sen《Development as Freedom》2000 电子版）：NCX 探测只认字面量 `toc.ncx` 四个候选路径，而该书的 NCX 叫 `Sen_..._epub_ncx_r1.ncx` 且放在 zip 根目录——探测落空后掉进"HTML 文件名字母序 + stem 当标题"的兜底，Preface 排到 slot 22、两份 Notes 倒置、宣传页混入，标题全是内部文件标识符；继续 Analyse 会把错误结构固化进 vault。
  - 修复按 EPUB 标准走发现链：`META-INF/container.xml` → OPF → spine itemref 顺序为权威（`linear="no"` 跳过），NCX 只供标签（经 media-type 或 `.ncx` 后缀定位；属性逐个抓取、不依赖顺序——该书 OPF 的 href 写在 id 前，组合正则在这里已实际踩过坑）。无 NCX 标签的 spine 条目取首个 h1–h4 当标题；标签、标题两者皆无的按 furniture 跳过（挡住该书无题宣传页 col1）。选 spine 而非纯 NCX 是因为实测 `nts1`（第 11–12 章注释，约 3400 词）在 spine 里却不在 navMap——纯 NCX 修复会静默丢内容。
  - 降级阶梯保留：无 OPF → NCX 顺序路径（探测放宽为任意 `*.ncx` 成员）；无 NCX → 字母序兜底，既有六个测试全部原样通过。`SKIP_TITLES_EXACT` 补 `other books by this author`、`illustrations` 两个实测漏网词条。Sen 冒烟结果为 16 条正确阅读序（Preface → Introduction → 12 章 → 两份 Notes）。修改由 Codex worker 按配方执行；配方里"期望 17 条"是主进程的算术错误，worker 以 26 条 spine − 10 条排除 = 16 的证据如实交付而未弱化 skip 规则。

- **0.56.3** (2026-08-01): **Kagi 恢复阶段发现的 URL 补走 EZProxy 通道，付费墙落地页不再只做裸抓。**
  - `download_paper` Phase 2 里由 Kagi 按题名发现的 URL 此前只尝试无代理直抓，而同一阶段发现的 DOI 却有 EZProxy 重试——不对称是疏漏。Kagi 对付费墙论文搜出的恰恰是只有机构代理才能取到的落地页（JSTOR/Springer/OUP 一类），裸抓必然 403，等于恢复阶段对最需要它的宿主类失效。现在幸存的发现 URL 汇总走一次步骤 5b 同款的 `_try_ezproxy_urls_with_refresh`，身份校验参数照传，0.56.1 的强身份门继续挡住 Kagi 词汇重叠带进的同作者姊妹论文。
  - 起因是一次 DOI-only 请求的复盘（`10.5840/philtopics19962427` 解析到 PDCNet 被 Cloudflare 拦截、全 cascade 正确耗尽后报 failed）：实测确认该论文属"无自动发现路径"类——JSTOR 页对 Kagi 不可见、OpenAlex locations 只有 doi.org、PhilPapers 有反爬，这类的真实出路仍是调用方补落地页 URL，本次不为它加投机通道；修的是恢复阶段对可发现宿主的真实缺口。修改由 Codex worker 按配方执行（净 +30 行），新增 Phase 2 代理路由单元测试。

- **0.56.2** (2026-08-01): **瘦身 0.56.1 的身份门：移除 `--year` 全链路贯穿。**
  - 年份不冲突检查对实际事故零贡献（错误论文的正文里通常也印着目标年份，真正拒绝它的是题名整句匹配），却在 CLI 参数、acquire envelope、验证器三层各加了一块合同面——它源自照单实现一份外部诊断的建议契约，而非从事故推出的最小修复。身份门保持两条强证据：嵌入 DOI 精确等于请求 DOI，或整句归一化题名 + 首作者在场。EXISTS 复验、`10.2307/` JSTOR 推导与 disposition/source 的 complete-terminal 收紧不变。
  - 本次修改由 Codex worker 按配方执行，主进程只做侦察、验收（diff 逐项核对 + 内容扫描 + 全套 396 测试复跑）与发布，是"主进程不自己动手改"工作模式的第一次完整走通。

- **0.56.1** (2026-08-01): **`paper fetch` 的成功条件改为强身份证明，词汇重叠不再等于身份。**
  - 实测事故：对精确 DOI `10.5840/philtopics19962427`（Clarke 1996）请求，cascade 把 Wong 2021（`10.2478/disp-2021-0008`）当 `status: ok` 返回——同子领域论文含有全部题名关键词并引用了目标作者，旧的关键词计数验证正好被这种形状骗过。新契约：嵌入文本的规范化 DOI 精确等于请求 DOI 即通过；否则要求整句归一化题名连续命中 + 首作者在场 + 年份不冲突（新增 `--year`，envelope 带 `expected_year`）。DOI-only 请求（无题名/作者）保持旧信任，避免误拒没有印 DOI 的老扫描件。
  - 遗留临时文件不再免检：`EXISTS` 短路分支现在先过同一身份门，不符即删并继续 cascade——此前一次错误下载会永久卡住该 slug 的重试。JSTOR 自有前缀 `10.2307/` 的 DOI 直接推导 stable URL hint，DOI-only 请求也能进 0.56.0 的 EZProxy 主机改写通路（实测经代理拿到正确的 Clarke 1996 全文）。
  - Receipt 一致性：`disposition`/`source` 描述的是一次被接受的写入，移入 complete terminal 分支内部（枚举收紧为非空）；failed/blocked/needs_input 分支是闭合对象，形状上不可能再回显 `disposition:"created"` 这类误导组合。新增验证契约 10 个单元测试与 paper/book acquire 的 terminal 形状钉子。

- **0.56.0** (2026-08-01): **EZProxy 先走改写主机名、URL-only 请求也能进代理，JSTOR stable URL 不再必然 403。**
  - 真实故障是两处叠加，而不是权限问题：其一，`download_paper` 的 EZProxy 那一步写在 `if doi:` 里，所以只给 URL 的请求从来没有进过代理，机构会话再有效也只发出裸的公网请求；其二，代理入口只构造 `login?url=` 形式，而 CookieCloud 拉到的 25 条 cookie 里没有一条落在 `login.` 主机上——会话是发在被改写的主机上的（`www-jstor-org.eux.idm.oclc.org` 上 7 条），于是 login 形式必然被判成 `EZProxyCookieExpired`。
  - `_ezproxy_request_urls` 因此把改写主机名的形式排在 `login?url=` 之前；后缀优先从用户自己 cookie 记录里带短横线首标签的域名推断（观察到的事实），推不出才退回 login 主机去掉 `login`/`ezproxy`/`proxy` 服务标签。已经在代理域上的 URL 原样请求，不二次包裹。改写形式对 Cell、ScienceDirect 等既有 publisher 同样生效。
  - JSTOR 适配本身只是派生 PDF URL：`/stable/{id}` → `/stable/pdf/{id}.pdf?acceptTC=1`，序号与 DOI 两种 stable id 都认，并保留调用方的 netloc 好让已代理的 hint 保持代理。`acceptTC=1` 是必需的——缺了它 JSTOR 在 PDF 路径上回的是条款页 HTML，读起来和付费墙一模一样。
  - 同时把 URL→PDF 派生收成一个入口 `_pdf_urls_from_article_url`，hint 收集、EZProxy landing、Kagi 恢复三处共用。此前每处各自手抄一份 publisher 名单，所以 Cell 三处齐全、ScienceDirect 只有两处、新加的平台默认只落一处——JSTOR 若照旧例加也会是同一个坑。
  - 主机匹配同样只留一个：`_unproxy_host` 先把 EZProxy 的单标签短横线编码解回真实主机（`pubsonline-informs-org.eux.idm.oclc.org` → `pubsonline.informs.org`），`_is_publisher_host` 再按域名（含子域）匹配。`PUBLISHER_PDF_PATTERNS` 因此改成域名键。原表里并存的 `pubsonline.informs` 与 `pubsonline-informs` 两行正是手工补代理拼写的痕迹，而同表的 `nature.com`、`academic.oup`、`mit.edu` 没补——它们在代理路径上从来没有匹配上过，这次一并修好。
  - 新增 `_publisher_pdf_urls_from_article_url`：URL 自己路径里就带 DOI 的 publisher（`tandfonline.com/doi/abs/10.1080/x` 之类）复用同一张表派生 PDF，不必先做一次 DOI 解析。
  - 实测：`paper fetch --url https://www.jstor.org/stable/43154235` 此前落到 Kagi 恢复阶段并"成功"下载了一份无关的 JSTOR 使用指南（4.1MB），现在经改写主机取回正确的 Clarke 1996《Agent Causation and Event Causation》3.1MB 原文。tandfonline 的 URL-only 请求确认能派生出两条 PDF hint 并经改写主机进入代理，只是该站另外回 Cloudflare challenge（已被正确识别，属既有问题）。

- **0.56.0** (2026-08-01): **新增只读 `quasi-download paper diagnose`，把拒绝访问的 HTTP 证据与下载 cascade 分离。**
  - JSTOR stable URL 的 native 请求曾只留下 `FAIL HTTP Error 403`，无法区分 access denial、登录页和 Cloudflare challenge；新命令只观察一条 direct 或显式 EZProxy 路径，返回脱敏的状态、响应类别与路由事实。
  - Diagnose 不写临时或 canonical 文件、不派生 PDF URL、不运行 OA/Kagi/代理下载 cascade，也不输出 cookie、Authorization、原始响应体或 URL query；它是 failed receipt 的证据工具，不是付费墙规避能力。

- **0.55.1** (2026-08-01): **给 receipt schema 里所有 exact-echo `const` 补显式 `type` 注解，弱模型宿主不再把非字符串 echo 串化到撞死重试上限。**
  - 实测故障：一次 paper Audit 连续 5 次 StructuredOutput 校验失败（重试上限），worker 模型是 glm-5.2，它把 `pass: 1` 发成 `"1"`、`artifact_roles: ["canonical"]` 发成字符串化数组——schema 里裸 `const`（无 `type`）会让弱模型默认按字符串输出，而同一收据里带 `type: "integer"` 的顶层 `attempt: 1` 是对的。Claude worker 在相同 row 上从未失败，说明这是 type 提示缺失、不是合同错误。
  - 修复只落在唯一咽喉 `stage.mts::stageReceiptSchema`：`annotateConstTypes` 递归给每个缺 `type` 的 `const` 节点按值推断补注解，不改 `const`/`enum`/`default`/`examples` 的字面值。exact-echo 纪律原样保留——echo 仍是把 receipt 绑到 exact refs 的身份证明，只是现在弱模型也能满足它。
  - 新增全 registry 扫描测试：所有注册 kind/stage row 生成的 schema 里不允许出现裸 `const`，并单独钉住 `paper.audit` 的 `pass`/`artifact_roles` 注解形状。

- **0.55.0** (2026-08-01): **运行架构倒置为 Skill 驱动，删除已经没有职责的自运行 Graph driver。**
  - 真实 clean-project E2E 已证明 `collect-material` 能以 `quasi-status` 磁盘观察和五次单阶段 `run-stage` 调用完成 Search → Acquire → Prepare → Analyse → Audit，全程没有触发旧 driver；这项 gate 通过后才删除大图 bundle、material/collection/research loops、router/join/scheduler/classifier machinery 及其 characterization tests，不留 alias。
  - 运行时四层现在固定为 Skill driver → descriptor rows + `run-stage` → specialist Agents → transactional `quasi-*` CLIs。Skill 负责 identity coalescing、阶段选择、并发、gate 与 resume；每个 Workflow 只解析一行、调用一个 Agent、原样返回 `quasi.stage.receipt/0.2`。协议测试收敛到全 registry row resolution、schema generation 与四 terminal shape，capability/status/skill guards 保持原样。
  - E2E 同时校正文档边界：Workflow specialist 的 `CLAUDE_PROJECT_DIR` 可能为空，故 cwd 是 project root、非空 env 才优先；Analyse 完成后由 Audit 做机械 normalization 是设计内行为；headless `--output-format json` stdout 只有最终 envelope，完整 driver 证据需查 session JSONL 与 per-Workflow sidecars。

- **0.54.0** (2026-08-01): **Topic 合入共享 material machinery，不再维护一座会继续漂移的第二套 Graph。**
  - Author discovery family、Topic steer 与 webcard 全部成为 descriptor rows；rolling Topic loop 由 `research/topic-recall.mjs` 唯一拥有的 bounded `maxRounds` graph 取代。Webcard fan-out 与材料 fan-out 并行，子材料复用共享 dispatch、`quasi-status --identity` disk admission 和 canonical `topic.audit`，所以 Topic 的专业步骤和其它 Operation 经过同一个 terminal gate。
  - 随着最后一个 pre-stage island 搬完，compatibility backstop、`guard` 和 `retryNull` 一并删除：readonly 的有限恢复和 writer 的禁止 replay 只由共享 runtime contract 表达，不再留 Topic 特例。
  - Topic dossier pages 明确作为产品决策退役，只保留 overview、resources 和可由用户编辑的 outline；公共 Skill 从 `precise-topic` 改名为 `research-topic`，且不提供 legacy alias，让用户路由与唯一 Topic owner 对齐。

- **0.53.0** (2026-08-01): **Constitution round：Graph 不再为每个 operation 和 material kind 各自成为一份代码实体。**
  - 一个 `defineOperation` factory 解释 Paper、Book、Talk、Translation 的 descriptor rows；一个 182 行 material interpreter 执行各 kind 的 declarative table。共享调用、terminal routing、fan-out、repair 与 coalescing 语义只写一次，新增阶段改数据而不是复制控制流。
  - Claude 成为唯一运行宿主，Pi/Codex adapters 与 modern runtime schema backstop 已删除；Stage receipt 只经过 contract-relative terminal gate，未迁移的 author discovery 与 rolling Topic 明确留在 legacy island。Graph doctrine tests 从约 23.5k 行裁到 14.8k 行，守协议与边界而不固化内部实现。
  - Collection join 改由 `member.admission-probe` 调用 `quasi-status --identity`，以磁盘 testimony 重证 child identity 和 canonical artifacts，不再相信 receipt artifact claims。Audit 尚无 durable disk signal，因此 clean-audit proof 暂时保留 receipt-based；下一轮才合并 Topic、重命名 `precise-topic` 并退役 legacy island。

- **0.52.28** (2026-08-01): **统一 material/document 的 Stage terminal，收紧 admission 而不把判断塞回 Graph。**
  - Analyse、Synthesise 与 Audit producer 现在和 Acquire/Prepare 一样交付 `quasi.stage.receipt/0.2`；Graph 只按四个 terminal 路由，消除每个 producer 自己的 status/branch union。Talk Transcribe 与 Translation Prepare 已对齐该形状，继续分别保留 media reconciliation 与 fenced-generation、manifest-last publication 的确定性语义。
  - Child MaterialReceipt admission 删去重复的专用 receipt 解释，改经共享 schema/Stage validators 重证 identity、canonical artifacts 与 clean final audit；strict Topic recall vertical 同步进入 shared terminal path。为保留未迁移 rolling Topic synthesis 的闭合 schema，恢复了它仍引用的 `knownOutcome`/`unknownOutcome` 常量。
  - `docs/GRAPH_COLLABORATION.md` 固定了薄 Graph 与测试边界：协议、ingress、join 与 capability tests 是长期守卫，钉死逐 operation receipt/edge 的 characterization assertions 只作为迁移脚手架。已知债务是 `topic.audit.legacy`，它保留到 topic-merge round 再删除。

- **0.52.27** (2026-07-31): **Acquire 统一为 Stage Unit，并把状态判断留在专业 worker 与确定性观察层。**
  - Book/Paper Acquire 现在和其它非平凡阶段一样交付 `quasi.stage.receipt/0.2`；Book 年份不匹配或歧义是标准 `needs_input` terminal，不再让 Graph 保留一套 acquisition 专用终态判断。
  - 采集方法、来源选择、失败停止与年份证据判断下沉到 `download-agent` 合同，Graph 只保留 exact refs、共享资源边界与 schema-valid terminal routing；新增共享 `materials/route.mjs`，避免各材料循环重复解释同一 Stage receipt。
  - 新增只读 `quasi-status` 磁盘状态 oracle：它不启动 LLM、Graph 或网络，可按 Paper、Book、Talk 已落盘的 canonical artifacts 给出已证明阶段和下一阶段的 exact refs。

- **0.52.26** (2026-07-31): **清理 Workflow、Stage specialist 与外层 Skill 的职责边界。**
  - Paper/Book 批次继续只启动一张顶层图；runtime 现在以 `Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit` 的每阶段独立 FIFO lane 控制最多五个活跃 Operation。队列等待不算 invocation timeout，批次仍可流水推进而不是按五项 barrier 分组。
  - Material ingress、child join 与 batch 汇总统一升到闭合的 0.2 receipts。Graph 只管理 exact refs、阶段推进、并发、coalesce 与 typed terminal；Search、Prepare 等 Stage specialist 对自己的目标、可用能力和 schema 负责，外层 `collect-material` 只启动图、处理真正的人类 gate 与安全 checkpoint。
  - Book/Paper Acquire 改为直接返回单项 Operation receipt，Paper Audit 也删除中间 adapter；Author artifact contract 改由 schema registry 生成，Talk 的 silent canonical 合并进 Prepare specialist，避免额外 worker 和重复状态解释。
  - `quasi-download accept` 增加同输出锁、sibling staging、流式 digest、fsync 与原子发布；Talk 压缩发布后清除 macOS staging inode 遗留的 hidden flag。生成 bundle 为 308,172 bytes；全库 810 项回归通过。

- **0.52.25** (2026-07-31): **修复 Book EPUB chapter-ref 生成端，不再用放宽标准接纳坏 manifest。**
  - Sen 的 17 章 Prepare 并非因 `disposition:replaced` 失败；真实 seam 是旧 extractor 把 filename-derived title 的下划线保留进 chapter slug，而 StructuredOutput schema 又没有公开 Graph 实际要求的 ASCII kebab-case。Chapter slug 现在在 host schema 与 Graph backstop 中共同固定为 `^[a-z0-9][a-z0-9-]{0,79}$`，Agent 会在交付前看到精确要求；underscore、Unicode、空格、点与路径分隔符继续 fail closed。
  - EPUB extractor 原生读取 `.htm|.html|.xhtml`，NCX 标题先规范化空白，slug 只由确定性 CLI 生成；无法 ASCII 化的标题使用唯一 `section-{slot}`。0.52.23 曾为接纳真实 receipt 而允许 title tab，本版撤回该放宽并在 schema 中禁止控制字符。
  - PDF/EPUB extraction fingerprint 新增 `canonical-v1` chapter-ref contract。旧 generation 不被兼容放行，而是在下一次 exact-source Prepare 中通过同一锁、staging 与 manifest-last transaction 重建。生成 bundle 为 293,722 bytes；全库 782 项回归通过。

- **0.52.24** (2026-07-31): **修复 Talk Prepare 在真实 StructuredOutput 中无法表达缺失 canonical 的问题。**
  - 原生 `glm-5.2` worker 已正确复用 committed transcript generation 并判定 `live`，但 `canonical_sha256` 连续被编码为字符串 `"null"`、空字符串或缺失，五次均被 schema 拒绝。Prepare 因而错误终止为 `talk.writer_outcome_unknown`，Analyse 从未获得执行机会。
  - Talk Prepare 不再用 `canonical_exists + nullable scalar hash` 表达同一事实。Source、generation 与 canonical 现在各自使用单一 `object|null` observation；不存在的 canonical 是整个 observation 为 null，存在时 object 同时绑定 exact path 与真实 digest。未完成分类使用显式 `unclassified`，不再要求宿主生成顶层 nullable string。
  - Graph 只验证下一阶段需要的 exact observations 与 transcript artifacts，没有新增转录个案、CLI 次数或隐藏恢复条件；全零伪 digest 仍 fail closed。生成 bundle 为 293,248 bytes；全库 773 项回归通过。

- **0.52.23** (2026-07-31): **修复三个由 StructuredOutput schema 与 Graph 完成谓词漂移造成的假阻断。**
  - Talk Prepare 的 nullable SHA-256 改为显式 `null | constrained string` schema 分支，避免 Claude 把缺失 canonical 的 JSON null 生成为字符串 `"null"`。Graph 仍只接受真实文件 hash；`canonical_exists:false` 搭配全零伪 hash 会明确失败。
  - `material.search` 现在按既有 schema/Agent 语义接受 `local_owner:null` 为“已检查且无本地 owner”，并沿 Search 选出的 canonical identity 进入 Acquire；exact owner object 仍须绑定同一 identity 与 canonical vault path。
  - Book Prepare 不再用通用控制字符规则否决逐字来自 EPUB manifest 的章节标题。内部 Tab 等 TOC 排版字符可随完整有序章节表进入 Analyse；manifest、slot、filename、slug、成员路径及唯一性证明保持严格。Esposito 的真实 12 章 receipt 已直接重放为 complete；缺失的 EPUB 聚合 `source.txt` 仍是合法的非必需观察。生成 bundle 为 292,632 bytes；全库 773 项回归通过。

- **0.52.22** (2026-07-31): **Stage 回执成为真正的闭合终态，Search canonical identity 不再被 provisional slug 反向否决。**
  - 统一 Stage receipt 升至 `quasi.stage.receipt/0.2`：必填 `terminal` 是嵌套的 `complete|needs_input|blocked|failed` 联合结构，`complete` 只能携带 `issue:null`，`needs_input` 必须给出可回答的问题；Search 的人工卡点还逐字保留候选 identity 与冲突字段。Claude StructuredOutput、Graph backstop、Codex strictifier 和 GUI driver 因而消费同一份完整性合同，不再依赖 Graph 猜测互相矛盾的顶层字段。
  - `material.search` 选出的 canonical slug 现在是 vault owner 查询和下游路径交接的唯一键。题名规范化、副标题补全或 canonical slug 改进可正常进入 Acquire；作者、作品、年份、identifier、edition 或 publication type 的实质冲突则作为 typed `needs_input` 返回，不再伪装成 owner mismatch。
  - Metadata/Prepare specialist 在交付前按 schema 选择并自检一个 terminal 分支。524 等宿主/API 中断仍诚实终止当前 run，没有新增 Graph 自动重投、provider 次数表或文献个案分支。生成 bundle 为 292,508 bytes；全库 769 项回归通过。

- **0.52.21** (2026-07-31): **Workflow 收敛为阶段看板，specialist Agent 接回专业方法与局部恢复。**
  - Search、Paper/Book Prepare、Talk Prepare 与 Translation Prepare 现在各由一次 goal-owning specialist invocation 完成。Workflow 只注入目标、capabilities、exact refs 与统一 `quasi.stage.receipt/0.1` schema，并按 `complete|needs_input|blocked|failed` 推进；查询、证据交叉核验、OCR、章节规划与局部恢复由对应 Agent 根据实际材料判断。
  - 单本 Book/Paper ingress 删除了重复的独立 `material.recall` worker。`material.search` 在同一次调查中先核定 identity，再通过 vault resolver 核对 exact local owner；Recall 仅保留为请求归一化与 same-run coalesce 的 UI 阶段，不再产生第二份 nullable lookup receipt。
  - Graph 不再因 schema-valid specialist failure 不符合隐藏策略而改判 receipt invalid，也不会在 readonly Stage outcome 未知时自动启动第二个 specialist。Exact artifact ownership、writer no-replay、batch phase admission 和 collection join 仍保持严格。

- **0.52.20** (2026-07-31): **把 Workflow 收敛为 Operation 图：回执校验进入 Schema/Runtime，Agent 接回稳定执行合同。**
  - Writer 的 exact path、ordered inputs、status matrix 与 closed failure 现在由每次调用的 composed StructuredOutput schema 直接约束；仍在运行的原 Agent 会被宿主要求修正不合格 receipt，Graph 只消费 `unknown|mismatch|reconcile|blocked|failed|ok` 闭合边，不再复制一套细粒度验证或在 unknown writer outcome 后重投。
  - `runtime.mts::operate` 用同一个 host schema 做统一 backstop；跨字段计数、年份证据、人类决定 replay、reconcile 解释等 JSON Schema 无法表达的少量语义留在 Operation contract。Author/Topic 的 child MaterialReceipt join 继续严格重证 identity、canonical artifact 与 final audit，host-pluggable dispatch seam 不被错误信任。
  - 有明确 owner Agent 的 operation prompt 改为自足 JSON envelope。Agent 合同统一拥有 exact-command/transaction discipline、JSON 类型保真、禁止 alternate command/retry/自行选图边；operation request 只携带业务词汇、exact refs、mode、diagnostics 与 evidence policy，host schema 拥有最终 receipt 形状。Talk transcription 合同因此从大段示例与字段清单收敛为稳定 relay 协议。
  - Book/Paper/Talk/Author/strict Topic/Translation 图移除重复 prompt pack 与 receipt predicate，生成 bundle 保持在 Claude Code 上限内；410 项 workflow 回归和 19 项 Talk/Translation relay 合同回归通过。

- **0.52.19** (2026-07-31): **批量材料共用一张处理图，并修复三处原生 Workflow 合同接缝。**
  - 同一请求中的 2–32 个 Book/Paper 现在作为一个 `kind:"batch"` envelope 进入一次 Workflow，共享同一 runtime，按输入顺序并行推进 `Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit`。顶层返回 `quasi.collection.material-batch.receipt/0.1`，逐项汇总 `complete|needs_input|blocked|failed`；一个卡点不取消其它材料，也不再在 Claude Code UI 中展开成 N 张同名图。
  - `material.recall` / `material.resolve` 升到 receipt 0.2，以无歧义的 `__none__` / `match:"none"` 表达 miss，再由 Graph 边界归一化为内部 null。这样绕开 Claude StructuredOutput 对 nullable path 的 `"null"` 字符串与 pattern 重试问题，同时保持 hit 的 canonical path、slug 和 identity 严格校验。
  - Book acquisition 在 `status:"ok"` 后丢弃不再具有语义的临时下载路径观察；最终 source path、identity、format、year evidence、source 和 attempts 仍按原严格矩阵验证。Paper create collision 则明确视为“未写入且 outcome known”，必须通过随后 exact audit 才能把既有 canonical 标为 reused。
  - 唯一生成 bundle 为 398,688 bytes，低于 Claude Code 的 512 KiB 上限；全库 980 项回归通过。

- **0.52.18** (2026-07-31): **修复材料未命中时 `"null"` 字符串阻断 metadata ingress。**
  - Claude StructuredOutput 在 `material.recall` 的 nullable string 字段上可能把要求的 JSON `null` 写成字符串 `"null"`。它满足了宽松的 `string|null` schema，却被 Graph 的严格 Recall validator 拒绝，导致批量材料在 Search 前全部 `metadata_failed`。
  - Recall/Resolve schema 现在优先声明 null、约束 canonical vault path，operation prompt 与 `metadata-agent` 明确要求无引号的 JSON null。Graph 只在 readonly lookup 的三个 miss 字段全部为 null sentinel 时确定性归一化，随后照常执行严格校验；hit、identity 和所有 writer receipt 均不放宽。
  - 回归直接注入 `vault_slug/path: "null"` 与真正的 `match:null`，确认它们被规范为真正的 null、进入 Search/Resolve/Acquire，并在 ingress receipt 中保存闭合的 typed 结果。

- **0.52.17** (2026-07-31): **修复 Claude Code 拒绝加载过大的统一 Workflow。**
  - 0.52.16 的生成图达到 531,416 bytes，超过 Claude Code 对单个 Workflow 脚本的 524,288-byte 硬上限，导致图在任何节点启动前直接失败。构建器现在只压缩生成 bundle 的空白，不改标识符、字段名或运行逻辑；产物降至约 390 KB，并保留足够的后续增长余量。
  - 构建和测试新增 512 KiB 硬性体积门。以后无论本地构建、`--check`、CI 还是发版，只要统一图重新超过宿主上限就会在发布前明确失败，不再把不可加载的版本交给用户。

- **0.52.16** (2026-07-31): **材料从第一步进入统一图，Workflow UI 改为真正的处理看板。**
  - 顶层单本 Book/Paper 不再由 `collect-material` 在图外先跑 metadata 与 vault recall。Workflow 新增闭合的 `material.recall → material.search → material.resolve` readonly ingress，接收用户原始 title/DOI/ISBN 提示后核定 canonical identity、已有 vault owner 与写入路径，再进入 Acquire；Author/Topic 已验证的 child identity 继续直达 child Material Loop，不重复搜索。
  - `collect-material` 收敛为薄协调层：启动图、展示 typed user gate、传递 Book year/Translation source 决定，并解释 blocked/failed receipt。未知 writer outcome 不再由 Skill 猜测文件存在后自动重投；下一次明确调用由图内 Recall/reconcile 观察真实产物。`metadata-agent` 同步改为只执行 caller 注入的 recall/search/resolve operation。
  - Workflow UI phase 从 `Paper|Book|Author|Talk|Topic|Translation` 分支名改成统一的 `Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit`，label 统一以 material/collection slug 开头。批量 Paper、Book 或 Author 运行现在可以直接看出每项材料停在哪个处理阶段。
  - `synthesis-agent` 与 `translate-agent` 删除大段 operation-specific 流程和示例，只保留稳定的输入输出、证据纪律、exact-write/command-relay 与 receipt 协议；Book/Author/Topic synthesis 结构及 Translation transaction 细节由 operation adapter 以自足 envelope 注入。Topic legacy synthesis 也改为显式 refs、outputs、artifact contract 和 diagnostics，不再依赖 Agent 内隐藏 mode dispatch。
  - 生成 bundle 与模块源码保持一致；Book/Paper/Author/Talk/Topic/Translation、Claude/Pi/Codex adapter、Schema/CLI 与 Skill 全库回归共 861 项通过。

- **0.52.15** (2026-07-30): **Book TOC 提取回执与严格 Graph 对齐。**
  - `quasi-extract split --method toc` 的 manifest 会保留已知 `start_page`，在没有逐章写入确定性结束页时返回 `end_page: null`。Book Graph 现在接受这一合法的 start-only 章节引用，不再把已经事务落盘的 TOC 章节集误判为 `book.writer_receipt_mismatch`。
  - 其它页码边界仍保持 fail closed：只有结束页、页码小于 1、或结束页早于起始页继续拒绝。回归覆盖真实 TOC receipt 形状与两个反例，并重新生成唯一 Workflow bundle。

- **0.52.14** (2026-07-30): **按工作位置拆分检索 worker，并让 Book acquisition 可严格恢复。**
  - 旧的多模式 `search-agent` 删除；已知材料书目核验、Author/Topic/缺失引文发现、中文版本关系分别由 `metadata-agent`、`discovery-agent`、`localisation-agent` 承担。`download-agent` 只为既定 identity 寻找访问路径，不再混入 metadata 或 discovery。
  - Book acquisition envelope 现在逐字段声明固定 `year_evidence` 合同，禁止 worker 把年份证据改写为自拟字段或自然语言 verdict。真实下载已落盘但 receipt 未能证明严格合同时，`collect-material` 仅在唯一 exact source 存在且 resume 明确为 `book.reconcile` 时发起一次 bounded 新 run；它只核验现有文件，不再 fetch。
  - Author、Topic、citation recovery、LOCALISE、Codex role 映射、状态行与维护文档全部切到新 worker 边界；生成 Workflow 与源码保持确定性一致。

- **0.52.13** (2026-07-30): **材料 Skill 恢复自然语言“处理”路由。**
  - `collect-material` 的 routing description 现在明确覆盖处理一篇或多篇论文、文章或书籍；用户无需刻意说“采集入库”，原有采集、作者材料、PDF、翻译和录音意图仍保留。

- **0.52.12** (2026-07-30): **Draft Skill 恢复英式拼写。**
  - 公共入口由 `finalize-draft` 修正为 `finalise-draft`，与项目采用的英式拼写和用户术语保持一致；Workflow、Agent 与产物协议均未改变。

- **0.52.11** (2026-07-30): **采集成功回执补齐来源证明，公共 Skill 采用更顺手的动词。**
  - Paper acquisition 的成功 item 现在必须返回非空 `source`；验证并复用既有 PDF 时固定为 `existing_file`。此前 0.52.10 已统一 caller path，但真实 Workflow 又证明 Agent 可能漏掉 strict validator 所需的来源字段，导致正确 source 仍被 fail-closed。
  - 最外层材料 Skill 会把可信 metadata 的 `container_title|venue` 归一化为 Paper `journal`；对 `paper.acquire` 的 unknown receipt，仅在 exact source 已存在且 resume 明确为 `paper.reconcile` 时自动发起一次 bounded 新 run。其它 unknown writer 仍不重投，并报告 stage、failure 与 resume。
  - 公共入口改名为 `collect-material`、`finalize-draft`、`precise-topic`；内部 host-neutral bundle 仍叫 `workflows/process-material.mjs`，避免把用户路由名称与稳定运行 ABI 混为一谈。

- **0.52.10** (2026-07-30): **收敛公共 Skill，并修正 Paper 获取回执的路径边界。**
  - `process-talk` 合入 `process-material`，Talk 的渐进加载合同移到该 Skill 的 reference；`process-draft` 改名为英式拼写的 `finalise-draft`，`research-topic` 改名为 `organise-topic`。公共入口由四个收敛为三个，但底层 Talk、Material 与 Topic Workflow 能力不变。
  - Paper/Book acquisition receipt 的 `path` 现在必须逐字回显 request 中 caller 指定的相对路径；`quasi-download` 返回的绝对解析路径只作为观察证据。此前已正确取得并核验的 PDF 会因两种等价路径写法不一致而被误判为 `writer_receipt_mismatch`。
  - 下一轮 Paper 调用可由 reconcile 复用已经存在且身份已核验的 source，不需要重新下载，也不再因 CLI 的绝对路径回显而阻断。

- **0.52.9** (2026-07-30): **Configure 的翻译选项按决策顺序分组并缩短标题。**
  - 展示顺序改为 PDF translation backend → Immersive auth key → 三个 pdf2zh 字段；用户先选后端，再只填写该后端需要的配置。
  - 后端标题不再内嵌 `immersive or pdf2zh`，pdf2zh base URL 标题不再内嵌 `OpenAI-compatible`；合法值、兼容协议与 URL 规则保留在字段 description。

- **0.52.8** (2026-07-30): **macOS Keychain 二进制凭据兼容与简化 marketplace 身份。**
  - Claude Code 会把某些 `Claude Code-credentials` password 作为二进制数据保存；`security ... -w` 对这类记录返回十六进制文本。Python hook helper 与 Pi runner 现在同时接受裸 JSON 和十六进制 UTF-8 JSON，Configure 中已保存的敏感字段不再出现“钥匙串里存在、quasi 却读取不到”的假缺失。
  - Marketplace 从 `ramu-toolkit` 简化为 `ramu`，新安装标识为 `quasi@ramu`；插件本身仍叫 `quasi`，Configure 字段和 Keychain 数据结构不变。
  - 新增 Python/Node 双路径回归，覆盖裸 JSON、十六进制 JSON、显式环境变量优先及 Keychain 缺失的 fail-soft 行为。

- **0.52.7** (2026-07-30): **单入口 Workflow 分层、Schema 驱动产物合同与可恢复的材料事务。**
  - `workflows/process-material.mjs` 继续是 Claude/Pi/Codex 共用的唯一运行入口，但可维护源码拆到 `scripts/workflows/`：Material、Collection、Research、Derivative Loop 只消费 typed Operation receipt；构建器确定性生成并校验 host-neutral bundle，不再靠手改 15K 行生成物。
  - Paper 与 Book 已迁到 fail-closed Material Loop：writer 的 null/timeout/malformed receipt 一律 blocked/unknown、下一轮从 reconcile 观察真实 artifact；Paper 的 extract/readability/OCR/analyse/audit 与 Book 的 transactional chapter extraction、boundary assessment、fan-out/join/refill/synthesis/audit 都有 exact path、有限预算和 owner routing。原生 Claude Book 三章 E2E 已完成 10 started/10 result、MaterialReceipt complete、双重 audit clean。
  - Paper、Chapter、Book overview 与 Talk 的 frontmatter、路径、identity、H1/H2、block kind 和表格列统一由 `scripts/schemas/` 导出 artifact contract；analyse/synthesis Operation 只注入 schema projection、exact refs 与动态 seed。原来仅供 acquisition 使用的 prose prompt-pack 生成链也已删除，Paper/Book acquisition 改为所属 Operation 注入结构化 policy。
  - Book PDF/EPUB extraction 统一走同目录锁、sibling staging、manifest-last publish、manifest fingerprint 与精确 slot repair；旧 generation、stale managed files、并发 legacy/JSON writer 和 post-manifest fsync failure 都有 typed receipt 与故障注入回归。Talk transcription/compression 与 PDF translation 同样获得 observe/run transaction、generation fence 和严格 receipt。
  - Author 开始只消费 exact child MaterialReceipt，Topic 独立为 `research-topic` 公共 Skill；两者仍复用同一 router，不复制 Paper/Book 图。Topic recall/discovery、outline、evidence cards 和 material dispatch 已有 typed 边界，复杂研究图继续按真实场景渐进收紧。
  - 新增 `quasi-codex-agents`:从唯一源码 `agents/*.md` 确定性生成项目级或用户级 `.codex/agents/quasi_*.toml`;默认不写任何范围,必须显式 `--project PATH` 或 `--user`,`--check` 可只验证漂移。插件 manifest 仍不声称能直接携带 Codex custom agents。
  - Codex driver 的 request 新增 `codex_agent_type`:`quasi:download-agent` 映射为 `quasi_download` 等已注册角色,普通调用映射为 `worker`。Skill 优先传原生角色,当前宿主未暴露 role selector 时仍执行通用 worker fallback。
  - 原来不可读的 `quasi_agent_N` task 名改成由 label + request suffix 生成的可读唯一名;完整 driver 协议抽到 `skills/process-material/references/codex-native-driver.md`,只在 Codex 路径渐进加载。
  - `research-topic` 成为独立公开 Skill,拥有 vault recall、outline、evidence card、`needs_seeds` 人工卡点与 topic 报告;`process-material` 只路由耦合的 paper/book/author 栈。二者仍共享 `workflows/process-material.mjs`,topic 的每个材料节点继续递归复用同一 paper/book router。

- **0.52.6** (2026-07-29): **title-only 输入先核定 metadata,下载失败保留证据。**
  - Codex BTS E2E 复现了与 Claude 的入口差异:Claude 先 dispatch `search-agent`,Codex 却从题名猜作者/年份/材料类型,以空 DOI 和非 canonical slug 启动图。`process-material` 现在把单本 `book|paper` 缺 ISBN/DOI 的 metadata search 写成强制前置阶段;Codex 用当前 thread 的可见 `quasi_metadata` worker,主进程禁止 WebSearch/WebFetch/browser 旁路。
  - `search-agent.picked` 必须按 provider 作者顺序补 canonical slug。BTS 实测 `Property, Power, Politics` 的正确记录是 Folkers 等、2026、*Theory, Culture & Society*、DOI `10.1177/02632764261457554`,不再从题名里把首位受访者误当作者首列。
  - 论文 metadata 合并器不再按并发完成顺序挑 `venue`:期刊名明确优先 Crossref,其 HTML entity 在 adapter 边界解码。此前 OpenAlex 先返回时会得到 `Theory Culture & Society`,而 Crossref 的注册名 `Theory, Culture &amp; Society` 虽已取回却被丢弃。
  - `download-agent` 的失败回执新增 `doi`、`failure_reason` 和逐来源 `attempts`;workflow schema 与 paper/book 失败结果原样上抛。此前 SAGE direct/OA/publisher 403、Sci-Hub 404、EZProxy 未配置、Wayback timeout 最终只剩 `download_failed`,主线程无法解释也容易临时转 browser。
  - Round 2 证明丰富 receipt 内联回 PTY 时会在约 1000 字符处截断并触发 `protocol_error`。driver 现在为每个 request 指定同目录 `receipt_path`;主线程把完整 JSON 落该路径,stdin 只发短 `result_path` event。driver 从指定路径读取、校验 schema,run 结束随 request dir 一起清理。
  - Codex 不提供 Claude Configure option env,且 native subagent 未必继承 coordinator 的 plugin hook。所有 Python-facing `quasi-*` shim 都 source `scripts/load-keychain-env.sh`,与 PreToolUse hook 共用运行时 `--keychain-exports` helper;缺失的 `QUASI_*` 从 `Claude Code-credentials` Keychain 填入,显式 env/宿主 option 优先。command argv 只含 helper 路径,不含 secret 值;也不把 secret 写进 driver envelope。
  - 真实诊断同时发现旧 Claude hook 会把 `CLAUDE_PLUGIN_OPTION_*` 展开为命令行 `export`,可被同用户的进程列表读到。macOS Claude 分支现在也改走进程内 Keychain helper,显式 `QUASI_*` 靠普通环境继承并由 helper 保留;测试用唯一 marker 守卫 rewritten command 不再含 secret 字面值。非 macOS 因无共享 Keychain provider 暂保留 direct-export 兼容路径。

- **0.52.5** (2026-07-29): **Codex GUI 原生 subagent driver。**
  - 新增 `quasi-codex-driver` / `scripts/codex-driver.mjs`:继续执行唯一的 `workflows/process-material.mjs`,但注入的 `agent()` 只经 stdout 发 JSONL `agent_request` 并在内存中等待 receipt。`process-material` skill 用当前 Codex thread 的 `spawn_agent` 响应,所以 download / extract / analyse 等 worker 会登记进同一 agent tree,GUI 可见、可 wait / followup / interrupt。
  - driver 的 PTY stdin 接收 `agent_result|agent_error|cancel`;原 workflow 的 JS continuation 不落盘也不复制。完整 worker 合同写到 `.quasi/temp/.../agent-N.json`,`agent_request` 只传短 `request_path`,避免 instructions / prompt / schema 被终端输出上限截断;run 结束后清理整个请求目录。
  - receipt 在 resolve 前按图内原 schema 校验,坏 JSON 发 `receipt_rejected` 让同一 worker修正;超时/取消发 `agent_cancel`。并发上限默认 3,给 coordinator 留一个 thread 槽。
  - Codex 有 native subagent + resumable exec 时默认走 driver;`quasi-codex-runner` 保留为 headless/CI fallback。真实 Codex exec 工具只有 `tty=true` 才保留可写 stdin,driver 在 PTY 中切 raw mode 关闭输入回显,避免回写 receipt 混入事件流。

- **0.52.4** (2026-07-29): **Codex 原生插件预览与薄 workflow runner。**
  - 新增 `.codex-plugin/plugin.json`,Codex 直接发现同一份标准 `skills/`;不复制 skill / agent / workflow 内容。
  - 新增 `quasi-codex-runner` / `scripts/codex-runner.mjs`:复用 Pi runner 已导出的 `createRunner` 图运行时,只把 worker invoker 换成临时 `codex exec --output-schema`。Claude 的可选 receipt schema 会被收紧为 Codex strict schema,结果仍按原 JSON 合同返回给 `process-material.mjs`。
  - `process-material` 根据 `CODEX_THREAD_ID` 走 Codex runner;Claude Code 的原生 Workflow 与 Pi runner 路径不变。Codex worker 默认 `workspace-write`、开启采集所需网络,只额外放行 plugin data;首版不硬映射 `sonnet|opus` 模型,只映射 reasoning(`high|medium`),可用 `QUASI_CODEX_MODEL` / `QUASI_CODEX_REASONING_LEVEL` 统一覆盖。
  - Codex 不把插件 `bin/` 自动加入 PATH;现有 PreToolUse hook 在改写 bare `quasi-*` 命令时同时注入 `<plugin>/bin`,继续维持所有 active skill 的稳定 shell surface。

- **0.52.3** (2026-07-29): **编排图迁到官方 `workflows/` 目录。**
  - `skills/process-material/orchestrate.mjs` → `workflows/process-material.mjs`(文件名对齐图内 `meta.name`)。官方插件参考把 `workflows/` 列为 Workflow 脚本的默认位置;放在 skill 目录里虽被允许,但专用位置让 `claude plugin validate` 与未来工具链都能认出它,也为日后按名调用(registered workflow)铺路。引用同步更新:`process-material/SKILL.md`、`pi-runner.mjs` 默认 `--script` 路径、两个测试文件、`docs/ARCHITECTURE.md`、CLAUDE/AGENTS 镜像。图本身零改动,Claude Code 走 Workflow 工具、Pi 走 `quasi-pi-runner` 的双路径不变。

- **0.52.2** (2026-07-29): **修复 Pi skill 发现:标准名称 + symlink 实路径。**
  - 三个 active `SKILL.md` 的 frontmatter name 从 `quasi:process-*` 改为 Agent Skills 标准 slug `process-*`;Claude Code 仍由插件宿主自动提供 `/quasi:process-*` 命令,Pi 则不再因冒号违反 `[a-z0-9-]+` 规则而拒绝加载。新增测试守卫 active skill 名称标准。
  - extension 用 `realpathSync(import.meta.url)` 解析 symlink,确保 `~/.pi/agent/extensions/quasi.ts` 指到稳定副本时仍把 `~/.agents/plugins/quasi/skills/` 注册给 Pi,而不是误算成 `~/.pi/agent/skills/`。

- **0.52.1** (2026-07-29): **Pi extension:把 quasi 的 skills 注册进 Pi 的发现路径。**
  - 新增 `extensions/quasi.ts`(15 行):监听 Pi 的 `resources_discover` 事件,把 quasi 的 `skills/` 目录注册为 Pi skill 搜索路径。打开任何 Pi 窗口,说"处理这篇论文",Pi 就能发现并路由到 `process-material` skill,不再需要手动调 `quasi-pi-runner`。Extension 通过 `import.meta.url` 反推 plugin root,不硬编码路径。
  - 安装方式:`~/.pi/agent/extensions/quasi.ts` → symlink 到 `~/.agents/plugins/quasi/extensions/quasi.ts`(稳定路径,不带版本号,更新不断)。`~/.agents/plugins/quasi/` 是 quasi 的无版本号副本,每次发版后需要同步。

- **0.52.0** (2026-07-29): **quasi 可以在 Pi 下跑了;plugin 配置全加密进 Keychain,runner 读同一份 blob。**
  - 新增 `scripts/pi-runner.mjs` + `bin/quasi-pi-runner`:Pi 专用适配器,直接用 `@earendil-works/pi-coding-agent` SDK,不引入第三方 workflow 兼容层。它执行同一份 `skills/process-material/orchestrate.mjs` 图——把源码包进 `AsyncFunction`,注入 `agent`/`parallel`/`phase`/`log`/`args` 五个全局原语,所以图本身零改动。Claude Code 继续走原生 Workflow 路径,两条路径共享同一个确定性图和同一组 agent 定义。
  - runner 从 `agents/*.md` 加载 `quasi:<name>` 定义(frontmatter name/tools/model + Markdown 正文),把 Claude 工具名映射成 Pi 小写工具名(`Read`→`read`、`Glob`→`find`、`WebFetch`→`web_fetch`),只给每个 agent 开它 frontmatter 声明的工具。structured output 用一个自定义 `structured_output` tool 实现(带 `terminate: true`),schema 由调用方传入;agent 没调就直接返 `null`,图的 `retryNull()` 照常重试。`web_fetch` 只在加载 `quasi:webcard-agent` 时注入,其余 session 里根本不存在。模型别名(opus/sonnet)找不到时继承父 Pi 的 `PI_PROVIDER`/`PI_MODEL`/`PI_REASONING_LEVEL`。并发限流放在真正的 `agent()` 边界(全局 semaphore),嵌套 `parallel()` 不会突破总并发上限也不会死锁。
  - **Keychain 配置桥**:runner 启动时从 macOS Keychain 读 Claude Code 的 `Claude Code-credentials` blob,解析 `pluginSecrets["quasi@*"]`,把每个字段写进 `process.env.QUASI_<KEY>`(已有环境变量优先)。这把 Claude 的 `PreToolUse hook → inject-userconfig.py` 链复刻到 Pi 路径:同一个 Keychain blob,同一个 `QUASI_*` 合同,两个宿主入口。非 macOS 或 Keychain 不可用时 fail-soft(退回手动 `QUASI_*` 环境变量)。
  - `translate_backend` 标为 `sensitive: true`,这样它也进 Keychain blob 而不是明文 `~/.claude/settings.json`;加上 Keychain 桥,runner 只需读一处就拿到全部 14 个配置字段,不用再读 settings.json。
  - 清理废弃的 `superset_agent`:从 `test_dead_names.py`、`test_hook_injection.py` 和 `process-draft/SKILL.md` 中移除残留引用。

- **0.51.3** (2026-07-29): **把双翻译后端的配置、URL 与 OCR 前置条件说清楚。**
  - `translate_backend` 现在显式默认 `immersive`,Configure options 的标题直接列出合法值 `immersive` / `pdf2zh`;Claude Code 的 userConfig schema 不支持 enum 下拉,所以仍是文本字段,运行时继续拒绝其他值。pdf2zh 三个字段统一加前缀,不再看起来像两个后端共用的参数。
  - `translate_base_url` 可以只填服务根地址:没有路径时 quasi 自动补 `/v1`(`https://api.deepseek.com` → `https://api.deepseek.com/v1`);已经给出的路径原样保留,因为兼容端点也真实使用 `/api/paas/v4`、`/v1beta/openai`、`/openai/v1`。`/chat/completions` 仍由 OpenAI client 追加,用户不填。
  - README/architecture 补上两个后端、配置字段与依赖边界:普通 born-digital PDF 走 pdf2zh 只要求 `uvx` + OpenAI-compatible endpoint,**不要求** DS OCR2/MinerU;二者只在 coverage 报 `Under-translated` 后的一次性重 OCR 恢复路径里出现。DS OCR2 需要 Apple Silicon,模型由 uvx/Hugging Face 首次下载;缺失时的 tesseract/逐行 fail-soft 会降低扫描书恢复质量。
  - `translate-agent` 不再把所有 auth 错误都误导成 `immersive_auth_key`:它按后端列出对应 Configure 字段,且禁止预先 OCR —— 只有 coverage 闸失败后才重做一次。

- **0.51.2** (2026-07-29): **`--layout` 三个只有扩样本才暴露的缺陷:旧文字层没剥干净、脚注不成段、块框可能倒置。** 起因是把测试样本从 3 本扩到 8 本,回答"每本书松紧不同要不要按书标定字号"。
  - `strip_text` 现在也剥 **Form XObject**。ABBYY 式扫描把 OCR 文字层放在名为 `OCR-<id>` 的 Form 里,而不是页面自身的 content stream —— 新测的 5 本书全是这个形状。漏剥的后果是页面上叠了两层文字,BabelDOC 的反应是**静悄悄丢正文**:coverage 0.23-0.29(健康值 0.33),其中一本每页都丢掉最长的那一段。修复后五本全部回到 0.30-0.35,页边碎片 9→0 / 23→14 / 7→3,重叠 10→3 / 23→15 / 48→19。只重写 `/Form` 子类型:同一个 `BT…ET` 正则打到图像流上会把图毁掉。
  - `FLOW` 加入 `ref_text`。脚注就是段落,留在逐行模式里等于原样复现这条路径要修的那个毛病;它是被漏掉的最大可流类别(三本脚注密集的书各 44/52/52 行),加上后 galison 页边碎片 3→1、hounshell 32→15。叶子规则仍然保证每条注单独成段:装着它们的 `list` 父块因为有子块而被丢弃。
  - 块框改用**排序后**的行边界,不再取 `lines[0]`/`lines[-1]`。grounding 顺序是阅读顺序,带插图的页面上一个块的末行可能在首行**上方**,于是算出倒置的矩形,PyMuPDF 直接抛 `text box must be finite and not empty` —— 真实书上的硬崩溃。
  - 结论是不做按书标定:再测 5 本,0.95 与 0.90 的页边碎片计数在噪声内完全一致(9/9、23/23、0/0、7/7、12/12)。看起来像"书有松有紧"的那点方差,是上面这三个 bug。

- **0.51.1** (2026-07-28): **`quasi-extract ocr --layout` 改为按段落成框,翻译后的中文不再被切碎。**
  - 逐行文本层是可读性的真正瓶颈:给 BabelDOC 一个"行"框,该行的中文就必须塞进该行的宽度,塞不下的尾巴被丢到页边。三本书各 10 页实测,逐行的页边碎片 11/12/19、重叠 20/34/77,改成段落框后是 1/3/33 和 0/7/32,段落连贯性 3/3 修好。
  - 段落归属来自 **MinerU2.5-Pro** 的 `layout_detect`,它只返回 `{type, bbox}`、不返回任何文字,所以 DS OCR2 的识别优势原封不动,MinerU 纯粹当分组器用。同一个 mlx-vlm 0.3.12 pin,约 2s/页(DS OCR2 约 20s/页),缺了就 fail-soft 退回旧的逐行层。
  - 行距取源页自己的行间距,所以流出来的文字落在它替换的墨迹上,不需要把框撑大——撑大正是让框互相重叠、译文叠在一起的原因。几何计算(嵌套、底边外扩)对**所有** block 做,可流类别的过滤放**最后**:先过滤会让脚注 `list` 在 `ref_text` 子块消失后显得无子,六条编号注释流成一坨;也会让图上方的正文块长穿整张图、吞掉图注。这两个都是第二本书上的真实回归。
  - 源层字号统一写 0.90 而不是逐段计算:BabelDOC 给 CJK 用 1.50 行距,而扫描书自己只有约 1.15,这个纵向缺口(不是字宽——中文同字号只要英文 0.70 的宽度)才是溢出的原因;scale 掉到 0.70 以下时 BabelDOC 不再缩字而是把段落框往右撑,那就是页边碎片本身。它还会把全文每段统一压到 `min(multimode(scales))`,所以源层字号一杂,输出就杂(主字号占比 41-49%,统一源层是 72-94%)。0.90 与 0.85 在三本书上缺陷持平,0.95 在最密的一本上一点没变大反而把均匀度腰斩,原大直接撞版。
  - 段内各行用 `join_lines` 拼接,在拼接点还原行末连字符(两个切片共 104 处),因此 `pre-logical` 里真正的连字符不会被吃掉。

- **0.51.0** (2026-07-28): **`quasi-translate` 长出第二个后端 pdf2zh,外加两道两个后端共用的产物闸。** 动机是本地化与自主可控,不是省钱。
  - `quasi-translate SLUG [--backend immersive|pdf2zh]`,默认 immersive。选哪个后端是用户配置(`translate_backend`)而不是 agent 的判断,所以 `agents/translate-agent.md` 对后端无感。pdf2zh 路线用 uvx 拉 `pdf2zh-next`,驱动用户自备的 OpenAI 兼容端点;新增四个 userConfig:`translate_backend` / `translate_base_url` / `translate_api_key` / `translate_model`。输出契约与 immersive 逐字节同构(`processing/translations/{slug}-{lang}.pdf`、原文译文交替、书签),因为 `--use-alternating-pages-dual` 产出的页序正是 immersive 走完 `split_dual_pdf()` 之后的形状,所以源解析、输出路径、TOC 三组 helper 原样复用。不认识的 flag 直接透传给 `pdf2zh_next`。
  - pdf2zh-next 把书译坏了也 exit 0,所以受理闸是输出页数 == 源页数 ×2;不合格的产物留在 `processing/translations/.pdf2zh-{slug}/` 供检查而不是删掉。`--pages` 局部跑会跳过 TOC:裁过的输出没有 1:1 的源页映射,书签会毫无征兆地落错页。
  - **ToUnicode 重建**(`scripts/translate/tounicode.py`,两个后端都跑)。BabelDOC —— Immersive Translate 的 PDF 流水线用的是同一套字体栈 —— 一旦超过几页译文,`/ToUnicode` CMap 就只剩几十条而不是每个字形一条。页面渲染完全正常,但复制粘贴和 PDF 内搜索全是乱码,因为阅读器退化成把裸 CID 当码点读。子集字体是 Identity-H 且保留原始字形编号,所以映射从 `~/.cache/babeldoc/fonts` 缓存的原始 TTF 重建(`QUASI_BABELDOC_FONT_DIR` 可覆盖);每次重建都拿 BabelDOC 写对的那部分交叉验证,对不上的字体跳过而不是写坏。脚本可单独跑,用来修这之前译出的旧 PDF。
  - **覆盖率闸**(`scripts/translate/coverage.py`,两个后端都跑,且必须排在 ToUnicode 修复之后)。一个页数正确、exit 0、零警告的 dual PDF,正文仍可能整段没译:源 PDF 自带的文字层太碎时,BabelDOC 的版面模型不再把段落认成可译块,原样留成扫描图。"译文汉字 / 源文拉丁字母"把两种情况分得很干净(实测健康页 0.30-0.36;一本只译出 43% 的书中位数 0.15、最差一页 0.01),所以闸门是逐页中位数对 `MIN_MEDIAN`。取中位数而不是均值或逐页规则,是为了不让一张图版或篇章扉页否决整本书;代价是好书里夹一张死页会放过。只对中文目标计分。顺序是硬要求:未修复的书在 CJK 扩展 A 区提取成乱码,而计数器故意不数那个区,于是一本健康的 368 页译作修复前算 0.17、修复后 0.31。`agents/translate-agent.md` 对这个错误的回答是走一次 `quasi-extract ocr --layout` 重 OCR 再译,只重一次。

- **0.50.2** (2026-07-27): **证据卡通道补齐身份、落盘与失败账,Annual Reviews 下载补齐出版商路由。**
  - `steer-agent` 现在必须给每条 `web_task` 一个 2-80 字符的单段 kebab-case `card_slug`;持久 schema、Workflow structured-output 与运行时边界同时拒绝缺失值、过短/过长值、`../`、斜杠、`.md` 和大小写路径。图不再按 query 猜文件名或给碰撞项补序号,因此一次任务只有一个稳定身份,不会覆盖别卡或生成 `.md.md`。
  - agent 的 `status: ok|unchanged` 只是声明,图会另起只读探针对 expected exact path 跑 `test -s`;回执的 `card_path`/`subq` 不匹配、agent 死亡、empty/error、或文件缺失都进入统一 failure 账,只有实存卡才算证据、阻止 `no_works` 并进入 synth。steer 每次运行还会删掉大纲中的失踪卡,并从磁盘收回已写但未登记的 orphan 卡。
  - 本轮成功卡和学术语料在下一次 steer 失败时仍会按既定 `subq`/`role` 合回本地子问题状态并记脏;`snowball_members` 把这次定向决定穿过采集阶段交还 steer,不让它从正文重新猜归属。失败/空卡任务记入 attempt 集,同一次图运行不再无限重派。已有卡无实质变化返回 `unchanged` 且不脏写专章;有变化只用 `Edit` 更新标题与正文,机械保留人写的 `created`/`themes`。
  - webcard fan-out 与独立的学术 probe/router 并发;每轮 card cap 在遍历中提前生效;增量 audit 只审本轮实际写过的 spine、专章和新卡,不再递归重扫整个 topic 历史目录。escalation 按 exact path 回到 outline/专章/card/spine 各自的 owner,不再拿 spine 重写敷衍所有坏页。正整数解析同时挡住 0、负数和小于 1 的小数配额造成的反向 slice/零轮运行。
  - Annual Reviews 增加 EZProxy host 的 `/doi/pdf/{doi}` 构造和 DOI `10.1146/` 的 direct PDF 路由;CookieCloud/EZProxy 已能落到文章页时不再因缺少出版商模式而误报 `no PDF found`。
  - 守卫覆盖 Annual Reviews 两条路由、card slug/path schema、磁盘证明、失败账、并发顺序、changed-file audit、metadata-preserving refresh 与用户卡点计数。plugin/marketplace `0.50.1→0.50.2`。

- **0.50.1** (2026-07-27): **topic 的圈外证据通道接上 —— `web_tasks` 从 0.50.0 的"只收不派"变成真的落地成材料卡。** 设计:`docs/topic-steering-design.md` §5。
  - **病例还是 sky-mobi**:证据在 SEC 文件、工信部规章、SDK 遗存、社交媒体回忆里,学术搜索传感器全程失明,6 条语料的主题页实际由圈外调研写成,雪球旁观。0.50.0 让 steer 报出了 `web_tasks`,但图不消费,那一条信息每轮原地蒸发。
  - **新 agent `webcard-agent`**:一条 web_task → 一张 `vault/topics/{slug}/cards/{card-slug}.md`(`quasi-search kagi` 检索 + WebFetch 抓一手来源 + 跨源核验)。三条硬约束都是针对同一个失败模式——**一张编造的机型卡会被 synth 当证据引用,比没有卡更坏**:抓不到不许用训练知识补完;每条关键事实两源一致才记 `confirmed`,单源记 `single-source`,冲突就两个数都写并标 `disputed`;拿不到可核验材料时返回 `status: "empty"` 且**不写文件**,图照实少收一张。「缺口/存疑」节不许留空。
  - **一卡的粒度是一条 web_task,不是"一个对象"**(设计原稿的修正)。用户在 unconventional 跑里手工产出的四份卡全是按品类汇总的合集(一张卡 6 款机型),已确认继续各自保留为一份合集、不拆成单机文件。所以任务的对象范围可以是一个具体对象,也可以是一个品类合集。
  - **卡是一条独立通道,不是语料**。`TopicSchema` 加 `kind: card`(新卡 frontmatter 仍只有 type/kind/title,与 dossier 同薄,`quasi-audit` 的 rglob 自动同审;另开 `created`/`themes` 两个**仅 card 可用**的可选字段并反向校验,因为老库那四张手写卡是从 `type: note` 迁进来的,strict schema 不该逼一次迁移丢掉人留的元数据 —— webcard-agent 不编这两个字段,但刷新已有卡时原样抄回);outline 加 `subquestions[].cards`(slug 表),与 `items` 平行。`items.kind` 仍是 `book|paper|talk` —— 把卡塞进去不会报错,只会让 synth 按 `vault/papers/{card}.md` 生成一条**读不到的死链**,分通道是唯一能让这个错误变响的做法。图里 `cards[]` 与 `ok[]` 分开累计,`cardPath()` 与 `itemPath()` 故意不共用解析器。
  - **`web_tasks` 单独也能驱动循环**(第二处设计修正)。原骨架把 webcard 挂在学术批次之后,但 `while (queue.length …)` 意味着学术候选为空时一轮都不跑 —— 正好是 sky-mobi 的形态,循环条件本身会把这条通道存在的理由否掉。改为 `while ((queue.length || webTasks.length) …)`;`no_works` / `needs_seeds` / `all_failed` 三个卡点改按"语料 + 卡"的证据总量判,否则一个 0 语料 + 5 卡的纯圈外主题会被当成"什么都没找到"。
  - 其余账:`card_slug` 由 steer 给(它握着 outline 卡表,能选刷新旧卡还是开新卡),缺了图按 query 确定性派生、批内重名补序号——随机或时间戳会让每次增量重跑在 `cards/` 里堆近似重复;卡回执**不 `filter(Boolean)`**,死掉的 agent 是 null 占位,滤掉就会把一张卡的标题安到另一张卡的 slug 上;新卡把其子问题加进 `dirty`(掌舵死了也记这笔账,否则专章不重写、卡白抓);每轮 ≤3 张,超出部分 `log()` 报出来不静默截断。
  - synth §T 两页都收 `card_paths`:dossier 多一节「证据档案」,01-resources 里卡在子问题小节内**另起子列表**与学术语料分开列(混列会让读者把圈外事实当同行评议结论),没被登记的卡进「未归类」。synth 读卡、引卡,但永远不写 `cards/`。
  - 探针/去重/batchYear/theory 配额/毕业机制/LOCALISE/guard 全不动。守卫:webcard 合同测试(禁幻觉/单卡所有权/证据三档/empty 不写文件)、图的圈外通道测试(循环条件/两条账不混/index 对齐)、steer 与 synth 的卡通道断言、TopicSchema card 与 items 拒卡测试。plugin/marketplace `0.50.0→0.50.1`。

- **0.50.0** (2026-07-27): **topic 从平面滚雪球改为闭环掌舵 —— 三个真实手机 topic(顺风/漂移/工具不对口)证明"与主题相关"的平面爬行在书为主的库里必然向社科经典回退。** 设计:`docs/topic-steering-design.md`。
  - **`02-outline.md` 成为持久研究状态**(schema `kind: outline`,subquestions 带 coverage/channel/theory_used):steer-agent 是唯一 writer,用户可手改,手改就是下次增量重跑的指令——把用户在 overview 里人肉写"本轮方针"的工作流正式化。
  - **新 agent `steer-agent` 吞掉 topicSearchPrompt + snowballPrompt**:每轮对账大纲、更新覆盖度、返回带 subq/role 标签的定向候选。两道栅栏:对象栅栏(候选自身的研究对象须落在子问题内,而非仅被主题文献引用)与 theory 配额(全 topic ≤3,账在 outline 跨轮累计)。成员表 subquestions[].items 持久在 outline frontmatter,跨轮跨重跑累计(评审修正)。可宣告 saturated 提前收口;web_tasks 本版只收不派(0.50.1 接 webcard)。
  - **子问题毕业成专章**:语料 ≥6 条 → `NN-{subq}.md`(编号只追加不重排),synth 拆 dossier(每页只读本聚类语料,0.49.4 爆 context 类结构性受控)与 spine(00 门面 + 01 清单,永远重写、恒薄,聚类结构照抄 outline 不许即兴)。只重写 steer 报脏的专章。
  - **终审修正四处**:种子轮回执的 dirty/saturated/建议词入账(丢弃它正好打断 legacy 迁移的毕业链);收到过活回执时空 dirty 意为"真没变",不再全量重写手写老专章;recall-only 主题补一次收口掌舵,库内语料必进成员表;role 随成员表持久并递入专章 synth。spine 不链接本轮写失败的专章,steer 对账自愈缺页。
  - 探针/去重/batchYear/needs_seeds 卡点/LOCALISE/guard 全不动。守卫:steer 合同栅栏测试、synth 分页测试、图闭环测试、TopicSchema outline/dossier 测试。plugin/marketplace `0.49.9→0.50.0`。

- **0.49.9** (2026-07-26): **`agent()` had no upper bound, so a dead subagent could stall the whole graph for hours.** Reported symptom: topic (and other) runs sit for hours with no progress and nothing in the main process reacting.
  - **Evidence, not inference.** In the `wf_2c154789-9f7` topic run, four agents were `started` in `journal.jsonl` with no `result` — all four `quasi:extract-agent`. Three of them had already written `API Error: 524 (Cloudflare timeout)` / `TLS handshake timeout` into their own transcripts at 13:35, 13:37 and 13:51; the run then sat until it was killed by hand at ~14:51. The agents were dead for over an hour while `agent()` never returned. `retryNull`'s `??` only fires on `null`, so the retry layer built in 0.45.0 was never reached, and the enclosing `parallel()` barrier held the graph frozen behind it.
  - **The fix is one race, not a supervisor.** `guard(prompt, opts)` wraps every `agent()` call in `Promise.race` against a 45-minute timer and normalises a timeout to `null` — which is precisely the value `retryNull` already knows how to handle, so a hung node costs one re-dispatch instead of a night. All five previously-bare `agent()` calls (the audit-escalation regens) route through it too; the only raw call left in the file is inside `guard` itself, and a test enforces that.
  - **45 minutes is measured, not guessed.** Across 202 real agent runs in the stored transcripts: `extract-agent` p50 10.6 / max 32.2 min, `search-agent` max 22.1, `analyse-agent` max 7.4, everything else under 11. The ceiling sits above every observed *successful* run, so it cannot behead a live agent, and far under the multi-hour stalls it exists to cut.
  - **Known residual, stated rather than papered over**: the workflow sandbox has `setTimeout`/`clearTimeout` but no `AbortSignal` (probed directly), so a timed-out agent cannot be killed — it keeps its concurrency slot until it ends on its own. The guard bounds the *graph*, not the zombie.
  - `tests/test_orchestrate_timeout.py` (3 guards: no unguarded `agent(`, finite sane constant, timeout resolves `null` into the retry path). plugin/marketplace `0.49.8→0.49.9`.

- **0.49.8** (2026-07-26): **`quasi-audit --report toc` — a book's chapter list has a sibling property nothing was checking (every title labelled or none, every title translated or none), and the honest answer is that no rule can check it.** The first cut was a `chapter_titles` diagnostic pass: six label styles recognised, duplicate/gap detection, `bilingual`/`cjk`/`latin` bucketing. It ran against the 1153-book production vault and produced 3287 findings over 696 books, but every rule in it had accrued an exception — `第一编·齿轮切削机——第1章 …` numbers the *part*, `C. Wright Mills` is an initial not roman 100, `1984 年的转折` is a year, `第2章 事实的建构：TRF(H)案例` is a Chinese title with an acronym in it, and majority-wins inverted its own polarity on `clare-the-marrow-s-telling-2022` (46 chapters, 26 untranslated to 20 translated) by flagging the 20 that were right. When the exceptions outnumber the rule, the rule is the wrong instrument. The whole pass was deleted before shipping.
  - **What ships instead is the half with no judgement in it**: `--report toc` groups `type: chapter` files by book directory and prints each book's `(filename, title)` list, verbatim, in slot order (`ch2` before `ch10`, so it reads like a table of contents rather than like `ls`). No normalisation, no verdict, no diagnostics. Whether a given book's mixture is a defect is a question a model or a human answers by looking at the list — which is exactly what the user does today, and what regex was pretending to do.
  - **The report carries its own reading instructions** (`TOC_GUIDANCE`, in the markdown body and as a `guidance` key in JSON): a listing nobody is told to act on gets read as trivia. It states the all-or-nothing rule and the one real trap — the fix is the chapter file's frontmatter `title`; the `chNN-` in the filename is the *source's* sequential slot, not the book's chapter number, so renaming files is never the repair.
  - Same shape as the existing `--report fields`: opt-in, read-only, `--format markdown|json` (`quasi-audit.chapter-toc.v1`), missing path → exit 2. Deliberately **not** wired into `audit-agent`, whose contract says 不要维护跨文件状态.
  - `audit.py` stays at ~700 lines instead of ~910. Three guards in `test_audit_cli.py` (slot order + non-chapters excluded + read-only, JSON titles verbatim, missing path). Suite 158 green. plugin/marketplace `0.49.7→0.49.8`.

- **0.49.7** (2026-07-26): **topic snowballing was running on a fraction of its fuel — prompt-layer fixes for four observed symptoms (dries up in 1-2 rounds, classics missed, books contribute nothing, no forward direction).** All in `snowballPrompt`; graph logic, `REFS_SCHEMA`, and agent files untouched.
  - **Books were mute in the snowball (the big one).** The prompt pointed book items at `vault/books/{slug}/00-overview.md` and said "read `## 核心引用`" — but the §B2 overview contract has never carried that section; it lives only in the per-chapter `ch*.md` analyses. Every book yielded zero citations, so a book-heavy vault snowballed on papers alone. Books now get `rg -A 30 '^## 核心引用' vault/books/{slug}/ch*.md`; papers/talks keep their exact paths.
  - **The "repeatedly cited" bar starved later rounds.** With ≤8 analyses per round the cross-text citation intersection is tiny, and identifier-resolution drops more. Now: multi-cited first, but single-cited works that are plainly foundational for the topic are kept too.
  - **Top-up before giving up**: the prompt now carries the round's target count (`perRound`); if filtering leaves fewer, the agent broadens with 2-3 self-chosen queries via quasi-search in the same call. `suggested_queries` shifts from last words at the dead-end to use-first-report-if-still-short.
  - **Approximate forward step**: for the 2-3 most-cited works of the round, one quasi-search each (short title + topic terms) pulls in newer literature responding to them. Real forward snowballing (OpenAlex `cites:` / `referenced_works` — the backend already exists in `scripts/search/sources/openalex.py`) is deferred until the prompt layer shows its ceiling.
  - Graph + prompt only; existing guards (`[...local, ...roundOk]` round-1 seeding, talk `## 文献人物`) still hold. plugin/marketplace `0.49.6→0.49.7`.

- **0.49.6** (2026-07-25): **agent-contract audit — the workflow cycle hardened the graph; this pass hardens the nine agent files themselves.** Systematic sweep of `agents/*.md` (1618 lines): two real defects, one dead-weight excision, one privilege trim. download/search/citecheck/proofread/translate came out clean.
  - **`extract-agent`'s declared protocol never promised the `chapters[]` array the graph fans out on.** `EXTRACT_RESULT` listed status/chapter_count/method/problems/notes — while `EX_SCHEMA` requires `chapters: [{slot, filename, slug}]` and the entire per-chapter analyse fan-out is driven by it. It worked only because StructuredOutput coerces the field at dispatch time; schema begging is not a contract (the `needs_ocr` class). The receipt now names the array, marks it a verbatim transcription of `manifest.json`, and says outright what silently breaks without it.
  - **`synthesis-agent` pointed at two deleted files for its templates** — §B2 "模板见原 overview-agent.md" and §A2 "模板见原 profile-agent.md" referenced agents absorbed and removed long ago; every run improvised template details (the required-H2 tables carried the audits). Pointers dropped; the in-file H2 tables are now the sole authority.
  - **`journal` and `kb-update` modes excised from `synthesis-agent`** — zero callers anywhere outside the file itself (process-journal has been archived for many versions). 268 → 229 lines; the mode enum, dispatch table, §K section, and the absorption-history note all go. All four names join `DEAD_NAMES`.
  - **`analyse-agent` loses its `Edit` grant** — its contract writes exactly one new file (Write suffices; regen is a full overwrite). Surplus grants are drift doors.
  - Guard: `test_extract_contract_promises_the_chapters_array_the_graph_fans_out_on`; dead-names entries for `kb-update`/`mode: journal`/`profile-agent`/`overview-agent`. Suite 155 green. Agent contracts + tests only. plugin/marketplace `0.49.5→0.49.6`.

- **0.49.5** (2026-07-25): **author synth now sees the chapter inventory before choosing what to read.** 0.49.4's budget fix told the agent "overview only, at most 2 chapters if the overview names one" — which made chapter selection depend on the overview happening to point somewhere. Disclosure is cheap, reading is expensive: §A1 now Globs each book's `ch*.md` **filenames only** (a few hundred bytes; slugged titles carry real signal), and the agent self-selects a few chapters to deep-read against that inventory — pivotal chapters, or on-topic titles the overview undersells. Budget unchanged (full mode ≤3/book, excerpt mode ≤1). Guard asserts the inventory stays filename-only. plugin/marketplace `0.49.4→0.49.5`.

- **0.49.4** (2026-07-25): **`synthesis-agent` gets a reading budget — the author-mode contract ordered a full Read of every chapter of every book, and the Philip Agre run overflowed the model's context.** The graph behaved perfectly: `synth-author`'s prompt was the tiny paths-only contract (3 book overviews + 10 papers), retryNull re-dispatched after the first death, and the graph returned an honest `synth_failed`. The kill was inside the agent: §A1 step 1b said "Glob 同目录 `ch*.md` 逐一 Read" — for Agre that's 34+ chapter analyses plus 10 full papers ≈ 1MB of text, and both attempts died on the API's deterministic `Prompt is too long`. The contract was written when an author meant one thin book; corpus size scales with the vault, the context window doesn't.
  - **Fix, in the contract**: §A1 now (1) measures first — `wc -c` over all input paths, an observable number, not vibes; ≤300000 bytes → full-text mode, above → excerpt mode (papers contribute frontmatter + `## 核心论点`/`## 关键概念`/`## 金句要点` via `rg -A` extraction); (2) reads **only `00-overview.md` per book** — the overview *is* the compression, synthesized from all chapters by book-synth; "books get diluted by papers" is a writing-weight concern, not a read-volume one; at most 2 pivotal chapters may be added per book. §J1 (topic/journal) inherits the same gate — topic corpora grow with local recall and have no ceiling. §B keeps its per-chapter reads: one book's own chapters are that mode's irreducible input.
  - Note: 0.49.1's `synth_failed` auto-resubmit retries this class too — for a *deterministic* overflow that costs one wasted re-run before escalating, which is acceptable; the budget gate makes the overflow stop happening at all. Guard: `test_synthesis_agent_bounds_its_reading_budget`. Suite 154 green. Agent-contract + test only. plugin/marketplace `0.49.3→0.49.4`.

- **0.49.3** (2026-07-25): **a real Agre author run looked like "60+ runaway papers of one person" — every cap had held; two display-layer defects manufactured the panic.** On-disk truth: exactly 10 papers (the `maxPapers` default), one already-in-vault book correctly probe-skipped, one new book (`agre-reinventing-technology-1997`) with 19 chapters. But the UI showed "Paper · 76 agents" with dozens of identical rows, because:
  - **`phase()` races under parallel recursion.** It is global mutable state; when `processAuthor` runs book and paper nodes in parallel, whichever node's `phase()` call lands last claims *every* subsequently-spawned agent — 19 chapter analyses filed under the *Paper* header. The Workflow API documents `opts.phase` as the fix for exactly this race; the graph now pins an explicit `phase: 'Book'|'Paper'|'Author'|'Topic'` on all 32 agent call sites (the `phase()` calls remain for group ordering). Recursed book work inside an author/topic run now displays as Book work.
  - **The chapter slot sat past the label truncation point.** `analyse:${slug}:${ch.slot}` truncates to `analyse:agre-reinventing-tec…` — 19 rows rendered byte-identical, indistinguishable from 19 separate papers. Labels now lead with the distinguishing part: `analyse-ch${ch.slot}:${slug}` (and `refill-ch*`/`regen-ch*` to match). Incidentally this converges on the label shape the 0.48.1 E2E worker's TASK doc had *expected* and flagged as a mismatch.
  - Guard: `test_orchestrate_agents_carry_explicit_phase_and_distinguishable_labels` (no bare `{ agentType:` in the node region, ≥30 phase-pinned sites, slot-first chapter labels). Suite 153 green. Graph + test only. plugin/marketplace `0.49.2→0.49.3`.

- **0.49.2** (2026-07-25): **topic recall now sweeps `vault/talks/` — talks can ONLY come from local recall, so skipping them made every talk permanently invisible to topic synthesis.** Same blind-spot class as 0.48.2, narrower scope: online discovery can never surface a recording the user made, so there is no probe, no snowball, no any-other-path by which a talk could enter a topic's corpus. The user's real vault carries 60 analysed talks (`vault/talks/{slug}/talk.md`, `type: talk` frontmatter with `themes`) — all of them off-limits to every topic run until now.
  - **Wiring**: `vaultRecallPrompt` sweeps `vault/books vault/papers vault/talks` and maps talk dirs to slugs; recalled items keep `kind: talk` (anything else non-book still defaults to paper); `itemPath` resolves `talk` → `vault/talks/{slug}/talk.md`; snowball reads the talk page's citation section, which is `## 文献人物` — not `## 核心引用` (checked against all 60 real talk pages, zero of which carry the book/paper heading). Talks never enter the router: they are corpus-only, which is the whole point.
  - **Deliberately NOT merged: talk *processing* stays in `process-talk`.** The graph's value is recursion (author/topic → book/paper); talk is a leaf — nothing recurses into it, it recurses into nothing, and it has no acquisition front-end (no search, no download, no dedup probe — the input is a local recording). The shared tail (analyse/audit) is already shared at the worker-agent layer, which is the right layer. Merging would buy one entry point and cost an alien branch plus its E2E burden.
  - **Live-verified read-only on the real vault**: a recall agent for "核想象与核档案 (nuclear imaginaries and nuclear archives)" returned the talk `atomic-anxieties-and-nuclear-imaginaries-20241114` as its top hit with `kind: "talk"`, alongside 7 on-point books/papers (Jasanoff, MacKenzie, Galison), all 8 slugs disk-verified. Guards: three new asserts in the recall test (sweep includes talks, itemPath resolves them, snowball reads `## 文献人物`). Suite 152 green. plugin/marketplace `0.49.1→0.49.2`.

- **0.49.1** (2026-07-25): **settling the accounts the E2E cycle left open — four small fixes, each traceable to a specific run.**
  - **Author corpus dedup** (same class as 0.48.3's topic fix, still latent in author): two different candidate slugs can probe-resolve to the *same* `vault_slug` — one book under two search namings — and both entered `okBooks`/`okPapers`, so the synth contract carried duplicate paths. Both lists are now `Set`-wrapped.
  - **Topic-landed books get LOCALISE**: the loop covered a single book (`[key]`) and an author's `book_slugs`, but books a topic run lands (0.48.2 E2E: Hughes, Lave) never got 中译本回填. The topic receipt now carries `book_slugs` too (a loop needs names, counts can't drive it) and the skill's list simplifies to `[key]` for book, `result.book_slugs` otherwise — `localise scan` is ISBN-idempotent so historical entries cost nothing.
  - **`synth_failed` auto-resubmits once**: in the 0.48.2 E2E a 90-minute topic run succeeded end-to-end except the final synth, whose agent *and* retryNull retry were both killed by transient provider errors — the whole run reported failure. Items are idempotent (recall/probe fly through on re-run, straight to synth), so the entry skill now re-invokes the graph once before escalating to a human. Two consecutive deaths remain a human problem.
  - **Doctor catches plugin-version drift**: agent/skill definitions load from the plugin cache at session start, and a mid-session cache sync does not update the running session — a 0.48.0-contract analyse-agent ran long after 0.48.2 was installed, reproducing the exact pre-fix failure before we realised why. `quasi-doctor` now compares the version of the copy it runs *from* against `installed_plugins.json` and prints `STALE — restart session` (non-fatal, `plugin-version-drift` in `optional_missing`).
  - Plus narration `log()` lines at the three silent choke points (chapters extracted, OCR fallback taken, author probe tally) and the topic report now states how many corpus items came from vault recall. Guards: doctor drift unit test, plus four new asserts in the post-steps test. Suite 152 green. plugin/marketplace `0.49.0→0.49.1`.

- **0.49.0** (2026-07-25): **the four per-kind skills are retired; `process-material` is the only acquisition→analysis entry.** `process-book` (274 lines), `process-paper` (180), `process-author` (456), and `process-topic` (323) are deleted; `process-material` (~190) covers all four kinds through the one orchestration graph. This ships only now because the goal was never "code exists" but "branches proven": every branch carries E2E evidence — book (recursed in-topic: 23 chapter analyses, 2 book synths, chapter-count reconciliation), paper (OCR fallback chain runtime-validated end-to-end), author (parallel discovery + probe + synth), topic (0.48.2/0.48.3: recall 6/6 seeds, 14/14 corpus wikilinks).
  - **The two post-steps the retired skills owned move into `process-material`.** Paper translation opt-in: `translate: true` → main process dispatches `translate-agent` (slug-only prompt) → `processing/translations/{slug}-zh.pdf`, skipped if the file exists. Author LOCALISE: the graph's author receipt now carries `book_slugs` (a loop needs names, counts can't drive it), and the skill's LOCALISE loop runs `[key]` for a single book or `result.book_slugs` for an author — `localise scan` is ISBN-idempotent, so historical books in the list cost nothing.
  - **`process-material` is promoted**: description rewritten as a routing hint for the four intents; the "experimental, runs alongside" framing, the old-vs-new concurrency warning, the spike caveat (long proven), and the parallel-period closing are all gone. Guard: `test_process_material_carries_the_retired_skills_post_steps` (also asserts "实验" never reappears in the skill).
  - **`superset_agent` dies with `process-topic`** — it existed only for that skill's `superset agents create` cross-session dispatch, the fire-and-forget channel with no receipts whose failure mode (poll-agent guessing completion from vault products) is exactly the bug class this whole cycle fixed. Removed: the `plugin.json#userConfig` entry, the hook's `_SUPERSET_KEYS`/`_SUPERSET_AGENTS_CREATE` branch, the CLAUDE.md table row, and doctor's orchestration probe. A superset command now passes the hook untouched (guard test rewritten accordingly).
  - Docs/scripts cleaned: README skill table, ARCHITECTURE active-skills list, `emit_bib.py`'s new-entry-pending hint (`/quasi:process-book` → `/quasi:process-material`), `scripts/search/context.md`. Dead names added: the four `quasi:process-*` skill ids, `superset agents create`, `QUASI_SUPERSET_AGENT`. Six retired-skill tests deleted, four superset hook tests collapsed into one pass-through guard. Suite 160 → 151, all green. plugin/marketplace `0.48.3→0.49.0`.

- **0.48.3** (2026-07-25): **the topic corpus list carried duplicate paths into the synth contract — probe-collected `vault_slug`s were never checked against works already recalled.** Found by the 0.48.2 topic E2E: the graph-built `synth-topic` prompt listed 16 `analysis_paths`, of which 2 (`star-institutional-ecology-1989`, `star-sorting-things-out-1999`) appeared twice — each was recalled from the vault *and* rediscovered online, and the probe's `vault_slug` receipt re-entered `ok` because `seen` only guards candidate slugs, not resolved vault slugs. `synthesis-agent` deduplicated on its own (`inputs_analyzed: 14`), so no product damage — but the corpus list is data handed to a downstream contract, and conformance is the graph's job, not the consumer's (the standing rule: standardise the shape at the source, don't patch non-conformance downstream). `roundOk` now filters out any slug already in `ok` before entering the corpus or the snowball source. Guard added to `test_orchestrate_topic_recalls_the_vault_before_it_searches_online`. Graph + test only; plugin/marketplace `0.48.2→0.48.3`.
  - **0.48.2 runtime-validated in the same E2E** (same tree and topic desc as the 0.48.1 run, so the two runs are directly comparable). In-graph `recall:*` returned 10 vault-real works **including all 6 seeds** (0.48.1 online discovery surfaced 1); recall and `search-topic:*` started 6ms apart (genuinely parallel); the graph-built synth contract's first 10 `analysis_paths` matched the recall receipt verbatim (the `ok = [...local]` wiring, proven end-to-end); and the regenerated topic pages wikilink **14/14 corpus works, all 6 seeds included** — against 0 vault-backlinks in the 0.48.1 product. md5 full-tree diff: only the two topic pages changed (their `overwrite: true` contract); every pre-existing analysis untouched.
  - **Honest accounting of the run itself**: provider weather (open.bigmodel.cn TLS timeouts, Cloudflare 524s) killed `synth-topic` *and its retryNull retry* in run 1 — the graph did not hang, it returned an honest `synth_failed` — and killed two extract chains in the worker's re-run, which was manually terminated after 1.5h; the killed synth step was completed by re-dispatching the graph-built prompt verbatim from the transcript. The 20–40min invisible harness backoff between a subagent's death and `agent()` seeing `null` is documented in the Debugging gotchas (mtime liveness check; kill + `resumeFromRunId` is the only shortcut). Full evidence in the E2E tree's `E2E-REPORT-0482.md`.

- **0.48.2** (2026-07-25): **`processTopic` searches the vault before it searches the internet — a topic's main corpus is the library the user already built on that topic, and the graph could not see it.** The 0.48.1 topic E2E (Bowker/Star infrastructure, seeded with 6 already-analysed works) finished with a conformant product and zero destructive rewrites, but its biggest content deviation was this: **of the 6 seed works, online discovery surfaced exactly 1** (`star-sorting-things-out-1999`, correctly skipped by the probe's tier-3 title match), and the finished overview + reading list carried **not one `[[wikilink]]` back into the vault** — Bowker appears in the synthesis only as plain prose. The other 5 (`bowker-memory-practices-in-the-sciences-2005`, `bowker-science-on-the-run-1994`, and 3 Bowker papers) were never candidates at all.
  - **The probe can only skip what discovery found.** That is the whole blind spot. `existsProbePrompt` is a *dedup* mechanism, not a *recall* mechanism — it answers "is this candidate already in the vault", never "what's in the vault that belongs here". So an in-vault work the search happens to miss is indistinguishable from one that doesn't exist. The topic branch's premise ("a topic's works are largely already in the library; this run accumulates around them") was never implemented — it was assumed to fall out of dedup, and it doesn't.
  - **Fix**: step 1 of `processTopic` becomes `parallel([recall, discovery])` — two independent questions, no reason to serialise them. `vaultRecallPrompt(desc, max)` asks a `general-purpose` agent for 6–12 bilingual keywords, sweeps `rg -il … vault/books vault/papers` (which prints the hits, so the signal is observable — the rule from 0.44.3), maps paths to real on-disk slugs, confirms each against the product's frontmatter title/themes, and returns `{items:[{kind, slug}]}` under `RECALL_SCHEMA`. Recalled works are already analysed, so they go straight into `ok` (they count as corpus even if not a single round runs) **and** into round 1's snowball source — their `## 核心引用` sections are usually the densest part of the topic's citation network, and dropping them halves the snowball's starting point. `processTopic` now also reports `recalled: N`.
  - Guard test `test_orchestrate_topic_recalls_the_vault_before_it_searches_online` pins all of it (recall exists, runs parallel to discovery, feeds the snowball, seeds `ok`), and `RECALL_SCHEMA` joins the receipt-schema tuple. Suite 159 → 160. Graph + test only; no bin, schema-contract, or agent-contract change. plugin/marketplace `0.48.1→0.48.2`.

- **0.48.1** (2026-07-25): **the paper OCR fallback never fired — its trigger was a regex over free-text prose, so two scanned papers were silently dropped. Fixed at the source: `analyse-agent` now emits a structured `needs_ocr` flag.** Found by the 0.48.0 topic E2E, which is exactly what an E2E is for: the run completed, returned an honest `needs_seeds`, and looked reasonable — but two of its three round-1 items had vanished into `analyse_failed`.
  - **What happened.** Both Star papers (`star-ethnography-of-infrastructure-1999`, `star-institutional-ecology-1989`) are scans. `analyse-agent` behaved perfectly: refused to fill in from training knowledge, returned `status: error`, and wrote `- notes: PDF 文本提取失败(疑似图像/扫描版),需 OCR 或人工处理:…` — **inside the `output` field**, because the receipt's `output` carried the whole `ANALYZE_RESULT:` block verbatim. The receipt's own `notes` field got a *paraphrase*: `PDF 文本提取仅得到期刊元数据、下载页眉页脚,未提取到可读正文;依据真实性约束未生成分析文件。` The 0.46.0 gate tested `/OCR|扫描|图像|scan/i` against `an.notes` only. Zero keyword hits → no `ocr:*` agent was ever spawned → both papers dropped.
  - **Same defect class as 0.44.3 / 0.45.1 / 0.46.0, one layer up.** Those were "the agent has no observable signal to branch on"; this is "the graph branches on a signal the agent was never required to emit in a fixed place." A phrase an agent writes freely is not a control signal — reword it and the caller silently stops catching it. So the fix goes in the contract, not the call site (project rule: standardise the data shape, don't keep patching non-conformance).
  - **Fix.** `agents/analyse-agent.md` requires `needs_ocr: true` alongside `status: error` whenever the PDF has no readable text layer, and its `ANALYZE_RESULT` protocol lists the field; the doc says outright that `needs_ocr` is the *only* structured signal the caller uses to decide on an OCR re-run, and that other failures (missing file, bad path, write failure) leave it false. `AN_SCHEMA` gains `needs_ocr: { type: 'boolean' }`, and the `processPaper` gate becomes `an.needs_ocr === true || /OCR|扫描|图像|scan/i.test(\`${notes} ${output}\`)`. The regex stays as a transition-period fallback over **both** fields and the whole thing is deliberately **fail-open**: a spurious OCR costs a few minutes, a missed one loses an entire paper without a trace.
  - New guard `test_orchestrate_paper_ocr_fallback_reads_a_structured_flag` asserts the schema field, the flag branch, and — specifically — that the notes-only regex is gone; it also asserts the agent contract mentions `needs_ocr`, so the two halves can't drift apart. Suite 158 → 159. Agent-contract + graph + test; no bin, CLI, or schema-contract change. plugin/marketplace `0.48.0→0.48.1`.
  - **Runtime-validated on the paper the 0.48.0 run dropped** (`star-ethnography-of-infrastructure-1999`, 16 pages of 600dpi CCITT bilevel scan, 2,010 chars of text layer — all SAGE cover metadata and a per-page download watermark). A clean-room `router('paper', …)` in an empty tree took the whole chain: first analyse returned `{"status":"error","needs_ocr":true,…}` **with the flag present and true in the StructuredOutput receipt verbatim** → the graph spawned `ocr:*` → `OCR_CHARS=48130` (24× the original text layer) → `analyse-ocr` returned `success` → a conformant 19,991-byte `vault/papers/…md` with the six paper H2s → audit `escalated: []`. 5 agents, 5/5 `started`/`result`, zero deaths, zero `:retry`, 288s. Content authenticity spot-checked verbatim against the OCR'd text: `infrastructural inversion` (Bowker 1994), the nine dimensions (`installed base` / `Embeddedness` / `breakdown` / `ready-to-hand` / `transparent`), `IDENTIFYING MASTER NARRATIVES AND "OTHERS"`, and the `One person's infrastructure is another's topic` line all trace to real OCR'd sentences — nothing filled in from training knowledge.
  - **Deployment gotcha worth remembering**: an agent definition is loaded from the installed plugin cache **at session start**. Re-syncing the cache mid-session does not update the agents already loaded — a same-session dispatch of `quasi:analyse-agent` after the sync still ran the 0.48.0 contract and emitted no `needs_ocr` at all. Validate a contract change in a **fresh** session (that dispatch also reproduced the old failure mode exactly, which is its own corroboration).

- **0.48.0** (2026-07-25): **`process-material` grows the `topic` branch — the graph's four kinds are complete, and the snowball loop is now code instead of an unobservable cross-session dispatch.** `topic` was the last `throw new Error('not implemented')` in `router()`, and it is also the branch that most needed moving: old `skills/process-topic/SKILL.md` (323 lines, 40 mentions of superset/sentinel/poll) drove item processing through `superset agents create`, which is **fire-and-forget — it returns only a `sessionId`, and the current Superset CLI has no transcript / status / logs / result command**. Completion could only be *guessed* from vault artifacts plus agent-written sentinels plus a `poll-agent` loop. That is the same "no observable signal → assume success" class that 0.44.3 / 0.45.1 / 0.46.0 kept re-fixing inside the graph, except here it was structural and unfixable in place.
  - **`processTopic` = loop-until-dry over the existing nodes.** Discovery search → per round: existence probe → `parallel(items → router(kind, …))` → snowball. Every item is `processBook` / `processPaper` — the same functions the book and author E2Es already validated — so the topic branch adds **zero new agents** and exactly one new schema (`REFS_SCHEMA`, spread from `SEARCH_SCHEMA` plus `suggested_queries`). This is the recursion thesis paying off a second time: 0.44.0 stopped `processAuthor` from inlining the book subflow, and `processTopic` reuses `processAuthor` too (opt-in via `meta.allowAuthors`, since one author pulls in 5 books + 10 papers).
  - **`router` gains an `opts` parameter** so a batch-dispatched book carries `batchYear: true`. Without it, one year-ambiguous book inside a topic run bubbles a gate all the way up and stalls the whole batch — the exact policy `processAuthor` already had, now available to any caller that recurses. Guarded by `test_orchestrate_topic_recurses_through_router`, which also asserts `processTopic`'s body contains no `processBook(` / `extractPrompt(` / `analysePrompt(` — re-implementing the subflow is precisely the duplication old `process-author` carried under a "keep naming in sync with process-book" prose contract.
  - **The snowball reads `## 核心引用` from the round's own products**, not the whole analysis — the section exists in every paper/chapter analysis, and the round's items are the only new evidence. Bounded by `maxRounds` (3) and `maxPerRound` (8); the round breaks early when nothing landed, because with no new body text there is nothing to mine references from.
  - **Dead ends bubble to a human gate instead of returning a thin `ok`.** When the queue runs dry below `minItems`, the graph returns `{status:'needs_seeds', collected, suggested_queries}` and the entry skill runs `AskUserQuestion`; the user supplies `meta.seeds` (re-run widened) or `meta.final: true` (synth what we have). The widening hints come from `search-agent`, which knows what it searched.
  - **The probe matters more here than for authors.** An author's works are largely disjoint from the vault; a topic's are largely *already in it* — snowballing a研究领域 surfaces the canonical works first, which is exactly what a reading vault already holds. Every round probes before dispatch, so already-in-vault items fold straight into the synthesis corpus without a download.
  - **`synthesis-agent` gains `analysis_paths`** as an alternative to `analysis_dir`. Topic corpora are scattered across `vault/papers/*.md` and `vault/books/{slug}/00-overview.md` — there is no single directory to glob, and the graph already holds the exact path list. Contract change per the checklist, not a prompt patch at the call site.
  - **Entry skill: `author`/`topic` are accumulating materials.** Step 0's product-exists short-circuit was wrong for both — 0.46.0 deliberately made author synth non-idempotent *so re-runs absorb newly-processed works*, yet Step 0 blocked the re-run outright. Now book/paper stay one-shot (a re-run duplicates) while author/topic report "本次为增量更新" and continue; the in-graph probe makes that cheap (Bowker's second run: 8 agents, zero download/extract).
  - Suite 156 → 158. Graph + skill + one agent contract; no bin, schema-contract, or CLI change. The four old skills stay in place — `process-topic` dispatches `/quasi:process-{paper,book,author}` **by name**, so nothing can be retired until the topic branch has E2E evidence of its own. plugin/marketplace `0.47.2→0.48.0`.

- **0.47.2** (2026-07-25): **`process-material` stops enumerating failure statuses and enumerates the success one instead — `year_mismatch` was falling through into the success report.** Found by auditing whether every status the graph can return actually surfaces at the entry skill. `processBook` re-raises download-agent's `item.status` verbatim (`orchestrate.mjs:92`), so the failure set is defined *outside* `SKILL.md` and grows with the agent contract; the skill gated on `result.status.endswith("_failed") or result.status in ("no_chapters", "no_works", "all_failed")`. `year_mismatch` matches none of those, isn't `year_ambiguous`, and so walked straight past every guard into "成功报告" — **exactly the bug class 0.47.1 fixed for `chapters_incomplete`**, which is what makes enumerate-the-failures the wrong shape rather than an unlucky omission.
  - Fix is directional, not additive: the final guard becomes `if result.status != "ok"`. Fail-closed, and immune to the download-agent enum growing again. The human gate now covers `("year_mismatch", "year_ambiguous")` together — both mean "file downloaded, year doesn't line up, left at `tmp_path` pending a human call", so they were always the same branch.
  - Guard test `test_process_material_reports_any_status_that_is_not_ok` asserts the catch-all exists, that `endswith("_failed")` is gone, and that the year gate covers both statuses. Skill/test only; no graph, schema, bin, or agent-contract change. plugin/marketplace `0.47.1→0.47.2`.

- **0.47.1** (2026-07-24): **`orchestrate.mjs` gains one shared `retryNull` wrapper — a terminal API death in any receipt-reading agent is retried once instead of silently degrading the run.** Both E2E runs of the 0.46.0 features passed, and both surfaced the same root cause: `agent()` returns `null` when a subagent dies on a terminal API error after retries, and every call site interpreted that null as a *content* answer.
  - **Book E2E** (`bowker-memory-practices-2005`, 9 chapters): ch04 died with `API Error: Server error mid-response`, ch07 with `API Error: stream error: stream ID 1; INTERNAL_ERROR`. The 0.46.0 synth reconciliation **worked exactly as designed** — `synth` reported 7 on-disk chapters vs 9 extracted, the refill round fired, ch04 recovered — but ch07's refill agent died *again* (same transient class, 8 minutes apart), and the run correctly returned `{status:"chapters_incomplete", analysed:8, expected:9}` instead of a false `ok`. That is the feature doing its job; the gap is that **one refill round is the only retry**, so a transient blip hitting the same chapter twice ends the run.
  - **Paper E2E** (`bowker-biodiversity-datadiversity-2000`, 42-page scan): the OCR fallback fired correctly (DS OCR2 → Tesseract auto-fallback, 4,392 → 139,788 chars; content-authenticity grep confirmed every key concept in the analysis traces to the OCR'd text — no hallucination). But `analyse-ocr` returned `{"status":"success", "notes":"目标文件已存在且未设置 overwrite,按幂等协议 no-op。"}` **while the file did not exist** — the immediately-following audit reported `target.exists=false` and escalated `missing_file`, and the escalation loop rewrote it. Self-healed by luck, not design. Root cause: `noopIfExists`'s idempotency grant is **semantically wrong on a retry path** — if we're retrying, the prior attempt produced nothing, so the output cannot exist; granting no-op there invites the agent to claim success without writing.
  - **Fix, once, where all callers route through**: `retryNull(prompt, opts, retrySuffix='')` re-dispatches on a null receipt with `:retry` appended to the label. Write-producing agents (analyse / synth) pass `OVERWRITE` so the retry cannot no-op; read-only / command agents (download / extract / audit / probe / ocr / search) pass nothing. Applied to all 14 receipt-reading call sites; the four fire-and-forget `regen-*` escalation calls stay plain `agent()`. The chapter **refill round keeps its idempotency grant on the first attempt** — it re-fans-out *all* chapters and already-done ones should legitimately no-op; only its retry carries `OVERWRITE`.
  - Highest-severity null was `probe-done`: an empty probe receipt makes `doneB`/`doneP` empty → every already-in-vault work counts as fresh → **destructive re-extract**, i.e. the exact 0.44.2 bug the probe exists to prevent. A dead `audit` was the quiet one: `(au && au.escalated) || []` reads as "clean".
  - `skills/process-material/SKILL.md`: the entry skill never handled `chapters_incomplete` — it doesn't end in `_failed` and wasn't in the failure list, so a partial book would have been reported as success. Now reported distinctly with a re-run hint (a re-run only fills the missing chapters; completed ones no-op).
  - **Runtime-validated on the author E2E** (`geoffrey-bowker`, 2026-07-25), which exercised both halves of the contract. A ch06 analyse died on `API Error: An error occurred while processing your request` (`isApiErrorMessage: true`); **20 seconds later the identical prompt was re-dispatched with `\noverwrite: true` appended** — the `retrySuffix`, which nothing but the graph adds — and returned `{status: success, output: …/ch06-….md}`. The author-synth call then died on `Prompt is too long`, retried once, died identically, and the graph gave up correctly: `retryNull` cannot tell a deterministic error from a transient one through a `null`, so it pays exactly one wasted retry — the accepted cost. Useful transcript fact for future debugging: **a dead agent writes no `result` line at all**, so its journal key stays `started`-only forever and the retry shows up as a *new* started+result pair — count `started` vs `result` keys to find deaths; do not look for `result: null`.
  - **The author branch now has full E2E evidence too** (pending since 0.44.0). Two runs of `{kind:"author", name:"geoffrey-bowker", maxBooks:3, maxPapers:2}`: a **clean-room** run against an empty vault took all 5 works through the real pipeline — AA/sci-hub/doi_cascade downloads, extract 13+9+5 chapters, per-chapter analyse, synth reconciled **13/13** and **9/9**, one scanned paper through the OCR fallback (139,788 chars) — and a **second run in the same tree** proved the skip path: the probe returned `match:"slug"` for all 4 already-done works, the graph spawned **8 agents total** (no download / extract / chapter analyse for anything already in the vault), and returned `{status:"ok", books:3, papers:2, book_failures:0, paper_failures:0}` with both audits `escalated: []` and a 20 KB `vault/authors/geoffrey-bowker.md` wikilinking all five works. The 0.44.2 destructive-re-extract regression did not recur.
  - **The 0.47.0 title tier is now proven inside the graph, not just at the bin** (`wf_7d8923ac-93b`, 2026-07-25). Neither author run above could exercise it — one had an empty vault (`match: null` throughout), the other exact slug hits — so tier 3 had shipped on read-only bin evidence alone. Closed by a **slug-drift run**: the clean-room artifacts were renamed into the real vault's shape (`bowker-sorting-things-out-1999` → `star-sorting-things-out-1999`, `bowker-memory-practices-2005` → `bowker-memory-practices-in-the-sciences-2005`, plus one drifted paper slug) and the same author graph re-run. All three books carry **no `isbn`** in frontmatter (`scanned.book.identifiers: 0`), so tiers 1–2 were structurally incapable of hitting them. The probe returned **`match: "title"` ×2** alongside `match: "slug"` ×3, and the graph acted on it: **5 agents total** (search ×2, probe, author synth, audit) — zero download, zero extract, zero chapter analyse. An md5 manifest of all 64 vault/processing files before and after shows **exactly one changed file**, `vault/authors/geoffrey-bowker.md` (the one this run should rewrite); no duplicate directory appeared under either drifted slug. The profile wikilinks the **vault** slugs (`[[star-sorting-things-out-1999/00-overview|…]]`) — direct evidence that `vault_slug`, not the candidate's drifted slug, propagates through `okBooks`/`okPapers` into synth, which reported `inputs_analyzed: 33, chapters_analyzed: 27` from files that exist only under the vault name. `{status:"ok", books:3, papers:2, 0 failures}`, audit `escalated: []`.
  - **E2E harness gotcha worth remembering**: `$CLAUDE_PROJECT_DIR` is fixed at session start, so a `cd` inside a dispatched worker's *prompt* does **not** redirect where the graph writes — the clean-room run above happened because a worker told to `cd` into the user's vault still resolved every relative path against its launch cwd. Dispatch E2E workers with the correct cwd; never rely on an in-prompt `cd`.
  - Graph/skill-only; no schema, bin, or agent-contract change. plugin/marketplace `0.47.0→0.47.1`.

- **0.47.0** (2026-07-24): **`quasi-helpers vault resolve` gains a third match tier — title + author surname — closing the author-branch dedup blind spot for vault entries that carry no ISBN/DOI.** 0.45.0 moved dedup out of prompt-space into a deterministic bin with two tiers (exact product path → ISBN/DOI identifier index). That fixed slug drift *for works that have an identifier in the vault*, but the live 16.9k-file vault has **105 books with no `isbn` and 139 papers with no `doi`** — for those the identifier index can never hit, so every author re-run re-fetches them and creates a duplicate entry under the drifted slug.
  - **Tier 3** (`match: "title"`): a candidate resolves to a vault slug when its normalised title key **uniquely** hits the title index **and** its author surnames intersect the vault entry's. `title_keys()` emits two keys — the full normalised title and the subtitle-stripped stem (`re.split(r"[:：]", …, 1)[0]`) — because a subtitle is routinely present on one side and absent on the other; normalisation lowercases, maps punctuation to space, collapses whitespace, and drops a leading article. `surnames()` handles both `Bowker, Geoffrey C.` and `Geoffrey C. Bowker` (and `van Dijck, José` / `José van Dijck`) → `{bowker}` / `{dijck}`. Year is deliberately **not** required — the Fourcade case drifts 2009↔2010.
  - **Fails closed by construction.** The asymmetry is the whole design: a false positive silently *drops* an unprocessed work; a false negative merely creates a visible, mergeable duplicate. So an ambiguous title key (>1 vault entry) refuses to match rather than guessing, and a **stem↔stem** match is rejected outright — both titles having *different* subtitles is the multi-volume shape (`Musik und Mathematik. Band 1: Hellas. Teil 2: Eros` vs `… Aphrodite`), where collapsing them would lose a volume. A vault sweep found 3 such stem collisions among 806 subtitled books, 2 of them genuine multi-volume works.
  - **Validated against the live vault by self-consistency sweep**: every vault record fed back as a slug-drifted candidate carrying only `title` + `authors` — **1125 books + 2262 papers resolved to themselves, 0 false positives**, 158 conservative refusals (duplicate-title works). Real-case checks: `abbott-masking-pandemic-2022` → `abbott-masking-in-the-pandemic-2023` (`match:"title"`, no ISBN either side), a wrong-author candidate with an identical title refused, and the Kittler multi-volume candidate refused. Full both-index scan of 1037+2157 identifiers and 1930+3588 title keys takes ~1.7s.
  - `_index()` now builds both indexes in **one** vault pass and returns `(idents, titles)`; `scanned` becomes `{kind: {identifiers, titles}}`. Laziness preserved: an item with neither a usable identifier nor title+authors still triggers no scan at all.
  - Callers updated so the tier can actually fire: `orchestrate.mjs::existsProbePrompt` now sends `title`/`authors` per candidate (the author-branch probe), and `skills/process-material/SKILL.md` Step 0 passes them too. `tests/test_vault_resolve.py` grows 6 cases (title drift, subtitle drift, ambiguous refusal, surname-mismatch refusal, stem↔stem refusal, identifier-beats-title, title-without-authors skips the scan); suite 147 → 154. Additive CLI surface; no schema-contract change. plugin/marketplace `0.46.0→0.47.0`.

- **0.46.0** (2026-07-24): **`process-material` stops reporting `ok` on silently incomplete work — the graph now reads the analyse/synth receipts it branches on, and paper acquisition grows an OCR fallback.** 0.45.1 fixed the *cause* of the Bowker chapter loss (unobservable existence check); this release fixes the *detection* gap that let it through as `book_failures: 0`, plus the two other module holes the same run exposed. All three trace to one root: `orchestrate.mjs` line 26 deliberately attached schemas only to download/extract/audit, so analyse and synth receipts came back as prose and every field read as `undefined`.
  - **Chapter completeness reconciliation.** `synthesis-agent` (mode=book) Globs `{output_dir}/ch*.md` itself and honestly reports `chapters_analyzed: N` — i.e. an *independent* count taken from disk, unlike the self-reported `status: success` that lied. New `SY_SCHEMA` makes the graph read it; `processBook` compares against `chapters.length` from the extract receipt, and on a shortfall re-fans-out the chapter analyses (the 0.45.1 idempotent prompt means only the missing ones write) then re-synths. Still short → returns `{status:'chapters_incomplete', analysed, expected}` instead of `ok`, which also makes it count as a `book_failure` inside `processAuthor`. Missing/unparseable `chapters_analyzed` coerces to 0 (`analysedCount`) — reconciliation fails **closed**, since a spurious repair round is cheap (all chapters no-op) and a spurious pass is the bug being fixed.
  - **Book and author synth stop being idempotent** (`overwrite: true`, `noopIfExists` dropped at those two sites). Two reasons: a no-op synth returns a stale `chapters_analyzed` and defeats the reconciliation above; and an author profile that no-ops when `vault/authors/{name}.md` exists can never absorb newly-processed works on a re-run (backlog issue 4). Chapter and paper analyse keep `noopIfExists` — they're the expensive per-input work and their outputs are genuinely terminal. Guard test relaxed `>= 4` → `>= 2` accordingly.
  - **Paper OCR fallback.** `analyse-agent` already returns `status: error` + "疑似图像/扫描版,需 OCR" for a PDF with no text layer, and is explicitly forbidden from filling in from training knowledge — but `processPaper` never read that receipt, so a scanned paper just produced nothing (`bowker-biodiversity-datadiversity-2000`). New `AN_SCHEMA` + a fallback branch: OCR to `.quasi/temp/{slug}.ocr.pdf` via a `general-purpose` agent running `quasi-extract ocr` (same shape as the existence probe — the command prints `OCR_CHARS=N` so the agent has an observable signal rather than an exit code), then re-analyse against the OCR'd PDF. ≥500 chars counts as usable.
  - **Null receipt = agent death, not content failure.** `agent()` returns `null` when a subagent dies on a terminal API error after retries (Bowker's first paper analyse died with `Connection closed mid-response`). Paper analyse retries once on `null`; book chapters need no special case — a dead chapter agent leaves no file and the synth reconciliation catches it. Author synth now also reads its receipt and returns `synth_failed` rather than auditing a file that was never written.
  - New tests: `test_orchestrate_reads_every_receipt_it_branches_on` (every `*_SCHEMA` is both defined **and** attached to an `agent()` call — the invariant 0.43.0 shipped without) and `test_orchestrate_book_reconciles_chapter_count_before_reporting_ok`. Graph + test only; no schema-contract, bin, or agent-contract change. plugin/marketplace `0.45.1→0.46.0`.

- **0.45.1** (2026-07-24): **the 0.44.3 "bare `test` has no observable signal" bug had four more call sites in `orchestrate.mjs` — analyse agents reported `success` without ever writing their file.** 0.44.3 fixed exactly this defect in the existence *probe* and even left a comment naming it, but the fix stopped at that one call site. The other four prompts (chapter analyse, book synth, paper analyse, author synth) still ended with a bare `若 output 已存在且未设 overwrite,直接 no-op 返回 success。` — no way for the agent to *observe* existence. It runs `test -e <output>`, the harness surfaces `(no output), is_error:false` whether the file exists or not, so the agent concludes "exists" and returns success having written nothing.
  - Caught by the Bowker author E2E against the live vault: **all 9 chapter-analyse agents returned `status: success`; only 2 chapters actually landed on disk.** Seven agents made a single `test -e` Bash call and returned. `book synth` then read what was really there (`inputs_analyzed: 2`) and built `00-overview.md` from 2 of 9 chapters — while the graph reported `book_failures: 0`. Silent partial output, not a crash.
  - Fix: one `noopIfExists(output)` helper emitting `test -e <output> && echo EXISTS || echo MISSING` plus an explicit "没写文件却返回 success 是错误", used by all four prompts. The permission to no-op is now granted in exactly one place, and that place always prints a signal. New guard `test_orchestrate_noop_permission_always_carries_an_observable_exists_check` asserts the invariant (one grant site, contains `echo MISSING`, ≥4 call sites) so the next prompt can't reintroduce it.
  - Same run **confirmed 0.45.0's identifier dedup on real data**: `bowker-sorting-things-out-1999` resolved to `star-sorting-things-out-1999` (`match:"isbn"` — his books are filed under Star), no duplicate directory, and the existing Star book + its `processing/chapters/` were left untouched. Graph/test-only; no schema-contract change. plugin/marketplace `0.45.0→0.45.1`.
  - **Surfaced (not fixed here — backlog): (a) identifier dedup is blind where the vault entry has no identifier** — 9% of books carry no `isbn`, 7% of papers no `doi` (e.g. `star-social-science-technical-systems-2014`), so a drifted slug for those still creates a duplicate; closing it needs a title+year tier. **(b) paper analyse has no OCR fallback** — a scanned-PDF paper (`bowker-biodiversity-datadiversity-2000`) downloaded fine but analyse could not extract text, while the book path would have routed it through `quasi-extract ocr`.

- **0.45.0** (2026-07-24): **new `quasi-helpers vault resolve` — identifier-level dedup fixes the 0.44.3 backlog issue 1 (search-slug drift breaks author idempotency).** The 0.44.3 probe was *correct* but only did exact-path matching, so the Fourcade case it surfaced stayed broken: the vault holds `fourcade-economists-societies-2009` while discovery generates `fourcade-economists-and-societies-2010` for the **same book** (connector word + year drift) — an exact-path check calls that "not done" and a re-run creates a duplicate. Slug is an LLM-generated display key and will always drift; the stable identity is the ISBN/DOI already present in both the search receipt and the vault frontmatter. So the check moves out of prompt-space into a deterministic bin:
  - New `scripts/vault/resolve.py` + `quasi-helpers vault resolve` (read-only): takes `[{kind, slug, isbn?, doi?}]` on `--items-json` or `--items-file` (`-` = stdin, safer for titles with apostrophes) and returns `{resolved:[{kind, slug, vault_slug, path, match}]}`. Two-tier match: **exact product path** (`match:"slug"`) → **identifier** (`match:"isbn"|"doi"`), where the identifier index is built from vault frontmatter and returns the **vault's real slug**. Reuses `localise.normalise_isbn` (ISBN-10→13) and adds `normalise_doi` (lowercase, strips `doi.org/` / `doi:` prefixes). The index is built lazily — a candidate with no identifier never triggers a vault scan. Book and paper indexes stay separate, so a book ISBN can't resolve against a paper.
  - `orchestrate.mjs`: `existsProbePrompt`'s inline `python3` heredoc collapses into one bin call; `PROBE_SCHEMA` becomes `{resolved:[{kind, slug, vault_slug, match}]}`; `processAuthor`'s `doneB`/`doneP` become `Map<candidate_slug, vault_slug>` and `okBooks`/`okPapers` now carry the **vault** slug, so author synth reads the file that actually exists instead of the drifted name.
  - `skills/process-material/SKILL.md` Step 0 uses the same bin for book/paper (author has no identifier and keeps the product-path check); `rg` fuzzy recall demotes to the no-identifier fallback. Same fix, all three callers.
  - Verified against the live 16.9k-file vault: the drifted `fourcade-economists-and-societies-2010` + hyphenated ISBN-13 resolves to `fourcade-economists-societies-2009` (`match:"isbn"`), an uppercase `https://doi.org/10.1016/J.AOS…` DOI resolves to the right paper, bogus identifiers return `null`, full scan of 1037 books + 2156 papers takes ~2.5s. New `tests/test_vault_resolve.py` (8 cases) covers exact/ISBN-drift/ISBN-10/DOI-prefix/miss/no-scan/index-separation/bad-kind. Additive CLI surface; no schema-contract change. plugin/marketplace `0.44.3→0.45.0`.

- **0.44.3** (2026-07-24): **root-cause fix for the 0.44.2 existence probe — it false-positived every candidate as "done".** The Fourcade author E2E (`marion-fourcade`, `maxBooks:2 maxPapers:2`) returned `{status:ok, books:2, papers:2, 0 failures}` with the vault left **git-clean** (no destructive re-extract) — but an adversarial read of the run showed the probe was **wrong, just safe-by-accident**: it reported all 4 discovered works as `*_done` when 2 of them (`fourcade-economists-and-societies-2010`, `fourcade-cents-sensibility-2011`) don't exist at that exact path. Root cause: `existsProbePrompt` told the agent to run `test -f` per slug, but a bare `test -f` prints nothing on success **or** failure, and the harness surfaces the tool result as `(Bash completed with no output), is_error:false` either way — so the agent had **no observable signal** to distinguish exist from not-exist and defaulted to "all present." Over-skip was harmless this run (the drifted slugs happened to get skipped, so no duplicates and no re-extract), but the same false-positive would silently **drop a genuinely-unprocessed work** from a batch. Fix: the probe command now computes the answer itself and prints one line of JSON (`python3 … os.path.isfile … print(json.dumps(...))`); the agent just relays that JSON. Verified against the live vault — a real slug resolves `True`, a drifted one `False`. Graph-only; no schema/agent-contract change. plugin/marketplace `0.44.2→0.44.3`.
  - **Surfaced (not fixed here — backlog issue 1): search-slug drift breaks author idempotency.** The vault holds `fourcade-economists-societies-2009`; the discovery search generated `fourcade-economists-and-societies-2010` (connector word + year drift) for the *same book*. With the corrected probe, an exact-path check can't recognise that as already-done → a re-run would fetch and create a **duplicate** under the drifted slug. The probe (exact-slug match) is the right fix for "same slug already done"; catching "same work, different slug" needs identifier-level (ISBN/DOI) dedup and is the next author-branch task.

- **0.44.2** (2026-07-24): **`processAuthor` skips already-in-vault works, `make_slug` stops truncating mid-word, and the two author searches run in parallel — three fixes from the first author E2E.** The bounded author run (`jussi-parikka`, 1 book + 2 papers) came back `{status:ok, books:1, papers:2, 0 failures}` but surfaced three issues, all fixed here:
  - **`processAuthor` re-ran `processBook` on books already in the vault** → `extract-agent` destructively re-extracted an existing book (deleting the `ch0N-*.txt` and rewriting `processing/chapters/{slug}/manifest.json`), because a pre-0.43.3 manifest lacked `slug` and the schema now requires it. Root cause: the batch had no "already done → skip" short-circuit, and the graph has no filesystem to check existence itself. Fix: one `general-purpose` **existence probe** agent per author run (`existsProbePrompt` + `PROBE_SCHEMA`) `test -f`s every candidate's product path (`vault/books/{slug}/00-overview.md` / `vault/papers/{slug}.md`) once; `processAuthor` then processes only the not-done set (`freshBooks`/`freshPapers`) and folds the already-done slugs straight into `okBooks`/`okPapers` so they still feed the author synth. Standalone `book`/`paper` entry stays covered by the entry skill's Step 0 recall; only the batch (author, later topic) needs the probe. No shared-agent contract change — the probe lives entirely in `orchestrate.mjs`.
  - **`make_slug` hard-cut the slug at 60 chars mid-word** (`…methodologies-for-reme`), which — combined with the re-extract above — even produced a *second* `ch07-…-for-reme.md` alongside the original. `scripts/extract/toc_utils.py` now truncates at the last hyphen inside 60 chars (`slug[:60].rsplit('-', 1)[0]`), falling back to a hard cut only for a single >60-char word. `test_extract_cli.py` still green; verified the Parikka ch07 title now slugs to `…methodologies-for` (whole word).
  - **The two author discovery searches (book, paper) ran as two sequential `await`s** — now a single `parallel([...])`, so paper discovery no longer waits on book discovery.
  - Instruction/graph/script-only; no schema-contract change, no shared-agent change. plugin/marketplace `0.44.1→0.44.2`.

- **0.44.1** (2026-07-24): **`processAuthor` gains `meta.maxBooks` / `meta.maxPapers` scope bounds.** A full author run (up to 5 books × full `processBook` + 10 papers) can take hours; the override lets a caller — or a bounded E2E test — cap the representative-work set (defaults stay 5/10, candidates sliced accordingly). No other behaviour change. plugin/marketplace `0.44.0→0.44.1`.

- **0.44.0** (2026-07-24): **`process-material` grows the `paper` and `author` branches — the recursive graph pays off.** Adds `processPaper` (download → analyse type B → audit) and `processAuthor` (search books+papers → `parallel(books→processBook + papers→processPaper)` → synth(author) → audit) to `orchestrate.mjs`; the router now handles book/paper/author (topic still throws "not implemented").
  - `processAuthor` **reuses the E2E-validated `processBook`** instead of re-implementing the book subflow — eliminating the duplication the old `process-author` carried (it inlined extract→analyse→synth under a "keep naming in sync with process-book" prose contract). This is the recursive-graph thesis realised: one book node, called N times.
  - Book year-ambiguity in the author **batch** does NOT pause: `processBook(…, {batchYear:true})` tells download-agent to auto-accept + attach `year_evidence` as a warning (mirrors old process-author batch policy), vs the standalone single-book gate-return. New `SEARCH_SCHEMA` validates the author-discovery `candidates[]` (each needs a canonical slug); the script-read receipts (download/audit/search) carry schemas, analyse/synth don't (§5 rule).
  - Entry SKILL is now kind-aware (book/paper/author recall + product paths + marple; LOCALISE stays book-only, author's per-book localise deferred). Syntax-checked; **author E2E validation still pending** (book was validated in 0.43.3/0.43.4). talk/draft stay out of the graph; topic is the last branch. plugin/marketplace `0.43.4→0.44.0`. No schema-contract change.

- **0.43.4** (2026-07-24): **`process-material` entry skill gains Step 0 local recall + LOCALISE, bringing the book pipeline to parity with `process-book`.** The v0 entry skill was a thin wrapper (parse → Workflow → gate → marple); it delegated the acquisition→analysis spine to the graph but omitted the two main-process-facing steps the graph structurally can't do (the Workflow script has no filesystem and can't call bins):
  - **Step 0 local recall/dedup** (before dispatch): if `vault/books/{slug}/00-overview.md` exists → skip the whole run; else an rg fuzzy recall over vault/sources/processing surfaces near-duplicate slugs so a title/year drift doesn't silently reprocess an existing book.
  - **Step 6 LOCALISE** (after `ok`): `quasi-helpers localise scan`, and if pending, a `search-agent` dispatch for `localisations.zh.candidates` → `quasi-helpers localise write` into `.quasi/localise/cndouban.json` (idempotent by original ISBN) — identical to `process-book` Step 6.
  These stay in the main process by design (recall needs judgment; localise calls bins); the graph keeps only the spine. marple-open (already present) is documented as the final entry step. Skill-only change; no graph/script/schema change. plugin/marketplace `0.43.3→0.43.4`.

- **0.43.3** (2026-07-24): **root-cause fix for `process-material` chapter identity — deterministic slug at the extract layer, replacing the 0.43.1/0.43.2 consumer-side patching.** The chapter output slug was invented by the LLM (analyse-agent) per run, so it was both non-conformant (sometimes `chNN-`/`00a-` prefixed → double-prefix) and **non-deterministic** (a different slug each run → the output path changed → **resume was NOT idempotent**, re-runs rewrote duplicate files). `chFilename`'s regex-stripping (0.43.2) patched the prefix but could never fix the instability, and still missed bare lettered-slot prefixes (`ch00a-00a-`). Fixed at the source, per the design's own rule (standardize + validate the data shape, don't patch the consumer):
  - New deterministic `toc_utils.make_slug(slot, title)` — strips the chapter-number prefix (Chapter N / 第N章 / N. / CH N) via the existing `CHAPTER_PATTERNS`, slugifies the rest (CJK-preserving, lowercase-hyphen, 60-char cap) into a **bare, prefix-free** slug; falls back to the full title when only a chapter number is present.
  - `split_chapters.py::create_manifest` and `process_epub.py` both now write `slug` into every `manifest.json` chapter, so chapter identity is born once, deterministically, in the extract script (not by an LLM). `EX_SCHEMA` already requires `slug` (receipt shape validated); `extractPrompt` now tells extract-agent to relay the manifest chapters verbatim without modifying slug. `orchestrate.mjs` uses `ch${slot}-${ch.slug}.md` directly and **deletes the entire `chFilename` helper**.
  - Restores resume idempotency (stable filename across runs → agents no-op on re-run; validated out-of-band as an 8/8-mtime-identical no-op) and eliminates all double-prefixing including lettered slots. Old `process-book`/`process-author` are unaffected (additive field; they still self-slugify) and gain a deterministic slug when they later adopt it. `test_extract_cli.py` asserts the manifest slug. plugin/marketplace `0.43.2→0.43.3`. No schema-contract change.

- **0.43.2** (2026-07-24): **fix `process-material` doubled chapter filenames.** extract-agent's receipt `slug` already carries a `chNN-` prefix for chapters whose title starts with "Chapter N" (it slugifies "Chapter 1" → "ch01"), so `orchestrate.mjs`'s `ch${slot}-${slug}.md` template double-prefixed them → `ch01-ch01-from-oscillation-….md` (intro/conclusion titles, lacking "Chapter N", came out clean, which is why the first smoke's file-count check missed it). New `chFilename(ch)` helper strips a leading `chNN-` from the slug before applying the slot prefix; both the analyse output path and the audit-escalation matcher route through it (DRY). Found via a real-download E2E: `greenspan-wireless-undertow-2023` (genuine Anna's Archive fetch, 11.6 MB PDF, 7 chapters, `status:ok`, audit clean, 10m39s) — so the real download cascade + year triage (verdict MATCH) are now validated as well. Still untested: the year_mismatch/ambiguous gate-return branch (the year genuinely matched, so it never fired). plugin/marketplace `0.43.1→0.43.2`. No schema-contract change.

- **0.43.1** (2026-07-24): **fix `process-material` receipts — 0.43.0's `orchestrate.mjs` passed no `schema` to its `agent()` calls, so receipts came back as prose strings and `dl.per_item` / `ex.chapters` / `au.escalated` were undefined → the graph always returned `download_failed` at the first step.** Adds `DL_SCHEMA` / `EX_SCHEMA` / `AU_SCHEMA` to the three receipt-reading calls (download / extract / audit); analyse & synth receipts are not read by the script and stay schema-less. This is the design's own rule (§5: control signals travel as schema-validated receipts) applied — 0.43.0 shipped without it.
  - Validated end-to-end via an Orca-dispatched worker running in a real vault: `parikka-media-archaeology-2012` (*What is Media Archaeology?*, 8 chapters, pre-existing source). First run failed in ~8s at download (undefined `per_item`); after the schema patch the same run completed in 482s with `{status:"ok", year_warning:null}` — extract returned a populated `chapters[]` (8 = 8 vault `ch*.md`), all 12 agents succeeded, audit passed with zero escalations, `agentType:'quasi:*'` resolved inside the Workflow.
  - plugin/marketplace `0.43.0→0.43.1`. No schema-contract change.

- **0.43.0** (2026-07-24): **experimental `process-material` unified-orchestration skill — new/old parallel, no old skill removed.** First step of collapsing the acquisition→analysis spine (paper/book/author/topic) into one deterministic orchestration graph, now that the harness lifts the old "subagents can't dispatch subagents" constraint (nesting + the Workflow tool for deterministic JS orchestration).
  - New `skills/process-material/SKILL.md` (thin entry, **explicit-invoke only** so it does not compete with the per-kind skills' auto-routing) + `skills/process-material/orchestrate.mjs` (a Workflow script: `router(kind)` recursive graph; **v0 implements `processBook` only**; paper/author/topic throw "not implemented").
  - Orchestration moves into the Workflow: the `while Glob sleep` polling disappears, fan-out/skip/escalation become code, `author` no longer inlines the book subflow (it calls `processBook`), and `topic`'s cross-session `superset agents create` dispatch can become in-process `pipeline(items)`. Substrate (bins/agents/hooks/schemas) is untouched; the graph starts existing agents via `agentType:'quasi:*'`.
  - Handoff: the Workflow script has no filesystem access, so it holds only the small `agent()` receipts; product content stays in files and downstream agents read them by path; resume is agent idempotency (no-op if output exists), NOT Workflow's own resume; human gates (book year-triage / topic dead-end) bubble a `{status}` object up to the entry skill, which does the `AskUserQuestion`.
  - Spike validated: `agentType:'quasi:audit-agent'` resolves to the tool-restricted agent (Read/Edit/Bash) inside a Workflow and reaches the `quasi-*` bins — the agentType approach holds, no inline-prompt fallback needed.
  - **talk / draft stay out of the graph** (different primitives / interactive review). Retirement order once proven: book → retire process-book, then author, then topic. Full design in `docs/process-material-design.md`.
  - No schema-contract change; purely additive. plugin/marketplace `0.42.4→0.43.0`.

- **0.42.4** (2026-07-19): **restore the previous chapter frontmatter contract after 0.42.3.**
  - `ChapterSchema` again rejects `doi` as an unsupported extra field; the schema contract returns from `0.7.1` to `0.7.0`.
  - Removes the stale chapter DOI allowance from the SPEC and restores the rejection regression test. Chapter-specific DOI values should be handled in vault data rather than by expanding the global schema.
  - Supersedes 0.42.3; plugin/marketplace `0.42.3→0.42.4`.

- **0.42.3** (2026-07-19): **temporarily added optional chapter DOI support (superseded by 0.42.4).**
  - Restored the shared `DOI` primitive to `ChapterSchema` and raised the schema contract to `0.7.1`; reverted in the following release to keep the global schema stable.

- **0.42.2** (2026-06-25): **Cell Press EZProxy acquisition prioritises the working `showPdf` path and stops misclassifying publisher challenges as expired cookies.**
  - Cell candidate order now preserves raw PII and tries `https://www.cell.com/action/showPdf?pii=<raw-PII>` before `/pdf/<raw-PII>.pdf`; raw PII is URL-encoded only when embedded in a URL, while ScienceDirect candidates use the normalized PII.
  - EZProxy wraps non-proxied Cell candidates with `{login_url}{candidate_url}`, matching the working CookieCloud path observed for `S1364-6613(26)00108-7`; PDF acceptance now also honours `Content-Type: application/pdf`.
  - Cloudflare / publisher challenge markers (`server: cloudflare`, `cf-ray`, `Just a moment`, `cf-chl`) no longer raise `EZProxyCookieExpired`; only the EZProxy login host or Shibboleth pages do.
  - If Cell / ScienceDirect article HTML is reachable but PDF is blocked, `paper fetch` can save an article-like `.txt` fallback after title/structure checks. Tests cover raw-vs-normalized PII, showPdf ordering, EZProxy wrapping, challenge classification, and text fallback. No schema-contract change; plugin/marketplace `0.42.1→0.42.2`.

- **0.42.1** (2026-06-25): **`quasi-download paper fetch` expands Cell Press / ScienceDirect article URLs before the DOI cascade.**
  - Cell Press fulltext URLs such as `cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7` now expand into the Cell `/pdf/...pdf`, Cell `/action/showPdf?pii=...`, and normalized ScienceDirect `/science/article/pii/...` variants before falling through to OA/Sci-Hub/EZProxy/Wayback.
  - If the caller provides only a Cell URL, quasi resolves the PII through Crossref `alternative-id` and continues with the canonical DOI; the reported example resolves to `10.1016/j.tics.2026.05.002`.
  - EZProxy now retries Cell / ScienceDirect hint URLs through the configured proxy and follows `citation_pdf_url` discovered on those pages. Direct unauthenticated live probes still get publisher 403s without EZProxy, but the resolver path is now adapted for the domain.
  - Tests: `test_download_cli.py` adds Cell fulltext expansion, ScienceDirect PDF variants, PII→DOI, and fetch-order regression coverage. No schema-contract change; plugin/marketplace `0.42.0→0.42.1`.

- **0.42.0** (2026-06-21): **`quasi-extract ocr` defaults to DeepSeek-OCR-2 (QUA-236).**
  DS OCR2 produces far cleaner long text on scanned books — full-book MacKenzie
  (484p) de-hyphenation: 2230 → 140 broken tokens (94% reduction vs the IA text
  layer quasi ingests). Tesseract is retained as an automatic fallback.
  - New `scripts/extract/ocr_dsocr2.py`: renders pages (PyMuPDF), one
    `uvx mlx-vlm==0.3.12` subprocess loads the model ONCE and OCRs all pages,
    writes a text-layer PDF (one page/input page) so `split` is unchanged. mlx-vlm
    pinned to 0.3.12 (0.4+ broke this model: processor load + generate
    `stopping_criteria`); load magic = `import mlx_vlm.generate`. uvx `--with
    torch/torchvision/addict/einops/matplotlib/tqdm` (model remote-code imports,
    load-time only). Fail-soft on missing uvx/model/non-Apple-Silicon.
  - `scripts/extract/extract.py`: `--engine dsocr2|tesseract` (default `dsocr2`),
    auto-fallback to `ocr_pdf.sh`. `agents/extract-agent.md`: wired the OCR→re-split
    loop (was a dead-end that only reported "需 OCR"). bin/README/ARCHITECTURE,
    CLAUDE+AGENTS, plugin/marketplace `0.41.2→0.42.0`, 4 new tests.
  - Install for DS OCR2: ensure `mlx-community/DeepSeek-OCR-2-bf16` is in the HF
    cache, set `QUASI_DSOCR2_MODEL` (optional; defaults to the repo id).

- **0.41.2** (2026-06-19): **Anna's Archive mirror discovery hardens against domain and TLS churn.**
  - `scripts/download/aa.py` now treats the current official domains as a static
    first tier (`annas-archive.pk`, `.gd`, `.gl`) and falls back to the
    Wikipedia infobox URL list when all static mirrors fail. The dynamic list is
    cached under `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/aa-mirrors.json` for 90
    days so normal runs stay deterministic and do not depend on Wikipedia.
  - AA HTML search, Fast Download API calls, and AA file streams use the shared
    AA HTTP helper, which prefers `curl_cffi`'s Chrome TLS impersonation. This
    avoids macOS system-Python LibreSSL failures observed against the 2026 AA
    mirrors before HTTP starts.
  - Legacy AA metadata sweep defaults are reordered to match the current static
    mirror list, and `test_download_cli.py` guards both the official-domain list
    and the Wikipedia recovery parser. No schema-contract change.

- **0.41.1** (2026-06-14): **process-talk gains local single-recording media
  compression.**
  - New `quasi-helpers talk compress-media --media F --output O` wraps a small
    deterministic `ffmpeg`/`libx265` helper for one talk recording at a time,
    matching the normal process-talk flow where the source recording often
    lives outside `vault/talks`.
  - `quasi:process-talk` now compresses video inputs locally to
    `vault/talks/{slug}/recording.mp4` before transcription and then uses that
    path for the rest of the workflow. Audio-only inputs skip compression.
  - No schema-contract change; plugin manifest / marketplace versions are
    bumped to `0.41.1`.

- **0.41.0** (2026-06-11): **image schema gains descriptive metadata fields (schema contract 0.6.0 → 0.7.0).**
  - `ImageSchema` now accepts optional `creator`, `date`, `source`, `themes`,
    `topics`, and `rating` alongside the existing required `type` / `title`, so
    local image objects can carry human-curated descriptive metadata without
    overloading the body.
  - Technical image facts (width, height, format, file size) remain explicitly
    path/indexer-derived from `vault/images/<slug>/original.<ext>` and must not
    be persisted in frontmatter (QUA-175).
  - `SPEC.md` §3.8 documents the expanded frontmatter shape and the plugin
    manifest / marketplace versions are bumped to `0.41.0`.

- **0.40.1** (2026-06-09): **punctuation autofix guards `!`/`?` inside Latin
  names.** A 5-agent adversarial review of the 0.40.0 dry-run over the live
  16.9k-file vault confirmed colons, commas, semicolons, parens, and masking
  (code/inline-code/links/wikilinks/frontmatter/`$…$` math) all clean — zero
  false positives (one reviewer independently reimplemented the masking and
  reproduced the change set exactly). It surfaced **one real bug class**: a
  proper noun whose spelling ends in `!`/`?` glued onto Han text
  (`Yahoo!目录`, `Spacewar!`, `Earth First!`, `Dans le Noir?黑暗餐厅`) had its
  mark "corrected" to full-width — 33 such corruptions across the vault.
  - Fix: `_is_ascii_alpha` guard in `_punctuation_replacements` — for `!`/`?`
    (`LATIN_TOKEN_PUNCT`), skip when an ASCII letter sits immediately before the
    mark and CJK immediately after (Latin-token-then-mark-then-CJK = the name
    pattern). The mirror direction (CJK-then-mark-then-Latin) is deliberately
    NOT guarded: `…会发生什么变化?Baldwin…` is a Chinese question whose next
    sentence merely starts with a Latin name — a sentence boundary, not a name.
    The first patch guarded both directions and wrongly killed ~19 such
    legitimate questions; re-running the dry-run caught it, and the guard was
    narrowed to one direction. Known residual: the `!Kung` click consonant
    (1 occurrence) still converts — accepted over re-killing real questions.
  - Two nested-paren cases (`(它们是世界的物质(再)配置)`) convert the inner CJK
    pair but leave the outer half-width — cosmetic incomplete conversion, not
    corruption; left as a known limitation.
  - `test_audit_punctuation_style_makes_cjk_halfwidth_full_width` extended with
    `Yahoo!目录` / `Spacewar!` / `Dans le Noir?` (unchanged) and a real Chinese
    question before a Latin name (still converts). Full suite 117 pass.
  - No schema-contract change. Vault not yet swept.

- **0.40.0** (2026-06-09): **audit gains a CJK half-width→full-width
  punctuation autofix pass.** Mirrors the existing quote-style pass in
  `scripts/audit/audit.py`: a new `_run_punctuation_autofix` runs right after
  `_run_quote_style_autofix`, over the same `_mask_markdown_non_body` /
  `_split_frontmatter_text` machinery, so code fences, inline code, link
  targets, `[[wikilink]]`, and frontmatter are never touched.
  - **Scope** (`CJK_PUNCT_INLINE` + `PAREN_PAIR_RE`): inline `, : ; ! ?` →
    `，：；！？` convert only when a CJK char sits immediately on either side;
    parentheses convert as a pair (`(…)` → `（…）`) only when the content
    contains CJK. Each replacement is one-char-for-one-char, so body offsets
    stay stable and before/after sentence contexts are read by index.
    Diagnostics: `id: punctuation.cjk_halfwidth`, `pass: punctuation_style`,
    `status: auto_fixed`, `action: none`; counted under
    `fix_counts.punctuation_style`.
  - **Period (`.`) deliberately excluded.** A read-only dry-run over the live
    16.9k-file vault produced 108,239 changes across 5,438 files with zero
    false positives on the inline+paren set — digit-flanked colons
    (`ISO 9000:1987`, `6:54`, `Foucault 2008:63`), English/digit-only parens
    (`(relational model)`, `(2011-12 IPO)`, `(1)`), and masked code/links all
    correctly preserved. The only `.→。` hits (58) were bibliography
    line-endings (`*活力物质*. 西北大学出版社.`), where converting the terminal
    dot but not the title-separator dot makes the entry mix `. … 。`. So the
    period rule is omitted entirely.
  - `agents/audit-agent.md` core-principle line extended to name CJK
    punctuation alongside quote style as body-only typography.
  - Tests: `test_audit_cli.py::test_audit_punctuation_style_makes_cjk_halfwidth_full_width`
    asserts the positive conversions plus the must-not-touch cases
    (digit-flanked colon, English-only parens, inline-code/link masking, no
    period rewrite). Full suite 117 pass.
  - No schema-contract change.

- **0.39.1** (2026-06-08): **process-topic delegated prompts explicitly forbid branch/worktree switching.**
  - Every `superset agents create --prompt` example in `skills/process-topic/SKILL.md`
    now begins with the vault/content-processing preface: this is not a software
    development task; do not create, enter, or switch git branches/worktrees; do
    not run `git worktree`, `git switch`, or `git checkout`; if isolation seems
    necessary, stop and report cwd + branch instead. This prevents delegated
    process-paper/book/author/synthesis/audit agents from misrouting content work
    into development-branch completion flows.
  - The old live maintainer smoke script under `skills/process-topic/` is removed
    from the active skill tree; the runtime contract is now guarded by
    `test_skill_orchestration.py` instead.
  - No schema-contract change; instruction/test-only release.

- **0.39.0** (2026-06-06): **process-topic Superset dispatch moves from the
  removed `agents run` to `agents create`, plus prompt-file transport,
  completion sentinels, and update-safe completion polling (QUA-187).**
  - Current Superset CLI (0.2.x) exposes only `agents create` / `agents list`
    (and `terminals create`); there is **no `agents run`** (it errors
    `Unknown command: run`) and **no transcript/status/logs/result** command
    for a session. `agents create` is fire-and-forget — it returns only a
    `sessionId`. So completion can only be judged from vault artifacts, never
    by querying the session. All of this is now documented as a hard
    constraint in `skills/process-topic/SKILL.md`.
  - **Dispatch verb**: every `superset agents run` template/example in
    `process-topic` is now `superset agents create`. The `--agent
    "${QUASI_SUPERSET_AGENT:-copilot}"` contract is unchanged.
  - **Hook**: `scripts/hooks/inject-userconfig.py` now matches `superset
    agents create` (regex `_SUPERSET_AGENTS_CREATE`) to inject only
    `QUASI_SUPERSET_AGENT`; it no longer matches the dead `agents run`.
    `test_hook_injection.py` updated (create-form injection + a guard that
    the removed `agents run` form gets no injection). The active-contract
    line in this file / `AGENTS.md` updated accordingly.
  - **Prompt-file transport**: long synthesis/audit/refine prompts no longer
    go through argv (copilot is `promptTransport: argv`; long Chinese prompts
    with quotes/numbered sections are fragile there). The skill writes a task
    file `.quasi/process-topic-runs/{slug}.prompt.md` and dispatches a short
    `Read … and perform it exactly` prompt. `--attachment` is a confirmed
    alternative (Superset uploads the file and injects an `# Attached files`
    absolute path into the prompt); prompt-file is preferred for being
    deterministic.
  - **Completion sentinels + poll modes**: poll-agent now supports `exists`
    (first-time generation), `mtime_changed` (overwrite/update), and
    `sentinel` (agent writes `.quasi/process-topic-runs/{run_id}.json`).
    Update/refine completion requires **sentinel AND mtime change** — a
    sentinel can land a beat before the file flush, and a sentinel alone does
    not prove the target actually changed.
  - **Refine mode + `final_status` state machine**: manifest gains `mode`
    (`generate` | `refine`) and `final_status`
    (`missing`/`generated`/`needs_update`/`updated`). FINAL is skipped only
    when `final_status ∈ {generated, updated}` — an explicit refine/update
    request is **not** skipped just because `00-overview.md` already exists.
  - **Smoke test**: `skills/process-topic/smoke-dispatch.sh` (live,
    maintainer-run, not CI) proves `agents create` creates a file and that
    prompt-file dispatch updates an existing file with sentinel+mtime
    detection. Validated live: both pass in ~15s on a real-backend agent
    preset. Note: the configured `copilot` preset routes through a local
    model proxy (`monster.json` → `ANTHROPIC_BASE_URL`); when that backend
    stalls, sessions are created but never produce output and there is no
    transcript to inspect — the skill detects this via poll timeout (the
    QUA-187 reproduction's "20 minutes, no change" was this backend stall,
    not a Superset/mechanism fault).
  - No schema-contract change; no Python script changes beyond the hook.

- **0.38.2** (2026-06-06): **extract-agent 阶段 2 prompt trimmed to instructions
  only.** The 0.38.1 prompt carried maintainer-facing rationale (why it used to
  stick, root cause, the "绝不整章通读" prohibition) inside the agent's runtime
  instructions — but the agent only ever receives the head+tail digest, so the
  prohibition is moot and the history is noise. Rewritten to four action steps:
  read `manifest.json` (empty → OCR; >100 → re-split), run the head/tail digest
  command and read its output, eyeball each chapter for truncation / boundary
  mis-cut / garble (Read a single chapter only if unsure), pass. No behaviour
  change; the "why" stays here in the changelog where maintainers read it.

- **0.38.1** (2026-06-06): **extract-agent validation no longer floods its own
  context (QUA-186).** The agent "经常卡住" because its 阶段 2 验证 read head+tail
  (~100+100 lines) *and* `wc -l`'d **every** chapter file — a 40-chapter book dumped
  ~8,000 lines (≈120–160k tokens) into the sonnet subagent, which then slowed,
  looped, or ran out of context.
  - Full per-chapter coverage is **kept** (sampling was rejected: an isolated
    mid-book boundary mis-cut — e.g. between ch5/ch6 — is only catchable by looking
    at every chapter; and OCR'd chapter-start formatting is too unstable for a
    script to judge heading presence, so truncation/garble judgment stays with the
    agent's eye). The fix is **volume per chapter**, not coverage.
  - `agents/extract-agent.md` 阶段 2 rewritten: mechanical pre-check reads only
    `manifest.json` (`extracted_count`, per-chapter `word_count`, fragmentation
    >100, file-count via one `ls | wc -l`; neighbour `word_count` jumps flag
    boundary mis-cuts). Then a **single** Bash `for f … head -n 8; tail -n 8`
    command emits one head+tail digest of **all** chapters, read in one shot —
    every chapter eyeballed for truncation/garble at ~16 lines each instead of 200,
    and ~1 tool call instead of ~80. "每章只看头尾少量行，绝不整章通读" is the stated
    hard constraint; chapter-start markers are explicitly treated as optional
    (OCR-unreliable).
  - 阶段 3 修复: per-chapter / boundary re-extract uses the manifest's `start_page`;
    after a re-run the head+tail digest is re-run; still capped at 2 rounds.
  - Output contract (`EXTRACT_RESULT`), CLI surface, and manifest schema unchanged —
    pure agent-prompt fix, no Python/test changes.

- **0.38.0** (2026-06-05): **New `quasi:process-talk` skill — recording → multi-engine
  ensemble transcription → structured talk summary (QUA-182).**
  - New `talk` + `transcript` schema types (schema contract **0.5.0 → 0.6.0**):
    `talk` = `vault/talks/<slug>/talk.md` (TalkSchema frontmatter `type/title/date/
    speaker/themes/rating/media` + six fixed four-char H2 body `核心论点 / 时间脉络 /
    分节摘要 / 关键概念 / 项目关联 / 文献人物` — `时间脉络` is video-specific, replacing
    paper's `理论框架`; `文献人物` replaces `核心引用`; Q&A folds into `分节摘要`).
    `transcript` = `vault/talks/<slug>/transcript.md`, lightweight freeform body
    (timestamped), frontmatter `type/title/talk`. Registered in `scripts/schemas/`
    (`talk.py`, `transcript.py`, `body.py`, `registry.py`, `__init__.py`), mirrored
    into `audit-agent.md`, snapshot/registry tests bumped. `autofix_mechanical`
    keeps `talk.date` (the global orphan list drops `date` for paper).
  - **Transcription is a multi-engine ENSEMBLE** (`scripts/transcribe/` +
    `bin/quasi-transcribe`): `run` extracts 16k mono wav and runs Soniox
    (`stt-async-v4`, cloud, highest quality + word timestamps, needs
    `soniox_api_key`) + Apple `SpeechTranscriber` (on-device, macOS 26, compiled
    from `apple_stt.swift`) + Parakeet-v3 (mlx, English/European, auto-skipped for
    Chinese) in parallel; each engine's SRT lands under `processing/talks/<slug>/`
    (tracked, user-inspectable intermediates like `processing/chapters/` — kept so
    the summary can be re-run without re-transcribing / re-paying Soniox) and
    the primary (Soniox-preferred) assembles `transcript.md` plus a tracked
    `recording.srt` (named to match `recording.<ext>` so video players auto-load
    it as subtitles). `classify` does a
    text-only live/DEAD verdict; `silent` writes the schema-conforming "no usable
    audio" `talk.md`. Engines fail-soft (empty on error) so the ensemble degrades.
  - `analyse-agent` gains a `type: T` (talk) mode: reads all engine transcripts and
    **cross-references by timestamp** (agreement ≈ truth, disagreement = the
    proper-noun/homophone/jargon spans to adjudicate), then writes `talk.md` per
    TALK_BODY, back-filling `speaker` / `themes`. Minimal additive change — A/B
    untouched.
  - New `soniox_api_key` userConfig (sensitive) → `QUASI_SONIOX_API_KEY` via the
    inject-userconfig hook `_KEYS`. New `skills/process-talk/SKILL.md` (single-talk,
    Step-0 local recall, `quasi-transcribe` + `analyse-agent` + `audit-agent`).
  - System deps for transcription: `ffmpeg`, `whisper-cli` (optional engine +
    language detect), `swiftc` (Apple), `uvx` (Parakeet). All optional/fail-soft
    except at least one working engine.
  - Tests: `test_transcribe.py` (SRT parse, Soniox word-boundary grouping, classify,
    silent/transcript body conformance), `test_schema_registry.py` +
    `test_schema_snapshot.py` extended for `talk`/`transcript`. Full suite 114 pass.

- **0.37.6** (2026-05-31): **Step 0 uses local-first duplicate/resume recall before search/download.**
  - `process-book` and `process-paper` now check local completed outputs,
    accepted sources, caches/manifests, and rg fuzzy candidates before calling
    `search-agent` / `download-agent`, so slug stopword drift is less likely to
    duplicate work.
  - `process-author` now checks existing author profile/manifest/discovery
    caches first and reconciles representative works against local final/source
    /partial artifacts before acquisition.
  - Regression tests assert local recall/reconcile precedes search/download.

- **0.37.5** (2026-05-30): **`topic` / `journal` pages gain required `title`
  (schema contract 0.4.0 → 0.5.0) + process-topic dispatch/polling hardening.**
  - `TopicSchema` and `JournalSchema` now require `title: Title` so every page
    type carries a human title for the reader / Marple frontend without
    parsing H1. journal `title` = 期刊名 (redundant with `journal` by design —
    every page type is uniform). Breaking field addition → schema contract
    version bumped `0.4.0 → 0.5.0` (`SPEC.md`, `scripts/schemas/__init__.py`).
  - Stale consumers caught the same way 0.37.2's `topics` mismatch was — the
    schema shipped without anyone downstream tracking it. Updated together:
    `SPEC.md` §3.5/§3.6 (TS defs, YAML examples, rules), `synthesis-agent.md`
    §J/§T (added the missing `<frontmatter_schema>` block — it had none),
    `process-topic` synthesis dispatch prompt (now emits `title: {topic}`),
    and `topic.py` docstring. The published Marple snapshot
    (`scripts/audit/emit_schema.py` → `.quasi/schema.json`) reads live models,
    so it self-updates; its expected-required table in
    `test_schema_snapshot.py` was bumped.
  - Tests: `test_schema_registry.py` (3 cases: lightweight validate now needs
    `title`; the old "journal-with-title is rejected" case became "extra field
    rejected" + a new "missing `title` rejected"; freeform-body fixtures gain
    `title`) and `test_schema_snapshot.py` (required tables). Full suite 209
    passing.
  - **process-topic** (problem the user flagged — tree dispatch wasn't stable):
    - New hard constraint at the top: 主进程只编排,绝不亲自处理 — every
      `process-*` / `synthesis` / `audit` step goes through `superset agents
      run`; the main process never runs `/quasi:process-*` or the `quasi-*`
      pipeline itself.
    - Completion polling moved off the main process: instead of the main
      process Glob-polling vault products (which floods its context on long
      delegated runs), it now dispatches one clean `general-purpose` poll-agent
      per batch with the batch's `vault_path` list. The agent loops `ls`/`test
      -f` every 60s until all present or 30min timeout, returns a compact
      `{present, missing, elapsed_s}`. read-only; main process updates the
      manifest from the result.
    - Added the `## Agent / Helper 合同` section the orchestration schema
      requires (process-topic was missing it — `test_active_skills_follow_
      runtime_schema` was already red on the prior commit) and houses the
      poll-agent contract there.
    - Fixed `test_process_topic_superset_agent_uses_shell_default_contract`
      which asserted double-brace `${{...}}` — the rest of the codebase (and
      the 0.37.1 runtime contract) uses single-brace `${QUASI_SUPERSET_AGENT:
      -copilot}`; the test was over-escaped, the SKILL was correct.

- **0.37.2** (2026-05-29): **Fix mechanical autofix stripping the `topics` support field.**
  - 0.37.0 (QUA-36) added `topics` as an optional membership field on the
    book / paper / chapter / author schemas and SPEC.md, but left `topics`
    in `scripts/typecheck/autofix_mechanical.py::ORPHAN_FIELDS`. Mechanical
    autofix therefore deleted the field as an orphan, undoing topic
    membership written by `process-topic` (and any hand-added `topics`).
  - Fix: removed `"topics"` from `ORPHAN_FIELDS`. The legacy singular
    `"topic"` stays an orphan — SPEC keeps dropping it; membership lives on
    the plural `topics` list. The schema field set and the orphan list were
    never linked by a test, so the QUA-36 schema change shipped without
    anything catching the mismatch.
  - Regression guard: `tests/test_block_list_yaml.py::`
    `test_autofix_keeps_topics_drops_singular_topic` feeds a fixture with
    both `topic` and `topics` through autofix and asserts `topics` survives
    while singular `topic` is dropped. Full suite 100 passing.

- **0.37.1** (2026-05-29): **Configurable Superset agent for process-topic dispatch.**
  - New `superset_agent` userConfig option (default `copilot`) forwarded as
    `QUASI_SUPERSET_AGENT`; `process-topic` dispatches
    `superset agents run --agent ${QUASI_SUPERSET_AGENT:-copilot}` instead of
    hardcoding `claude`.
  - `inject-userconfig` hook injects only `QUASI_SUPERSET_AGENT` for
    `superset agents run` commands, and blanks quoted spans before command
    detection so prompt text like `--prompt 'Run quasi-search'` no longer
    triggers broad config injection.

- **0.37.0** (2026-05-29): **Process-topic becomes vault-native review + reading-list indexing.**
  - `process-topic` now discovers papers and books with `quasi-search`, delegates
    item processing to `process-paper` / `process-book`, and indexes accepted vault
    products with topic-page `[[wikilinks]]` plus entity `topics: [slug]` membership.
  - Topic frontmatter now carries only `type` / `kind`; paper, book, chapter, and
    author schemas gain optional `topics` membership lists. Schema contract version
    is bumped to 0.4.0.
  - Resume handling reconciles stranded processing items by checking whether the
    delegated vault product already exists before re-dispatching work.

- **0.36.3** (2026-05-28): **Schema accepts numeric ISBNs and audit reports strict fields.**
  - `BookSchema.isbn` now accepts `int | str` input and coerces ISBN values to
    strings, so numeric YAML/JSON ISBNs validate instead of failing type checks.
  - `quasi-audit --path` now surfaces strict frontmatter field diagnostics for
    schema fields that need maintainer attention.

- **0.36.2** (2026-05-27): **Audit emits diagnostic-first repair contracts.**
  - `quasi-audit --path` now returns per-file `diagnostics[]` with explicit
    `status`, `action`, and location fields instead of the older
    `llm_editable` / `escalated` buckets.
  - Mechanical audit fixes report their own diagnostics, including QUA-108
    frontmatter flow-array to block-list rewrites and CJK body quote cleanup
    that skips frontmatter, code, links, and wiki aliases.
  - `audit-agent` now follows the diagnostics contract directly, applying only
    the actions the audit runner declares safe and escalating everything else.
  - `process-book`, `process-paper`, `process-author`, and `process-topic` now
    best-effort open the final Marple page after successful completion.

- **0.36.1** (2026-05-21): **Wrap-up citation review uses four-card AskUserQuestion rounds.**
  - `wrap-up` Phase 2.4 now tells the main process to show a short queue
    summary, expand at most four review cards, and collect the current round's
    decisions with `AskUserQuestion`.
  - Each `AskUserQuestion` question maps to one review card; complex cards run
    alone, while simple same-kind cards can share a round up to the four-question
    tool limit.
  - After each round, the main process must immediately update
    `decisions.json`, apply needed local edits, re-emit `references.bib`, and
    report remaining pending cards before showing the next round.

- **0.36.0** (2026-05-21): **Wrap-up citation review moves to Claude Code-native review cards.**
  - `quasi-helpers citation review-cards` merges `citecheck-agent` batch
    outputs into `.quasi/citation/{stem}/review-cards.json`, preserving
    both the new rich card fields and the legacy `flag` / `note` shape for
    transition.
  - `citecheck-agent` now writes high-context review cards: draft quote,
    use summary, current bib concern, candidate evidence from vault files,
    recommended action, confidence, and missing evidence. It still never
    edits draft, vault, manifest, biblio, or decisions.
  - `wrap-up` Phase 2.4 is explicitly CC-native review, not HTML/TUI. The
    main process must pass review-card context through to the user and, after
    each group of user decisions, immediately update `decisions.json`, apply
    needed local edits, re-emit `references.bib`, and report remaining work.
  - Tests: `tests/test_citation_review_cards.py` covers rich-card merging and
    legacy compact-note normalisation.

- **0.35.0** (2026-05-20): **Audit agent gains frontmatter metadata QA via search CLI (QUA-61).**
  - `audit-agent` now follows an explicit step sequence: Step 1 local audit
    transaction, Step 2 minimal LLM edits, Step 3 frontmatter check, Step 4
    validation.
  - Step 3 reads each item's frontmatter and, when needed, calls the existing
    `quasi-search` CLI (`book --isbn` / `--title --author`, `paper --doi` /
    `--title --author`) to verify `title`, `authors`, `year`, `isbn`, `doi`,
    `journal`, `publisher` against online metadata.
  - Mismatches are reported as `kind: "metadata_mismatch"` with current value,
    search candidate, and evidence source. Only clear, minimal frontmatter edits
    are applied; conflicts, weak matches, and edition/translation judgment calls
    are escalated. Never fabricates DOI / ISBN / year / publisher.

- **0.34.0** (2026-05-20): **EZProxy global cross-process rate gate (QUA-50).**
  - `quasi-download` now spaces EZProxy attempts across separate processes so
    parallel paper downloads cannot trigger institutional EZProxy bans —
    agent-side concurrency control was unreliable.
  - New `_ezproxy_throttle()` in `scripts/download/download.py` takes an
    exclusive `fcntl.flock` on a user-global state file
    (`${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/ezproxy-throttle.state`), and
    **holds the lock across the wait**, so competing processes pass the gate
    exactly one interval apart (true serialization, no thundering herd).
  - Called once at the top of `try_ezproxy_download`, after the
    "not configured" skip — unconfigured runs never wait; Phase-1, Phase-2
    Kagi, and the cookie-refresh retry all funnel through the single gate.
  - `EZPROXY_MIN_INTERVAL = 30` seconds, hardcoded (no env var, no Configure
    option). Wait is uncapped (a queued process always waits its turn) but a
    single wait is bounded to one interval against corrupted/future
    timestamps. No-op when `fcntl` is unavailable.
  - Scope: EZProxy only. AA stays agent-spaced; `download-agent.md` note
    relaxed accordingly.
  - Tests: `tests/test_download_cli.py` gains throttle timing/locking unit
    tests, a real multi-process serialization test, and gate-placement tests
    for `try_ezproxy_download`.

- **0.33.6** (2026-05-20): **Publisher PDF discovery handles Crossref PDF endpoints and proxied INFORMS hosts.**
  - Crossref PDF discovery now accepts official PDF-looking URLs even when Crossref marks their `content-type` as `unspecified`, covering OUP article-PDF URLs.
  - Cambridge Crossref `content/view/...` endpoints are accepted as PDF candidates; live 2026 Cambridge EZProxy validation also succeeds through `citation_pdf_url` when direct construction is not usable.
  - INFORMS proxied hosts (`pubsonline-informs-...`) now match the EZProxy PDF pattern, and DOI prefix `10.1287/` now maps to `pubsonline.informs.org/doi/pdf/{doi}` for publisher-direct attempts.
  - Live 2026 EZProxy validation: ACM, Cambridge, De Gruyter, Brill, MIT Press, OUP, Project MUSE, SAGE, Taylor & Francis, UChicago, Wiley, plus forced Springer EZProxy stage all succeed. INFORMS reaches the proxied article page but tested `/doi/pdf/...` endpoints return HTML/no entitlement; Elsevier ScienceDirect reaches the subscribed article page but PDF download is gated by a browser intermediate page.
  - Tests: full suite 29/29 passing.

- **0.33.5** (2026-05-19): **EZProxy CookieCloud domain matching handles OCLC subdomains.**
  - CookieCloud filtering now keeps cookies across the configured EZProxy domain tree instead of requiring exact-domain equality. Configuring `oclc.org` now preserves usable cookies from `idm.oclc.org` and publisher-specific proxied subdomains.
  - EZProxy sessions preserve each CookieCloud cookie's original domain/path, so parent-domain and subdomain cookies are scoped the same way the browser scoped them.
  - Direct proxied PDF downloads build a Cookie header from only the cookie records matching the requested proxied host, avoiding stale or unrelated sibling-domain cookies.
  - Live validation: Taylor & Francis proxied direct PDF for DOI `10.1080/02691728.2025.2480274` succeeds with configured domain `oclc.org`.
  - Tests: full suite 25/25 passing.

- **0.33.4** (2026-05-19): **Fix proxied direct URL cookie injection.**
  - `download_pdf_from_url()` now supports CookieCloud's multi-cookie EZProxy config (`cookies` dict) when downloading already-proxied direct PDF URLs.
  - Fixes a `KeyError: 'cookie'` path introduced after CookieCloud moved from a single cookie value to domain-filtered cookie dictionaries.
  - Tests: full suite 23/23 passing.

- **0.33.3** (2026-05-19): **Plugin config cleanup for worktrees.**
  - All active plugin Configure options are marked `sensitive` so Claude Code stores and injects every option through the same private/keychain path. This works around worktree sessions only receiving private plugin options in hook subprocesses.
  - `anna_mirrors` is removed from plugin Configure options and no longer forwarded by the Bash PreToolUse hook.
  - Anna's Archive download still uses the built-in default mirror list internally, so users only configure `anna_donator_key`.
  - README credential table updated accordingly.

- **0.33.2** (2026-05-19): **Publisher PDF download query variants.**
  - EZProxy direct PDF patterns now try `?download=true` variants for Taylor & Francis, Wiley, and UChicago before falling back to embedded viewer scraping.
  - EZProxy epdf fallback now covers Taylor & Francis (`/doi/epdf/{doi}?needAccess=true`) and Wiley (`/doi/epdf/{doi}`), matching proxied viewer URLs observed for Social Epistemology and British Journal of Sociology papers.
  - Publisher Direct and Wayback URL construction now include `?download=true` variants for Taylor & Francis, Wiley, and UChicago; Wiley `10.1111/` DOI prefixes are included alongside `10.1002/`.
  - `citation_pdf_url` meta extraction is now attribute-order tolerant, so viewer pages with extra `<meta>` attributes still resolve to the underlying PDF URL.
  - Tests: full suite 23/23 passing.

- **0.33.1** (2026-05-19): **UChicago EZProxy PDF discovery.**
  - EZProxy publisher-pattern download now tries all matching publisher
    patterns instead of stopping after the first match. This lets UChicago
    fall through from `/doi/pdf/{doi}` to `/doi/pdfplus/{doi}`.
  - UChicago embedded viewer support: EZProxy fetches `/doi/epdf/{doi}`
    and extracts `citation_pdf_url` from the page before the generic HTML
    link scrape. This covers UChicago pages whose direct PDF endpoint is
    not exposed on the DOI landing page.
  - Publisher Direct also tries all matching patterns and includes
    UChicago `/doi/pdfplus/{doi}`.
  - Tests: full suite 23/23 passing.

- **0.33.0** (2026-05-19): **Paper download gains multi-source discovery,
  publisher direct PDF, and Kagi recovery.** Driven by 19-paper test
  batch where 15 papers failed acquisition (6× EZProxy expired,
  6× abstract-only/no-PDF, 2× paywall+no OA, 1× too new — the
  remaining 4× ECONNRESET/502 were already fixed by 0.32.15 retry).
  Root cause: papers had no multi-source candidate discovery — unlike
  books (which search Anna's Archive for multiple candidates and iterate),
  papers took a single DOI and ran a fixed cascade. If the DOI was wrong
  or the cascade failed, there was no fallback.
  - **Paper fetch cascade expanded** from 5 stages to 8 (Phase 1) + Kagi
    recovery (Phase 2). New cascade:
    `hint URLs → OA (+Crossref links) → Sci-Hub → Publisher Direct
    → EZProxy → Wayback → [if all fail] Kagi discovery → retry with
    discovered DOIs/URLs`.
  - **Crossref PDF links** added to `find_oa_url()` as 4th source.
    Queries `https://api.crossref.org/works/{doi}` and extracts
    `link[]` entries with `content-type: application/pdf`. Many
    publishers register their PDF endpoints here.
  - **Publisher Direct PDF** — new cascade stage between Sci-Hub and
    EZProxy. `_try_publisher_direct(doi, output_path)` constructs
    publisher PDF URLs from DOI prefix patterns
    (`_PUBLISHER_DIRECT_URLS`: uchicago, tandfonline, sagepub, oup,
    wiley, springer, nature, mit, acm, muse, cambridge, informs)
    and tries fetching them without EZProxy. Catches cases where
    institutional IP access works or publisher has opened access.
  - **Kagi recovery** — when Phase 1 cascade exhausts all sources,
    `_kagi_discover_paper(title, author)` searches the paper title
    via `kagi search --format json`, filters results by ≥50% title
    word overlap, extracts DOIs from URLs via regex, and collects
    publisher URLs. Discovered URLs are tried directly; discovered
    DOIs (different from the original) are retried through
    OA/Sci-Hub/EZProxy. Silently skipped if kagi CLI is unavailable
    or `QUASI_KAGI_SESSION_TOKEN` is unset. Enables acquisition
    even when the caller's DOI is wrong.
  - **Multiple `--url` hints** — `paper fetch` now accepts repeated
    `--url` flags (`action="append"`). Each URL is tried as a direct
    download attempt before the DOI cascade. This lets the agent
    pass OA URLs and publisher URLs discovered via search.
  - **`--title` / `--author` flags** — `paper fetch` now accepts
    `--title` and `--author` for Kagi recovery. When the DOI cascade
    fails, these enable the automatic Kagi discovery phase.
  - **Wayback patterns expanded** — `find_wayback_url()` now
    constructs publisher-specific PDF URLs for UChicago (`10.1086`),
    Wiley (`10.1002`), OUP (`10.1093`), MIT Press (`10.1162`),
    T&F (`10.1080`), SAGE (`10.1177`), in addition to the existing
    ACM, Springer, MUSE patterns. Each gets a dedicated CDX lookup.
  - **download-agent.md** — paper flow now mirrors book flow: agent
    calls `quasi-search paper --doi/--title/--author --json` to
    verify DOI and discover access URLs before calling `paper fetch`.
    Passes verified DOI + `oa_url`/`url` as `--url` hints. Handles
    wrong/missing DOI case. Agent prompt updated with new CLI
    examples and search-before-fetch guidance.
  - **process-paper SKILL.md** — download-agent dispatch now passes
    `oa_url` and `url` from search-agent results through to
    download-agent's `identifiers:` block, so download-agent already
    has URLs to try without re-searching.
  - Tests: full suite 23/23 passing. No test changes needed — new
    features are additive (new cascade stages, new CLI flags with
    defaults, new recovery path).

- **0.32.15** (2026-05-19): **Paper download cascade gains retry/backoff
  and a real INFORMS pattern; Wayback always on.** Triggered by a 5-paper
  batch (Hayles 2019 / Star 1996 / Oudshoorn 2004 / Lock 1994 /
  Dhaliwal 2022) where 4 of 5 papers failed acquisition. Live re-probe
  showed 3 of 4 DOI-bearing papers downloaded fine *today* — the original
  batch had been killed by transient sci-hub / EZProxy errors that no
  retry layer was catching. Lock 1994 has no DOI (JSTOR stable URL
  only) and is out of scope for download.py; that one needs agent-side
  changes to fall back through `--url` when `doi:null`.
  - New `_retry(fn, attempts=3, base_delay=1.0)` helper with
    `_is_retryable_http()` companion. Retries `URLError` /
    `RequestException` / `TimeoutError` / `ConnectionResetError` and
    transient HTTP codes (`429, 500, 502, 503, 504, 520, 521, 522, 524`)
    with exponential backoff. Determinstic 4xx propagates immediately —
    a 404 should never become 3× wall-clock cost.
  - Wrapped network entry points: `try_scihub_download` (both the
    page-fetch and the PDF-fetch `urlopen`s, per mirror),
    `download_pdf_from_url` (urllib), `_stream_download` (requests stream
    — chunked transfer restarts from byte 0 on failure), and
    `try_ezproxy_download`'s three `session.get` calls (login redirect,
    publisher-pattern PDF try, scrape try).
  - `SCIHUB_MIRRORS`: `[".ru", ".ren"]` → `[".ru", ".st", ".box"]`.
    Probed 2026-05: `.ren` persistently returns 403; `.st` and `.box`
    mirror the same storage backend as `.ru` and reliably surface
    `citation_pdf_url` meta tags. Mirror list is now 3 deep with no
    known-dead entries.
  - `PUBLISHER_PDF_PATTERNS` gains `("pubsonline.informs",
    "/doi/pdf/{doi}")` — INFORMS journals (Information Systems
    Research, Organization Science, MIS Quarterly, etc.) host PDFs at
    `pubsonline.informs.org/doi/pdf/{doi}`. Previously EZProxy
    redirects to INFORMS fell through to the HTML-scrape branch which
    rarely works (INFORMS hides PDF links behind a JS click handler).
  - `try_ezproxy_download` logs `EZProxy: not configured (CookieCloud
    env vars missing), skipping` when `load_ezproxy_config()` returns
    None. Was silent — diagnostically misleading because the cascade
    printed `Trying EZProxy for X...` then `Could not download paper`
    with no signal that the stage was a no-op.
  - `--retry-wayback` flag accepted but ignored (help hidden via
    `argparse.SUPPRESS`); Wayback is now always tried as the last
    cascade step. `_cmd_paper_fetch` calls `download_paper(...,
    retry_wayback=True)` unconditionally. The flag stays callable so
    existing agent prompts / skills that still pass it don't break.
  - `agents/download-agent.md` paper-fetch command example drops
    `[--retry-wayback]` and notes the cascade has retry/backoff at each
    stage.
  - Tests: `test_download_cli.py` + `test_dead_names.py` unchanged and
    passing (7/7). `_retry` smoke-tested out of band: 4xx propagates
    after 1 attempt, 5xx / ConnectionResetError retry to 3 attempts
    then re-raise, second-attempt-success returns the value.
  - End-to-end re-probe (post-fix):
    - Star 1996 (`10.1287/isre.7.1.111`) → sci-hub.ru direct, 2.4 MB ✓
    - Dhaliwal 2022 (`10.1086/721167`) → sci-hub.ru/.st/.box all empty
      (sci-hub doesn't have the 2022 article) → EZProxy uchicago
      pattern → 10.5 MB ✓

- **0.32.14** (2026-05-19): **Douban zh-localisation: two-stage CJK
  filter; bin no longer guesses relevance.** Three interlocking bugs
  surfaced when localising *Living a Feminist Life* — Kagi's top hit
  (`/subject/36494081/?_dtcc=1`) was being silently dropped, and the
  ISBN fallback variant was polluting results with popular unrelated
  Chinese books. Root cause was 0.32.9's "strict admission" regex
  rejecting normal URL cruft, plus an under-considered ISBN variant
  using the original-language ISBN that Douban doesn't index.
  - **Regex normalises subject-URL cruft instead of rejecting it.**
    `_RE_DOUBAN_SUBJECT_CLEAN` switched to
    `^https?://book\.douban\.com/subject/(\d+)/*(?:\?[^#]*)?(?:#.*)?$`.
    Accepts `/subject/{id}//` (double-slash) and `/subject/{id}/?_dtcc=1`
    (Kagi tracking suffix) and `/subject/{id}#frag`, all normalise to
    canonical `/subject/{id}/`. Still rejects `/comments`,
    `/blockquotes`, `/doulists`, `/annotation`, `/offers`, `/buylinks`,
    `/reviews/...` child paths. This reverses 0.32.9 — that release's
    "exact policy" was a regression in disguise; real Kagi output
    routinely carries the cruft on legitimate subject pages.
  - **ISBN variant gated to ISBN-only queries.** `_external_book_queries`
    no longer adds the ISBN as a Kagi search variant when title or
    free-text query is present. Douban indexes the *Chinese-edition*
    ISBN, never the original English one — so an English-edition ISBN
    triggers Kagi's "no precise match, return popular results"
    fallback, which surfaces top-rated unrelated Chinese books
    (典型: 如何阅读一本书 / 脑髓地狱 / 边界力 / 谁来决定吃什么 returned for any
    English ISBN under `subject=zh`).
  - **Pre-fetch CJK title filter.** `_kagi_subject_urls` now returns
    `[(canonical_url, kagi_title), ...]` pairs. `_kagi_book_search`
    accepts `cjk_title_only=True` and skips Kagi hits whose page title
    is Latin-dominant before spending an HTTP fetch on them — drops
    the English-edition Douban page when we're after the Chinese
    translation. `_cjk_dominant` decides by CJK-vs-ASCII-letter count.
  - **Bin no longer attempts query-vs-record relevance matching.**
    `_zh_localisation_search` is two coarse filters and a sort:
    pre-fetch CJK title → fetch → post-fetch `_is_chinese_edition`
    (publisher / translator / ISBN-agency / kana-hangul-reject signals
    unchanged) → sort by `ratings_count`. The "is this record the
    translation of *this specific* book the caller asked for"
    disambiguation is the caller agent's job — bin returns the small
    set of Chinese-book candidates Kagi surfaced, agent picks.
  - **Per-variant Kagi pull bumped 10 → 20** so the CJK pre-filter has
    enough candidates to survive even when the EN edition crowds the
    top of Kagi's ranking.
  - Tests in `test_source_douban_cn.py` and `test_douban_cn_en2zh.py`
    updated for the new `(url, title)` return shape and the cjk-title
    pre-filter behaviour. Full search suite green (35 + 12 + others).
  - Behaviour: end-to-end `quasi-search book --title "Living a
    Feminist Life" --author "Sara Ahmed" --source douban_cn --subject
    zh` now returns the single correct record `subject 36494081 过一种
    女性主义的生活, 原作名 = Living a Feminist Life, 出版社 = 上海文艺出版社`
    (previously: 4 unrelated popular Chinese books).

- **0.32.13** (2026-05-19): **EZProxy config takes a base URL, not a
  half login prefix.**
  - Breaking config rename: `cookiecloud_login_url` is removed and
    replaced by `cookiecloud_ezproxy_base_url`.
  - Users now enter a clean base such as `https://ezproxy.example.edu` or
    `ezproxy.example.edu`. `scripts/download/cookiecloud.py` normalises it
    to `https://.../login?url=` internally.
  - Removed the last hard-coded EZProxy login-prefix fallback from
    `download.py`; EZProxy only runs when the new base URL and the rest of
    the CookieCloud config are present.

- **0.32.12** (2026-05-19): **Configure Options copy cleanup for
  CookieCloud / EZProxy.**
  - Removed the hard-coded Harvard EZProxy default from
    `cookiecloud_login_url`; users should provide their own institution's
    redirect prefix if they want EZProxy downloads.
  - Clarified the three distinct values: CookieCloud endpoint, EZProxy
    cookie domain, and EZProxy login URL prefix. The CookieCloud endpoint
    is only used to fetch browser cookies; the EZProxy fields describe the
    institution proxy itself.

- **0.32.11** (2026-05-19): **Kagi auth moves into plugin userConfig.**
  - Added sensitive `kagi_session_token` to `.claude-plugin/plugin.json`.
    Users configure it via `/plugin` → Configure options, matching the
    existing Anna's Archive / CookieCloud / Immersive Translate credential
    flow.
  - `scripts/hooks/inject-userconfig.py` now propagates it as
    `QUASI_KAGI_SESSION_TOKEN` for `quasi-*` Bash commands.
  - `scripts/search/sources/douban_cn.py` maps `QUASI_KAGI_SESSION_TOKEN`
    to `KAGI_SESSION_TOKEN` only for the `kagi` subprocess. This uses
    kagi-cli's documented env-var override and avoids relying on CWD
    `.kagi.toml`.

- **0.32.9** (2026-05-19): **Douban subject discovery tightened and
  query variants broadened.**
  - URL admission now uses the exact book-subject policy:
    `^https?://book\.douban\.com/subject/(\d+)/?$`. Only canonical
    `/subject/<digits>` and `/subject/<digits>/` pages survive; child
    pages such as `/comments`, `/blockquotes`, `/annotation`,
    `/doulists`, `/reviews/...`, query-string URLs, and double-slash
    variants are rejected instead of being normalised into candidates.
  - Kagi discovery now tries ordered query variants instead of one weak
    `title-head + author` string. It first searches the exact original
    title, then exact-title variants with Douban metadata hints
    (`原作名`, `译者`), then title-head variants for subtitled books, and
    only then author-qualified fallbacks.
  - Restored `_zh_localisation_search(query)` as a thin wrapper around the
    Kagi path for test and maintainer clarity: it fetches subject pages,
    filters Chinese editions, and sorts them by `ratings_count`.
  - Tests updated to the Kagi-only adapter surface:
    `test_source_douban_cn.py` 33/33 and `test_douban_cn_en2zh.py` 12/12.

- **0.32.8** (2026-05-19): **Douban localisation: Doko walk removed,
  Kagi + BeautifulSoup is the only path.** 10/10 live test books (Foucault
  / Butler / Latour / Anderson / Said / Arendt / Bourdieu / Haraway etc.)
  returned at least one Chinese-edition candidate via the simple flow —
  vindicating the user's diagnosis that the Doko maze was overengineering.
  - **`scripts/search/sources/douban_cn.py`**: 1402 → 678 lines (51% cut).
    Deleted: `_doko_read`, `_find_cndouban`, `_cndouban_works_*`,
    `_related_version_search`, `_fetch_subject_for_related`,
    `_parse_cn_subject_page`, `_parse_doko_subject_page`,
    `_grab_doko_meta`, `_doko_meta_window`, `_clean_doko_title`,
    `_extract_related_version_urls*`, `_version_section_snippets`,
    `_parse_doko_references`, `_extract_manifestations_from_works_page`,
    `_kagi_site_subject_urls`, `_kagi_site_subject_query`,
    `_score_primary_match`, `_normalise_for_match`, plus a dozen helpers.
    Net deletion of the entire Doko subprocess path.
  - **New 3-step path** (`_zh_localisation_search`):
    1. `_compact_external_book_query(title, author)` →
       `_kagi_subject_urls(q)` runs `kagi search --format json
       site:book.douban.com/subject {q}` and filters `data[].url` via
       `_RE_DOUBAN_SUBJECT_CLEAN = r"^https?://book\.douban\.com/subject/
       (\d+)/*(?:\?[^#]*)?$"` — drops `/comments`, `/blockquotes`,
       `/doulists`, `/reviews/...`, normalises `/subject/ID//` and
       `?_dtcc=...` to canonical `/subject/ID/`.
    2. `_fetch_subject_via_bs4(url)` uses plain `urllib` (`_dd_fetch`) +
       `BeautifulSoup` to parse `<span property="v:itemreviewed">` for the
       title and `<div id="info">` for `作者 / 译者 / 出版社 / 出版年 / ISBN
       / 原作名` etc. Field parsing uses label-alt lookahead so the inline
       metadata block doesn't bleed across fields, and stays scoped to
       `#info` so stray `译者:` in reader comments can't leak in.
    3. `_is_chinese_edition(rec)` (unchanged from 0.32.7): ISBN agency
       prefix decisive (CN/TW/HK accept, JP/KR/VN reject), then kana /
       hangul anywhere reject, then CJK in publisher / translator-with-CJK
       / title accept.
  - `search_book(query)` `subject=zh` branch shrinks from a 3-fallback
    cascade (Doko cndouban → kagi-seeded related-version walk → direct
    search → related-version walk) to one call to
    `_zh_localisation_search`.
  - **No new `userConfig`** — `kagi` CLI reads `.kagi.toml` from CWD per
    its own convention; the plugin doesn't bridge or override.
  - **Tests rewritten**: `test_source_douban_cn.py` (29 tests) and
    `test_douban_cn_en2zh.py` (19 tests) target the new functions —
    URL-filter regex (canonical / `/comments` reject / double-slash
    normalisation / dedup / limit), `_compact_external_book_query`
    behaviour, `_kagi_subject_urls` shell-out (kagi missing / nonzero rc
    / site-limiter format), `_fetch_subject_via_bs4` parsing (info-block
    isolation, block detection, fetch-failure handling),
    `_is_chinese_edition` matrix (CN/TW/HK accept, JP reject even with
    kanji, kana/hangul reject, CJK-publisher accept, non-CJK translator
    reject), `_zh_localisation_search` integration (filter mix EN+ZH,
    sort by ratings_count, kagi-warning surface). Full suite: 94 pass.
  - `agents/search-agent.md` zh-localisation note updated:
    `Kagi 不可用或无结果时,bin 会自行走豆瓣兜底` → `Kagi 不可用时,
    localisations.zh.candidates 为空`. No more Doko fallback to misrepresent.
  - `docs/DOUBAN_LOCALISATION_HANDOFF.md` rewritten end-to-end against
    the new 3-step pipeline.

- **0.32.7** (2026-05-19): **Douban Chinese localisation pipeline — end-to-end
  correctness pass.** Builds on 0.32.4–0.32.6 (Kagi-CLI primary subject
  discovery). Five real-book end-to-end runs surfaced five downstream bugs
  that were masking each other; all fixed in `scripts/search/sources/douban_cn.py`:
  - **Primary-subject picker no longer takes Kagi rank #1 blindly.** For
    "Strange Encounters / Sara Ahmed" Kagi ranked *The Cultural Politics of
    Emotion* #1 (CPE's page text mentions SE). Now each Kagi URL is
    Doko-fetched, parsed, and scored against the original title/author
    (`_score_primary_match`: title-head substring ⇒ +1.0; token overlap ≥60%
    ⇒ +0.6; author-surname ⇒ +0.4). Score ≥1.2 early-breaks; <0.3 rejects.
  - **`_parse_cn_subject_page` field extraction rewritten.** Doko renders
    Douban metadata as one long line `作者: ... 出版社: ... 出版年: ... ISBN: ...`,
    so the old `作者:.+?\n` regex greedily grabbed the entire blob. Now uses
    `_grab_doko_meta` with label lookahead against `_DOKO_META_LABELS`.
  - **`_grab_doko_meta` scoped to a metadata window.** Previously matched
    anywhere in the body — picked up stray `译者:` from reader comments far
    below the metadata, producing translator blobs like `"Alice Lian Sara
    Ahmed(2004),The Cultural Politics of Emotion..."`. New helper
    `_doko_meta_window(body)` slices text between `**Title**` and `豆瓣评分`.
  - **Title cleaning.** `_guess_title_from_subject_page` used to return
    `# Title (豆瓣)` with markdown noise. Now prefers the `**Title**` marker
    and strips the `(豆瓣)` suffix via `_clean_doko_title`.
  - **Chinese-edition detection no longer a publisher whitelist.** Old
    `_ZH_PUBLISHER_HINT_RE` enumerated ~25 publisher fragments (`三联|译林|
    上海|...`) — could never keep up with the long tail of academic / indie
    presses, and its bare `出版` alternation also matched the year label
    `出版年` (false positive). Replaced with registry-based signals:
    - ISBN agency prefix `978-7-` (mainland) / `978-957/986` (TW) /
      `978-988/962` (HK) ⇒ accept
    - ISBN prefix `978-4-` (JP) / `978-89/11` (KR) / `978-604` (VN) ⇒
      explicit reject (otherwise kanji-only Japanese titles like 伴侶種宣言
      slip through the generic CJK check)
    - Kana or Hangul anywhere in title / publisher / translator ⇒ reject
    - CJK in publisher | (CJK in translator AND translator non-empty) |
      CJK in title ⇒ accept
    The translator-non-empty alone (which had let through a French CPE
    edition by "Laurence Brottier") now requires CJK to count.
  - **End-to-end validation** in `docs/DOUBAN_LOCALISATION_HANDOFF.md`:
    Gender Trouble returns 3 Chinese editions (上海三联书店 / 岳麓书社 /
    桂冠 TW); Discipline and Punish returns 4 (三联书店 various years);
    Strange Encounters / CPE / Staying with the Trouble correctly return
    no candidates (no Chinese Douban subject for those works exists).
  - Existing 38 `douban_cn` tests still pass; full search suite 84 pass.
  - No new plugin `userConfig` slot — `kagi` CLI auth is read from
    `.kagi.toml` in CWD (user's own setup), not bridged through the
    plugin.

- **0.32.3** (2026-05-18): **book localisation sidecar becomes
  Doko-first and source-independent.** `quasi-search book` now always
  attempts the `localisations.zh` Douban sidecar, even when the caller
  limits canonical metadata search with `--source`. Chinese localisation
  lookup now prefers the Doko-rendered path (ISBN/search → Douban subject
  → other versions / works page → Chinese manifestation subject) before
  falling back to direct HTTP + related-version probing. Doko failures are
  surfaced as `localisations.zh.status="error"` instead of the previous
  false-negative `none`, so callers do not cache "no translation" when the
  browser bridge/API path was unavailable.

- **0.32.1** (2026-05-18): **frontmatter description discipline.**
  Treats `description:` as a routing hint, not a mini-README.
  Skill descriptions normalised to user-intent shape — `Use when
  the user wants to {core task} from/with {likely inputs}.`
  Agent descriptions normalised to worker shape — `Worker for
  {single specialist action}. {Main contract.}` Trigger-word piles,
  history notes (`前身: ...`), and phase walkthroughs (`Phase X →
  ...`) removed across all 5 active skills and all 9 active agents.
  `AGENTS.md`, `CLAUDE.md`, and `docs/SKILL_ORCHESTRATION.md`
  carry the maintainer-facing convention. Enforcement landed as
  `tests/test_skill_orchestration.py::test_frontmatter_descriptions_are_routing_hints`
  (length cap 220, required prefix per kind, forbidden tokens
  `user says / 前身 / Phase / → / 由` per kind).

- **0.32.0** (2026-05-18): **skill orchestration schema + bin
  surface trim.** All five active skills rewritten to the
  maintainer schema documented in `docs/SKILL_ORCHESTRATION.md`
  (new file): `任务` (one positive sentence), `输入` (intent →
  variable extraction), `硬约束`, `状态` (skill main process owns
  workflow state), `Agent / Helper 合同`, `工作流`, `执行流程`,
  `断点续跑`, `输出`. `调用方式`-style invocation API blocks are
  removed from runtime skills; natural-language trigger via
  frontmatter description is canonical. `AGENTS.md`, `CLAUDE.md`,
  `README.md`, and `docs/ARCHITECTURE.md` carry the maintainer-facing
  pointer to the schema doc, so active `SKILL.md` files no longer
  link back to maintainer docs.
  - Rewritten: `process-book`, `process-author`, `process-paper`,
    `process-topic`, `wrap-up`. Behaviour preserved end-to-end; the
    rewrite is structural — phases, agent dispatches, and human
    gates are now made explicit per the schema.
  - **BREAKING — `quasi-search`**: `--shape canonical|raw|single`
    and `--output PATH` flags removed; the markdown emitter is
    gone. Output is always canonical JSON to stdout. `--json` is
    accepted as a no-op for compatibility. Callers that needed
    `--shape single` should slice `results[:1]` themselves; the
    `raw` shape was unused.
  - **BREAKING — `quasi-download`**: `batch` subcommand removed
    along with `batch_download_manifest()` and the related glue
    (`_cmd_batch`, parser entry). Batch acquisition is now a skill
    main-process concern — `process-author` / `process-topic`
    dispatch `download-agent` directly with structured items.
  - `quasi-extract` chapter manifest: per-chapter field `file`
    renamed to `filename`; added `extracted_count` (top-level) and
    `word_count` (per chapter). Downstream extract callers and
    `process-book` Step 2 read the new shape.
  - `tests/test_dead_names.py` now scans active markdown plus
    `bin/quasi-*` shims, `README.md`, and `docs/ARCHITECTURE.md`,
    and grows entries for `--shape single|raw`, `--output`,
    `quasi-download batch`, `output_schema`, `citation-agent`
    (post-0.25.2 rename), and `mode: papers` (post-0.24.0 search
    refactor).
  - New tests: `tests/test_search_cli.py` (asserts JSON-only output
    contract, no `--shape`/`--output`), `tests/test_extract_cli.py`
    (asserts new chapter manifest field names),
    `tests/test_skill_orchestration.py` (asserts all five active
    skills carry the schema landmarks).
  - Minor: `scripts/extract/toc_utils.py` gains
    `from __future__ import annotations`; `scripts/citation/emit_bib.py`
    docstring updated to reference the wrap-up review step (not the
    deprecated `review.html` "导出 JSON" button); `quasi-helpers`
    header comment updated to `citecheck-agent` (post-0.25.2).

- **0.31.0** (2026-05-18): **quasi-audit becomes a single
  agent-facing typecheck wrapper.** The active CLI is now
  `quasi-audit --path PATH`. It always runs mechanical autofix,
  typecheck, residual issue classification, and emits JSON. Removed
  the agent-facing `run` verb, `--mode`, and `--json`; there is no
  check-only path in the active workflow. `emit-bib` moved to
  `quasi-helpers citation biblio`, and metadata backfill sweeps are
  maintenance scripts rather than `quasi-audit` subcommands.

- **0.30.0** (2026-05-18): **localise becomes a scale-facing helper,
  keyed by original ISBN.** This supersedes the 0.27/0.29
  local-agent/audit-localise shape. Book search now returns
  `localisations.zh` sidecar candidates; search-agent filters and
  passes those candidates upward but does not write files. The top-level
  skill decides whether to persist them via
  `quasi-helpers localise scan|write`, which writes
  `.quasi/localise/cndouban.json`:
  - `by_isbn[{normalized_original_isbn}]` stores checked state,
    current book path snapshots, and curated `cndouban_ids`.
  - `by_douban_id[{id}]` stores Chinese-edition metadata.
  - `quasi-audit localise` and `agents/local-agent.md` are removed from
    the active surface; audit is back to vault consistency only.

- **0.29.0** (2026-05-18): **cndouban fully externalised + audit
  reverts to a stateless typechecker.** Two intertwined cleanups landed
  together. First: continues 0.26.0's `.quasi/` artifact discipline by
  evicting `cndouban` from book frontmatter — it was the last
  user-facing field that was actually plumbing (an index into
  `.quasi/audit/translations.json`); now both the per-book state
  machine and the per-id metadata cache live in that file. Second:
  audit-agent has no persistent state of its own — it's structurally
  a unit-like typechecker — so its disk-write surface contracts to
  zero, and the cndouban backfill knowledge moves out of audit into
  local-agent's domain entirely.

  **Externalising cndouban:**
  - `scripts/schemas/book.py`: `cndouban` field removed. Comment in its place
    points readers to the external file.
  - `.quasi/audit/translations.json` schema bumped v1 → v2:

    ```json
    {
      "version": 2,
      "by_book": {
        "{slug}": {
          "checked_at": "YYYY-MM-DD",
          "verdict": "found" | "none",
          "douban_ids": [12345, 67890]
        }
      },
      "by_douban_id": {
        "12345": { ...per-id metadata, as before... }
      }
    }
    ```

    `verdict="none"` replaces the old `cndouban: []` semantic (查过、无中
    译本). `by_book[slug]` absent ⇒ 未查 (replaces `cndouban` field-absent
    semantic). v1 flat files are migrated by the script — readers do
    not need to handle v1 directly.
  - `scripts/migrations/cndouban_externalise.py` (new): one-shot
    user-disk migration. Scans `vault/books/**/00-overview.md`,
    converts each `cndouban: [...] / [] / null` field into a
    `by_book` entry (or for the null case, just strips the line —
    "not yet queried" needs no entry), reformats existing
    `translations.json` from v1 flat to v2 if needed, then strips
    the `cndouban:` line from frontmatter. Idempotent on
    already-migrated vaults. Invoke with
    `CLAUDE_PROJECT_DIR=/path/to/vault python "$CLAUDE_PLUGIN_ROOT/scripts/migrations/cndouban_externalise.py"`,
    optionally `--dry-run` first.
  - `agents/audit-agent.md`: book frontmatter `optional` list drops
    `cndouban` with a pointer comment to the external file.

  **Audit runner ⟂ translations.json decoupling + helper subcommands
  for local-agent:**
  - `scripts/audit/audit.py:_scan_needs_backfill` no longer flags
    `cndouban` at all; only structural frontmatter fields
    (publisher/isbn/doi) are reported. The runner doesn't open
    translations.json; cross-domain coupling that briefly slipped
    into `needs_backfill` is gone.
  - `scripts/audit/localise.py` (new) + `quasi-audit localise`
    subcommand: gives local-agent the script support it needs without
    a whole new bin. Two verbs:
    - `quasi-audit localise scan [--path X] [--json]` — enumerate
      `00-overview.md` files under PATH, emit per-book `{slug, path,
      has_entry, title, authors, year, isbn}`. `has_entry=true` means
      `by_book[slug]` is present in translations.json — the agent
      uses this for idempotent gating.
    - `quasi-audit localise write --slug SLUG (--results-json '[...]'
      | --results-file PATH)` — merge one book's localise outcome
      into translations.json. Empty results ⇒ `verdict=none`;
      non-empty ⇒ `verdict=found` + merge per-id metadata
      (`first_seen` preserved on existing keys). v1 flat cache
      auto-migrates to v2 on first write.

    These verbs live under `quasi-audit` purely as the natural home
    for small vault-touching helpers; the runner's analytical output
    stays domain-pure (cf. `feedback_audit_stateless` — runner stays
    decoupled even though bin can ship related helpers).
  - `agents/local-agent.md` rewritten: agent calls
    `quasi-audit localise scan --json` for the work list, dispatches
    `quasi-search book --source douban_cn --subject zh` per pending
    book, and writes results back via `quasi-audit localise write`.
    Agent no longer touches the JSON cache or vault frontmatter
    directly — tool surface trimmed to `Read, Bash`.
  - `skills/{process-book,process-author}/SKILL.md`: Step 6 / Phase 7
    LOCALISE comments + resume tables updated to reference
    `.quasi/audit/translations.json#by_book[slug]`; local-agent's
    self-contained gating noted.

  **Audit CLI dead-code cleanup — audit becomes effectively stateless:**
  - `scripts/audit/audit.py`: `_write_state()` deleted along with its
    `.quasi/audit/audit-state.json` artifact. Nothing programmatic
    read it; the wrap-up SKILL referenced it in pseudocode
    (`audit_state_clean()`) for a Phase 0 gating that was never
    actually implemented.
  - `quasi-audit check` and `quasi-audit fix` subcommands removed —
    they thin-delegated to typecheck.py / autofix_mechanical.py and
    had zero callers (agents use `quasi-audit run --mode {check,fix}`,
    which carries the structured JSON envelope). The `_delegate`
    helper goes with them. `bin/quasi-audit` shim help block rewritten.
  - `skills/wrap-up/SKILL.md`: `--audit-first` flag + the
    `audit_state_clean()` pseudocode block stripped (Phase 0 was never
    real; the only real audit consumers are inside process-book /
    process-author skills which dispatch audit-agent directly).
  - Post-cleanup, audit's only disk side-effect is
    `.quasi/audit/typecheck-results.json` (the in-process round-trip
    artifact left behind by typecheck.py). audit-agent itself is now
    truly stateless — runs, returns JSON, done.

  **Tests**: no test changes — existing `test_douban_cn_en2zh.py` /
    `test_source_douban_cn.py` cover the data-source layer
    (HTML parsing, search, normalisation), not the agent writeback
    path or the translations.json schema, so they're untouched by
    this refactor.

- **0.28.0** (2026-05-18): **process-book/author reorchestration +
  new process-paper skill.** Rewires `process-book` Step 0 and
  `process-author` Phase 1/2 around the post-0.24.0 search-bin and
  post-0.25.0 agent contracts, and lifts YEAR_TRIAGE out of skill
  prose into a structured field in `download-agent`'s output protocol.
  - `agents/download-agent.md`: `DOWNLOAD_RESULT.per_item` for
    `kind=book` gains a `year_evidence` sub-object
    (`slug_year`, `source_years`, `pdf_signals`, `recommended_year`,
    `recommendation_reason`, `verdict`). Status enum grows
    `year_mismatch` and `year_ambiguous`; `tmp_path` exposed in those
    cases. Verdict computation rule codified in the agent prompt:
    `recommended_year` prefers `pdf.first_published` > multi-source
    mode > `pdf.copyright_year`; translation books exclude
    `original_year`; `MATCH` iff `slug_year == recommended_year` and
    ≥2 corroborating signals. Papers (`kind=paper`) explicitly do
    not carry `year_evidence` — DOIs are one-to-one, no version
    ambiguity.
  - `skills/process-book/SKILL.md`: Step 0 shrinks from ~80-line
    inline prompt (replicating search→download→finalize chain inside
    download-agent's prompt) to a thin caller — dispatch
    download-agent with `{kind: book, items: [1]}`, branch on
    `item.status`. `ok` → continue to EXTRACT;
    `year_mismatch`/`year_ambiguous` → report `year_evidence`
    verbatim to user (user changes slug or manually mv tmp);
    `download_failed` → fail. No more string-match parsing of agent
    reply prose. Preamble describing the inline chain rewritten to
    point at the agent contract.
  - `skills/process-author/SKILL.md`: Phase 1 replaces single
    narrative search-agent dispatch with two strict-contract
    dispatches (`kind=book` + `kind=paper`) writing
    `.quasi/authors/{slug}/{books,papers}.json`; skill merges into
    the canonical `manifest.json` shape Phase 2+ already expects.
    Phase 2 replaces single `mode=both` download-agent dispatch (no
    longer supported by agent contract since 0.24.0) with two
    structured dispatches (`kind=book` + `kind=paper`). Batch policy
    on book year mismatch: do NOT pause — skill overrides agent's
    "keep as tmp" signal, `mv`s tmp → final under slug-authoritative
    name, records `year_evidence` + a one-line `year_warning` for
    end-of-run report. Paper failures (fail-fast, no candidate
    retry) recorded with `failure_note`. Manifest status enum grows
    `year_mismatch` and `year_ambiguous`; resume-skip rules updated
    accordingly. Orchestration diagram updated to show
    `Phase 2: download-agent × 2`.
  - `skills/process-paper/SKILL.md` (new): single-paper end-to-end
    skill — `--doi` (preferred), `--slug` (PDF already in
    `sources/`), or `--title --author` (fallback). Opt-in
    `--translate` flag dispatches `translate-agent`. Reuses
    search-agent, download-agent, analyse-agent type=B, audit-agent,
    translate-agent with no new agent. No synthesis step;
    `analyse-agent type=B` already produces the full
    `vault/papers/{slug}.md` indistinguishable from
    `process-author` Phase 4 output. Trigger phrases: "处理这篇论文",
    "process paper", "跑这篇 paper", "summarize this paper".
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.
  - No bin changes, no Python changes, no user-disk migration.
    process-author manifests with `status: acquired` from earlier
    runs are consumed unchanged; new `status: year_mismatch` /
    `year_ambiguous` entries are treated as `acquired` by downstream
    Phase 3+ (file is on disk, just with a year warning attached).

- **0.27.0** (2026-05-18): **local-agent for cndouban backfill +
  douban_cn related-version probe.** Splits "find the Chinese
  translation of this book" out of the audit pipeline into its
  own narrow-scope agent, and gives the douban_cn source the
  capability to surface translations from a direct hit's other-versions
  block.
  - `agents/local-agent.md` (new): the only agent in quasi whose
    job is filling `cndouban: [...]` onto book frontmatter and
    maintaining `.quasi/audit/translations.json`. Reads
    `quasi-audit run --mode check --json`, filters
    `needs_backfill[]` to `type=book` + `missing=cndouban`, calls
    `quasi-search book --subject cndouban`, writes back. Idempotent
    on already-localised records (even `cndouban: []` is treated
    as "user already decided no Chinese edition exists" and
    skipped).
  - `scripts/search/sources/douban_cn.py`: new related-version
    probe path. When the caller passes `--subject
    zh/chinese/cn/translation/cndouban` **and** the direct search
    returns a hit, the source walks the subject page's `其他版本`
    / `同一作品` block and emits Chinese-like manifestations. Hint
    regex covers mainland presses (人民/三联/商务/译林/中信...)
    plus HK/TW patterns (聯經/時報/麥田/遠流/天下/印書館). Subject
    URL + works URL both normalised against `book.douban.com`.
    Pure addition — non-`zh` queries are unchanged; CJK-author
    fallback to works-page enumeration still triggers when direct
    returns empty.
  - `skills/process-book/SKILL.md`: new Step 6 LOCALISE, dispatched
    foreground after audit. Resume table documents the
    "frontmatter already has `cndouban` ⇒ skip" idempotency.
  - `skills/process-journal/SKILL.md`: Step 6 grows the same
    audit-escalation loop that `process-book` has had — items the
    audit escalates get one regeneration pass via `analyse-agent`
    (type B for journal papers), then re-audit; if still escalated,
    report and bail. Brings the two skills into structural parity.
  - `scripts/audit/audit.py` + `scripts/audit/sweep/README.md`:
    docstring/prose updates reflecting that online metadata
    backfill is its own workflow, not orchestrated by `audit-agent`.
    Sweep README's "Integration plan (future)" section is now
    just "Integration" — `quasi-audit backfill` is the actual
    dispatcher.
  - `agents/search-agent.md`: drop one redundant "不要在 prompt 里
    推该调哪个源" paragraph — the I/O contract already covers this.
  - `tests/test_douban_cn_en2zh.py` (new): end-to-end mock-driven
    test for the English-title → Chinese-translation pipeline.
    `test_source_douban_cn.py` grows a case proving the
    related-version probe fires when `--subject zh` and direct hits
    exist, and stays out of the way otherwise.
  - `docs/`: delete four stale design docs —
    `ADR-002-capability-layering.md`, `LAYERS.md`,
    `EXPERIENCE-vault-metadata-backfill.md`,
    `processing-schema.md`. The layered architecture they
    described was simplified away in 0.18.0; keeping them around
    misled both humans and Claude Code sessions opened in the
    source tree.

- **0.26.0** (2026-05-18): **artifact path discipline.** Sharpens the
  `processing/` vs `.quasi/` split on "would the user ever open this
  file?" Everything plumbing-shaped — manifests, indices, audit state,
  dispatch scratch, downloaded temp PDFs — moves into `.quasi/`.
  `processing/` ends minimal: `chapters/` (extracted text the user
  reads when PDFs are unclear) and `translations/` (translated PDFs).
  - Group B: `processing/proofread/{stem}/sections.json` →
    `.quasi/proofread/{stem}/`. Cleanup goes from optional to required.
  - Group C: `/tmp/{journal,topic,snowball}-pdfs/` →
    `.quasi/temp/{journal-pdfs/{name}, topic-pdfs/{name}, snowball-pdfs}/`.
    Brings temp PDFs into the project tree where they're inspectable
    and not subject to macOS /tmp/ reaping.
  - Group D: audit pipeline consolidates under `.quasi/audit/`.
    `scripts/typecheck/typecheck.py` `OUT_DIR` moves from `.quasi/`
    top-level to `.quasi/audit/`. `agents/audit-agent.md` doc paths
    fixed across multiple stale references (state.json,
    translations.json, typecheck-*). `scripts/schemas/book.py` description
    string + `docs/ARCHITECTURE.md` echo updated.
  - Group E: `processing/authors/{name}/manifest.json` →
    `.quasi/authors/{name}/manifest.json`. Driver file for the
    process-author phase state machine; user never opens.
  - Group A: residual cleanup. The bulk of the citation move was
    already merged in 0.22.x (`ct_dir = .quasi/citation/...`); this
    release finishes the trailing edges — citecheck-agent example,
    citation.py docstring, wrap-up 中间产物 tree. `render.py:741`
    has a stale reference too but render.py is deprecated per 0.22.0
    and skipped here.
  - User-disk migration: only `authors/{name}/manifest.json` carries
    a real caveat — any author run paused mid-flight loses its
    `--resume` state on upgrade. Finish or abandon before upgrading.
    Other stale dirs (`processing/citation/`, `processing/proofread/`,
    `processing/audit/`, top-level `.quasi/typecheck-*`) become
    harmless orphans the user can `rm -rf` at leisure.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.2** (2026-05-18): **rename citation-agent → citecheck-agent.**
  Naming consistency pass: most agents in quasi are verb-form
  (`search-agent` / `download-agent` / `extract-agent` / `proofread-agent` /
  `translate-agent` / `audit-agent` / `analyse-agent`); `citation-agent`
  was a noun-form outlier. Renamed to `citecheck-agent` (compare
  "spellcheck") to bring it into line.
  - `agents/citation-agent.md` → `agents/citecheck-agent.md` (`git mv` +
    frontmatter `name:` update).
  - Caller / cross-reference updates in `skills/wrap-up/SKILL.md`
    (Phase 2.2 dispatch + prose), `agents/proofread-agent.md` (cross-ref
    in 不动清单), `docs/ARCHITECTURE.md` (pattern table + DAG).
  - Historical references in `CLAUDE.md` Recent Changes entries
    (0.16 / 0.17 / 0.18 / 0.20 / 0.22 / 0.25.1) and in the committed
    spec / plan docs are **left intact** — they record what the agent
    was called at the time.
  - Caller-visible breaking change: any external invocation
    `Agent("quasi:citation-agent", ...)` must switch to
    `Agent("quasi:citecheck-agent", ...)`. All in-tree callers updated
    in the same commit.

- **0.25.1** (2026-05-18): **citation-agent vault-grounded judgment.**
  Phase 2.2 of `quasi:wrap-up` historically had `citation-agent` judge
  context-fit by reading `biblio.json` metadata fields
  (`title / journal / themes / publisher`) plus LLM prior knowledge.
  That meant judgments for obscure / non-English / idiosyncratically-read
  works degraded into hallucination. Re-grounded:
  - `agents/citation-agent.md` rewritten so each candidate is judged by
    reading the user's actual vault summary file (`vault/papers/{slug}.md`
    or `vault/books/{slug}/00-overview.md`) via `candidate.path` — already
    present in manifest since 0.17.0. New "严禁仅凭 title / publisher /
    LLM 先验知识判断" guard in the judgment guidance.
  - `biblio.json` dropped from the agent's input contract.
    `skills/wrap-up/SKILL.md` Phase 2.2 dispatch no longer passes
    `biblio:` to the agent. `biblio.json` is still produced upstream and
    consumed by `resolve.py` (for manifest building) and `emit_bib.py`
    (for the final .bib) — those uses are unchanged.
  - No Python script changes. `path` field on candidate was already
    propagated from `biblio.py:230` → `resolve.py:101` since the 0.17.0
    citation refactor; this release just starts using it.
  - Token cost: net byte volume to the agent goes **down** (drops a
    whole-vault frontmatter index, picks up a handful of scoped summary
    reads per batch). Main-process context unaffected — same prompt
    shape with one fewer path.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.0** (2026-05-18): **agent surface cleanup post-search-refactor.**
  Lands the long-lived `quasi-arch-refactor` branch into main and tidies
  the agent file naming after 0.24.0's atomic search-bin cutover.
  - `agents/new-discover-agent.md` → `agents/search-agent.md` (146 → 119
    lines). Frontmatter `name:` updated; content rewritten against the
    new bin: dropped the trust/priority table (bin does
    `match_and_priority` internally), dropped per-source fallback table
    (bin internal fallback handles douban_cn works-page / etc), fixed
    envelope shape to `{kind, query, results, diagnostics}`, corrected
    source counts (8 book + 3 paper), confidence heuristic now keyed on
    `sources_hit` + `conflicts`, output protocol renamed
    `DISCOVER_RESULT` → `SEARCH_RESULT`.
  - `agents/discover-agent.md` deleted — superseded by `search-agent`;
    all callers (process-author, wrap-up Phase 2.5, process-book Step 0)
    migrated on the refactor branch.
  - `process-author/SKILL.md` and `scripts/search/context.md` rename
    references updated.
  - No bin-layer change. Pure agent file rename + caller rewire.

- **0.24.0** (2026-05-17): **search bin complete refactor (BREAKING).**
  Historical implementation plan docs were removed after completion; the
  active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
  the skill / agent files.
  - 2137-line `scripts/search/search.py` replaced by sectioned ~700-line
    `search.py` + 9 per-platform adapters in `sources/`.
  - CLI: only two verbs left — `quasi-search book` / `quasi-search paper`.
    `metadata` / `validate` / `scholar` / `backfill` / `cndouban` / `books` /
    `papers` removed entirely (no back-compat).
  - AA file-locate moved to `scripts/download/aa.py` (Python import only,
    no CLI verb). `download-agent` calls it directly.
  - Backfill dispatcher + sweep scripts moved to `scripts/audit/`.
    `quasi-audit backfill --strategy X` replaces `quasi-search backfill`.
  - Unpaywall / S2 / Wayback adapters dropped (enrich cascade non-goal).
  - Conflict surfacing: every fan-out call's diagnostics carries
    `conflicts[].evidence` for year / isbn_13 / publisher / page_count /
    authors — process-book Step 0 YEAR_TRIAGE now reads this rather than
    re-calling each source. Generalises 0.21.0's `year_signals` hack.
  - Callers migrated in same PR: `new-discover-agent.md` (delete routing
    table), `process-book` / `process-topic` / `process-author` /
    `wrap-up` (verb rename + remove validate/metadata batch calls),
    `download-agent.md` (AA via Python import), `discover-agent.md`
    (verb rename + delete validate/scholar).

- **0.22.0** (2026-05-17): **citation review pivots to TUI — HTML report
  - structured verdict enum deprecated.** Background: 0.20.0's tab-based
  HTML review still had a coarse fit between agent output shape and what
  the user actually had to do per cite — and earlier reflection on the
  Decisions Report json export (274 entries, ~10% had unstructured-note
  carryover that the buckets couldn't capture) showed the agent's
  structured verdict was both token-wasteful and less useful than a
  short context-fit note. User's diagnosis: "我们之前犯的错就是太结构化了".
  - **citation-agent rewritten** to output a minimal `{key, picked_slug,
    flag, note}` per cite. Drops the 4-way verdict enum (ok /
    context-mismatch / maybe-vault-typo / missing-from-vault) entirely.
    Agent only does two things now: pick the bib_source from candidates
    (single → the only one; multi → context-fittest), and flag ok or
    review for upper-layer triage. Note is free-form Chinese.
  - **wrap-up Phase 2 restructured** into 2.1 parse+resolve → 2.2
    citation-agent (single+multi only) → 2.3 discover-agent recover
    (miss only) → **2.4 TUI 审定** → 2.5 decisions.json + emit-bib.
    Phase 2.4 is a main-process AskUserQuestion loop, walking bins in
    dimension order (`review_single` / `review_multi` / `miss_recover` /
    `miss_orphan`) — `flag=ok` cites auto-accept with no user prompt.
    Each prompt shows mention snippet + agent's picked_slug + note;
    options vary by bin (accept / pick another candidate / mark
    draft-rewrite / vault-todo / skip).
  - **HTML review.html no longer driven by the skill.** `render.py` /
    `quasi-helpers citation render` is retained on disk but is now
    **stale** — it expects the old verdict enum (`ok` / `context-mismatch`
    / `maybe-vault-typo` / `missing-from-vault`) and will not render
    cleanly against the new `{key, picked_slug, flag, note}` batch
    format. Will be either rewritten against the new shape or deleted
    in a future minor; not blocking. The Phase 3 SUMMARY HTML is
    dropped — TUI prints a final stats block + paths inline.
  - **decisions.json schema preserved at the seams** — top level still
    `by_key: {key: {bib_source, decision, note}}` (what emit_bib.py
    consumes via `_pick_vault_slug`) plus `vault_todo[]` and
    `draft_rewrites[]` arrays for the user's follow-up work. emit_bib
    unchanged.
  - `--citation-only` flag now skips Phase 0/1/3 (cleanup), runs only
    Phase 2 (parse → agent → recover → TUI → emit). `--no-recover` still
    skips 2.3.

- **0.21.0** (2026-05-17): **year triage overhaul — N-source contract,
  structured PDF year signals, Google Books via dokobot.** Triggered by a
  failure case where Simondon's *Imagination and Invention* (UMN Press
  English translation, canonical year 2023) kept finalising as 2022.
  Root causes were 4 independent bugs stacked:
  - `_guess_year` in `scripts/download/download.py` returned the *first*
    `\b(?:19|20)\d{2}\b` regex hit in front matter — for translations this
    is almost always the original-language year ("Originally published in
    French as ... 1965"). Replaced with `_extract_year_signals` returning
    a structured dict `{first_published, copyright_year, original_year,
    other_years, best_guess, evidence_text}`. Anchors on
    "First published / First edition / Published" patterns, treats
    "Copyright YEAR" separately, and never lets "Originally published"
    or "Translated from" leak into best_guess. Includes a Q4-press
    heuristic: if `copyright == YEAR` and `YEAR+1` or `YEAR+2` also
    appears in front matter, prefer the later one (typical for press
    books copyrighted in Q4 and shipped the following year).
    `verify_book_file` returns `year_signals` alongside `year`;
    `finalize_book_identity` propagates it into the manifest entry.
    Back-compat shim `_guess_year` still exists, calling
    `_extract_year_signals(...)["best_guess"]`.
  - `process-book/SKILL.md` Step 0 prompt previously asked the agent
    for a slug / ol / pdf 3-way compare but named the discover-side year
    `ol_year` regardless of which source it came from — almost always
    Anna's Archive, since AA is the only source that yields an MD5.
    Rewritten as YEAR_TRIAGE: agent reports per-source years separately
    (`source_years: {google_books, openlibrary, openalex, anna_archive}`),
    per-pattern PDF signals (`pdf_signals: {first_published,
    copyright_year, original_year, other_years}`), a `recommended_year`
    with a one-line `recommendation_reason`, and a `verdict ∈ {MATCH,
    MISMATCH, AMBIGUOUS}`. Only `MATCH` finalises the file rename;
    other verdicts keep the `.tmp.{ext}` and surface the full triage
    block to the skill main process for user adjudication.
    `download-agent.md` finalize-doc updated to describe the new
    `year_signals` field and the N-source contract.
  - `search_google_books` was hitting the unauthenticated
    `googleapis.com/books/v1/volumes` endpoint, which returns HTTP 429
    with `RATE_LIMIT_EXCEEDED` (quota=0 on the default project) — i.e.
    the Google Books source was silently dead, cutting cross-verification
    from 3 sources to 2 without anyone noticing. Refactored into
    `_search_google_books_http` (existing path) + `_search_google_books_via_doko`
    (new, scrapes `google.com/search?tbm=bks` via `dokobot read --local`,
    falls back to remote mode if no bridge installed). Wrapper detects
    HTTP 429 / `RATE_LIMIT_EXCEEDED` and dispatches automatically.
    Returns parsed entries (title / authors / year via `AUTHOR · YEAR`
    pattern) plus a `raw_doko_text` field so agents can re-parse when
    the structured parse looks thin.
  - The agent-prompt heuristic "pdf_year = 出现的最大 published year,
    排除 reprint dates" couldn't distinguish copyright year from
    publication year — the new N-source contract makes the agent
    enumerate both `copyright_year` and `first_published` separately
    instead, so the skill main process sees the actual structure.

  Net: Simondon's book now triages as `pdf_signals.first_published=2023,
  pdf_signals.copyright_year=2022, pdf_signals.original_year=1965`,
  GB+OL=2023, AA=2022 — `recommended_year=2023` with reason "first_published
  beats copyright by 1 year (Q4 press lag)", and the slug `-2017` shows
  up as MISMATCH for user correction rather than auto-finalising to 2022.

- **0.20.0** (2026-05-17): **citation review UI — tabs by dimension,
  decisions grouped by side-effect.** Background: the previous review.html
  rendered a flat table with uniform `✓ ✗ ?` per row whose "✓ accept agent
  suggestion" semantics differed wildly across statuses (apply draft rewrite
  / run vault mv / pick candidate / nothing-to-apply for `ok`). User found
  the buttons misleading — particularly `ok` rows showing "accept" when
  there's nothing to accept, and a sea of `?` for rows agent didn't process.
  - render.py: replaced the 3-state filter (全部/需处理/已通过) with a
    7-tab nav by display_status: 全部 / 挑候选 / 修 draft / 修 vault /
    补 vault / 等 agent / ✓ 通过. Each tab shows count.
  - new `_action_widget()` renders per-dimension actions:
      ok                  → "✓ 通过" read-only badge
      pending             → "⏳ 等 agent" read-only badge
      context-mismatch    → [✓ 应用] [✗ 保留原引] (default 应用)
      maybe-vault-typo    → [✓ 执行 rename] [✗ 忽略] (default 忽略;
                            renames are destructive, opt-in)
      missing-from-vault  → [✓ 加待跑] [✗ 忽略] (default 加 if Phase 2.5
                            recovered with ≥medium confidence)
      multi-hit           → badge → "展开选 bib chooser radio"
  - JS exportDecisions now emits 4 grouped buckets:
      draft_rewrites     (context-mismatch + applied)
      vault_renames      (maybe-vault-typo + applied)
      vault_todo         (missing-from-vault + applied)
      multi_hit_picks    (multi-hit + bib chosen)
    plus a `skipped` group and a flat `by_key` for backward compat.
  - apply-bar at top of report instructs user to run
    `quasi-helpers citation apply <decisions.json>` (subcommand not yet
    implemented — coming in next minor version; for now decisions.json
    is enough to drive things manually).

- **0.19.1** (2026-05-17): wrap-up `--citation-only` flag.
  Skips Phase 0 (audit) + Phase 1 (proofread) + Phase 4 (cleanup), runs
  Phase 2 + 2.5 + 3 only. Use after补 vault'd a few books — re-emit bib
  in seconds without re-proofreading. Also documents `--no-recover` and
  `--audit-first` flags more explicitly in the call-shape section.

- **0.19.0** (2026-05-17): **wrap-up Phase 2.5 — online citation recovery.**
  When citation-agent flags an entry as `missing-from-vault`, the existing
  flow could only say "vault 缺,补完再重跑". This release adds an online
  step: discover-agent gains a new `mode=recover-citation` that takes the
  citation key + author + year_hint + mention_context + citation-agent's
  prior-knowledge guess, hits quasi-search (Crossref/OL/AA + scholar
  fallback), and emits an `online_recovery` record with title / author /
  year / ISBN / DOI / publisher / confidence / suggested_slug /
  process_book_cmd. wrap-up dispatches one discover-agent per missing
  entry in parallel (cap 4) after citation-agent finishes; render.py
  merges `verdicts/recovery-*.json` into the review UI so each
  missing row shows a "🔍 在线 recover" block with the recovered ID.
  This converts vault-todo from "list of names to look up" into "list of
  ready-to-paste `/quasi:process-book {slug}` commands". Opt-out with
  `/quasi:wrap-up <draft> --no-recover` to skip the online step.

- **0.18.1** (2026-05-17): process-book Step 0 hardening.
  - Self-dispatches download-agent when `sources/{slug}.{epub,pdf}` is
    absent — no longer bails out telling the user to "先用 process-author".
    The skill is orchestration; acquisition is part of orchestration.
  - download-agent prompt now replicates process-author's
    discover→download→finalize 3-stage chain (N=1 version): pre-download
    `quasi-search books` records `ol_year`, post-download Read PDF first
    3 pages records `pdf_year`, 3-way compare against `slug_year`. Any
    mismatch returns `YEAR_MISMATCH` report (skill main process decides
    whether to correct slug or accept) — file kept as `.tmp.{ext}` until
    resolution. Prevents the "user-supplied slug year propagating through"
    failure mode (e.g. user passes `simondon-...-2024` for a book whose
    canonical first English edition is 2023).

- **0.18.0** (2026-05-17): **Layer-cleanup refactor (BREAKING).** End-to-end
  rework of the bin / agent / skill split per `docs/LAYERS.md` and
  `docs/ARCHITECTURE.md`. Drives Pattern B (skill 直调 bin) out of the
  layer model by aggregating skill helpers into a single `quasi-helpers` bin.
  - **bins**: 13 → 6. Deletions: `quasi-typecheck`,
    `quasi-autofix-mechanical`, `quasi-proofread`, `quasi-citation`,
    `quasi-extract-{epub,ocr,split}`, `quasi-journal-{fetch,report}`,
    `quasi-synthesize-refs`. The last three are **deletion-as-forcing-
    function**: synthesis-agent's journal/topic mode will fail until the
    refs-extraction redesign (Q3) and journal stack rework land. New:
    `quasi-audit {check|fix|emit-bib}` (vault consistency dispatcher),
    `quasi-helpers {proofread|citation} <sub>` (skill orchestration aggregator).
    Subcommand restructure: `quasi-extract {epub|ocr|split}`,
    `quasi-download {paper|book|batch|finalize}` (was flag-based),
    `quasi-search` + `scholar` (dokobot Google Scholar) + `backfill`
    (vault metadata multi-source chain; ingests bts/scripts 8 sweep scripts
    documented in `docs/EXPERIENCE-vault-metadata-backfill.md`).
  - **agents**: `typecheck-agent` → `audit-agent` with new online
    metadata backfill responsibility. `analyze-agent` → `analyse-agent`
    (British spelling). `overview-agent` + `profile-agent` + 原 `synthesis-agent`
    → unified `synthesis-agent` with caller-passed `mode = book|author|
    journal|topic|kb-update`. `scan-agent` / `setup-agent` marked DEPRECATED
    (files retained, not dispatched by new code).
  - **skills**: `citation-snowball/` → `process-topic/` (rename only,
    internal redesign deferred). `wrap-up/SKILL.md` now calls `quasi-helpers
    {proofread,citation} *` and gains a Phase 0 audit-agent dispatch.
    `process-book` / `process-author` migrated to `synthesis-agent(mode=X)` +
    `audit-agent`.
  - **Deferred** (next round): entire journal stack
    (`quasi-journal-{fetch,report}` / `scan-agent` / `/quasi:process-journal`
    skill / `quasi-search journal` subcommand); `setup-agent` redesign;
    `process-topic` internal redesign; `quasi-synthesize-refs` disposition.

- **0.17.0** (2026-05-17): **Citation pipeline refactor — biblio.json as ground truth.**
  Driven by ADR-002 (see `docs/ADR-002-capability-layering.md`): citation
  flow now reads a pre-computed `biblio.json` instead of glob-walking the
  vault each call. New artefacts in `scripts/citation/`:
  - `biblio.py` scans vault frontmatter into `biblio.json` (multi-segment
    author-slug indexing so multi-word surnames like `agard-jones` /
    `fausto-sterling` resolve correctly)
  - `resolve.py` rewritten: input is `parse.json` + `biblio.json`,
    output is `manifest.json` with `{single-hit, multi-hit, miss}` status
    and 4-tier fuzzy fallback (strict → author-only → fuzzy author+year → miss)
  - `render.py` rewritten: single-decision review UI, bib chooser per row,
    top banner for missing-from-vault + maybe-vault-typo
  - `emit_bib.py` (new) renders BibTeX from `biblio.json` keyed by the draft's
    citation set; honours user-picked `bib_source` from decisions.json
  - `citation.py` subcommands: `biblio` / `parse` / `resolve` / `render` /
    `emit-bib` (removed `run` — orchestration belongs in the skill, not the CLI)
  `citation-agent` rewritten as **offline universal consistency judge**
  (no WebFetch / WebSearch): verdict ∈ `{ok, context-mismatch,
  maybe-vault-typo, missing-from-vault}`. Online cross-checking for vault
  metadata moves out of citation entirely (slated for `quasi-audit` in a
  future release). `skills/wrap-up/SKILL.md` is **not yet updated** for the
  new pipeline — TODO next.
- **0.16.0** (2026-05-15): **New `quasi:wrap-up` skill + two reusable agents**
  (`proofread-agent`, `citation-agent`). Drift finalisation in one shot —
  Phase 1 proofread (per-section parallel agents in-place edit typos /
  punctuation / spacing), Phase 2 citation (parse + vault lookup CLI →
  per-batch parallel agents do online cross-verification against Crossref /
  Anna's / Douban via dokobot), Phase 3 summary HTML linking both reports.
  Design rule: **skills only exist for composition; single-task work is
  done by dispatching agents directly** — so no standalone `citation` or
  `proofread` skills. New files: `skills/wrap-up/SKILL.md`,
  `agents/{proofread,citation}-agent.md`,
  `scripts/{proofread,citation}/*.py`,
  `bin/quasi-{proofread,citation}`. Citation parse-step ships a loose-scan
  validator (any paren-with-4-digit-year) to catch what the strict parser
  misses before downstream consumers see the data.
- **0.15.3** (2026-05-13): Doc/script rename — `$PWD` → `$CLAUDE_PROJECT_DIR`
  across all 11 agent prompts, `bin/quasi-typecheck`, and the two typecheck
  scripts' docstrings/help. Aligns with the official plugins-reference
  recommendation: `$CLAUDE_PROJECT_DIR` is set by Claude Code at session start
  and doesn't drift if anything `cd`s; `$PWD` is just the shell's transient
  cwd. `typecheck.py` / `autofix_mechanical.py` `PROJECT_ROOT` resolution now
  consults `CLAUDE_PROJECT_DIR` between the existing `QUA_PROJECT_ROOT`
  escape hatch and the `os.getcwd()` fallback — no behavior change when
  invoked from the project root (the common case), but stable under `cd`.
- **0.15.2** (2026-05-12): PreToolUse hook also propagates `CLAUDE_PLUGIN_ROOT`
  and `CLAUDE_PLUGIN_DATA` to bash subprocesses (in addition to the userConfig
  `QUASI_*` block). Before this, the shims fell back to `~/.cache/quasi/.venv`
  for the venv because `$CLAUDE_PLUGIN_DATA` was unset in Bash-tool env, even
  though the SessionStart hook had already materialised the venv at the
  official `$CLAUDE_PLUGIN_DATA/.venv` (= `~/.claude/plugins/data/<id>/.venv`).
  Now shims use the official path. Users with the old fallback venv can
  `rm -rf ~/.cache/quasi/.venv` to reclaim disk.
- **0.15.1** (2026-05-12): Trim `setup-agent.md` (166 → 122 lines). Drop the
  obsolete "credentials don't live here" callout and "调用方约定 (主 Claude 应
  AskUserQuestion 收集凭据)" section — neither makes sense after 0.15.0's hook
  bridge. No functional change.
- **0.15.0** (2026-05-12): **Breaking.** Final config resolution: PreToolUse hook
  bridge. The docs claim `CLAUDE_PLUGIN_OPTION_*` env vars reach "plugin
  subprocesses" but empirically Bash-tool subprocesses don't get them — only
  hooks/MCP/LSP/monitor do. Solution: a PreToolUse(Bash) hook
  (`scripts/hooks/inject-userconfig.py`) runs in a real plugin subprocess, reads
  its env, and prepends `export QUASI_<KEY>=...;` to any `quasi-*` shell
  command before Claude Code executes it. Scripts read clean `QUASI_*` env
  vars. Sensitive userConfig fields stay in the macOS keychain — they only
  materialise in the hook+bash process env for one tool call at a time. Also
  renames all `bin/qua-*` shims to `bin/quasi-*`. Probe agent removed.
- **0.14.1–0.14.3** (2026-05-12): Diagnostic releases — probe agents and probe
  hooks to map out which subprocess types actually receive `CLAUDE_PLUGIN_OPTION_*`
  env injection. Results: only the 4 documented types (hook/MCP/LSP/monitor) do;
  Bash-tool subprocesses and Task-tool subagents do not. Drove the 0.15.0 design.
- **0.14.0** (2026-05-12): **Breaking.** Anna's Archive and Immersive Translate
  credentials follow CookieCloud into plugin `userConfig`. New userConfig fields:
  `anna_donator_key` (sensitive), `anna_mirrors` (multiple, defaults to 3 official
  mirrors), `immersive_auth_key` (sensitive). `download.py` / `search.py` /
  `immersive_translate.py` no longer read `config/anna-archive.json` or
  `config/immersive-translate.json` — fully env-var driven. `setup-agent` becomes
  purely permissions + system deps + dokobot indicator; the entire `$CLAUDE_PROJECT_DIR/config/`
  directory is now optional and quasi never writes there.
- **0.13.0** (2026-05-12): EZProxy creds moved to `userConfig` (CookieCloud).
  Removed `config/cookiecloud.json` and `config/ezproxy.json` reading.
- **0.12.1** (2026-05-12): Drop `setup-agent` Step 0 (plugin self-install bootstrap).
  Installation is now the canonical `/plugin marketplace add giraphant/quasi` +
  `/plugin install quasi@ramu-toolkit` flow; `setup-agent` is purely env + creds.
  README install section rewritten to match.
- **0.12.0** (2026-05-12): CookieCloud auto-refresh for EZProxy. Initial `config/
  cookiecloud.json` + `config/ezproxy.json` file-based flow — superseded by 0.13.0.
- **0.11.0** (2026-05-12): Python venv extracted from per-shim inline pip into a
  `SessionStart` hook + bootstrap script. Shims now ~half the size. Persistent venv
  lives in `$CLAUDE_PLUGIN_DATA` (or `~/.cache/quasi/`), never in plugin root.
- **0.10.0**: SPEC v0.2 schema + typecheck-agent + bin shims.
- **0.9.0**: Unified setup-agent (bootstrap + config).
