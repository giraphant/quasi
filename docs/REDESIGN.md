# quasi 重构：技能组 + 外部会话派发

状态：设计草案（2026-11-01），分支 `redesign/skill-group`。原型跑通前，旧的 Workflow 体系原样保留，两套并存。

## 为什么重构

1. **写作质量。** 2026-11-01 做过一次对照实验：同一模型、同一批 Turner《Charged》章节笔记，只换提示词。现行 `agents/synthesis-agent.md` 里写作方法只占约 21%，其余是 receipt、入口核验、宿主补丁，再加上约 6KB 的 artifact_contract JSON Schema。用它写出的概览正文有 112 处 `chNN` 引注，读起来像合规回执。换成一份 2KB、只讲读者和写法的提示词后，引注降为 0，可读性明显更好。模型会照着提示词的语域写作，提示词写得像协议，产物就像回执。
2. **模型选择。** Claude 和 Codex 的模型都偏向编码，中文写作不如 AGY。写作任务必须能派给最会写的模型，而 Workflow 只能派 Claude Code 自己的子代理。
3. **Workflow 的代价大于收益。** receipt 验的是汇报，不是产物，大部分拒绝都卡在簿记字段上，反复报错、反复要人介入；真正的不实汇报（0.58.2）反而要靠查磁盘才发现。Workflow 还带来生成产物、auto 模式的 schema 长度上限、沙箱缺 `URL`/`fetch`，并且只能在 Claude Code 里跑。
4. **旧架构是成功的。** 0.4 到 0.42 的做法是"技能主进程派 agent、看磁盘续跑、audit 后返修一次"，这就是我们要回去的形状。Workflow 时代的收获（schema 更准、并行更快、能力更多）都在能力层和 `scripts/schemas` 里，与 Workflow 无关，全部保留。

## 四个 harness 共享什么

本机核对过的版本：claude 2.1.316、codex 0.166.0、pi 1.4.0、agy 1.4.12。

| 共享 | 不共享 |
|---|---|
| SKILL.md（Agent Skills 规范） | 子代理定义（Pi 没有，Codex 能力弱） |
| AGENTS.md | 插件格式（骨架相近，清单各异） |
| shell 和无头 CLI（`claude -p` / `codex exec` / `pi -p` / `agy -p`） | hook（事件名和格式各异） |
| MCP | Workflow（只有 Claude） |

由此得出四条决定：

- 模型要读的东西全部写成技能。
- 不用原生子代理，工人跑在外部终端会话里。
- 正确性不依赖 hook。
- 不做 MCP。

## 分层：一个技能，内部用目录逐层路由

整个 quasi 只装一个技能。内部是一棵目录树：每个目录有一个入口文件，只做两件事，一是告诉模型下一步读哪里，二是写下对下面所有分支都成立的规则。模型每一跳只读一个小文件，上下文里只有它走过的那条路径。

```
skills/quasi/
  SKILL.md                 根：判断是收录、研究还是定稿；全局约定（文库位置、CLI、派活方式）
  collect/
    README.md              判断材料类型；收录共用的规则（写作派写手、验收四条、audit 处理）
    paper/
      README.md            论文流程
      search.md            论文怎么找、怎么判断找对了
      acquire.md           怎么下载、怎么接收源文件
      prepare.md           怎么抽取正文、什么时候 OCR
      writing.md           写作说明，原样交给写手
    book/ talk/ webpage/ archive/ translation/ author/   之后逐个迁入
  research/README.md       研究循环
  draft/README.md          定稿校对
  connectors/rex.md        派活方式；换框架就加一页，改根目录里的一行
  scripts/quasi            唯一的 CLI 入口
```

**为什么只装一个技能。** 并列的技能，每个都会在每个会话的系统提示里常驻一行描述，由 harness 拿描述去匹配用户请求。quasi 的入口实际上只有一个，材料之间的判断（这个链接是论文还是网页）往往要先查一下才能定，交给主管读路由表比交给描述匹配更可控。运行时也必须在同一个文件夹里，复制安装和 Codex 丢软链接都要求技能自包含。Matt Pocock 的技能组之所以并列，是因为他的技能彼此独立。

**为什么按材料竖着拆。** Workflow 时代是按操作横切的：一个 download-agent 同时管论文和书的下载，一个 analyse-agent 同时写 paper、chapter、talk、webpage。结果每个工人都背着所有材料的变体。竖着拆以后，每种材料在自己的目录里写自己的子流程：论文的 `acquire.md` 讲 DOI 级联，书的 `acquire.md` 讲 ISBN、版本和年份判定；书还可以有论文没有的切章、章节写作、全书综合。各材料之间会有少量重复，这是可以接受的；共用的机械操作在 CLI 里，共用的规则在 `collect/README.md`。

**几条约定：**

