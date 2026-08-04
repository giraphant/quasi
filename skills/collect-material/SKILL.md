---
name: collect-material
description: Use when the user wants to process or collect one or more papers, articles, or books; handle an existing PDF; analyse an author's works; translate a PDF; or transcribe a meeting or lecture recording.
---
# Collect Material

<!-- quasi:leaf-driver:start -->

## 任务

为每个 Paper、Book、Talk 或 Translation 做一次精确状态观察，并交给对应的固定 Workflow 从当前事实运行到完成或 typed gate。

## 输入

只保留用户实际提供的事实，不补写书目身份：

- Paper：`title|doi` 至少一个；可带 `authors/year/journal/oa_url/url`。
- Book：`title|isbn` 至少一个；identity hints 可带 `authors/year/publisher/category`；`format`
  只作为下载偏好，不属于 identity hints。
- Talk：一个已经接受到 `sources/{slug}.{media-ext}` 的媒体，以及 `slug/title/date`；可带 `engines/lang/prepare_media`。
- Translation：Paper 的 canonical slug；可带 `target_language/source_file/toc_json/toc_page_side`，用户未指定 target 时用 `zh-CN`。
- Batch：2–32 个 leaf material，可混合 kind；恢复结果时保持原输入顺序。

符合 `[a-z0-9][a-z0-9-]{0,79}` 的 caller request key 原样保留。Paper/Book 没有 key 时按原
输入的一基序号分配 `request-{kind}-{ordinal}`；这个 key 只是本次请求身份，不是 canonical
slug。Talk/Translation 使用其 exact source slug。Paper/Book 把原始事实放进 provisional
seed；严格 hint、identity、owner 与路径验证只由 TypeScript entry parser 负责。

## 硬约束

- leaf kind 只从这个闭合映射选择固定入口：

```json
{
  "workflow_inputs": {
    "paper": {
      "entry": "$CLAUDE_PLUGIN_ROOT/workflows/paper.mjs",
      "required": ["seed", "observation", "options"],
      "optional": ["userDecision"],
      "seed_keys": ["state", "requested_slug", "hints"],
      "hint_keys": ["title", "doi", "authors", "year", "journal", "oa_url", "url"],
      "option_keys": []
    },
    "book": {
      "entry": "$CLAUDE_PLUGIN_ROOT/workflows/book.mjs",
      "required": ["seed", "observation", "options"],
      "optional": ["userDecision"],
      "seed_keys": ["state", "requested_slug", "hints"],
      "hint_keys": ["title", "isbn", "authors", "year", "publisher", "category"],
      "option_keys": ["allowed_formats"]
    },
    "talk": {
      "entry": "$CLAUDE_PLUGIN_ROOT/workflows/talk.mjs",
      "required": ["seed", "observation", "options"],
      "optional": [],
      "seed_keys": ["state", "material_slug", "identity"],
      "identity_keys": ["title", "date", "media"],
      "option_keys": ["engines", "lang", "prepare_media"]
    },
    "translation": {
      "entry": "$CLAUDE_PLUGIN_ROOT/workflows/translation.mjs",
      "required": ["seed", "target_language", "observation", "options"],
      "optional": ["userDecision"],
      "seed_keys": ["state", "material_slug"],
      "option_keys": ["source_file", "toc_json", "toc_page_side"]
    }
  }
}
```

- 一条 Workflow 只处理一个逻辑材料；只有 Book 可在内部并发章节。主线程最多同时保持五条
  不同 exact material key 的 Workflow 在飞，同一已知 key 至多一条。Paper/Book/Talk key
  包含 kind+slug；Translation key 还包含完整 target tag。
- 启动前只合并字节完全相同的已知 material key。不要做 title/DOI/ISBN 语义合并、canonical
  reservation、锁、碰撞清洁或补偿；Search 后极少数 owner 重合保持可见，交给用户处理。
