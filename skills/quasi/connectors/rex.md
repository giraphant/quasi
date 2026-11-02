# 派活：Rex

quasi 派活只用五个动作：开工、等待、读结果、追加、收工。本页把它们映射到 Rex。要换终端框架，就在 `connectors/` 下另写一页，再把根目录 `SKILL.md` 里指向本页的那一行改掉。

前提：你自己运行在 Rex 里，`REX_SESSION` 和 `REX_BLOCK`（你自己的 pane）已设置。没有设置就先跑 `rex whoami --json`；连不上就告诉用户。Rex 的完整用法见 rex 技能，这里只写 quasi 用得到的部分。

## 两种工人

- **写手**：写一份文档，把整页写进回复文件。
- **材料会话**：从头到尾处理一整件材料（批量里的一篇论文、一本书）；需要用户决定时，它就在自己的 pane 里问。

两种工人都在 pane 里跑交互式会话，这样用户能看到它在做什么，也能随时插话。

## 准备消息

每个工人一个标签，形如 `paper-SLUG-write`。把交给它的消息写进 `.quasi/temp/workers/标签.prompt.md`。

- **写手的消息**：读哪份写作说明、输入文件、书目信息、交付方式。交付方式写成："把完整的笔记写进文件 R（从 frontmatter 的第一行 --- 开始，到最后一节结束，前后不加别的文字），不要把全文贴在对话里；写完后在 S 里写一行「完成」。"
- **材料会话的消息**：使用 quasi 技能，从哪个叶子入口开始（绝对路径），以及材料线索。末尾加上这一段：

  ```text
  做完、需要用户决定、或者做不下去时，把状态写进 .quasi/temp/workers/标签.status.md：第一行只写「完成」「等你决定」或「失败」之一，后面用一两句话说明。写完不要退出，等下一条消息。
  ```

每条消息末尾都加一句："不要重命名 Rex 会话、窗口或 pane。"Rex 会在每个 agent 启动时提示它给会话起名，而工人继承的是你的会话，照做就会把你的会话改名。写手还要加一句"这个任务不需要调用任何 rex 命令"。

不加 JSON 信封，也不要求回执格式。交给工人的文件路径尽量落在文库根目录之内，否则可能没有读取权限；本技能目录如果在文库之外，就改用文库里 `.agents/skills/quasi/` 这个软链接下的路径。

## 开工：在旁边开一个 pane

工人开在你自己的 pane 旁边，排成右侧一列。用户可以自己折叠、放大这些 pane，不影响工人运行。

- 第一个工人，从你的 pane 往右分出一列：

  ```sh
  rex split -s "$REX_SESSION" -b "$REX_BLOCK" --split=right --ratio 40 \
    -c "$PWD" --label "标签" --keep-open --focus=false --json -- sh -c '命令'
  ```

- 之后的工人，在最近开的那个工人 pane 下方叠一个：把 `-b` 换成那个工人的 BLOCK，`--split=right --ratio 40` 换成 `--split=below`。
- 右侧的工人 pane 都关掉之后，下一个工人重新从 `$REX_BLOCK` 往右开。

记下返回 JSON 里的 `.block_ids[0]`，后面的动作都用它。

**当前使用的 harness：codex。** 写手和材料会话都用它。要换成别的，只改这一行（正式写作推荐 agy，中文写得最好）。

各 harness 的命令（`P`、`R`、`S` 分别是这个标签的 prompt、reply、status 文件的绝对路径）：

| harness | 写手 | 材料会话 |
|---|---|---|
| codex | `codex --no-daemon -C "$PWD" -s workspace-write -a on-request "$(cat P)"` | 同左，需要联网下载时再加 `-c sandbox_workspace_write.network_access=true` |
| agy | `agy --model gemini-4-argon-high --mode accept-edits -i "$(cat P)"` | `agy --model gemini-4-argon-high --mode auto -i "$(cat P)"` |
| claude | `claude --permission-mode acceptEdits "$(cat P)"` | 同左 |

注意事项：

- `agy` 的 `-p`、`-i` 会把紧跟在后面的那个参数当成提示词，所以 `--model`、`--mode` 等选项必须放在它们之前。
- 不要加 `--dangerously-skip-permissions` 一类绕过权限的参数。agy 的 `--mode auto` 会自己审核要跑的命令，常规命令不再逐条问用户，材料会话用它。
- 交互式会话第一次在某个文库里打开时，harness 可能会问是否信任这个文件夹。这要用户在 pane 里确认一次，告诉用户去点。
- 写手只写 `.quasi/temp/workers/` 下的回复文件，不直接写进 vault。由你检查后存到输出路径，这样失败了也不会弄坏文库里的页面。
- 无头模式（`agy -p "…" > R`）也能用，但 pane 里什么都看不到，只在不需要用户看的场合用。

可以连续开好几个工人并行跑，然后逐个等待。

## 等待

交互会话不会自己退出，所以看状态文件 `S`：每隔半分钟看一次，有内容了就读第一行。并行的工人可以在一个循环里一起看。也可以看 Rex 收到的程序状态：

```sh
rex block call -s "$REX_SESSION" -b BLOCK program_status
```

agy 和 claude 会上报自己的状态：`working` 表示正在干活；`done` 表示这一轮做完了，在等下一条消息；`blocked` 且 `kind: "permission"` 表示在等用户批准，这时告诉用户去对应的 pane 里处理。状态文件仍是判断结果的依据，程序状态只用来知道它是不是卡住了。

## 读结果

- **写手**：读 `R`。页面应当从 frontmatter 的第一行 `---` 开始；开头如果夹着说明文字，删掉那部分再存；正文本身有问题就重派。
- **材料会话**：读 `S`，然后照常看磁盘、跑 audit，不信状态文件里的说法。

文件为空或内容不对时，看工人 pane 里的输出：

```sh
rex capture -s "$REX_SESSION" -b BLOCK --trim | tail -n 40
```

## 追加

给还开着的交互会话补一句话，比如回答它的问题，或者带上 audit 诊断让它接着改：

```sh
rex send -s "$REX_SESSION" -b BLOCK '要说的话' && rex send-key -s "$REX_SESSION" -b BLOCK enter
```

发之前先清空状态文件，再照"等待"里的办法等它写新的状态。

## 收工

验收通过后关掉：

```sh
rex block close -s "$REX_SESSION" BLOCK
```

失败的工人先别关，留给用户看。
