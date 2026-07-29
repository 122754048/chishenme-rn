# USFR 服务端简化公共 HTTP API 设计

日期：2026-07-29

## 1. 目标

为工程化部署后的 USFR 视频复刻服务增加一层极简公共 HTTP API，供 Web 服务提交阿里云 OSS 素材地址、查询进度、修改或确认文字脚本与故事板，以及取得最终视频。

公共调用方只提交素材 URL 和真实业务选项。SHA-256、文件大小、MIME、时长、分辨率、FPS、版本号、revision、审批摘要、对象键、上传作用域、Provider 任务信息和 CAS 数据全部由服务端生成并隐藏。

本设计只简化对外接口，不删除或弱化现有 USFR 的路由判断、素材拆解、脚本和故事板审核、深度复刻、质量检测、幂等保护、付费任务去重、RunningHub、Seedance、TTS、ASR、对口型、音频以及 UI 重建能力。

## 2. 范围与非目标

### 2.1 本次范围

- 在现有 FastAPI 服务内部增加公共 API 外壳。
- 公共 OpenAPI 只展示三个接口。
- 从允许的 OSS URL 自动导入素材并自动启动任务。
- 用任务级 `access_token` 保护后续请求。
- 对外只保留文字脚本和故事板两个审核节点。
- 将最终视频上传到阿里云 OSS，并返回永久可访问 URL。
- 通过真实 Docker 部署、真实 OSS、真实 GPT、RunningHub、Seedance 和媒体工作流验证接口。

### 2.2 非目标

- 不建设账号、用户、租户、权限、订单、计费、历史列表或运营后台。
- 不把 GPT、RunningHub 或 Seedance 的内部参数暴露给 Web。
- 不允许客户端跳过路由、分析、审核或质量门禁。
- 不删除现有内部 Job、Artifact、SHA、revision、CAS、Provider intent 和审批约束。
- 不改变本地 Skill 的业务能力和生成效果。

## 3. 总体架构

采用“公共外壳 + 现有内部引擎”结构：

```text
用户浏览器
  -> Web 服务将原始素材永久上传到阿里云 OSS
  -> Web 调用 USFR 三个公共接口
  -> 公共 API 外壳校验 URL、Token 和业务字段
  -> 导入器将媒体流式复制到任务级临时 MinIO
  -> 服务端探测媒体并生成内部素材清单
  -> 现有 USFR 路由、分析、脚本、故事板、生成和 QA 引擎
  -> 最终 MP4 上传到阿里云 OSS
  -> 公共 API 返回永久结果 URL
```

现有复杂接口不再暴露到公网，也不出现在公共 OpenAPI。内部引擎继续使用现有强约束数据结构。若内部 HTTP 路由仍需保留用于部署内调试，它们必须挂载到私有应用或私有网络，不能与公共监听地址共享公开入口。

## 4. 存储与素材生命周期

### 4.1 阿里云 OSS

- Web 负责将用户原始素材上传到 OSS。
- Web 将永久可访问 URL 传给 USFR。
- USFR 不删除、不移动、不覆盖原始 OSS 对象。
- 最终视频由 USFR 上传到 OSS，并永久保留。
- 原始素材 URL 和最终视频 URL 不受任务 Token 过期影响。

### 4.2 临时 MinIO

- 每个 OSS 媒体文件只导入一次。
- 导入位置使用任务隔离前缀，Worker 只读取稳定的 MinIO 副本。
- 临时对象包括下载副本、关键帧、音频、ASR 文件、故事板中间件、分段视频、Seedance 输入输出和合成中间文件。
- 临时对象在任务结束后按部署配置清理，不作为长期素材库。
- 默认 `USFR_TEMPORARY_RETENTION_SECONDS=0`：任务进入 `completed` 或不可恢复的 `failed` 后立即进入任务级临时媒体清理队列；清理失败必须重试并告警。正在处理或等待脚本/故事板确认的任务不能提前清理。

### 4.3 服务端自动生成的内部信息

导入媒体后，服务端自动计算或探测：

- SHA-256
- 文件大小
- 真实 MIME 和封装格式
- 视频或音频时长
- 视频宽高、画幅和 FPS
- 音视频流信息
- 内部对象键、素材版本和 revision

