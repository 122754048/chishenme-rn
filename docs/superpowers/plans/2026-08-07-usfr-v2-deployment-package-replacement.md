# USFR V2 部署包平稳替换实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改原始部署 ZIP、不破坏微软 GPT、Redis、阿里云 OSS、RunningHub 接口适配及既有 bugfix 的前提下，从原包的逐字节备份副本构建一个只运行 V2 视频编辑链路、可独立部署、可验证、可一键回滚的新部署包。

**Architecture:** 原部署包作为不可变回滚基线；在校验过 SHA-256 的工作副本中完成 V2 替换。最终包不再接受新的 V1 任务，也不保留可执行的 V1 业务路由；上线通过“停止新任务、排空旧任务、备份配置与镜像、部署 V2、健康检查、冒烟任务、失败即回滚”的方式平稳切换。

**Tech Stack:** Python 3、FastAPI、Redis Streams、MinIO/S3 临时对象存储、阿里云 OSS 永久成片、Microsoft/OpenAI-compatible GPT API、RunningHub、FFmpeg、Docker Compose、pytest。

## Global Constraints

- 原始包 `C:\Users\zhaocx04\Documents\New project\exports\usfr-video-service-2026-08-03-deploy-windows-latest-sync.zip` 只读，禁止覆盖、改名或就地解压修改。
- 先生成逐字节备份并校验 SHA-256；所有代码修改只发生在备份派生的工作副本中。
- 最终新包默认且只运行 `edit_v2`；禁止继续创建 V1 任务，禁止使用 shadow 模式维持旧业务链路。
- 上线前排空旧包中的在途 V1 任务；已完成视频的永久 OSS URL 不受升级影响。
- 保留现有 Microsoft GPT、Redis、MinIO、阿里云 OSS、RunningHub、Whisper、TTS、歌曲/非歌曲对口型、Provider reconcile、60 秒 QC、公共 HTTP API 和认证方式。
- 用户层只能出现两个确认门：文字脚本 Markdown 和完整故事板 PNG 集合。
- 纯改语言仍使用“翻译/改写 → TTS → 非唱歌对口型”，但仍需经过脚本和故事板两个确认门。
- 歌曲 MV 走歌曲对口型；背景音乐不得覆盖口播、旁白、画外音或 UI 独白。
- `ui_operation_video` 只走 FFmpeg 确定性替换；UI 截图和 App Store/Google Play 链接走 App 资产板；没有 UI 输入时保留原 UI。
- 最终部署包不得向用户输出模型名、供应商名、内部提示词、内部工作流名、阶段名或技术路由。
- MinIO 中的中间媒体在任务终态后清理；仅最终 MP4 永久写入 OSS。脚本和故事板只在审批期临时保留。
- Provider Create 结果不明确时只允许 reconcile，禁止盲目重提；确认生成失败最多进行一次受审定向重试。
- 最终 QC 墙钟时间上限 60 秒；超时执行现有受控交付策略，不允许反复 QC。
- 不新增用户、租户、计费、历史记录或产品后台等非视频生成能力。

---

### Task 1：建立不可变备份、工作副本和回滚基线

**Files:**
- Source: `exports/usfr-video-service-2026-08-03-deploy-windows-latest-sync.zip`
- Create: `exports/backups/usfr-video-service-2026-08-03-original-2026-08-07.zip`
- Create: `.tmp/usfr-v2-upgrade-20260807/work/`
- Create: `.tmp/usfr-v2-upgrade-20260807/baseline-sha256.txt`
- Create: `.tmp/usfr-v2-upgrade-20260807/baseline-file-list.txt`

**Interfaces:**
- Consumes: 原始 ZIP 字节。
- Produces: 可回滚备份、唯一工作目录、原包 SHA 和文件清单。

- [ ] 校验原 ZIP 可正常打开且不存在路径穿越条目。
- [ ] 计算原 ZIP SHA-256，复制到备份目录，再计算备份 SHA-256；两者必须完全一致。
- [ ] 只把备份 ZIP 解压到工作目录，禁止直接解压原 ZIP。
- [ ] 检查工作副本包含 `.env.example`、`deployment/docker-compose.yml`、`server/`、`scripts/`、`references/`、`schemas/` 和 `tests/`。
- [ ] 保存基线文件清单、基线测试结果和 `docker compose config` 输出。

**Verification:**

```powershell
Get-FileHash -Algorithm SHA256 '<original.zip>'
Get-FileHash -Algorithm SHA256 '<backup.zip>'
python -m pytest -q
docker compose --env-file .env.example -f deployment/docker-compose.yml config
```