- 规则放在它适用的最高那一层，往下继承。
- 深度控制在三层：根、需求、材料。
- 叶子开头写明上游："如果你是被直接派到这里的，先读上面两层"。批量工人直接拿叶子路径开工，不走路由。
- 写手只拿到 `writing.md` 和输入文件，从不进这棵树。
- 整棵树在同一个技能文件夹里，所以跨分支引用没有问题（比如 author 写"每篇论文按 `collect/paper/` 做"）。

**谁来执行。** 单件材料由主会话按叶子流程直接跑，需要用户做决定时就在对话里问；批量时每件材料开一个工人会话，从头跑到尾。写作这一步总是派给写手会话。

下载、抽取、OCR、翻译的专业方法（provider 选择、OCR 判断、翻译恢复等），从现有 `agents/*.md` 迁进对应材料目录的说明文件，协议部分丢掉。

## 派活：connectors/

quasi 派活只需要五个动作。connector 负责把它们映射到当前用的终端框架：

| 动作 | 含义 | Rex 映射（v1） |
|---|---|---|
| 开工 | 在指定目录开一个新会话，用指定 harness 跑一段提示词，返回 id | `rex run -s "$REX_SESSION" -c DIR --label L --keep-open --focus=false --json -- agy -p ...` |
| 等待 | 等会话结束，或到时限返回 | `rex wait -s "$REX_SESSION" BLOCK --for 9m --json` |
| 读结果 | 读它最后的输出 | `rex capture -s "$REX_SESSION" -b BLOCK --trim` |
| 追加 | 给还开着的会话补一句话 | `rex send` 加 `rex send-key enter`（v2，交互式工人用） |
| 收工 | 关掉 | `rex block close -s "$REX_SESSION" BLOCK` |

connector 还记录哪类活派给哪个 harness，默认写作派 `agy`、操作派 `codex` 或 `claude`。这只是用户偏好，随时可改。

**v1 用无头模式**：工人在 Rex 的一个 tab 里跑 `agy -p` / `codex exec` / `claude -p`，进程退出就算结束，`--keep-open` 让用户事后能看输出。交互式工人（用户可以插话，返修时用"追加"在同一上下文里接着改）放到 v2；它需要 harness 上报运行状态，Claude 通过 Rex hook 有这个能力，Pi 没有。

**换框架只加一页。** 在 `connectors/` 下写新框架的映射，再把根目录 `SKILL.md` 里指向 `connectors/rex.md` 的那一行改掉。其他文件只写"按派活方式开工、等待、读结果"，不出现任何 Rex 命令。

### 派给工人的消息

写手的消息只写几件事：读哪份写作说明、输入文件、书目信息、交付方式。

```text
请读写作说明：/abs/vault/.agents/skills/quasi/collect/paper/writing.md
然后通读这篇论文的全文：/abs/vault/processing/papers/smith-2020/source.txt
书目信息：……
按写作说明写出论文笔记，把笔记全文作为你的最终回复：从 frontmatter 的第一行 --- 开始，到最后一节结束，前后不要加任何别的文字。只读取上面列出的文件。
```

写手不写文件，只需要读权限；编排者检查回复后存到输出路径。消息里不加 JSON 信封，不要求回执格式，也不要求回显输入输出。

## 验收与规则

只验产物，不验汇报：文件在不在由 `quasi status` 判断，合不合格由 `quasi audit` 判断。工人的最后回复只用来知道有什么需要用户决定，或者为什么做不下去。

现在 CLAUDE.md 里的一大段运行时合同，换成四条规则：

1. 同一个输出路径，同一时间只派一个工人。
2. 工人结束后看磁盘、跑 audit，不信汇报。
3. 返修时，把原技能、audit 诊断和现有文件一起交给工人，保留用户自己写的内容。
4. 工人崩了或结果不明，先看磁盘再决定，不盲目重派。

OCR、翻译、抽取的事务、锁和隔离目录都在 CLI 里，原样保留。

## 长任务

- **分段推进**：OCR 每次调用只推进一个 profile 的页段（MinerU 16 页），然后返回，编排者看进度再调下一次。这是现成的，任何 harness 的工具调用都会超时，所以这个设计要保留。
- **在 Rex tab 里跑**：翻译、转写这种动辄半小时的任务，用 connector 的"开工"在一个 tab 里跑 `scripts/quasi translate ...`，再用"等待"分段等。状态照旧由 `quasi status` 观察。所以 `quasi wait` 暂时不需要。

## CLI 入口

`skills/quasi/scripts/quasi <命令> [参数]` 自己定位（realpath），转发到对应的 `bin/quasi-<命令>`。现有 shim 已经会自定位、在 `~/.cache/quasi` 下建 venv、通过 Keychain helper 读密钥，所以 PreToolUse hook 不再需要。

