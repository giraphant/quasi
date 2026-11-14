# 派活：Rex

quasi 派活只用五个动作：开工、等待、读结果、追加、收工。本页把它们映射到 Rex。要换终端框架，就在 `connectors/` 下另写一页，再把根目录 `SKILL.md` 里指向本页的那一行改掉。一次要派一大批任务会话时，可以改用文末的「无头批量派工」，不开 pane。

前提：你自己运行在 Rex 里。先确定自己所在的会话和 pane：

```sh
RS="${REX_SESSION:-$QUASI_REX_SESSION}"; RB="${REX_BLOCK:-$QUASI_REX_BLOCK}"
```

你是用户直接开的会话时，用的是 `REX_*`；你是被派出来的材料会话时，用的是 `QUASI_REX_*`（原因见"开工"）。两者都没有，就先跑 `rex whoami --json`；连不上就告诉用户。下文命令里的 `$RS`、`$RB` 都指这两个值。另外记下你会话现在的名字（`rex session inspect "$RS" --json` 里的 `label`），收工时要核对。Rex 的完整用法见 rex 技能，这里只写 quasi 用得到的部分。

## 写手和任务会话

- **写手**：写一份文档，把整页写进回复文件。
- **任务会话**：材料会话处理一件材料，Scout 按 `snowball/scout.md` 整理候选，两者使用 `session_harness`。综合会话是按 `snowball/synthesis.md` 直接维护专题文档的综合写手，使用 `writer_harness`。需要用户决定时，在自己的 pane 里说明。

两种工人都在 pane 里跑交互式会话，这样用户能看到它在做什么，也能随时插话。不要用 harness 自带的子代理（Codex 的 `spawn_agent`、Claude 的 Task 之类）代替 pane 工人：用户看不见它们，也换不了写作模型。

## 准备消息

每个工人一个标签，形如 `paper-SLUG-write`。把交给它的消息写进 `.quasi/temp/workers/标签.prompt.md`。

- **写手的消息**：读哪份写作说明、输入文件、书目信息、交付方式。交付方式写成："把完整的笔记写进文件 R（从 frontmatter 的第一行 --- 开始，到最后一节结束，前后不加别的文字），不要把全文贴在对话里；写完后在 S 里写一行「完成」。"
- **任务会话的消息**：使用 quasi 技能，从哪份工作说明开始（绝对路径），以及材料线索、Scout 或综合任务的输入和文档输出路径。末尾加上这一段：

  ```text
  做完、需要用户决定、或者做不下去时，把状态写进 .quasi/temp/workers/标签.status.md：第一行只写「完成」「等你决定」或「失败」之一，后面用一两句话说明。写完不要退出，等下一条消息。
  ```

每条消息的第一句写："你是被派出来的工人，运行在别人的 Rex 会话里，不要重命名 Rex 会话、窗口或 pane。"写手还要加一句"这个任务不需要调用任何 rex 命令"。

不加 JSON 信封，也不要求回执格式。交给工人的文件路径尽量落在文库根目录之内，否则可能没有读取权限；本技能目录如果在文库之外，就改用文库里 `.agents/skills/quasi/` 这个软链接下的路径。

## 开工：在旁边开一个 pane

工人开在你自己的 pane 旁边，排成右侧一列。用户可以自己折叠、放大这些 pane，不影响工人运行。

- 第一个工人，从你的 pane 往右分出一列：

  ```sh
  rex split -s "$RS" -b "$RB" --split=right --ratio 40 \
    -c "$PWD" --label "标签" --keep-open --focus=false --json -- \
    sh -c 'export QUASI_REX_SESSION="$REX_SESSION" QUASI_REX_BLOCK="$REX_BLOCK"; unset REX_SESSION REX_BLOCK; exec 命令'
  ```

  `sh -c` 里的前半段不能省。Rex 会在每个 agent 启动时，凡是看到 `REX_SESSION`，就提示它先给会话起名；工人照做的话，就会把你的会话改名（实测发生过）。所以先把两个变量另存成 `QUASI_REX_*` 再清掉：钩子看不到会话，不会再提示；材料会话仍然能用另存的值派写手。

- 之后的工人，在最近开的那个工人 pane 下方叠一个：把 `-b` 换成那个工人的 BLOCK，`--split=right --ratio 40` 换成 `--split=below`。
- 右侧的工人 pane 都关掉之后，下一个工人重新从 `$RB` 往右开。

记下返回 JSON 里的 `.block_ids[0]`，后面的动作都用它。

派工前，分别读出写手和材料会话使用的 harness：

```sh
quasi config get writer_harness
quasi config get session_harness
```

