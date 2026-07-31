# Material Loop Protocol v0.1

状态：**current contract**
Reference implementation：**Paper Loop**

## 1. 目的

Material Loop Protocol 定义一份材料从已知事实出发，经过具名 Operation、审计与有限修复，最终收敛为可信产物的共同控制合同。

它不规定 Handler 必须是 Agent 还是 Bin，也不把 library 当成一个执行层：

```text
Material Loop
  ├─ 调用具名 Operation
  │    └─ Handler = Agent | Bin | composite
  └─ 读写持久 artifacts
       sources/ · processing/ · vault/
```

Paper 是 v0.1 的 reference implementation。Book、Talk、Web、Image、Note 将依次验证协议是否真的跨材料成立；Author、Journal、Topic 只消费 MaterialReceipt，不理解材料内部实现。

## 2. 核心状态机

每一轮只允许执行一个业务 Operation：

```text
reconcile
  → exactly one next operation
  → operation receipt
  → reconcile
  → ...
  → complete | needs_input | blocked | failed
```

终态语义：

- `complete`：canonical 产物存在，且最后一次 audit 对当前目标返回 clean。
- `needs_input`：专业判断已收敛到一个真实用户决定，并携带闭合 `user_gate`。
- `blocked`：唯一安全的下一步需要外部事件、用户决定、资源恢复，或无法确认旧 writer 已停止。
- `failed`：当前输入与预算下已经没有合法恢复边。
- `partial` 不属于单份 Material；它只属于 Author、Journal、Topic 等 aggregator。

`retryable` 与 terminal status 正交。一个 `failed` receipt 可以建议用户在输入或环境变化后重新发起新的 Loop，但本次 Loop 已经终止。

## 3. 分层所有权

### Loop / Graph

- 选择 Operation key；
- 持有顺序、分支、budget、fan-out/join 与 repair backedge；
- 根据 typed receipt 决定下一条边；
- 生成 terminal MaterialReceipt。

### Operation

Operation 是跨 Handler 的合同：

```text
name
input_schema
output_schema
effect: control | readonly | writer
retry: safe | fenced | forbidden
artifact ownership
handler
```

### Handler

- Agent：需要模糊判断、阅读、分析或语义修复时使用。
- Bin：可以稳定重放和机器验证的确定执行。
- Composite：一个边界清楚的小型 Operation 可以组合 Bin 信号和 Agent 判断。

Handler 不拥有业务 Loop，不选择下一个 Operation，也不向用户提问。

### Skill

- 归一化用户输入与 canonical identity；
- 观察本地持久 artifacts；
- 持有人闸；
- 启动 Workflow；
- 执行 material 完成后的 optional derivatives。

Skill 只报告观察事实，不替 Loop 决定下一步。

## 4. MaterialRequest

```json
{
  "schema_version": "quasi.material-loop/0.1",
  "material": {
    "kind": "paper",
    "id": "canonical-slug",
    "identity": {
      "title": "Verified title",
      "authors": ["Verified author"],
      "year": 2024,
      "doi": "10.x/example",
      "journal": "Example Journal",
      "oa_url": null,
      "url": null,
      "confidence": "verified"
    }
  },
  "observed": {
    "canonical": null,
    "source": null,
    "recovery_source": null
  },
  "policy": {
    "max_ocr_recoveries": 1,
    "max_repairs": 1
  }
}
```

约束：

- v0.1 只接受 `material.kind == "paper"`。
- `material.id` 是 canonical slug。
- `observed` 只装调用方确定性观察到的 artifact reference，不装推测。
- caller 不能把两个 budget 提高到 `1` 以上。
- request/receipt 不得携带 cookie、token、header、service env 或完整 prompt。

Artifact reference 的最小字段：

```json
{
  "role": "source",
  "path": "sources/canonical-slug.pdf",
  "exists": true,
  "size_bytes": 12345,
  "mtime_ms": 1785300000000,
  "usable": true,
  "producer": "paper.download"
}
```

Paper 的 artifact ownership：

```text
source          → paper.download
recovery_source → paper.ocr
canonical       → paper.analyse
```

## 5. MaterialState

MaterialState 是本次运行内的控制状态，不是 event log：

```json
{
  "schema_version": "quasi.material-loop.state/0.1",
  "material_key": "paper:canonical-slug",
  "phase": "reconcile",
  "selected_input": null,
  "artifacts": [],
  "operations": [],
  "audit": null,
  "budgets": {
    "ocr": {"used": 0, "limit": 1},
    "repair": {"used": 0, "limit": 1}
  },
  "disposition": "created"
}
```

v0.1 不持久化 JS cursor、continuation ID、phase event 或 append-only journal。续跑重新观察持久 artifacts，然后从 `reconcile` 进入。

## 6. OperationReceipt

```json
{
  "key": "paper.analyse",
  "effect": "writer",
  "status": "succeeded",
  "attempt": 1,
  "artifact_roles": ["canonical"],
  "signal": null,
  "failure": null,
  "producer_key": null
}
```

枚举：

```text
effect = control | readonly | writer
status = succeeded | skipped | blocked | failed
```

控制分支只读取结构化 signal。自由文本 notes 只能进入 diagnostics，不能决定 OCR、repair 或 terminal status。

## 7. Paper Operation Map

