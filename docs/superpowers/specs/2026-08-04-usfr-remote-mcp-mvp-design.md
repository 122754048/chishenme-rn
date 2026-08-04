# USFR 远程 MCP MVP 设计

日期：2026-08-04
状态：已完成对话设计确认，等待用户审阅书面规格

## 1. 目标

为公司内部不超过 20 名员工提供一个远程托管的 USFR MCP 服务。员工通过 Codex 或 ChatGPT 调用服务，底层 OpenAI、RunningHub、OSS 等 API 使用服务端密钥并由公司承担费用。

MVP 同时支持：

- 单条素材复刻；
- 同一原视频的批量复刻；
- 原片和分析缓存复用；
- 脚本、导演故事板和最终 MP4 的归档；
- 每人每日额度、公司月预算和可配置并发；
- 管理员创建/停用账号和转移员工资产。

## 2. 不可变边界

以下本地 Skill 禁止任何修改：

`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`

新系统必须建立为独立工程。实现时允许从部署 ZIP 复制代码作为新工程基础，但不得向本地 Skill 目录写入任何文件。

基础部署包：

`C:\Users\zhaocx04\Documents\我的POPO\usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2.zip`

该 ZIP 已包含 Linux Docker/Compose、FastAPI、Worker、Redis、MinIO、OSS 和 Provider 配置入口，但不包含 MCP、账号、批量编排、域名 HTTPS 或管理后台。

ZIP 内 `.env` 的多个秘密字段存在非空值。新工程不得复制这些值。部署前应创建或轮换生产密钥，并确保 ZIP 不被分发给员工。

## 3. 用户与 MVP 安全范围

### 3.1 用户范围

- 公司内部使用；
- 不超过 20 名员工；
- 不开放公开注册；
- 管理员创建和停用账号。

### 3.2 MVP 包含的账号能力

- 独立用户名和密码；
- 密码使用安全哈希保存；
- 登录失败限流；
- 管理员重置密码、停用账号和强制失效访问；
- 登录、任务、审批、额度和资产转移审计日志。

### 3.3 MVP 暂不包含

- 企业 SSO；
- MFA/TOTP；
- 单设备或单会话限制；
- IP 白名单；
- 设备绑定；
- 复杂账号防扩散和异常登录风控；
- 公开客户注册和外部商业计费。

## 4. 推荐部署架构

MVP 使用单台 Linux 云服务器，通过 Docker Compose 部署：

1. Caddy 或 Nginx：域名、HTTPS、反向代理、上传限制；
2. MCP Gateway：Streamable HTTP `/mcp`、账号、权限、额度和秘密隔离；
3. Batch Orchestrator：批量预检、样片放行、自动任务和并发控制；
4. Source Library：原片、分析缓存、归属和复用索引；
5. PostgreSQL：账号、Source Master、批次、额度、永久资产索引和审计记录；
6. USFR API：从基础 ZIP 复制的 Jobs API；
7. Redis：任务状态、队列、检查点、幂等和短期权威；
8. Worker/Sweeper：分析、Provider、FFmpeg、QC 和清理；
9. MinIO：处理中的临时对象；
10. 阿里云 OSS：原片、分析缓存和永久产物；
11. 外部 Provider：OpenAI、RunningHub、Seedance 及所需分类/评估服务。

建议初始服务器规格为 16 vCPU、32 GB 内存、500 GB SSD。服务器区域优先香港或新加坡，最终应根据 OpenAI、RunningHub 和 OSS 的网络实测确定。

架构边界必须允许后期把 Worker、Redis 和对象存储拆分到独立服务，而不改变 MCP 工具契约。

PostgreSQL 属于新 MCP 工程，不修改原 USFR 的“无 SQL 临时 Job”边界。MCP 只在 PostgreSQL 中保存长期产品元数据；USFR Job 的执行状态仍由原 Redis JobStore 和 Work Queue 负责。两者通过稳定的 `job_id`、`batch_id` 和非敏感句柄关联。

## 5. 统一的单条/批量入口

MCP 提供统一复刻入口，不把批量功能设计成独立产品。

执行模式：

- `single`：单条复刻；
- `batch`：批量复刻；
- `auto`：默认模式，只给出建议，不直接产生付费任务。

自动判断规则：

- 用户明确说“批量”“分别生成”“每个各生成一条”等，建议批量模式；
- 用户主动打开批量开关，建议批量模式；
- 只有一套素材时，建议单条模式；
- 同类素材有多份但用途存在歧义时，返回 `clarification_required`；
- 多张同一人物的多角度参考不能被自动解释为多个批量人物；
- 自动判断只能生成预检摘要，不得直接创建正式任务。