派写手时按 `writer_harness` 的值选下面表里的写手命令，派材料会话或 Scout 时按 `session_harness` 的值选材料会话命令。综合会话使用 `writer_harness` 对应的写手命令，消息和完成状态按任务会话处理，直接更新派工指定的专题文档。两项未设时都用 codex；用户可以在 Marple 的设置里或用 `quasi config set writer_harness agy`、`quasi config set session_harness codex` 分别修改。材料会话自己派写手时也要这样读，不能因为自己运行在 Codex 里，就把写作也交给 Codex。

各 harness 的命令（`P`、`R`、`S` 分别是这个标签的 prompt、reply、status 文件的绝对路径）：

| harness | 写手 | 材料会话 |
|---|---|---|
| codex | `codex --no-daemon -C "$PWD" -s workspace-write -a on-request "$(cat P)"` | 同左 |
| agy | `agy --mode auto -i "$(cat P)"` | `agy --model gemini-4-argon-high --mode auto -i "$(cat P)"` |
| claude | `claude --permission-mode auto "$(cat P)"` | 同左 |
| pi | `pi "$(cat P)"` | 同左 |

环境变量 `QUASI_WORKER_PERMISSIONS` 的值是 `full` 时（用户专门放开权限的开发机），改用下面的完全放行命令，写手和材料会话相同：

| harness | 命令 |
|---|---|
| codex | `codex --no-daemon --dangerously-bypass-approvals-and-sandbox -C "$PWD" "$(cat P)"` |
| agy | `agy --model gemini-4-argon-high --dangerously-skip-permissions -i "$(cat P)"` |
| claude | `claude --dangerously-skip-permissions "$(cat P)"` |
| pi | `pi "$(cat P)"` |

注意事项：

- Pi 默认没有内置权限确认或沙箱；两张表都用同一条交互命令，不加不存在的权限参数。需要限制时应先配置 Pi 扩展或外部沙箱。

- `agy` 的 `-p`、`-i` 会把紧跟在后面的那个参数当成提示词，所以 `--model`、`--mode` 等选项必须放在它们之前。
- `--no-daemon` 是 `codex` 自身的选项，要放在子命令前面，比如无头模式写成 `codex --no-daemon exec …`。
- 权限是装机时一次配好的（联网、缓存目录、quasi 和 rex 命令的放行）。工人仍然停在确认提示上，就告诉用户去对应 pane 处理。除了上面 `QUASI_WORKER_PERMISSIONS=full` 的情形，不要加 `--dangerously-skip-permissions` 一类绕过权限的参数。agy 的 `--mode auto` 会自己审核要跑的命令，常规命令不再逐条问用户，材料会话用它。
- 交互式会话第一次在某个文库里打开时，harness 可能会问是否信任这个文件夹。这要用户在 pane 里确认一次，告诉用户去点。
- 单页写手把整页写到 `.quasi/temp/workers/` 下的回复文件，由派工者检查后保存。综合会话在输入中获得明确的 Topic 页面输出路径，直接维护这些页面并完成 audit。
- 无头模式（`agy -p "…" > R`）也能用，但 pane 里什么都看不到，只在不需要用户看的场合用。在你自己的 shell 里直接跑 harness 时，同样要先清掉这两个变量（`env -u REX_SESSION -u REX_BLOCK codex …`），否则它也会去改你的会话名（实测发生过）。

可以连续开好几个工人并行跑，然后逐个等待。所有层级的工人都开在同一个 Rex 会话里，所以开工前先数一下会话里的 pane（`rex session inspect "$RS" --json`）：加上用户的主会话，总数不超过 7 个；满了就等有 pane 关掉再开。遇到模型服务限流（429），再少开几个，过一会儿再派，不要改用别的通道。

## 等待

交互会话不会自己退出，所以看状态文件 `S`：每隔半分钟看一次，有内容了就读第一行。并行的工人可以在一个循环里一起看。也可以看 Rex 收到的程序状态：

```sh
rex block call -s "$RS" -b BLOCK program_status
```

agy、claude、codex 都会上报自己的状态：`working` 表示正在干活；`done` 表示这一轮做完了，在等下一条消息；`blocked` 且 `kind: "permission"` 表示在等用户批准，这时告诉用户去对应的 pane 里处理。状态文件仍是判断结果的依据，程序状态只用来知道它是不是卡住了。

## 读结果

- **写手**：读 `R`。页面应当从 frontmatter 的第一行 `---` 开始；开头如果夹着说明文字，删掉那部分再存；正文本身有问题就重派。
- **任务会话**：读 `S`，再读交付文档。材料会话负责收录产物的 audit，综合会话负责 Topic 文档的 audit；上级围绕文档内容和本轮任务判断交付，收录或综合内部的修订交回对应会话完成。

文件为空或内容不对时，看工人 pane 里的输出：

