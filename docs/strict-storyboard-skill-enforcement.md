# 导演故事板严格执行系统方案

## 结论

不能依靠提示词要求 Image2 严格复刻固定版式。固定版式必须由程序确定性渲染，AI 只能生成被允许填入的画面素材。任何缺少结构、文字、数量或验证回执的故事板均不得发布、不得进入用户确认、不得上传 Seedance。

## 本次故障根因

1. `daohuo_storyboard_prompt.md` 定义了固定版式，但它只是自然语言约束。
2. 当前 `StoryboardStage` 在 Image2 返回后只验证 PNG 解码和宽高，没有验证固定区域、Cut 数量、标题、角色区、目标证据区、环境/机位区和底栏。
3. 为避免 Seedance 抄入时间码，执行时临时把专业导演板改成了无标签七格图，造成规则冲突。
4. `storyboard_image` 发布与审批接口没有强制要求版式合同和版式 QC 回执。

## 新架构：AI 生成内容，程序锁死版式

### 0. 取消本地直连 Provider 旁路

这是根治的第一条件。正式运行禁止模型、通用终端或本地脚本直接读取 RunningHub 凭证并调用 `runninghub_image2.py` / Seedance 创建任务。

- Provider 密钥只注入独立 Worker 的 `provider_adapter`；
- Codex/AI 只能提交结构化阶段请求，不能直接访问密钥；
- `create_asset` / `create_video` 只接受 JobStore 当前状态与上游签名回执；
- 本地脚本保留为测试工具，但生产配置下必须拒绝创建 Provider 任务；
- 所有正式任务必须从 `/api/v1/jobs` 和同一个状态机进入。

只要还保留“模型可以直接运行付费脚本”的路径，任何 Skill 都只能是软约束。

### 1. 冻结机器可读版式合同

在生成前创建 `director_board_layout_contract.json`，至少包含：

- 固定画布尺寸和 16:9 比例；
- 模板版本与模板文件 SHA-256；
- 顶栏、角色区、人物细节区、目标证据区、环境/机位图、故事板 Cut 区、灯光/情绪/风格区、音频区、摄影笔记区的归一化矩形；
- 每个区域的必填/条件必填规则；
- Cut 数量、顺序和每张 Cut 卡片的矩形；
- 允许出现的短标签、字体、字号范围、颜色、对齐和最大行数；
- 禁止区域、禁止长文本、禁止溢出规则；
- 场景内文字与后期 overlay 文字的载体路由。

合同一旦冻结，AI、提示词和后续步骤均不得修改版式坐标。

### 2. Image2 只生成视觉内容槽位

Image2 不再负责整张导演板排版，只负责生成：

- 人物参考视图；
- 人物细节特写；
- 每个 Cut 的真实画面；
- 需要的环境或机位示意素材；
- 场景实体上的文字，如纸张、包装、衣服、招牌文字。

这些素材输出为 `storyboard_content_sheet.png`，并通过 Cut/角色/目标证据清单验证。Image2 无权生成标题、时间码、版面栏目、底栏或任意新增区域。

### 3. 使用确定性模板合成正式导演板

由 Pillow、SVG/HTML 渲染器或同等确定性组件，把已验证内容填入固定模板：

- 所有区域坐标由合同决定；
- 标题、Cut 编号、时间、标签和说明由批准脚本确定性排版；
- AI 不参与字体、区域位置、栏目数量和页面层级；
- 不存在“普通九宫格替代专业导演板”的可能；
- 输出固定为 `storyboards/segment_XX_vN.png`。

这不是用拼图替代生成画面：Cut 主画面仍是 Image2 生成内容，程序只负责不可变的导演板版式和文字排版。

### 4. 导演板与 Seedance 参考图分离

一个文件承担两个角色会产生冲突，因此必须拆分：

- `director_board_approval.png`：用户看到并确认的完整固定版式导演板；
- `seedance_visual_carrier.png`：程序从已批准导演板的 Cut 主画面 ROI 确定性提取并重新排列的无版面标签视觉载体。

`seedance_visual_carrier.png` 必须绑定：

- 已批准导演板 SHA-256；
- 版式合同 SHA-256；
- 每个 Cut ROI 坐标与像素 SHA-256；
- 提取脚本版本和输出 SHA-256。

它不是新的创意资产，不新增用户确认。Seedance 使用该执行载体可以避免把标题、时间码和栏目标签复制进视频。

### 5. 三层失败关闭验证

#### 生成前验证

- 模板版本和 SHA 正确；
- 所有动态字段已填充；
- Cut 数量与批准脚本一致；
- 文字载体路由明确；
- 没有未知占位符；
- 只有合同允许的区域和标签。

失败代码：`STORYBOARD_LAYOUT_CONTRACT_INVALID`，禁止调用 Image2。

#### 合成后结构验证

- 画布尺寸和比例精确；
- 每个必需区域存在且坐标一致；
- 区域数量、Cut 数量和顺序完全一致；
- OCR 检查固定标题、Cut 编号、时间和短标签；
- 检查文本不溢出、不遮挡 Cut 主画面；
- 检查人物区、目标证据区和环境机位区是否按条件出现；
- 检查场景内文字只存在于其物理载体；
- 检查无额外时间码、乱码和未知栏目。

