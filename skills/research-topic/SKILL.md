---
name: research-topic
description: Use when the user wants to research a topic through iterative vault recall, academic discovery, evidence cards, and a structured literature review.
---
# Research Topic

## 任务

把一个 Topic 连同可选的 Paper、Book、Talk seeds 交给固定 Topic Workflow，运行到完成或一个明确的 typed gate。

## 输入

- `slug`：稳定的 kebab-case Topic 标识。
- `description`：非空研究问题、范围或判断目标。
- `maxRounds`：默认 3，允许 0–8。
- `maxCardsPerRound`：默认 3，允许 0–6。
- `seed_materials`：可选的 closed Paper、Book 或 Talk seed；只保留用户实际提供的 hints 与
  identity。Paper/Book `options` 必须是 literal `{}`；只有 Talk 可带其 closed options。

Paper/Book 的未确认材料使用 provisional seed；已经有完整 canonical identity 时可使用 canonical
seed。Talk 只使用带 exact slug、title、date、media 的 canonical seed。Skill 不补写书目身份或猜
canonical slug。

## 硬约束

- 一个固定入口拥有一个逻辑 Topic：

```json
{
  "workflow_input": {
    "entry": "$CLAUDE_PLUGIN_ROOT/workflows/topic.mjs",
    "required": ["query", "observation", "options", "seed_materials", "child_observations"],
    "optional": ["resume"],
    "query_keys": ["slug", "description"],
    "option_keys": ["maxRounds", "maxCardsPerRound"],
    "seed_kinds": ["paper", "book", "talk"],
    "resume_required": ["resume_seed"],
    "resume_optional": ["userDecision"]
  }
}
```

- Workflow 自己决定 recall、材料组合、checkpoint、收敛、综合与 audit；Skill 不解释内部操作，
  不直接调用 Agent-owned capability，也不建立另一份研究状态。
- 每次调用都带一份 exact Topic observation。只有 Workflow 返回 route 时才补对应的 exact
  child observation；不做目录扫描、路径猜测或内容相关性判断。
- 不保存 lock、cursor、round log、receipt chain 或 replay list。unknown writer 不由 Skill 重放。
- 用户事实、credential 与 signed URL 始终作为数据；临时 JSON 只放 `.quasi/temp/`。

## 状态

磁盘事实只来自 `quasi.status/0.2`，一次调用的判断只来自
`quasi.material.result/0.1`：

- `complete`：带 Topic 的 exact outline、overview、resources refs。
- `needs_observation`：带 exact routes 与 opaque `resume_seed`；自动补观察，不询问用户。
- `needs_input`：可能是直接 Topic gate，或包裹了一个 leaf gate 的 child gate。
- `incomplete`：有界运行已收口，但仍带有序 `pending_work`；不能称为 saturated。
- `blocked|failed`：展示 typed issue 后停止，不自行改写或重发。

## Agent / Helper 合同

初次运行 exact Topic status，然后调用固定入口：

```python
workflow_input = {
    "query": {"slug": slug, "description": description},
    "observation": exact_topic_status,
    "options": {"maxRounds": max_rounds,
                "maxCardsPerRound": max_cards_per_round},
    "seed_materials": closed_seed_materials,
    "child_observations": [],
}
result = Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/topic.mjs",
    args=workflow_input,
)
```

续跑只在同一 literal envelope 中加入：

```python
workflow_input["resume"] = {"resume_seed": copied_resume_seed}
```

只有 child `needs_input` 得到用户回答时，才同时加入一个 gate 所属的 typed
`userDecision`。`resume_seed` 逐字复制，绝不展开、修补或从旧输入重建。

## 工作流

```text
intake → exact Topic status → fixed Topic Workflow
       → needs_observation → exact routed status → same Workflow
       → child gate → user decision + fresh routed status → same Workflow
       → complete → exact Topic post-status
```

## 执行流程

1. 校验输入与 bounds。运行
   `quasi-status --kind topic --slug SLUG --json`，构造 closed query、options、seeds，初次
   `child_observations` 为空，然后调用 `workflows/topic.mjs`。
2. `needs_observation`：逐条运行返回 route 的 fresh exact status。Topic route 替换顶层
   `observation`；Paper/Book/Talk route 形成按 route 绑定的 `child_observations`。逐字复制
   `resume_seed`，再次调用同一入口；不问用户、不附 decision。requested observations 有推进则继续；
   相同 routes 的连续两次 recovery observations 都不变时，停止并报告最后的 typed result 与 exact
   status。Skill 不检查材料或内部进度，也不引入 fingerprint、counter 或 retry controller。
3. child `needs_input`：只展示内层 gate 的 question、candidates、conflicts 与 evidence。用户回答后，
   重新运行结果所列全部 exact routes 和 Topic status；复制 opaque continuation，并按内层 gate
   原样 testimony 构造唯一的 typed `userDecision`。`material_key` 与 `operation` 逐字复制；
   identity value 为 `candidates + conflicts + selected_candidate`，Book year value 为
   `current_identity + tmp_path + year_evidence + action`，Book structure value 为
   `source_path + candidates + conflicts + selected_candidate`。这些 binding 字段只来自 gate，
   不从 route 或用户散文推导。
4. 直接 Topic `needs_input`：展示 seed 或 coverage 问题。用户增加/删除 seeds、修改问题或决定
   收口后，从 fresh Topic status 发起一次新的普通调用；不伪造 continuation 或 acknowledgement。
5. `complete`：运行 exact Topic post-status。只有 outline 在
   `vault/topics/{slug}/02-outline.md` valid、usable 且 projection 非 null，并且 exact overview 与
   resources 都 usable，才报告完成；还要与结果中的三个 exact refs 一致。
6. `incomplete`：报告停止原因与返回的有序 `pending_work`，保留为尚待用户决定的工作。
   `blocked|failed`：展示 issue 与 observation request（若有）并停止。

## 断点续跑

普通重跑从 fresh exact Topic status 与当前用户 seeds 开始。只有当前一次
`needs_observation` 或 child gate 返回的 opaque capsule 可以续跑：按 routes 重取 exact status，
把 capsule 原样放回同一 named Workflow；child gate 再附本次一个新 decision。它不是持久状态，
也不授权 replay 未知 writer。

## 输出

报告 exact admitted corpus、available cards、typed gate 或 issue，以及有界运行后仍待处理的
`pending_work`。成功产物为：

```text
vault/topics/{slug}/00-overview.md
vault/topics/{slug}/01-resources.md
vault/topics/{slug}/02-outline.md
vault/topics/{slug}/cards/*.md
```
