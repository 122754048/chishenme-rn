# USFR Local Skill to Deployment Package Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在不破坏部署包既有 HTTP、OSS、远程素材导入、语言直通、TTS、对口型、路由优先、UI 开关和 Docker 部署能力的前提下，把本地 `universal-source-fidelity-replication` 的最新有效能力同步到部署包，并输出一个可回滚、可部署、可离线验收的新 ZIP。

**Architecture:** 不做目录覆盖。以部署包为主干，把本地 Skill 的新合同和实现按功能块移植到部署包，再通过“受保护能力回归测试 + 本地新版合同测试”双向验收。部署包专属适配器继续作为最终运行入口，本地文件只作为差异来源，不成为服务器运行依赖。

**Tech Stack:** Python 3.12、FastAPI、Redis、Docker Compose、MinIO/阿里云 OSS、FFmpeg、RunningHub AI App/Workflow/Standard Model API、pytest。

## Global Constraints

- 原始部署 ZIP 和已配置 `.env` 不得被覆盖。
- 不删除、不改名、不降级部署包已经接入的公共 HTTP API、OSS、远程 URL 下载、TTS、最终对口型、语言直通和 UI 开关能力。
- 不把本地 `server/`、`deployment/`、`SKILL.md` 或任何整目录直接覆盖到部署包。
- 不发起付费 RunningHub、GPT、Image2、Seedance、TTS 或对口型任务；发布前只做离线合同测试和无 Provider HTTP smoke。
- 用户层仍只有文字脚本文件和导演故事板 PNG 整组两个可编辑确认入口；内部替换控制图禁止出现在用户接口。
- `USFR_UI_REBUILD_ENABLED=false` 的默认行为保持不变；`ui_screenshot`、App Store/Google Play 链接仍始终触发目标产品分析，但不自动改变原 UI 操作片段；`ui_operation_video` 仍优先走剪辑替换。
- 部署包 `.env` 中所有已配置密钥和接入参数必须保持字节级不变；新增配置只写入 `.env.example` 和 Compose 变量映射，当前 `.env` 仅在明确需要时增加非密钥开关。
- 最终 QC 预算继续受现有不超过 60 秒的工程化规则约束，不因同步本地深度合同恢复反复 QC。
- 所有用户可见表面禁止出现模型名、供应商名、内部工具名、内部 Stage 名和内部流程说明。禁止词至少包括 `Image2`、`Seedance`、`RunningHub`、`GPT`、`Whisper`、`TTS`、`lip-sync`、`对口型工作流`、`Provider`、`ComfyUI`；该规则覆盖文字脚本 Markdown、导演故事板图片中的所有文字、公共 HTTP 响应、用户错误信息和最终交付元数据。内部日志和受访问控制的诊断记录可以保留真实技术信息。
- 只有 `source_video`、没有六个可选槽、没有有效 `background_music` 扩展、也没有有效 `output_language` 时，必须在创建正式 Job、远程素材导入、视频分析和任何付费调用之前返回 HTTP 422，错误码固定为 `MIN_ONE_OPTIONAL_INPUT_REQUIRED`。
- 新发布包不得包含历史生成媒体、历史任务目录、运行缓存、测试复制目录、旧 ZIP、Provider 返回文件或审计临时文件；长期结果仍只允许最终视频进入外部 OSS。

---

## 审计基线

### 已完成备份

- 原包：`C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2.zip`
- 备份：`C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2.pre-local-skill-sync-backup-2026-07-31.zip`
- 两者大小：`1,045,390` bytes
- SHA-256：`D289A90A0F070431892763BB65FA8BEF4E712390B62524013455282574D8A6DC`
- 结论：备份与原包完全一致，可直接回滚。

### 文件差异

- 本地有效文件：325
- 部署包有效文件：234
- 完全一致：134
- 同路径但内容不同：71
- 本地独有：120，其中绝大部分是测试；生产代码独有项主要是 `server/ffmpeg_encoding.py`
- 部署包独有：29，主要是简化 HTTP、OSS、远程素材导入、发布打包、路由基准和部署验证代码

### 已验证状态

- 部署包自身关键离线测试：`34 passed`
- 将本地最新合同测试放入部署包运行：`83 passed, 34 failed`，另有两个测试因部署包缺少新版符号而在收集阶段失败
- 本地最新性能测试放入部署包运行：`8 failed`
- 这些失败集中为下表中的功能差距，不代表 42 个独立故障。

## 功能差距表

