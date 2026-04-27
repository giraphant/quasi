# Book Slug And Source Alignment Design

## Problem

quasi 当前把书籍目录名的决定拆散在多个阶段里，尤其是 `skills/process-book/SKILL.md` 里存在“`derive_slug(source_file)`，agent 自行实现”这样的自由推导点。这导致两个问题：

1. 新流程中，弱模型容易把 `sources/`、`processing/chapters/`、`vault/monographs/` 的 slug 算成不同名字。
2. 历史库里已经形成了一批稳定的 `vault/monographs/{slug}` 目录，但 `sources/` 中仍有未对齐的旧文件名。

这两个问题相关，但不是同一个问题。设计上必须拆成两条独立线路：

1. **A 线：历史残留整理** — 以已有 monograph 目录名为准，反向对齐历史 `sources/` 文件名。
2. **B 线：插件未来优化** — 让未来新增书籍在下载阶段就完成 slug 定稿，避免再产生新的错位。

## Goals

1. 对历史库，保留既有 `vault/monographs/{slug}` 目录名不变。
2. 对未来流程，消除分析阶段再次推导 slug 的自由度。
3. 保持 slug 格式统一为 `{author-surname}-{short-title}-{year}`。
4. 允许下载阶段根据文件内容纠偏 `title`、`year`、`slug`，但纠偏只发生一次。
5. 让便宜模型也能稳定复用同一 slug，而不是在不同阶段各起一个名字。

## Non-Goals

1. 不批量重命名历史 `vault/monographs/` 目录。
2. 不把历史库清洗逻辑塞进日常 workflow。
3. 不引入新的不可变 `book_id` 体系。
4. 不依赖 PDF metadata 作为书籍身份的判断依据。
5. 不要求区分具体版本或版次；默认只关心“是不是同一本书、同一个作者”。

## Canonical Slug Format

所有书籍 slug 统一采用：

`{author-surname}-{short-title}-{year}`

要求：

1. 全小写。
2. kebab-case。
3. 作者部分使用姓氏或稳定的作者标识。
4. 标题部分使用主标题的短形式，不要求保留完整副标题。
5. 年份保留在 slug 中，即使后续下载文件是不同版本，也仍然保持同一格式。

## Track A: Historical Source Alignment

### Purpose

将历史库中已有的 `vault/monographs/{slug}` 视为既有规范，反向修正历史 `sources/` 文件名，使同一本书在源文件层和分析目录层尽量一致。

### Canonical Source Of Truth

对 A 线而言，canonical 名称来自现有 `vault/monographs/{slug}` 目录名，而不是来自 `sources/` 文件名，也不是来自新的 discover 结果。

### Workflow

1. 扫描 `vault/monographs/*`，收集所有 canonical slug。
2. 扫描 `sources/*`，建立现有源文件 stem 到实际路径的索引。
3. 对已经存在同名 `sources/{slug}.pdf|epub` 的书，标记为 `aligned`。
4. 对未对齐项，优先使用强证据反向确认：
   - 作者 manifest 中该书已有的 `books[].slug`
   - manifest 中现有 `source` 或 `file` 路径
   - `processing/chapters/{slug}` 的存在情况
5. 对仍不明确的项，读取文件前部内容做书名/作者确认。
6. 仅在高置信度下，将该源文件重命名为对应的 canonical slug。
7. 输出三类结果：
   - `aligned`
   - `renamed`
   - `needs_review`

### Safety Rules

1. 绝不改已有 `vault/monographs/{slug}` 目录名。
2. 绝不覆盖已存在的 `sources/{slug}.*`。
3. 一个 source 文件匹配多个 monograph 时，不自动改名。
4. 一个 monograph 对应多个 source 文件时，不自动删文件，只报告冲突。
5. A 线是库清洗任务，不属于 quasi 正常 workflow 的隐式步骤。

## Track B: Future Plugin Workflow

### Purpose

对未来新增书籍，slug 的决定权前移到下载阶段，并且只允许定稿一次。后续任何 workflow 都只能复用该 slug，不再重新推导。

### Lifecycle

1. `discover-agent` 先生成候选书目，并给出**格式已经正确**的候选 slug。
2. `download-agent` 下载文件。
3. `download-agent` 基于文件内容验真“是否是同一本书、同一个作者”。
4. 若匹配，则允许 `download-agent` 在同一格式下纠偏 `title`、`year`、`slug`。
5. `download-agent` 将最终文件落到 `sources/{final-slug}.pdf|epub`。
6. `download-agent` 回写 manifest 中这本书的最终字段。
7. `process-book` 和 `process-author` 只消费 `final-slug`，不再拥有 slug 推导权。

### Responsibilities By Component

#### `discover-agent`

`discover-agent` 的职责是：

1. 根据外部搜索结果选书。
2. 生成符合规范格式的候选 slug。
3. 将候选 `title`、`year`、`slug` 写入 manifest。

`discover-agent` 生成的 slug 不是最终不可变真相，但必须已经符合 canonical 格式。它不能输出随意的短名，比如 `against-technoableism` 或 `work-pray-code` 这种不含作者与年份的非规范名字。

#### `download-agent`

`download-agent` 的职责是：

