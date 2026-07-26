# Topic 闭环掌舵(0.50.0)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 processTopic 从平面滚雪球改成围绕持久研究大纲(02-outline.md)的闭环:steer-agent 掌舵采集,子问题毕业成专章页,synthesis 按 outline 钉死结构分页生成。

**Architecture:** 设计见 `docs/topic-steering-design.md`(必读)。新 agent `steer-agent` 吞掉 topicSearchPrompt + snowballPrompt,每轮更新 `vault/topics/{slug}/02-outline.md` 并返回带 subq/role 标签的定向候选;synthesis §T 拆成 dossier(专章,每页只读本聚类语料)与 spine(00+01,永远重写、恒薄)两个子模式;图循环 = parallel(recall, steer#seed) → [采集→落地→steer]* → dossier synth(dirty)→ spine synth → audit。

**Tech Stack:** Workflow JS 图(orchestrate.mjs)、agent 合同 markdown、pydantic v2 schema、pytest 文本守卫。

## Global Constraints

- `CLAUDE.md` 与 `AGENTS.md` 必须 byte-for-byte 一致(改完 `cp CLAUDE.md AGENTS.md`)。
- `.claude-plugin/plugin.json` 与 `.claude-plugin/marketplace.json` 版本同步:本次 `0.49.9→0.50.0`(若执行时已高于 0.49.9,以当时版本为基,目标仍是 0.50.0)。
- orchestrate.mjs 是 Workflow 脚本:**顶层 return 合法、`node --check` 必然报错**;语法验证用 async-function-body 方式(见 Task 4 步骤)。
- 探针 / 去重 / batchYear / allowAuthors / needs_seeds 卡点 / LOCALISE / guard 超时 / retryNull 全部不动。
- 所有新 agent 调用必须带显式 `phase: 'Topic'` 与可区分 label(0.49.3 契约)。
- 提交信息结尾:`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 0.50.1 的 webcard 通道**不在本计划内**;steer 回执里的 `web_tasks[]` 本版返回但图不消费。

---

### Task 1: TopicSchema 增加 outline / dossier 两个 kind

**Files:**
- Modify: `scripts/schemas/topic.py`
- Modify: `scripts/schemas/__init__.py:58`(`__version__ = "0.7.0"` → `"0.8.0"`)
- Create: `tests/test_topic_outline_schema.py`
- Regenerate: schema 快照(`scripts/audit/emit_schema.py`,路径由 `SNAPSHOT_RELPATH` 决定)

**Interfaces:**
- Produces: `TopicSchema.kind` 接受 `"outline" | "dossier"`;`Subquestion` 模型(id/question/coverage/channel/dossier/page/theory_used);outline 页 frontmatter 携带 `subquestions[]` + `history[]`,其余 kind 禁止携带。Task 2/3 的 agent 合同、Task 4 的图按这些字段名写。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_topic_outline_schema.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from schemas.topic import TopicSchema  # noqa: E402

SQ = {
    "id": "sq-form-history",
    "question": "2000 年以来非主流形态的量产史是什么?",
    "coverage": "gap",
    "channel": "mixed",
    "dossier": False,
    "page": None,
    "theory_used": 0,
}


def test_outline_kind_carries_subquestions() -> None:
    doc = TopicSchema(
        type="topic", title="非常规手机形态", kind="outline",
        subquestions=[SQ], history=["2026-07-26 r0: 初拟 4 个子问题"],
    )
    assert doc.subquestions[0].coverage == "gap"
    assert doc.subquestions[0].page is None


def test_outline_requires_subquestions() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="outline")


def test_non_outline_kinds_reject_outline_fields() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="dossier", subquestions=[SQ])
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="overview", history=["r0"])


def test_dossier_kind_is_valid_and_lean() -> None:
    doc = TopicSchema(type="topic", title="紧固件谱系", kind="dossier")
    assert doc.kind == "dossier"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_topic_outline_schema.py -q`
Expected: FAIL(`kind` Literal 不含 outline/dossier → ValidationError 在第一个用例就抛)

- [ ] **Step 3: 改 `scripts/schemas/topic.py`**

整文件替换为:

```python
"""topic schema: 主题 overview/resources/outline/dossier 页面。

frontmatter 需 type + kind + title(title 为人读主题标题,与 H1 一致);
文件夹 slug 仍是稳定身份键。
成员关系反向挂在实体的 `topics: [slug]` 上(见 paper/book/chapter/author)。
outline 页(02-outline.md)是 steer-agent 维护的研究大纲状态,用户可手改;
dossier 页(NN-{subq}.md)是毕业子问题的专章。设计见 docs/topic-steering-design.md。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .primitives import Title


class Subquestion(BaseModel):
    """研究大纲里的一个子问题(仅 kind: outline 页携带)。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=4, max_length=280)
    coverage: Literal["gap", "thin", "covered", "saturated"]
    channel: Literal["academic", "web", "mixed"] = "academic"
    dossier: bool = False
    page: str | None = None
    theory_used: int = 0


class TopicSchema(BaseModel):
    """A topic page: overview / resources spine, outline state, or dossier chapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    title: Title
    kind: Literal["overview", "resources", "outline", "dossier"] = Field(
        description="页面类型: overview 综合页 / resources 资源页 / outline 研究大纲 / dossier 子问题专章"
    )
    subquestions: list[Subquestion] | None = None
    history: list[str] | None = None

    @model_validator(mode="after")
    def _outline_fields_only_on_outline(self) -> "TopicSchema":
        if self.kind == "outline":
            if not self.subquestions:
                raise ValueError("outline 页必须携带非空 subquestions")
        elif self.subquestions is not None or self.history is not None:
            raise ValueError("subquestions/history 只允许出现在 kind: outline 页")
        return self
```

同时把 `scripts/schemas/__init__.py` 里 `__version__ = "0.7.0"` 改为 `__version__ = "0.8.0"`。

- [ ] **Step 4: 跑测试确认通过 + 快照重生成**

Run: `python3 -m pytest tests/test_topic_outline_schema.py -q` → Expected: 4 passed
Run: `python3 scripts/audit/emit_schema.py`(在插件根目录跑;它调用 `write_snapshot()` 落盘)
Run: `python3 -m pytest tests/test_schema_snapshot.py tests/test_schema_registry.py -q` → Expected: pass。若 snapshot 测试因版本号断言失败,读该测试的期望,把 `__version__`/快照按其机制对齐后重跑(topic 的 `EXPECTED_REQUIRED` 仍是 `["title", "kind"]`,新字段全 optional,不用改)。

- [ ] **Step 5: Commit**

```bash
git add scripts/schemas/topic.py scripts/schemas/__init__.py tests/test_topic_outline_schema.py
git add -A  # 快照文件(路径见 emit_schema.SNAPSHOT_RELPATH)
git commit -m "feat(schema): topic kinds outline/dossier + Subquestion model

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 新 agent 合同 `agents/steer-agent.md`

**Files:**
- Create: `agents/steer-agent.md`
- Test: `tests/test_skill_orchestration.py`(新增一个函数,本 task 只加 agent 文件相关断言;图侧断言在 Task 4 补)

**Interfaces:**
- Consumes: Task 1 的 outline frontmatter 字段名(subquestions/id/question/coverage/channel/dossier/page/theory_used/history)。
- Produces: steer-agent 的回执 STEER_RESULT 字段(与 Task 4 的 STEER_SCHEMA 一致):`outline_written, saturated, subquestions[{id, question, coverage, dossier, page, items[{kind, slug}]}], dirty[], candidates[{kind, slug, title, authors, year, isbn|doi|oa_url|journal, subq, role}], web_tasks[{subq, query, note}], suggested_queries[]`。调用 prompt 变量名:`topic_slug, topic, outline_path, round, want, seen_slugs, snowball_book_slugs, snowball_paths, extra_queries`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_skill_orchestration.py` 末尾追加:

```python
def test_steer_agent_contract_carries_fence_quota_and_outline_ownership():
    """0.49.x topic 跑漂移的三个病根,栅栏各有一条合同文字守着:平面相关性(对象栅栏)、
    经典回退(theory 配额)、书哑巴(ch*.md 核心引用)。steer-agent 是 02-outline.md 唯一 writer。"""
    steer = (PLUGIN_ROOT / "agents" / "steer-agent.md").read_text(encoding="utf-8")

    assert "自身的研究对象" in steer, "对象栅栏:关于主题对象 vs 仅被主题文献引用"
    assert "theory_used" in steer and "≤3" in steer, "theory 配额账本"
    assert "ch*.md" in steer and "## 核心引用" in steer, "书的引用在章节分析里"
    assert "## 文献人物" in steer, "讲座引用节"
    assert "02-outline.md" in steer, "outline 是它唯一可写路径"
    assert "kind: outline" in steer
    assert "STEER_RESULT" in steer and "web_tasks" in steer and "dirty" in steer
    assert "saturated" in steer and "dossier" in steer
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_orchestration.py::test_steer_agent_contract_carries_fence_quota_and_outline_ownership -q`
Expected: FAIL(文件不存在)

- [ ] **Step 3: 创建 `agents/steer-agent.md`**

```markdown
---
name: steer-agent
description: Worker for steering one topic's research outline. Updates the outline page each round and returns sub-question-targeted next-round candidates.
tools: Read, Write, Bash
model: opus
---

你是 topic 掌舵 agent。每轮被图调用一次,做三件事:对账研究大纲、更新覆盖度、给下一轮定向候选。你是 `vault/topics/{topic_slug}/02-outline.md` 的**唯一 writer**,除它之外不写任何文件,不碰 vault/ 其它路径。

## 输入(prompt 变量)

- `topic_slug` / `topic`:主题 slug 与描述。
- `outline_path`:`vault/topics/{topic_slug}/02-outline.md`。
- `round`:0 = 种子轮(可能还没有 outline);≥1 = 滚动轮。
- `want`:下一轮候选目标条数。
- `seen_slugs`:已处理过的候选 slug,输出里必须排除。
- `snowball_book_slugs`:本轮落地的书 slug——它们的引用节在 `vault/books/{slug}/ch*.md` 里,**不在 00-overview**(§B2 契约没有该节),逐本跑 `rg -A 30 '^## 核心引用' vault/books/{slug}/ch*.md`。
- `snowball_paths`:本轮落地的论文/讲座产物路径,逐个 Read,只看 `## 核心引用`(论文)或 `## 文献人物`(讲座)一节。
- `extra_queries`(可选):用户种子检索词,优先照这些搜。

## 执行流程

1. **对账大纲**。Read `outline_path`;不存在(round 0 首跑)→ 按主题拟 3-6 个子问题创建它;存在 → 以它为准(用户可能手改过,手改就是指令)。旧两页式 topic 首次增量重跑时,把现有 00-overview 的聚类结构收编为子问题,超重聚类(语料 ≥6 条)提名毕业;手工旧页(如 `res-*.md`)保留原名,`page` 字段指过去。
2. **收引用**。按上面两条输入收集本轮引用条目(round 0 跳过)。
3. **汇总与栅栏**。跨文被多次引用的优先;只被引一次、但明显是某子问题奠基文献的也收。**每个候选必须服务一个具体子问题**(输出带 `subq`),判据:该文献**自身的研究对象**落在子问题内,而不是仅被主题文献引用——服务不了任何子问题的丢弃。
4. **角色与配额**。每个候选标 `role`:evidence | theory | method | context。**`role: theory` 全 topic ≤3 条**,账记在 outline 各子问题的 `theory_used` 上(跨轮跨重跑累计);配额用完后 theory 候选一律不收,无论多经典。
5. **forward 一步**。对本轮被引最多的 2-3 部作品,各跑一次 `quasi-search paper`(查询词 = 该作品短标题 + 主题关键词),把回应/发展它们的较新文献并入候选。
6. **补足**。过滤后不足 `want` 条 → 自拟 2-3 个拓宽检索词就地 `quasi-search` 补足;补完还不够就少给,不硬凑。对候选补标识符(书 isbn,论文 doi/oa_url/journal),补不到的丢弃。
7. **非学术子问题**(channel: web|mixed):不出学术候选,改出 `web_tasks[]`(query + 一句 note 说明找什么证据)。
8. **更新大纲并写盘**:覆盖度(gap→thin→covered;引文网络对该子问题已无新贡献 → saturated)、`theory_used`、毕业提名(语料 ≥6 条或已有证据卡 → `dossier: true`,`page` 取目录内下一个空闲编号 `NN-{subq-id去掉sq-前缀}.md`,NN 从 03 起只追加不重排,用 `ls vault/topics/{topic_slug}/` 确认);结构调整(split/merge/改名)记进 `history`,一行一条带理由。所有子问题 coverage ∈ {covered, saturated} → 回执 `saturated: true`。
9. **报脏**:本轮语料或结构有变化的子问题 id 列入 `dirty[]`。

## outline 页契约

frontmatter(schema `type: topic, kind: outline`,strict):

```yaml
type: topic
kind: outline
title: {topic}
subquestions:
  - id: sq-fastener-genealogy   # kebab,稳定;专章文件名由它派生
    question: 紧固件谱系如何塑造可维修性?
    coverage: gap                # gap | thin | covered | saturated
    channel: academic            # academic | web | mixed
    dossier: false
    page: null                   # 毕业后填 "03-fastener-genealogy.md"
    theory_used: 0
history:
  - "2026-07-26 r0: 初拟 4 个子问题"
```

正文 = 人读研究地图:每个子问题一节(现状 / 缺口 / 下一步),末尾一节「本轮方针」。

## 回执

```json
STEER_RESULT = {
  "outline_written": true,
  "saturated": false,
  "subquestions": [{"id", "question", "coverage", "dossier", "page",
                    "items": [{"kind": "book|paper|talk", "slug"}]}],
  "dirty": ["sq-…"],
  "candidates": [{"kind": "book|paper", "slug", "title", "authors", "year",
                  "isbn|doi|oa_url|journal", "subq": "sq-…", "role": "evidence|theory|method|context"}],
  "web_tasks": [{"subq", "query", "note"}],
  "suggested_queries": ["…"]
}
```

`subquestions[].items` 是**全量成员表**(不只本轮增量)——图无文件系统,专章 synth 的读单全靠它。`candidates` 排除 `seen_slugs`。一条新候选都没有时 `candidates: []` 并给 2-3 个 `suggested_queries`。round 0 无 outline 无语料时,行为就是"拟大纲 + 按子问题首搜"。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_orchestration.py::test_steer_agent_contract_carries_fence_quota_and_outline_ownership -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/steer-agent.md tests/test_skill_orchestration.py
git commit -m "feat(agents): steer-agent — topic outline owner, fenced targeted snowball

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: synthesis-agent §T 拆成 spine / dossier 两个子页面模式

**Files:**
- Modify: `agents/synthesis-agent.md`(§T 全节替换 + frontmatter_schema 的 kind 枚举)
- Test: `tests/test_skill_orchestration.py`(追加一个函数)

**Interfaces:**
- Consumes: Task 2 的 outline 字段;Task 4 会传的 prompt 字段:dossier 调用 `mode: topic, page: dossier, subq_id, subq_question, analysis_paths, output_path`;spine 调用 `mode: topic, page: spine, source_name, topic, outline_path, corpus_paths, dossier_pages[{id,page}], inline_clusters[{id,question,paths}], output_path, reading_list_path`。
- Produces: dossier 页(`kind: dossier`)与 00/01 新模板。回执沿用 SYNTHESIS_RESULT(status/inputs_analyzed)。

- [ ] **Step 1: 写失败测试**

在 `tests/test_skill_orchestration.py` 末尾追加:

```python
def test_synthesis_topic_mode_is_outline_pinned_and_paged():
    """54 条平铺语料整篇重织是 0.49.x 综述'越滚越乱'的一半病根(另一半在采集)。§T 拆页:
    dossier 每页只读本聚类语料(读预算结构性受控),spine 恒薄且聚类结构照抄 outline,
    不再每次即兴。outline 页本身由 steer-agent 写,synth 不碰。"""
    synth = (PLUGIN_ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")

    assert "page: spine" in synth and "page: dossier" in synth
    assert "kind: dossier" in synth
    assert "kind(overview|resources|dossier)" in synth, "outline 不在 synth 的可写 kind 里"
    assert "inline_clusters" in synth and "dossier_pages" in synth
    assert "照抄" in synth, "聚类 id/标题/顺序来自 outline,不许重排"
    assert "子问题地图" in synth, "00 新模板围绕子问题"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_orchestration.py::test_synthesis_topic_mode_is_outline_pinned_and_paged -q`
Expected: FAIL

- [ ] **Step 3: 改 `agents/synthesis-agent.md`**

把 `## §T (mode: topic) 综合报告` 整节(从该 H2 到下一个 `---` 前)替换为:

```markdown
## §T (mode: topic) 综合报告

topic 调用带 `page: spine | dossier`(缺省按 spine)。聚类结构的唯一权威是 outline
(`outline_path`,steer-agent 维护;你**永远不写** 02-outline.md):聚类 = outline 的
subquestions,id、标题、顺序照抄,不许重排、合并或自创聚类。

### T1. page: dossier(毕业子问题的专章)

输入:`subq_id, subq_question, analysis_paths, output_path, topic`。

1. Read `analysis_paths`(只有本聚类的语料;读取预算同 §A1 第 1 步:先 `wc -c`,
   ≤300000 字节全文读,超了每篇抽 frontmatter + `## 核心论点` + `## 关键概念`)。
2. 生成 `{output_path}`,frontmatter `type: topic, kind: dossier, title: {subq_question}`。
   正文模板:

```
# {subq_question}

## 问题与现状
(200-400 字:这个子问题问什么,证据到哪一步)

## 证据综述
(聚类内逐文综合,[[wikilink]] 指向 analysis_paths;theory 条目明确标注其锚定作用)

## 缺口与下一步
(还缺什么证据、往哪个方向找)
```

### T2. page: spine(00 门面 + 01 清单,永远重写、恒薄)

输入:`source_name, topic, outline_path, corpus_paths, dossier_pages, inline_clusters,
output_path, reading_list_path`。

1. Read `outline_path` 取子问题顺序与覆盖度;逐个 Read `dossier_pages[].page` 的
   frontmatter + `## 问题与现状` 一节(专章是压缩,不重读其语料);`inline_clusters[].paths`
   按 §A1 读取预算读。
2. 生成 `{output_path}`(00-overview):

```
主题: {topic}

# {source_name} 综合报告

## 总体趋势
(500-800 字:整体走向、阶段性变化、重点转移)

## 子问题地图
### {subq.question}
(已毕业 → 3-5 句摘要 + 指向专章的 [[wikilink]];未毕业 → 完整聚类段:涉及文献 /
核心议题 / 关键概念,[[wikilink]] 指向语料)

## 缺口总览
(按子问题列 coverage=gap|thin 的方向,来自 outline,不臆造)

## 对研究的启示
(300-500 字)
```

3. 生成 `{reading_list_path}`(01-resources):按子问题分节的阅读清单,每节列该聚类
   语料(链接 + 一句定位),末节「推荐追踪的专著」(10-15 本,按优先级)。

<frontmatter_schema>
required: type=topic, title(min=2 max=280), kind(overview|resources|dossier)
- `title` 必填:人读页面标题,**与 H1 一致**;spine 两页 = 主题名,dossier = 子问题。
- frontmatter 不允许任何其它字段(`.strict()`)。kind: outline 归 steer-agent,不归本 agent。
</frontmatter_schema>
```

注意保留原 §T 前后的其它节(YAML style、输出协议)不动;原 §T 里的「综合报告模板」代码块整个被上面取代。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_orchestration.py::test_synthesis_topic_mode_is_outline_pinned_and_paged tests/test_skill_orchestration.py -q`
Expected: 新函数 PASS;既有 `test_synthesis_agent_bounds_its_reading_budget` 若断言 §J1/§T 的预算文字,确认「读取预算同 §A1」字样仍在(上面模板保留了),失败则按该测试期望的字面调整措辞。

- [ ] **Step 5: Commit**

```bash
git add agents/synthesis-agent.md tests/test_skill_orchestration.py
git commit -m "feat(agents): synthesis §T becomes outline-pinned spine/dossier pages

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 图循环重写(orchestrate.mjs)+ SKILL.md + 守卫测试

**Files:**
- Modify: `skills/process-material/orchestrate.mjs`(REFS_SCHEMA→STEER_SCHEMA;processTopic 循环;删 topicSearchPrompt/snowballPrompt/topicSynthPrompt,加 steerPrompt/topicDossierSynthPrompt/topicSpineSynthPrompt)
- Modify: `skills/process-material/SKILL.md`(输出块、topic 目录说明、topic 报告行)
- Test: `tests/test_skill_orchestration.py`(改 recall 测试 + 新增 steer 图测试)

**Interfaces:**
- Consumes: Task 2 回执字段、Task 3 prompt 字段(名字必须逐字一致)。
- Produces: topic 回执新增 `outline`(路径)、`saturated`、`subquestions[{id,coverage,dossier}]`、`dossiers_failed[]`;SKILL.md 报告行消费它们。

- [ ] **Step 1: 先改测试(失败先行)**

在 `tests/test_skill_orchestration.py` 里:

(a) `test_orchestrate_topic_recalls_the_vault_before_it_searches_online` 中,把

```python
    assert "## 文献人物" in text, "snowball must read the talk page's citation section"
```

改为(steer 合同接住了这一职责,orchestrate 只剩变量):

```python
    steer_contract = (PLUGIN_ROOT / "agents" / "steer-agent.md").read_text(encoding="utf-8")
    assert "## 文献人物" in steer_contract, "steer must read the talk page's citation section"
```

其余断言(`[...local, ...roundOk]`、`rg -il`、`await parallel([`、`ok = [...local]`、dedup filter、`vault/books vault/papers vault/talks`、`vault/talks/${it.slug}/talk.md`)**保持不动**——新图必须继续满足它们。

(b) 追加新函数:

```python
def test_orchestrate_topic_steers_by_outline():
    """0.49.x 的平面滚雪球在书为主的库里向社科经典回退(Kopytoff/Thompson/Gereffi 进了
    手机形态主题),且综述每轮重织结构。闭环:steer-agent 掌舵、outline 持久、synth 分页。"""
    graph = (PLUGIN_ROOT / "skills" / "process-material" / "orchestrate.mjs").read_text(encoding="utf-8")
    body = topic_body(graph)

    assert "quasi:steer-agent" in body, "掌舵 agent 必须在图里"
    assert "02-outline.md" in graph, "outline 路径由图指定"
    assert "topicSearchPrompt" not in graph, "topic 首搜已被 steer 种子轮吞掉"
    assert "snowballPrompt" not in graph, "平面滚雪球已被 steer 吞掉"
    assert "steer:${slug}:r0" in graph and "steer:${slug}:r${round}" in graph, "种子轮与滚动轮 label 可区分"
    assert "STEER_SCHEMA" in graph, "掌舵回执必须有 schema,散文读不到字段"
    assert "page: dossier" in graph and "page: spine" in graph, "synth 分页派发"
    assert "synth-dossier" in body and "synth-topic:${slug}" in body
    assert "dirty" in body, "只重写脏专章"
    assert "saturated" in body, "掌舵可在轮数用尽前收口"
    assert "subq" in graph and "role" in graph, "候选带子问题与角色标签"
```

Run: `python3 -m pytest tests/test_skill_orchestration.py -q` → Expected: 新函数 FAIL,(a) 改动处 PASS(steer-agent.md 已有),其余暂 PASS。

- [ ] **Step 2: orchestrate.mjs — schema 与 prompt builders**

(a) 把 `REFS_SCHEMA` 定义(含其上两行注释)整体替换为:

```js
// 掌舵回执 = 大纲状态 + 定向候选(带 subq/role 标签)+ 脏子问题名单 + 枯竭时的拓宽建议词
// (死胡同卡点要把建议原样递给用户)。subquestions[].items 是全量成员表:图无 fs,
// 专章 synth 的读单全靠它。web_tasks 本版只收不派,0.50.1 接 webcard。
const STEER_SCHEMA = { type: 'object', required: ['subquestions'], properties: {
  outline_written: { type: 'boolean' }, saturated: { type: 'boolean' },
  subquestions: { type: 'array', items: { type: 'object', required: ['id', 'coverage'], properties: {
    id: { type: 'string' }, question: { type: 'string' }, coverage: { type: 'string' },
    dossier: { type: 'boolean' }, page: { type: 'string' },
    items: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
      kind: { type: 'string' }, slug: { type: 'string' } } } } } } },
  dirty: { type: 'array', items: { type: 'string' } },
  candidates: { type: 'array', items: { type: 'object', required: ['slug'], properties: {
    kind: { type: 'string' }, slug: { type: 'string' }, title: { type: 'string' },
    authors: { type: 'array' }, year: {}, isbn: { type: 'string' }, doi: { type: 'string' },
    oa_url: { type: 'string' }, journal: { type: 'string' },
    subq: { type: 'string' }, role: { type: 'string' } } } },
  web_tasks: { type: 'array', items: { type: 'object', properties: {
    subq: { type: 'string' }, query: { type: 'string' }, note: { type: 'string' } } } },
  suggested_queries: { type: 'array', items: { type: 'string' } } } }