这些信息用于稳定读取、缓存、质量校验、审批绑定、重复付费保护和故障恢复，但不由 Web 提交，也不发送给 GPT 或 RunningHub，除非某个下游媒体接口执行任务确实需要对应媒体属性。

## 5. 公共请求模型

`source_video` 必传。除 `source_video` 外，必须至少提交一个业务选项。媒体字段传永久 OSS URL；`app_store_url` 传 Apple App Store 或 Google Play 官方地址。

```json
{
  "source_video": "https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4",
  "new_product_images": [
    "https://bucket.oss-cn-hangzhou.aliyuncs.com/product.jpg"
  ],
  "new_model_images": [
    "https://bucket.oss-cn-hangzhou.aliyuncs.com/model.jpg"
  ],
  "ui_screenshots": [
    "https://bucket.oss-cn-hangzhou.aliyuncs.com/ui-1.jpg"
  ],
  "app_store_url": "https://apps.apple.com/app/id000000000",
  "ui_operation_video": "https://bucket.oss-cn-hangzhou.aliyuncs.com/ui-operation.mp4",
  "tail_video": "https://bucket.oss-cn-hangzhou.aliyuncs.com/tail.mp4",
  "audio": "https://bucket.oss-cn-hangzhou.aliyuncs.com/song.mp3",
  "output_language": "en"
}
```

除 `source_video` 外的所有字段均为可选。允许组合提交。公共外壳将这些字段映射到现有内部固定槽位：

| 公共字段 | 内部槽位或业务含义 |
|---|---|
| `source_video` | `source_video` |
| `new_product_images` | `new_product_image` |
| `new_model_images` | `new_model_image` |
| `ui_screenshots` | `ui_screenshot` |
| `app_store_url` | `app_store_url` |
| `ui_operation_video` | `ui_operation_video` |
| `tail_video` | `tail_video` |
| `audio` | 现有上传音频/`background_music` 入口 |
| `output_language` | 现有目标语言入口 |

公共请求禁止接收本地路径、Base64 媒体、客户端 Provider Key、最终 Seedance Prompt、内部 revision 或任意未注册素材列表。

## 6. 三个公共接口

### 6.1 创建并自动启动任务

`POST /api/v1/jobs`

Web 自动生成并发送请求头：

```http
Idempotency-Key: <UUID>
```

请求体只包含上一节定义的素材 URL 和业务选项。同步阶段只做 JSON、字段、URL 格式和域名校验。校验通过后立即创建任务，异步导入素材；不再调用单独的 `/start`。

响应：

```json
{
  "job_id": "job_123",
  "access_token": "xxxxx",
  "status": "importing"
}
```

原始 Token 只出现在成功创建响应及其完全相同的幂等重放响应中。服务端使用部署密钥、`job_id` 和 `Idempotency-Key` 安全派生稳定 Token，并只保存 Token 哈希；因此网络重试可以再次取得同一个 Token，但数据库和日志不保存明文 Token。

### 6.2 查询任务

`GET /api/v1/jobs/{job_id}`

请求头：

```http
Authorization: Bearer <access_token>
```

普通处理中：

```json
{
  "job_id": "job_123",
  "status": "processing",
  "stage": "source_analysis"
}
```

等待文字脚本审核：

```json
{
  "job_id": "job_123",
  "status": "waiting_review",
  "stage": "script",
  "review": {
    "type": "script",
    "content": "当前生成的两段式 Markdown 文字脚本"
  }
}
```

等待故事板审核：

```json
{
  "job_id": "job_123",
  "status": "waiting_review",
  "stage": "storyboard",
  "review": {
    "type": "storyboard",
    "image_urls": [
      "https://example.com/storyboard-1.jpg"
    ]
  }
}
```

完成：

```json
{
  "job_id": "job_123",
  "status": "completed",
  "result_url": "https://bucket.oss-cn-hangzhou.aliyuncs.com/final/job_123.mp4"
}
```

失败：

```json
{
  "job_id": "job_123",
  "status": "failed",
  "error": {
    "code": "PROCESSING_FAILED",
    "message": "视频生成失败，请重新提交任务",
    "retryable": true
  }
}
```

### 6.3 修改或确认当前审核内容

`POST /api/v1/jobs/{job_id}/review`

请求头同查询接口。

确认当前脚本或故事板：

```json
{
  "action": "approve"
}
```

修改文字脚本：

```json
{
  "action": "revise",
  "content": "用户修改后的两段式 Markdown 文字脚本"
}
```

