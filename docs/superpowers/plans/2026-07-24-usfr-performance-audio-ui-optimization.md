# USFR 高保真故事板、音频与受限 UI 优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 USFR 七固定槽位、十二语义阶段、两次用户确认和最多两个 Seedance 生成段的前提下，完成双故事板连续性、一次性源内容时间轴、可审计音频/演唱、可选音乐上传和受限 UI 重建。

**Architecture:** 新能力全部作为既有阶段中的冻结合同或受限 StagePort 注入，不增加用户审批、完整视频二次分析或全局渲染。源视频的动态、ASR、OCR 和音乐事件只做一次，随后阶段只能读取带 SHA 的合同；按需工具由路由条件选择，默认快速路径仍是现有 FFmpeg/确定性实现。

**Tech Stack:** Python 3、pytest、JSON Schema、FFmpeg、Redis 临时 Job/对象存储、RunningHub Whisper/图像工作流、Youdao Seedance 2.0、现有 Remotion 适配器。

## Global Constraints

- `source_video` 始终必传；固定槽位仅为 7 个，`background_music` 只能放在 `extensions`。
- 保持两次用户确认：反解脚本、成对故事板；不得增加第三次确认。
- 保持最多两个 4–15 秒 Seedance 段；不向 Provider 提供源视频、opaque UI 或尾部视频。
- 不改变源 Cut 顺序、节奏、转场、CTA 和源音乐窗口；上传音乐禁止循环、拉伸、变速、变调、静音填充或模型替代。
- 仅 `final/{job_id}/result.mp4` 长期保留，其余制品由 Job TTL 清理。
- 工具条件满足且为当前片段最优解时自动启用；不满足条件时必须写入 `skipped` 原因且不触发额外推理/渲染。

---

### Task 1: 完成可选背景音乐入场合同

**Files:**
- Modify: `usfr-server/scripts/bind_input_slots.py`
- Modify: `usfr-server/schemas/input_slots.schema.json`
- Modify: `usfr-server/references/fixed-input-slot-contract.md`
- Modify: `usfr-server/SKILL.md`
- Modify: `usfr-server/tests/test_fixed_input_slot_contract.py`
- Modify: `usfr-server/tests/test_audio_backends.py`
- Modify: `usfr-server/server/audio_backends.py`

**Interfaces:**
- Consumes: `background_music: Path | upload completion | None`，七槽位输入和 `output_language`。
- Produces: `extensions.background_music`、`admission.enabled_extension_present`、`routes.background_music`。
- Invariant: `slot_order` 和 `slots` 中永远不能出现第八槽位；没有合规适配器时只能拒绝音乐执行，不能伪称“默认关闭上传功能”。

- [x] **Step 1: 写入并运行失败测试**

```python
def test_music_extension_is_admissible_without_an_eighth_slot():
    manifest = bind_slots({"source_video": source}, background_music=song)
    assert manifest["slot_order"] == list(SLOT_ORDER)
    assert "background_music" not in manifest["slots"]
    assert manifest["extensions"]["background_music"]["provider_route"] == "seedance_audio_reference"
```

Run: `python -B -m pytest tests/test_fixed_input_slot_contract.py -p no:cacheprovider -q`
Expected: FAIL before extension support exists.

- [x] **Step 2: 只实现固定槽位外的扩展归一化**

```python
manifest["extensions"] = {"background_music": extension}
manifest["routes"]["background_music"] = "seedance_audio_reference"
manifest["admission"]["enabled_extension_present"] = True
```

- [x] **Step 3: 校验 schema 和快速通道路由**

```python
language_only = output_language is not None and optional_count == 0 and extension is None
can_proceed = optional_count >= 1 or extension is not None or language_only
```

Run: `python -B -m pytest tests/test_fixed_input_slot_contract.py tests/test_server_intake_artifacts.py tests/test_api_upload_lifecycle.py -p no:cacheprovider -q`
Expected: PASS。

- [x] **Step 4: 用能力状态替代遗留“永久禁用”表述**