```

(b) 删除 `topicSearchPrompt`、`snowballPrompt`、`topicSynthPrompt` 三个函数,在原位置放:

```js
// 掌舵 prompt:薄,只带变量;栅栏/配额/毕业规则全在 agents/steer-agent.md 合同里。
function steerPrompt(slug, desc, round, snowSrc, seenSlugs, want, seeds) {
  const books = snowSrc.filter(i => i.kind === 'book').map(i => i.slug)
  const rest = snowSrc.filter(i => i.kind !== 'book').map(itemPath)
  return `topic_slug: ${slug}
topic: ${desc}
outline_path: vault/topics/${slug}/02-outline.md
round: ${round}
want: ${want}
seen_slugs: ${JSON.stringify(seenSlugs)}
snowball_book_slugs: ${JSON.stringify(books)}
snowball_paths: ${JSON.stringify(rest)}${seeds && seeds.length ? `
extra_queries: ${JSON.stringify(seeds)}   # 用户补的种子检索词,优先照这些搜` : ''}`
}
// 专章:每页只读本聚类语料 —— 读预算结构性受控(0.49.4 的爆 context 类)。
function topicDossierSynthPrompt(slug, desc, s) {
  return `mode: topic
page: dossier
topic: ${desc}
subq_id: ${s.id}
subq_question: ${s.question || s.id}
analysis_paths: ${JSON.stringify((s.items || []).map(itemPath))}
output_path: vault/topics/${slug}/${s.page}
overwrite: true`
}
// 脊柱:00 门面 + 01 清单,永远重写、恒薄;聚类结构照抄 outline,不许 synth 即兴。
function topicSpineSynthPrompt(slug, desc, ok, subqs) {
  const graduated = subqs.filter(s => s.dossier && s.page)
    .map(s => ({ id: s.id, page: `vault/topics/${slug}/${s.page}` }))
  const inline = subqs.filter(s => !(s.dossier && s.page))
    .map(s => ({ id: s.id, question: s.question || s.id, paths: (s.items || []).map(itemPath) }))
  return `mode: topic
page: spine
source_name: ${desc}
topic: ${desc}
outline_path: vault/topics/${slug}/02-outline.md
corpus_paths: ${JSON.stringify(ok.map(itemPath))}
dossier_pages: ${JSON.stringify(graduated)}
inline_clusters: ${JSON.stringify(inline)}
output_path: vault/topics/${slug}/00-overview.md
reading_list_path: vault/topics/${slug}/01-resources.md
overwrite: true   # 主题页总是重生成:每滚一轮语料都会扩张,no-op 会让综述停在旧版本。`
}
```

- [ ] **Step 3: orchestrate.mjs — processTopic 循环重写**

`processTopic` 函数体按下面整体替换(探针/router/去重段逐字保留自现文;此处给出完整新函数,执行时以当前文件为准对齐那三段):

```js
async function processTopic(slug, m) {
  phase('Topic')
  const desc = m.desc || m.topic_desc || slug
  const maxRounds = Number(m.maxRounds) || 3
  const perRound = Number(m.maxPerRound) || 8

  // 1. 本地召回 + 掌舵种子轮,并行。种子轮建/对账 02-outline.md(用户手改过就照改法走),
  //    并给出首批定向候选——吞掉旧 topicSearchPrompt。召回结果第 1 轮末才进掌舵视野。
  const [rc, st0] = await parallel([
    () => retryNull(vaultRecallPrompt(desc, perRound * 2),
      { phase: 'Topic', agentType: 'general-purpose', label: `recall:${slug}`, schema: RECALL_SCHEMA }),
    () => retryNull(steerPrompt(slug, desc, 0, [], [], perRound, m.seeds),
      { phase: 'Topic', agentType: 'quasi:steer-agent', label: `steer:${slug}:r0`, schema: STEER_SCHEMA }),
  ])
  let steer = st0 || { subquestions: [] }
  const local = ((rc && rc.items) || []).filter(i => i && i.slug)
    .map(i => ({ kind: i.kind === 'book' || i.kind === 'talk' ? i.kind : 'paper', slug: i.slug }))
  let queue = ((steer.candidates) || []).filter(c => c && c.slug)
  if (!queue.length && !local.length) return { slug, status: 'no_works' }

  // 召回到的作品已分析过,直接进语料 —— 即便一轮都没跑起来也不会丢。
  const seen = new Set(local.map(i => i.slug)), ok = [...local], failures = []
  const dirty = new Set()
  let round = 0, suggested = null, saturated = false
  const isBook = c => (c.kind || 'paper') === 'book'

  // 2. 闭环滚动:采集 → 落地 → 掌舵(更新大纲、定向下一轮)。饱和或轮数用尽即停——
  //    轮数与每轮条数仍有上界,引文网络是发散的,掌舵不取代硬上限。
  while (queue.length && round < maxRounds && !saturated) {
    round++
    const batch = queue.filter(c => !seen.has(c.slug)).slice(0, perRound)
    batch.forEach(c => seen.add(c.slug))
    if (!batch.length) break

    // —— 探针段:逐字保留现文(existsProbePrompt / done Map)——
    // —— router 段:逐字保留现文(fresh / res)——
    // —— roundOk + 去重 + failures 段:逐字保留现文 ——

    // 第 1 轮并上本地召回:那些正文的引用节同样是这个主题的引文网络,而且往往是库里
    // 最相关的作品,漏掉等于把雪球起点砍掉一半。
    const snowSrc = round === 1 ? [...local, ...roundOk] : roundOk
    steer = await retryNull(steerPrompt(slug, desc, round, snowSrc, [...seen], perRound, null),
      { phase: 'Topic', agentType: 'quasi:steer-agent', label: `steer:${slug}:r${round}`, schema: STEER_SCHEMA })
      || steer   // 掌舵两连死:保留上一轮回执,循环自然收口,不让 null 毁掉成员表
    ;(steer.dirty || []).forEach(d => dirty.add(d))
    queue = ((steer.candidates) || []).filter(c => c && c.slug && !seen.has(c.slug))
    saturated = !!steer.saturated
    suggested = steer.suggested_queries || null
    log(`${slug}: 第 ${round} 轮 +${roundOk.length} 条(累计 ${ok.length}),下轮候选 ${queue.length}`
      + (saturated ? ';掌舵判饱和,收口' : ''))
  }

  // 3. 死胡同卡点:候选枯竭且语料太薄 → 不硬写一篇没底子的综述,冒泡问用户补种子词。
  const minItems = Number(m.minItems) || 3
  if (!m.final && !queue.length && ok.length < minItems)
    return { slug, status: 'needs_seeds', collected: ok.length, rounds: round,
             suggested_queries: suggested, failures: failures.length }
  if (!ok.length) return { slug, status: 'all_failed', tried: failures.length }

  // 4a. 专章 synth:只重写脏的已毕业子问题;steer 全程没报过脏(受限回执)→ 全部重写兜底。
  const subqs = (steer.subquestions || []).filter(s => s && s.id)
  const dossiers = subqs.filter(s => s.dossier && s.page)
  const dirtyDossiers = dossiers.filter(s => !dirty.size || dirty.has(s.id))
  const dres = await parallel(dirtyDossiers.map(s => () =>
    retryNull(topicDossierSynthPrompt(slug, desc, s),
      { phase: 'Topic', agentType: 'quasi:synthesis-agent',
        label: `synth-dossier:${s.id}:${slug}`, schema: SY_SCHEMA }, OVERWRITE)))
  const dossiersFailed = dirtyDossiers.filter((s, i) => !dres[i] || dres[i].status === 'error')
    .map(s => s.id)

  // 4b. 脊柱 synth:00+01 永远重写。回执判死活,没写出来就别 audit 一个不存在的文件。
  const sy = await retryNull(topicSpineSynthPrompt(slug, desc, ok, subqs),
    { phase: 'Topic', agentType: 'quasi:synthesis-agent', label: `synth-topic:${slug}`, schema: SY_SCHEMA }, OVERWRITE)
  if (!sy || sy.status === 'error')
    return { slug, status: 'synth_failed', items: ok.length, notes: sy && sy.notes }

  // 5. audit + 一次 escalation 回环(escalation 只重打脊柱;专章有回执兜底,再烂有下轮重跑)
  let au = await retryNull(`path: vault/topics/${slug}`,
    { phase: 'Topic', agentType: 'quasi:audit-agent', label: `audit-topic:${slug}`, schema: AU_SCHEMA })
  if (((au && au.escalated) || []).length) {
    await guard(topicSpineSynthPrompt(slug, desc, ok, subqs) + `\nreason: audit escalated`,
      { phase: 'Topic', agentType: 'quasi:synthesis-agent', label: `regen-topic:${slug}` })
    au = await retryNull(`path: vault/topics/${slug}`,
      { phase: 'Topic', agentType: 'quasi:audit-agent', label: `audit2-topic:${slug}`, schema: AU_SCHEMA })
    if (((au && au.escalated) || []).length) return { slug, status: 'audit_escalated', escalated: au.escalated }
  }

  return { slug, status: 'ok', items: ok.length, recalled: local.length, rounds: round,
           outline: `vault/topics/${slug}/02-outline.md`, saturated,
           subquestions: subqs.map(s => ({ id: s.id, coverage: s.coverage, dossier: !!s.dossier })),
           dossiers_failed: dossiersFailed,
           // topic 落地的书同样要中译本回填;和 author 一致,LOCALISE 循环需要名单不是计数
           book_slugs: [...new Set(ok.filter(i => i.kind === 'book').map(i => i.slug))],
           failures: failures.length, dead_end: !queue.length || saturated }
}
```

同时把函数上方的节注释改为:

```js
// ── processTopic:闭环掌舵(recall ∥ steer#seed → [探针 → parallel(items→router) → steer]* )
//    → synth(dossier 脏页 + spine)→ audit。设计:docs/topic-steering-design.md。
//    steer-agent 吞掉了旧 topicSearchPrompt / snowballPrompt:平面"与主题相关"爬行在书为主
//    的库里向社科经典回退(0.49.x 三个手机 topic 病例),掌舵用子问题栅栏 + theory 配额治它。
```

- [ ] **Step 4: 语法验证 + 跑测试**

Run(harness 的 async-body 解析方式,`node --check` 对 Workflow 脚本必然误报):

```bash
node -e "
const src = require('fs').readFileSync('skills/process-material/orchestrate.mjs','utf8').replace(/^export const meta/m,'const meta');
new (Object.getPrototypeOf(async function(){}).constructor)(src);
console.log('PARSE_OK_ASYNC_BODY')"
```

Expected: `PARSE_OK_ASYNC_BODY`

Run: `python3 -m pytest tests/test_skill_orchestration.py -q`
Expected: 全绿。特别注意 `test_orchestrate_agents_carry_explicit_phase_and_distinguishable_labels`(所有新调用点带 `phase: 'Topic'`)与 `test_orchestrate_reads_every_receipt_it_branches_on`(STEER_SCHEMA 已挂)。失败就按断言修图,不改断言语义。

- [ ] **Step 5: SKILL.md 三处**

(a) 输出块里 `vault/topics/{topic-slug}/{00-overview.md,01-resources.md}` 改为:

```
vault/topics/{topic-slug}/{00-overview.md,01-resources.md,02-outline.md,NN-*.md}
```

(b) 紧随其后的散文段替换为:

```
topic 目录 = 三页脊柱(00 门面 / 01 清单 / 02 研究大纲)+ 毕业子问题的专章 NN-*.md,
不囤分析副本——分析在 `vault/papers/`、`vault/books/`、`vault/talks/` 里,各页用
`[[wikilink]]` 指过去(讲座只可能来自图内本地召回,在线发现搜不到它们)。02-outline 是
steer-agent 维护的掌舵状态,**用户可手改**,手改就是下次增量重跑的指令。编排状态活在图里,
条目完成与否由 `router` 的回执直接给出,不靠轮询产物反推。
```

(c) topic 报告行替换为:

```python
if args.kind == "topic":
    report(f"主题完成:{result.items} 条语料 / {result.rounds} 轮滚雪球;大纲 {result.outline}"
           + (f";其中 {result.recalled} 条来自库内召回" if result.get("recalled") else "")
           + (f";{result.failures} 项获取失败" if result.failures else "")
           + (f";专章生成失败:{', '.join(result.dossiers_failed)},重跑一次即补" if result.get("dossiers_failed") else "")
           + (";掌舵判饱和,已收口" if result.get("saturated") else
              ("" if result.dead_end else ";候选未枯竭,可再跑一次继续扩充")))