编排者知道自己的技能目录，派活时把 CLI 的绝对路径写进消息。人想在终端里直接用，就把它 `ln -s` 到 `~/.local/bin`。

后续：skills CLI 是按单个技能文件夹复制安装的，所以 Python 核心最终要搬进 `skills/quasi/scripts/`。原型阶段先通过 realpath 回到仓库根目录调用。

## 写作说明怎么写

- 照 `quasi-synthesiser` 的样子写：读者是谁、语言风格如何、结构用人话说清楚。
- 结构那一节可以由 `scripts/schemas` 生成，但要生成人话，不是 JSON Schema；维护者备注不进模型能看到的文字。
- `scripts/schemas` 仍是 audit 的唯一结构标准。
- 写作说明放在材料目录里（如 `collect/paper/writing.md`），派活时把它的绝对路径交给写手。
- 起草交给中文写得最好的模型（目前是 AGY 的 Gemini 4 Argon），由用户审定。

## 和 Marple 的关系

- 合同就是 vault 本身：quasi 写入 `.quasi/schema.json`，Marple 读取。这一点不变。
- Marple 的 Reader AI 提示词目前点名的是 `quasi:analyse-agent` 等内部名字（其中 `quasi:process-book` 已经不存在）。等新技能名定下来，改成点名 quasi 技能。
- 两个仓库不合并，quasi 的执行能力也不进 Marple。

## 留什么，删什么

**保留**：
- `scripts/` 里的全部 Python 能力、事务与锁；
- `scripts/schemas`（继续导出 `.quasi/schema.json`）；
- `quasi-status`、`quasi-audit`；
- 测试中针对能力层的部分。

**原型跑通后删除**（2026-11-02 已删，见下方「仓库清理」）：
- `workflows/*.mjs`、`scripts/workflows/`；
- request/receipt schema、descriptor rows；
- `agents/*.md`（方法迁进 references 之后）；
- `hooks/` 里的 inject-userconfig；
- `skills/collect-material`、`skills/research-topic`、`skills/finalise-draft`；
- `codex/skills/quasi`、`deprecated/`；
- 守护 Workflow parity 的测试。

此外，`userConfig` 改为配置文件加 Keychain，`CLAUDE.md` 删掉，只保留重写后的 `AGENTS.md`（Claude Code 在没有 CLAUDE.md 时会读 AGENTS.md）。

## 第一步：Paper 原型

范围：

- `skills/quasi/SKILL.md`、`collect/README.md`
- `skills/quasi/collect/paper/`：`README.md`、`search.md`、`acquire.md`、`prepare.md`、`writing.md`
- `skills/quasi/connectors/rex.md`
- `skills/quasi/scripts/quasi`（转发到 `bin/quasi-*`）

旧 Workflow 和旧技能一概不碰。

验收：

1. 在 claude、codex、pi、agy 里各起一次，确认模型能拿到技能目录，并用绝对路径跑通 `scripts/quasi status --scan --json`。
2. 在一个临时 vault 里处理一篇真论文：查找、下载、抽取、分析、audit，全程经 connector 派工，最终 audit clean。
3. 同一篇论文，与现行 Workflow 的产物做盲比。

之后的顺序：Book（章节并行派工）→ Talk → Webpage / Archive → Translation → Author → Topic → Draft，最后统一删除旧体系。

## 未决

- 交互式工人与"追加"返修（v2）。
- Python 核心何时搬进技能目录。
- 配置项迁移的具体格式。
- 工人的权限配置：已定为装机时照 `docs/SETUP.md` 一次配好，agent 不负责部署（第七轮）。Claude Code 和 agy 两节还没实测。

## 实测记录

**2026-11-01，Paper 原型第一轮**，临时 vault `/tmp/quasi-redesign/vault`，技能用项目级软链接接入：

- **技能发现**：
  - agy 能发现技能，并直接给出技能目录；
  - codex 能发现技能并给出路径，但临时 vault 需要加 `--skip-git-repo-check`；另外 `~/.codex/skills/quasi`（0.67.0 的旧独立技能）和新的入口技能撞名；
  - claude 能发现技能，但技能列表里不带路径，加载技能时才给出 base directory；
  - pi 没有配置模型 API key，没测成。
- **全流程**（McLennan 2004，Thesis Eleven）：身份、查重、下载（doi_cascade 一次成功）、接收、抽取（12 页文本层可读，不需要 OCR）都直接用 `scripts/quasi` 跑通。AGY（gemini-4-argon-high）写手无头运行，回复直接就是完整页面。audit 自动修好 2 处 frontmatter，另有 2 处软警告（理论框架里夹了列表，核心引用的书目和说明拆成了两行），已据此收紧 `writing.md`。
- **用户评价**：新版（AGY）质量明显好于旧 Workflow 产物。