| 能力 | 部署包现状 | 本地最新状态 | 同步判断 |
| --- | --- | --- | --- |
| 简化公共 HTTP API | 部署包独有并已接入 | 本地没有对应完整实现 | 完整保留 |
| URL 素材导入与阿里云 OSS 永久结果 | 部署包独有 | 本地没有 | 完整保留 |
| TTS、语言校验、最终对口型 | 部署包已形成独立 Stage | 本地 `packaged_stages.py` 不含这些 Stage | 完整保留，禁止覆盖 |
| 语言直通剪辑 | 部署包有 `LanguageOnlySpliceStage` | 本地没有该部署适配器 | 完整保留 |
| 路由优先与工具授权 | 部署包有 execution scope、工具 receipt、分析去重 | 本地版本较简化 | 完整保留 |
| UI 重建开关 | 部署包已接入默认关闭逻辑 | 本地合同也要求默认关闭 | 保留部署实现，仅补回归测试 |
| 两个用户确认入口 | 部署包公共 API 已实现并通过测试 | 本地 Skill 文档更严格 | 保留部署实现，同步合同文字和边界测试 |
| 导演故事板固定模板 | 部署包能读取模板 | 本地模板新增分页、版式和 SHA 约束 | 合并模板和运行时分页，不覆盖部署 Stage |
| 故事板分页 | 部署包仍按单页/旧模板运行 | 本地要求每页最多 4 Cut、最多 2 页 | 需要实现；本地当前主要是合同，部署端需补真正运行逻辑 |
| Seedance 多图绑定 | 部署包仍以单故事板和最多 4 图为主 | 本地支持最多 9 图、完整 binding v2 | 需要移植到部署适配器 |
| `@Video1` 来源隔离提示词 | 部署包没有强制常量和校验 | 本地有固定字面合同 | 需要同步并在提交前强制校验 |
| 可见文字载体路由 | 部署包把文字主要作为统一确定性层 | 本地区分场景实体文字、屏幕叠字和 UI 文字 | 需要增量合并 |
| 性能优化 | 部署包有 route-first，但缺少本地最新 8 项底层优化 | 本地已有实现和测试 | 逐项移植，不能删除部署包已有加速器 |
| RunningHub Whisper | 部署包把 AI App ID 调到 `/run/workflow/`，会返回 `workflow not exists` | 本地同样没有完整 AI App 类型抽象 | 增加兼容类型开关；其他 RunningHub 接入不变 |
| Bundle/Release manifest | 部署包有专属生成脚本 | 本地 manifest 不能直接覆盖部署包 | 使用部署包脚本重新生成 |
| 单原视频入口拦截 | 服务端反馈当前简化 HTTP 可以创建 source-only 任务 | 本地合同明确要求 source + change | P0 修复，API 与内部 intake 双层拒绝 |
| 用户可见技术信息 | 当前故事板/脚本/错误投影没有统一禁止模型和内部流程词 | 新增硬性商业化规则 | 增加统一净化器和发布拒绝门 |

## 受保护文件和能力

以下部署包文件不能由本地同名文件覆盖；只能通过小范围补丁调用新公共函数：

- `server/public_api_models.py`
- `server/public_errors.py`
- `server/public_fastapi_router.py`
- `server/public_idempotency.py`
- `server/public_job_projection.py`
- `server/public_script_approval.py`
- `server/aliyun_oss_final_store.py`
- `server/remote_media_import.py`
- `server/replacement_control_qc.py`
- `server/shared_frame_evidence.py`
- `server/source_evidence_bundle.py`
- `server/qc_escalation.py`
- `scripts/build_release_manifest.py`
- `scripts/package_release.py`
- `deployment/Dockerfile.app`
- `deployment/Dockerfile.base`
- `validation/e2e/public_http_driver.py`
- `validation/e2e/local_public_http_smoke.py`
- `server/packaged_stages.py` 中的 `ImportSourcesStage`、`LanguageOnlySpliceStage`、`TtsStage`、`TtsLanguageValidationStage`、`FinalLipSyncStage`
- `server/ephemeral_worker.py` 中的 execution scope、工具授权 receipt、全源分析去重 ledger 和部署能力检查

---

### Task 1: 建立不可回退的部署能力保护测试

**Files:**
- Create: `validation/test_local_skill_sync_protected_capabilities.py`
- Modify: none

**Interfaces:**
- Consumes: 当前部署包公共 API、Stage map、Compose 配置和 `.env` 非敏感变量名
- Produces: 同步过程中任何部署能力被删除时立即失败的离线测试

- [x] **Step 1: 写受保护能力测试**

```python
from pathlib import Path
import server.packaged_stages as stages


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_only_stages_remain_available():
    for name in (
        "ImportSourcesStage",
        "LanguageOnlySpliceStage",
        "TtsStage",
        "TtsLanguageValidationStage",
        "FinalLipSyncStage",
    ):
        assert hasattr(stages, name)


def test_public_http_and_oss_files_remain_packaged():
    for relative in (
        "server/public_fastapi_router.py",
        "server/public_job_projection.py",
        "server/aliyun_oss_final_store.py",
        "server/remote_media_import.py",
    ):
        assert (ROOT / relative).is_file()


def test_ui_rebuild_default_remains_disabled():
    compose = (ROOT / "deployment/docker-compose.yml").read_text(encoding="utf-8")
    assert "USFR_UI_REBUILD_ENABLED" in compose
    assert "${USFR_UI_REBUILD_ENABLED:-false}" in compose
```

