# USFR 优化包缺口收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变本地 `universal-source-fidelity-replication` 业务流程和两步确认规则的前提下，把 `usfr-optimized.zip` 更新为最新、可独立部署、可真实调用 API 的批量视频服务包。

**Architecture:** 先以本地 `usfr-server` 与最新本地 USFR skill 为唯一基线，补齐 ZIP 中落后的契约和实现；再修复语言-only、App 证据/UI 开关、生产能力校验和 route-first 门控；最后通过真实 API、Docker、OSS 和素材矩阵验证后重新打包。所有优化都在现有 12 个语义阶段和两个用户确认点内完成，不增加新的用户审批。

**Tech Stack:** Python 3.12、FastAPI、Redis/Redis Streams、MinIO（临时对象）、阿里云 OSS（原始素材和最终 MP4 永久保存）、FFmpeg、GPT 证据网关、RunningHub Whisper/Seedance/TTS/对口型工作流、Docker Compose。

## Global Constraints

- 本地 `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md` 是功能和流程基线；同步时不得反向修改本地 skill。
- 生成媒体任务的用户确认顺序固定为：可下载 `analysis/reverse_storyboard_script.md`，然后实际 PNG 故事板整组；禁止范围、方案、时长、提示词、生成和 QC 等额外确认。
- 脚本不能以内联 Markdown 代替下载文件；故事板必须是 PNG 图片集合，两个 Segment 一次整组确认。
- `USFR_UI_REBUILD_ENABLED=false` 仍是默认值。`ui_operation_video` 始终走 opaque splice；没有该视频时，检测到原片 UI 默认保持源 UI，不自动重绘。
- `ui_screenshot`、Google Play/App Store 链接始终进入 App 产品证据和卖点分析；它们是否触发 UI 重绘与 App 证据分析分开判断。
- language-only 只走 ASR、脚本、故事板、TTS、语言校验和 RunningHub 对口型，不得提交 Seedance 视频任务。
- 上传音乐先做 SHA 绑定的 `song/non_song` 分类；歌曲必须在脚本中锁定歌词、时间和演唱人物，多人角色不明确时阻断，不猜测。
- 只保留成功任务的 `final/{job_id}/result.mp4`；临时 Redis/MinIO/工作目录和中间产物按任务清理；用户 OSS 原始素材和最终 OSS 视频不删除。
- 未完成真实 Docker、Provider、TTS、对口型、UI renderer、独立 QC evaluator 和素材矩阵验证前，不得宣称生产质量已验证或 profile 已激活。

---

## 1. 审计结论（2026-07-30）

审计对象：`C:\Users\zhaocx04\lobsterai\project\usfr-optimized.zip`。

### 已通过或已具备

| 项目 | 结果 | 说明 |
|---|---|---|
| ZIP 自包含检查 | 通过 | 原始 ZIP 222 个文件，无 `.env`、API Key、`.pyc` 或 `__pycache__`；测试产生的缓存只出现在临时解压目录，不在 ZIP 内。 |
| 轻量包检查 | 通过 | `scripts/verify_lightweight_bundle.py` 在干净解压目录通过。 |
| 公共 HTTP 本地 smoke | 通过 | 创建、查询、Bearer access token、幂等创建、脚本审核、故事板审核、可播放 MP4 结果均通过。 |
| 36-case catalog | 通过结构检查 | physical product 10、App 10、service 5、brand 4、creator 4、mixed media 3。 |
| 临时/最终对象生命周期 | 已有实现 | MinIO/Redis 临时对象和阿里云 OSS 最终 MP4 分离。 |
| UI 默认开关 | 已有实现 | `USFR_UI_REBUILD_ENABLED=false`，opaque UI 优先级已存在。 |
| RunningHub Whisper 和 Standard Seedance 配置 | 已有框架 | Whisper 输入节点默认 12，Standard Model 和 upload/query 配置已存在。 |

### 仍不能认为已完成

