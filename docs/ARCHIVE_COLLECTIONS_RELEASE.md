# Archive Collections — 发布交接

2026-09-23 初次交接时已按用户要求直接适配，未 bump version、未提交发版，也未移动真实 vault。
仓库原有的 Webpage/agent 修改保留；生成 Workflow 包含这些现有来源的最新投影，发布时不要
将它们误当成本次独立变更或回退。

## 已实现

- `scripts/archive/paths.py`：发现根目录 Archive 或一层带 collection.md 的合集；拒绝歧义、
  重复 slug、嵌套合集及符号链接。slug 在整个 archives 下唯一；合集名允许中文和空格。
- status、scan、vault resolve、URL owner 查找使用真实位置；collect 在锁内定位现存档案，
  新档案仍放根目录，不因分组产生副本。
- revision 包含当前目录，移动后旧 observation 失效；必须 fresh status 后继续采集。
- collect 共享锁 `.marple/archive-collections.lock` 与 Marple 目录整理的排他锁互斥；
  未完成 Marple 操作日志阻止继续写入。audit/手工编辑不在此互斥范围。
- Topic card archives 接受合集路径，Workflow 使用观察得到的 archiveDirectory，输出
  archive.md、manifest.yaml、originals 的 exact refs。manifest/0.2 无变化。
- schema 是唯一来源，生成产物用 `npm run build:workflows` 更新；未手改生成文件。

数据与协作合同详见 [ARCHIVE_STORAGE.md](ARCHIVE_STORAGE.md)。
不新增 collection manifest、members 列表、collection_id，也不扩展 Book。

## 验证与发版

已运行 `npm run check:workflows`；Archive、Topic、status、resolve、schema、dead names、
技能合同共 194 项测试通过。新增 `tests/test_archive_directory_collections.py` 覆盖移动后
再次采集、旧 revision 阻断、不生成副本、重复 slug、标记、互斥锁及生成 Workflow exact refs。

本机测试用 `uv run --no-project --with pytest --with 'pymupdf<1.27' --with-requirements scripts/requirements.txt python -m pytest ...`。
PyMuPDF 限制仅用于测试环境，避免新版 fitz 导入提示污染现有 JSON 子进程测试；未改项目依赖。

发布时按现有流程整合仓库当前改动、更新版本/CHANGELOG、重新 build/check workflows。
Claude Host 手工验收：创建合集 → 用 Marple 移入一件临时档案 → 从 Quasi fresh status/resolve
定位 → membership 或 collect 更新 → 确认写在同一目录，Topic archives 仍指向实际路径。
随后移出，重复 status 与读取原件。不要用真实研究档案做破坏性测试。

## 0.67.3 发布验证（2026-09-24）

- 整合 Archive 改动及工作区已有 Webpage/agent 修改，两份 manifest 同步为 0.67.3。
  发布方式沿用 marketplace 的 main 分支版本提交。
- 先原样重跑交接的 194 项测试，全部通过；检查后补齐异常 Marple JSON 日志的 blocked
  回执和合集目录名检查，避免产生 Workflow 无法接受的路径。
- 新增回归覆盖单字中文/带空格合集、换组与移出、原件摘要不变、Topic 旧路径失效及
  exact path 修复、生成 Workflow 的 Audit/source refs、坏布局和双向跨进程锁互斥。
- 最终 `python -m pytest -q`：**1,729 passed，1 skipped**（226.09s）。
  使用上面的 uv/PyMuPDF 测试环境；跳过项是默认关闭的付费 Claude Webpage Host E2E，
  本次未重跑模型 Host，历史验收记录不冒充本次证据。
- `npm run build:workflows`、`npm run check:workflows`、`git diff --check`、
  `cmp -s CLAUDE.md AGENTS.md` 均通过。`claude plugin validate .` 和显式 plugin manifest
  校验通过；后者只有已知的根 CLAUDE.md 不自动载入提示，运行时合同仍位于 skills/agents。
- 已用运行中的 Marple CLI 与源码 Quasi CLI 完成临时 PNG Archive/Topic 的实际联调：
  创建带中文和空格的合集、移入、fresh status 与 URL resolve、原位 membership 更新、
  移出和读取原件；两次移动后旧 revision 均 blocked，Topic archives/Markdown 引用自动
  更新且可用，原件 SHA-256 不变。校验的 37,181 个既有 Markdown/YAML 文件无变化，
  临时 Archive、合集、Topic 和请求文件已清理，Marple 完成回执保留。
  证据：[archive-collections-0.67.3.json](evals/archive-collections-0.67.3.json)。
