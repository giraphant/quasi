---
name: quasi:wrap-up
description: >
  Use when the user says "收尾", "wrap up", "整理这篇", "我写完了帮我过一遍",
  or wants to finalise a draft — proofread typos/punctuation/spacing
  AND verify every citation against vault + online — in one shot.
  ALSO use when user says "审完了", "清理记录块", "删掉校对记录",
  "proofread cleanup", "proofread 收尾" — to remove the
  `<!-- proofread:start -->...<!-- proofread:end -->` block from drafts after review.
---

# Wrap-Up — 文章收尾

一篇 draft 写完后的统一收尾入口。`proofread-agent` 改文字 + `citation-agent` 校引用,产出一份带末尾"校对记录"块的 draft 和一份 citation 报告。审完后再触发清理。

## 调用方式

```
/quasi:wrap-up vault/drafts/draft.md
/quasi:wrap-up vault/drafts/                # 整目录
```

## 整体流程

```
┌─ Phase 1 PROOFREAD ─ 三阶段:
│   ├─ Stage A: sonnet 节内多轮 → 直接改正文 + 写记录
│   ├─ Stage B: codex 整篇 2 轮 → 只提议(`? c{N}` 前缀),不改正文
│   └─ Stage C: 主进程审稿 → 接受/拒绝 codex 提议,sanity-check sonnet 改动
├─ Phase 2 CITATION  ─ 解析引用 + 在线交叉验证 → report.html + .bib
├─ Phase 3 SUMMARY   ─ 单页汇总 summary.html,链接两份详细
└─ Phase 4 CLEANUP   ─ 等用户审完触发("审完了" / "清理记录块"等)
                       quasi-proofread cleanup 删 draft 末尾的记录块
```

## Phase 1 — PROOFREAD

按节切 → sonnet 节内多轮迭代到收敛 → codex 跨模型兜底。**改动直接累积在 draft 末尾的 `<!-- proofread:start -->...<!-- proofread:end -->` 块**。

**Stage A — sonnet 节串行 + 节内多轮迭代**:

1. `quasi-proofread split <draft> -o {pf_dir}/sections.json` — 按 H2/H3 切节
2. `quasi-proofread init <draft>` — 在 draft 末尾创建空记录块(已存在则跳过)
3. 对每节顺序处理(节间串行,避免并发改 draft 末尾块):
   ```
   for sec in sections:
     for r in 1..5:
       Agent("quasi:proofread-agent", prompt 给 draft/section_id/round_tag=s{r}/start_line/end_line)
       本轮 grep `^- \*\*s{r} ` count in draft 末尾块
       == 0 → 该节收敛,跳出
   ```

**Stage B — codex 提议(不改正文)**:

sonnet 全部收敛后,跑 codex 2 轮整篇 draft 作为**提议者**。实测 sonnet 多轮收敛后仍可能漏同音错字 / 双重否定(`发文→发问`、`等等等等→等等`),codex 训练偏置不同,常常一发命中。**但 codex prompt-following 弱,频繁越界改用词 / 全角化 `/-`**,所以 codex 这一阶段**只能提议,不能直接改正文**。提议追加到记录块,Stage C 主进程审稿决定接受/拒绝。

跨 draft 可并发(codex 实测同时跑 5 个互不冲突)。对每个 draft 顺序跑 `r = 1..2`。**必须**:
- 用绝对路径 `/opt/homebrew/bin/codex`(绕过 superset shim 的 notify hook 阻塞)
- 重定向 stdin `< /dev/null`(`codex exec` 即使收到 prompt 参数也会等 stdin EOF,不关闭会永远卡住)

```bash
/opt/homebrew/bin/codex exec --sandbox workspace-write --skip-git-repo-check "$(cat <<'EOF'
你是 draft 校对**提议者**。Read /path/to/draft.md,**不要修改正文**。

发现客观错(typo / punct-en-in-zh / punct-redundant / punct-pairing /
spacing-around-punct / spacing-multiple / grammar-clear)就**提议**。

不提议:用词替换、风格、引用元数据、markdown 结构、半角 /-[]@%、汉字-拉丁/数字间的单空格。

操作:**只 Edit 一处** —— 在 draft 末尾 <!-- proofread:end --> 标记之前追加提议行,
格式以 `? ` 开头标识"待审":

  - **? c{N} L{line}** `{old片段}` → `{new片段}` — {一句话 rationale}

**绝不**修改正文其他位置。完成后不要打印总结。
EOF
)" < /dev/null
```