| 优先级 | 当前状态 | 问题/风险 | 计划处理 |
|---|---|---|---|
| P0 | ZIP 不是最新本地基线 | ZIP 222 个文件，本地 `usfr-server` 324 个文件；208 个同名文件中只有 158 个相同，50 个关键文件已分叉。`SKILL.md`、scope、evidence、orchestrator、ports、catalog 等均可能落后。 | 先做基线冻结和完整同步，再做功能修复。 |
| P0 | 两步确认实现不完整 | 脚本查询接口仍返回内联 `content`；缺少 `logical_name`、`presentation` 等最新 metadata；故事板整组确认字段不全；route_1 仍保留一次确认旧逻辑。 | 统一 revision/artifact/public projection 契约。 |
| P0 | language-only 未闭环 | stage plan 仍编译/审计/提交/等待 Seedance；没有接入 TTS 和最终对口型执行，`2080140197518823426` 目前只有请求构造器。 | 改为 TTS + 语言校验 + 对口型工作流，禁止 Seedance 视频提交。 |
| P0 | App 证据与 UI 重绘耦合 | `app_store_url + ui_operation_video` 时 App Store evidence 可能被标记 skipped，产品卖点分析丢失；截图/商店链接分析不能独立于 UI renderer。 | 拆出 `app_product_evidence` 与 `ui_render/rebuild` 两条决策。 |
| P0 | 生产能力校验被绕过 | `packaged_ports.py` 中多处 `production=False/profile_active=False`；启动只检查可调用，不强制检查真实 adapter、manifest、digest 和 readiness。 | active/production 启动前执行完整 capability/Provider binding 校验。 |
| P1 | route-first 只有部分接入 | `AnalysisInvocationLedger` 和 `SharedFrameEvidenceStore` 没有接入调用点；scope promotion/receipt 不是所有高成本 stage 的强制门。 | 把 scope、receipt、lease/retry 去重做成硬门。 |
| P1 | 共享帧证据没有真正复用 | VLM、故事板和 QC 仍可能各自 FFmpeg 解码；`build_shared_frame_manifest` 只有 import，没有统一发布和读取。 | dynamics 后一次解码、后续按 SHA/timestamp 复用。 |
| P1 | QC escalation 仍偏报告 | `build_qc_plan()` 已有，但尚未证明基础 QC 失败后只升级失败因素，也未证明阻止整视频深度重跑。 | 让 plan 直接控制 evaluator 调用和重试边界。 |
| P1 | 性能没有实测证据 | 只有阈值，没有 baseline/candidate 调用次数、临时文件量、实际耗时和质量对比报告。 | 增加运行账本和报告生成器，未有报告前不宣称提速。 |
| P1 | 发布状态文档过期 | `references/production-readiness-status.md` 仍写 2026-07-21、1142 passed、Docker 未验证。 | 更新为当前测试数字，并明确 3 个既有无关失败和 Docker 未执行事实。 |
| P2 | 真实部署未执行 | 本机没有 Docker/WSL，尚未进行容器 build、Redis/MinIO Worker E2E、真实 GPT/RunningHub/OSS 素材矩阵。 | 在有 Docker 和 API 凭证的环境执行发布门。 |

预计工期：P0 约 2–3 天；P1 约 2–4 天；真实 API/素材矩阵至少 1–2 天，取决于 Provider 排队和生成时长。

---

## 2. 实施任务表

### Task 1：冻结最新基线并同步 ZIP

**Files:**

- Modify: `SKILL.md`
- Modify: `bundled-skills/seedance-storyboard-replication/SKILL.md`
- Modify: `server/analysis_scope.py`
- Modify: `server/source_evidence_bundle.py`
- Modify: `server/shared_frame_evidence.py`
- Modify: `server/orchestrator.py`
- Modify: `server/production_ports.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/packaged_ports.py`
- Modify: `validation/case_catalog.json`
- Modify: `references/bundle_manifest.json`, `references/dependency-map.md`
- Create: `scripts/build_release_manifest.py`
- Test: `scripts/verify_bundle.py`, `scripts/verify_lightweight_bundle.py`

