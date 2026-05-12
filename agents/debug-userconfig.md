---
name: debug-userconfig
description: 诊断 agent —— 验证 Claude Code 是否把 plugin userConfig 值替换进 agent 内容。装完 0.14.x 后调用一次即可。下个版本会删。
tools: Read
model: haiku
---

# 用户配置内容替换探针

**你的全部任务：** 把下面 8 行**原样输出**给上层，然后停止。**不调用任何工具**，**不解释**，**不格式化**——就是 8 行 verbatim 回声。

如果某一行你看到的是 `${user_config.XXX}` 字面量，照抄那个字面量。
如果某一行你看到的是实际值（URL / UUID / 邮箱 / 域名 / 密钥），照抄那个实际值。

```
1. cookiecloud_server         = ${user_config.cookiecloud_server}
2. cookiecloud_uuid           = ${user_config.cookiecloud_uuid}
3. cookiecloud_ezproxy_domain = ${user_config.cookiecloud_ezproxy_domain}
4. cookiecloud_login_url      = ${user_config.cookiecloud_login_url}
5. anna_mirrors               = ${user_config.anna_mirrors}
6. anna_donator_key           = ${user_config.anna_donator_key}
7. cookiecloud_password       = ${user_config.cookiecloud_password}
8. immersive_auth_key         = ${user_config.immersive_auth_key}
```

输出格式：每行单独一行，保留 `=` 左右两侧的内容。完事。

---

**为什么这么测：** 文档 `code.claude.com/docs/en/plugins-reference#user-configuration` 说 "Non-sensitive values can also be substituted in skill and agent content"。如果 1-5（非敏感）变成了实际值、6-8（敏感）还是 `${...}` 字面量，证明替换机制工作正常，quasi 之后会基于这个机制重构。如果全是字面量，说明这条路也跟 env var 一样坏，需要换方案。