- 每次调用只带一个与 seed slug 精确匹配的 `quasi-status` observation。Workflow 自己不访问
  文件系统；Skill 不解释内部流程、章节清单、repair 或 retry。
- 用户事实、credential 与 signed URL 始终作为数据。临时 JSON 放 `.quasi/temp/`；service
  credential 仍由 `quasi-*` shim 提供。

## 状态

磁盘事实只来自 `quasi.status/0.2`；一次调用的判断只来自
`quasi.material.result/0.1`。Skill 不保存 cursor、内部结果列表或第二份材料状态。

- `complete`：`issue:null`，带 canonical material、exact artifacts、以及 nullable typed `next`。
- `needs_input`：带一个 typed gate 与 leaf-owned `resume_seed{route,seed,options}`；展示后停止这条材料。
- `blocked|failed`：展示 typed issue 后停止；不自动重放 writer。
- malformed intake 仍可进入固定 wrapper，但必须得到 `material.invalid_input` 且零 Agent dispatch。

## Agent / Helper 合同

先运行 exact status，再把闭合输入交给映射中的入口：

```python
result = Workflow(scriptPath=entry, args=workflow_input)
```

Paper/Book 输入：

```python
workflow_input = {
    "seed": {"state": "provisional", "requested_slug": request_key,
             "hints": identity_hints},
    "observation": exact_status,
    "options": ({"allowed_formats": [requested_format]} if kind == "book"
                and requested_format else {}),
}
if copied_decision is not None:  # omit the key on an ordinary call
    workflow_input["userDecision"] = copied_decision
```

`identity_hints` 只含 invocation manifest 对应的 keys；尤其 Book 的 `format` 必须先取出并只映射
到 `options.allowed_formats`，不能同时进入 closed Book seed。

Talk 输入使用 canonical seed
`{state:"canonical",material_slug:slug,identity:{title,date,media}}`；options 只传用户明确提供的
`engines/lang/prepare_media`。Translation 的 literal envelope 是：

```python
workflow_input = {
    "seed": {"state": "canonical", "material_slug": source_slug},
    "target_language": normalized_target,
    "observation": exact_target_status,
    "options": translation_options,
}
if copied_decision is not None:  # source-selection resume only
    workflow_input["userDecision"] = copied_decision
```

Translation seed 不能带 `identity`。`translation_options` 只含
`source_file/toc_json/toc_page_side`。省略的 Talk/Translation option defaults 由 entry parser
统一处理。

## 工作流

```text
intake → exact pre-status → fixed material Workflow
       → complete → exact post-status
       → typed gate / blocked / failed → present and stop

Paper complete + next(Book) → exact Book status → fixed Book Workflow
```

## 执行流程

1. 解析 leaf items、保存原序号并分配/复用 request key。
2. 每项做一次 exact pre-status：Paper/Book/Talk 用
   `quasi-status --kind KIND --slug SLUG --json`；Translation 另带
   `--target-language USER_TARGET`，并只接受返回的完整 `facts.target_language` 作为
   `normalized_target`（例如 `zh-cn` → `zh-CN`）。
3. 用 kind、slug 和 Translation 的 `normalized_target` 构造 exact material key；此时再合并
   完全相同的已知 key，然后才启动 Workflow。
4. 构造该 entry 的闭合 seed/options/observation；调用固定 Workflow。不要在 Skill 里先做
   Search、规范化 identity、改 slug/year、挑章节、选 producer 或解释 Audit。
