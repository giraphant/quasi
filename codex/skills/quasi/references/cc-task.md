# CC 材料任务

用下面的内容填充 Orca Task spec；不是新的机器 API。将占位项替换为实际值后再派发。
入口名来自 [CC 执行参考](cc-execution.md) 的 cc_routes；插件根应是 CC 本次实际加载的 Quasi 版本。

```text
Target: 在 <绝对资料库根目录> 完成 <一个材料或 draft 的明确目标>。
Research context: <本次问题、引出这份材料的线索，以及它可能补充什么；单件处理请求可省略>。
Entry: 调用 quasi:<collect-material 或 finalise-draft>，或读取本次已加载插件中的对应 skills/<入口>/SKILL.md。
Input: <exact URL / kind+slug / 本地文件 / 书目信息，用户指定的格式、语言、topics 等>。
Existing: <已知 canonical 路径；若为续跑，附原始 material result / gate 和用户新决定>。
Ownership: 只写该材料 Skill 拥有的文件及 <唯一 .quasi/temp/... 报告路径>；不写 Topic 三页、其他材料、插件代码或用户配置。
Constraints: cwd 和非空 CLAUDE_PROJECT_DIR 必须匹配资料库。确认实际 Quasi 版本和 Workflow 工具可用；若不匹配或不可用，报告阻碍，不仿造 Workflow。不扩大收录范围。
Execution: 自行完成 Skill 内部的 Workflow、fresh exact observation、needs_observation 续跑和审计；Codex 不承担逐阶段循环。
Questions: 需要决定时使用活跃 Orca preamble 的 ask 通道，携带原样 typed gate / 引用 review cards 及足够上下文。不要调用无人响应的本地 AskUserQuestion；不要替用户裁决引用或删除 cleanup 记录。答复后仍按 Skill fresh status / apply 规则继续。
Acceptance: 保存原样最终材料结果、最终 exact status 和实际产物路径；不能只凭文件已存在报告 complete。
Report: 将简短报告写入 <唯一绝对报告路径>，内容见下。按活跃 Orca preamble 提交 worker_done，完成后结束该回合。
```

报告只包含下一位消费者需要的信息：

- 首次使用该 worker 时确认实际 cwd、Quasi 插件根和版本、调用的 Skill；Topic 任务如需主代理写页，另提供当前生成的 Topic artifact-contract.json 路径（远程不共享文件系统时传回内容）；
- 材料：原样最终 `quasi.material.result/0.1`（包含 terminal、issue、gate/continuation），及该结果要求的最终 exact status；draft 则报告实际完成的 phase、pending review cards、决定文件和 bibliography 路径，不假造材料结果；
- 实际写入路径、原件收录范围、未取得内容，以及审计是否真正执行并通过；有研究问题时附几句相关内容、值得主代理阅读的位置和处理时发现的后续线索，不扩大本任务收录范围或另做一次完整综合；
- 若失败、等待决定或结果不明，明确阻碍和安全下一步，不伪称成功。

只有目标完成才发 `worker_done --outcome succeeded`。等待提问答复期间任务保持未结算；
若决定结束本次尝试且目标未完成，使用 failed 并说明是 gate/blocked/failed/unknown 中哪种情形。
Orca Task outcome 不能替代材料 terminal；不要创建第二套 receipt schema 或隐藏执行日志。
