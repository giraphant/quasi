# quasi

> 仿佛读过、仿佛想过、仿佛写过。

一个学术阅读文库工具：用自然语言把论文、书、讲座、网页、档案原件收进本地文库，自动检索书目、取得全文、抽取正文、写出中文阅读笔记；也能把论文和书翻成双页对照的译本、为一位作者写学术画像，并围绕一个研究专题持续找材料、读材料、整理认识。

quasi 是一个 agent 技能（`skills/quasi`），加上一层确定性的 Python 能力。Codex、Claude Code、agy 等能读技能的 agent 都能用它。

## 用法

在文库目录里开一个 agent 会话，直接说要做什么：

- 「收一下这篇：DOI 10.1016/j.respol.2013.05.008」
- 「把 Cubitt 的 Finite Media 收进来」
- 「这个录像收成讲座：~/Downloads/talk.mp4」
- 「把这个专利存档：https://patents.google.com/patent/US174465A/en」
- 「把这篇翻成中文」
- 「收录 Sheila Jasanoff 的代表作，议题是 sociotechnical imaginaries」
- 「围绕山寨手机的制造体制继续研究两轮」

写作一律交给单独开的写手会话，可以换成中文写得最好的模型；批量材料各开一个会话并行处理。这些会话开在 Rex 终端里的 pane 中，过程看得见，也可以随时插话。

## 安装

照 [docs/SETUP.md](docs/SETUP.md) 做一次：装外部工具、配密钥、把技能链进文库、配好 agent 的权限，最后跑 `skills/quasi/scripts/quasi doctor` 自检。

## 文库布局

当前工作目录就是文库根目录：

```text
sources/      收下来的源文件
processing/   抽出的正文、OCR 结果、转写、译本等中间产物
vault/        阅读页：papers/ books/ talks/ webpages/ archives/ authors/ topics/
.quasi/       临时文件、派活用的提示词和回复、缓存
```

## 维护

维护说明见 [AGENTS.md](AGENTS.md)；这次重构的来龙去脉和逐轮实测记录见 [docs/REDESIGN.md](docs/REDESIGN.md)；OCR 和翻译管线的实测经验见 [docs/PDF_PIPELINE.md](docs/PDF_PIPELINE.md)；版本历史见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。