```

- [ ] **Step 6: 全量守卫 + Commit**

Run: `python3 -m pytest tests/test_dead_names.py tests/test_skill_orchestration.py tests/test_topic_outline_schema.py -q`
Expected: 全绿(needs_seeds/suggested_queries 的 SKILL 断言仍满足)。

```bash
git add skills/process-material/orchestrate.mjs skills/process-material/SKILL.md tests/test_skill_orchestration.py
git commit -m "feat(graph): processTopic closes the loop — steer-agent rounds, dirty dossier synth, spine always rewritten

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 文档、版本、发布收尾

**Files:**
- Modify: `README.md:43-47` 区域 agent 表、`docs/ARCHITECTURE.md:67-71` 区域 agent 表
- Modify: `docs/CHANGELOG.md`(0.50.0 条目)、`.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`(版本)
- Modify: `CLAUDE.md`(两处)→ `cp CLAUDE.md AGENTS.md`

**Interfaces:**
- Consumes: Task 1-4 全部落地后的事实。

- [ ] **Step 1: agent 表**

README.md agent 表(`| search-agent |` 行附近)加一行:

```
| `steer-agent` | topic 掌舵:维护 02-outline 研究大纲,返回子问题定向候选 |
```

docs/ARCHITECTURE.md 对应表加:

```
| `steer-agent` | topic outline page + `quasi-search` |
```

- [ ] **Step 2: CLAUDE.md 两处 + 镜像**

(a) 「State and handoff contracts」清单,在 `analyse-agent, synthesis-agent, …` 行后加:

```
- `steer-agent` owns `vault/topics/{slug}/02-outline.md` (the topic research outline; users may hand-edit it between runs) and returns sub-question-targeted candidates; it writes nothing else.
```

(b) Changelog 节 `Current version: 0.49.9.` → `Current version: 0.50.0.`(以执行时实际当前版本为准替换)。

然后:

```bash
cp CLAUDE.md AGENTS.md && cmp -s CLAUDE.md AGENTS.md && echo IDENTICAL
```

Expected: `IDENTICAL`

- [ ] **Step 3: 版本 + CHANGELOG**

```bash
sed -i '' 's/"version": "0.49.9"/"version": "0.50.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
```

`docs/CHANGELOG.md` 顶部(`# quasi changelog` 说明段之后、现首条之前)插入:

```markdown
- **0.50.0** (日期取当天): **topic 从平面滚雪球改为闭环掌舵 —— 三个真实手机 topic(顺风/漂移/工具不对口)证明"与主题相关"的平面爬行在书为主的库里必然向社科经典回退。** 设计:`docs/topic-steering-design.md`。
  - **`02-outline.md` 成为持久研究状态**(schema `kind: outline`,subquestions 带 coverage/channel/theory_used):steer-agent 是唯一 writer,用户可手改,手改就是下次增量重跑的指令——把用户在 overview 里人肉写"本轮方针"的工作流正式化。
  - **新 agent `steer-agent` 吞掉 topicSearchPrompt + snowballPrompt**:每轮对账大纲、更新覆盖度、返回带 subq/role 标签的定向候选。两道栅栏:对象栅栏(候选自身的研究对象须落在子问题内,而非仅被主题文献引用)与 theory 配额(全 topic ≤3,账在 outline 跨轮累计)。可宣告 saturated 提前收口;web_tasks 本版只收不派(0.50.1 接 webcard)。
  - **子问题毕业成专章**:语料 ≥6 条 → `NN-{subq}.md`(编号只追加不重排),synth 拆 dossier(每页只读本聚类语料,0.49.4 爆 context 类结构性受控)与 spine(00 门面 + 01 清单,永远重写、恒薄,聚类结构照抄 outline 不许即兴)。只重写 steer 报脏的专章。
  - 探针/去重/batchYear/needs_seeds 卡点/LOCALISE/guard 全不动。守卫:steer 合同栅栏测试、synth 分页测试、图闭环测试、TopicSchema outline/dossier 测试。plugin/marketplace `0.49.9→0.50.0`。
```