**2026-11-01，目录路由第二轮**：三个技能合并成一个 `quasi`，内部改为目录逐层路由。agy 和 codex 各起一个只读会话，只给一句"帮我把这篇论文收进文库：DOI 10.1177/0306312717709363"。两者都按 `SKILL.md` → `collect/README.md` → `collect/paper/README.md` → `search.md` 的顺序读了 4 个文件，在能开始干活的地方停下，没有读任何别的分支，并且各自用技能目录的绝对路径写对了前两步的 CLI 命令。

**2026-11-01，pane 派活第三轮**：工人改为在编排者旁边开 pane（`rex split`），右侧排成一列。

- 无头写手 pane：开出来后焦点留在编排者这边，结果存进文件。
- 交互式材料会话（`agy --mode accept-edits -i`）：按要求写出状态文件。追加消息用 `rex send` 加 `send-key enter`，它接着干活并改写了状态文件。
- agy 会向 Rex 上报程序状态：`working`、`done`（一轮结束），以及 `blocked`/`permission`（在等批准）。
- 新文件夹第一次以交互模式进入时，agy 要求用户确认信任一次。

**2026-11-02，Book 全流程第四轮**（Turner《Charged》）：

- 身份确认、查重后，Anna's Archive 找到两个 EPUB 候选；取 12.9MB 的那个，版权年与身份一致，接收。
- EPUB 抽出 10 章，其中第 10 项是丛书书目；读过正文确认后，用 `--exclude-title` 加清单指纹排除，剩 9 章。
- 章节写手分两批并行：
  - 第一批 5 章用 agy 无头模式，pane 里看不到过程。用户指出这一点后，写手改为在 pane 里跑交互式会话，把整页写进回复文件，再写状态文件。
  - 第二批 4 章用交互式 codex，4 分钟内全部完成。
- 9 章全部一次通过 audit，每章 1–2 处自动修正。全书概览用 codex 写，整本书的 audit 也通过。
- 发现的问题：Rex 会在每个 agent 启动时提示它给会话起名，Codex 写手照做，想执行 `rex session rename`，而工人继承的是编排者的会话。已拒绝这次请求，并在 connector 里要求每条派活消息都写明不要重命名。
- 用户要求：之后的测试一律用 codex（启动时带 `--no-daemon`），以节省 agy 额度；connector 里用一行写明当前使用的 harness。

**2026-11-02，材料会话第五轮**：在 pane 里开交互式 codex 材料会话，只告诉它"用 quasi 技能，从 `collect/paper/README.md` 开始，收录这个 DOI"。

- **Sovacool & Hess 2017**：6 分 24 秒完成。它自己走完查找、查重、下载、抽取，按 connector 另开写手 pane，写完后存页、跑 audit（clean），关掉写手 pane，写状态文件。全程没有卡在权限确认上。
- **发现的问题**：编排者的 Rex 会话被改名为 `quasi-paper-sovacool`。工人继承了 `REX_SESSION`，Rex 的启动钩子要求 agent 在加载技能之前先给会话命名，派活消息末尾那句"不要重命名"压不住。对照实验：去掉 `REX_SESSION`/`REX_BLOCK` 启动的 codex 收不到命名提示，带着这两个变量启动的会收到。
- **修法**：所有工人都经包装启动，先把两个变量另存为 `QUASI_REX_*` 再清掉；编排者统一用 `RS`/`RB`；派活消息第一句声明工人身份；收工时核对会话名。
- **Stilgoe 等 2013**：按新包装重跑，5 分 32 秒完成，会话名全程没有变化。写手消息第一句按新规矩写；页面 audit clean。
- **小问题**：上一轮核对时生成的 `.inspect.txt` 留在了临时目录里，已在 `acquire.md` 补上"自己生成的临时文件也要删"。

**2026-11-02，第六轮：书的材料会话 + OCR + 返修**（两个 codex 材料会话并行）：

- **Cubitt《Finite Media》**（只给"Sean Cubitt, Finite Media"）：20 分钟完成。它找到 EPUB 并接收，切出 7 项，排除了封面、版权页、致谢、索引等 10 项，并行派了 7 个章节写手，再派概览写手。整本书 8 页 audit clean，写手 pane 全部关掉，会话名没变。
- **Bourdieu 1985**（只告诉它 `sources/` 里已有 PDF）：11 分半完成，其中包括两次等批准。它从 Crossref 定下是 SSI 24(2) 版，确认文本层只有下载水印，分两段 OCR（16 + 10 页），generation 已提交。读结果时发现末条参考文献漏了半行，对照原页补进交给写手的阅读文本，没有改 `ocr-generations/` 里的文件。页面 audit clean。
- **返修回路**：编排者删掉页面的「核心引用」、把「理论框架」第一段改成列表，并加了一节「我的笔记」，然后用 `rex send` 告诉材料会话"用户改过这一页，重新验收"。它按规则另派写手，消息里带上写作说明、正文、现有页面和 audit 诊断原文，并说明 unknown_h2 只是提示，不得删用户笔记。结果：「核心引用」按原文重写，列表改回段落（保留了用户的缩写，没有恢复原文），其余各节逐字未动，「我的笔记」逐字保留，audit clean。整个返修 2 分半。
- **权限**：MinerU 和 `quasi download book candidates` 都要写 `~/.cache/uv`，codex 沙箱挡住了，需要用户批准。见"未决"。
- **问题**：书的流程会给单独成节的参考文献（以及上一轮 Turner 的注释）也写一份章节笔记，没有阅读价值。用户定下：单独成节的参考文献、索引、尾注都不进章节清单，已写进 `collect/book/prepare.md`。
- **编排者自己的坑**：监视脚本放在 zsh 里跑，`for l in $LABELS` 不分词，结果什么都没监视到。之后的循环要么把标签直接写在循环里，要么显式用 bash。

