# USFR 本地控制台

运行时 Skill 固定使用本仓库内的 `../usfr-server`，不依赖用户目录或外部安装路径；打包服务端时同样以该目录为源码边界。

这是 `universal-source-fidelity-replication` 的独立本地可视化工作台。它 **does not modify the Skill**：不会改写、复制、删除或覆盖现有 Skill 内的任何文件，也不会使用 OpenAI API。

浏览器只连接 `127.0.0.1`。GPT 分析、翻译、脚本和提示词推理继续由当前 Codex 客户端执行；控制台只保存本地任务、显示两个确认点、提交已验证的 Provider 请求、轮询和下载结果。

## 启动

1. 打开本目录：`C:\Users\zhaocx04\Documents\New project\usfr-local-console`。
2. 复制 `.env.example` 为 `.env`。
3. 只有需要提交 RunningHub 任务时，才在 `.env` 填写一行：`RUNNINGHUB_API_KEY=你的密钥`。不要把密钥输入浏览器，也不要把 `.env` 发给他人。
4. 商业批次需额外配置标准后端：`USFR_COMMERCIAL_BATCH_API_URL=http://127.0.0.1:8000/api/v1/commercial-batches`。未配置时，控制台可预检格式但会拒绝提交，不会改用本地文件队列。
5. 在 PowerShell 运行：`./start.ps1`。
6. 打开 `http://127.0.0.1:8765`。关闭 PowerShell 即停止服务。

首次运行时，启动脚本会检查 FastAPI、Uvicorn 和 multipart 依赖；缺少时仅安装本目录 `requirements.txt` 中固定版本的依赖。

## 操作步骤

1. 上传“爆款复刻原视频”。它是必传项，最长 30 秒。
2. 再上传至少一个可选槽位（商品图、模特图、UI 截图、App 商店页链接、UI 操作视频、尾卡视频），或选定输出语言。仅上传原视频时，按钮不可点击。
3. 创建任务后，点击“生成 Codex 任务包”，复制或下载 JSON，并粘贴到当前 Codex 对话。让 Codex 按既有 `$universal-source-fidelity-replication` Skill 处理并返回结构化 `codex_result.json`。
4. 将 JSON 结果包导入控制台。控制台会核验任务 ID、版本、输入 SHA-256 和阶段；任意不匹配都会拒绝，不会提交 Provider。
5. 正常的全量复刻只会停在两个位置：
   - “确认文字脚本”：可编辑并保存为新版本；确认后才进入故事板阶段。
   - “确认故事板”：只确认当前 SHA-256 对应的版本；确认后自动准备 Provider。
6. `provider_request_ready` 导入后，不会出现“确认提交”按钮。控制台会先永久保存请求 SHA-256，再向 RunningHub 创建一次任务；之后只轮询同一 task ID。
7. 成功后，控制台自动下载已登记的结果，并显示视频预览和下载按钮。

背景音乐是可选 `background_music` 扩展，不是第八固定槽位。仅“原视频加背景音乐”不会进入 language-only/TTS 快速通道：标准执行路线必须把上传音乐作为 Seedance 2.0 的 `@Audio1`，注册为 Audio 资产，并禁止 `reference_audios`。源合同冻结后需要帧级音乐窗口；最终 QA 必须保存上传音乐精确片段、可见演唱歌词或音素对齐和口型收据，以及最终混音收据。控制台不会把这条路线降级为 RunningHub 请求。

“只改语言”路由不显示文字脚本和故事板确认；它直接请求 Codex 返回经过现有 Skill 编排的 Provider 请求。

## Codex 结果包要求

不要把 Codex 的自然语言回复直接粘贴进控制台。必须导入结构化 JSON。控制台导出的任务包已经含有 `job_id`、`expected_job_version`、`input_manifest_sha256`、允许的结果类型和 `task_sha256`；Codex 返回时必须保留这些字段，添加：

```json
{
  "result": {
    "kind": "provider_request",
    "provider_request": {
      "workflow_id": "RunningHub 工作流 ID",
      "payload": {"nodeInfoList": []}
    }
  },
  "result_sha256": "result 的规范 JSON SHA-256"
}
```

`payload` 必须是该 RunningHub 工作流 API 页面规定的请求体，例如 `nodeInfoList`、`instanceType` 和 `usePersonalQueue`。控制台按 RunningHub 标准接口提交到：`/openapi/v2/run/ai-app/{workflow_id}`，并轮询 `/openapi/v2/query`。这意味着 Codex/既有 Skill 必须在生成结果包前将需要的媒体字段准备为该工作流可接受的值；控制台不会猜测节点 ID 或重绘工作流。

## 恢复规则

- 页面刷新、浏览器关闭或控制台重启后，先刷新任务；已经有 task ID 的任务只会继续查询，绝不会再创建一次。
- 如果创建请求写入后网络超时，状态会是 `PENDING_CREATE`。这是一种“结果不明”状态：不要再次点击或重新导入请求。先到 RunningHub 后台核对是否已有任务，再依据 task ID 恢复。
- 若提示 `CODEX_BRIDGE_RESULT_REJECTED`，重新导出当前任务包并让 Codex 按新版本生成结果；不要修改旧 JSON 的 job ID、版本或摘要。
- 如出现 `JOB_VERSION_CONFLICT`，页面状态已过期，点击“刷新状态”后继续。
- 商业批次行的重试只恢复已知 job/Provider 任务；它不会从控制台重新创建付费 Provider 任务。

## 本地数据与安全

- 所有任务数据只写入本项目的 `data/jobs/<job-id>/`；输入会复制并 SHA-256 固化。
- 控制台不会写入既有 Skill，也不会写入历史 `replication-runs`。
- 密钥仅由后端读取 `.env` 或进程环境变量，不会进入任务 JSON、浏览器页面、日志、下载链接或错误响应。
- 静态素材只允许通过已登记的 artifact ID 读取；路径遍历和 `.env` 读取会被拒绝。