修改故事板：

```json
{
  "action": "revise",
  "content": "保持人物服装不变，第二个镜头产品展示得更清楚"
}
```

当 `review.type` 为 `script` 时，`content` 表示用户修改后的完整两段式 Markdown 文字脚本；当 `review.type` 为 `storyboard` 时，`content` 表示故事板修改要求，服务端据此重新生成故事板。服务端自动定位当前待审核 revision、执行 CAS、绑定审批摘要并推进任务，客户端不提交审核类型、版本号、SHA 或 revision。

重复确认返回当前任务状态，不重复推进阶段或创建付费任务。审核顺序固定为先文字脚本、后故事板；未确认前一项时不能进入下一项。

## 7. 对外状态模型

公共状态只保留：

- `importing`：正在从 OSS 导入并校验素材。
- `processing`：正在分析、生成或合成。
- `waiting_review`：等待用户处理文字脚本或故事板。
- `completed`：最终视频已上传 OSS。
- `failed`：任务不能继续。

可选 `stage` 用于 Web 展示进度：

- `source_analysis`
- `script_generation`
- `script`
- `storyboard_generation`
- `storyboard`
- `video_generation`
- `finalizing`

所有路线都必须经过文字脚本和故事板两个用户审核节点，包括只改语言、只替换 UI 操作视频、只替换尾部视频和只上传音频的路线。

## 8. 鉴权、生命周期与幂等

- `access_token` 与一个 `job_id` 绑定。
- 后续请求只在 `Authorization` Header 中发送 Token。
- Token 不进入 URL、响应日志或模型 Prompt。
- Token 在任务活动期间有效，任务完成或失败后继续有效 7 天。
- 任务元数据至少保留到 Token 过期；OSS 原始素材和最终视频永久保留。
- Token 不匹配、无效或过期时返回统一的 `ACCESS_DENIED`，不泄漏其他任务是否存在。
- `POST /api/v1/jobs` 的 `Idempotency-Key` 由 Web 自动生成，用户和 AI 无需填写。
- `Idempotency-Key` 必须是 Web 为一次用户提交生成的高熵 UUID，并持续复用于该次提交的网络重试。
- 同一 `Idempotency-Key` 和相同请求体的重试返回原任务及可重新派生的同一个 `access_token`，不重复导入或调用付费 Provider。
- 同一 `Idempotency-Key` 携带不同请求体时返回 `INVALID_REQUEST`，不能覆盖原任务。
- 内部继续计算素材和业务选项指纹，阻止网络重试、Worker 重放或 Provider 状态不明导致的重复付费调用。

## 9. URL 导入与安全边界

- 媒体 URL 只允许配置的阿里云 OSS 或自定义 OSS 域名。
- `app_store_url` 只允许 Apple App Store 和 Google Play 官方 HTTPS 域名。
- 禁止 `localhost`、环回地址、链路本地地址、私网 IP、Redis、MinIO 管理端口以及未授权域名。
- DNS 解析和每次重定向后都重新执行地址检查，阻止重定向到内网。
- 使用流式下载，不将整个文件一次性读入内存。
- 设置连接超时、总下载超时、最大跳转次数和按素材类型配置的大小限制。
- 根据真实文件头、解码结果和媒体探测判断格式，不能只相信扩展名或响应 MIME。
- 源视频超过 30 秒时，在 GPT、RunningHub、Seedance 或其他付费任务启动前拒绝。
- 导入成功后，所有 Worker 使用稳定的任务级 MinIO 副本，避免永久 OSS URL 在任务中途被外部替换影响当前任务。

## 10. UI 替换与重建

UI 路线支持三种提交方式，并且只处理原视频中已识别的 UI 区间。

### 10.1 只提交 UI 截图

- 从原视频时间轴找出 UI 操作区间。
- 只对这些区间执行详细 OCR、布局和交互分析。
- 使用截图作为页面视觉事实，重建按钮、文字、滑动、点击和页面切换。
- 输出严格服从原区间时长、画幅、位置、布局和转场。
- 只有确定性重建是最优解时，才启用受限的 `remotion_react_ui` 适配器；禁止全局运行 ShotCraft 或将其模板、镜头选择、BGM、SFX 引入主流程。

### 10.2 只提交 UI 操作视频