## 6. 公开输入契约

新 MCP 对外展示八个固定素材槽位：

| 槽位 | 必填 | 说明 |
| --- | --- | --- |
| `source_video` | 是 | 原视频 |
| `new_product_image` | 否 | 产品目标证据 |
| `new_model_image` | 否 | 人物目标证据 |
| `ui_screenshot` | 否 | UI 目标证据 |
| `app_store_url` | 否 | 官方 App Store / Google Play URL |
| `ui_operation_video` | 否 | 不透明 UI 操作视频 |
| `tail_video` | 否 | 不透明尾卡视频 |
| `background_music` | 否 | 固定为音乐；单任务只能绑定一首 |

`output_language` 是独立可选参数，不属于素材槽位。

为保持复制工程的原音乐执行结构，MCP 在内部把 `background_music` 投影为原契约的 `extensions.background_music`，继续复用现有歌曲分类、源音乐窗口、歌曲口型、音频路由和 QC 规则。

## 7. 单条任务流程

单条任务保持原有内容流程：

1. 预检并展示确定性执行摘要；
2. 用户确认摘要；
3. 创建和启动 Job；
4. 分析或复用 Source Master；
5. 审批实际脚本 Markdown；
6. 审批实际导演故事板 PNG；
7. Provider 生成、合成和 QC；
8. 交付最终 MP4。

长任务使用异步句柄。MCP 工具快速返回 `job_handle`，状态通过查询工具获取。

## 8. 批量意图契约

批量路线必须完全由用户明确需求决定。系统禁止自行排列组合、扩充、循环、截断或猜测素材对应关系。

支持的意图包括但不限于：

- 批量换不同人物；
- 批量换不同歌曲；
- 批量换不同输出语言；
- 用户明确要求的一一对应换人物和歌曲；
- 用户明确要求的一一对应换人物和语言；
- 用户明确要求的一一对应换歌曲和语言；
- 用户明确要求的一一对应换人物、歌曲和语言。

示例：

- 一个原视频加 20 首歌曲，明确生成 20 条换歌任务；
- 10 个人物加 10 首歌曲，只有用户明确要求一一对应时才生成 10 条；
- 10 个人物加 10 首歌曲不得自动生成 100 条；
- 素材数量或对应关系不明确时，停在预检并要求用户说明。

每次批量任务必须先生成确定性执行摘要，例如：

> 本批次使用同一个原视频，将上传的 20 首歌曲分别替换到 20 个任务中，共生成 20 条视频；不更换人物，不更改语言，不做排列组合。

用户确认摘要前：

- 不创建正式批次；
- 不分析新增素材；
- 不生成故事板；
- 不调用付费 Provider。

单批次最多 20 条。

## 9. 批量样片放行流程

批量清单第一条固定为 Pilot，不允许改用其他条目充当样片。

流程：

1. 用户确认批次执行摘要；
2. 冻结完整 Batch Manifest 和 SHA-256；
3. 第一条完成脚本审批；
4. 第一条完成导演故事板审批；
5. 第一条完成 Provider、口型、合成和 QC；
6. 用户查看并批准第一条最终 MP4；
7. 签发不可变 `batch_execution_authorization`；
8. 第 2–20 条自动生成脚本、故事板、MP4 和 QC，不再等待人工审批。

`batch_execution_authorization` 至少绑定：

- batch ID；
- owner user ID；
- Batch Manifest SHA；
- Batch Intent；
- Pilot 脚本 SHA；
- Pilot 故事板 SHA；
- Pilot 最终 MP4 SHA；
- 允许变化的素材集合；
- 额度和有效状态。

批次清单、对应关系或超出 Batch Intent 的素材发生变化时，授权立即失效。

## 10. 样片修改

样片最终 MP4 不满意时：

- 整个批次继续暂停；
- 用户填写修改意见；
- 只重新执行第一条受影响阶段；
- 不启动后续任务；
- 保留历史样片版本供对比；
- 最新 MP4 再次等待确认。

每条修改意见必须明确标记作用域：

- `batch_wide`：更新批次共享模板，后续任务继承；
- `pilot_only`：只影响第一条样片。

作用域与修改内容明显冲突时必须要求用户重新确认，不能自行判断传播范围。

## 11. 并发、部分成功和重试

- 单批次默认并发 5 条；
- 管理员可在 1–20 之间调整；
- 完成一条后立即补充下一条；
- 用户级、批次级和公司级并发限制共同生效；
- 单条失败不阻塞其他任务；
- 成功任务永不因其他任务失败而重新生成；
- 允许只重试失败任务；
- 修改失败任务的素材后创建新的变体版本；
- Provider 明确失败可安全重试；
- Provider 状态不明时进入对账，禁止盲目重复提交。