1. 下载书籍文件。
2. 读取下载文件前部内容做验真。
3. 判断 discover 结果是否指向同一本书、同一个作者。
4. 在必要时重新生成同格式的最终 slug。
5. 将 `title`、`year`、`slug`、`source/file` 等字段回写到 manifest。
6. 将文件最终保存为 `sources/{final-slug}.*`。

`download-agent` 允许纠偏，但纠偏只允许发生在下载阶段，而且只发生一次。

#### `process-book`

`process-book` 的职责从“推导 slug + 处理书”收缩为“使用已有 final slug 处理书”。

它不再执行类似 `derive_slug(source_file)` 的逻辑，也不再在 `sources/` 文件名与输出目录名之间创造新名字。

#### `process-author`

`process-author` 继续消费 manifest 里的 `book.slug`，但该字段现在代表下载阶段已经验真并定稿的 final slug。

它不再拥有任何重命名或重新推导 slug 的职责。

## Verification Rules In Download Stage

### Evidence Sources

1. **PDF**：不读 metadata，不信任 metadata。
2. **PDF**：只看文件前部可提取文本，优先：
   - title page
   - copyright page
   - 目录前后的书名/作者信息
3. **EPUB**：可参考内部 metadata，但只作为辅助证据。
4. **EPUB**：主证据仍优先来自正文前部或封面内页文本。

### Match Criteria

只要满足以下两条，就判定为 `match`：

1. 标题能对上同一本书。
2. 作者能对上同一个作者。

默认不因以下差异判失败：

1. 版次不同。
2. paperback / revised edition / second edition 等版本描述不同。
3. 副标题轻微差异。
4. 年份差异。

### When Automatic Renaming Is Allowed

以下情况允许 `download-agent` 自动纠偏并回写 manifest：

1. discover 的 slug 格式正确，但作者前缀、短标题或年份不够准确。
2. discover 的标题和文件内容显示的主标题是同一本书，但 discover 用的是更短或更粗糙的标题写法。
3. discover 的年份与文件内容年份不同，但明显是同一本书不同版本。

示例：

1. `against-technoableism` 风格的旧名应被纠偏为 `shew-against-technoableism-2023`。
2. `work-pray-code` 风格的旧名应被纠偏为 `chen-work-pray-code-2022`。

### When To Fail Or Escalate

以下情况不得自动纠偏，应标记为 `mismatch` 或 `needs_review`：

1. 作者明显不是同一个人。
2. 标题只是主题相近，但不是同一本书。
3. 文件前部证据不足，无法确认书名或作者。
4. 存在多个合理候选，无法唯一确定最终 slug。

## Manifest Semantics

manifest 中书籍条目的语义调整为：

1. `discover-agent` 写入的是**候选** `title`、`year`、`slug`。
2. `download-agent` 验真后可将它们更新为**最终** `title`、`year`、`slug`。
3. 一旦 `download-agent` 回写完成，这些字段即视为 final，不应再被后续 workflow 修改。

应一起回写的字段包括：

1. `title`
2. `year`
3. `slug`
4. `source` 或 `file`
5. `status`

## Required Changes

### 1. `agents/discover-agent.md`

补充约束：书籍 `slug` 必须直接产出 canonical 格式，不允许输出仅含短标题的旧式 slug。

### 2. `agents/download-agent.md`

补充阶段性职责：下载后必须执行书籍内容验真，并在匹配时允许在同一格式下纠偏 `title/year/slug` 与 manifest 路径字段。

### 3. `skills/process-book/SKILL.md`

移除“`derive_slug(source_file)`，agent 自行实现”这类二次推导设计，改为只消费已定稿的 slug。

### 4. `skills/process-author/SKILL.md`

明确 `book.slug` 是下载后定稿值，后续只复用，不再重算。

### 5. `scripts/download/download.py`

在现有下载主链中补充：

1. 文件前部证据提取
2. 书名/作者匹配判断
3. 最终 slug 纠偏
4. manifest 回写
5. 最终文件命名

该增强应尽量复用现有下载流程与已有 `slugify()` 能力，不引入新的独立入口脚本。

## Error Handling

1. 下载失败：保持 manifest 为未获取状态，不进入验真阶段。
2. 下载成功但验证失败：标记 `mismatch` 或 `needs_review`，不进入后续处理。
3. 目标 `sources/{final-slug}.*` 已存在：不覆盖，进入 `needs_review`。
4. manifest 回写失败：视为下载阶段失败，不允许后续 workflow 继续消费未定稿状态。

## Testing Strategy

测试重点放在规则边界，而不是 agent 文案本身：

1. discover 输出的 slug 符合 canonical 格式。
2. download 对“同书同作者但不同版本”判定为 `match`。
3. download 对“同主题不同书”判定为 `mismatch`。
4. download 在纠偏时会同步更新 manifest 与最终文件名。
5. process-book 不再存在二次推导 slug 的入口。
6. process-author 只消费 final slug。

## Rollout Strategy

1. A 线与 B 线分开推进，不互相阻塞。
2. A 线作为一次性历史数据整理任务执行。
3. B 线作为 quasi 主流程优化进入日常使用。
4. 在 B 线完成后，新下载数据不应再产生 `sources/` 与 `vault/monographs/` 命名漂移。

## Out Of Scope

1. 用新规则反向改写所有历史 monograph 目录名。
2. 自动区分不同 edition 的独立知识库身份。
3. 引入额外的数据库或全局 ID 体系。
4. 依赖 PDF metadata 做书籍身份裁定。