- 识别原视频所有 UI 操作区间并剪掉这些区间的旧 UI 画面。
- 对新 UI 操作视频做局部轻量分析，识别点击、滑动、输入、页面切换和有效操作范围。
- 若原视频存在多个 UI 区间，按操作事件顺序切分新 UI 操作视频并映射到各区间。
- 时长不一致时，依次删除等待和无效画面、按事件重切、做安全范围内的轻微变速，并保持原区间总时长不变。
- 能直接剪辑时禁止调用 Seedance 或 UI 生成模型。
- 新 UI 操作视频默认静音，只替换画面；最终声音继续由主流程中的解说、唱歌、TTS 和背景音乐控制。

### 10.3 同时提交 UI 截图和 UI 操作视频

- UI 操作视频负责真实动作与页面跳转。
- UI 截图负责页面样式、文字、按钮位置和关键状态校准。
- 操作视频缺失的首帧、尾帧或静态停留画面可由截图确定性补齐。
- 操作视频与截图样式冲突时，以 UI 截图为最终视觉标准。
- 直接映射仍然优先；只有直接剪辑不能满足原视频布局和时序时，才按区间启用受限重建。

### 10.4 审核衔接

文字脚本必须写明 UI 展示区间、页面、点击目标、滑动动作和页面文案。故事板必须展示新旧镜头对应、关键页面、操作视频到原时间轴的映射以及 UI 与人物或商品镜头的衔接。UI 不新增第三个审核节点，用户仍只审核文字脚本和故事板。

## 11. 业务路由保持不变

公共外壳只负责映射输入，不做全量深度分析。内部先执行轻量路由判断，再只运行当前需求需要的工具：

| 路线 | 关键行为 |
|---|---|
| 只改语言 | 文字脚本确认后执行 TTS、目标语言校验和最终对口型 |
| 替换人物 | 分析人物表演和镜头，只生成需要替换人物的区间 |
| 替换实物商品 | 分析商品外观、卖点和交互，只替换相关区间 |
| 替换 APP 产品 | 解析 App Store 证据，替换卖点、文案和必要 UI |
| UI 替换或重建 | 按第 10 节三种方式处理，禁止全局运行 UI 工具 |
| 替换尾部视频 | 按原时间轴处理画幅、转场和衔接 |
| 上传音频 | 源视频是唱歌 MV 时走唱歌、歌词和对口型流程；非 MV 时只替换背景音乐 |
| 复合需求 | 合并已提交选项，只执行命中的局部能力，不退回全量深度分析 |

音频路线继续使用现有轻量 MV/非 MV 判定、歌曲歌词提取、Seedance 脚本编译和必要的 RunningHub 对口型兜底逻辑。公共 API 不接收或返回这些内部工作流参数。

## 12. 错误处理与恢复

公共错误统一为：

```json
{
  "code": "SOURCE_UNAVAILABLE",
  "message": "无法下载源视频，请检查 OSS 地址是否有效",
  "retryable": true
}
```

公开错误码只保留：

- `INVALID_REQUEST`
- `ACCESS_DENIED`
- `SOURCE_UNAVAILABLE`
- `UNSUPPORTED_MEDIA`
- `SOURCE_TOO_LONG`
- `REVIEW_NOT_ALLOWED`
- `PROCESSING_FAILED`

URL 格式、域名和请求结构错误同步返回。实际下载、媒体探测和异步生成错误通过任务的 `failed` 状态返回。不得向外暴露堆栈、Provider 原始响应、MinIO 对象键、内部摘要或模型参数。

OSS 波动、GPT 超时、RunningHub 排队或暂时失败、Seedance 查询失败以及最终 OSS 上传失败由服务端自动重试，默认最多三次。重试从最近的已完成阶段继续，不能重新执行已经通过的脚本或故事板审核，也不能重复创建付费任务。确定不能恢复后才进入 `failed`。

## 13. 公共 OpenAPI

公共 OpenAPI 只能包含：

1. `POST /api/v1/jobs`
2. `GET /api/v1/jobs/{job_id}`
3. `POST /api/v1/jobs/{job_id}/review`

以下现有能力不能出现在公共 OpenAPI：

- `/start`
- script/storyboard revision 列表、单独 revise 和 revision-specific approve
- Provider reconcile
- 单独 result 接口
- `slots`
- `upload_scope`
- `object_key`
- `expected_version`
- `expected_sha256`
- revision number、approval SHA 和 line contracts
- SHA、大小、MIME、时长、分辨率、FPS
- Provider 任务 ID 和内部执行数据