## 12. Source Library 与分析缓存

每份原片建立一个 `Source Master`，归属于最初上传员工。

缓存命中条件：

```text
owner_user_id
+ source_sha256
+ analysis_profile
+ analyzer_model_sha256
+ analysis_contract_version
```

只有所有字段完全一致才复用分析。

同一员工再次使用同一原片：

- 跳过完整原片分析；
- 复用 Cuts、动作、镜头、音频窗口、Overlay、关键帧、时间线和 Source Fidelity 基础合同；
- 新人物、新歌曲、新语言仍分别执行目标绑定、歌曲检查、故事板/Prompt、Provider、合成和 QC。

不同员工上传相同原片：

- 不得命中其他员工缓存；
- 不得提示其他员工已经上传过该文件；
- 独立创建 Source Master 和分析记录。

分析模型或契约升级时不覆盖旧缓存，而是保存新版本。任务可按兼容规则复用旧缓存或执行新版分析。

## 13. 存储和生命周期

持续保存，直到员工或管理员主动删除：

- 原片；
- 原片指纹和分析缓存；
- 文字脚本；
- 导演故事板；
- 最终 MP4。

临时保存并按任务生命周期清理：

- Provider 下载文件；
- FFmpeg 临时切片；
- 内部控制图；
- 中间 QC 文件；
- 临时工作目录；
- 签名 URL。

删除原片后：

- 原片对象不可继续直接复刻；
- 默认保留分析缓存、脚本、故事板和最终 MP4；
- 如需再次生成且流程必须使用原片像素/音频，员工需要重新上传原片。

管理员可把员工的 Source Master、分析缓存、任务、脚本、故事板和成片整体转移给另一名员工。转移采用所有权变更而不是复制，并保留完整审计记录；转移后原员工立即失去访问权。

## 14. MCP 工具边界

### 14.1 素材和 Source Library

- `create_upload_session`
- `complete_asset_upload`
- `list_source_masters`
- `get_source_master`
- `delete_source_master`

### 14.2 统一复刻入口

- `preview_replication`
- `confirm_and_create_replication`
- `get_replication`

`preview_replication` 返回：

- `suggested_mode`：`single`、`batch` 或 `clarification_required`；
- `batch_intent`；
- `task_count`；
- `execution_summary`；
- `requires_confirmation`。

### 14.3 审批和修改

- `revise_script`
- `approve_script`
- `revise_storyboard`
- `approve_storyboard`
- `revise_pilot`
- `approve_pilot_result`

### 14.4 批次运行

- `get_batch`
- `retry_failed_batch_items`
- `cancel_queued_batch_items`

### 14.5 管理端

- `create_user`
- `disable_user`
- `transfer_user_assets`
- `get_usage_summary`
- `update_usage_limits`

工具必须使用明确输入/输出 Schema、稳定 ID 和准确的只读/写入安全标记。不得返回 Provider Key、Job capability、内部 Prompt、完整 Provider payload 或其他秘密。

## 15. 费用控制

默认策略：

- 每位员工每天最多 50 条；
- 公司每月最多 ¥10,000；
- 单批次最多 20 条；
- 单批次默认并发 5。

所有策略必须由管理员后台配置，不能写死在业务代码中。

付费 Provider 调用前检查：

1. 账号状态；
2. Source/任务所有权；
3. 每日条数；
4. 公司月预算；
5. 已结算成本与已冻结预计成本；
6. 请求幂等 SHA；
7. 批次授权；
8. Provider attempt 状态。

预算分级：

- 70%：通知管理员；
- 90%：高优先级通知，可配置降低并发或限制新批次；
- 100%：停止新的付费调用。

达到预算上限不应重复取消已经成功提交的 Provider 任务。Provider 状态不明的任务仍先对账。

## 16. API Key 和能力令牌安全

- OpenAI、RunningHub、OSS 等 Key 只保存在服务器部署 Secret 或环境变量；
- 开发、测试和生产使用不同 Key；
- 日志过滤 `Authorization`、API Key、签名 URL 和 Provider 私有响应；
- Key 不进入 Skill、插件包、前端、MCP 工具参数或结果；
- MCP 用户认证与 Provider Key 完全分离；
- 底层 Job capability 只由 MCP 服务端保存或封装；
- 员工和模型只能得到非敏感 `job_handle` / `batch_handle`；
- 对 Provider 请求实施超时、限流、幂等和预算熔断；
- ZIP 若曾离开受控设备，应轮换其中可能存在的真实密钥。

## 17. 失败处理