**2026-11-02，第七轮：权限**：

- Codex 读文库里的项目配置。`.codex/config.toml` 的 `writable_roots` 和 `network_access` 实测生效：同一条写 `~/.cache/uv` 的命令，有这份配置就能写，没有就报 `Operation not permitted`。
- 光加可写目录不够：MinerU 在 Codex 沙箱里报 `No Metal device available`，Anna 的浏览器回退也起不来。所以 quasi 命令必须在沙箱外跑。`.codex/rules/` 里的前缀规则会自动批准这类提权申请，交互会话实测不再弹确认；`codex exec` 固定 `approval: never`，用不了提权。
- 试过让 agent 首次进文件夹时自己部署权限：工人跳过了这一步；主会话照做了，但写配置要用户确认一次，而且它自己这个会话读不到新配置，之后的 quasi 命令照样弹确认。用户的判断是太重，文库不常换，改成装机时照 `docs/SETUP.md` 一次配好。技能里只留一句"quasi 命令直接申请在沙箱外运行"。
- 编排者的坑：我在自己 shell 里直接跑的 `codex exec` 探测没清 `REX_SESSION`，把会话改名成了 `quasi-permission-probe`。connector 已补上：无头模式同样要先用 `env -u` 清掉这两个变量。

**2026-11-02，第八轮：讲座、网页、档案**（三个 codex 材料会话并行，在配好权限的测试文库里）：

- **网页**（Paul Graham, How to Do Great Work）：7 分钟完成。写手只写 frontmatter 和摘要，编排者把 `source.md` 接在 `## Content` 下；核对过正文与 `source.md` 逐词一致（11826 词）。原页只写「July 2023」，`published` 按规则留空。audit clean。
- **讲座**（Foucault–Chomsky 辩论片段，6 分 51 秒视频）：8 分钟完成。它自己把录像收进 `sources/`，压缩出播放版，三引擎转写，派写手。它查出了日期 1971-10-22、场合（NOS International Philosophers' Project，埃因霍温），分节的「时间：」行和时间脉络的格式都对。audit clean。
- **档案**（Bell 1876 年电话专利，Google Patents）：7 分半完成。kind 判为 `patent`；日期取公开日，并说明申请日不同；只挑了扫描 PDF 和页面快照两件原件，没有抓相关专利；正文逐页讲附图和权利要求。audit clean。
- **问题**：quasi 命令带了 heredoc（`--items-file - <<'JSON'`）或重定向（`> 文件`），Codex 的前缀规则就匹配不上，照样弹确认。根 `SKILL.md` 已改为：quasi 命令写成单独一条，JSON 先写进 `.quasi/temp/` 再传路径，输出读完再另外写文件。各叶子的查重步骤已同步。

**2026-11-02，第九轮：搬到 Mac Mini，测译本和作者**：

- 开发挪到 Mac Mini（`~/Vibe/quasi`，测试文库 `~/Vibe/quasi-testvault`）。代码用 git bundle 经 Rex 传过去，不往 GitHub 推。Mini 的 `~/.zshenv` 设了 `QUASI_WORKER_PERMISSIONS=full`，connector 据此用跳过权限的命令启动工人。两条测试都由我在 Mini 上开主会话，像用户一样只说一句话。
- **论文接译本**（Stilgoe 2013）：18 分半。论文收录、写手、audit 都通过；翻译时它让写手和翻译并行跑。译本卡在 CLI 的覆盖率门槛：中位数 0.290，低于 0.30，草稿留在暂存目录，没有发布。正文 10 页的比值都在 0.28–0.29，没有接近 0 的页，参考文献也已排除，更像门槛偏紧，而不是漏译。另一个问题：Elsevier 原生电子版 PDF 因为页面上有图片对象，被判为要先做版面重建，整篇走了一遍 MinerU。这两点属于 CLI 的翻译管线，待议。
- **作者**（Sheila Jasanoff，限 1 本书、2 篇论文）：47 分 50 秒。作者页、全书概览、15 个章节页、2 篇论文页，共 19 页 audit 全部 clean，作者页里的作品链接检查通过。
- **问题一：限流。** 3 个材料会话加书的 5 个章节写手同时跑，十来个 Codex 触发 429，两个写手一直重试。connector 已加总量上限：开工前数一下 Rex 会话里的 pane，连同用户的主会话不超过 7 个；遇到 429 就少开几个、过一会儿再派。
- **问题二：原生子代理。** 主会话为了补限流卡住的两章，改用 Codex 的 `spawn_agent`，补完后连后面的三章也继续用它。connector 已明文禁止用 harness 自带的子代理代替 pane 工人。