**Interfaces:**

- Consumes: 本地 `usfr-server` 与本地 USFR skill 的文件字节和 SHA-256。
- Produces: ZIP 中与本地基线一致的 runtime files、依赖快照和 36-case catalog。

- [ ] **Step 1: 建立无缓存比较清单**

```powershell
python scripts/build_release_manifest.py `
  --source-root C:\Users\zhaocx04\Documents\New project\usfr-server `
  --package-root C:\Users\zhaocx04\Documents\New project\.tmp\release-staging
```

该脚本只接受显式的 source/package 根目录，排除 `__pycache__`、`.pyc`、`.pytest_cache`、用户素材、API key 和本地运行目录；对每个纳入文件记录相对路径、字节 SHA-256、角色和版本，并在发现同名文件 SHA 不同、来源路径含 `.codex` 或输出包含凭证时返回非零状态。

- [ ] **Step 2: 同步实现和契约**

以本地源码为准复制变化文件，同时保留 ZIP 已有的部署脚本和中文手册；不得把本地 `C:\Users\...\.codex\skills` 路径写入运行时引用。

- [ ] **Step 3: 校正 36-case 旧审批预期**

生成媒体 route_1 全部改为 `approval_count=2`；只有明确 `local_only` 的 A09 保持 0。任何 route_1 不得再通过统计 projection 偷换为一次确认。

- [ ] **Step 4: 运行基线审计**

```powershell
python -B scripts/verify_bundle.py
python -B scripts/verify_lightweight_bundle.py
python -B -m compileall -q .
```

预期：bundle/lightweight 均返回 valid；干净打包目录不含 `.env`、`.pyc`、缓存或用户素材。

---

### Task 2：收口两步确认和公开 artifact 契约

**Files:**

- Modify: `server/analysis_scope.py`
- Modify: `server/production_ports.py`
- Modify: `server/public_job_projection.py`
- Modify: `server/review_models.py`
- Modify: `server/review_workflow.py`
- Modify: `server/orchestrator.py`
- Modify: `schemas/script_revision.schema.json`, `schemas/storyboard_revision.schema.json`
- Test: `validation/e2e/local_public_http_smoke.py` and contract tests in the source test suite

**Required metadata:**

- Script: `logical_name=analysis/reverse_storyboard_script.md`, `presentation=file`, `content_type=text/markdown; charset=utf-8`。
- Storyboard: each `segment_XX_vN.png` carries `logical_name`, `presentation=image_set`, `approval_scope=all_segments_together`, `text_only_substitute_forbidden=true`。

- [ ] **Step 1: 补齐 `build_execution_scope`**

让它返回固定的 script/storyboard review contract、generated-region、tool scope 和 source evidence metadata，并由现有 `build_analysis_scope` 调用，避免 ZIP 直接导入测试失败。

- [ ] **Step 2: 修改脚本公开投影**

将 `_script_review()` 的返回从内联 `content` 改为可下载 artifact projection，例如：

```python
{
    "type": "script",
    "artifact": {
        "logical_name": "analysis/reverse_storyboard_script.md",
        "presentation": "file",
        "content_type": "text/markdown; charset=utf-8",
        "url": signed_url,
    },
}
```

服务端内部仍保存 JSON revision 和 Markdown 文件，但用户层只暴露可下载文件。

- [ ] **Step 3: 修改故事板整组投影**

返回 PNG URL 数组及整组元数据；不允许只返回文字 storyboard description，也不允许把两张图拆成两次确认。

- [ ] **Step 4: 固化 revision invalidation**

脚本修改只使 storyboard、segment plan、prompt、provider、assembly、QC 失效；故事板修改只使 segment plan、prompt、provider、assembly、QC 失效；不得新增第三种用户确认。

- [ ] **Step 5: 验证**

```powershell
python -B validation/e2e/local_public_http_smoke.py
pytest -q -k "script_review or storyboard_review or approval_scope or execution_scope"
```

