"""quasi config: Keychain-backed keys, exercised against a fake `security` tool."""
from __future__ import annotations

import importlib.util
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Mimics the parts of /usr/bin/security that config.py uses. `-i` reads one
# command from stdin; inside double quotes it unescapes \\ and \" only, which is
# what shlex does in POSIX mode (checked against the real tool).
FAKE_SECURITY = r'''
import json, os, shlex, sys
store_path = os.environ["FAKE_KEYCHAIN"]
store = json.load(open(store_path)) if os.path.exists(store_path) else {}
args = sys.argv[1:]
if args == ["-i"]:
    args = shlex.split(sys.stdin.readline())
os.environ.get("FAKE_ARGV_LOG") and open(os.environ["FAKE_ARGV_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
op, rest = args[0], args[1:]
opts, i = {}, 0
while i < len(rest):
    if rest[i] in ("-U",):
        i += 1
        continue
    if rest[i] == "-w" and i + 1 == len(rest):
        opts["-w"] = None
        i += 1
        continue
    opts[rest[i]] = rest[i + 1]
    i += 2
key = opts["-s"] + "/" + opts["-a"]
if op == "find-generic-password":
    if key not in store:
        sys.exit(44)
    print(store[key]["password"])
elif op == "add-generic-password":
    store[key] = {"password": opts["-w"], "label": opts.get("-l")}
elif op == "delete-generic-password":
    if key not in store:
        sys.exit(44)
    del store[key]
json.dump(store, open(store_path, "w"))
'''


@pytest.fixture
def config(tmp_path, monkeypatch):
    fake = tmp_path / "security"
    fake.write_text(f"#!{sys.executable}\n{FAKE_SECURITY}")
    fake.chmod(0o755)
    monkeypatch.setenv("FAKE_KEYCHAIN", str(tmp_path / "keychain.json"))
    monkeypatch.setenv("FAKE_ARGV_LOG", str(tmp_path / "argv.jsonl"))
    for name in ("KAGI_SESSION_TOKEN", "TRANSLATE_BACKEND", "TRANSLATE_MODEL", "SONIOX_API_KEY"):
        monkeypatch.delenv(f"QUASI_{name}", raising=False)
    spec = importlib.util.spec_from_file_location("quasi_config", ROOT / "scripts" / "config" / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SECURITY", str(fake))
    module.store_path = tmp_path / "keychain.json"
    module.argv_log = tmp_path / "argv.jsonl"
    return module


def run(config, monkeypatch, capsys, *argv, stdin=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = config.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_secret_round_trips_exactly_and_never_reaches_argv(config, monkeypatch, capsys):
    secret = 'tok "en"\\with$HOME`x` \'q\''
    code, out, _ = run(config, monkeypatch, capsys, "set", "kagi_session_token", stdin=secret + "\n")
    assert code == 0 and "已保存" in out
    assert config.read("kagi_session_token") == secret
    stored = json.loads(config.store_path.read_text())["quasi/kagi_session_token"]
    assert stored["label"] == "quasi: kagi_session_token"
    assert secret not in config.argv_log.read_text()


def test_secret_value_on_the_command_line_is_refused(config, monkeypatch, capsys):
    code, _, err = run(config, monkeypatch, capsys, "set", "soniox_api_key", "abc")
    assert code == 2 and "不要写在命令行里" in err
    assert config.read("soniox_api_key") is None


def test_plain_setting_may_be_given_inline_and_choices_are_checked(config, monkeypatch, capsys):
    assert run(config, monkeypatch, capsys, "set", "translate_backend", "pdf2zh")[0] == 0
    assert config.read("translate_backend") == "pdf2zh"
    code, _, err = run(config, monkeypatch, capsys, "set", "translate_backend", "deepl")
    assert code == 2 and "immersive 或 pdf2zh" in err
    assert config.read("translate_backend") == "pdf2zh"


@pytest.mark.parametrize("value", ["", "   ", "中文", "a\nb"])
def test_empty_and_non_ascii_values_are_rejected(config, monkeypatch, capsys, value):
    code, _, err = run(config, monkeypatch, capsys, "set", "translate_model", stdin=value)
    assert code == 2 and err
    assert config.read("translate_model") is None


def test_unknown_key_is_rejected(config, monkeypatch, capsys):
    code, _, err = run(config, monkeypatch, capsys, "set", "kagi_token", "x")
    assert code == 2 and "没有这个键" in err


def test_exports_fill_missing_env_and_respect_explicit_values(config, monkeypatch, capsys):
    run(config, monkeypatch, capsys, "set", "kagi_session_token", stdin="it's secret")
    run(config, monkeypatch, capsys, "set", "translate_model", "gpt-x")
    monkeypatch.setenv("QUASI_TRANSLATE_MODEL", "from-env")
    code, out, _ = run(config, monkeypatch, capsys, "exports")
    assert code == 0
    assert out.startswith("export ")
    assert "QUASI_TRANSLATE_MODEL" not in out
    exported = subprocess.run(["sh", "-c", out + 'printf %s "$QUASI_KAGI_SESSION_TOKEN"'],
                              capture_output=True, text=True, check=True).stdout
    assert exported == "it's secret"


def test_exports_print_nothing_without_a_keychain(config, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(config, "SECURITY", str(tmp_path / "missing"))
    assert run(config, monkeypatch, capsys, "exports") == (0, "", "")


def test_show_json_hides_secret_values_and_reports_sources(config, monkeypatch, capsys):
    run(config, monkeypatch, capsys, "set", "kagi_session_token", stdin="sekrit")
    run(config, monkeypatch, capsys, "set", "translate_backend", "immersive")
    monkeypatch.setenv("QUASI_TRANSLATE_MODEL", "from-env")
    code, out, _ = run(config, monkeypatch, capsys, "show", "--json")
    assert code == 0 and "sekrit" not in out
    payload = json.loads(out)
    assert payload["service"] == "quasi"
    rows = {row["name"]: row for row in payload["keys"]}
    assert set(rows) == set(config.KEYS)
    assert rows["kagi_session_token"]["set"] is True and "value" not in rows["kagi_session_token"]
    assert rows["kagi_session_token"]["source"] == "keychain"
    assert rows["translate_backend"]["value"] == "immersive"
    assert rows["translate_backend"]["choices"] == ["immersive", "pdf2zh"]
    assert rows["translate_model"] == {**rows["translate_model"], "source": "env", "value": "from-env"}
    assert rows["soniox_api_key"]["set"] is False and rows["soniox_api_key"]["source"] is None


def test_show_text_masks_secrets(config, monkeypatch, capsys):
    run(config, monkeypatch, capsys, "set", "kagi_session_token", stdin="sekrit")
    code, out, _ = run(config, monkeypatch, capsys, "show")
    assert code == 0 and "sekrit" not in out and "kagi_session_token" in out


def test_unset_removes_and_tolerates_missing(config, monkeypatch, capsys):
    run(config, monkeypatch, capsys, "set", "translate_model", "m")
    assert run(config, monkeypatch, capsys, "unset", "translate_model")[1].startswith("已删除")
    assert config.read("translate_model") is None
    code, out, _ = run(config, monkeypatch, capsys, "unset", "translate_model")
    assert code == 0 and "本来就没设" in out


def test_shim_runs_without_the_venv():
    result = subprocess.run([str(ROOT / "scripts" / "commands" / "quasi-config"), "--help"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "show" in result.stdout and "unset" in result.stdout
