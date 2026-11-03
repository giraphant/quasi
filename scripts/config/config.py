#!/usr/bin/env python3
"""quasi configuration, kept entirely in the macOS login Keychain.

Every key is one generic-password item: service ``quasi``, account = key name.
Items are always written through /usr/bin/security, so the reads that every
quasi command makes through the same tool never raise an access prompt. GUI
front ends (Marple) call this command rather than touching the Keychain, which
keeps this file the only owner of the key list and the storage layout.

Scripts read only ``QUASI_<KEY>`` environment variables; ``exports`` fills the
missing ones from the Keychain, and an explicitly set variable always wins.
Values never travel in argv: secrets arrive on stdin and reach ``security``
through its stdin command mode.

Standard library only (macOS system Python 3.9): shims run this before the
venv exists.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

SERVICE = "quasi"
SECURITY = "/usr/bin/security"
_NOT_FOUND = 44

# name: (group, secret, description). Keep in sync with docs/SETUP.md.
KEYS: Dict[str, Tuple[str, bool, str]] = {
    "cookiecloud_server": ("下载", False, "CookieCloud 服务器地址"),
    "cookiecloud_uuid": ("下载", True, "CookieCloud 扩展里设的 user KEY"),
    "cookiecloud_password": ("下载", True, "CookieCloud 的端到端加密密码"),
    "cookiecloud_ezproxy_domain": ("下载", False, "学校 EZProxy 登录后的 cookie 域名，如 .idm.oclc.org"),
    "cookiecloud_ezproxy_base_url": ("下载", False, "学校 EZProxy 的地址"),
    "anna_donator_key": ("下载", True, "Anna's Archive 捐助者 key，用快速下载接口"),
    "translate_backend": ("翻译", False, "翻译后端：immersive 或 pdf2zh"),
    "immersive_auth_key": ("翻译", True, "Immersive Translate Zotero 接口的 key（immersive 后端）"),
    "translate_base_url": ("翻译", False, "OpenAI 兼容端点的地址（pdf2zh 后端；只填根地址会自动补 /v1）"),
    "translate_api_key": ("翻译", True, "OpenAI 兼容端点的 key（pdf2zh 后端）"),
    "translate_model": ("翻译", False, "OpenAI 兼容端点的模型名（pdf2zh 后端）"),
    "kagi_session_token": ("检索", True, "Kagi 的 Session Link 或 token，用于网络检索和豆瓣中文版查找"),
    "soniox_api_key": ("转写", True, "Soniox 转写接口的 key"),
}
CHOICES: Dict[str, Tuple[str, ...]] = {"translate_backend": ("immersive", "pdf2zh")}


class ConfigError(Exception):
    pass


def env_name(name: str) -> str:
    return "QUASI_" + name.upper()


def available() -> bool:
    return os.access(SECURITY, os.X_OK)


def _security(args: List[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SECURITY, *args], input=stdin, capture_output=True, text=True, timeout=10, check=False
    )


def read(name: str) -> Optional[str]:
    if not available():
        return None
    try:
        result = _security(["find-generic-password", "-s", SERVICE, "-a", name, "-w"])
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n") or None


def read_many(names: List[str]) -> Dict[str, str]:
    if not names or not available():
        return {}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        values = dict(zip(names, pool.map(read, names)))
    return {name: value for name, value in values.items() if value}


def _quote(text: str) -> str:
    """Quote one word for `security -i`, whose parser unescapes \\\\ and \\" inside quotes."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def validate(name: str, value: str) -> str:
    if name not in KEYS:
        raise ConfigError(f"没有这个键：{name}。运行 quasi config show 查看全部键名。")
    value = value.strip()
    if not value:
        raise ConfigError(f"{name} 的值是空的；要删除请用 quasi config unset {name}。")
    # `security -w` prints non-ASCII data as hex, indistinguishable from a hex
    # token, so only printable ASCII is stored.
    if not (value.isascii() and value.isprintable()):
        raise ConfigError(f"{name} 的值只能是可打印的 ASCII 字符（网址里的中文请先转义）。")
    choices = CHOICES.get(name)
    if choices and value not in choices:
        raise ConfigError(f"{name} 只能是 {' 或 '.join(choices)}。")
    return value


def write(name: str, value: str) -> None:
    value = validate(name, value)
    if not available():
        raise ConfigError("quasi 的配置存在 macOS 钥匙串里；这台机器没有 /usr/bin/security，请直接设环境变量 " + env_name(name) + "。")
    command = " ".join([
        "add-generic-password", "-U", "-s", SERVICE, "-a", name,
        "-l", _quote(f"quasi: {name}"), "-w", _quote(value),
    ])
    result = _security(["-i"], stdin=command + "\n")
    if result.returncode != 0:
        raise ConfigError(f"写入钥匙串失败（{result.returncode}）：{result.stderr.strip()}")


