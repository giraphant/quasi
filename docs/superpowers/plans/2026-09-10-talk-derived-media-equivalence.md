# Talk observe：先转写、后补视频的 generation 仍视为 current（配方，目标版本 0.65.33）

## 背景

`quasi-transcribe observe`（`scripts/transcribe/transcribe.py::cmd_observe`，约 704–745 行）在
`vault/talks/{slug}/recording.mp4` 及其 sidecar 有效时，把 transcription source 切换为 prepared media，
并只用 prepared media 的 SHA 计算 `request_fingerprint`。0.65.31 及之前的 Talk 常见顺序是"先用原始
媒体转写、事后再 prepare-media"，于是 `processing/talks/{slug}/manifest.json`（source 为原始 .mov）会被
报告为 `request_fingerprint:null`、artifacts 不含 transcript 行，也就是"不可复用"。文件本身完好无损。

实测：`bts` vault 的 `maintenance-sig-dominic-brownell-repair-reuse-cars-20260910`，转写 manifest 的
`source.sha256 = 29272ac8…`（.mov），sidecar `input_sha256` 同为 `29272ac8…`，`observe` 却返回
`request_fingerprint:null`。

`compress_media.inspect_prepared(output, source_sha)` 只有在 sidecar `input_sha256 == source_sha` 时才返回
identity，所以 `prepared_identity is not None` 已经证明 recording.mp4 派生自本次 exact 原始 source。

## 目标

`observe` 在 prepared media 存在时，除 prepared-based fingerprint 外，也接受"以本次 exact 原始 source 转写"
的 generation 为 current。其它命令（`run`/`classify`/`silent`）和 Workflow 层不变。

## 硬约束

- 工作树里别人未提交的改动**不要碰、不要 stash/checkout/revert**：`scripts/audit/audit.py`、
  `scripts/audit/field_distribution.py`、`scripts/schemas/SPEC.md`、`scripts/schemas/body.py`、
  `scripts/typecheck/typecheck.py`、`tests/test_audit_readonly_contract.py`、`tests/test_schema_snapshot.py`、
  `tests/test_typecheck_contract.py`。
- 不改 `scripts/workflows/`、`workflows/*.mjs`、`scripts/status/`、`scripts/talk/compress_media.py`、
  `scripts/transcribe/talk_commit.py`。
- 不改版本号、`docs/CHANGELOG.md`、`CLAUDE.md`/`AGENTS.md`。不 commit。

## 改动

### 1. `scripts/transcribe/transcribe.py::cmd_observe`

把现有的单一比对：

```python
if (
    manifest["request_fingerprint"] != fingerprint
    or manifest["source"].get("sha256") != transcription_source.get("sha256")
    or manifest["source"].get("size") != transcription_source.get("size")
):
    manifest = None
    fingerprint = None
else:
    ...
```

改为对候选 source 逐个匹配：

```python
candidates = [transcription_source]
if prepared_identity is not None:
    # inspect_prepared already proved recording.mp4 derives from this exact
    # source, so a generation transcribed from the raw source is the same request.
    candidates.append(source)
matched = next(
    (
        candidate
        for candidate in candidates
        if manifest["request_fingerprint"]
        == request_fingerprint(candidate, engines, lang, title)
        and manifest["source"].get("sha256") == candidate.get("sha256")
        and manifest["source"].get("size") == candidate.get("size")
    ),
    None,
)
if matched is None:
    manifest = None
    fingerprint = None
else:
    fingerprint = manifest["request_fingerprint"]
    ...  # 现有 else 分支原样保留
```

`fingerprint` 变量在 manifest 为 None 时的既有语义（"只报告已 committed generation 的 fingerprint"）不变。
`_observe_receipt` 不改：manifest 匹配时 `artifacts` 自然包含 transcript/engine 行加 `prepared_media` 行。

### 2. `agents/transcribe-agent.md`

「工作方法」第一段补半句：`observe` 报告 generation 为 current 时（包括先于 prepared media、从原始 source
转写出来的 generation）直接复用，不再调用 `run`。

### 3. 测试 `tests/test_transcribe_cli.py`

参照现有 `test_prepared_video_observe_uses_prepared_source_fingerprint` 的 monkeypatch 方式：

- `test_prepared_video_added_after_transcription_keeps_raw_generation_current`：
  1. 写 `sources/input.mov`，`_stub_audio`，以 `--media sources/input.mov`、slug `video-talk`、title `Video Talk`
     跑 `run` → `disposition == "created"`，记下 `first["request_fingerprint"]`。
  2. 再对同一 `sources/input.mov` 跑 `compress_media.run`（monkeypatch ffmpeg）生成
     `vault/talks/video-talk/recording.mp4` + sidecar。
  3. `observe --media sources/input.mov ...`：断言 `request_fingerprint == first["request_fingerprint"]`、
     `prepared_path == "vault/talks/video-talk/recording.mp4"`、`classification == "live"`、
     `transcript_path` 非 None、`artifacts` 同时含 `role == "transcript"` 与 `role == "prepared_media"` 行、
     引擎 stub 的 `calls == []`。
- `test_prepared_video_does_not_revive_a_generation_from_another_source`：
  1. 以 `_args(tmp_path, "video-talk")` 默认的 `sources/talk.wav` 跑 `run`（manifest source 为 talk.wav）。
  2. 对 `sources/input.mov` 跑 `compress_media.run` 生成 recording.mp4 + sidecar。
  3. `observe --media sources/input.mov ...`：断言 `request_fingerprint is None`，`artifacts` 只有
     `prepared_media` 一行。
- 现有 `test_prepared_video_observe_uses_prepared_source_fingerprint` 必须原样通过。

## 验证

```bash
python3 -m pytest tests/test_transcribe_cli.py tests/test_transcribe.py tests/test_compress_media.py \
  tests/test_dead_names.py tests/test_skill_orchestration.py -q
cmp -s CLAUDE.md AGENTS.md && echo same
git status --short
```

完成后报告：改动文件列表、pytest 结果原文、偏离配方之处及原因。