- [x] **Step 2: 运行当前部署包基线测试**

Run:

```powershell
python -m pytest -q validation/test_public_review_contract.py validation/test_language_only_pipeline.py validation/test_task7_8_10_contracts.py validation/test_local_skill_sync_protected_capabilities.py
```

Expected: 全部通过。

- [x] **Step 3: 记录 `.env` 和受保护文件 SHA 基线**

Run:

```powershell
Get-FileHash .env, server/public_fastapi_router.py, server/aliyun_oss_final_store.py, server/remote_media_import.py -Algorithm SHA256
```

Expected: 生成内部基线记录；报告中不得打印 `.env` 内容。

---

### Task 1A: 增加 source-only 创建拒绝门

**Files:**
- Modify: `server/public_api_models.py`
- Modify: `server/public_fastapi_router.py`
- Modify: `server/remote_media_import.py`
- Modify: `server/intake.py`
- Modify: `scripts/bind_input_slots.py`
- Create: `validation/test_source_only_admission_gate.py`

**Interfaces:**
- Consumes: 简化 HTTP 创建请求中的 `source_video`、六个可选素材、`background_music` 和 `output_language`
- Produces: 创建前确定性 admission decision；source-only 请求返回 HTTP 422

- [x] **Step 1: 写公共 API 失败测试**

```python
def test_source_only_request_is_rejected_before_job_creation(client, job_store):
    response = client.post(
        "/api/v1/jobs",
        json={"source_video": "https://example.test/source.mp4"},
        headers={"Idempotency-Key": "source-only-rejected"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MIN_ONE_OPTIONAL_INPUT_REQUIRED"
    assert job_store.count_jobs() == 0
```

- [x] **Step 2: 写允许路线测试**

分别验证以下请求可以越过 admission gate：

```text
source_video + new_model_image
source_video + new_product_image
source_video + ui_screenshot
source_video + app_store_url
source_video + ui_operation_video
source_video + tail_video
source_video + background_music
source_video + output_language
```

- [x] **Step 3: 在远程下载前执行轻量判断**

公共 API 只判断是否存在至少一个允许的 change 字段，不下载 URL、不探测 MIME、不创建 Job。进入内部 intake 后再次使用 `bind_input_slots.py` 验证类型、完成状态、SHA 和语言枚举，防止绕过 HTTP 直接调用服务。

- [x] **Step 4: 运行 admission 测试**

Run:

```powershell
python -m pytest -q validation/test_source_only_admission_gate.py validation/test_public_review_contract.py
```

Expected: source-only 被 422 拒绝，八类有效 change 路线仍可进入下一阶段。

---

### Task 1B: 增加用户可见技术信息零泄漏门

**Files:**
- Create: `server/public_content_policy.py`
- Modify: `server/user_script_document.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/public_job_projection.py`
- Modify: `server/public_errors.py`
- Modify: `server/public_fastapi_router.py`
- Modify: `bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md`
- Create: `validation/test_public_model_name_redaction.py`

**Interfaces:**
- Consumes: 即将发布给用户的 Markdown、故事板文字字段、公共 JSON、错误 message 和 artifact metadata
- Produces: 无模型名、供应商名和内部流程词的商业化用户内容；检测到禁词时发布失败或转换为业务语言

- [x] **Step 1: 写用户表面禁词测试**

```python
import pytest
from server.public_content_policy import assert_public_content_safe


@pytest.mark.parametrize("value", [
    "Use Image2 to generate the board",
    "Seedance video generation",
    "RunningHub provider task",
    "GPT analysis",
    "Whisper ASR",
    "TTS workflow",
    "final lip-sync workflow",
    "ComfyUI node 12",
])
def test_public_content_rejects_internal_model_and_workflow_names(value):
    with pytest.raises(ValueError):
        assert_public_content_safe(value)
```

- [x] **Step 2: 实现统一发布检查器**

```python
PUBLIC_FORBIDDEN_TERMS = (
    "image2", "seedance", "runninghub", "gpt", "whisper",
    "tts", "lip-sync", "comfyui", "provider", "workflow node",
    "对口型工作流", "生图工作流", "视频生成模型",
)


def assert_public_content_safe(value: object) -> None:
    text = canonical_public_text(value).casefold()
    matched = [term for term in PUBLIC_FORBIDDEN_TERMS if term in text]
    if matched:
        raise PublicContentPolicyError("public artifact contains internal implementation terminology")
```

