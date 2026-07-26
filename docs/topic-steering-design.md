# topic 闭环掌舵设计 —— 从平面爬行到围绕子问题的定向推进

- 日期: 2026-07-26
- 状态: 设计定稿(用户已确认方向与页面架构)
- 范围: `processTopic` 一条分支 + topic 页面契约 + synthesis §T。book/paper/author 分支、探针、去重、batchYear、LOCALISE、needs_seeds 卡点全部不动。
- 释放: **0.50.0** = outline + steer + 分层 synth(毕业机制);**0.50.1** = webcard 证据卡。

---

## 1. 背景:三个手机 topic 暴露的三种失败模式

2026-07-26 用户在 bts 库连跑三个手机相关 topic,加上库内最重的 `repair-morphology-interface-control`,构成完整病例:

| topic | 语料 | 结局 |
|---|---|---|
| `shanzhai-mobile-phones` | 39 条 | **顺风局**。主题恰好对应成熟学术文献群,雪球滚在群内,产物正常。现机制只在这种情形下工作。 |
| `unconventional-mobile-phone-form-factors-since-2000` | 54 条 / 五轮 | **漂移局**。主题真对象(非常规机型、产品史)学术覆盖薄,雪球顺引文梯度爬向旁边与上游:修理研究、模块化理论、GVC。当天新落 32 篇里有 Sturgeon 2002、MacDuffie 2013、Kopytoff 1986、E.P. Thompson 1967、Gereffi 2005、户口制度 1994——全是"被主题文献引用的经典",不是"关于主题对象的文献"。0.49.7 放宽的"单引但奠基也收"火上浇油。综述自认"不是机型目录",真对象全躺缺口清单。 |
| `sky-mobi-maopao-mrp-feature-phone-ecosystem` | 6 条 | **工具不对口局**。证据在 SEC 文件、工信部规章、SDK 遗存、社交媒体回忆里;学术搜索传感器失明,页面实际由圈外 web 调研写成,雪球全程旁观。 |
| `repair-morphology-interface-control` | — | **结构自发涌现**。00-overview 膨胀到 48KB;旁边手工长出 `res-fastener-genealogy.md`(53KB)、`res-repair-ecology.md`(67KB)等子问题专章及 `-sources/-notes` 伴页;证据卡流亡到 `vault/notes/`。用户已经用脚投票出目标结构。 |

## 2. 结构性病根

1. **爬行是平的,没有子问题结构。** desc 是一个字符串,每轮只问"和主题相关吗"。语料越多,"相关"邻域越大,越滚越糊。综述末端产出的「主题聚类」就是该有的子问题结构——但它只在终点出现,从不指挥采集。
2. **backward 梯度天然指离主题。** 参考文献总是更老、更泛;不设"关于主题对象 vs 仅被主题文献引用"的栅栏,每轮向社科经典的引力中心回退。
3. **回路开环。** 综述精确列出缺口,但下一轮雪球的输入只有落地正文的核心引用,缺口清单从不回流。用户在 overview 里手写"本轮方针"就是在人肉当反馈回路。
4. **语料无角色、综述全重织。** 平铺路径表进 synth,理论地基/方法范本/直接证据/邻域背景权重相同;`overwrite: true` 每轮整篇重写,结构每次自由发挥,增量重跑一次重洗一次。
5. **传感器只有学术一路。** 非学术主题(产业史、档案、机型)无证据通道;Kagi 管线在库里现成(`kagi_session_token` → quasi-search / kagi CLI),没接进 topic 回路。

## 3. 页面架构与推进模型

```
vault/topics/{slug}/
  00-overview.md        门面:总体趋势 + 每子问题一段摘要 + 指针 + 缺口总览(恒定薄)
  01-resources.md       阅读清单总账,按子问题分节(grep 友好的平铺账本)
  02-outline.md         研究大纲/状态 —— 掌舵的家,用户可手改
  03-{subq-slug}.md     「毕业」的子问题专章(编号毕业时分配,只追加不重排)
  04-{subq-slug}.md     …
  cards/{card-slug}.md  证据卡(网页/档案/机型/口述),被专章与 00 引用
```

推进四阶段:

- **阶段 0 提问**:desc → outline 拟 3-6 个子问题,全部 `gap`。
- **阶段 1 铺底**:召回 + 首轮采集,00/01 v1 落地,聚类都住在 00 里。
- **阶段 2 毕业**:某子问题语料 ≥6 条或攒下 cards → steer 标 `dossier: true` → synth 生成独立专章页,00 里该聚类瘦身为摘要+指针。
- **阶段 3 再组织**:子问题 split/merge(outline 记 reason);饱和的标 `saturated` 冻结不再重写;新缺口开新章。00 永远是活的门面。

顺带解决三个老毛病:synth 读预算按页拆分(0.49.4 的爆 context 类结构性缓解——专章只读自己聚类的语料);00 不再膨胀;cards 有家。

### 02-outline.md 机读契约(frontmatter)

```yaml
type: topic
kind: outline
title: {desc}
subquestions:
  - id: sq-fastener-genealogy      # kebab,稳定;专章文件名取它
    question: 紧固件谱系如何塑造可维修性?
    coverage: gap | thin | covered | saturated
    channel: academic | web | mixed
    dossier: false                  # true = 已毕业,有专章页
    page: 03-fastener-genealogy.md  # 毕业后填
    theory_used: 1                  # role=theory 配额账本(全 topic ≤3)
history:
  - "2026-07-26 r2: split sq-repair 为 sq-repair-knowledge / sq-repair-economy(理由…)"
```

