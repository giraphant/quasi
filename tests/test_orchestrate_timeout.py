from __future__ import annotations

from pathlib import Path
import re


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATE = PLUGIN_ROOT / "workflows" / "process-material.mjs"
RUNTIME = PLUGIN_ROOT / "scripts/workflows" / "runtime.mjs"


def source() -> str:
    return ORCHESTRATE.read_text(encoding="utf-8")


def runtime_source() -> str:
    return RUNTIME.read_text(encoding="utf-8")


def code_lines() -> list[tuple[int, str]]:
    """行号 + 正文,去掉整行注释(注释里提 agent( 不算调用)。"""
    out = []
    for i, line in enumerate(source().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        out.append((i, line.split("//")[0]))
    return out


def test_one_agent_primitive_feeds_bounded_legacy_and_unbounded_writer():
    """Legacy calls remain bounded; operation writers await one underlying call.

    Racing a writer against the legacy timer could return blocked while the losing
    Agent continues writing in the background, so guard and invokeWriter share one
    callAgent primitive but only guard races its returned Promise.
    """
    bare = [
        (n, line.strip())
        for n, line in code_lines()
        if re.search(r"(?<![\w.:])agent\s*\(", line)
    ]

    assert len(bare) == 1, f"agent() 调用边界漂移: {bare}"
    assert re.search(
        r"Promise\.resolve\(agent\(prompt,\s*opts\)\)",
        bare[0][1],
    )

    runtime = runtime_source()
    assert "const callAgent = (prompt, opts) =>" in runtime
    assert "const invocation = callAgent(prompt, opts)" in runtime
    assert "const invokeWriter = async" in runtime
    assert "await callAgent(prompt, opts)" in runtime
    assert 'effect === "writer"' in runtime
    assert "? await invokeWriter(prompt, opts)" in runtime
    assert "writer operation retry policy must be forbidden" in runtime


def test_timeout_is_finite_and_sane():
    match = re.search(
        r"const AGENT_TIMEOUT_MS = (\d+) \* 60 \* 1000", runtime_source()
    )
    assert match, "AGENT_TIMEOUT_MS 必须是显式的分钟常量"

    minutes = int(match.group(1))
    # 下界:实测跑完的最长 agent(extract-agent 拆大部头)是 32 分钟,腰斩活着的 agent 比卡住更贵。
    # 上界:超时的意义是别让一次挂死吃掉一整夜。
    assert 35 <= minutes <= 120, f"AGENT_TIMEOUT_MS={minutes} 分钟超出合理区间"


def test_timeout_resolves_null_into_the_retry_path():
    """超时必须归一成 null —— retryNull 的 ?? 才接得住,复用既有的一次重投。"""
    runtime = runtime_source()
    guard = re.search(r"const guard = \(prompt, opts\) => \{.*?\n  \};", runtime, re.S)
    assert guard, "guard 不见了"

    body = guard.group(0)
    assert "resolve(null)" in body, "超时分支必须 resolve(null),不能 throw 或 resolve 别的值"
    assert "clearTimeout(timer)" in body, "agent 先返回时必须清掉定时器,否则挂着的 timer 拖住收尾"
    assert "??" in runtime and "guard(prompt + retrySuffix" in runtime, (
        "retryNull 必须仍然接住 guard 返回的 null"
    )
