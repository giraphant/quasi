# Archive 原件与阅读器合同

适用于 0.65.39 起的新采集。用户主要通过 Topic 进入；独立 Webpage 类型保留。

## 存储

```text
vault/archives/<slug>/
├── archive.md
├── manifest.yaml
└── originals/
    ├── 001-screen-discoloration.jpg
    ├── 002-connector-detail.jpg
    ├── screen-repair-manual.pdf
    ├── repair-post.webarchive
    └── screen-removal.mp4
```

一件 Archive 是一个有边界的材料对象，可包含组图与混合格式。文件名使用有指向的
kebab-case，顺序编号可选；引用建立后不为调整展示顺序而重命名。没有章节子目录，
不要求逐图标题或标注。没有原件时可只有 Markdown 与空清单，不创建空 originals 目录。

`archive.md` 是可独立阅读的材料入口。frontmatter 保留 type/title/kind/created，
来源平台或发布机构 source、材料直接链接 url，以及核实后的 creator/date；themes/topics 按需。
created 是本库建档日期，date 仅为原材料发布日期。网页采集必须查找可见日期和页面元数据：
有明确完整发布日期才填 date；只有更新日期、部分日期或没有日期时，正文据实说明，不补造日期。
更新日期不冒充发布日期，实际保存时间来自 manifest 的 captured_at。

新建正文使用以下栏目（旧轻量记录继续兼容，不新增格式验收关卡）：

- H1：材料标题。
- **材料概况**：材料对象、产生语境、用途、适用型号/版本，原作或转载/节选关系。
- **来源与保存**：原标题、日期依据或未知说明、核读与保存范围、语言/版本和缺失限制。
- **内容与摘录**：足够具体的内容概述、关键事实/方法/条件及来源定位；区分摘要、引文和判断。
- **关联**：有实质关联时提供 Topic、材料和笔记链接，可省略。
- **本地原件**：helper 按清单追加陈列，图片嵌入、其他原件用相对链接，无需逐图分析。

页面 url 来自同一 identity，与 manifest 共同出处保持一致；source 是面向读者的来源名称，
manifest 继续管理逐文件原始 URL、异源覆盖及保存记录。初次采集后保留已有正文和元数据；
补充已知元数据只填空缺，遇到已有不同值先明确协调，不静默覆盖。

## manifest.yaml

机器结构的唯一源为 `scripts/schemas/archive_manifest.py`，producer projection 随 Archive
artifact contract 提供给采集 agent。Markdown、YAML 是纯文本，原件保留各自的二进制格式。

```yaml
schema_version: quasi.archive.manifest/0.1
source:
  url: https://example.org/posts/123
  title: 屏幕维修讨论
files:
  - path: originals/001-screen-discoloration.jpg
    media_type: image/jpeg
    captured_at: '2026-09-21T12:00:00+00:00'
    size: 123456
    sha256: <64 位十六进制 SHA-256，实际写入不能使用这个占位符>
    url: https://example.org/uploads/screen.jpg
  - path: originals/screen-removal.mp4
    media_type: video/mp4
    captured_at: '2026-09-21T12:02:00+00:00'
    size: 456789
    sha256: <64 位十六进制 SHA-256>
    url: https://cdn.example.net/removal.mp4
    source:
      url: https://example.net/videos/456
      title: 补充演示
coverage: 收录正文配图与演示；未收录评论。
```

- `files[].path` 相对于 Archive 目录，也是 Markdown 与清单的关联键。清单数组保存采集顺序，
  Markdown 可以有自己的陈列顺序。
- `source` 是共同出处；`files[].source` 仅在不同出处时覆盖。`files[].url` 是实际保存的
  原件最终下载地址，不能用 CDN 文件地址替代材料上下文出处。
- 标题与 source override 可省略；captured_at/size/sha256/media_type/url 由 helper 自动填写。
- `coverage` 是自由文本；缺失内容是说明而非失败比例。files 可以为空，表示仅保留出处。
- 不包含流程 cursor、stage、完成率或重试日志。

Marple 可将 Markdown 相对链接解析到 files[].path，以 MIME 决定图片、PDF、网页快照或
音视频的展示方式。出处按上述继承关系显示在详情，不需要逐图正文标注。视频/音频本期
仅保存可直接下载的原件并供播放，不转录、OCR、转码；浏览器不支持的编码仍可打开原件。
受登录保护、DRM 或仅提供流媒体播放清单的来源暂记出处与未取得原因。

## 采集与并发

Topic 只读发现材料 → Archive agent 检查 exact URL 与对象内附件 → 选择原件 →
`quasi-archive collect` → fresh Archive status → Topic 核读/综合（证据卡按需）。

CLI:

- `quasi-archive inspect --url URL`：只读检查内容类型、标题、带字段标签的日期/作者元数据证据和对象内候选链接；不自动递归。
- `quasi-archive collect --request-file .quasi/temp/UNIQUE.json`：发布原件、清单、陈列页。
  请求为 identity/topics/expected_revision/files/body/coverage，可加 metadata（creator/date/source）；
  metadata 的未知字段省略，membership 使用 {}，旧六键请求仍兼容。files 项为
  name/url/method（download 或 webarchive）及可选 source。expected_revision 必须来自
  fresh `quasi-status --kind archive` 的 facts.collection.revision。
- `quasi-archive read --path EXACT.webarchive`：只读输出已保存快照的文本，供 Topic 核读；
  不落地派生产物。图片/PDF 由 specialist Read exact originals；音视频不推断内容。

网页快照复用既有 WebKit capture 能力（macOS）；其它原件走流式 HTTP 下载。单文件上限
1 GiB、下载循环五分钟上限、单次请求最多 200 个选定原件。失败文件不加入清单，保留
coverage 原因；全失败也能建立有出处的链接型 Archive。

两个进程对同 URL 或同 slug 写入时，通过 `.quasi/locks/` 中的短期 flock 排他；不同
Archive 可并行。锁文件本身不是运行状态，退出即释放锁。锁忙或 revision 过期返回 blocked，
不自动重试；主进程 fresh status 后再明确续跑。这样不会覆盖另一进程的原件或丢 topics。
URL owner 在锁内再次核对，避免两个 provisional slug 收录同一个 URL。

远程采集先暂存在 .quasi/temp，发布原件后写 archive.md，最后写 manifest.yaml。已发布
后出现任何错误返回 outcome_unknown，不重放。status 检查清单与实际字节，并拒绝未登记
的 originals，以识别不完整的发布。checksum 是文件一致性检查，不是收录完整率。
旧链接型 Archive 经 Topic 再次访问时可补清单和原件，原有正文与元数据保留。

## Claude 手工验收建议

从两个**不同 Topic slug** 的项目根进程运行 research-topic，选择会引用同一来源的研究问题。
确认共同材料只有一个 Archive；第二进程若遇冲突应停止并报告，之后 fresh status 续跑，
最终 topics 含两个专题，两个证据卡引用同一个 archive.md。不要同时维护同一个 Topic
大纲：本期互斥只保护 Archive 采集，不改变 Topic 自身的单写者合同。

另测一个含组图的帖子：原件有描述性文件名，正文无需逐图说明；manifest 共同出处只写
一次，缺失图片仅留下 coverage；在 Marple 按相对路径核对展示和出处。Claude Host 验收
由使用者执行，本仓库测试覆盖确定性 helper、生成 Workflow 和进程并发边界。