- **research 暂行版**（2026-11-02）：用户定下搜索由主会话自己做（它最清楚研究进度），只有写作派写手。`research/README.md` 写成一个循环（读地图、本地召回、搜索、收录、读笔记、更新地图、写页、默认两轮后汇报），`research/writing.md` 分综述、专章、资源页三节。研究地图（`02-outline`）由主会话维护，也是续跑的依据。还没实测；topic schema 不认 `dossier` 类型，也不认 outline 子问题里的 `dossier`、`page` 字段，但用户的真实文库里已经在用，之后要补进 schema。

**2026-11-02，仓库清理**：七种材料都跑通后，按用户要求清理仓库。删掉 Workflow 产物和 TypeScript 源码、agents、旧技能（collect-material、research-topic、finalise-draft；draft 以后从历史重做）、旧 Codex 技能、插件钩子注册、子代理状态栏、输出风格、旧的计划和 spec，以及测 Workflow、宿主编排和旧技能路由的测试，共约 4.9 万行。`scripts/hooks/inject-userconfig.py` 保留，因为 Keychain 读密钥还要经过它；`.claude-plugin/` 暂留，作为配置项的记录，等配置迁出后再删。`AGENTS.md` 按新结构重写，`CLAUDE.md` 只剩一行 `@AGENTS.md`；`README.md` 重写；`docs/ARCHITECTURE.md` 删除，有用的部分并进了 `AGENTS.md`。新加 `tests/test_skill_tree.py`，检查技能页提到的页面路径和 quasi 子命令都存在。剩下的测试全部通过（1000 个）。

**2026-11-03，第十轮：PDF 书和扫描书**（Mac Mini，两个主会话放在同一个 Rex 会话里，共用 7 个 pane 的上限；材料取自用户文库的副本，放在文库外的 `~/Vibe/quasi-inbox/`，像用户给文件那样只说一句「收这本书：路径」）：

- **Gitelman《Always Already New》**（222 页，有文本层，没有 EPUB）：14 分 39 秒。PDF 自带的目录不可用，它读目录页自己写了切分方案，切成 7 项（序言、导论、四章、尾声）；注释、参考文献、索引按新规则没有进清单。5 个写手并行，概览加 7 章 audit clean。
- **Hutchby《Media Talk》**（198 页扫描本，没有文本层）：2 小时 37 分，绝大部分花在 OCR 上。Mini 是 M1、16 GB，MinerU 每页 35–40 秒，内存吃满。OCR 在单独的 pane 里用 shell 循环一段段推进（16 页一段，`partial` 就接着跑），generation 提交后用 OCR 版 PDF 切章，得到 12 项，写了 13 页，audit clean。术语表也成了一章：这本书的术语表是会话分析的概念说明，笔记写得有内容，所以没有把术语表加进排除规则（是否排除本来就要看正文）。
- **问题**：两个会话都对用户给的 PDF 用了 `quasi download accept`，它会把输入文件移走，用户原来的文件夹空了。`collect/README.md` 已补规则：用户给的文件复制进 `sources/`，不移动不删除；`accept` 只用于 `.quasi/temp/` 里的临时下载。

**2026-11-03，仓库根目录即技能**：原来技能在 `skills/quasi/`，靠软链接挂进文库，`scripts/quasi` 再往上找回仓库里的 `bin/` 和 `scripts/`；单独拷走技能文件夹就用不了。用户定下整个仓库就是技能：`SKILL.md`、`collect/`、`research/`、`draft/`、`connectors/` 搬到根目录，`scripts/quasi` 是唯一入口，原来的 11 个 bin shim 移进 `scripts/commands/`，行为不变，只改了定位仓库根的那一行。Python 层本来就在根目录的 `scripts/` 下、按 `scripts.xxx` 导入，所以一行导入都不用改。安装变成把仓库克隆到 `~/.agents/skills/quasi`，`git pull` 就是更新。`draft/` 暂时只说"暂不支持"。全量测试 1000 个通过。