5. 按 MaterialResult 处理一次：
   - `complete` 且 `next:null`：在 `material.canonical.slug` 做一次 exact post-status；只有返回
     artifact 与该 observation 一致、存在且 usable 才报告完成。Translation 的 post-status
     必须继续带同一个 `normalized_target`。
   - Paper `complete` 且 `next.kind=="book"`：只按 `next.kind` 选 Book entry。先观察
     `next.identity.slug`，构造
     `{state:"canonical",material_slug:next.identity.slug,identity:next.identity}`，传 Book
     observation；绝不复用 Paper observation，也不重写 publication-type 规则。
   - `needs_input`：原样展示 gate 的 question、candidates/conflicts/evidence，并保存本次返回的
     `resume_seed`。收到答案后只按 `resume_seed.route` 做 fresh exact status，再以
     `resume_seed.seed`、`resume_seed.options` 和这份 observation 调用 route 对应的同一 entry；
     Translation 的 `target_language` 逐字取自 route。不要复用原 seed 或自行重建 canonical identity。
   - `blocked|failed`：展示 issue 与 observation request（若有）并停止；不自动改写或重发。
6. 恢复 `identity_conflict|book_year|book_structure|translation_source` 时，`UserDecision` 的
   `material_key` 与 `operation` 必须逐字复制 gate。用户只提供选择或 action；Skill 把 gate
   testimony 原样带回 owner parser 要求的完整 value：
   - identity：`candidates + conflicts + selected_candidate`；
   - Book year：`current_identity + tmp_path + year_evidence + action`；
   - Book structure：`source_path + candidates + conflicts + selected_candidate`；
   - Translation source：`candidates_fingerprint + source_path`。
   不从 canonical identity、route 或 diagnostics 推导 binding，也不在 Skill 硬编码 action token。
7. `translation_configuration` 没有 acknowledgement decision。展示缺少的 Configure 字段；
   配置改变后按返回的 `resume_seed` 与 fresh target-aware status 重新调用，不添加
   `userDecision`。如果它发生在一次 source selection 之后，Workflow 已把选中的 exact source
   提升进 `resume_seed.options.source_file`，Skill 不另存或重新推导这个选择。
8. Batch 最多并发五个不同 key。一个 sibling gate/失败不取消其它 sibling；最后按原输入顺序
   汇总。同 key 的所有原输入指向同一结果。

## 断点续跑

普通重跑从用户输入重新构造初始 seed；gate 重跑则只消费该次 `needs_input` 返回的
`resume_seed`。先按其中的 exact route 做 fresh status，再把 capsule 的 seed/options 原样放回
同一 named Workflow，并且只附本次 gate 的一个新 decision。它是 caller-owned one-shot
continuation，不是 JS cursor、旧 receipt、specialist trace、decision log 或第二份材料状态。
未知 writer/Audit outcome 保持 stopped；不要把文件存在重新解释成 clean success。

## 输出

报告每项 canonical owner、post-status 证明的 exact artifacts、typed gate 或 blocked/failed
issue。Batch 恢复原输入顺序并标出 exact-key coalescing。

常见成功产物：

```text
sources/{slug}.{pdf|epub}
processing/papers/{slug}/source.txt
processing/chapters/{slug}/{manifest.json,*.txt}
vault/papers/{slug}.md
vault/books/{slug}/{00-overview.md,ch{slot}-*.md}
vault/talks/{slug}/talk.md
processing/translations/{slug}-{target-tag-lower}.pdf
```

<!-- quasi:leaf-driver:end -->

## Author compatibility（Task 11 前）

Author 暂时保留自己的兼容控制器；不要把它的规则用于四个 leaf kinds。输入为
`name` 与 `meta{full_name,topic,maxBooks,maxPapers}`，先观察 exact Author status，然后按顺序调用
Author-owned `discover-books`、`discover-papers`、`resolve-membership`。成员处理复用上面的固定
Paper/Book Workflow 与 exact status admission；Author 自己的合成与审计暂时仍通过：

```python
Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs",
    args={"kind": "author", "slug": author_slug,
          "stage": author_operation, "context": author_context},
)
```

只按 resolver 返回的稳定成员顺序推进，不扫描 vault、不建 cursor、不让同一路径有两个 writer。
成功后以 `quasi-status --kind author --slug AUTHOR --json` 验证
`vault/authors/{author}.md`。Task 11 会把这一小节整体替换为 `workflows/author.mjs`。