错误不得把命中的具体内部词返回用户，只写入受保护日志。

- [x] **Step 3: 把内部词替换成用户业务语言**

```text
Image2 / 生图模型 → 视觉生成
Seedance / 视频模型 → 视频制作
TTS → 配音
lip-sync / 对口型工作流 → 口型同步
Whisper / ASR → 语音识别
Provider task → 制作任务
内部 Stage → 当前处理步骤
```

故事板固定骨架中的制作说明只能写镜头、人物、产品、动作、环境、灯光、声音和画面信息，不得写使用了哪个模型、API 或内部流程。

- [x] **Step 4: 在四个发布边界执行拒绝门**

1. 发布 `analysis/reverse_storyboard_script.md` 前；
2. 将导演故事板 prompt 发送给视觉生成服务前，检查所有允许显示的文字字段；
3. 公共 Job projection 返回 JSON 前；
4. 公共错误响应返回用户前。

- [x] **Step 5: 运行零泄漏测试**

Run:

```powershell
python -m pytest -q validation/test_public_model_name_redaction.py validation/test_public_review_contract.py
```

Expected: 用户表面零命中；内部日志仍能保存原始 Provider 诊断。

---

### Task 2: 合并两步确认合同和导演故事板分页

**Files:**
- Modify: `SKILL.md`
- Modify: `bundled-skills/seedance-storyboard-replication/SKILL.md`
- Modify: `bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md`
- Modify: `server/packaged_stages.py`
- Modify: `server/review_models.py`
- Modify: `server/public_job_projection.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `schemas/storyboard_revision.schema.json`
- Create: `validation/test_storyboard_pagination_runtime.py`

**Interfaces:**
- Consumes: `StoryboardStage` 当前模板加载、Image2、artifact publication 和公共审核投影
- Produces: `StoryboardPagePlan`, 支持一个 Segment 的 1-2 个 PNG 页面，每页最多 4 Cut；公共 API 仍一次返回和确认完整集合

- [x] **Step 1: 写分页运行时失败测试**

```python
from server.packaged_stages import _partition_storyboard_cuts


def test_seven_cuts_are_partitioned_three_plus_four():
    pages = _partition_storyboard_cuts([f"C{i:02d}" for i in range(1, 8)])
    assert pages == [
        ["C01", "C02", "C03"],
        ["C04", "C05", "C06", "C07"],
    ]


def test_more_than_eight_cuts_fail_before_image2():
    try:
        _partition_storyboard_cuts([f"C{i:02d}" for i in range(1, 10)])
    except Exception as exc:
        assert "at most two pages" in str(exc)
    else:
        raise AssertionError("expected pagination rejection")
```

- [x] **Step 2: 增加确定性分页函数**

```python
def _partition_storyboard_cuts(cut_ids: Sequence[str]) -> list[list[str]]:
    values = [str(value) for value in cut_ids]
    if not values:
        raise ReplicationError("CONTRACT_INVALID", "director storyboard requires at least one Cut")
    if len(values) <= 4:
        return [values]
    if len(values) <= 8:
        split = len(values) - 4
        return [values[:split], values[split:]]
    raise ReplicationError(
        "CONTRACT_INVALID",
        "director storyboard supports at most two pages of four Cuts",
    )
```

- [x] **Step 3: 合并本地模板占位符和强制骨架**

模板必须增加并由 `StoryboardStage` 填满：

```text
{{BOARD_PAGE_INDEX}}
{{BOARD_PAGE_COUNT}}
{{PAGE_CUT_RANGE}}
```

生成前检查所有 `{{...}}` 均已消失；模板 SHA 同时写入 Image2 request、layout receipt、storyboard metadata 和 Revision manifest。

- [x] **Step 4: 保持一页旧命名，增加两页兼容命名**

```text
单页：storyboards/segment_01_v1.png
分页：storyboards/segment_01_v1_page_01.png
      storyboards/segment_01_v1_page_02.png
```

公共投影同时接受两种形式；同一 revision 的所有页面返回一个 `approval_scope=all_segments_together` 集合。

- [x] **Step 5: 保留部署包已有审核 metadata**

不得删除 `RevisionManifest` 和 `StoryboardCutRef` 中现有字段：

```python
artifact_id: str | None
logical_name: str | None
cut_ids: tuple[str, ...]
user_artifact_id: str | None
user_artifact_object_key: str | None
user_artifact_sha256: str | None
presentation: str | None
approval_scope: str | None
text_only_substitute_forbidden: bool | None
```

- [x] **Step 6: 运行故事板测试**

Run:

```powershell
python -m pytest -q validation/test_public_review_contract.py validation/test_storyboard_template_binding.py validation/test_storyboard_pagination_runtime.py
```

Expected: 全部通过，且替换控制图仍不会出现在公共审核响应中。

---

### Task 3: 同步 Seedance 最多九图的完整引用绑定

**Files:**
- Modify: `server/runninghub_standard_contract.py`
- Modify: `server/packaged_stages.py`
- Modify: `bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
- Modify: `scripts/seedance_prompt_compiler.py`
- Modify: `references/universal-source-fidelity-contract.md`
- Create: `validation/test_multimodal_reference_binding_v2.py`

