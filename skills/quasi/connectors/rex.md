# 派活：Rex

quasi 派活只用五个动作：开工、等待、读结果、追加、收工。本页把它们映射到 Rex。要换终端框架，就在 `connectors/` 下另写一页，再把根目录 `SKILL.md` 里指向本页的那一行改掉。

前提：你自己运行在 Rex 里，`REX_SESSION` 和 `REX_BLOCK`（你自己的 pane）已设置。没有设置就先跑 `rex whoami --json`；连不上就告诉用户。Rex 的完整用法见 rex 技能，这里只写 quasi 用得到的部分。

## 两种工人

- **写手**：写一份文档。无头运行，几分钟就完，只读文件，不需要用户插话。最终回复就是完整页面，存进回复文件。
- **材料会话**：从头到尾处理一整件材料（批量里的一篇论文、一本书）。交互式运行，用户能在 pane 里看到它在做什么，也能随时插话；需要用户决定时，它就在自己的 pane 里问。

## 准备消息

每个工人一个标签，形如 `paper-SLUG-write`。把交给它的消息写进 `.quasi/temp/workers/标签.prompt.md`。

- **写手的消息**：读哪份写作说明、输入文件、书目信息、交付方式（全文作为最终回复）。
- **材料会话的消息**：使用 quasi 技能，从哪个叶子入口开始（绝对路径），材料线索。末尾加上这一段：

  ```text
  做完、需要用户决定、或者做不下去时，把状态写进 .quasi/temp/workers/标签.status.md：第一行只写「完成」「等你决定」或「失败」之一，后面用一两句话说明。写完不要退出，等下一条消息。
  ```

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

各类工人用的命令（`W` 指 `$PWD/.quasi/temp/workers`，`P`、`R`、`S` 分别是这个标签的 prompt、reply、status 文件）：

| 工人 | 命令 |
|---|---|
| 写手（默认） | `echo "▶ 标签 写作中"; agy --model gemini-4-argon-high -p "$(cat P)" > R; echo "■ 结束 exit=$?"` |
| 写手（备用） | 把上面的 `agy …` 换成 `claude -p "$(cat P)"` |
| 材料会话（默认） | `agy --model gemini-4-argon-high --mode auto -i "$(cat P)"` |
| 材料会话（备用） | `claude --permission-mode acceptEdits "$(cat P)"`，或 `codex "$(cat P)"` |

注意事项：

- `agy` 的 `-p`、`-i` 会把紧跟在后面的那个参数当成提示词，所以 `--model`、`--mode` 等选项必须放在它们之前。
- 不要加 `--dangerously-skip-permissions` 一类绕过权限的参数。agy 的 `--mode auto` 会自己审核要跑的命令，常规命令不再逐条问用户，材料会话用它。
- 交互式会话第一次在某个文库里打开时，agy 会问是否信任这个文件夹。这要用户在 pane 里确认一次，告诉用户去点。
- 写手不写文件：由你检查回复后存到输出路径。这样写手只需要读权限，失败了也不会弄坏文库里的页面。

可以连续开好几个工人并行跑，然后逐个等待。

## 等待

**写手**：等进程结束。

```sh
rex wait -s "$REX_SESSION" BLOCK --for 9m --json
```

返回 `exit_code` 就是结束了；超时只说明还在跑，接着等。

**材料会话**：交互会话不会自己退出，所以看状态文件 `S`。每隔半分钟看一次，有内容了就读第一行。也可以看 Rex 收到的程序状态：

```sh
rex block call -s "$REX_SESSION" -b BLOCK program_status
```

agy 和 claude 会上报自己的状态：`working` 表示正在干活；`done` 表示这一轮做完了，在等下一条消息；`blocked` 且 `kind: "permission"` 表示在等用户批准，这时告诉用户去对应的 pane 里处理。状态文件仍是判断结果的依据，程序状态只用来知道它是不是卡住了。

## 读结果

- **写手**：读 `R`。写作回复应当从 frontmatter 的第一行 `---` 开始；开头如果夹着说明文字，删掉那部分再存；正文本身有问题就重派。
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
