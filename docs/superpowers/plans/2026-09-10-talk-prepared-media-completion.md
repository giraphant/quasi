# Talk prepared media 纳入完成条件（配方，目标版本 0.65.32）

## 背景

Talk Workflow 0.65.31 不保证生成 prepared media：

- `scripts/workflows/contracts/talk.mts::parseTalkOptions` 缺省 `prepare_media` 为 `false`，与媒体类型无关。
- `scripts/workflows/operations/rows/talk.mts` 的 `talk.prepare.complete` 不要求 `prepared_media` artifact。
- `scripts/workflows/plans/talk.mts::runTalkPlan` 在 `facts.canonical.usable` 时直接进入 Audit，跳过 Prepare。
- `quasi-status --kind talk` 的 facts 只有 `media/transcripts/canonical`，没有 prepared 事实，Skill 的 post-status 无法证明 prepared media。

实测案例：`vault/talks/maintenance-sig-dominic-brownell-repair-reuse-cars-20260910/` 有 usable `talk.md`，但没有 `recording.mp4` 及其 sidecar `.recording.mp4.quasi-compress.json`。

## 目标（四条，全部要做）

1. 视频类媒体（`mov|mp4|m4v|mkv|webm`）的 Talk 缺省 `prepare_media:true`；音频类缺省仍为 `false`；用户显式值优先。
2. `prepare_media:true` 时，exact `vault/talks/{slug}/recording.mp4` 及其可信 provenance sidecar 成为 Prepare 与 material 完成条件的一部分。
3. `prepare_media:true` 且 prepared media 缺失时，不因 canonical `talk.md` 已 usable 而短路。
4. 最终 material result 返回 `prepared_media` artifact，`quasi-status` 暴露 `facts.prepared`，Skill 的 post-status 能证明它存在且 usable。

## 硬约束

- 工作树已有别人未提交的改动，**不要碰、不要 stash/checkout/revert**：`scripts/audit/audit.py`、`scripts/audit/field_distribution.py`、`scripts/schemas/SPEC.md`、`scripts/schemas/body.py`、`scripts/typecheck/typecheck.py`、`tests/test_audit_readonly_contract.py`、`tests/test_schema_snapshot.py`、`tests/test_typecheck_contract.py`。
- 不手改 generated 文件：`scripts/workflows/artifact-contracts/generated.mjs`、其声明文件、`workflows/*.mjs`。改完 `.mts` 后跑 `npm run build:workflows` 重新生成。
- 不改 `CLAUDE.md`/`AGENTS.md`、版本号、`docs/CHANGELOG.md`（主进程做发布记账）。
- 不改 `scripts/transcribe/`、`scripts/talk/compress_media.py`（CLI 合同不动）。
- 不 commit。

## 改动清单

### 1. `scripts/workflows/contracts/talk.mts`

- 新增导出：

```ts
export const TALK_VIDEO_EXTENSIONS = ["mov", "mp4", "m4v", "mkv", "webm"] as const;
export const talkMediaIsVideo = (media: string): boolean =>
  TALK_VIDEO_EXTENSIONS.some((extension) => media.endsWith(`.${extension}`));
```

- `parseTalkOptions(value: unknown, media: string): TalkOptions | null`：缺省 `prepare_media = talkMediaIsVideo(media)`；显式值仍必须是 boolean，其余校验不变。
- `parseTalkRunInput`：先 `parseTalkSeed(raw.seed)`，为 null 直接 `invalid()`；再 `parseTalkOptions(raw.options, seed.identity.media)`。
- `TalkStatusFacts` 增加 `prepared: ArtifactObservation`。
- `parseTalkStatusObservation`：facts 的 `exactKeys` 改为 `["kind", "media", "prepared", "transcripts", "canonical"]`，并要求 `isArtifactObservation(facts.prepared) && facts.prepared.path === \`vault/talks/${observation.slug}/recording.mp4\``。

### 2. `scripts/workflows/contracts/topic.mts`

两处 `parseTalkOptions(value.options)`（约 385 行与 440 行）改为 `parseTalkOptions(value.options, seed.identity.media)`；seed 为 null 时先返回 null。

### 3. `scripts/workflows/shared/material-result.mts`

`ExactArtifactRef.role` union 增加 `"prepared_media"`。