两个 ZIP 哈希必须相同；基线失败项必须先记录为既有问题，禁止把既有失败冒充 V2 回归。

### Task 2：冻结基础设施适配与公共 API 兼容边界

**Files:**
- Modify only when necessary: `.env.example`
- Modify only when necessary: `deployment/docker-compose.yml`
- Protect: `server/gpt_evidence_gateway.py`
- Protect: `server/redis_job_store.py`
- Protect: `server/redis_streams.py`
- Protect: `server/aliyun_oss_final_store.py`
- Protect: `server/public_api_models.py`
- Protect: `server/public_fastapi_router.py`
- Test: `tests/test_v2_protected_infrastructure.py`
- Test: `tests/test_v2_public_http_compatibility.py`

**Interfaces:**
- Consumes: 原包环境变量名和 HTTP 合同。
- Produces: V2 升级前后完全兼容的部署入口。

- [ ] 为受保护文件建立内容哈希或行为测试，禁止 V2 代码绕开现有 GPT、Redis、OSS 和 access token 绑定。
- [ ] 保持 `POST /api/v1/jobs` 的素材 URL 字段不变；V2 模式由服务端内部版本决定，不要求前端新增复杂字段。
- [ ] 保持任务创建、脚本审批、故事板审批、状态查询和最终永久 OSS URL 的公共响应结构。
- [ ] `.env.example` 只删除已经没有运行时引用的 V1 变量；所有密钥仍为空，不得打入 ZIP。
- [ ] 公共错误经过 `public_content_policy` 清洗，禁止出现模型、供应商、内部阶段或提示词名称。

### Task 3：建立 V2 唯一运行时契约和依赖失效机制

**Files:**
- Create: `server/v2_edit_contracts.py`
- Create: `server/v2_stage_plan.py`
- Create: `schemas/edit_manifest.schema.json`
- Create: `schemas/v2_stage_checkpoint.schema.json`
- Modify: `server/job_models.py`
- Modify: `server/redis_job_store.py`
- Modify: `server/ephemeral_driver.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/orchestrator.py`
- Modify: `server/review_workflow.py`
- Test: `tests/test_v2_stage_dependencies.py`
- Test: `tests/test_v2_downstream_invalidation.py`

**Interfaces:**
- `build_v2_stage_plan(manifest) -> tuple[V2StageSpec, ...]`
- `invalidate_v2_downstream(changed_stage, checkpoints) -> tuple[str, ...]`
- 每个 checkpoint 持有 `depends_on`、`input_fingerprint`、`output_fingerprint`、`contract_version`、`status`。

- [ ] 新任务一律冻结 `workflow_version=edit-v2`，不再创建 V1 运行计划。
- [ ] 运行计划固定为：输入绑定、轻量拆解、脚本、脚本审批、资产板、素描故事板、故事板审批、分段、编辑请求、Provider、后处理、QC/交付。
- [ ] 脚本修改使资产板及全部下游失效；资产板修改使故事板及全部下游失效；故事板修改使分段及全部下游失效。
- [ ] 分段或提示词修改不得复用旧 Provider 结果；后处理输入改变时可复用未变化的 Provider 视频，但必须重做后处理和 QC。
- [ ] 禁止从中间阶段人工跳步；依赖指纹不一致时自动回到最早失效阶段。
- [ ] 保持两个且只有两个审批门。

### Task 4：把重型源拆解替换为 V2 轻量分析

**Files:**
- Create: `server/v2_source_analysis.py`
- Create: `schemas/v2_source_analysis.schema.json`
- Modify: `server/packaged_ports.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/analysis_scope.py`
- Modify: `server/source_content_timeline.py`
- Reuse: `server/gpt_evidence_gateway.py`
- Reuse: `server/capability_ports.py`
- Test: `tests/test_v2_lightweight_source_analysis.py`
- Test: `tests/test_v2_audio_classification.py`

**Interfaces:**
- `analyze_edit_source(source, slots, capabilities) -> V2SourceAnalysis`
- 输出 Cut、ASR 台词窗口、三类音频窗口、人物/商品/UI/文字区域、尾部终止边界、爆款基因。

