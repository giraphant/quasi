# 部署 quasi

装机时照本页做一次。换一台机器、或新开一个文库时，再看一遍。agent 运行时不读本页；技能里只保留"quasi 命令要在沙箱外跑"这一句提醒。

做完之后跑 `scripts/quasi doctor`（在仓库目录里），缺什么它会列出来。

## 1. 外部工具

| 用途 | 工具 |
|---|---|
| 派活 | `rex`（工人开在 Rex pane 里） |
| 写手和工人 | `codex`、`agy`、`claude`，至少一个；用哪个写在 `connectors/rex.md` 的"当前使用的 harness"那一行 |
| 运行环境 | `uv` / `uvx`。Python 依赖装在 `~/.cache/quasi/.venv`，第一次运行时自动装好；`quasi doctor --sync` 可以手动同步 |
| 抽取 | `pdftotext`、`tesseract`（含 `eng`、`chi_sim`）、`ocrmypdf` |
| OCR | MinerU 经 `uvx` 运行，只支持 Apple Silicon；模型第一次用时下载到 `~/.cache/huggingface`，约 1 GB |
| 检索 | `kagi` |
| 转写 | `ffmpeg`（带 libx265）、`whisper-cli`、`swiftc` |
| 打开页面（可选） | `marple-cli` |

## 2. 密钥和服务配置

所有键都存在 macOS 登录钥匙串里，每个键一条（服务名 `quasi`，账户名就是键名）。用 `quasi config` 查看和修改：

```sh
scripts/quasi config show                         # 列出全部键、有没有设；密钥不显示值
scripts/quasi config set kagi_session_token       # 提示输入，粘贴后回车；输入不回显
scripts/quasi config set translate_backend pdf2zh # 非密钥的键可以直接写值
scripts/quasi config get writer_harness           # agent 也可读取，限非密钥；环境变量、钥匙串、默认值依次优先
scripts/quasi config unset translate_model
```

密钥不能写在命令行上（会留在 shell 历史和进程列表里），只能在提示里粘贴，或者从标准输入给。值只能是可打印的 ASCII 字符。也可以在"钥匙串访问"里搜 `quasi` 直接改已有的条目；新建条目请用 `quasi config set`，这样 quasi 读取时不会弹授权框。

每条 quasi 命令启动时会把钥匙串里的值填进 `QUASI_*` 环境变量（`QUASI_` 加大写键名，比如 `QUASI_KAGI_SESSION_TOKEN`）。显式设置的环境变量优先，适合临时换一个值；不是 macOS 的机器只能用环境变量。

| 键 | 用途 |
|---|---|
| `cookiecloud_server`、`cookiecloud_uuid`、`cookiecloud_password` | CookieCloud 服务器地址、扩展里设的 user KEY 和端到端密码，用来取浏览器 cookie 走 EZProxy 下载 |
| `cookiecloud_ezproxy_domain`、`cookiecloud_ezproxy_base_url` | 学校 EZProxy 登录后的 cookie 域名（如 `.idm.oclc.org`）和 EZProxy 地址 |
| `anna_donator_key` | Anna's Archive 捐助者 key，用快速下载接口 |
| `translate_backend` | 翻译后端：`immersive` 或 `pdf2zh` |
| `immersive_auth_key` | Immersive Translate Zotero 接口的 key（`immersive` 后端） |
| `translate_base_url`、`translate_api_key`、`translate_model` | OpenAI 兼容端点的地址、key 和模型（`pdf2zh` 后端；只填根地址会自动补 `/v1`） |
| `kagi_session_token` | Kagi 的 Session Link 或 token，用于网络检索和豆瓣中文版查找 |
| `soniox_api_key` | Soniox 转写接口的 key |
| `writer_harness` | 派工：写手使用的框架，`codex`、`agy` 或 `claude`，默认 `codex` |
| `session_harness` | 派工：材料会话使用的框架，`codex`、`agy` 或 `claude`，默认 `codex` |

## 3. 把技能装进文库

整个仓库就是技能，目录名要叫 `quasi`。最简单的装法是直接克隆到全局技能目录，再给 Claude 链一份：