**Interfaces:**
- Consumes: 已批准故事板页面、固定槽目标图片、Provider 公网 URL 和 SHA-256
- Produces: `usfr-multimodal-reference-binding/v2`、binding SHA、`seedance-final-reference-lineage/v2`

- [x] **Step 1: 移植并测试三个本地公共合同**

```python
SOURCE_VIDEO_PROMPT_CONTRACT: str

def image_reference_binding_sha256(binding: Mapping[str, object]) -> str: ...

def validate_image_reference_binding(
    payload: Mapping[str, object],
    binding: Mapping[str, object] | None,
) -> None: ...
```

测试必须覆盖：1-9 张图、每图 URL/SHA/role/artifact/Cut scope/purpose 完整、页面连续、审批集合一致、禁止 execution carrier、`uploaded_tags == binding_tags == prompt_tags`。

- [x] **Step 2: 在部署版 `SeedancePromptStage` 内建立连续角色顺序**

```text
新模特（存在时）
→ 产品或 App 证据（存在时）
→ 已确认导演故事板全部页面
→ 明确 Cut 范围的附加证据
```

缺失角色不得放空白占位图；`@Video1` 和 `@Audio1` 不占图片序号。

- [x] **Step 3: 在部署版 `SeedanceAuditStage` 生成 binding v2**

保留部署包现有 Standard Model URL、上传器、背景音乐和 TTS/对口型数据；只替换图片引用 sidecar 的构建方式。`video_reference_binding` 改为绑定完整 `image_reference_binding_sha256`，不再只绑定一个 `storyboard_url`。

- [x] **Step 4: 强制 `@Video1` 来源隔离文字**

最终 prompt 必须包含本地 Skill 的固定 `SOURCE_VIDEO_PROMPT_CONTRACT`，并在 dry-run 和付费提交边界各验证一次。

- [x] **Step 5: 同步已确认唱歌冲突检查**

把本地 `_reject_verified_singing_conflicts()` 合并到编译器，确保已确认歌词、人物分配、节拍和 `@Audio1` 不被后续自由 prompt 覆盖；部署包现有 TTS 和最终对口型 Stage 保持不变。

- [x] **Step 6: 运行引用绑定测试**

Run:

```powershell
python -m pytest -q validation/test_multimodal_reference_binding_v2.py validation/test_task7_8_10_contracts.py
```

Expected: 全部通过，不创建 Provider 任务。

---

### Task 4: 同步可见文字的三路载体合同

**Files:**
- Modify: `server/visible_text_contract.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Modify: `references/universal-source-fidelity-contract.md`
- Create: `validation/test_visible_text_carrier_routes.py`

**Interfaces:**
- Consumes: 用户确认的 `visible_text_locks`
- Produces: `generation_surface`、`deterministic_overlay`、`deterministic_ui` 三组稳定路由

- [x] **Step 1: 写三路测试**

```python
from server.visible_text_contract import visible_text_render_route


def test_packaging_text_stays_on_physical_carrier():
    assert visible_text_render_route({
        "text_id": "t1",
        "cut_ids": ["C01"],
        "start_ms": 0,
        "end_ms": 1000,
        "kind": "packaging_text",
        "disposition": "replace",
        "text": "NEW",
        "placement": {
            "carrier_id": "box",
            "surface_relation": "front face",
            "motion_behavior": "moves with box",
        },
    }) == "generation_surface"
```

- [x] **Step 2: 移植本地路由函数**

```python
def visible_text_render_route(lock: Mapping[str, Any]) -> str: ...

def split_visible_text_locks_by_render_route(
    locks: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]: ...