### 4. `scripts/workflows/plans/talk.mts`

- `completedTalk(state, prepareMedia: boolean)`：artifacts 为

```ts
[
  { role: "canonical", path: `vault/talks/${state.slug}/talk.md` },
  ...(prepareMedia
    ? [{ role: "prepared_media", path: `vault/talks/${state.slug}/recording.mp4` }]
    : []),
]
```

  `auditTalk` 内两处 `completedTalk(state)` 改传 `input.options.prepare_media`。
- `runTalkPlan` 短路条件改为：

```ts
if (
  observation.facts.canonical.usable &&
  (!input.options.prepare_media || observation.facts.prepared.usable)
)
  return auditTalk(runtime, input, state, null);
```

  其余路径不变：canonical present 时 analyse 仍以 `mode:"repair"` 进入。

### 5. `scripts/workflows/operations/rows/talk.mts`

`talk.prepare` 的 `complete` 追加一个合取项：

```ts
(!context.prepareMedia ||
  receipt.artifacts.some(
    (row: any) => row.role === "prepared_media" && row.path === context.prepared,
  ))
```

### 6. `scripts/status/status.py`

`talk_status` 的 facts 在 `media` 之后加 `"prepared": talk_prepared_observation(root, slug)`。新增：

```python
PREPARED_MEDIA_MANIFEST_SCHEMA = "quasi.talk.prepared-media.manifest/0.1"
PREPARED_MEDIA_MANIFEST_KEYS = {
    "schema_version", "request_fingerprint", "input_sha256", "output_sha256", "size",
}


def talk_prepared_observation(root: Path, slug: str) -> dict[str, Any]:
    """Prepared media is usable only with a well-formed sidecar whose size matches."""
    prepared = artifact_path(root, "talk.prepare", "prepared", slug=slug)
    fact = artifact_observation(root, prepared)
    if not fact["usable"]:
        return fact
    sidecar = prepared.with_name(f".{prepared.name}.quasi-compress.json")
    usable = False
    try:
        if stat.S_ISREG(sidecar.lstat().st_mode):
            value = json.loads(sidecar.read_text(encoding="utf-8"))
            usable = (
                isinstance(value, dict)
                and set(value) == PREPARED_MEDIA_MANIFEST_KEYS
                and value["schema_version"] == PREPARED_MEDIA_MANIFEST_SCHEMA
                and isinstance(value["size"], int)
                and not isinstance(value["size"], bool)
                and value["size"] == prepared.stat().st_size
            )
    except (OSError, UnicodeError, ValueError):
        usable = False
    fact["usable"] = usable
    return fact
```

不重算 SHA-256（源文件可达 3 GB；深度校验属于 `quasi-transcribe observe`）。`quasi.status/0.2` 版本号不变：facts 形状按 kind 私有，producer 与 parser 同一版本发布。

### 7. `agents/transcribe-agent.md`

「工作方法」段加一段（中文）：request `prepare_media:true` 时，先用 `quasi-transcribe prepare-media` 产出或复用 exact `refs.prepared_media`（`observe` 已报告一致的 `prepared_path` 时可复用），再以该 prepared 路径作为 `quasi-transcribe run --media` 的转写来源；receipt `artifacts` 必须逐字包含 CLI receipt 的 `prepared_media` 行，缺失时不得返回 `complete`。`prepare_media:false`（音频或用户显式关闭）不压缩。

### 8. `skills/collect-material/SKILL.md`

- 「输入」Talk 行：`prepare_media` 省略时由 entry parser 按媒体类型决定（视频 true，音频 false）。
- 「执行流程」第 5 条 `complete` 段，Webpage 那句之后加：Talk 的 canonical returned ref 必须命中 `facts.canonical`；返回 `prepared_media` ref 时必须命中 `facts.prepared` 且 present、usable。
- 「常见成功产物」增加 `vault/talks/{slug}/recording.mp4`。

### 9. `docs/ARCHITECTURE.md`

约 170 行 `transcribe-agent` 那段加一句：视频 Talk 缺省准备 `vault/talks/{slug}/recording.mp4`，`prepare_media:true` 时它与 sidecar 是 Prepare 与 material 完成条件的一部分，`quasi-status` 以 `facts.prepared` 暴露。