```python
def input_contract_v2_extensions(*, music_execution_available: bool) -> Mapping[str, Mapping[str, Any]]:
    return {"background_music": {"enabled": music_execution_available,
                                  "public_input": True,
                                  "required_capability": "background_music_execution/v1"}}
```

- [x] **Step 5: 更新操作合同并提交**

Run: `git diff --check && git add usfr-server && git commit -m "feat: admit background music as an input extension"`
Expected: 仅音乐输入合同、文档和测试进入该提交。

### Task 2: 冻结一次性源内容时间轴与按需说话人分配

**Files:**
- Create: `usfr-server/server/source_content_timeline.py`
- Create: `usfr-server/tests/test_source_content_timeline.py`
- Modify: `usfr-server/server/real_capabilities.py`
- Modify: `usfr-server/server/orchestrator.py`
- Modify: `usfr-server/server/production_ports.py`

**Interfaces:**
- Consumes: 已冻结的 source SHA、完整 Cut、独立 OCR interval、Whisper/ASR segments、音乐/节拍事件和可见人物/口型证据。
- Produces: `source_content_timeline/v1`，每条记录含 source 时间窗、内容类别、文字、证据 SHA、置信度、`speaker_assignment` 或 `PENDING_ASSIGNMENT`。
- Invariant: 只在有语音且多人/归属不确定的 Cut 运行分离；低置信度记录不能到达 Provider。

- [x] **Step 1: 写入时间轴归并的失败测试**

```python
def test_timeline_merges_cut_bound_ocr_asr_music_and_speaker_evidence_once():
    timeline = build_source_content_timeline(cuts=cuts, ocr_intervals=ocr, asr_segments=asr,
                                             music_events=music, speaker_evidence=speakers)
    assert timeline["analysis_passes"] == 1
    assert timeline["rows"][0]["speaker_assignment"]["status"] == "CONFIRMED"
```

Run: `python -B -m pytest tests/test_source_content_timeline.py -p no:cacheprovider -q`
Expected: FAIL because the module does not exist.

- [x] **Step 2: 实现纯合同构造器和 SHA 绑定**

```python
def build_source_content_timeline(*, source_video_sha256: str, source_duration_ms: int,
                                  cuts: Sequence[Mapping[str, Any]], ocr_intervals: Sequence[Mapping[str, Any]],
                                  asr_segments: Sequence[Mapping[str, Any]], music_events: Sequence[Mapping[str, Any]],
                                  speaker_evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # 只归并已存在证据；不读取媒体、不调用模型。
```

- [x] **Step 3: 实现按需说话人门禁**

```python
def speaker_assignment_for_line(line: Mapping[str, Any], visible_tracks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # 单一可见说话人 -> CONFIRMED；多人或置信度不足 -> PENDING_ASSIGNMENT。
```

Run: `python -B -m pytest tests/test_source_content_timeline.py -p no:cacheprovider -q`
Expected: PASS。

- [x] **Step 4: 在既有 dynamics/script 间发布并复用制品**

```python
context.publish_artifact(kind="source_content_timeline", payload=timeline)
# build_script 只 materialize 已发布 SHA；不得再次调用 ASR/OCR/VLM。
```

- [x] **Step 5: 跑端口回归并提交**

Run: `python -B -m pytest tests/test_real_media_ports.py tests/test_production_ports.py tests/test_source_content_timeline.py -p no:cacheprovider -q`
Expected: PASS。

### Task 3: 将用户确认的说话人/台词写入 Seedance-20 不可改写合同

**Files:**
- Modify: `usfr-server/scripts/line_contract.py`
- Modify: `usfr-server/server/performance_audio_contracts.py`
- Modify: `usfr-server/scripts/seedance_prompt_compiler.py`
- Modify: `usfr-server/tests/test_line_contract.py`
- Modify: `usfr-server/tests/test_performance_audio_contracts.py`
- Modify: `usfr-server/tests/test_seedance_prompt_compiler.py`