**硬约束**:
- codex 是**提议者**,不动正文。Stage C 主进程审稿才决定 apply 与否
- 跨 draft 可并发(5 个 codex 同时跑 ok)
- 同一 draft 内 r1 / r2 串行(都 Edit 同一个 `<!-- proofread:end -->`,race 风险)

## Phase 1 续 — Stage C 主进程审稿

Stage A(sonnet 已改)+ Stage B(codex 已提议)都跑完后,主进程对每个 draft 进入审稿模式:

**输入**:draft 文件(含正文 + 末尾记录块,块内 sonnet 已 applied、codex 是 `? ` 待审)。

**对每条 `? c{N}` 提议**:

1. Read 提议行的 `{old片段}`,确认它**仍在正文中**(verify codex 没有违规改正文 —— 若 old 找不到,说明 codex 越界了,需要进一步排查)
2. Read 正文 L{line} 周围上下文
3. 判断:
   - 是否真的是客观错(typo / punct / spacing / grammar-clear)
   - 是否违反"不动"清单(用词、`/-`、CJK-Latin 空格、markdown 结构等)
4. **Accept**(judgement = 合法客观错):
   - Edit 正文:`{old片段}` → `{new片段}`
   - Edit 记录块:把该行的 `? ` 前缀删除(变正式记录)
5. **Reject**:
   - Edit 记录块:删除该行

**也顺手 review sonnet 改动**(`s{N}` 行,无 `?` 前缀):
- 觉得明显错的(应该非常罕见,sonnet 严守 prompt):Edit 正文反向 + Edit 记录块删行 / 标 reverted
- 觉得灰区可疑的:留着,在 review 总结里提

**输出**:审稿结束后给用户一句话总结(每篇 draft:sonnet N 处 / codex 接受 M 提议 / codex 拒绝 K 提议 / sonnet 反向 R 处)。

**硬约束**:
- 主进程**同时**持有正文 + 记录块,审稿是单 turn 内一次性完成(不要拆成多个 background)
- 6 篇 draft 串行审(每篇约 1-2k 行 + ~10-30 条提议 + 长 context),避免上下文混淆

## Phase 2 — CITATION

1. `quasi-citation parse <draft> -o {ct_dir}/parse.json`
2. `quasi-citation resolve {ct_dir}/parse.json -o {ct_dir}/manifest.json`
3. 把 manifest 里的 entries 按 8 条一批分组,每批并发 dispatch `quasi:citation-agent`(cap 4)
4. `quasi-citation render` → `report.html` + `references.bib`

**硬约束**:Phase 1 全部完成才进入 Phase 2;否则改字会让 parse 行号失效。

## Phase 3 — SUMMARY

主进程 grep 每个 draft 末尾块的 `^- \*\*` 行数(proofread 改动总数) + 读 citation manifest stats,渲染单页 `processing/wrap-up/{stem}/summary.html`,链接到 citation 报告。**proofread 不需要单独 HTML 报告** — 改动直接在 draft 里。

## Phase 4 — CLEANUP

校对记录块是临时审阅工具。审完作者用 git 接受/拒收改动后,触发清理:

- **触发词**:用户说 "审完了" / "清理记录块" / "删掉校对记录" / "cleanup" / "proofread 收尾"
- **执行**:`quasi-proofread cleanup <draft-or-dir>` — 从每个 markdown 文件删除整个 `<!-- proofread:start -->...<!-- proofread:end -->` 块,无块的文件跳过
- **执行后**(可选):`rm -rf processing/proofread/{stem}/` 清掉 split 产物

## 中间 / 终产物

```
processing/
├── proofread/{stem}/
│   └── sections.json              # split 产物(切节范围)— proofread 中间产物仅此一份
├── citation/{stem}/
│   ├── parse.json
│   ├── manifest.json
│   ├── agents/batch-NNN.json
│   ├── report.html                # ← 引用详细
│   └── references.bib             # ← BibTeX
└── wrap-up/{stem}/
    └── summary.html               # ← 一页汇总
```

**draft 文件本身**:Phase 1 in-place 修改正文 + 末尾累积 `<!-- proofread:start -->...<!-- proofread:end -->` 块,Phase 4 删整段记录块。**改动记录的 single source of truth = draft 末尾块**,无 sidecar / changelog 冗余。