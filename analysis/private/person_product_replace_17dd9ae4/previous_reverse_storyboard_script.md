# 双人物替换｜逆向脚本与单次审批

状态：`AWAITING_SCRIPT_APPROVAL`  
执行方式：Seedance 2.0 单次视频编辑，同时替换两个人物。

## 已核实的源片事实

- 竖屏 `720×1280`，`24 fps`；有效画面约 `15.041667s`。
- 夜间街头采访，一镜到底。女性人物开场位于画面中间偏右；男性采访者开场在画面左侧局部出现，随后完整进入，并始终手持麦克风。
- 两个人物在全片内是两条独立、连续的物理轨迹，没有身份互换。
- 约 `13.00s` 开始出现较大的 SUGO 下载叠层，但人物仍在讲话和运动，因此该段不是可删除的纯尾卡。
- Seedance 单段上限按 `15.000s` 执行：仅舍弃源容器末端约 `0.042s`，不变速、不补帧、不改变有效动作。

## 资产索引与绑定

| API 物理顺序 | Prompt 索引 | 原视频人物轨迹 | 替换范围 |
| --- | --- | --- | --- |
| `imageUrls[0]` | `@Image1` | 开场中间偏右、长深色头发、灰色无袖上衣的女性 | 使用 `@Image1` 的完整人物身份及图中清晰可见的白色长袖短上衣、灰色紧身裤和可见配饰 |
| `imageUrls[1]` | `@Image2` | 开场画面左侧、黑色连帽衫、白色短裤、手持麦克风的男性 | 使用 `@Image2` 的完整人物身份及图中清晰可见的宽松白色 T 恤、粗银链、白色墨镜和尖刺发型 |

两张图都是单人物独立资产。数组采用严格 1-based 对齐：`imageUrls[0] = @Image1`，`imageUrls[1] = @Image2`。

## 冻结执行提示词

```text
编辑视频：Multi-subject replacement based on @Video1.
- Source woman (opening center-right, long dark hair, gray sleeveless top): Replace with exact identity and visible wardrobe from @Image1.
- Source man (opening frame-left, black hoodie, white shorts, holding the microphone): Replace with exact identity and visible wardrobe from @Image2.
Each mapped subject stays on its own continuing physical track through movement and occlusion, inheriting its source motion, expression, gaze, interaction, and timing. @Video1 supplies camera, framing, lighting, background, props, subtitles, SUGO overlays, dialogue, ambience, and audio.
```

## 保留项与验收标准

- 一次请求同时完成两个人物替换，不逐人生成。
- 人物服装优先采用对应参考图中的可见穿着；本次两张人物图均有充分服装证据。
- 保留原片镜头、构图、运动、站位、遮挡、人物互动、麦克风与手机接触关系、夜景、字幕、SUGO 图形叠层、对白和原音。
- QC 分别检查女性轨迹与男性轨迹：身份、服装和配饰必须与各自参考图匹配，且从首次出现到结束不串位、不漂移。
- 供应商返回成功只代表任务完成；只有两条人物轨迹均通过对象级人工抽查，才交付最终 MP4。

## 审批边界

批准本脚本后，后续只允许把上述冻结提示词和固定索引提交为一次 Seedance 2.0 编辑请求。任何资产顺序、人物映射、穿着来源、时长、保留项或提示词变化，都必须先停止执行并重新说明，禁止静默改写。