```

- [x] **Step 3: 合并到故事板、Seedance 和 QC**

- `generation_surface`：进入替换控制图、导演故事板和 Seedance Cut prompt。
- `deterministic_overlay`：禁止 Image2/Seedance 生成字形，继续走现有 overlay renderer。
- `deterministic_ui`：继续走现有 UI renderer/OCR，不进入 Seedance。
- 不改部署包已有用户脚本文件结构和审核接口。

- [x] **Step 4: 运行测试**

Run:

```powershell
python -m pytest -q validation/test_visible_text_carrier_routes.py validation/test_public_review_contract.py
```

Expected: 全部通过。

---

### Task 5: 移植本地八项性能优化，同时保留 route-first

**Files:**
- Create: `server/ffmpeg_encoding.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/timeline_renderer.py`
- Modify: `bundled-skills/analyze-reference-video-dynamics/scripts/probe_video.py`
- Modify: `bundled-skills/seedance-storyboard-replication/scripts/concat_videos.py`
- Modify: `.env.example`
- Modify: `deployment/docker-compose.yml`
- Create: `validation/test_local_performance_sync.py`

**Interfaces:**
- Consumes: 当前 route-first 结果、FFmpeg、最多两个独立 Provider Segment
- Produces: 更少解码、合并 QC 扫描、并行独立 I/O、可选 NVENC，不改变输出合同

- [x] **Step 1: 移植性能测试**

覆盖以下八项：

1. UI 帧一次 pre-seek raw decode 后本地编码 PNG；
2. 音频窗口粗 seek + 细 seek；
3. 黑帧、冻结和音频 ebur128 使用同一个 FFmpeg 输入；
4. Provider polling 使用 `3/5/8/12/15` 秒退避；
5. 两个相互独立的 Provider 操作最多 2 worker 并行；
6. 场景检测先缩放至宽 160；
7. `USFR_FFMPEG_ENCODER=libx264|h264_nvenc`；
8. `USFR_FFMPEG_THREADS=1..64`。

- [x] **Step 2: 增加统一编码参数模块**

```python
def video_encoder_args() -> list[str]:
    encoder = os.environ.get("USFR_FFMPEG_ENCODER", "libx264").strip() or "libx264"
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", *_threads_args()]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0", *_threads_args()]
    raise FfmpegEncodingConfigurationError(
        "USFR_FFMPEG_ENCODER must be libx264 or h264_nvenc"
    )
```

- [x] **Step 3: 只替换本地最新已经覆盖的编码路径**

先接入 `packaged_stages.py`、`timeline_renderer.py` 和 `concat_videos.py`。TTS、最终对口型、overlay、audio mixer 的独立编码命令暂不做全局机械替换，避免改变已验证的音视频边界。

- [x] **Step 4: 保留部署包现有 route-first 和 QC 60 秒预算**

不得删除：execution scope、tool receipts、analysis ledger、`qc_budget_seconds`、路由基准阈值及已有短路逻辑。

- [x] **Step 5: 运行性能测试**

Run:

```powershell
python -m pytest -q validation/test_local_performance_sync.py validation/performance/route_first_benchmark.py
```

Expected: 离线合同测试全部通过；不执行付费 Provider。

---

### Task 6: 修复 Whisper AI App/Workflow 类型错配

**Files:**
- Modify: `server/runninghub_workflows.py`
- Modify: `server/packaged_ports.py`
- Modify: `.env.example`
- Modify: `deployment/docker-compose.yml`
- Modify: `deployment/中文部署配置手册.md`
- Create: `validation/test_runninghub_whisper_endpoint_type.py`

**Interfaces:**
- Consumes: `RUNNINGHUB_WHISPER_ENDPOINT_TYPE`、当前工作流/AI App ID、节点和字段
- Produces: 正确的 `/run/ai-app/{id}` 或 `/run/workflow/{id}` 地址

- [x] **Step 1: 写端点选择测试**

```python
def test_whisper_ai_app_uses_ai_app_endpoint(fake_transport):
    client = RunningHubWorkflowClient(
        api_key="x" * 32,
        base_url="https://www.runninghub.ai",
        transport=fake_transport,
    )
    client.run_whisper(
        audio_path=fixture_path,
        workflow_id="2080170949061038081",
        input_node_id="1",
        input_field="video",
        endpoint_type="ai-app",
    )
    assert fake_transport.urls[0].endswith(
        "/openapi/v2/run/ai-app/2080170949061038081"
    )
```

- [x] **Step 2: 增加严格端点类型**

```python
if endpoint_type == "ai-app":
    submit_url = f"{self.base_url}/openapi/v2/run/ai-app/{workflow_id}"
elif endpoint_type == "workflow":
    submit_url = f"{self.base_url}/openapi/v2/run/workflow/{workflow_id}"
else:
    raise RunningHubWorkflowError(
        "RUNNINGHUB_WHISPER_ENDPOINT_TYPE must be ai-app or workflow"
    )
