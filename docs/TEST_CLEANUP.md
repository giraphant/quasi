# 2026-11-03 测试清理摸底

以配置提交 `8957811` 为清理基线，共 48 个测试文件、1019 项参数化测试。归类按测试实际覆盖的行为，混合文件逐部分处理，不以文件名里的 receipt、manifest、legacy 为删除依据。

调用链从 `SKILL.md`、`collect/`、`research/`、`connectors/` 的 quasi 命令开始，核对 `scripts/commands/` 和 Python 调用方。四类指定活契约（Marple schema、中文版本 sidecar、Archive manifest 0.2、PDF/OCR/翻译不变量）优先保留。

| 文件（tests/） | 分类 | 依据与处理 |
|---|---|---|
| `test_archive.py` | 能力行为 | archive schema、audit、status、vault resolve、topic membership；保留。 |
| `test_archive_collection.py` | 能力行为 | archive collect/read 与 manifest 0.2；保留发布、原件校验和并发测试。 |
| `test_archive_directory_collections.py` | 能力行为 | archive 路径与 Marple 合集移动锁；保留。 |
| `test_archive_pdf_inspection.py` | 能力行为 | archive inspect 的 PDF 下载、预览和失败清理；保留。 |
| `test_audit_cli.py` | 能力行为；接口形式 | 保留实际修正、诊断、只读报告；删旧 run 命令不存在的测试及固定回执版本/字段集合断言。 |
| `test_audit_field_distribution.py` | 能力行为 | audit --report fields/toc 仍调用 field_distribution；保留。 |
| `test_audit_readonly_contract.py` | 能力行为 | 保留不写磁盘、未知 H2 提示、报告范围；删固定回执版本断言。 |
| `test_block_list_yaml.py` | 能力行为；死功能 | 保留 audit 调用的 autofix；删独立 sweep-clean 的 2 项测试及不再可达的 sweep/backfill 代码。 |
| `test_bootstrap_venv.py` | 能力行为 | 各 shim 的依赖同步及失败停止；保留。 |
| `test_citation_review_cards.py` | 接口形式（仍可达） | 批次 verdict 的汇总仍由 helpers citation review-cards 提供；现有 shim 会到达，保留。 |
| `test_compress_media.py` | 能力行为；接口形式 | 保留 ffmpeg 复用、文件标记、路径与原子发布；仅移除结果中无人读取的宿主标记。 |
| `test_config.py` | 能力行为 | Keychain、安全输出、默认值、优先级及非密钥 get；保留。 |
| `test_core.py` | 能力行为 | 活模块共享的根目录、路径、frontmatter 和原子 JSON 写入；保留。 |
| `test_doctor_cli.py` | 能力行为；接口形式 | 保留依赖检测和退出码；删除已移除 dokobot 的缺席断言及回执版本断言。 |
| `test_download_cli.py` | 能力行为；接口形式 | 保留下载、身份验证、代理、限流、接收与并发；删旧 flag/batch 入口已移除的 2 项测试。 |
| `test_extract_cli.py` | 能力行为 | text/ocr/ocr-generation/split 与实际 manifest 读取、恢复、并发；全部保留。 |
| `test_extract_epub_cli.py` | 能力行为 | epub 切章、排除、spine 顺序、失败保留和复用；全部保留。 |
| `test_layout_review.py` | 能力行为 | 源文件绑定的版面人工复核、图像保留和免重推理；全部保留。 |
| `test_localise_helper.py` | 能力行为 | Marple 使用的 .quasi/localise/cndouban.json，及 ISBN 合并；保留。 |
| `test_ocr_mineru.py` | 能力行为 | PDF_PIPELINE 的引擎、排版、证据、字符与空白页规则；全部保留。 |
| `test_pdf2zh_translate.py` | 能力行为；死功能 | 保留活 provider 的命令、配置、候选发现；删独立 translate_slug 发布和只由该入口使用的调参测试，共 10 项；共同门槛迁入 translate_cli。 |
| `test_proofread_helper.py` | 能力行为；接口形式 | prepare/cleanup 仍有 shim；保留行为，删除旧 split/init 不存在的测试。 |
| `test_schema_registry.py` | 能力行为；接口形式 | 保留产物 schema 和正文验证；删除旧网页 agent/phase/effect 目录测试及已无调用方的生成者 JSON 投影断言。 |
| `test_schema_snapshot.py` | 接口形式（活契约） | Marple 的 .quasi/schema.json；版本、required 字段和原子幂等写入全部保留。 |
| `test_search_cli.py` | 能力行为；接口形式 | 保留 Kagi 与中文本地化；删旧 shape/output 选项缺席的测试和帮助文本断言。 |
| `test_search_main.py` | 能力行为 | 实际 adapter 扇出、合并、错误及中文 sidecar；保留，SearchResponse 仍由 CLI 输出。 |
| `test_search_merge.py` | 能力行为 | 身份合并、冲突与 Crossref journal 优先级；保留。 |
| `test_search_schemas.py` | 接口形式 | 仅复写 dataclass 默认值与完整字段集合，6 项全部删除；活的 record/query/response 类仍供 adapter、合并与 CLI 使用。 |
| `test_search_source_amazon.py` | 能力行为 | search book/paper 实际调用的 amazon adapter；保留。名字中的 legacy 指仍在调用的抓取函数，不代表死功能。 |
| `test_search_source_crossref.py` | 能力行为 | search book/paper 实际调用的 crossref adapter；保留。 |
| `test_search_source_douban_cn.py` | 能力行为 | search book/paper 实际调用的 douban_cn adapter；保留。 |
| `test_search_source_goodreads.py` | 能力行为 | search book/paper 实际调用的 goodreads adapter；保留。名字中的 legacy 指仍在调用的抓取函数，不代表死功能。 |
| `test_search_source_googlebooks.py` | 能力行为 | search book/paper 实际调用的 googlebooks adapter；保留。 |
| `test_search_source_openalex.py` | 能力行为 | search book/paper 实际调用的 openalex adapter；保留。 |
| `test_search_source_openlibrary.py` | 能力行为 | search book/paper 实际调用的 openlibrary adapter；保留。 |
| `test_search_source_scholar.py` | 能力行为 | search book/paper 实际调用的 scholar adapter；保留。 |
| `test_search_source_storygraph.py` | 能力行为 | search book/paper 实际调用的 storygraph adapter；保留。名字中的 legacy 指仍在调用的抓取函数，不代表死功能。 |
| `test_skill_tree.py` | 能力行为 | 页面路由、CLI、入口权限、维护说明和不恢复 Workflow 的架构约束；全部保留。 |
| `test_status_cli.py` | 能力行为；接口形式 | 保留磁盘事实、产物模板、manifest、symlink 与扫描；删除旧 --identity 选项不存在的测试。 |
| `test_tounicode.py` | 能力行为 | 实际 CMap 修复；全部保留。 |
| `test_transcribe.py` | 能力行为 | 转写分段、语言与讲座正文生成；全部保留。 |
| `test_transcribe_cli.py` | 能力行为；接口形式 | 保留转写发布、manifest 校验、复用、视频身份和并发；仅移除输出中无人读取的宿主标记。 |
| `test_translate_cli.py` | 能力行为 | 统一 observe/run 事务、源选择、provider 状态、锁、恢复和质量门槛；保留，并新增两后端的页数门槛及修复/覆盖率顺序共 8 项运行时测试。 |
| `test_translate_coverage.py` | 能力行为；死功能 | 保留全部数值与参考文献范围规则；删除同时检查两个死发布入口的 AST 顺序测试，迁为活事务的运行时验证。 |
| `test_translation_recovery.py` | 能力行为 | 保留 recognition 复用、版面错误定位、锁和正式输出观察；删 effect 字段断言。 |
| `test_typecheck_contract.py` | 能力行为 | 保留 schema、别名、未知 H2、不落盘和诊断稳定性；删回执版本断言。 |
| `test_vault_resolve.py` | 能力行为 | 技能实际调用的去重、身份索引和路径防护；全部保留。 |
| `test_webpage_cli.py` | 能力行为 | inspect/capture/extract 与原生 WebKit helper、超时、取消、缓存和发布；全部保留，并补 2 项回归测试：本地期限到达后不再采样、最后一次采样后网络变化仍须拒绝。 |