- [ ] Cut 检测使用 FFmpeg；只抽样必要关键帧，禁止逐帧 VLM。
- [ ] Whisper 只用于非纯音乐/非纯背景音乐路线，并直接上传源视频。
- [ ] 音频只分为口播/旁白、歌曲、背景音乐/环境音所需类别；不重建旧 Foley 全量合同。
- [ ] GPT 只执行一次营销推理：爆款基因、新商品/App 卖点、痛点、展示方法和原片适配。
- [ ] 停止生成完整 Source Fidelity Contract、Invocation A、逐 Cut 相机合同和原子动作图。
- [ ] 仍保留文字物理层、叠加层和水印层分类，以及 `_sharpness_ratio` 所需源文字锁。

### Task 5：生成 V2 脚本文档并修复语言-only 审批绕过

**Files:**
- Modify: `server/user_script_document.py`
- Modify: `server/production_ports.py`
- Modify: `server/review_workflow.py`
- Create: `schemas/v2_script_revision.schema.json`
- Test: `tests/test_v2_user_script_document.py`
- Test: `tests/test_v2_language_only_two_approvals.py`
- Test: `tests/test_v2_public_content_redaction.py`

**Interfaces:**
- `render_v2_user_script_markdown(analysis, bindings, audio_plan) -> bytes`
- 输出路径固定为 `analysis/reverse_storyboard_script.md`。

- [ ] 脚本包含剧情梗概、爆款基因、卖点/痛点、适配方案、人物绑定、视觉资产类型、替换点、台词、文字分层、音频和分段计划。
- [ ] 用户可在同一个脚本门修改台词、人物映射、资产类型、替换范围和音频计划。
- [ ] 纯改语言也先生成脚本和故事板，确认后再执行 TTS 与非唱歌对口型。
- [ ] 脚本不得出现 Image2、Seedance、Whisper、RunningHub、GPT、内部阶段名、内部提示词或路由名。

### Task 6：建立五类资产板和独立素描故事板

**Files:**
- Create: `server/v2_asset_boards.py`
- Create: `server/v2_sketch_storyboard.py`
- Create: `references/v2_asset_board_templates.md`
- Create: `references/v2_sketch_storyboard_prompt.md`
- Create: `schemas/v2_asset_board.schema.json`
- Modify: `server/packaged_stages.py`
- Modify: `server/production_ports.py`
- Modify: `references/bundle_manifest.json`
- Modify: `references/runtime_skill_manifest.json`
- Test: `tests/test_v2_asset_boards.py`
- Test: `tests/test_v2_sketch_storyboard.py`
- Test: `tests/test_v2_reference_limit.py`

**Interfaces:**
- `generate_asset_board(asset_type, source_asset, approved_script) -> AssetBoardReceipt`
- `generate_sketch_storyboards(cuts, script, asset_bindings) -> tuple[StoryboardPage, ...]`

- [ ] 支持人物、服装、场景、商品、App 五类资产板；失败输出 `ASSET_BOARD_GENERATION_FAILED`，禁止回退到原图。
- [ ] 同一资产板被两个 Segment 复用，禁止重复生成。
- [ ] 故事板只显示 Cut 顺序、时间、人物标签、动线、动作目的和新产品展示逻辑，不渲染真实身份细节。
- [ ] 每页最多 6 Cut、最多 2 页，所有页一次性审批。
- [ ] 创建独立 V2 素描模板；禁止覆盖 V1 的 `daohuo_storyboard_prompt.md`，待 V1 删除阶段再清理旧模板。
- [ ] 资产板加故事板总数超过 9 张时，在 Provider 调用前输出明确 blocker，禁止静默丢弃引用。

### Task 7：用确定性编辑编译器替换 V1 全量提示词链路

**Files:**
- Create: `server/v2_edit_prompt.py`
- Create: `references/v2_edit_prompt_contract.md`
- Create: `schemas/v2_edit_request.schema.json`
- Modify: `server/runninghub_standard_contract.py`
- Modify: `server/production_ports.py`
- Modify: `server/packaged_stages.py`
- Test: `tests/test_v2_edit_prompt.py`
- Test: `tests/test_v2_provider_reference_order.py`
- Test: `tests/test_v2_source_video_segments.py`

**Interfaces:**
- `compile_v2_edit_prompt(script, boards, assets, segment) -> CompiledEditPrompt`
- `validate_v2_provider_request(payload, lineage) -> None`

