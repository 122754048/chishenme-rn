# USFR 音乐与口播分轨优化实施计划

> **For Codex:** 执行本计划时使用 `executing-plans`，按任务顺序逐项实现。先写定向测试，再做最小代码修改；不得借本次修改重构无关链路。

**目标：** 让复刻流程严格做到“音乐替换音乐，口播替换口播”。上传的指定音乐只能进入原视频的音乐区间；口播、念白、独白、对话、旁白必须根据新产品卖点重写并经用户确认。正常复刻时，画面内人物的确认台词直接编译进视频生成提示词；只有“只改语言”时，画面内说话才使用 TTS 和非唱歌对口型。旁白始终单独生成参考原音色的 TTS，不能被音乐覆盖，也永远不做人脸对口型。

**实现思路：** 不增加一轮重度分析。复用原视频现有的一次音频和画面分析结果，生成一份内存中的“声音时间轴”。每个时间段只允许属于一种主要声音类型，并绑定唯一处理路线。后续文字脚本、TTS、歌曲对口型、口播对口型、音频合成和提交前检查都读取同一份结果，禁止各阶段自行猜测。

**技术范围：** Python、现有 GPT 分析接口、现有 RunningHub TTS/歌曲对口型/口播对口型能力、FFmpeg、pytest。用户层仍然只确认文字脚本和导演故事板。

---

## 一、最终运行规则

| 原视频中的声音和表演 | 新视频如何处理 | 是否使用上传音乐 | 是否做人物对口型 |
|---|---|---:|---:|
| 全程人物唱歌 | 全程替换为指定歌曲 | 是 | 全程歌曲对口型 |
| 部分区间人物唱歌 | 只替换对应唱歌区间 | 仅唱歌区间 | 仅对应人物、对应区间做歌曲对口型 |
| 只有背景音乐，人物没有唱歌 | 只替换背景音乐 | 是 | 否，禁止把人物变成唱歌 |
| 人物口播、念白、独白或对话：正常复刻 | 按新产品卖点和痛点改写台词，用户确认后将精确台词写入视频生成提示词 | 否 | 不调用外部非唱歌对口型，由视频生成阶段直接让人物说确认台词 |
| 人物口播、念白、独白或对话：只改语言 | 翻译确认台词并生成 TTS | 否 | 仅此路线使用非唱歌对口型 |
| 画外音、旁白 | 改写台词，用户确认后，以原旁白/画外音为音色参考生成 TTS | 否 | 绝不做人脸对口型 |
| 环境声、动作声、音效 | 默认保留原有时间和位置 | 否 | 否 |
| 静音 | 保持静音 | 否 | 否 |

直白地说：原片哪里唱歌，就在哪里换歌并让人物唱；正常复刻时，原片哪里有人说话，就把确认后的准确台词直接写进该段视频的生成提示词。只有用户明确选择“只改语言、不重新生成人物画面”时，才生成口播 TTS 并调用非唱歌对口型。上传的音乐不允许从头铺到尾，也不允许盖住任何一句口播。

---

## 二、统一声音时间轴

新增一个轻量的内部数据结构 `source_audio_lane_contract/v1`。它只在任务运行期间使用，不作为用户文件长期保存。

每个声音区间至少记录：

```json
{
  "region_id": "A01",
  "start_ms": 4200,
  "end_ms": 8600,
  "source_kind": "spoken_dialogue",
  "visual_performance": "on_camera_speaking",
  "speaker_id": "CHARACTER_A",
  "voice_reference_id": "VOICE_CHARACTER_A",
  "operation_mode": "normal_replication",
  "replacement_route": "approved_dialogue_in_generation_prompt",
  "uploaded_music_allowed": false
}
```

允许的 `source_kind` 只有六种：

- `song_performance`：画面人物确实在唱歌。
- `background_music`：有音乐，但画面人物没有唱歌。
- `spoken_dialogue`：画面人物口播、念白、独白或对话。
- `voiceover`：画外音或旁白。
- `ambience_sfx`：环境声、动作声和音效。
- `silence`：无有效声音。