```text
paper.identify  → control
paper.download  → download-agent       writer
paper.analyse   → analyse-agent type:B writer
paper.ocr       → quasi-extract relay  writer
paper.audit     → audit-agent          writer
paper.repair    → control
paper.terminal  → control
```

Graph 选择 `paper.analyse`；当前物理 Handler 仍复用共同的 `analyse-agent` 并由 Graph 注入 `type: B`。这允许以后替换 Prompt Pack 或 Handler，而不改变 Paper Loop。

## 8. Paper reconcile

Paper 的 reference flow：

```text
identify
  → reconcile
      ├─ no source/canonical     → paper.download
      ├─ usable source          → paper.analyse
      ├─ usable recovery source → paper.analyse(recovery source)
      └─ canonical exists       → paper.audit

paper.analyse
  ├─ success    → paper.audit
  ├─ needs_ocr  → paper.ocr → paper.analyse(overwrite)
  └─ error      → failed

paper.audit
  ├─ clean      → complete
  ├─ owned escalation → paper.repair → paper.audit
  └─ no legal repair  → failed
```

规则：

1. 已存在 canonical 也必须 audit；文件存在不是完成证明。
2. 有可用 recovery source 时直接分析它，不重新支付 OCR。
3. OCR 只认结构化 `needs_ocr: true`。
4. OCR 最多一次；OCR 后仍需要 OCR，终止为 `paper.ocr_insufficient`。
5. Worker success string 不能独自证明完成；最终由 audit 验证 canonical 目标。
6. Loop 必须有内部 step 上界，意外循环 fail closed。

## 9. Audit 与 repair

Audit clean 的必要条件：

```text
status == clean
remaining_violations == 0
escalated.length == 0
```

如果 audit 自己做了机械或局部修改并最终 clean，成功 disposition 是 `repaired`。

若 audit escalation：

1. escalation path 必须精确等于当前 Paper canonical path；
2. artifact owner 必须解析为 `paper.analyse`；
3. 消耗一次 semantic repair budget；
4. `paper.analyse(overwrite)` 收到完整 diagnostic reason；
5. 再 audit 一次；
6. 第二次仍 escalation，返回 `failed/paper.repair_exhausted`。

未知 path 或无法确定 producer 时返回 `failed/paper.repair_owner_unknown`，不能猜测 repair 节点。

## 10. Writer timeout

未知 writer outcome 不允许立即重投：

```json
{
  "status": "blocked",
  "failure": {
    "code": "paper.writer_outcome_unknown",
    "operation_key": "paper.analyse",
    "outcome": "unknown",
    "retryable": false
  },
  "resume": {
    "operation_key": "paper.reconcile"
  }
}
```

`retryable: false` 表示不能在同一次未知 outcome 后立刻启动第二个 writer；不表示该材料永远不能重跑。

v0.1 不实现 lease/fencing。只有具备 cancellation acknowledgement、进程退出证明或 generation fencing 后，未知 writer 才能安全自动重试。

## 11. MaterialReceipt

```json
{
  "schema_version": "quasi.material-loop.receipt/0.2",
  "material_key": "paper:canonical-slug",
  "kind": "paper",
  "id": "canonical-slug",
  "status": "complete",
  "disposition": "created",
  "stage": "audit",
  "artifacts": [],
  "operations": [],
  "audit": {},
  "freshness": {
    "observation": "observed_unchanged",
    "basis": "artifact-observation-and-audit"
  },
  "warnings": [],
  "failure": null,
  "user_gate": null,
  "resume": null
}
```

`user_gate` 是必备闭合字段。`complete|blocked|failed` 时它为 `null`；`needs_input`
时它是带固定 `schema_version`、`operation_key`、`kind` 与 `question` 的类型化对象，并携带
该决定所需的 exact candidates、conflicts 或 evidence。上层 Skill 只展示这个 gate，不从
Operation 日志或自由文本重新推断问题。

成功 disposition：

```text
created | resumed | reused | repaired
```

Acquisition failure 必须保留当前 `failure_reason` 与完整的 per-source `attempts[]`。这些是一次 acquisition operation 的业务证据，不是 event log；不得包含凭据。

## 12. Freshness 限制

v0.1 只记录：

```text
observed_unchanged | observed_stale | unknown
```

以及判定 basis。它不使用 `fresh`，因为尚未具备完整的：

```text
identity fingerprint
→ accepted source digest
→ OCR input/output + options fingerprint
→ analysis input/output + producer fingerprint
→ audit input/output + version
→ publication digest
```

因此 v0.1 不能可靠发现：

- 保持 size/mtime 的源文件替换；
- prompt/model/options 漂移；
- 未反映到 artifact observation 的依赖变化。

这些限制不妨碍验证 Loop 的控制语义。Talk 接入前必须补 generation/fingerprint，因为转写昂贵且输入媒体会变化。

## 13. 验证顺序

```text
Protocol v0.1
  → Paper：最小完整 Loop
  → Book：fan-out / join / refill / synthesis / repair routing
  → Talk：generation / paid operations / partial reuse
  → Web / Image / Note：identity / operations / artifacts / audit
  → Author / Journal：只消费 MaterialReceipt
  → Topic：产生需求、等待 receipts、更新研究状态、决定下一轮
```