### 10. 测试

- `tests/test_material_plans.py`
  - `talk_observation(*, transcripts=(), canonical=False, prepared=False, media_extension="mp3")`：media 列表按 `media_extension` 标 present/usable；facts 加 `"prepared": {"path": f"vault/talks/{slug}/recording.mp4", "present": prepared, "usable": prepared}`。
  - `canonical_talk_input(..., prepared=False, media_extension="mp3")`：identity 用 `deepcopy(TALK_IDENTITY)` 后把 `media` 改成 `sources/exact-talk.{media_extension}`。
  - `talk_prepare_complete(..., prepared=False)`：为 True 时 artifacts 追加 `{"role": "prepared_media", "path": "vault/talks/exact-talk/recording.mp4", "sha256": "9" * 64, "size": 500}`。
  - 新测试：
    - `test_talk_video_media_defaults_prepare_media_true`：mp4、无 canonical、outputs `[talk_prepare_complete("live", prepared=True), talk_analyse_complete(), audit_complete()]`；断言 prepare request `prepare_media is True`，result `complete`，`result["artifacts"]` 含 `{"role": "prepared_media", "path": "vault/talks/exact-talk/recording.mp4"}`。
    - `test_talk_video_prepare_without_prepared_artifact_is_incoherent`：mp4，prepare receipt 无 `prepared_media` 行 → calls 仅 `talk.prepare`，result terminal `blocked`；issue code 以 `scripts/workflows/shared/dispatch-prepared.mts` 对 `complete` 返回 false 的实际 code 为准。
    - `test_talk_usable_canonical_without_prepared_media_reenters_prepare`：mp4、`canonical=True`、`prepared=False`、options `{}` → calls `["talk.prepare", "talk.analyse", "talk.audit"]`，analyse request `mode == "repair"`，result `complete`。
    - `test_talk_usable_canonical_with_prepared_media_starts_at_audit`：mp4、`canonical=True`、`prepared=True` → calls `["talk.audit"]`，`complete`，artifacts 含 prepared_media。
    - `test_talk_video_explicit_prepare_media_false_skips_prepared_media`：mp4 + options `{"prepare_media": False}`、`canonical=True`、`prepared=False` → calls `["talk.audit"]`，artifacts 不含 prepared_media。
  - 现有 `test_talk_usable_canonical_starts_at_audit`（mp3）保持不变并继续通过。
- `tests/test_material_result.py`：talk fixture facts 加 `prepared`；foreign 例子把 `facts.prepared.path` 改成别的 slug，断言 parser 返回 None。
- `tests/test_status_cli.py`：现有 talk 测试加断言 `payload["facts"]["prepared"] == observation(f"vault/talks/{slug}/recording.mp4", present=False, usable=False)`；新测试覆盖三态：只有 `recording.mp4` → present True/usable False；`recording.mp4` + 合法 sidecar（`size` 等于文件大小）→ usable True；sidecar `size` 不匹配 → usable False。
- `tests/test_workflow_dispatch.py`：新测试 `talk.prepare` 在 `meta` 含 `"media": "sources/exact-talk.mp4", "prepareMedia": True` 时，无 `prepared_media` 行 → `report["result"]["kind"] == "incoherent_complete"`；含 `{"role": "prepared_media", "path": "vault/talks/exact-talk/recording.mp4", "sha256": "9" * 64, "size": 500}` → 与现有 complete 断言一致。可参照 `_dispatch_talk_prepare_artifacts` 写带 meta 参数的变体。
- `tests/test_topic_plan.py`：`talk_seed()` 显式 `prepare_media: False`，不改；fixture 通过 `test_material_plans.talk_observation` 自动带 `prepared`。

## 构建与验证

```bash
npm run build:workflows && npm run check:workflows
pytest tests/test_material_plans.py tests/test_material_result.py tests/test_status_cli.py \
  tests/test_workflow_dispatch.py tests/test_topic_plan.py tests/test_skill_orchestration.py \
  tests/test_dead_names.py tests/test_transcribe_cli.py tests/test_compress_media.py -q
cmp -s CLAUDE.md AGENTS.md && echo same
git status --short
```

完成后报告：改动文件列表、测试结果原文、是否有未按配方做的偏离及原因。
