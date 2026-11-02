# 研究一个 topic

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md`。

研究是一个循环：读现状，找材料，收进文库，读笔记，更新认识，再决定下一步。选线索、挑候选、读材料、判断收口，这些都由你自己做；派出去的只有收录和写作。下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `research/`。

## Topic 的几页

都在 `vault/topics/SLUG/` 下，frontmatter 都是 `type: topic`，`kind` 标明是哪一页：

- `02-outline.md`（`kind: outline`）：研究地图。frontmatter 的 `subquestions` 列出子问题，每个子问题有 `id`、`question`、`coverage`（`gap`、`thin`、`covered`、`saturated`）、`channel`（`academic`、`web`、`mixed`）和 `items`（每项 `kind`、`slug`、`role`，`role` 是 `evidence`、`theory`、`method`、`context` 之一）。正文写中心问题、解释思路、历史线索和缺口。**这一页由你自己维护**，它也是续跑的依据。
- `00-overview.md`（`kind: overview`）：综述，维持全局图景。
- `01-resources.md`（`kind: resources`）：按子问题排列的阅读路径，每件材料一行链接加一句说明。
- 专章：某个子问题材料多到综述装不下时，单独写一页深入，比如 `03-modular-manufacturing.md`。现有 schema 还不认这类页面，audit 会报类型不对，先忽略这一项。

## 循环

1. **读现状。** 已有 Topic 就先读研究地图和综述；没有就和用户谈清楚研究问题和范围，定一个英文 kebab slug。
2. **本地召回。** 先看文库里已经有什么：在 `vault/` 下用 `rg` 搜关键词、作者和概念，读相关的阅读笔记。已有的材料直接用，不重新收。
3. **搜索。** 针对地图里覆盖薄弱的子问题自己去找：学术材料用 `quasi search paper` 和 `quasi search book`（`--query`、`--author`、`--title`），网络材料用 `quasi search kagi`。看到线索就顺着引用和作者往下追。候选按"能回答哪个子问题、补上什么新东西"来挑，不按数量凑。
4. **收录。** 按 `collect/README.md` 收进文库：学术材料按论文或书，非学术的网页原件按档案（发布请求的 `topics` 里写上本 Topic 的 slug）。件数多就派材料会话。某件收不到，记为缺口，继续做别的。
5. **读和更新地图。** 读新收材料的阅读笔记（需要细节时再读原文），把每件材料挂到对应子问题下并注明角色，调整各子问题的覆盖度，必要时拆分或新增子问题。地图写回磁盘。
6. **写页。** 每轮都请写手更新资源页。综述和专章只在攒够一批材料、某个子问题确实有推进时重写。按 `connectors/rex.md` 派写手，消息照下面这样写：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径，按其中「综述」（或「专章」「资源页」）一节写
   研究地图：vault/topics/SLUG/02-outline.md 的绝对路径
   请读这些阅读笔记，每行一个：绝对路径 | 链接写法 [[vault/papers/slug|简称]]
   现有页面（重写时给）：路径
   只读取上面列出的文件。
   ```

   重写已有页面时，保留用户自己写的内容。存回之后对整个 Topic 目录跑 `quasi audit --path vault/topics/SLUG`。

7. **判断下一步。** 默认跑两轮就停下来，向用户报告：新收了哪些材料、哪些子问题有了推进、还剩哪些方向和缺口。用户要继续，就从第 1 步接着来。

## 续跑

从研究地图接着做：它记着有哪些子问题、每个子问题已经有哪些材料、覆盖到什么程度。没收完的材料按 `collect/README.md` 的续跑规则处理。