正文为人读的研究地图(每个子问题一节:现状、缺口、下一步)。**放 vault 而非 `.quasi`,因为它是给用户编辑的**:手改子问题/覆盖度,下次增量重跑照改法走——把"人肉写本轮方针"的工作流正式化。

## 4. 掌舵步:steer-agent(新 agent,吞掉 topicSearch + snowball)

每轮一次。读 02-outline.md(无则创建)+ 语料表 + 本轮落地正文的核心引用(round 1 并上本地召回,保留现 `[...local, ...roundOk]` 语义;书读 `ch*.md` 的核心引用节,0.49.7 的修正保留)。然后:

1. **更新 outline 覆盖度并写盘**——它是 02-outline.md 的唯一 writer。
2. 输出下一轮**定向候选**:每个候选必须带 `subq` 与 `role`(evidence | theory | method | context)标签,服务不了任何子问题的不收。**栅栏判据写进合同:该文献自身的研究对象落在子问题内,而不是仅被主题文献引用。**
3. **经典配额**:`role: theory` 全 topic ≤3 条,账记在 outline 的 `theory_used`,跨轮跨重跑累计。
4. 非学术子问题(channel: web|mixed)输出 `web_tasks[]`(0.50.0 先返回但图不消费,0.50.1 接 webcard)。
5. 候选不足时自拟拓宽词就地 quasi-search 补足(0.49.7 行为保留);可宣告 `saturated: true`,循环在轮数用尽前正常收口。
6. 提名毕业:子问题语料 ≥6 或有 cards → `dossier: true`。
7. 回执带 `dirty: [subq-id]`(本轮语料/结构有变化的子问题)——synth 按它决定重写哪些专章。

工具:Read, Write, Bash。写权限限定 `vault/topics/{slug}/02-outline.md`(caller 指定精确路径,延续"agent 只写合同命名的产物"契约)。

`topicSearchPrompt` / `snowballPrompt` 两个 builder 退役(内部函数,不进 DEAD_NAMES);首轮 steer 无 outline、无语料,行为即"拟大纲 + 按子问题首搜",自然替代 topicSearchPrompt。

STEER_SCHEMA(回执):

```js
{ outline_written: bool, saturated: bool,
  subquestions: [{id, coverage, dossier}],
  dirty: [id],
  candidates: [{kind, slug, title, authors, year, isbn|doi|oa_url|journal, subq, role}],
  web_tasks: [{subq, query, note}],
  suggested_queries: [..] }   // needs_seeds 卡点沿用
```

## 5. Kagi 非学术通道:webcard-agent(0.50.1)

接 steer 的 `web_tasks`,kagi CLI + WebFetch 检索核验,写 `vault/topics/{slug}/cards/{card-slug}.md`。每卡一个对象(一款机型/一份 SEC 文件/一段口述),带来源与证据等级——unconventional 跑里手工发明的"材料卡"模式正式化。每轮 ≤3 张防爆量。卡不进 `ok` 语料表(不是 vault 分析件),独立 `cards[]` 递给 synth。工具:Read, Write, Bash。

## 6. synth §T 重构:按 outline 分页生成

- 输入增加:`outline_path` + 带 `subq/role` 标签的语料表 + `cards[]` + `dirty[]`。
- **聚类 = outline 子问题**:id、标题、顺序照抄;theory 条目只出现在其锚定聚类;cards 以证据档案节引用。
- 分页生成:`dirty` 里已毕业的子问题 → 重写其专章页(只读该聚类语料);00 与 01 永远重写(读各专章摘要 + 未毕业聚类语料,00 恒薄);干净专章不碰。
- 仍然 `overwrite: true` 全页重写,但结构被 outline 钉死——"持续再组织"由 steer 演化 outline、synth 跟随实现,不是 synth 每次即兴。

## 7. 图循环(processTopic 改后骨架)

```
1. parallel(recall, steer#seed)            # steer 首轮:创建 outline + 首批定向候选
2. while (候选或 web_tasks 非空 && round < maxRounds && !saturated):
     探针 → router 落地学术候选(≤perRound,机制不动)
     [0.50.1] parallel(web_tasks → webcard, ≤3)
     steer#round → 更新 outline、下一轮候选、dirty
3. needs_seeds / all_failed 卡点沿用(suggested_queries 来自 steer)
4. synth:按 §6 分页派发(专章逐页 + 00/01),回执对账
5. audit vault/topics/{slug}(多页同审)+ 一次 escalation 回环
```

增量重跑天然收敛:outline 已存在 → steer 对账更新而非重来。

## 8. 迁移与兼容

- 老 topic(两页式)增量重跑:steer 首轮对账,超重聚类提名毕业;`res-*` 手工旧页保留原名,outline 登记 `page: res-….md` 指过去,不强迫改名。
- `manifest.json` 等老 process-topic 遗留状态由 outline 取代,不读不删。
- schema 侧新增 `kind: outline | dossier | card`(quasi-audit 注册,YAML 风格沿 topic 现契约)。
- CLAUDE.md/AGENTS.md:topic 目录契约从"两页"改为"三页脊柱 + 毕业专章 + cards/"。

## 9. 测试与文档清单

- 改:`test_skill_orchestration.py` 里 snowball 相关断言(`[...local, ...roundOk]` 语义保留但文字可能变;`## 文献人物` 保留;新增 steer/outline/配额/毕业断言)。
- 新 agent 文件:`agents/steer-agent.md`、`agents/webcard-agent.md`(0.50.1);`synthesis-agent.md` §T 重写。
- `docs/ARCHITECTURE.md`、`README.md` agent 表;CHANGELOG;plugin/marketplace 版本。
- E2E:用 bts 真库对 `unconventional-…` 增量重跑一轮验证毕业 + 反漂移(theory 配额挡住新经典)。