分类时必须同时参考音频和画面中的嘴部/表演行为。仅检测到音乐，不能直接认定人物在唱歌。

对口型路线还必须遵守以下唯一对应关系：

| 声音区间 | TTS 音色来源 | 允许的对口型路线 |
|---|---|---|
| `song_performance` | 用户上传歌曲本身 | 只能使用歌曲对口型工作流 `2082759080288296961` |
| `spoken_dialogue` + 正常复刻 | 不单独生成口播 TTS；将用户确认台词、说话人和时间窗口直接写入视频生成提示词 | 禁止调用外部非唱歌对口型工作流 |
| `spoken_dialogue` + 只改语言 | 使用翻译后的确认台词生成 TTS | 只能使用非唱歌口播对口型工作流 `2080140197518823426` |
| `voiceover` / 旁白 / 画外音 | 必须使用原视频中该旁白或画外音的干净语音片段作为音色参考 | 禁止调用任何人脸对口型工作流 |
| `background_music`、`ambience_sfx`、`silence` | 不生成说话 TTS | 禁止调用任何人脸对口型工作流 |

这里的“画面内真实说话”不是仅凭有台词判断，而是必须同时满足：存在台词、人物脸部可见、嘴部正在说话，并且说话人已经绑定。即使全部满足，正常复刻也不调用非唱歌对口型；只有 `operation_mode=language_only` 时才允许调用。

---

### 任务 1：建立统一的声音区间合同

**文件：**

- 新建：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\audio_lane_router.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\source_content_timeline.py`
- 新建测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_router.py`

**实施内容：**

1. 定义上述六种声音类型及其允许的处理路线。
2. 把现有音频分析、Whisper 时间戳、人物可见性和嘴部表演证据合并为一份时间轴。
3. 相邻且类型、人物、处理方式相同的区间自动合并，减少碎片和后续调用次数。
4. 不确定区间不得猜测为唱歌：优先落为背景音乐或需要明确说话人的语音区间；多人归属无法确定时，在付费生成前拦截。
5. 保证区间有序、不重叠，并覆盖原视频完整时间轴。
6. 为每个口播人物和每个旁白声源绑定独立的 `voice_reference_id`；禁止把人物 A、人物 B 和旁白的音色混为同一个默认说话人。
7. 在声音区间合同中冻结 `operation_mode`：只能是 `normal_replication` 或 `language_only`。后续阶段不得自行把正常复刻切换成只改语言路线。

**定向测试：**

- 全程唱歌只生成一个或少量合并后的 `song_performance` 区间。
- “前半口播、后半唱歌”被分成两条不同路线。
- 音乐存在但人物不张嘴时是 `background_music`，不是 `song_performance`。
- 静音和环境声不会被误判成音乐或口播。
- 两个人交替说话时分别绑定 `CHARACTER_A`、`CHARACTER_B`。
- 旁白区间绑定 `VOICEOVER` 和对应 `voice_reference_id`，但对口型路线必须为 `none`。
- 相同的画面内口播在 `normal_replication` 下路由为提示词直出，在 `language_only` 下才路由为 TTS + 非唱歌对口型。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_router.py" -q
```

**预期结果：** 全部通过；分类只运行一次，后续阶段直接复用结果。

---

### 任务 2：将上传音乐限制在音乐区间

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\uploaded_audio_contract.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\singing_audio_router.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_uploaded_audio_contract.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_singing_audio_router.py`

**实施内容：**

1. 上传音频仍按现有规则识别为 `song` 或 `non_song`，不增加新的用户参数。
2. 上传歌曲仅可绑定 `song_performance` 或 `background_music` 区间。
3. 全片都是 `song_performance` 时，自动形成全片歌曲替换路线。
4. 只有部分唱歌时，只截取上传歌曲对应长度的音频进入这些区间，其他区间不得听到上传音乐。
5. 纯背景音乐区间只换音乐，不生成歌词表演，也不触发歌曲对口型。
6. 禁止循环、任意拉伸、提前进入、延后退出或填满静音区间。