```sh
rex capture -s "$RS" -b BLOCK --trim | tail -n 40
```

## 追加

给还开着的交互会话补一句话，比如回答它的问题，或者带上 audit 诊断让它接着改：

```sh
rex send -s "$RS" -b BLOCK '要说的话' && rex send-key -s "$RS" -b BLOCK enter
```

发之前先清空状态文件，再照"等待"里的办法等它写新的状态。

## 收工

验收通过后关掉：

```sh
rex block close -s "$RS" BLOCK
```

失败的工人先别关，留给用户看。最后核对一下你会话的名字有没有被改掉；改了就用 `rex session rename "$RS" 原来的名字` 改回来。

## 无头批量派工

一次要派很多任务会话、又不需要用户逐个盯着时（典型是 snowball 的一批材料会话和 Scout），不要开一排 pane：pane 要占席位、要记 block、要逐个收工，派工本身成了主会话的负担。这种场合把任务会话换成无头工人：消息、状态文件、验收合同都不变，只是进程在后台跑，画面写进日志文件。写手不进无头：单页写手和综合会话仍按「开工」一节开 pane，用户要看得见、要能换写作模型。

### 消息

照「准备消息」写 `.quasi/temp/workers/标签.prompt.md`，但无头工人是一次性的：末尾那段删去「写完不要退出，等下一条消息」，只保留写状态文件的约定。无头工人没法被追问；要用户决定的事，让它写「等你决定」并停下，答案由你放进下一次派工的消息里重派。派工前先删掉同名旧状态文件，免得把上一轮的当成这一轮的。

### 开工

无头工人从你的 shell 启动，不经过 rex split。所有命令带同一串前缀——清掉 `REX_*`（原因见「开工」开头），把你的会话与 pane 另存成 `QUASI_REX_*` 传下去（材料会话自己还要开写手 pane），`nohup` 放后台：

```sh
env -u REX_SESSION -u REX_BLOCK QUASI_REX_SESSION="$RS" QUASI_REX_BLOCK="$RB" nohup
```

下表省略这串前缀；`P` 是 prompt 文件的绝对路径，`L` 是日志文件（`.quasi/temp/workers/标签.log`）的绝对路径。harness 仍按 `quasi config get session_harness` 选：

| harness | 命令 |
|---|---|
| codex | `codex --no-daemon exec --skip-git-repo-check -C "$PWD" -s workspace-write "$(cat P)" > L 2>&1 &` |
| agy | `agy --model gemini-4-argon-high --mode auto -p "$(cat P)" > L 2>&1 &` |
| claude | `claude --permission-mode acceptEdits -p "$(cat P)" > L 2>&1 &` |
| pi | `pi -p "$(cat P)" > L 2>&1 &` |

`QUASI_WORKER_PERMISSIONS` 为 `full` 时改用完全放行。无头进程卡在权限提示上没有人能点，比 pane 更要避免：

| harness | 命令 |
|---|---|
| codex | `codex --no-daemon exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -C "$PWD" "$(cat P)" > L 2>&1 &` |
| agy | `agy --model gemini-4-argon-high --dangerously-skip-permissions -p "$(cat P)" > L 2>&1 &` |
| claude | `claude --dangerously-skip-permissions -p "$(cat P)" > L 2>&1 &` |
| pi | pi 没有权限参数，同上 |

无头工人自己不占 pane，但它们派的写手 pane 占的是你会话的席位（一个工人至多同时占一个写手席位），所以同时在飞的无头任务会话不要超过 5 个，加上你的主会话正好用满 7 个 pane。一批超过 5 件就分波：一波落地后再发下一波。遇到 429 减并发，不要硬发。

### 等待与读结果

无头工人结束的标志是它的状态文件非空。等一批工人用一条阻塞循环，不要反复醒来看：

```sh
# 等一波 5 件，标签形如 batch-3-<材料slug>
for i in $(seq 1 60); do
  n=$(find .quasi/temp/workers -maxdepth 1 -type f -name 'batch-3-*.status.md' -size +0c | wc -l)
  [ "$n" -ge 5 ] && break
  sleep 30
done
```

半小时（60 × 30 秒）还没写状态的就是卡住了：`tail -n 40` 它的日志，权限提示或明显挂死的按失败处理。状态文件第一行仍是「完成」「等你决定」「失败」三选一，处理办法同「读结果」。想看某个工人在干什么，随时 `tail` 它的日志；也可以临时开一个 pane 跑 `tail -f` 同时盯几个日志，看完关掉。

### 返修

无头没有「追加」：返修、回答它的问题、audit 后再改，都是带着新材料（诊断、现有产出、你的回答）重新派一个。一次性任务这样反而干净。