```sh
git clone https://github.com/giraphant/quasi ~/.agents/skills/quasi   # codex、agy、pi 读这里
ln -s ~/.agents/skills/quasi ~/.claude/skills/quasi                    # claude 读这里
```

以后 `git pull` 就是更新。只想在某个文库里用，就在文库根目录建同样的两个软链接（`.agents/skills/quasi`、`.claude/skills/quasi`）指向仓库。注意：旧体系的 `~/.codex/skills/quasi` 还在的话，Codex 可能读到旧技能。

## 4. 权限

专门的开发机可以完全放开：在那台机器的登录环境里设 `QUASI_WORKER_PERMISSIONS=full`（比如写进 `~/.zshenv`），connector 就用跳过权限的命令启动工人，下面的配置都不用做。只在用户明确放开的机器上这样设。

quasi 的命令要用 GPU（OCR、转写）、浏览器（下载的回退）、网络，还要写文库外的几个共享缓存：`~/.cache/uv`、`~/.local/share/uv`、`~/.cache/quasi`、`~/.cache/kagi-cli`、`~/.cache/huggingface`。不配权限，worker 一跑就会停在确认提示上，等你去点。

下面的配置写在文库里（项目级），只对这个文库生效。全局配置也可以，格式相同。`Q` 指 quasi 命令的绝对路径，也就是 `.agents/skills/quasi/scripts/quasi`。经软链接调用时，规则里要把软链接路径和真实路径都写上。配置在会话启动时读取，配完要新开会话才生效（或者接着刚才的对话重开：`codex resume --last`、`agy --continue`、`claude --continue`）。

### Codex（已实测）

Codex 的沙箱里没有 GPU（MinerU 报 `No Metal device available`），也开不了浏览器，所以 quasi 命令必须在沙箱外跑。技能已经要求 agent 运行 quasi 命令时申请提权；下面这条规则会自动批准，不再问你。其他命令照常在沙箱里跑。

`.codex/rules/quasi.rules`：

```text
prefix_rule(pattern=["Q"], decision="allow")
prefix_rule(pattern=["rex"], decision="allow")
```

`.codex/config.toml`：

```toml
[sandbox_workspace_write]
network_access = true
writable_roots = ["/Users/you/.cache/uv", "/Users/you/.local/share/uv", "/Users/you/.cache/quasi", "/Users/you/.cache/kagi-cli", "/Users/you/.cache/huggingface"]
```

- 前缀规则只认单独一条命令。接了管道、重定向、heredoc 或 `&&` 的命令匹配不上，照样会弹确认；技能里已经要求 quasi 命令写成单独一条（第八轮实测）。
- `network_access` 也决定 rex 能不能在沙箱里连上 Rex 的 socket。不开的话，派活和轮询都要提权。
- 可写目录是兜底：quasi 命令忘了申请提权时，检索和下载至少还能在沙箱里跑。
- 项目配置只在受信任的文件夹生效。
- 放行 `rex`，等于允许 agent 在沙箱外开新会话（`rex split` 可以跑任意命令）。quasi 派活离不开它，你要知道这一点。
- 交互式确认里的第 2 项（"don't ask again"）会把一条带完整参数的规则写进全局的 `~/.codex/rules/default.rules`，换个参数就用不上了，不如这里的前缀规则。

### Claude Code（未实测）

`.claude/settings.local.json`：

```json
{
  "permissions": {
    "allow": ["Bash(Q:*)", "Bash(rex:*)"]
  }
}
```

Claude Code 默认不开沙箱，GPU 和缓存目录都能直接用；这两条只是免去逐条确认。开了沙箱的话，quasi 命令同样要在沙箱外跑。

### agy（未实测）

agy 的规则写法是 `command(前缀)`、`write_file(绝对路径)`、`read_url(域名)`，放在设置的 `permissions.allow` 里。全局设置在 `~/.gemini/antigravity-cli/settings.json`；项目级设置由 agy 存在 `~/.gemini/config/projects/` 下，优先于全局：

```json
{
  "permissions": {
    "allow": ["command(Q)", "command(rex)"]
  }
}
```

agy 默认不开沙箱（`--sandbox` 才开），GPU 可用。材料会话用 `--mode auto`，常规命令由它自己审核。