**2026-11-03，不再是插件**：仓库链进 `~/.claude/skills/quasi` 之后，Claude Code 因为根目录有 `.claude-plugin/plugin.json`，把它当成名叫 `quasi` 的插件（`quasi@skills-dir`），和已安装的旧插件 `quasi@ramu` 撞名，拒绝加载。删掉 `.claude-plugin/` 后，它作为普通技能正常加载（无头 Claude 实测能看到 `quasi`）。`scripts/core/core.py` 定位仓库根改为找 `SKILL.md` 加 `scripts/quasi`；`quasi doctor` 里比较插件缓存版本的检查一并删掉。配置项清单和用途移进 `docs/SETUP.md`。密钥仍存在旧插件名下的 Keychain 记录里，所以旧插件只禁用、不卸载。旧的 `~/.codex/skills/quasi` 已在本机和 Mini 上删除。

**2026-11-03，配置迁进 quasi 自己的钥匙串条目**：原来 13 个键存在 Claude Code 的 `Claude Code-credentials` 记录里，挂在旧插件 `quasi@…` 名下，靠插件时代的钩子脚本读取，所以旧插件不能卸载。用户考虑过让 Marple 做配置界面，定下全部放钥匙串、统一编辑：每个键一条 generic password（服务名 `quasi`，账户名是键名），`scripts/config/config.py` 是唯一的读写方，`quasi config show [--json]`、`set`、`unset` 同时给人和 Marple 用。Marple 不直接碰钥匙串：钥匙串条目记得创建它的程序，由 Marple 建的条目，`/usr/bin/security` 每次读都会弹授权框，Marple 重签名后还可能要重新允许；全部经 `security` 写入，读取就不弹框。实测：`security -i` 从标准输入读命令，双引号里只认反斜杠转义的反斜杠和双引号，`$`、反引号、单引号原样保存，所以密钥写入不进 argv；读一个键约 15 毫秒，13 个键并行读。值限定为可打印 ASCII，因为 `security -w` 会把其他内容打成十六进制，和十六进制 token 分不清。密钥值不许写在命令行，只能粘贴或走标准输入；非密钥的键可以直接写值。`scripts/hooks/` 和 `load-keychain-env.sh` 删除，shim 改为加载 `load-config-env.sh`。本机和 Mini 各自用一次性脚本从旧记录迁移（Mini 的旧记录挂在 `quasi@ramu-toolkit` 名下），迁移后逐键比对一致，并实际跑了一次 Kagi 检索。`QUASI_WORKER_PERMISSIONS` 仍是登录 shell 的环境变量，因为 connector 要 agent 直接读它。

**2026-11-03，写手和材料会话分别选择框架**：钥匙串配置新增「派工」分组，`writer_harness` 和 `session_harness` 都可选 codex、agy、claude，未设时默认 codex。`quasi config get` 给 agent 读非密钥的值，依次取环境变量、钥匙串、默认值；密钥直接拒绝。`show` 给 Marple 单独报告默认值，不把未设说成已设。connector 派两类工人时分别读取，材料会话再派写手也重新读取。假 security 的配置测试和技能树测试共 26 个通过。

**2026-11-03，测试清理**：先沿技能页实际调用的 quasi 命令、shim 和 Python 调用方摸底，逐个归类 48 个测试文件，完整清单见 [TEST_CLEANUP.md](TEST_CLEANUP.md)。没有按 receipt、manifest、legacy 这些名字直接删。