**定向测试：**

- 全唱歌视频允许全片替换。
- 混合视频只允许替换唱歌/背景音乐窗口。
- 上传音乐与口播窗口发生一毫秒重叠也会被拒绝。
- 纯背景音乐不会生成 `sings` 指令。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_uploaded_audio_contract.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_singing_audio_router.py" -q
```

---

### 任务 3：把口播内容写进唯一的文字脚本确认流程

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_script_document.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\line_contract.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_stages.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_script_document.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_line_contract.py`

**实施内容：**

1. 对 `spoken_dialogue` 和 `voiceover` 区间读取原转写文字。
2. GPT 根据新产品/App 的真实卖点、目标人群痛点、原句时长和说话人口吻，改写新台词。
3. 每句台词绑定 `Cut`、时间区间、说话人、是否画面内、目标语言和对应卖点。
4. 多人物内容按原视频的说话顺序和人物归属分配；证据不足时不得自行把所有台词交给一个人。
5. 用户看到的文字脚本必须清楚显示：时间、类型、谁说/谁唱、原内容、新内容、处理方式。
6. 歌词和口播仍在同一份文字脚本中一次确认，不新增“音频确认”。
7. 旁白和画外音在脚本中必须标明“参考原旁白音色生成 TTS，不做人脸对口型”，不得写成“人物口播对口型”。

**文字脚本示例：**

```markdown
### 00:04.200–00:08.600｜人物口播

- 说话人：人物 A
- 原台词：……
- 新台词：……
- 对应卖点/痛点：……
- 处理方式：正常复刻时，将本句原文、人物 A 和本时间窗口直接写入视频生成提示词；不调用外部口播对口型
- 上传音乐：本区间禁止进入
```

```markdown
### 00:15.000–00:19.500｜旁白/画外音

- 声音角色：原旁白 A
- 原台词：……
- 新台词：……
- 音色：使用原旁白 A 的声音作为参考
- 处理方式：只生成旁白 TTS，不执行任何人物对口型
- 上传音乐：本区间禁止覆盖旁白
```

```markdown
### 00:08.600–00:15.000｜人物唱歌

- 演唱者：人物 A
- 替换歌曲：用户上传音乐
- 使用歌词：……
- 处理方式：替换音乐，并对人物 A 做歌曲对口型
```

**定向测试：**

- 口播区间一定有用户可见的新台词。
- 每句口播都绑定唯一人物或明确标为旁白。
- 用户修改后的确认稿成为正常复刻视频提示词或只改语言 TTS 的唯一文本来源。
- 每条旁白都绑定原视频中的旁白音色参考，且对口型方式为 `none`。
- 脚本中不得展示模型名称、工作流名称、内部节点或内部技术提示词。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_script_document.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_line_contract.py" -q
```

---

### 任务 4：按任务模式严格分开“提示词直出”和“只改语言对口型”

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_stages.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_ports.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\.env.example`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\runninghub_workflows.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\runninghub_song_lip_sync.py`
- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\runninghub_final_lip_sync.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_packaged_stages.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_workflows.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_song_lip_sync.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_final_lip_sync.py`

**实施内容：**

