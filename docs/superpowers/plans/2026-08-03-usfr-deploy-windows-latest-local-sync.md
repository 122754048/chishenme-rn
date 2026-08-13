# USFR Windows 部署包同步本地最新 Skill 实施计划

> 状态：待用户审核。本文只定义差异、保护边界和实施步骤；审核通过前不修改原部署 ZIP，不调用付费接口。

## 一、目标

以当前服务端已配置的 Windows 部署包为主干，在以下能力保持不变的前提下，把本地 `universal-source-fidelity-replication` 的最新视频复刻能力增量同步进去：

- 微软侧 GPT / OpenAI-compatible Responses 接入方式、地址、模型配置和现有缓存逻辑不变。
- Redis 的任务状态、队列、租约、CAS、失败提交、幂等、恢复与清理逻辑不变。
- 阿里云 OSS 的远程素材导入、永久成片存储、永久 URL 和安全校验不变。
- 当前三个公共 HTTP 接口、鉴权、`access_token`、`Idempotency-Key` 和错误投影不变。
- 服务端已经完成的 bugfix 不回退。
- 真实 `.env` 不覆盖、不重写、不在报告中展示。

同步原则只有一条：**部署包做主干，本地 Skill 只作为功能差异来源，逐模块人工合并，禁止任何方向的整目录覆盖。**

## 二、审计基线

### 对比对象