def delete(name: str) -> bool:
    if name not in KEYS:
        raise ConfigError(f"没有这个键：{name}。运行 quasi config show 查看全部键名。")
    if not available():
        return False
    result = _security(["delete-generic-password", "-s", SERVICE, "-a", name])
    if result.returncode == _NOT_FOUND:
        return False
    if result.returncode != 0:
        raise ConfigError(f"从钥匙串删除失败（{result.returncode}）：{result.stderr.strip()}")
    return True


def describe() -> List[dict]:
    stored = read_many([name for name in KEYS if not os.environ.get(env_name(name))])
    rows = []
    for name, (group, secret, description) in KEYS.items():
        from_env = os.environ.get(env_name(name)) or None
        value = from_env or stored.get(name)
        row = {
            "name": name,
            "env": env_name(name),
            "group": group,
            "secret": secret,
            "description": description,
            "set": value is not None,
            "source": "env" if from_env else ("keychain" if value else None),
        }
        if name in CHOICES:
            row["choices"] = list(CHOICES[name])
        if not secret:
            row["value"] = value
        rows.append(row)
    return rows


def cmd_exports() -> int:
    """Print one `export` line for the shims to eval; never fail a command over config."""
    try:
        values = read_many([name for name in KEYS if not os.environ.get(env_name(name))])
    except Exception:  # noqa: BLE001 - a broken Keychain must not block quasi commands
        return 0
    if values:
        print("export " + " ".join(f"{env_name(n)}={shlex.quote(v)}" for n, v in values.items()))
    return 0


def cmd_show(as_json: bool) -> int:
    rows = describe()
    if as_json:
        print(json.dumps({"store": "macOS Keychain", "service": SERVICE, "keys": rows},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"quasi 配置（macOS 钥匙串，服务名 {SERVICE}；环境变量 QUASI_* 优先）")
    group = None
    width = max(len(name) for name in KEYS)
    for row in rows:
        if row["group"] != group:
            group = row["group"]
            print(f"\n{group}")
        if not row["set"]:
            state = "未设"
        elif row["secret"]:
            state = "已设"
        else:
            state = f"已设  {row['value']}"
        if row["source"] == "env":
            state += f"  （来自环境变量 {row['env']}）"
        print(f"  {row['name']:<{width}}  {state}")
    return 0


def cmd_set(name: str, value: Optional[str]) -> int:
    if name not in KEYS:
        raise ConfigError(f"没有这个键：{name}。运行 quasi config show 查看全部键名。")
    secret = KEYS[name][1]
    if value is not None and secret:
        raise ConfigError(f"{name} 是密钥，不要写在命令行里：运行 quasi config set {name}，再粘贴值。")
    if value is None:
        if sys.stdin.isatty():
            prompt = f"{name}（{KEYS[name][2]}）："
            value = getpass.getpass(prompt) if secret else input(prompt)
        else:
            value = sys.stdin.read()
    write(name, value)
    print(f"已保存 {name}")
    if os.environ.get(env_name(name)):
        print(f"注意：环境变量 {env_name(name)} 也设了，quasi 会优先用环境变量。")
    return 0


def cmd_unset(name: str) -> int:
    print(f"已删除 {name}" if delete(name) else f"{name} 本来就没设")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quasi config",
        description="查看和修改 quasi 的配置。所有键都存在 macOS 钥匙串里（服务名 quasi），环境变量 QUASI_* 优先。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="列出所有键、有没有设、值从哪来；密钥不显示值")
    show.add_argument("--json", action="store_true", help="机器可读输出（给 Marple 之类的界面用）")
    set_ = sub.add_parser("set", help="设置一个键；值从标准输入读，在终端里会提示输入")
    set_.add_argument("name")
    set_.add_argument("value", nargs="?", help="只有非密钥的键可以直接写在这里")
    unset = sub.add_parser("unset", help="删除一个键")
    unset.add_argument("name")
    sub.add_parser("exports", help="（供 quasi 命令内部使用）输出补齐环境变量的 export 行")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "show":
            return cmd_show(args.json)
        if args.command == "set":
            return cmd_set(args.name, args.value)
        if args.command == "unset":
            return cmd_unset(args.name)
        return cmd_exports()
    except ConfigError as error:
        print(f"quasi config: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