1. 只有文字脚本确认后，才能编译人物台词、生成 TTS 或执行任何对口型。
2. `song_performance` 使用上传歌曲，并只调用歌曲对口型工作流 `2082759080288296961`。
3. 正常复刻中的 `spoken_dialogue` 不生成单独口播 TTS，也不调用 `2080140197518823426`；确认台词直接交给视频提示词编译器，由新视频中的人物按指定时间说出。
4. 只有 `operation_mode=language_only` 且区间为画面内真实说话的 `spoken_dialogue` 时，才使用翻译后的确认台词生成 TTS，并调用非唱歌口播对口型工作流 `2080140197518823426`。
5. `voiceover` 必须先从原视频中提取对应旁白/画外音的干净声音片段，作为 TTS 的音色参考；使用确认台词生成新旁白音频后直接进入合成，禁止调用歌曲或非唱歌口播对口型工作流。
6. 歌曲对口型与只改语言对口型的客户端方法、输入合同和结果类型分开，代码层禁止互相调用。
7. 只改语言 TTS 或旁白 TTS 超出原时间窗时，先让 GPT 在不损失核心卖点的前提下缩短台词或调整合理语速，禁止拉长视频。
8. 同一人物在不同区间既唱歌又口播时，按区间分别处理，不能把整段视频交给单一对口型工作流。
9. 旁白音色参考从原视频对应声源的可用区间中一次提取；优先选择无音乐、无其他人声、无明显音效污染的连续片段。存在多个旁白时分别建立音色参考，禁止串用。
10. 如果当前 TTS 工作流不能接收参考音频，必须在旁白 TTS 提交前明确报错并停止，不得退回通用说话人、默认音色或错误人物音色。执行时应为现有 TTS 适配器增加参考音频输入，而不是增加新的用户操作。
11. 在 `packaged_ports.py` 和 `.env.example` 中增加 TTS 参考音频节点的可选配置；一旦任务含旁白，该配置由“可选”转为本次任务的必需能力。参考音频由服务内部从原视频提取并上传，用户无需再上传声音样本。

**定向测试：**

- 唱歌区间只调用歌曲工作流。
- 正常复刻的画面内口播不会调用 TTS 或非唱歌口播工作流。
- 只有“只改语言 + 画面内真实说话”才调用 TTS 和非唱歌口播工作流 `2080140197518823426`。
- 旁白使用原旁白参考音色生成 TTS，且歌曲、非唱歌两个对口型工作流的调用次数都为零。
- 歌曲不得进入非唱歌对口型工作流，口播不得进入歌曲对口型工作流。
- 未确认脚本时任何 TTS/对口型调用均被拒绝。
- 正常复刻的“唱歌 + 人物口播 + 旁白”中，人物口播由提示词直出，旁白单独生成 TTS，歌曲单独走歌曲对口型，三条路线互不串用。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_packaged_stages.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_workflows.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_song_lip_sync.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_final_lip_sync.py" -q
```

---

### 任务 5：编译提示词时明确谁在唱、谁在说、谁不说话

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\seedance_prompt_compiler.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prompt_compiler.py`

**实施内容：**

1. 每个生成区间必须从声音时间轴读取表演类型，不能由模型临时判断。
2. 唱歌区间明确写入“人物、歌曲引用、确认歌词和开始结束时间”。
3. 正常复刻的口播区间必须把“唯一说话人、用户确认的逐字台词、台词语言、开始结束时间、说话动作和口型要求”直接写入视频生成提示词，禁止只写笼统的“人物在说话”。
4. 背景音乐、旁白、环境声和静音区间明确禁止人物唱歌或擅自说话。
5. 混合区间按时间顺序分别编译，不使用一句笼统的“跟随音频表演”。
6. 延续现有规则：原视频继续作为动作、镜头和节奏参考；替换后的角色、产品、文字和声音以确认合同为准。
7. `language_only` 不进入正常视频提示词生成路线；它直接使用翻译、TTS 和非唱歌对口型处理原视频画面。
8. 正常复刻提示词必须标明口播由该次视频生成直接完成，禁止生成后再安排非唱歌对口型补丁。

**定向测试：**

- 唱歌区间包含明确的 `sings` 语义和指定演唱者。
- 正常复刻口播区间包含明确的 `speaks` 语义、唯一说话人、逐字确认台词和精确时间窗。
- 正常复刻编译结果不会创建非唱歌对口型请求。
- 只改语言路线不会创建新视频生成提示词，只创建对应口播窗口的 TTS 和非唱歌对口型请求。
- 纯背景音乐区间包含“人物不唱歌”。
- 同一个 Cut 不得同时出现互相冲突的唱歌和口播指令。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prompt_compiler.py" -q
```

---

### 任务 6：按时间窗合成最终声音，禁止串轨

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\audio_mixer.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_mixer.py`

