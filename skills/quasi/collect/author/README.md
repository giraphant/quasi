# 收录一位作者

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

收一位作者的代表作，再据此写一份作者页。下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/author/`。

## 流程

1. **确定身份。** 弄清作者全名，以及用户是从哪个研究议题（topic）来找这位作者的；议题决定哪些作品算"代表作"。slug 用全名的 kebab 写法，比如 `adrian-mackenzie`。默认收 5 本书、10 篇论文，用户可以要求少收。

2. **观察现状。** `quasi status --kind author --slug SLUG --json`。作者页已经在了，就跳到第 7 步做 audit。

3. **找代表作。** 分别检索书和论文：

   ```sh
   quasi search book --author "全名" --query "议题" --limit 20
   quasi search paper --author "全名" --query "议题" --limit 30
   ```

   按引用量和与议题的相关度挑出代表作。逐项核对作者确实是这个人：同名作者很常见，看合著者、机构、研究领域是否对得上。同一部作品的不同版本只留一个。论文其实是书的一章时，归到书里。

4. **请用户确认清单。** 把挑出的书和论文列给用户（题名、年份、为什么入选），用户确认或删改后再动手。代表作一多，工作量就很大，这一步不要省。确认后的清单存进 `.quasi/temp/author-SLUG-list.md`。

5. **查重。** 把整份清单写进 `.quasi/temp/` 下的一个 JSON 文件（每项写 `kind`、`slug`、`title`、`authors`，以及 `doi` 或 `isbn`），运行 `quasi helpers vault resolve --items-file 该文件`。已经收过的作品沿用文库里的 slug，并对它们的页面跑一次 audit；只收还没有的。

6. **逐件收录。** 每件作品按 `collect/README.md` 里"一次收好几件"的规则，派材料会话从对应的入口跑到底：论文用 `collect/paper/README.md`，书用 `collect/book/README.md`。书会再派自己的章节写手，所以同时最多开 3 个材料会话，做完一批再开下一批。

   某件作品下载不到或要用户决定，记下来，继续做别的；全部跑完后一起报告。

7. **写作者页。** 所有作品都有通过 audit 的页面以后（收不到的除外），按 `connectors/rex.md` 派一个写手：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径
   作者：全名；研究议题：…
   请读这些作品页（书给全书概览，论文给论文页），每行一个：
   绝对路径 | 链接写法（书写 [[书的slug/00-overview|书名]]，论文写 [[论文slug|论文题名]]）
   按写作说明写出作者页。只读取上面列出的文件。
   ```

   检查回复文件无误后，存为 `vault/authors/SLUG.md`。

8. **验收。** `quasi audit --path vault/authors/SLUG.md`，按 `collect/README.md` 的规则处理。

9. **报告。** 告诉用户作者页路径、收了哪些作品、哪些没收到及原因。

## 续跑

中断之后，从第 2 步重新观察。确认过的清单存在 `.quasi/temp/author-SLUG-list.md`，续跑时直接用，不重新挑。已有页面的作品不重做。