- **能力行为**：保留 `test_archive*`、`test_audit*`、`test_download_cli`、`test_extract*`、`test_ocr_mineru`、`test_layout_review`、`test_translate*`、`test_translation_recovery`、`test_tounicode`、`test_transcribe*`、`test_compress_media`、`test_webpage_cli`、`test_status_cli`、`test_vault_resolve`、检索主流程/合并/九个 adapter，以及配置、core、doctor、bootstrap、技能树、typecheck 等实际行为。章节、OCR、转写和翻译 manifest 仍供状态观察、原子发布和失败恢复读取，不属于可删除的宿主回执。Marple 的 schema snapshot、中文版本 sidecar 和 Archive manifest 0.2 原样保留。
- **接口形式**：删 `test_search_schemas.py` 中复写 dataclass 默认值和完整字段集合的 6 项测试；删 audit、download、doctor、proofread、search、status 中只断言旧入口不存在的测试，以及 schema registry 中的旧网页派工目录测试。混合文件去掉固定回执版本/字段集合的断言，保留实际行为。代码删除无生产调用方的 `schemas/contracts.py` 生成者 JSON 投影；`OPERATION_CATALOG` 保留产物路径，去掉 agent/phase/effect/kinds 和无产物的操作；Talk 输出去掉旧宿主标记，翻译输出去掉无人读取的 key/effect。持久化 manifest 和翻译未决任务恢复所读的 receipt 字段不动。
- **死功能**：`test_block_list_yaml.py` 中两项 sweep 测试与旧 `audit/backfill.py`、`audit/sweep/` 一起删。两个翻译 provider 的独立 `translate_slug` 发布器、main/parser、旧来源/输出路径辅助函数和仅供它们使用的调参分支也删，当前 shim 从来不调用它们。`test_pdf2zh_translate.py` 的死入口测试删除，`test_translate_coverage.py` 的旧 AST 顺序检查迁到统一事务；两后端页数门槛和先修 ToUnicode 再测覆盖率都在活路径上做运行时验证。
- **验证**：按要求新建 `/tmp/quasi-test-venv`，安装 `scripts/requirements.txt` 加 pytest（Python 3.15.0、PyMuPDF 1.28.2、pytest 9.2.0），前后都运行 `/tmp/quasi-test-venv/bin/python -m pytest tests -q`。清理前 1019 项，956 通过、63 失败，原因是新版 PyMuPDF 的 `import fitz` 向 stdout 打弃用提示，污染 CLI JSON；单独提交改为 `import pymupdf as fitz`，受影响的 372 项通过。第一次清理后全量为 999 通过、1 失败，暴露 WebKit 在本地期限到达后仍发起 1 毫秒采样的竞态；新增用例先稳定复现，再修复为到期不再采样，并核对最后一次采样后的网络 revision。没有放宽总超时、网络安静期或 PDF 规则。最终全量 **1002 项通过**（253.32 秒，6 条依赖弃用警告，无跳过）。
- **规模与保留**：纯清理删 27 项参数化测试（21 个函数），补 8 项活事务验证；WebKit 修复另补 2 项，最终测试数 1019 → 1002，净减 17。纯清理的生产 Python 删除 3094 行、增加 63 行，净减 3031 行；测试净减 394 行；连同 shim 和文档净减 3465 行，不含此次报告及两项兼容/边界修复。`citation/proofread` 和 `translate legacy` 仍能从公开 shim 到达，是否随未来 draft 重做一起下线尚不确定，因此保留；固定旧 OCR progress 与 DS generation 的只读恢复有明确活调用和 PDF_PIPELINE 约束，保留；BodySchema 的 H1、身份和写作证据说明仍作为维护依据保留。当前任务没有等待用户决定的阻塞项。

- **未覆盖**：论文下载的异常路径（身份存疑、下载额度用完、只有 HTML、要用户决定）、译本的两个 CLI 问题、research 实测、draft 入口、Claude Code 和 agy 的权限配置，以及 pi。

**2026-11-08，BabelDOC 0.7.1 实测**：在 Mac Mini 测试文库，以 Python 3.12 隔离安装 BabelDOC 0.7.1 + pdf2zh-next 2.10.2，沿现有 pdf2zh adapter 试译。原生论文 5 页生成 10 页双语 PDF，106.88 秒，中文覆盖率中位数 0.300588，通过；现有 Stilgoe 布局 OCR 论文 13 页生成 26 页，341.78 秒，排除有来源依据的参考文献后中位数 0.272669，未过 0.30，保留检查，不发布正式译本。两份均未触发 ToUnicode 修复，不能据此认定旧问题普遍消失。另对同一 5 页原生 PDF 交替跑 0.6.4 / 0.7.1 各三次，关闭模型翻译并在公式样式处理结束后停止，取中位数：版面阶段 1.2032 → 0.8159 秒（耗时少 32.2%），解析 0.3464 → 0.1433 秒，段落 0.4789 → 0.1086 秒，处理至公式样式结束合计 4.3069 → 2.1257 秒（少 50.6%）。模型加载不计时，未测 MinerU OCR 或旧版端到端翻译。未修改依赖、配置或质量门槛；布局样本覆盖率仍需检查，尚不作全面采用建议。详细方法、原始计时和产物位置见 [实测记录](evals/babeldoc-071-20261108.md)。

同日按用户授权继续对照后正式采用：Stilgoe 前三页在相同公开 API/配置下，0.6.4 与 0.7.1 的覆盖率为 0.272771 / 0.273496；Hutchby 扫描书四页经 MinerU 布局 OCR 后，两版为 0.276477 / 0.275064，均保留为未过门槛的候选。抽查两版同页与扫描书最低分页，未见新增整段遗漏或明显重叠，不能据此保证全篇质量。原 Stilgoe 中的兼容汉字漏计只解释部分差值，NFC 只读重测为 0.288981，仍未过线，不改计数器或阈值。最终固定 `pdf2zh-next==2.10.2` 与 `BabelDOC==0.7.1`，移除旧 bitstring 约束，将 engine 纳入现有配置指纹。本机与 Mac Mini 的两个实现文件及两个测试文件哈希一致。Mac Mini 相关回归 **114 项通过**；五页原生论文经真实严格 observe/run/final 事务发布 10 页译本并确认 reused。未运行全量回归，未更改用户默认 backend，未覆盖旧译本。