预期：生成媒体 route_1/route_2 均出现两次审核；脚本为下载 Markdown，故事板为 PNG 整组；local-only 仍不创建无意义审核。

---

### Task 3：修复 language-only 的 TTS + 最终对口型链路

**Files:**

- Modify: `server/orchestrator.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/packaged_ports.py`
- Modify: `server/runninghub_workflows.py`
- Modify: `server/runninghub_final_lip_sync.py`
- Modify: `.env.example`
- Modify: `deployment/docker-compose.yml`, `deployment/README.md`, `deployment/中文部署配置手册.md`
- Test: language-only route, TTS request, lip-sync request and no-Seedance assertions

**Interfaces:**

- `RunningHubWorkflowClient.run_tts(text, language, timing, ...) -> Mapping[str, Any]`
- `RunningHubWorkflowClient.run_final_lip_sync(audio_url, video_url) -> Mapping[str, Any]`
- `TtsStage.run(context, input_artifacts) -> Mapping[str, Any]`
- `FinalLipSyncStage.run(context, input_artifacts) -> Mapping[str, Any]`

- [ ] **Step 1: 改造 language-only stage plan**

保留脚本和故事板两个确认点；删除 language-only 的 `compile_seedance20_prompt`、`audit_seedance_request`、`submit_provider_video`、`wait_provider_video`；在既有 assembly/provider 语义阶段内执行 TTS、语言校验和最终对口型，不新增用户审批。

- [ ] **Step 2: 接入 TTS 配置**

在 `.env.example` 增加实际工作流所需的 `RUNNINGHUB_TTS_WORKFLOW_ID`、输入节点/字段和超时配置；缺失配置时在 `/readyz` 失败，不静默降级为本地假音频。

- [ ] **Step 3: 接入固定对口型工作流**

固定 `RUNNINGHUB_FINAL_LIP_SYNC_WORKFLOW_ID=2080140197518823426`，Node 3 使用音频，Node 6 使用对应视频；请求、输入音频、输入视频和输出 MP4 都要发布 SHA/receipt。

- [ ] **Step 4: 锁定对白时间和语言**

TTS 只接受已确认脚本中的 exact line、speaker、`start_ms/end_ms`、locale；生成后做 UTF-8/语言校验，再把对应音频和同时间窗口视频送入对口型。多人对白保持 speaker assignment，不允许默认合并成一个人。

- [ ] **Step 5: 验证没有 Seedance 视频调用**

```powershell
pytest -q -k "language_only and (tts or lip_sync or no_seedance)"
```

预期：ASR → 脚本审核 → 故事板审核 → TTS → 语言校验 → `2080140197518823426` → assembly/QC；Seedance CreateVideo 调用数为 0。

---

### Task 4：拆分 App 产品证据和 UI 重绘开关

**Files:**

- Modify: `server/analysis_scope.py`
- Modify: `server/orchestrator.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/public_script_approval.py`
- Modify: `validation/case_catalog.json`
- Test: App URL/screenshot/opaque UI/generated UI route matrix

**Interfaces:**

- `scope.tools.app_product_evidence`: App 名称、官方截图、卖点、证据 provenance 的分析决策。
- `scope.tools.ui_rebuild`: 仅 UI renderer/重绘或 opaque splice 的执行决策。

- [ ] **Step 1: 建立独立决策**

`ui_screenshot` 或官方 App Store/Google Play URL 出现时，`app_product_evidence=required`；`ui_rebuild` 仍由 `ui_operation_video` 优先级和 `USFR_UI_REBUILD_ENABLED` 决定。

- [ ] **Step 2: 修复 App URL + UI operation video**

即使 UI route 是 `opaque_ui_demo`，也必须先执行一次官方商店解析，把 App 名称、截图、卖点和 provenance 供 script/intent 使用；UI 操作视频本身不 OCR、不重绘、不送 Seedance，只做精确时长 splice。