**实施内容：**

1. 最终合成器只接受声音时间轴批准的音频片段。
2. 唱歌区间放入上传歌曲；正常复刻口播保留新生成视频中按确认台词产生的口播声音；只改语言口播放入确认后的 TTS；旁白区间放入参考原音色生成的旁白 TTS。
3. 环境声和必要音效按原时间轴保留；静音区间不自动填音乐。
4. 区间边界使用很短的淡入淡出避免爆音，但不得改变实际切入切出时间。
5. 对任何交叉覆盖执行硬拒绝，尤其是上传音乐覆盖口播、旁白或 TTS。
6. 合成中间文件继续使用任务临时目录，任务结束后按现有清理规则删除，不纳入 Skill 长期文件。
7. 旁白 TTS 作为普通音轨直接进入对应时间窗，不能把旁白音频和无关人物视频送进对口型工作流。

**定向测试：**

- “口播—唱歌—口播”最终音轨顺序正确。
- 上传音乐在口播窗口的音量为零。
- 正常复刻口播使用新视频自身的确认台词音频，不被再次覆盖为 TTS。
- 只改语言口播使用 TTS + 非唱歌对口型结果。
- 环境声不因更换音乐被整段删除。
- 最终音频总时长与原视频一致。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_mixer.py" -q
```

---

### 任务 7：在付费生成前增加硬拦截

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\audio_route_guard.py`
- 新建测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_route_guard.py`

**以下情况必须在提交生图、生视频或付费对口型前停止：**

1. 上传音乐进入任何口播、念白、独白、对话或旁白区间。
2. 唱歌区间没有绑定明确的演唱人物。
3. 多人说话或唱歌，但人物分配不明确。
4. 旁白或只改语言路线的 TTS 文本和用户确认的文字脚本不一致。
5. 旁白或只改语言路线的 TTS 音频超出批准的时间窗。
6. 歌曲区间错误调用非唱歌对口型，或任何非歌曲区间错误调用歌曲对口型。
7. 背景音乐区间产生人物唱歌指令。
8. 声音时间轴存在空洞、倒序或重叠。
9. `voiceover`、旁白或画外音准备调用任意对口型工作流。
10. 旁白 TTS 没有绑定原旁白音色参考，或绑定了其他人物/其他旁白的音色。
11. 非唱歌对口型请求不是来自 `language_only + spoken_dialogue + on_camera_speaking + confirmed speaker` 四项同时成立的区间。
12. 实际工作流 ID 与路线不一致：歌曲只能是 `2082759080288296961`，非唱歌口播只能是 `2080140197518823426`。
13. 正常复刻的画面内人物口播准备调用非唱歌对口型工作流。
14. 正常复刻的口播提示词缺少确认台词、明确说话人或精确时间窗口。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_route_guard.py" -q
```

**预期结果：** 错误路线在收费生成前被拒绝，而不是等最终 QC 才发现。

---

### 任务 8：更新 Skill 规则，保持用户流程不变

**文件：**

- 修改：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract.py`
- 修改测试：`C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract_docs.py`

**实施内容：**

1. 在上传音频规则中明确写入“音乐替换音乐、口播替换口播”。
2. 明确全音乐、部分音乐、背景音乐、口播、旁白和混合视频的不同路线。
3. 明确只进行一次轻量声音分类，禁止每个阶段重新深度分析。
4. 明确用户仍然只确认文字脚本和导演故事板。
5. 明确声音时间轴和中间音频是临时运行数据，不新增长期输出文件。
6. 不改变 UI 开关、故事板、控制图、产品/App 替换、语言选择及其他无关规则。
7. 明确旁白必须参考原旁白音色生成 TTS，但绝不执行人脸对口型。
8. 明确非唱歌对口型只服务于“只改语言”路线中的画面内真实说话人物，并固定使用 `2080140197518823426`；正常复刻口播直接由视频提示词生成；歌曲对口型固定使用 `2082759080288296961`，二者不可互换。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract_docs.py" -q
```