`fixtures/translation_language_tags.json` 是活翻译与 status 测试使用的语言标签样例；`webpage_test_support.py` 是活 WebKit 测试的本地 HTTP fixture。两者保留。

删除边界：

- `audit/backfill.py` 和 `audit/sweep/` 只有内部相互引用及两项 sweep 测试，没有技能、shim 或活模块入口。
- 两个翻译 provider 的 `translate_slug`、独立 main/parser、旧来源寻找和旧输出路径辅助函数没有 shim 或活调用方；当前 `translate.py`（包括保留的 legacy 适配层）调用 `translate_to_candidate` 和 `translate_commit.run_transaction`。删除的调参分支在活路径中始终收到空列表。
- `schemas/contracts.py::artifact_contract_for_type` 只剩 __init__ 导出及测试，没有生产调用；Marple 的 emit_schema 直接读取 TYPE_REGISTRY，不经过它。
- OPERATION_CATALOG 的唯一生产读取方 status 只读取 artifacts，保留原路径模板，删除 agent/phase/effect/kinds 及没有产物的旧操作。
- Talk 的回执 schema/key/effect/固定 attempt/material_key/artifact_roles 没有读取方；这些只从 CLI 结果移除。Talk manifest 的版本、失败字段和产物角色仍由恢复逻辑读取，保留。翻译只移除无人读取的 key/effect，保留参与未知任务恢复的 RUN_SCHEMA、持久化 receipt 和 derivative_key。