**Interfaces:**
- Consumes: 已确认脚本行、`source_content_timeline` SHA、角色、可见性、毫秒窗口、节拍和歌词状态。
- Produces: `line_contract` 与 `performance_line_contract` 的一对一绑定，供 Invocation A/B 使用。
- Invariant: `PENDING_ASSIGNMENT`、未确认歌词、跨 Cut/Segment 的行必须在 Invocation B 前失败。

- [x] **Step 1: 写入未确认说话人被阻止的失败测试**

```python
def test_compiler_rejects_pending_speaker_assignment():
    with pytest.raises(ValueError, match="PENDING_ASSIGNMENT"):
        compile_prompt(request_with_pending_assignment)
```

- [x] **Step 2: 扩展逐句合同字段并保持已有 spoken/sung/instrumental/inaudible 行为**

```python
line["speaker_assignment"] = {"status": "CONFIRMED", "speaker_id": "CHARACTER_A",
                               "confidence": 0.94, "evidence_sha256": evidence_sha}
```

- [x] **Step 3: 在 Invocation A、脚本修订和 Invocation B 重复验证同一 SHA**

Run: `python -B -m pytest tests/test_line_contract.py tests/test_performance_audio_contracts.py tests/test_seedance_prompt_compiler.py -p no:cacheprovider -q`
Expected: PASS。

- [x] **Step 4: 提交**

Run: `git add usfr-server && git commit -m "feat: bind approved speaker assignments to audio contracts"`

### Task 4: 接通音乐执行、最终音频替换和演唱 QA

**Files:**
- Modify: `backend/app/background_music_execution.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/app/usfr_commercial_deployment.py`
- Modify: `usfr-server/server/performance_audio_contracts.py`
- Modify: `backend/tests/test_background_music_execution.py`
- Modify: `backend/tests/test_replication_runtime.py`
- Modify: `backend/tests/test_usfr_commercial_deployment.py`

**Interfaces:**
- Consumes: `extensions.background_music`、源音乐时间窗、确认的 `performance_line_contract`、Youdao Audio 资产回执。
- Produces: `@Audio1` 受审计请求、演唱或 BGM 替换合同、上传音乐 SHA/片段 SHA/窗口/最终视频 SHA 的混音回执。
- Invariant: 最终音频来自上传文件的精确片段；无可验证歌词/歌手时只能 BGM 模式，绝不声称精准演唱。

- [x] **Step 1: 写入演唱/BGM 两模式及禁止变换的失败测试**

```python
def test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transform():
    receipt = execute_background_music(...)
    assert receipt["forbidden_operations"] == ["loop", "atempo", "stretch", "pitch_shift", "silence_padding"]
    assert receipt["uploaded_audio_sha256"] == uploaded_sha
```

- [x] **Step 2: 复用已有部署适配器，拒绝没有该适配器的商业任务**

```python
if is_background_music_manifest(manifest) and adapter is None:
    raise ContractError("BACKGROUND_MUSIC_EXECUTION_CAPABILITY_REQUIRED")
```

- [x] **Step 3: 将 verified singing 合同接到 Seedance-20 B，BGM 合同明确 `No lyric lip-sync`**

- [x] **Step 4: 跑商业/本地回归并提交**

Run: `cd backend; python -B -m pytest tests/test_background_music_execution.py tests/test_replication_runtime.py tests/test_usfr_commercial_deployment.py -p no:cacheprovider -q`
Expected: PASS。

### Task 5: 接通严格受限的 `remotion_react_ui` 适配器

**Files:**
- Modify: `usfr-server/scripts/hybrid_compositor.py`
- Modify: `usfr-server/server/production_ports.py`
- Modify: `usfr-server/server/real_capabilities.py`
- Modify: `usfr-server/tests/test_hybrid_compositor.py`
- Create: `usfr-server/tests/test_remotion_react_ui_activation.py`

