# USFR 路由先行分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在任何 VLM、ASR、OCR、App Store、故事板或视频生成调用前，先按固定输入确定最小分析范围；不命中的工具不启动，不确定时只升级到所需的最小证据。

**Architecture:** 新增纯本地、零 Provider 调用的 `analysis_scope`。它读取已冻结的七槽位、`background_music`、`output_language` 和默认路由，写入既有阶段计划并注入 `EphemeralStageContext`。动态分析、App Store 解析和 UI 渲染只读取该范围与 Stage 4 的真实区间；十二语义阶段、两次审批、Provider 审计和最终 QC 不变。

**Tech Stack:** Python 3、pytest、现有 Redis 临时 Job、FFmpeg、VLM/ASR/OCR StagePort。

## Global Constraints

- 不新增公开输入、审批、语义阶段或 Provider 任务。
- 路由本身不得调用 Provider、VLM、ASR、OCR、网页抓取、故事板或 Seedance。
- `skipped` 仅代表该路线绝不消费该工具；`deferred` 必须等待 Stage 4 证明区间需要该能力；来源不明或冲突必须升级证据，不能猜测跳过。
- 已命中的生成区间仍保留完整源证据、Seedance-20 编译/审计和最终 QC。
- `source_ui_keep`、`opaque_ui_demo` 与尾部视频不得 OCR、重绘、语义改写或送入生成模型。

---

### Task 1: 固定输入的预路由合同

**Files:**

- Create: `usfr-server/server/analysis_scope.py`
- Test: `usfr-server/tests/test_analysis_scope.py`

**Interfaces:**

- Produces: `build_analysis_scope(manifest) -> dict[str, Any]`
- Output: `contract`, `route_family`, `semantic_pass`, `tools`, `escalation_policy`, `scope_sha256`

- [x] **Step 1: 写入失败测试并验证**

```powershell
python -B -m pytest tests/test_analysis_scope.py -q -p no:cacheprovider
```

预期初始失败：`ModuleNotFoundError: server.analysis_scope`。

- [x] **Step 2: 以固定槽位生成最小范围**

```python
scope = build_analysis_scope(manifest)
assert scope["tools"]["app_store_evidence"]["status"] in {"skipped", "deferred"}
```

模型替换只聚焦人物/镜头/动作/连续性；App UI 只等待真实 `generated_ui_demo`；语言单改只保留时间戳 ASR；不透明拼接跳过语义 VLM 与 ASR；上传音乐只启用 Audio1 对齐，源语音按风险延后。

- [x] **Step 3: 验证**

```powershell
python -B -m pytest tests/test_analysis_scope.py -q -p no:cacheprovider
```

### Task 2: 将范围传入既有工作流和 VLM

**Files:**

- Modify: `usfr-server/server/orchestrator.py`
- Modify: `usfr-server/server/ephemeral_worker.py`
- Modify: `usfr-server/server/real_capabilities.py`
- Modify: `usfr-server/server/vision_backends.py`
- Test: `usfr-server/tests/test_ephemeral_runtime.py`
- Test: `usfr-server/tests/test_real_capabilities.py`
- Test: `usfr-server/tests/test_vision_backends.py`

**Interfaces:**

- `build_stage_plan(...)["analysis_scope"]` carries the immutable decision.
- `EphemeralStageContext.analysis_scope` exposes the same decision to every StagePort.
- Scope-aware VLM receives `analysis_scope` inside its evidence-bound request body.

- [x] **Step 1: 写入失败测试并验证**

```powershell
python -B -m pytest tests/test_real_capabilities.py tests/test_ephemeral_runtime.py tests/test_vision_backends.py -q -p no:cacheprovider -k "pre_route_scope or technical_splice_scope or adaptive_evidence_plan"
```

预期初始失败：Scope-aware VLM 缺少 `analysis_scope`，Worker Context 不含该字段，技术拼接仍会调用 VLM。

- [x] **Step 2: 实现严格传递和技术路径 VLM 门控**

```python
if semantic_pass["status"] == "skipped":
    # 保留 FFmpeg 的完整时序/边界证据，但不调用 semantic_analyzer。
    pass
else:
    semantic_backend.analyze(..., analysis_scope=scope)
```

生产 VLM 若已接收预路由范围但不支持该参数必须在付费/外部调用前阻断，不能悄悄退回全量语义请求。

- [x] **Step 3: 验证**

```powershell
python -B -m pytest tests/test_real_capabilities.py tests/test_ephemeral_runtime.py tests/test_vision_backends.py -q -p no:cacheprovider
```

### Task 3: 用 Stage 4 的真实区间阻止无关 UI/语音工具

**Files:**

- Modify: `usfr-server/server/real_capabilities.py`
- Modify: `usfr-server/server/capability_ports.py`
- Test: `usfr-server/tests/test_real_capabilities.py`
- Test: `usfr-server/tests/test_capability_ports.py`

**Interfaces:**

- `BundledAppStoreEvidenceParser.run(...)` 在已路由且无 `generated_ui_demo` 时返回 `{"status": "skipped", "skipped_reason": "no_generated_ui_region"}`。
- `CapabilityStagePort("resolve_ui_evidence", ...)` 在相同条件下不调用 UI renderer。
- `CapabilityStagePort("analyze_dynamics", ...)` 在 `source_asr=skipped` 时不调用 ASR，并在输出中记录 `skipped_tools`。

- [x] **Step 1: 写入失败测试并验证**

```powershell
python -B -m pytest tests/test_real_capabilities.py tests/test_capability_ports.py -q -p no:cacheprovider -k "no_generated_ui_region or technical_splice_scope"
```

- [x] **Step 2: 实现仅在已知真实区间下的跳过**

没有 `timeline_regions` 的旧/不确定调用必须走保守路径；只有 Stage 4 已提供空区间或非生成 UI 区间时才跳过，避免错误省略质量证据。

- [x] **Step 3: 验证**

```powershell
python -B -m pytest tests/test_real_capabilities.py tests/test_capability_ports.py -q -p no:cacheprovider
```

### Task 4: 回归和质量核对

**Files:**

- Test: `usfr-server/tests/test_analysis_scope.py`
- Test: `usfr-server/tests/test_real_capabilities.py`
- Test: `usfr-server/tests/test_capability_ports.py`
- Test: `usfr-server/tests/test_ephemeral_runtime.py`
- Test: `usfr-server/tests/test_vision_backends.py`

- [x] **Step 1: 运行受影响的完整回归**

```powershell
python -B -m pytest tests/test_analysis_scope.py tests/test_real_capabilities.py tests/test_capability_ports.py tests/test_ephemeral_runtime.py tests/test_vision_backends.py -q -p no:cacheprovider
```

预期：全部通过；模型替换、语言单改、App/UI、透明拼接、上传音乐和不确定回退均有覆盖。

- [x] **Step 2: 运行现有高保真合同矩阵**

```powershell
python -B -m pytest tests/test_skill_contract.py tests/test_universal_fidelity_contract.py tests/test_high_fidelity_ports.py tests/test_performance_audio_contracts.py -q -p no:cacheprovider
```

预期：不改变十二语义阶段、两次审批、Seedance 审计或最终 QC 的既有约束。