- 原部署包：`C:\Users\zhaocx04\Documents\New project\exports\usfr-video-service-2026-07-29-deploy-windows.zip`
- 原部署包 SHA-256：`F510316570AD11947207C08F807ACA2AD74E7131F2754E3D0FC93831C112EA5A`
- 本地 Skill：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication`

### 文件差异

| 项目 | 数量 |
| --- | ---: |
| 部署包文件 | 222 |
| 本地 Skill 文件 | 334 |
| 同路径文件 | 203 |
| 同路径且完全一致 | 141 |
| 同路径但内容不同 | 62 |
| 本地独有 | 131 |
| 部署包独有 | 19 |

这说明两者已经形成分叉：部署包不是本地 Skill 的简单旧副本，本地 Skill 也不能直接替代部署包。

## 三、差异结论

### 1. 部署包领先、必须原样保护的能力

| 能力 | 部署包现状 | 同步规则 |
| --- | --- | --- |
| 公共 HTTP | 只公开创建任务、查询任务、提交审核三个业务接口 | 接口路径、字段、返回结构不增不减 |
| 鉴权与幂等 | job 级 Bearer token、只存 token hash、创建幂等、同请求稳定重放 | 原样保留 |
| URL 素材导入 | HTTPS、域名/IP/重定向/大小/媒体类型/时长检查 | 原样保留 |
| 阿里云 OSS | 原素材导入与最终 MP4 永久保存，返回永久 URL | 原样保留，禁止退回 MinIO 最终存储 |
| Redis | 公共状态字段、CAS、租约、ACK、失败原子提交、重试和清理 | 以部署版为准 |
| `ImportSourcesStage` | 先导入 URL 素材，再进入分析 | 必须继续作为正式入口 |
| source-only 拦截 | 只有原视频、没有任何变更目标时在付费调用前返回 422 | 保留且回归验证 |
| UI 规则 | UI 重建默认关闭；UI 截图/商店链接仍做产品分析；UI 操作视频走剪辑替换 | 保留部署定制策略 |
| GPT 复用 | 相同证据请求缓存、source evidence bundle、用户 revision 绑定 | 不能被本地同名文件覆盖 |
| 临时清理 | 临时 MinIO、上传副本和任务文件可清理，OSS final 永久保留 | 原样保留 |

### 2. 本地 Skill 领先、需要同步的能力

| 能力 | 部署包当前缺口 | 目标状态 |
| --- | --- | --- |
| 只改语言快捷路线 | 仍错误经过故事板、确认和新视频生成 | 直接翻译 → TTS → 非唱歌口型同步 → QC；不生成故事板和新视频 |
| Whisper 新接口 | 仍先抽 WAV，再传旧节点 | 仅非音乐语音调用；原视频直接上传 AI App，节点 `1`、字段 `video`、ID `2080170949061038081` |
| 音乐/口播/旁白分轨 | 歌曲和口播边界混杂 | 音乐替换音乐、口播替换口播、旁白独立配音，三者禁止串线 |
| 两套口型同步 | 歌曲与语言可能共用旧工作流 | 歌曲固定 `2082759080288296961`；只改语言口播固定 `2080140197518823426` |
| 上传歌曲规则 | 仍反推并要求时间戳歌词 | 上传歌曲字节是演唱和口型权威；不再反推歌词、不向用户展示歌词 |
| 正常复刻口播 | 可能在生成后再做非唱歌口型同步 | 用户确认台词直接写入视频生成指令；正常复刻不调用非唱歌口型工作流 |
| 旁白音色 | 缺少原旁白参考音色闭环 | 从原视频提取对应旁白音色作 TTS 参考；旁白不做人脸口型同步 |
| 内部替换控制图 | 缺少完整硬校验和收据 | 一张源帧总图一次生成一张替换控制总图，禁止逐 Cut、禁止本地换脸 |
| 导演故事板 | 生产提示词未真正使用固定模板，分页与绑定不完整 | 运行时填充固定骨架；每页最多 4 Cut、最多 2 页；两页一次确认并完整绑定 |
| 身份替换约束 | 源视频人物仍可能压过新模特 | 所有视频指令开头加入强制 `@Video1` 隔离规则，新模特图是唯一身份权威 |
| 用户技术信息屏蔽 | 公共错误较安全，但脚本、故事板和部分投影没有统一守卫 | 所有用户可见出口禁止出现模型名、供应商名、内部 Stage/工具/流程名 |
| QC 时间 | 没有统一 60 秒硬上限 | 最终视频可读取后，QC 总预算最多 60 秒；到时直接交付，不反复 QC |
| 性能优化 | 缺本地最新编码和并行能力 | 保留 route-first，并同步 FFmpeg 编码、故事板/查询/下载的安全并行 |

### 3. 已基本一致、不需要重做的能力

- 七个素材入口和 `background_music` 的内部语义基本一致。
- 公共 API 的音频字段继续叫 `audio`，内部再映射为 `background_music`，不改公共字段名。
- source-only 创建前拦截已经存在。
- UI 重建默认关闭、显式 UI 证据触发和 UI 操作视频剪辑替换已经存在。
- `server/gpt_evidence_gateway.py`、`server/object_store.py`、`server/redis_streams.py` 两边一致，不做无意义覆盖。

### 4. 不能直接复制的冲突文件

以下文件两边都包含有效能力，只能按函数和状态迁移，禁止整文件覆盖：

- `.env.example`
- `deployment/docker-compose.yml`
- `server/orchestrator.py`
- `server/ephemeral_driver.py`
- `server/ephemeral_worker.py`
- `server/ephemeral_service.py`
- `server/packaged_stages.py`
- `server/packaged_ports.py`
- `server/production_ports.py`
- `server/real_capabilities.py`
- `server/analysis_scope.py`
- `server/packaged_factory.py`
- `server/deployment_bootstrap.py`
- `server/redis_job_store.py`
- `server/job_models.py`
- `server/cleanup.py`
- `server/capability_tokens.py`
- `schemas/job.schema.json`
- `deployment/requirements.lock`
- `deployment/requirements-control-plane.lock`
- `references/bundle_manifest.json`

本地以下文件不能覆盖部署版本：`packaged_factory.py`、`deployment_bootstrap.py`、`redis_job_store.py`、`cleanup.py`、`job_models.py`。否则会丢失公共 HTTP、OSS、永久 URL、Redis 公共字段和失败恢复能力。

## 四、实施计划

### 任务 0：冻结原包与受保护配置

**动作**

- [ ] 原 ZIP 保持只读，另建带日期的工作副本和回滚副本。
- [ ] 记录原 ZIP、核心受保护文件、Compose、requirements 和 manifest 的 SHA-256。
- [ ] 如果包中存在真实 `.env`，只做字节级备份与哈希，不读取到报告、不改任何值。
- [ ] 在独立 staging 目录修改，禁止直接在原 ZIP 解压目录上工作。

**验收**

- 原 ZIP SHA-256 仍为 `F510...EA5A`。
- 回滚副本与原 ZIP 哈希完全一致。

### 任务 1：先建立“不可回退”保护测试

**新增验证**

- [ ] OpenAPI 只存在三个公共业务路径。
- [ ] 同 `Idempotency-Key` + 同 body 返回同一 job/token；同 key + 不同 body 返回 409。
- [ ] 错误、缺失、跨 job token 都被拒绝。
- [ ] `source_video` 单独提交在创建正式 Job 和远程下载前返回 422。
- [ ] `IMPORTING → import_sources → ANALYZING` 只执行一次。
- [ ] Redis lease/version/dedupe 不匹配时禁止提交；终态先落库再 ACK。
- [ ] URL 导入继续拦截私网、非法重定向、超限文件和超时长视频。
- [ ] OSS final 重复同字节幂等、不同字节冲突；临时清理后 final 仍存在。
- [ ] Compose 不对外发布 Redis/MinIO 端口，requirements 继续包含 `oss2==2.19.1`。
- [ ] 现有 GPT endpoint/model/config SHA 和请求方式不变，相同请求缓存仍有效。

这些测试必须在同步任何业务功能之前通过，后续每批合并后都只跑相关保护测试。

### 任务 2：合并路由和 Stage 状态机

**主要文件**

- `server/intake.py`
- `server/orchestrator.py`
- `server/ephemeral_driver.py`
- `server/ephemeral_worker.py`
- `server/packaged_stages.py`
- `server/packaged_factory.py`

**动作**

- [ ] 以部署版 Stage 图为主，保留 `ImportSourcesStage`、公共审核投影和 Redis checkpoint。
- [ ] 加入本地最新的 route-first 判断，路由结论只计算一次并复用。
- [ ] 只改语言固定为：`build_script → run_tts → run_final_lip_sync → run_qc`。
- [ ] 只改语言不生成控制图、故事板和新视频，不出现用户确认。
- [ ] 正常复刻仍只保留两个用户确认：文字脚本、导演故事板整组。
- [ ] 不增加第三个确认入口，不把内部控制图暴露给用户。

**验收**

- `ImportSourcesStage` 和公共三接口不变。
- 只改语言路线不会触发故事板或视频生成 Provider。
- 普通复刻确认顺序仍为文字脚本后故事板。

### 任务 3：同步 Whisper 原视频直传与轻量声音判断

**主要文件**

- `server/runninghub_workflows.py`
- `server/capability_ports.py`
- `server/packaged_ports.py`
- `server/packaged_stages.py`

**动作**

- [ ] 非音乐语音识别改为直接上传原视频，不再为 Whisper 先生成 WAV。
- [ ] 使用 AI App ID `2080170949061038081`、节点 `1`、字段 `video`。
- [ ] 纯音乐和纯背景音乐跳过 Whisper，禁止多余调用。
- [ ] 轻量声音分类结果在任务内冻结并复用，禁止每个 Stage 重复深度分析。
- [ ] 保留旧环境变量名的一版兼容读取，但启动预检必须明确显示最终采用的配置，避免静默调用错误工作流。

**验收**

- 非音乐视频仅提交一次原视频识别请求。
- 音乐路线的 Whisper 调用次数为零。
- RunningHub 返回 `workflow not exists` 时在预检或创建阶段给出明确内部诊断，不自动重复付费提交。

### 任务 4：同步音乐、口播、旁白三条声音链路

**新增/合并文件**

- 新增 `server/audio_lane_router.py`
- 新增 `server/runninghub_song_lip_sync.py`
- 合并 `server/runninghub_final_lip_sync.py`
- 合并 `server/uploaded_audio_contract.py`
- 合并 `server/singing_audio_router.py`
- 合并 `server/audio_mixer.py`
- 合并 `server/packaged_stages.py`
- 合并 `server/packaged_ports.py`

**固定规则**

- [ ] 上传歌曲 + 原视频是歌曲/MV：只替换唱歌区间，并调用歌曲口型工作流 `2082759080288296961`。
- [ ] 原视频只有部分唱歌：只替换该区间；口播、对白、独白、旁白禁止被歌曲覆盖。
- [ ] 上传歌曲 + 原视频不是歌曲/MV：仅作为背景音乐替换，不让人物唱歌。
- [ ] 上传歌曲不再做歌词反推，不要求时间戳歌词；上传音频本身是歌曲与口型权威。
- [ ] 正常复刻中的画面内人物说话：把用户确认台词、说话人和时间窗直接写入视频制作指令，不调用非唱歌口型工作流。
- [ ] 只有“只改语言 + 画面内人物真实说话”才调用非唱歌口型工作流 `2080140197518823426`。
- [ ] 旁白/画外音使用原旁白音色作为 TTS 参考，只替换音轨，不调用任何人脸口型工作流。
- [ ] 多人内容必须冻结“谁在什么时间说/唱什么”，未能确定时在付费生成前停止。

**特别收口**

本地歌曲口型已有请求构造器，但审计发现实际 Stage 编排尚未完整闭环。本次不能只复制文件，必须把它真正接入视频生成后的区间处理、最终音轨合成和失败处理。

**验收**

- 两套口型工作流在类型、请求构建、提交和结果解析四层都不能互相调用。
- 背景音乐、歌曲、正常口播、只改语言口播、旁白五类测试全部命中唯一正确路线。
- 最终音轨总时长与原视频一致，音乐不能覆盖口播或旁白窗口。

### 任务 5：同步内部替换控制总图和导演故事板

**主要文件**

- `bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md`
- `server/packaged_stages.py`
- `server/replacement_control_qc.py`
- `server/review_models.py`
- `server/public_job_projection.py`
- `schemas/storyboard_revision.schema.json`

**动作**

- [ ] 从原视频一次生成一张完整源帧总图。
- [ ] 以该总图一次生成一张内部替换控制总图；明确替换模特、商品或 App，动作、表情、姿态、视线、手部关系、背景、构图、镜头和光线保持不变。
- [ ] 禁止逐帧、逐 Cut 生成替换图；禁止本机换脸；禁止把用户模特图当作控制图。
- [ ] 控制图必须绑定源总图 SHA、目标素材 SHA、单次生成收据和视觉一致性验收，未通过时不得进入故事板。
- [ ] 导演故事板必须读取并完整填充 `daohuo_storyboard_prompt.md` 固定骨架，不能再由 `_segment_prompt()` 自行拼简版提示词。
- [ ] 故事板必须把内部替换控制总图作为视觉参考。
- [ ] 每页最多 4 Cut；4 Cut 放不下时才生成第二页；总共最多 2 页。
- [ ] 两页同时交给用户做一次整组修改或确认，不增加确认次数。
- [ ] 最终视频生成绑定所有实际存在的故事板页，不能只绑第一页。

**模板冲突处理**

审计发现本地 `daohuo_storyboard_prompt.md` 尾部仍残留“每 Cut 单独 PNG、没有 1–2 页限制”的旧附录，与当前主规则冲突。同步时只删除这段冲突旧附录，保留用户已经认可的固定导演板骨架和视觉风格，不重写其他故事板规则。

**验收**

- 最终发送的故事板提示词可证明来自完整模板，并记录模板 SHA。
- 1–4 Cut 只生成一页；5–8 Cut 才生成两页；超过 8 Cut 在付费调用前停止。
- 两页故事板只产生一次用户审核请求。

### 任务 6：强化新模特/新产品的生成前身份边界

**主要文件**

- `scripts/seedance_prompt_compiler.py`
- `server/runninghub_standard_contract.py`
- `server/production_ports.py`
- `server/packaged_stages.py`

**动作**

- [ ] 所有视频制作提示词开头固定加入中英文高权重规则：不得复制源视频人物身份、产品/App、可见文字、原声、旁白或对话，只允许继承镜头、动作、节奏、构图和环境关系。
- [ ] 新模特参考图是人物身份唯一权威；新产品/App 证据是产品内容唯一权威。
- [ ] 原视频继续作为动作、镜头、时长和节奏参考，不能删除。
- [ ] 多页故事板、模特图、产品图、音频和源片段使用结构化引用绑定，提交前验证数量、顺序、SHA 和角色。
- [ ] 音频 sidecar 不能只依赖调用者传入的可变字典；必须绑定服务端可验证的 job/审计记录或签名摘要。

**验收**

- 缺新模特权威、引用错位或伪造完整 audio sidecar 时，在任何 Provider HTTP 调用前拒绝，transport 调用次数为零。
- 源视频人物不会成为替换任务的身份参考。

### 任务 7：把技术信息屏蔽接入部署包公共出口

**新增/合并文件**

- 新增 `server/public_content_policy.py`
- 小范围修改 `server/public_fastapi_router.py`
- 小范围修改 `server/public_errors.py`
- 小范围修改 `server/public_job_projection.py`
- 修改用户脚本文档和故事板发布点

**动作**

- [ ] 文字脚本、故事板可见文字、公共 JSON、错误信息和最终元数据统一经过 fail-closed 检查。
- [ ] 用户侧禁止出现模型名、供应商名、内部工具名、Stage 名、工作流 ID、节点号和内部流程说明。
- [ ] 内部受保护日志仍保留真实诊断信息，便于服务端维护。
- [ ] 只在现有公共文件中接入守卫，不用本地文件覆盖部署版公共 API。

**验收**

- 用户可见内容零技术名泄漏。
- 服务端内部日志仍能定位具体 Provider/工作流错误。

### 任务 8：同步 60 秒 QC 和安全性能优化

**主要文件**

- `server/real_capabilities.py`
- 新增 `server/ffmpeg_encoding.py`
- `server/timeline_renderer.py`
- `server/packaged_stages.py`
- `.env.example`
- `deployment/docker-compose.yml`

**动作**

- [ ] 最终视频可读后启动统一 QC deadline，硬上限 60 秒。
- [ ] 到达上限立即停止语义扩展、重复审核和补充 QC，直接交付最终视频。
- [ ] 保留最基本的“文件存在、可解码、时长有效”检查，避免交付损坏文件。
- [ ] 同步可选 NVENC 和 FFmpeg 快速编码，失败时安全回退软件编码。
- [ ] 两页故事板、独立 Provider 查询/下载在无依赖时并行，禁止并行改变 Stage 顺序。
- [ ] 保持 route-first，不重新启用全量深度分析。

**验收**

- QC 实际墙钟时间不超过 60 秒。
- 快速路线不触发无关工具；生成质量约束、控制图和故事板引用不减少。

### 任务 9：合并配置、Compose 和依赖，不碰真实 `.env`

**动作**

- [ ] 以部署版 `.env.example`、Compose 和 requirements 为主，取两边变量与依赖的并集。
- [ ] 保留微软侧 GPT、Redis、OSS、TTL、公共 HTTP、UI 开关和临时清理配置。
- [ ] 加入最新 Whisper、TTS、歌曲口型、语言口型、QC budget 和 FFmpeg 配置映射。
- [ ] `oss2==2.19.1` 必须保留。
- [ ] MinIO 继续只作内部临时存储，Compose 不暴露 9000/9001；Redis 也不公开端口。
- [ ] 不把 `.env.example` 覆盖到真实 `.env`；缺失的新变量写入维护文档，由服务端按说明补充。

**微软 GPT 说明**

当前代码审计显示它使用 OpenAI-compatible Responses 调用方式，而不是独立 Azure SDK。若服务端当前通过微软侧兼容代理已经跑通，本次必须字节级保留该接入方式，不擅自改成 Azure SDK、改 header 或改 URL。是否增加 Azure OpenAI 直连属于另一项需求，不纳入本次同步。

### 任务 10：分层验证，避免反复和付费测试

**第一层：静态与离线定向验证**

- [ ] `python -B` 编译所有变更 Python 文件。
- [ ] pytest 禁用 cache provider，并设置不写 `.pyc`。
- [ ] 只运行本次变更和受保护能力的定向测试，不反复跑全量测试。
- [ ] `docker compose config` 验证变量映射。
- [ ] 严格 bundle verifier 验证公共 API、OSS、Redis、运行时文件和 manifest 闭包。

**第二层：无付费公共 HTTP smoke**

- [ ] 启动 staging Compose。
- [ ] 使用 fake/shadow Provider 跑创建、查询、脚本审核、故事板审核、成功投影、错误投影和清理。
- [ ] 验证 HTTP 入参仍然只需业务 URL/选项，不暴露内部 SHA、MIME、revision、Provider 参数。

**第三层：受控真实接口验证**

仅在离线层全部通过并获得用户确认后执行：

- [ ] 微软侧 GPT 一次最小结构化请求。
- [ ] 每个发生变化的 RunningHub 工作流各一次受控请求，防止重复创建付费任务。
- [ ] OSS 使用专用测试前缀做 put/head/get，不触碰现有对象。
- [ ] 最后只跑一条小素材复合链路验证真实闭环。

### 任务 11：清理、重新生成 manifest 和打包

**动作**

- [ ] 删除 staging 中的 `__pycache__`、`.pyc`、`.pytest_cache`、历史生成媒体、任务目录、旧 ZIP 和 Provider 临时返回文件。
- [ ] 生产包不包含测试缓存、真实测试素材和历史计划文档。
- [ ] 重新生成 `bundle_manifest.json`，不能采用任一侧旧 manifest。
- [ ] 运行最终 verifier 后生成新的不可变 ZIP 和 SHA-256。
- [ ] 原部署包继续保留，不覆盖原文件。

**建议交付名**

- `usfr-video-service-2026-08-03-deploy-windows-latest-sync.zip`
- `usfr-video-service-2026-08-03-deploy-windows-latest-sync.sha256.txt`
- `2026-08-03-usfr-deploy-sync-difference-report.md`
- `USFR-服务端增量更新与回滚手册.md`

### 任务 12：旁路部署和回滚

- [ ] 切换前暂停新任务并排空旧 Worker，避免新旧 Stage DAG 共用 Redis。
- [ ] 新包和新镜像使用独立版本号，不覆盖旧镜像 tag。
- [ ] Redis、MinIO、OSS 和数据卷原地保留，禁止 `docker compose down -v`。
- [ ] 先启动新 `api/worker/sweeper`，通过 ready 和公共 smoke 后再开放新任务。
- [ ] 回滚只切回旧包/旧镜像，继续使用原 `.env` 和原存储。
- [ ] 新版本产生的测试任务与旧 Worker 隔离，避免回滚时错误接管。

## 五、最终验收标准

只有同时满足以下条件，才算同步完成：

1. 原部署 ZIP、真实 `.env`、微软侧 GPT 配置、Redis keyspace 和 OSS bucket/prefix 均未改变。
2. 公共业务接口仍然只有三个，入参和出参没有重新复杂化。
3. OSS 继续返回永久 URL，任务清理不会删除最终视频。
4. source-only、SSRF、鉴权、幂等、Redis 失败提交和现有 bugfix 全部通过回归。
5. 只改语言不再进入故事板和新视频生成。
6. Whisper 仅处理非音乐语音，并直接接收原视频。
7. 歌曲、正常口播、只改语言口播和旁白不会串用工作流。
8. 内部替换控制图一次生成、一次视觉验收，导演故事板必须引用它。
9. 故事板固定模板、1–2 页分页、一次整组确认和多页完整绑定全部生效。
10. 新模特/新产品在生成前成为唯一内容权威，不能再由源视频人物覆盖。
11. 用户可见内容不泄露模型、供应商和内部流程信息。
12. QC 最长 60 秒；缓存、历史文件和生成中间文件不进入发布包。
13. 新 ZIP、镜像、manifest 和 SHA 可以一一对应，并有可执行回滚手册。

## 六、明确不做

- 不修改原 ZIP。
- 不整目录同步，不用本地 `server/` 覆盖部署 `server/`。
- 不修改或打印真实 `.env`。
- 不重建 Redis、MinIO、OSS，不清空队列或数据卷。
- 不把本地 11 个内部接口重新暴露给用户。
- 不改变微软 GPT 当前已经跑通的接入协议。
- 不在计划审核阶段联网或发起任何付费任务。
- 不把测试缓存、历史生成文件、历史方案文档打入新生产包。

## 七、建议执行方式

用户确认本计划后，再按任务 0–12 顺序执行。每完成一个功能簇，只运行该簇与受保护基础设施的定向验证；全部离线验证通过后再决定是否进行一次受控真实接口测试。