```

- [x] **Step 3: 保持其他 RunningHub 接入不变**

Image2、TTS、最终对口型和普通 ComfyUI 工作流仍走原有 `/run/workflow/`；Seedance Standard Model 仍走当前独立端点。

- [x] **Step 4: 修正明确失败分类**

当响应已经包含 `errorMessage="workflow not exists"` 等确定失败时，在 `_checked_response()` 中直接抛出 Provider failure；只有响应确实可能已经创建付费任务但没有 task ID 时才保留 `PROVIDER_AMBIGUOUS`。

- [x] **Step 5: 更新非密钥配置**

```env
RUNNINGHUB_WHISPER_ENDPOINT_TYPE=ai-app
```

当前配置 `2080170949061038081 / node 1 / video` 保持不变。

---

### Task 7: 合并清单、依赖和部署配置

**Files:**
- Modify: `references/runtime_skill_manifest.json`
- Regenerate: `references/bundle_manifest.json`
- Modify: `references/dependency-map.md`
- Modify: `.env.example`
- Modify: `deployment/docker-compose.yml`
- Modify: `deployment/requirements.lock` only if imports require an existing absent dependency

**Interfaces:**
- Consumes: 完成同步后的实际文件字节
- Produces: 与最终 ZIP 完全一致的 runtime/bundle manifest

- [x] **Step 1: 校验没有工作站路径**

Run:

```powershell
rg -n "C:\\Users|\.codex\\skills|\.codex/skills" . --glob '!docs/**' --glob '!validation/**'
```

Expected: 生产文件零命中。

- [x] **Step 2: 使用部署包自己的脚本重建清单**

Run:

```powershell
python scripts/build_release_manifest.py
python scripts/verify_bundle.py
```

Expected: manifest 与实际文件 SHA 一致。

- [x] **Step 3: 验证 `.env` 没有被改变**

Run:

```powershell
Get-FileHash .env -Algorithm SHA256
```

Expected: 与 Task 1 基线完全一致；如果只增加 `RUNNINGHUB_WHISPER_ENDPOINT_TYPE`，必须单独记录旧值不存在、新值为 `ai-app`，其他行保持一致。

- [x] **Step 4: 验证 Compose 展开**

Run:

```powershell
docker compose -f deployment/docker-compose.yml config --quiet
```

Expected: exit code 0。

---

### Task 8: 离线回归、HTTP smoke 和重新打包

**Files:**
- Modify: none
- Output: `C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2-local-skill-synced-v3.zip`
- Output: `C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2-local-skill-synced-v3.sha256.txt`

**Interfaces:**
- Consumes: 已同步工作目录
- Produces: 可部署 ZIP、SHA 文件和验证报告

- [x] **Step 1: 运行部署包原有定向测试**

Run:

```powershell
python -m pytest -q validation/test_public_review_contract.py validation/test_storyboard_template_binding.py validation/test_control_sheet_latest_sync.py validation/test_language_only_pipeline.py validation/test_task7_8_10_contracts.py
```

Expected: 原有 34 项全部继续通过。

- [x] **Step 2: 运行新增同步测试**

Run:

```powershell
python -m pytest -q validation/test_local_skill_sync_protected_capabilities.py validation/test_storyboard_pagination_runtime.py validation/test_multimodal_reference_binding_v2.py validation/test_visible_text_carrier_routes.py validation/test_local_performance_sync.py validation/test_runninghub_whisper_endpoint_type.py
```

Expected: 全部通过。

- [x] **Step 3: 运行无 Provider HTTP smoke**

Run:

```powershell
python validation/e2e/local_public_http_smoke.py --no-provider
```

Expected: 创建任务、URL 导入模拟、脚本下载/批准、故事板整组投影/批准和结果查询接口均成功；不得联系真实 RunningHub。

- [x] **Step 4: 校验 ZIP 内容轻量化**

禁止打包：

```text
__pycache__/
.pytest_cache/
sync_audit_tests/
*.pyc
运行时临时媒体
旧 ZIP
审计解压目录
```

同时删除新构建目录中的历史生成目录或文件模式：

```text
runtime_uploads/
runs/
outputs/
generated/
temporary/
final/（仅构建残留；不影响外部 OSS 正式结果）
*.mp4
*.mov
*.wav
*.mp3
*.flac
历史 task/status/request/response 媒体结果
```

删除前必须先打印匹配文件的解析后绝对路径，并验证它们全部位于新构建目录内；不得删除源 ZIP、备份 ZIP、外部 OSS 或用户其他工程文件。

部署包保留必要的 `validation/` 发布烟测，但不复制本地完整 100+ 单元测试集。

- [x] **Step 5: 使用部署包发布脚本生成新 ZIP**

Run:

```powershell
python scripts/package_release.py --output "C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2-local-skill-synced-v3.zip"
Get-FileHash "C:/Users/zhaocx04/Documents/我的POPO/usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2-local-skill-synced-v3.zip" -Algorithm SHA256
```

Expected: ZIP 非空、可解压、顶层结构完整，并生成对应 SHA 文件。

---

### Task 9: 编写中文服务端维护与替换手册

**Files:**
- Create: `deployment/中文服务端更新维护手册.md`
- Include in release ZIP: `deployment/中文服务端更新维护手册.md`

**Interfaces:**
- Consumes: 旧版本部署目录、新 ZIP、现有 `.env`、Docker Compose、Redis、MinIO/OSS
- Produces: Java/运维人员无需理解 Python 业务代码也能完成的升级、验证和回滚步骤

- [x] **Step 1: 写升级前检查清单**

必须说明：记录旧版本 SHA、备份整个部署目录、单独备份 `.env`、确认 OSS 最终文件、检查当前运行任务、禁止执行 `docker compose down -v`。

- [x] **Step 2: 写停机与替换步骤**

明确区分：

```text
必须保留：.env、外部 OSS、Redis/MinIO volume、反向代理配置
需要替换：server/、scripts/、bundled-skills/、runtime-skills/、references/、schemas/、deployment/ 内代码和镜像定义
需要删除：旧 __pycache__、.pytest_cache、历史临时媒体、旧容器镜像缓存（可选）
```

- [x] **Step 3: 写 Docker 重建命令**

```bash
docker compose -f deployment/docker-compose.yml config
docker compose -f deployment/docker-compose.yml build --no-cache api worker sweeper
docker compose -f deployment/docker-compose.yml up -d api worker sweeper redis minio
docker compose -f deployment/docker-compose.yml ps
docker compose -f deployment/docker-compose.yml logs --tail=200 api worker sweeper
```

- [x] **Step 4: 写升级后验证**

覆盖 `/healthz`、`/readyz`、source-only 422、有效 URL 创建、脚本文件下载、故事板整组确认、最终结果 URL、Whisper AI App 配置和公开内容禁词检查。

- [x] **Step 5: 写回滚步骤**

回滚必须使用同步前备份目录和原 `.env`，重建旧镜像；不得删除 Redis/MinIO volume，不得删除外部 OSS。

- [x] **Step 6: 写常见错误表**

至少包含：`.env` 未加载、`workflow not exists`、AI App/Workflow 类型错误、source-only 被 422 拒绝、旧 Idempotency-Key 返回旧任务、容器仍使用旧镜像、OSS 权限错误、Redis/MinIO readiness 失败。

## 执行后的验收标准

1. 旧部署包和备份包保持不变。
2. 新 ZIP 可以独立部署，不读取本地 `.codex/skills`。
3. 公共 HTTP 入参/出参没有恢复成复杂内部合同。
4. OSS 永久结果、URL 导入、TTS、最终对口型、语言直通、UI 开关均保留。
5. 故事板真正按模板和分页运行，而不是只更新文档。
6. Seedance 接收全部已批准故事板页和目标图，最多 9 张，并有完整 SHA/角色/Cut scope 绑定。
7. 场景实体文字、叠字和 UI 文字走各自正确的生成或确定性渲染链路。
8. 本地八项性能优化生效，route-first 和 QC 60 秒上限不回退。
9. Whisper AI App ID 不再错误调用 `/run/workflow/`。
10. 不执行真实付费 API 也能完成全部合同、Compose 和 HTTP smoke 验证。
11. source-only 请求在任何 Job 或远程导入创建前返回 `MIN_ONE_OPTIONAL_INPUT_REQUIRED`。
12. 用户脚本、导演故事板、公共 API 和用户错误中不出现任何模型名、供应商名或内部流程词。
13. 新 ZIP 内不包含历史生成文件、运行缓存或审计临时文件。

## 明确不做

- 不把本地完整测试目录打入生产 ZIP。
- 不把本地 `server/packaged_stages.py` 覆盖部署版本。
- 不删除部署包专属文件以追求目录一致。
- 不切换 Java 重写。
- 不改变公共 API 设计。
- 不改变用户体系、计费、数据库等产品架构。
- 不在计划批准前修改原部署 ZIP 或开始同步实现。

## 2026-07-31 最终执行记录

- 状态：已完成并重新打包。
- 完整离线测试：`105 passed`。
- 无供应商 HTTP 冒烟：创建、查询、鉴权、幂等、文字脚本确认、故事板整组确认和可播放结果全部通过。
- source-only 请求：在创建 Job、下载素材、分析和付费调用前返回 HTTP 422，错误码 `MIN_ONE_OPTIONAL_INPUT_REQUIRED`。
- 发布包检查：246 个文件；维护手册、Skill、Compose 和服务代码完整；缓存、`.env`、密钥、历史音视频和临时媒体为 0。
- 最终 ZIP SHA-256：`b17f59c8529364c98f7fe786eecea0a82428539560a06e1bd6e1382745686d56`。
- 构建机未安装 Docker，因此未在本机执行容器启动；发布指纹明确记录 `docker_status=not_available_on_build_host`。服务端按中文维护手册执行 `docker compose config --quiet`、重建、`/healthz`、`/readyz` 和 HTTP 验证。
- 未调用任何真实付费接口。