- [ ] 提示词固定以“编辑视频：@Video1 是源视频编辑对象”开头，只列实际替换、修改台词和音频计划。
- [ ] 明确写入：被替换窗口中目标资产优先于原片；未声明替换的内容逐帧保持。
- [ ] 图片顺序固定为人物资产板、服装、场景、商品、App、故事板页；标签与上传顺序完全一致。
- [ ] 原视频按自然 Cut 分为每段 4–15 秒、最多两段；台词不得跨段。
- [ ] 继续使用现有 Provider attempt、请求 SHA、reconcile 和防盲重提机制。
- [ ] 删除 V2 活动路径中的 5000 字符全量重发、factor 覆盖和 Invocation A/B；模板组装不得调用 GPT。

### Task 8：完成 V2 UI、音频和后处理路由

**Files:**
- Modify: `server/audio_lane_router.py`
- Modify: `server/audio_route_guard.py`
- Modify: `server/singing_audio_router.py`
- Modify: `server/runninghub_song_lip_sync.py`
- Modify: `server/runninghub_final_lip_sync.py`
- Modify: `server/timeline_renderer.py`
- Modify: `server/audio_mixer.py`
- Modify: `server/visible_text_contract.py`
- Test: `tests/test_v2_audio_routes.py`
- Test: `tests/test_v2_ui_operation_splice.py`
- Test: `tests/test_v2_tail_and_overlay.py`

**Interfaces:**
- `assemble_v2_timeline(provider_media, ui_video, tail_video, audio_plan, overlays) -> ArtifactRef`

- [ ] `ui_operation_video` 替换脚本批准的 UI 区间，原视频该区间从最终时间线移除；不上传给生成模型。
- [ ] UI 截图/App 链接只生成 App 资产板；无 UI 输入时原 UI 保持。
- [ ] 纯歌曲/MV 使用歌曲对口型工作流；普通背景音乐只换音乐轨。
- [ ] 旁白和画外音保留或用参考音色 TTS，不做人脸对口型。
- [ ] 纯改语言使用非唱歌对口型；歌曲和非歌曲对口型工作流禁止互换。
- [ ] UI 独白、口播和旁白窗口具有音乐 ducking 保护。
- [ ] 叠加层文字后期合成；物理层文字由编辑请求处理；水印只处理脚本批准的范围。

### Task 9：建立 V2 QC、一次定向重试和临时文件清理

**Files:**
- Create: `server/v2_qc.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/qc_escalation.py`
- Modify: `server/cleanup.py`
- Modify: `server/ephemeral_worker.py`
- Test: `tests/test_v2_qc_ceiling.py`
- Test: `tests/test_v2_provider_retry_policy.py`
- Test: `tests/test_v2_ephemeral_retention.py`

**Interfaces:**
- `run_v2_qc(final_media, edit_contract, timeout_seconds=60) -> V2QcReceipt`

- [ ] 检查指定人物/商品/App 是否完成替换、未指定画面是否保持、修改台词是否准确、拼接是否连续。
- [ ] 保留 `_sharpness_ratio`，但不逐帧检查源帧，也不进行无限视觉验收。
- [ ] QC 墙钟时间超过 60 秒立即走现有超时交付策略。
- [ ] 只有明确失败允许一次新的受审请求；timeout、断连和未知结果只 reconcile。
- [ ] 任务终态后清理 MinIO 中资产板、故事板、Provider 临时视频、分析 JSON 和日志媒体；只保留 OSS 最终 MP4。

### Task 10：删除最终包内可执行 V1 链路与历史残留

**Files:**
- Remove after zero-reference proof: `server/high_fidelity_envelope.py`
- Remove after zero-reference proof: `server/high_fidelity_ports.py`
- Remove after zero-reference proof: `server/high_fidelity_projection.py`
- Remove after zero-reference proof: `server/seedance_invocations.py`
- Remove after zero-reference proof: `server/replacement_control_qc.py`
- Remove after zero-reference proof: `scripts/high_fidelity_analysis.py`
- Remove after zero-reference proof: `scripts/high_fidelity_profile.py`
- Remove after zero-reference proof: `scripts/high_fidelity_qc.py`
- Remove after zero-reference proof: `scripts/seedance_prescript.py`
- Remove after zero-reference proof: `scripts/seedance_prompt_compiler.py`
- Remove after zero-reference proof: `scripts/control_keyframe_contract.py`
- Remove after zero-reference proof: `scripts/source_pixel_card_compositor.py`
- Remove after zero-reference proof: V1-only schemas/references/tests and UI redraw sidecar files
- Modify: `references/bundle_manifest.json`
- Modify: `references/runtime_skill_manifest.json`
- Test: `tests/test_v2_no_legacy_runtime.py`