- 输入或批量意图不明确：停在预检，无正式任务和付费调用；
- 上传失败：允许恢复上传，不创建不完整素材记录；
- 分析失败：保留有效检查点，重试当前阶段；
- 脚本/故事板失败：只重试对应阶段；
- Provider 明确失败：记录失败并允许安全重试；
- Provider 状态不明：进入待对账，禁止直接重提；
- QC 失败：禁止交付，保留诊断并按恢复规则重跑；
- 批次部分失败：其他任务继续，失败任务独立处理；
- 服务重启：通过 Redis 检查点、对象存储和 Provider attempt 恢复；
- 成功 Provider 任务、成功变体和已确认产物不得因重启重复执行。

公开错误不得包含 Provider、模型、工作流 ID、节点 ID、Key、内部 Prompt 或服务端路径。

## 18. 部署前置条件

上线前必须补齐：

- Linux 云服务器；
- 域名和 HTTPS；
- MCP Streamable HTTP 端点；
- 新账号、额度、批量编排和 Source Library 应用层；
- PostgreSQL 数据库及每日备份；
- OSS 私有 Bucket、访问策略和签名 URL；
- 新的生产 OpenAI、RunningHub、OSS 凭证；
- 音乐 `song` / `non_song` 分类服务。

现有 ZIP 中以下音乐分类环境变量为空，批量换歌或单条上传音乐的生产路线不能在缺失它们时上线：

- `USFR_UPLOADED_AUDIO_CLASSIFIER_ENDPOINT`
- `USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_ID`
- `USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_SHA256`
- `USFR_UPLOADED_AUDIO_CLASSIFIER_API_TOKEN`

## 19. MVP 验收测试

### 19.1 单条任务

- 八槽位逐项覆盖；
- `background_music` 正确投影到现有音乐执行结构；
- song/non_song 分类；
- 歌曲口型、普通对白和多语言口型不串路；
- 脚本和故事板审批；
- 最终 MP4 下载和归档。

### 19.2 批量任务

- 批量换人；
- 批量换歌；
- 批量换语言；
- 用户明确的一一对应组合；
- 绝不产生排列组合；
- 摘要未确认时 Provider 调用数为 0；
- 第一条样片未批准时后续 Provider 调用数为 0；
- 样片修改的 `batch_wide` 与 `pilot_only` 传播正确；
- 默认并发 5；
- 单条失败不阻塞其他条；
- 只重试失败条目；
- 状态不明时只对账不重提。

### 19.3 缓存和权限

- 同员工、同原片、同分析版本命中缓存；
- 不同员工相同 SHA 不共享；
- 不泄露跨员工缓存存在性；
- 管理员资产转移完整且可审计；
- 转移后原员工立即失去访问权。

### 19.4 费用和秘密

- 每人每日 50 条默认限制；
- 公司月预算 ¥10,000 熔断；
- 冻结额度避免并发超支；
- 配置修改即时作用于新任务；
- MCP 结果、错误、日志和归档不包含 API Key；
- Provider request SHA 防止重复扣费。

### 19.5 部署和恢复

- HTTPS 和 MCP Inspector 连通；
- API、Worker、Redis、MinIO、OSS readiness；
- 服务重启后任务恢复；
- 真实单任务；
- 真实批量样片；
- 真实 5 并发；
- 失败与 Provider 对账演练；
- 临时文件清理和永久产物保留。

## 20. 上线策略

1. 本地和容器单元/契约测试；
2. Shadow 环境真实单任务验证；
3. Shadow 环境真实批量样片验证；
4. 5 并发、部分失败、重启恢复和预算统计验证；
5. 少量内部员工试用；
6. 扩展到最多 20 名员工。

在真实 Provider、音乐分类、合成、QC、费用统计和恢复测试全部通过前，不将系统标记为生产可用。

## 21. 明确非目标

- 修改本地 USFR Skill；
- 将你的生产 API Key 分发给员工；
- 自动排列组合批量素材；
- 对外公开注册；
- 外部客户计费、订单、订阅或发票；
- 企业 SSO/MFA/设备限制；
- 多区域高可用或自动扩缩容；
- 在 MVP 中重写 USFR 的分析、Seedance、合成和 QC 核心。

## 22. 设计完成标准

该设计完成的判断标准是：

- 单条和批量共享统一入口；
- 用户明确意图是批量组合的唯一权威；
- 第一条最终 MP4 批准前，后续任务绝不启动；
- 本地 Skill 保持字节不变；
- 同员工复用分析，跨员工严格隔离；
- 服务端 Key 不暴露；
- 额度、并发和月预算可配置；
- 单条失败不拖累批次，且不重复扣费；
- 单台 Linux Docker Compose 可以交付 MVP，并保留后期拆分能力。