失败代码：`STORYBOARD_LAYOUT_QC_FAILED`，禁止发布给用户。

#### Seedance 前绑定验证

- 导演板已批准；
- 执行载体由当前批准导演板确定性派生；
- 每个 Cut ROI SHA 与导演板对应区域一致；
- 执行载体无栏目文字、时间码和屏幕固定字幕；
- 场景实体文字和批准脚本逐字一致。

失败代码：`SEEDANCE_VISUAL_CARRIER_INVALID`，禁止付费生成。

### 6. 发布与状态机硬门槛

`storyboard_image` 只有同时携带以下字段才允许发布：

- `layout_contract_sha256`；
- `template_sha256`；
- `content_sheet_sha256`；
- `layout_render_receipt_sha256`；
- `layout_qc_receipt_sha256`；
- `required_region_count` 与实际区域清单；
- `cut_count` 与有序 Cut ID；
- `passed=true`。

缺少任意字段时：

- JobStore 不得进入 `AWAITING_STORYBOARD_APPROVAL`；
- API 不得返回故事板给用户；
- 审批接口不得接受该 revision；
- Seedance 审计不得上传该图；
- 系统只能自动重新生成允许的内容素材，或返回类型化 blocker。

状态机必须使用单向能力令牌：

`SCRIPT_APPROVED -> CONTROL_FRAME_VALIDATED -> DIRECTOR_BOARD_RENDERED -> LAYOUT_VALIDATED -> STORYBOARD_APPROVED -> EXECUTION_CARRIER_VALIDATED -> PROMPT_AUDITED -> PROVIDER_ALLOWED`

每个箭头由服务端验证器签发一次性阶段回执。AI 不能自行设置状态、补写 `passed=true`、跳转阶段或构造下一阶段令牌。

### 7. 禁止 AI 绕过规则

- Provider 适配器不接受自由文本整板提示词，只接受结构化 `layout_contract + content_requests`；
- AI 无权修改模板、区域坐标、必需栏目、字体规则和审批类型；
- 禁止使用“用户更需要干净图”“为了 Seedance 效果”等理由改版；
- 需要干净参考图时只能生成批准导演板的确定性执行载体；
- 未通过验证的文件不得用“接近”“可接受”“稍后修复”进入下一阶段。

### 8. Skill 编译为 Policy-as-Code

`SKILL.md` 继续负责说明意图，但所有可硬执行规则必须同步编译到机器合同：

- JSON Schema：输入、阶段输出、版式、文字载体、引用顺序；
- 状态机：合法阶段和唯一迁移；
- Provider policy：允许的模型、参数、引用和最大任务数；
- Artifact policy：父级 SHA、生成器、模板和 QC 回执；
- Approval policy：只能出现脚本和导演板两类用户确认；
- Error policy：每种违规对应固定错误码并失败关闭。

CI 必须比较 `SKILL.md` 的规则清单与 Policy bundle：新增或修改规则却没有对应可执行断言时，构建失败，禁止部署。

### 9. 能力代理而不是自由工具调用

AI 不再获得“执行任意脚本”的生产能力，只获得有限命令：

- `submit_control_frame_request(job_id, contract_sha)`；
- `submit_storyboard_content_request(job_id, control_receipt_sha)`；
- `render_director_board(job_id, layout_contract_sha)`；
- `request_seedance(job_id, prompt_audit_receipt_sha)`。

能力代理在服务端验证状态、父级产物、哈希、任务额度和回执。验证失败时命令不可执行，而不是依赖 AI 自觉停止。

## 必须加入的自动化测试

以下反例必须全部被拒绝：

1. 普通七宫格或九宫格，没有专业导演板区域；
2. 缺顶部标题、角色区、环境机位图或底栏；
3. 7 个 Cut 只生成 6 格；
4. Cut 顺序错误或重复；
5. 时间码进入 Cut 画面内部；
6. 纸面文字被当作后期浮字；
7. 底部字幕被 Image2 写进场景；
8. 文本溢出、乱码、未知标签；
9. 执行载体不是从当前批准导演板派生；
10. 仅凭 PNG 尺寸正确就尝试发布。

正常案例需要覆盖 1、2、3、7、12、15 个 Cut，以及单/双 Segment。

## 验收标准

- 固定版式区域几何匹配率：100%；
- 必需区域完整率：100%；
- Cut 数量与顺序：100%；
- 固定标签 OCR：100%；
- 批准场景实体文字 OCR：100%；
- 执行载体与批准导演板 ROI 像素绑定：100%；
- 任何硬失败时发布数、用户确认数、Seedance 任务数：0。

## 对当前案例的处理

当前 `segment_01_v1.png` 是七格视觉载体，不是规定版式的正式导演板，应标记为 `STORYBOARD_LAYOUT_QC_FAILED`，不得确认、不得上传 Seedance。需要先按上述确定性模板重新合成正式导演板，再由正式导演板派生无标签的 Seedance 执行载体。