**Interfaces:**
- Consumes: 已通过的完整 V2 实现。
- Produces: 无 V1 运行入口、无悬空引用的轻量部署包。

- [ ] 先用 `rg` 证明每个候选文件没有被 V2 运行时、部署入口、测试和文档引用，再删除。
- [ ] 保留仍被 V2 使用的 OCR、App Store 解析、Provider reconcile、音频后端和 FFmpeg 组件；禁止按目录整块删除。
- [ ] 删除 `generated_ui_demo`、replacement-control、Invocation A/B、V1 高保真 profile、V1 Prompt、旧 UI 重绘开关及其专属测试。
- [ ] 更新 bundle manifest 后验证所有 SHA 与实际文件一致。
- [ ] 最终包外保留原始备份 ZIP，最终包内不得携带旧 ZIP、历史生成文件、缓存、`.git`、API Key 或测试输出。

### Task 11：真实 HTTP、容器和功能矩阵验收

**Files:**
- Create: `validation/v2/case_catalog.json`
- Create: `validation/v2/public_http_driver.py`
- Create: `deployment/USFR-V2-升级回滚维护手册.md`
- Modify: `references/post-deployment-test-plan.md`
- Test: `tests/test_v2_release_package.py`

**Interfaces:**
- Produces: HTTP 验收报告、Provider 验收报告、回滚手册和可发布判定。

- [ ] 运行全部离线测试，必须没有新增失败。
- [ ] 用 Docker Compose 启动 Redis、MinIO、API、Worker、Sweeper，验证健康检查和任务推进。
- [ ] 真实跑通 HTTP：创建任务、读取脚本、修改/确认脚本、读取故事板 PNG、确认故事板、查询最终 OSS URL。
- [ ] 覆盖人物、商品、人物+商品、App 截图、商店链接、UI 操作视频、尾卡、纯改语言、背景音乐、歌曲 MV、多人物、多商品、双段视频。
- [ ] 真实验证 Provider 的 `videoUrls` 确实具有“编辑对象”语义；若只把视频当弱参考，不得发布 V2。
- [ ] 验证公共响应、脚本文档、故事板可见文字和错误消息不包含内部技术信息。
- [ ] 验证终态后 MinIO 中间文件被清理、OSS 最终 MP4 永久可访问。

### Task 12：重新打包、生成升级脚本并执行平稳切换

**Files:**
- Create: `deployment/upgrade-to-v2.ps1`
- Create: `deployment/upgrade-to-v2.sh`
- Create: `deployment/rollback-to-v1.ps1`
- Create: `deployment/rollback-to-v1.sh`
- Create: `exports/usfr-video-service-v2-2026-08-07-deploy-windows.zip`
- Create: `exports/usfr-video-service-v2-2026-08-07-release-report.md`

**Interfaces:**
- Upgrade input: 旧部署目录、旧 `.env`、新 V2 ZIP。
- Upgrade output: V2 容器与可回滚的旧镜像/目录。

- [ ] 升级脚本先停止创建新任务，再查询 Redis 在途任务；未排空时拒绝切换。
- [ ] 备份服务器 `.env`、Compose 配置、当前镜像标签和部署目录；禁止覆盖原备份。
- [ ] 新包继承旧 `.env`，运行配置校验、镜像构建、健康检查和一个最小 HTTP 冒烟任务。
- [ ] 冒烟失败自动恢复旧目录、旧镜像和旧 Compose；不删除故障现场日志。
- [ ] 成功后恢复新任务入口；旧备份至少保留到 V2 完整业务矩阵验收结束。
- [ ] ZIP 中只包含部署所需源码、契约、模板、脚本、测试和中文维护手册；不包含缓存、历史生成文件、密钥或 `.git`。

## 发布硬门

只有同时满足以下条件才允许宣告完成：

1. 原始 ZIP 与备份 ZIP 的 SHA-256 完全相同。
2. 原始 ZIP 从未被修改。
3. 最终包只创建 V2 任务，V1 可执行路由和历史残留已清除。
4. Microsoft GPT、Redis、MinIO、OSS、RunningHub、认证、Provider reconcile 和已知 bugfix 的兼容测试全部通过。
5. 两个用户确认门顺序正确，任何路线都不能跳过。
6. 真实 HTTP 全链路和至少一个真实 Provider V2 编辑任务跑通。
7. 60 秒 QC、一次定向重试、临时文件清理和最终 OSS 永久 URL 均有证据。
8. 新 ZIP、发布报告、升级脚本、回滚脚本和中文维护手册均已生成且可打开。