保守留下的项目：

- helpers citation/proofread 尚无新 draft 技能调用，但仍有公开 shim 分支和维护说明中的 CLI 契约；没有擅自撤销。若要一起下线，应另行决定删除这些公开入口。
- translate legacy 仍由 quasi-translate shim 转发，保留；它已经走统一事务，没有保留被删除的后端独立发布器。
- 固定旧 OCR progress 和 DS generation 的只读恢复仍由 extract/status 到达，且 PDF_PIPELINE 明文要求保留，不能作为旧 Workflow 游标删除。
- BodySchema 的 H1、身份和 evidence_rules 描述虽已无 JSON 投影读者，仍被维护说明视作写作结构的依据；本轮不删这些语义说明，也不改变任何阅读页结构。
- audit 的只读 fields/toc/typecheck 报告仍是当前 audit 参数分支；search 的结构化元数据仍由 adapter 和 CLI 消费，均保留。

计数按 pytest 收集项（展开参数化）统计：纯清理删除 27 项旧测试，新增 8 项活事务验证，1019 → 1000；全量复测发现 WebKit 期限边界竞态，另补 2 项回归测试，最终为 1002 项，净减 17 项。纯清理提交的生产 Python 删除 3094 行、增加 63 行，净减 3031 行；测试净减 394 行；连同 shim 和文档合计净减 3465 行（不含本报告、重构记录、PyMuPDF 导入兼容修复及另行提交的 WebKit 修复）。

验证结果：清理前全量 956 passed / 63 failed（1019 项），失败均为 PyMuPDF 旧 fitz 导入提示污染 JSON；修复导入后的 372 项相关测试通过。首次清理后全量 999 passed / 1 failed（1000 项），定位并修复 WebKit 本地期限后额外采样的竞态，新增两项回归；最终全量 1002 passed，6 warnings，253.32 秒，无跳过。命令为 `/tmp/quasi-test-venv/bin/python -m pytest tests -q`；环境安装了完整 `scripts/requirements.txt` 和 pytest。