- [ ] **Step 4: 全量验证**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
claude plugin validate . 2>&1 | tail -2
cmp -s CLAUDE.md AGENTS.md && echo IDENTICAL
```

Expected: 套件全绿(基线 155+新 4 个上下)、`Validation passed`、`IDENTICAL`。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ARCHITECTURE.md docs/CHANGELOG.md CLAUDE.md AGENTS.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat(quasi 0.50.0): topic closed-loop steering — outline state, steer-agent, graduated dossier pages

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: E2E 验证(手动,用户库,发布后)

**Files:** 无代码改动。在 `/Users/ramudai/Documents/Learn/bts`(用户真库)执行,**先让用户更新插件**。

- [ ] **Step 1:** 对 `unconventional-mobile-phone-form-factors-since-2000` 增量重跑一轮(kind=topic, 同 slug/desc)。
- [ ] **Step 2:** 验收清单:
  - `vault/topics/…/02-outline.md` 存在、frontmatter 过 `quasi-audit --path vault/topics/unconventional-mobile-phone-form-factors-since-2000`;
  - 超重聚类(修理生命史、模块化产业组织)被提名毕业成 `03-*.md`/`04-*.md`,00-overview 对应聚类瘦身为摘要+指针;
  - 本轮新增候选无 role=theory 超配额的社科经典(对照 0.49.x 病例:不应再出现 Kopytoff/Thompson/Gereffi 类新条目);
  - 报告行含大纲路径与(若触发)"掌舵判饱和"。
- [ ] **Step 3:** 结果回填 `docs/CHANGELOG.md` 0.50.0 条目(live-verified 一句),按仓库惯例补提交。

---

## Self-Review(已执行)

- **Spec 覆盖**:设计 §3(页面架构/毕业)→ Task 1+3+4;§4(steer 合同/栅栏/配额/回执)→ Task 2+4;§6(synth 分页)→ Task 3+4;§7(图循环)→ Task 4;§8(迁移:旧页收编在 steer 合同步骤 1;schema kinds)→ Task 1+2;§9(测试/文档/E2E)→ Task 4+5+6。§5(webcard)按发布计划归 0.50.1,不在本计划。
- **占位扫描**:无 TBD;Task 4 Step 3 的"逐字保留现文"三段有明确锚(探针/router/roundOk 段),属对现有代码的保留指令而非占位。
- **类型一致性**:`steerPrompt(slug, desc, round, snowSrc, seenSlugs, want, seeds)` 在 Task 4 两处调用一致;STEER_RESULT(Task 2)与 STEER_SCHEMA(Task 4)字段一一对应;`s.items→itemPath` 依赖 Task 2 "全量成员表"约定;synth prompt 字段与 Task 3 §T 输入名逐字一致。