## 14. 测试设计

### 14.1 快速自动测试

每次提交执行不产生模型费用的测试：

- 请求和响应契约测试。
- 公共 OpenAPI 端点白名单测试。
- Token 与任务绑定测试。
- `Idempotency-Key` 重放测试。
- 状态映射与审核顺序测试。
- 重复审核不重复推进测试。
- OSS 域名、SSRF、重定向、大小、格式和 30 秒限制测试。
- 内部复杂结构没有泄漏到公共响应或模型请求的测试。
- 模拟 Provider 的断点恢复和重复付费保护测试。

### 14.2 Docker 黑盒测试

使用最终 Docker Compose 包从外部 HTTP 客户端调用三个接口，不导入 Python 内部模块。验证：

- 一条命令启动服务及内置 MinIO。
- 创建任务后自动进入导入和处理阶段。
- Web 只提交 URL 和业务选项。
- OpenAPI 只显示三个公共接口。
- 脚本和故事板审核能够通过同一个 `/review` 接口完成。
- 完成后返回永久 OSS URL。

### 14.3 真实能力路线测试

使用真实 OSS 文件、真实 API Key 和真实 Provider 完成以下任务，而不只是验证可以提交：

1. 原视频 + 目标语言。
2. 原视频 + 人物图片。
3. 原视频 + 实物商品图片。
4. 原视频 + App Store URL。
5. 原视频 + UI 截图。
6. 原视频 + UI 操作视频。
7. 原视频 + UI 截图 + UI 操作视频。
8. 原视频 + 尾部视频。
9. 原视频 + 上传音频，并分别覆盖 MV 唱歌和非 MV 背景音乐判定。
10. 改语言 + 换人物 + 换 APP + 换 UI + 换尾部视频 + 上传音频的复合任务。

每个成功用例都必须经过创建、轮询、脚本审核、故事板审核、最终生成、OSS 上传和结果下载播放。UI 操作视频用例必须验证旧 UI 已被完全剪掉，没有旧 UI 闪帧、残留文字、新旧页面重叠或错误音轨。

### 14.4 真实异常测试

必须验证以下输入在任何付费任务前被拒绝：

- localhost、环回地址和内网 IP。
- Redis 与 MinIO 管理地址。
- 非白名单 OSS 域名。
- 重定向到内网的 URL。
- 伪装成媒体的文件。
- 超过大小限制的文件。
- 超过 30 秒的源视频。

还必须验证 Token 跨任务访问被拒绝、相同 `Idempotency-Key` 不重复扣费、重复确认不重复启动 Provider、临时 Provider 失败能够恢复。

### 14.5 测试报告

测试报告记录：

- 用例名称和提交的业务字段。
- `job_id`。
- 每个公开状态和阶段的时间。
- 脚本与故事板审核动作。
- 内部 Provider 任务 ID，仅保存在受限测试报告中。
- 是否发生重试和是否创建重复付费任务。
- 最终 OSS URL、下载结果和媒体播放校验。
- 原始 OSS 对象未被修改的校验结果。
- 临时 MinIO 对象生命周期和清理结果。

测试报告和日志不得保存 API Key 或原始 `access_token`。

## 15. 验收标准

- 公共请求体只包含素材 URL 和真实业务选项。
- `source_video` 必传，其他业务选项至少一个。
- 成功创建后自动导入并启动，不存在公共 `/start`。
- 公共 OpenAPI 只有三个端点。
- 创建任务只返回 `job_id`、`access_token` 和 `status`。
- 查询结果不暴露 SHA、版本、revision、CAS、对象键或 Provider 参数。
- 所有路线都必须经过文字脚本和故事板审核。
- UI 截图、UI 操作视频及两者同时提交均按第 10 节执行。
- UI 操作视频默认静音，并真正替换原视频 UI 区间。
- 30 秒限制和安全校验在任何付费调用前完成。
- 相同幂等请求和重复审核不会创建重复付费任务。
- 原始 OSS 素材与最终 OSS 视频永久保留，临时 MinIO 中间文件按规则清理。
- Docker 环境中的三个 HTTP 接口真实跑通。
- 第 14.3 节路线全部生成可下载、可播放的最终视频。