- [ ] **Step 3: 固定默认开关行为**

| 输入 | App 产品/台词分析 | UI 操作区 |
|---|---|---|
| UI 截图/商店 URL，无 UI 操作视频，开关 false | 开启 | 保持原片 UI |
| UI 截图/商店 URL，无 UI 操作视频，开关 true | 开启 | 允许 generated UI |
| UI 操作视频 | 若有 App URL 仍开启 | 始终 opaque splice |
| 无 UI 证据 | 不抓取商店页 | 保持原片 UI |

- [ ] **Step 4: 验证**

```powershell
pytest -q -k "app_store_evidence and (opaque_ui or source_ui_keep or generated_ui)"
```

预期：App evidence 不再因 opaque UI 被 skipped；UI renderer 仍不会因 App evidence 自动全局启用。

---

### Task 5：补齐 active/production 能力强校验

**Files:**

- Modify: `server/packaged_ports.py`
- Modify: `server/packaged_factory.py`
- Modify: `server/deployment_bootstrap.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/capability_ports.py`
- Modify: `server/production_ports.py`
- Modify: `schemas/stage_capabilities.schema.json`
- Test: startup readiness and fail-closed capability tests

- [ ] **Step 1: 消除生产模式硬编码旁路**

active/production 配置下，dynamics、ASR、UI renderer、Seedance Invocation A/B、compositor、QC、Provider、TTS、final lip-sync 全部使用 `production=True` 和真实绑定；shadow/local 才保留兼容端口。

- [ ] **Step 2: 启动前执行完整检查**

`EphemeralWorkerManager.validate_startup_capabilities()` 必须依次执行 manifest 校验、runtime capability port 校验、stage binding 校验、Provider callable identity/digest 校验、profile snapshot 校验、readiness probe；任一缺失在 HTTP 服务和 worker lease 前失败。

- [ ] **Step 3: 强制 canonical evidence**

dynamics 必须有 Cut/audio evidence；ASR 必须有 timestamped segments；UI 必须有真实 MP4、state/OCR/layout 证据；Seedance A/B 必须有 prompt/artifact digest；compositor 和 QC 必须有当前最终 MP4 绑定 receipt。

- [ ] **Step 4: 验证**

```powershell
pytest -q -k "capability_manifest or runtime_capability or provider_callable_binding or readiness"
```

预期：缺少真实端口、模型 SHA、receipt 或 API 配置时 `/readyz` 返回 503，不创建 Provider task；完整配置时通过。

---

### Task 6：把 route-first scope、analysis ledger 和 shared frame cache 变成硬门

**Files:**