---

### 任务 9：执行最小回归验证

**验证案例：**

1. 全程人物唱歌 + 上传歌曲。
2. 前半口播、后半唱歌 + 上传歌曲。
3. 唱歌、口播交替出现两次以上。
4. 纯口播 + 上传歌曲，验证歌曲完全不进入视频。
5. 纯背景音乐，验证人物不会被做成唱歌。
6. 两人交替口播。
7. 一人唱歌、另一人口播。
8. 画外音 + 背景音乐。
9. 正常复刻中同时存在歌曲、画面内口播和画外旁白，验证“歌曲对口型、提示词直接口播、旁白 TTS”三条路线互不串用。
10. 两个不同旁白声源，验证各自使用自己的原声音色参考且均不调用对口型。
11. 只改语言的视频含画面内口播和画外旁白，验证只有画面内口播调用非唱歌对口型，旁白只替换音轨。

**运行命令：**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_router.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_uploaded_audio_contract.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_singing_audio_router.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_lane_route_guard.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_script_document.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_line_contract.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_audio_mixer.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prompt_compiler.py" -q
```

通过定向测试后，只运行一次与本次修改直接相关的现有回归测试集合；不反复执行全量测试。

---

## 三、速度与文件控制

本次优化不会因为声音分类而让流程明显变慢，具体限制如下：

- 原视频音频只提取一次。
- Whisper/声音识别只运行一次，结果供脚本、路由、TTS、提示词和合成共同使用。
- 画面只在声音类型边界附近做轻量人物嘴部状态判断，不逐帧重复分析。
- 相同连续区间先合并；正常复刻口播不再额外调用 TTS/非唱歌对口型，只有旁白、歌曲和只改语言路线调用各自必要的音频能力。
- 音频路线错误在付费生成前拦截，不依赖最终 QC 补救。
- 不增加第三个用户确认步骤。
- 不新增用户长期文件；仍然只长期保留文字脚本、导演故事板和最终视频，并保存在 Skill 工程目录之外。
- 不全局启用额外工具；歌曲、口播、旁白按条件调用对应能力。

## 四、本次明确不修改的内容

- 不改变现有故事板生成规则和故事板确认方式。
- 不改变内部替换控制图和人物/产品替换链路。
- 不改变 UI 截图、商店链接和 UI 操作视频开关规则。
- 不改变只改语言的快捷路线；该路线仍是翻译、TTS、口播对口型。
- 不改变视频镜头、动作、节奏和原视频参考方式。
- 不修改部署包；本计划只针对本地 Skill，除非用户后续单独要求同步。

## 五、完成标准

只有同时满足以下条件，才算完成：

1. 全音乐视频能够完成全程歌曲替换和歌曲对口型。
2. 部分音乐视频只替换音乐区间，并只在对应区间做歌曲对口型。
3. 任何口播、念白、独白、对话、旁白都不会被上传音乐覆盖。
4. 口播台词经过产品卖点/痛点改写，并以用户确认的文字脚本为唯一来源；正常复刻直接写入视频生成提示词，只改语言才转成口播 TTS。
5. 多人物能够明确分配谁唱、谁说；不明确时在付费生成前阻止。
6. 歌曲工作流和口播工作流在代码层不可混用。
7. 整个链路只做一次声音时间轴分析，没有重复重度推理。
8. 用户确认步骤仍然只有文字脚本和导演故事板。
9. 没有新增长期中间文件，也没有破坏任何无关功能。
10. 所有旁白和画外音均使用各自原声音色作为 TTS 参考，且从未进入任何对口型工作流。
11. 非唱歌对口型只发生在“只改语言”任务的画面内人物真实说话区间，固定使用 `2080140197518823426`；正常复刻调用次数必须为零。
12. 歌曲对口型固定使用 `2082759080288296961`；两个工作流在请求构建和提交前均有类型校验，无法用错。

本文件仅为实施计划。用户审核确认后再修改本地 Skill 代码。
