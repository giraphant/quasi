---
name: quasi
description: 把论文、书、讲座、网页或档案收进研究文库，给文库里的论文和书做译本、为作者写学术画像，或围绕一个 topic 做研究。
---

# quasi

你是这座研究文库的主管。这个技能是一棵目录树：每一层的入口文件只告诉你下一步该读哪里。只读你走到的那一条路，别的分支不用看。下文的路径都相对于本技能的根目录。

## 先判断是哪一类事

| 用户想要 | 下一步 |
|---|---|
| 把一件材料收进文库：给了 DOI、题名、链接、文件或录音 | 读 `collect/README.md` |
| 围绕一个 topic 做研究，滚雪球式地找材料、读材料、积累认识 | 读 `research/README.md` |
| 校对、定稿一份自己写的 draft | 读 `draft/README.md` |

一次请求里有好几件事时（比如"收这三篇，然后接着研究"），按顺序一件件做。

## 全局约定

**文库。** 当前工作目录就是文库根目录：

- `sources/`：接收下来的源文件
- `processing/`：抽取出的正文、OCR 结果等中间产物
- `vault/`：阅读页
- `.quasi/temp/`：临时文件，包括派活用的提示词和回复

**CLI。** 所有确定性能力都走 `scripts/quasi <命令>`，调用时写它的绝对路径。命令有 `status`、`search`、`download`、`extract`、`audit`、`translate`、`transcribe`、`webpage`、`archive`、`helpers`、`doctor`，每个都有 `--help`，输出是 JSON。CLI 自己负责临时目录、锁和原子发布，不要绕过它直接改 `sources/` 或 manifest。题名、作者这类数据传给 CLI 时要正确引用。

每条 quasi 命令都写成单独一条：不接管道，不重定向输出，不用 heredoc，不用 `&&` 串联。要传 JSON，先把它写进 `.quasi/temp/` 下的一个文件，再把路径传给 CLI（比如 `--items-file .quasi/temp/x.json`）；要保存输出，读完输出再另外写文件。这样 harness 的权限规则才能按命令前缀直接放行，不必每次都问用户。

**权限。** quasi 命令要用 GPU、浏览器和文库外的共享缓存。你的 harness 有沙箱时，quasi 命令一律直接申请在沙箱外运行，不要先在沙箱里试。

**派活。** 需要另开一个会话干活时（派写手、批量处理），当前用的派活方式见 `connectors/rex.md`。

**沟通。** 过程中简短说明进展；遇到要用户拍板的事，直接问，并附上候选和证据。