- Modify: `server/analysis_scope.py`
- Modify: `server/source_evidence_bundle.py`
- Modify: `server/shared_frame_evidence.py`
- Modify: `server/ephemeral_driver.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Test: lease/retry dedupe, tool-call scope, shared-frame reuse

- [ ] **Step 1: Analysis ledger 持久化**

将 `AnalysisInvocationLedger` 从内存对象改为 Redis job-scoped record，以 `job_id + source_sha256 + scope_sha256 + tool + route_digest` 去重；lease reclaim/retry 后仍只能有一次完整 source semantic/ASR pass。

- [ ] **Step 2: Scope receipt 强制校验**

所有高成本 stage（GPT/VLM、ASR、OCR/App evidence、Image2、Seedance、TTS、lip-sync、semantic QC）调用 `validate_tool_call()`；deferred 工具必须带 `promote_deferred_tool()` receipt，缺 receipt 直接 fail closed。

- [ ] **Step 3: 发布共享帧清单**

dynamics 完成后调用 `build_shared_frame_manifest()`，按 Cut、timestamp、decoded frame SHA、source SHA 发布唯一 artifact；故事板、Prompt、Seedance 和 QC 只读取该清单，不重复解码同一帧。

- [ ] **Step 4: 验证**

```powershell
pytest -q -k "analysis_invocation_ledger or shared_frame_evidence or scope_receipt"
```

预期：同一 job 在重试时完整分析调用数为 1；相同 timestamp/frame SHA 只产生一次解码；越权工具调用被拒绝。

---

### Task 7：让 QC escalation 真正控制执行

**Files:**

- Modify: `server/qc_escalation.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/recovery_workflow.py`
- Modify: `server/recovery_executor.py`
- Test: base QC, factor escalation, prohibited full rerun

- [ ] **Step 1: 固定两级 QC**

先执行 stream/duration/black/frame/audio/timeline 基础 QC；只有失败因素对应的 semantic evaluator、OCR 或 audio evaluator 才能升级。

- [ ] **Step 2: 禁止整视频重复深度 QC**

`build_qc_plan()` 输出的 `prohibited_full_rerun=true` 必须被执行器读取；恢复流程只能提交失败 Cut/因素和最小证据窗口，不能重新分析全视频。

- [ ] **Step 3: 保留 receipt**

每次升级调用绑定 final MP4 SHA、source/evidence SHA、evaluator/model SHA 和 factor digest；没有 receipt 不能把技术 QC pass 发布为生产 pass。

- [ ] **Step 4: 验证**

```powershell
pytest -q -k "qc_escalation or focused_qc or prohibited_full_rerun"
```

---

### Task 8：生成真实性能和质量对比报告

**Files:**

- Modify: `validation/performance/route_first_benchmark.py`
- Modify: `validation/performance/route_first_thresholds.json`
- Create: `validation/performance/reports/README.md`
- Modify: `server/telemetry.py`, `server/production_ports.py`
- Test: benchmark report schema and call-count export

- [ ] **Step 1: 记录实际调用账本**

每次 GPT/VLM、ASR/Whisper、App parser、Image2、Seedance、TTS、lip-sync、UI renderer、QC evaluator 记录 stage、route、attempt、duration、status、request digest 和 provider task id；不记录 API key 或原始隐私内容。

- [ ] **Step 2: 输出 baseline/candidate 报告**

报告至少包含：总 active time、provider wait、每阶段耗时、深度分析次数、解码帧次数、临时文件数/总字节、Seedance/TTS/lip-sync 调用数、QC escalation 次数、最终质量分和 hard gate。

- [ ] **Step 3: 执行固定阈值**

standard 至少 1.8×、compound app/ui/audio 至少 1.3×、deterministic splice 至少 3.0×；质量下降为 0；完整源语义分析最多 1 次。没有 baseline/candidate 实测报告时，profile 保持 shadow。

- [ ] **Step 4: 验证**

```powershell
python -B validation/performance/route_first_benchmark.py --help
pytest -q -k "route_first_benchmark or performance_report"
```

---

### Task 9：真实 API、Docker、OSS 和素材矩阵验收

**Files:**

- Modify: `deployment/docker-compose.yml`, `deployment/Dockerfile`
- Modify: `validation/e2e/driver.py`, `validation/e2e/public_http_driver.py`
- Modify: `部署操作手册.md`, `deployment/中文部署配置手册.md`
- Modify: `references/production-readiness-status.md`

- [ ] **Step 1: Docker 控制流**

```powershell
docker compose -f deployment/docker-compose.yml config
docker compose -f deployment/docker-compose.yml build --no-cache
docker compose -f deployment/docker-compose.yml up -d redis minio api worker sweeper
```

预期：API/Worker/Redis/MinIO readiness 均通过；本机未安装 Docker 时只能记录“未执行”，不能标记通过。

- [ ] **Step 2: 三个简化 HTTP 接口黑盒验证**

只提交 source video URL 和至少一个固定素材 URL/语言/音频扩展；服务自己探测 SHA、MIME、时长和媒体类型。验证 access token 只在 Authorization Header 传递、幂等创建、脚本文件下载、故事板整组下载和永久 OSS `result_url`。

- [ ] **Step 3: 真实 Provider 小矩阵**

先执行固定六例 smoke：physical product、opaque App UI、Google Play evidence、service/voice、creator/two-person、mixed media/audio；再按影响标签执行 36-case release candidate。每例保留 provider task id、receipt、最终 MP4 SHA 和 QC 报告。

- [ ] **Step 4: OSS 永久保存验证**

确认原始用户 OSS 对象不被删除，最终 MP4 写入 `USFR_OSS_FINAL_PREFIX/final/{job_id}/result.mp4`，返回永久可访问 HTTPS URL；MinIO/Redis 清理后 URL 仍可播放。

- [ ] **Step 5: 更新 readiness 文档**

把 `references/production-readiness-status.md` 更新为实际日期、实际测试数、实际失败列表、Docker 执行状态和真实 API 素材矩阵状态；不得用 shadow/control-flow 结果冒充商业成片质量。

---

### Task 10：干净打包和最终交付

**Files:**

- Create: `exports/usfr-video-service-<release-date>-optimized.zip`
- Modify: `references/bundle_manifest.json`
- Modify: `references/production-readiness-status.md`

- [ ] **Step 1: 从干净 staging 目录打包**

只复制 runtime、部署、验证脚本和手册；排除 `.env`、API key、`.pyc`、`__pycache__`、`.pytest_cache`、临时媒体、用户素材、历史运行目录和本地 skill 外部路径。

- [ ] **Step 2: 执行发布前检查**

```powershell
python -B scripts/verify_bundle.py
python -B scripts/verify_lightweight_bundle.py
python -B validation/e2e/local_public_http_smoke.py
tar -tf exports/usfr-video-service-<release-date>-optimized.zip | Select-String "\.env$|\.pyc$|__pycache__|replication_runs|\.codex"
```

最后一条必须无输出；ZIP 必须能在独立目录运行 smoke，不能依赖本地 skill 或当前工程路径。

- [ ] **Step 3: 记录发布指纹**

保存 ZIP SHA-256、runtime manifest SHA、profile/capability snapshot SHA、测试摘要和 Docker/Provider 验收状态；只有这些证据齐全才允许交给服务端部署。

---

## 3. 验收门槛

### P0 完成条件

- ZIP 与本地最新功能基线同步，关键文件不再分叉。
- 所有生成媒体 route 只有脚本和故事板两次用户确认；脚本是可下载 Markdown，故事板是 PNG 整组。
- language-only 不创建 Seedance 视频任务，真实 TTS 和 `2080140197518823426` 对口型链路可跑通。
- App Store/Google Play/截图证据始终能进入产品卖点和台词分析；UI 重绘仍由独立开关控制。
- active/production 缺能力时在启动阶段 fail closed，不会付费调用。

### P1 完成条件

- route-first 在 lease/retry 下不重复完整分析。
- VLM/故事板/QC 复用同一 shared frame manifest。
- QC 失败只升级失败因素，不全视频重跑。
- 有真实 baseline/candidate 性能和质量报告，满足阈值且无质量下降证据。

### 发布完成条件

- 干净 ZIP 审计通过，HTTP smoke 通过。
- Docker Compose build 和容器 E2E 通过，或明确记录未执行且不宣称通过。
- 真实 GPT、RunningHub Whisper/Seedance/TTS/对口型、UI renderer、独立 QC evaluator 和 OSS 通过固定 smoke 与 36-case release candidate。
- 最终成功响应只返回永久 OSS MP4 结果句柄；临时文件和历史缓存不会进入长期保存区。

## 4. 自检清单

- [ ] 计划覆盖了本地基线同步、两步确认、language-only、App/UI、生产能力、route-first、shared frames、QC、性能、Docker/API、打包发布。
- [ ] 计划没有新增用户审批或修改七个固定上传槽位。
- [ ] 计划没有把 UI renderer、ShotCraft、Remotion 或 HyperFrames 设为全局必经链路。
- [ ] 计划没有把 Docker/control-flow smoke 当成商业视频质量证明。
- [ ] 计划没有把 API key、用户素材或本地路径放进 ZIP。