**Interfaces:**
- Consumes: `generated_ui_demo`、目标 UI SHA、truth/render/source interval 合同 SHA、白名单 2.5D 动作和同案例基准回执。
- Produces: `remotion_react_ui` 或现有 FFmpeg/确定性 UI renderer 的单一选路决定。
- Invariant: 不安装或合并 Video ShotCraft；opaque/source UI、无证据 UI 和未基准的候选绝不进入 Remotion。

- [x] **Step 1: 写入阶段端口只接收完整 eligibility 合同的失败测试**

```python
def test_generated_ui_stage_uses_remotion_only_with_an_active_same_case_receipt():
    assert select_ui_renderer(eligible_contract, enabled_capability) == "remotion_react_ui"
    assert select_ui_renderer(contract_without_receipt, enabled_capability) == "ffmpeg"
```

- [x] **Step 2: 发布 source interval SHA 和运动白名单，复用现有 `choose_backend`**

- [x] **Step 3: 用黄金 UI 案例写入 OCR/layout/无黑帧/时长与耗时基准回执；缺失回执时回退**

Run: `python -B -m pytest tests/test_hybrid_compositor.py tests/test_backend_substitution_policy.py tests/test_remotion_react_ui_activation.py -p no:cacheprovider -q`
Expected: PASS。

### Task 6: 端到端回归、临时制品清理与完成审计

**Files:**
- Modify: `usfr-server/tests/test_cleanup_contract.py`
- Modify: `usfr-server/tests/test_object_lifecycle.py`
- Modify: `usfr-server/tests/test_cleanup_sweeper.py`
- Modify: `usfr-server/tests/test_bundle_runtime_closure.py`
- Modify: `backend/tests/test_background_music_local_mvp.py`
- Modify: `docs/superpowers/specs/2026-07-25-usfr-commercial-batch-optimization-goal.md`

**Interfaces:**
- Consumes: 任务 1–5 的冻结合同、运行时制品与最终结果。
- Produces: 需求逐项证据、仅保留 `final/{job_id}/result.mp4` 的清理验证。

- [ ] **Step 1: 为五项新增能力各加入“命中/跳过/失败关闭”回归用例**

- [x] **Step 2: 验证 TTL 清理不会移除 final，也不会永久保留 ASR/故事板/音乐片段/QC**

```python
assert store.list_prefix(f"temporary/{job_id}/") == []
assert store.head(f"final/{job_id}/result.mp4").sha256 == final_sha
```

- [x] **Step 3: 分组完整回归并记录实际结果**

> 2026-07-27 验证状态（非完成声明）：当前改动下，`backend/tests/test_background_music_execution.py` 与 `backend/tests/test_background_music_local_mvp.py` 为 64 passed；此前完整 `backend` 套件为 119 passed。`usfr-server` 的功能套件（明确排除三个会扫描工作目录缓存的打包契约文件）为 1262 passed / 1 skipped；核心 Provider/能力端口回归为 227 passed，故事板/时间轴/音频/UI/清理回归为 156 passed，本地控制台为 80 passed。`git diff --check` 已通过。官方脱敏 Provider 预检确认 RunningHub 与 Youdao/Seedance 配置均为 present，且未创建 Provider 任务。
>
> 尚未完成：工程目录仍有解释器生成的 `__pycache__`，三个打包契约测试会按设计失败；当前执行环境拒绝删除命令，因此需在具备删除权限的环境中清除这些已确认缓存后复跑。真实 Provider E2E 仍必须等待用户提供授权的源视频（≤30 秒）及至少一个替换素材；不得由 mock、预检或单元测试替代。

Run: `python -B -m pytest tests/test_storyboard_manifest.py tests/test_line_contract.py tests/test_performance_audio_contracts.py tests/test_seedance_prompt_compiler.py tests/test_hybrid_compositor.py tests/test_audio_backends.py -p no:cacheprovider -q`
Expected: PASS。

- [ ] **Step 4: 执行 `git diff --check`、清理测试缓存并提交最终回归结果**

Run: `git diff --check; git status --short`
Expected: 无未预期改动。
