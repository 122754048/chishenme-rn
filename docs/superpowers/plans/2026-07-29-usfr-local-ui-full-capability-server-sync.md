# USFR 本地 UI 重绘与服务端全能力同步实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 `universal-source-fidelity-replication` Skill 的 UI 重绘能力完成真实功能验证后，以该本地 Skill 为唯一源码重新生成可独立部署的 Docker Compose 服务包，使服务端拥有本地 Skill 当时的全部最新能力，而不是只增量复制 UI 文件。

**Architecture:** 本地 Skill 是主流程发布源，独立项目 `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar` 是 UI 像素级渲染实现源，旧 ZIP 只作为差异基线。发布时同时冻结两棵源码树，通过确定性打包器将 Sidecar 的源码、锁文件、已编译 Remotion bundle 和不可变身份清单放入 USFR ZIP；Worker 仅在命中合格 `generated_ui_demo` 时通过 `OnDemandUiSidecarRenderer` 启动包内 CPU-only 子进程，其他路线保持零 Sidecar 进程、零 Chromium、零 OpenCV 分析。

**Tech Stack:** Python 3.12、FastAPI、Redis Streams、MinIO/S3、Docker Compose、FFmpeg/OpenCV、GPT API、RunningHub API、pytest、PowerShell、ZIP/SHA-256。

## Global Constraints

- 本地 Skill 路径 `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication` 是唯一功能真源。
- UI 像素级渲染项目路径 `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar` 是唯一 Sidecar 实现真源；`node_modules`、Python 虚拟环境、Chromium 下载缓存和渲染缓存不得进入 Skill 目录。
- 不在指定对话仍写文件或测试未结束时同步；只同步完成后的冻结快照。
- 不直接修改或覆盖旧 ZIP；生成新的版本化 ZIP，旧包保留为回滚基线。
- 同步的是本地 Skill 的全部运行能力，不只同步 UI 重绘文件。
- 七个固定素材入口、`output_language` 参数、十二个语义阶段、文字脚本与故事板两个用户确认点、最多两个 Seedance 任务保持不变。
- `ui_operation_video` 始终优先走 `opaque_ui_demo`，禁止 OCR、重绘或语义解释其主体内容。
- 直接 `output_language`-only 路线不启动 Sidecar；只有同时存在商品、模特、UI 截图、App 证据或批准文案等 UI 重绘触发条件时，Sidecar 才使用目标语言渲染该 UI 区间。
- 只有原视频已经识别出 UI Cut 时才允许重绘；原视频无 UI 时不得启动 UI 分析、OCR、重绘或新增模型调用。
- UI 重绘只分析已识别 UI ROI 和冻结帧窗口，禁止重新做全视频深度分析、深度 QA、自动重试或新增付费 Seedance 任务。
- UI 可读文字必须 UTF-8、无 `?` 替换字符、无 U+FFFD、无伪文字，OCR 与布局验证必须通过。
- UI 像素、文字和操作动效不得进入 Seedance；由确定性 UI 渲染器和时间轴合成器处理。
- Docker 运行时禁止读取 `C:/Users/...`、`.codex/skills`、本地输出目录或用户电脑路径。
- ZIP 内不得包含 API Key、`.env`、用户素材、生成视频、运行日志、`.git`、`.pytest_cache`、`__pycache__` 或其他缓存。
- 只有真实视频渲染器验证通过才可宣称服务端拥有 UI 重绘能力；测试 fake、静态 PNG 归一化或仅合同校验不算功能完成。
- Sidecar 默认 CPU-only：Chromium 禁用硬件加速，FFmpeg 固定软件解码和 `libx264` 编码，不安装 CUDA、DirectML、NVENC 或 GPU 推理依赖。
- Sidecar 构造时不得启动进程；首次合格 UI 调用才启动，默认空闲 120 秒关闭，并发 UI 作业共享同一个健康进程。

---

### Task 1: 冻结本地 UI 重绘完成状态和发布证据

**Files:**
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/ui_interaction_contract.py`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/on_demand_ui_sidecar.py`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/analysis_scope.py`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/real_capabilities.py`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/bundled-skills/seedance-storyboard-replication/SKILL.md`
- Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/ui-render-sidecar-manifest.json`
- Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/package.json`
- Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/package-lock.json`
- Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/src/`
- Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/python/requirements.lock`
- Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/python/extract_motion.py`
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-ui-local-release-evidence.json`

**Interfaces:**
- Consumes: 指定对话 `019f8e29-5c2d-7292-b0d3-d1cfd2e46674` 的最终测试结果和本地 Skill 文件。
- Produces: 不可变发布证据，记录文件 SHA、测试命令、通过数量、真实 UI 样例结果、渲染器身份和耗时。

- [ ] **Step 1: 等待指定对话完成，而不是读取正在变化的工作目录**

  接受条件：任务状态为完成；没有待确认问题；最终消息列出 Skill 与 Sidecar 修改文件、依赖安装结果、测试通过数、真实 MP4 路径、HTTP receipt、渲染耗时和已知质量限制。

- [ ] **Step 2: 运行 UI 聚焦回归**

  Run:

  ```powershell
  Set-Location 'C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication'
  $env:PYTHONDONTWRITEBYTECODE='1'
  python -B -m pytest -q tests/test_ui_interaction_contract.py tests/test_analysis_scope.py tests/test_packaged_stages.py tests/test_real_capabilities.py tests/test_skill_contract.py
  ```

  Expected: 全部通过；不存在跳过核心 UI 渲染测试的情况。

- [ ] **Step 3: 运行 UI 路由保护回归**

  Run:

  ```powershell
  python -B -m pytest -q tests/test_fixed_input_slot_contract.py tests/test_source_ui_interval_contract.py tests/test_timeline_region_contract.py tests/test_timeline_splice.py tests/test_timeline_splice_real_media.py
  ```

  Expected: 全部通过，并证明：无 UI 零开销、上传 UI 视频仍为 opaque、缺失尾部仍省略、时间轴无黑帧回归。

- [ ] **Step 4: 执行一条真实 UI 重绘样例**

  样例固定为：原视频包含 UI Cut，仅上传 `new_product_image` 或 `new_model_image`，不上传 `ui_operation_video`。必须产生真实 MP4，不得使用测试 fake 或单张 PNG。

  验证 JSON 必须包含：

  ```json
  {
    "route": "generated_ui_demo",
    "schema_version": "source-ui-interaction/v1",
    "video_valid": true,
    "source_frame_locked": true,
    "ocr_match_percent": 100,
    "layout_match_percent": 100,
    "replacement_glyph_count": 0,
    "full_video_reanalysis_count": 0,
    "automatic_retry_count": 0,
    "extra_seedance_task_count": 0
  }
  ```

  还必须证明：构造 `OnDemandUiSidecarRenderer` 后进程不存在；第一次合格 UI 调用启动一个 CPU-only Sidecar；第二个并发调用复用同一 PID；空闲 120 秒后进程退出；无 UI、`opaque_ui_demo` 和直接 language-only 测试中 PID 从未出现。

- [ ] **Step 5: 写入冻结发布证据**

  `usfr-ui-local-release-evidence.json` 必须记录本地 Skill 根文件、Sidecar `package-lock.json`、Python `requirements.lock`、Remotion bundle、OpenCV extractor、Noto 字体清单及渲染器实现的 SHA-256；任一文件随后变化，发布流程必须重新从 Task 1 开始。

### Task 2: 生成本地 Skill 与旧部署包的完整差异清单

**Files:**
- Read: `C:/Users/zhaocx04/Documents/New project/exports/usfr-video-service-2026-07-29-deploy-with-manual.zip`
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-server-sync-diff.json`
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/compare_release_bundle.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_compare_release_bundle.py`

**Interfaces:**
- Consumes: 冻结本地 Skill、冻结 Sidecar 项目和旧 ZIP。
- Produces: `added`、`changed`、`unchanged`、`removed` 四组文件及 SHA-256，防止只复制显眼的 UI 文件而漏掉合同、清单或依赖。

- [ ] **Step 1: 写失败测试，证明新 UI 模块必须被识别为 added**

  ```python
  def test_compare_marks_ui_interaction_runtime_as_added(tmp_path):
      result = compare_release_bundle(local_root=LOCAL_SKILL, zip_path=OLD_ZIP)
      assert "server/ui_interaction_contract.py" in result["added"]
      assert "references/bundle_manifest.json" in result["changed"]
  ```

- [ ] **Step 2: 实现只读 ZIP 差异器**

  接口固定为：

  ```python
  def compare_release_bundle(
      *,
      local_root: Path,
      sidecar_root: Path,
      zip_path: Path,
  ) -> dict[str, list[dict[str, str]]]:
      """Compare Skill and Sidecar release paths with raw-byte SHA-256 values."""
  ```

  比较器必须忽略缓存和测试运行产物，但不能忽略 `SKILL.md`、`server/`、`scripts/`、`bundled-skills/`、`runtime-skills/`、`references/`、`schemas/`、`deployment/` 和 `validation/`。

- [ ] **Step 3: 输出完整差异清单**

  Run:

  ```powershell
  python -B scripts/compare_release_bundle.py --local-root . --sidecar-root 'C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar' --zip 'C:\Users\zhaocx04\Documents\New project\exports\usfr-video-service-2026-07-29-deploy-with-manual.zip' --output 'C:\Users\zhaocx04\Documents\New project\exports\usfr-server-sync-diff.json'
  ```

  Expected: 至少识别 `server/ui_interaction_contract.py` 为新增，并识别 `packaged_stages.py`、`analysis_scope.py`、`real_capabilities.py`、两个 Skill 文档、`verify_bundle.py`、`bundle_manifest.json` 的变化。

### Task 3: 建立确定性的“全量快照”打包器

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/package_python_service.py`
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_package_python_service.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/bundle_manifest.json`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/verify_bundle.py`

**Interfaces:**
- Consumes: Task 1 冻结 SHA 清单和本地 Skill。
- Produces: 一个干净的版本化 ZIP，以及 ZIP 根目录的 `RELEASE-MANIFEST.json`。

- [ ] **Step 1: 写失败测试，禁止再次生成空包或部分包**

  ```python
  def test_package_contains_complete_runtime_and_ui_contract(tmp_path):
      result = build_package(
          source_root=LOCAL_SKILL,
          sidecar_root=LOCAL_SIDECAR,
          output_zip=tmp_path / "release.zip",
          release_evidence=RELEASE_EVIDENCE,
      )
      names = set(result.entries)
      assert "SKILL.md" in names
      assert "server/ui_interaction_contract.py" in names
      assert "server/packaged_ports.py" in names
      assert "deployment/docker-compose.yml" in names
      assert "deployment/中文部署配置手册.md" in names
      assert "sidecars/usfr-ui-render-sidecar/package.json" in names
      assert "sidecars/usfr-ui-render-sidecar/package-lock.json" in names
      assert "sidecars/usfr-ui-render-sidecar/dist/server.js" in names
      assert "sidecars/usfr-ui-render-sidecar/python/extract_motion.py" in names
      assert "RELEASE-MANIFEST.json" in names
      assert result.file_count > 100
      assert result.uncompressed_bytes > 500_000
  ```

- [ ] **Step 2: 实现清单驱动打包器**

  接口固定为：

  ```python
  @dataclass(frozen=True)
  class PackageResult:
      output_zip: Path
      sha256: str
      file_count: int
      uncompressed_bytes: int
      entries: tuple[str, ...]

  def build_package(
      *,
      source_root: Path,
      sidecar_root: Path,
      output_zip: Path,
      release_evidence: Path,
  ) -> PackageResult:
      """Build a clean server release from frozen Skill and Sidecar snapshots."""
  ```

  打包器必须重新复制两棵源码树，禁止打开旧 ZIP 后增量写入；必须验证每个源文件 SHA 与 Task 1 证据一致。Sidecar 在 ZIP 内固定映射到 `sidecars/usfr-ui-render-sidecar/`，开发机绝对路径不得写入产物。

- [ ] **Step 3: 固定排除项**

  排除：`tests/__pycache__`、`.pytest_cache`、`.ruff_cache`、`.mypy_cache`、`.git`、`.env`、日志、媒体、`final/`、`runs/`、`validation_runs/`、Sidecar `node_modules/`、`.venv/`、Chromium 下载缓存、Remotion 临时 bundle 和渲染输出。保留测试源码、锁文件、正式 `dist/`、Python extractor 源码和字体清单；Dockerfile 继续通过 `.dockerignore` 排除测试，使发布包可自检而生产镜像不增重。

- [ ] **Step 4: 生成 RELEASE-MANIFEST**

  构造逻辑固定为：

  ```python
  manifest = {
      "schema_version": "usfr-release-manifest/v1",
      "source_skill_sha256": sha256_tree(source_root, skill_paths),
      "ui_sidecar_sha256": sha256_tree(sidecar_root, sidecar_paths),
      "ui_release_evidence_sha256": sha256_file(release_evidence),
      "files": [
          {
              "path": relative_path,
              "sha256": sha256_file(release_path_to_source(relative_path)),
              "size": release_path_to_source(relative_path).stat().st_size,
          }
          for relative_path in sorted(release_paths)
      ],
  }
  ```

  `files` 按路径排序，所有大小必须大于 0；清单本身不包含 API Key、绝对路径或用户素材信息。

### Task 4: 将本地验证过的真实 UI 渲染能力绑定到服务端 Worker

**Files:**
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/src/server.ts`
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/src/contracts.ts`
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/src/render.ts`
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/src/composition/UiInteraction.tsx`
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/python/extract_motion.py`
- Create/Verify: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/tests/`
- Create/Verify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/on_demand_ui_sidecar.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/real_capabilities.py`
- Verify/Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/vision_backends.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_packaged_ports.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_real_capabilities.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_on_demand_ui_sidecar.py`

**Interfaces:**
- Consumes: Node.js/TypeScript/Remotion Sidecar、CPU OpenCV ROI 轨迹提取器、`source-ui-interaction/v1`、UI truth/render contract 和独立 OCR。
- Produces: 服务端 `ocr_ui_renderer` capability，能输出真实 MP4、state evidence、OCR/layout evidence 和渲染身份 receipt。

- [ ] **Step 1: 写失败测试，禁止生产包继续使用无视频后端的开发模式**

  ```python
  def test_packaged_ports_bind_real_ui_video_renderer_in_production(monkeypatch):
      monkeypatch.setenv("USFR_PROFILE_MODE", "active")
      ports = build_ports()
      renderer = ports["capability_ports"]["ocr_ui_renderer"].adapter
      renderer.validate_production_readiness()
      assert renderer.render_backend is not None
      assert renderer.ocr_backend is not None
  ```

- [ ] **Step 2: 完成独立 CPU-only Sidecar**

  Sidecar 固定使用 Express + Zod 提供 `GET /readyz` 和 `POST /v1/render`；Remotion 按源帧索引渲染，OpenCV 只读取已经裁切的 UI 区间与 ROI，输出 translate、scale、rotate、opacity、scroll、tap 和置信度轨迹；FFmpeg 固定软件编解码。禁止读取完整原视频、调用 Seedance、安装 CUDA 或使用测试 fake 代替真实 MP4。

- [ ] **Step 3: 实现按需生命周期管理器**

  接口固定为：

  ```python
  class OnDemandUiSidecarRenderer:
      def __init__(
          self,
          *,
          command: tuple[str, ...],
          endpoint: str,
          manifest_path: Path,
          idle_timeout_seconds: int = 120,
      ) -> None: ...

      def __call__(self, source: Path, output: Path, context: object, **contracts: object) -> Mapping[str, object]: ...
      def capability_identity(self) -> Mapping[str, str]: ...
  ```

  `__init__` 只校验清单和命令，不启动进程。`__call__` 仅在合格 UI 路由中加跨进程锁、探测 `/readyz`、启动一个子进程、执行一次 render，并记录 PID、启动/复用状态、空闲退出和非敏感 receipt。

- [ ] **Step 4: 绑定独立 OCR**

  active/production 模式必须使用 `EvidenceBoundHttpOcrBackend` 或与其证据合同兼容的包内 OCR 适配器。OCR 响应必须绑定输入字节 SHA、请求/响应 SHA、模型 ID 和模型 SHA；不得相信渲染器自报的 100%。

- [ ] **Step 5: 保留轻量路由并解决语言合同冲突**

  `packaged_stages.py` 只在已经存在 UI Cut 且存在允许的替换触发条件时附加合同。直接 language-only 不启动 Sidecar；复合请求中的 `output_language` 只负责确定已触发 UI 重绘区间的目标文字语言。`analysis_scope.py` 必须证明 `full_video_reanalysis_count=0`，并且 `opaque_ui_demo`、无 UI 视频和直接 language-only 不会导入 Chromium、运行 OpenCV 或调用 UI renderer。

### Task 5: 更新 Docker Compose、单一 .env 和中文手册

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/deployment/Dockerfile`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/deployment/docker-compose.yml`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/.env.example`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/deployment/README.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/deployment/中文部署配置手册.md`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_deployment_bundle_config.py`

**Interfaces:**
- Consumes: Task 4 的真实 UI renderer/OCR 配置。
- Produces: 服务端只编辑一个 `.env` 即可启动所有能力。

- [ ] **Step 1: 写失败测试，验证 Compose 传递 UI 配置**

  ```python
  def test_compose_forwards_evidence_bound_ui_renderer_and_ocr_settings():
      compose = COMPOSE.read_text(encoding="utf-8")
      for name in (
          "USFR_UI_SIDECAR_COMMAND",
          "USFR_UI_SIDECAR_MANIFEST",
          "USFR_UI_SIDECAR_IDLE_SECONDS",
          "USFR_UI_SIDECAR_TOKEN",
          "USFR_UI_RENDER_ENDPOINT",
          "USFR_UI_RENDER_MODEL_ID",
          "USFR_UI_RENDER_MODEL_SHA256",
          "USFR_OCR_ENDPOINT",
          "USFR_OCR_MODEL_ID",
          "USFR_OCR_MODEL_SHA256",
      ):
          assert name in compose
  ```

- [ ] **Step 2: 在镜像中安装独立项目，但不随容器启动**

  Dockerfile 使用 Node 多阶段构建，把 `sidecars/usfr-ui-render-sidecar/dist/`、生产依赖、Python extractor 和字体清单复制到 `/opt/usfr/sidecars/usfr-ui-render-sidecar/`。运行镜像不包含源码缓存、npm cache、开发依赖或本地虚拟环境；默认命令仍然是 USFR Worker，Sidecar 不作为 Compose 常驻 service 启动。

- [ ] **Step 3: 配置包内惰性启动命令**

  `.env.example` 和 Compose 固定提供包内命令、`127.0.0.1` 端点、120 秒空闲时间、身份清单和 Token。USFR `/readyz` 只校验 Sidecar 文件、命令、锁文件 SHA 和可执行依赖存在，返回 `installed=true, running=false, lazy_ready=true`；不得为了健康检查提前启动 Chromium 或 OpenCV。首次合格 UI 任务由 Worker 启动并探测 Sidecar 自身 `/readyz`。

- [ ] **Step 4: 更新中文手册**

  手册必须新增：UI 路由判断、三种 UI 路线、直接 language-only 不启动规则、复合需求语言规则、Sidecar 惰性启动/空闲退出、CPU-only 要求、环境变量、无 UI 零开销、文字防乱码标准、OCR 失败处理、如何查看 `installed/running/lazy_ready`、如何回滚旧 ZIP。

### Task 6: 运行本地、解压包和容器三层回归

**Files:**
- Test: `C:/Users/zhaocx04/Documents/New project/usfr-ui-render-sidecar/tests/`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_bundle_runtime_closure.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_container_video_e2e_contract.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_no_workstation_dependency.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_package_python_service.py`

**Interfaces:**
- Consumes: 新构建的 ZIP。
- Produces: 本地源码、干净解压目录和 Docker 容器结果三者一致的验证报告。

- [ ] **Step 1: 运行完整无付费测试**

  ```powershell
  Set-Location 'C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar'
  npm test
  .\.venv\Scripts\python.exe -B -m pytest -q python\tests
  Set-Location 'C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication'
  python -B -m pytest -q
  ```

  Expected: 全部通过；若有环境型跳过，报告必须逐项说明，不能把跳过算作能力通过。

- [ ] **Step 2: 在全新临时目录解压并验证**

  ```powershell
  $extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'usfr-r2-package-verification'
  python -B scripts/verify_bundle.py $extractRoot
  python -B scripts/verify_lightweight_bundle.py $extractRoot
  python -B -m pytest -q (Join-Path $extractRoot 'tests\test_package_python_service.py') (Join-Path $extractRoot 'tests\test_bundle_runtime_closure.py')
  ```

  Expected: bundle valid、lightweight bundle valid、没有本机绝对路径和缓存。

- [ ] **Step 3: 运行 Compose 配置与构建检查**

  ```powershell
  docker compose --env-file .env -f deployment/docker-compose.yml config
  docker compose --env-file .env -f deployment/docker-compose.yml build --no-cache
  ```

  Expected: API、Worker、Sweeper、Redis、MinIO 和包内 UI renderer/OCR 依赖均可解析；镜像构建时 `verify_bundle.py` 通过；容器启动后 Sidecar 进程仍不存在。

- [ ] **Step 4: 运行容器 E2E 路由矩阵**

  必测七条：

  1. 原视频无 UI + 换人物：不调用 UI renderer。
  2. 原视频有 UI + 上传 UI 操作视频：`opaque_ui_demo`，不 OCR、不重绘。
  3. 原视频有 UI + 商品图：生成 frame-locked UI MP4。
  4. 原视频有 UI + 模特图：生成 frame-locked UI MP4。
  5. 原视频有 UI + UI 截图/App Store：以目标 UI 证据重绘。
  6. 直接 `output_language`-only：不启动 Sidecar，保持语言专用路线。
  7. 原视频有 UI + 商品/模特/UI 证据 + `output_language`：Sidecar 已因重绘触发，UI 文字使用目标语言且无乱码。

  每条都必须检查任务数、时长、OCR、黑帧、音视频流、最终 MinIO 只长期保存 `final/{job_id}/result.mp4`。

### Task 7: 生成新的版本化部署包并提供回滚信息

**Files:**
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-video-service-2026-07-29-r2-ui-full-deploy-with-manual.zip`
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-video-service-2026-07-29-r2-ui-full-deploy-with-manual.sha256`
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-video-service-2026-07-29-r2-release-report.md`

**Interfaces:**
- Consumes: 所有通过的验证结果。
- Produces: 新 ZIP、SHA-256、文件数量/体积报告、能力清单、测试证据和旧包回滚路径。

- [ ] **Step 1: 构建新包，不覆盖旧包**

  ```powershell
  python -B scripts/package_python_service.py --source-root 'C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication' --sidecar-root 'C:\Users\zhaocx04\Documents\New project\usfr-ui-render-sidecar' --release-evidence 'C:\Users\zhaocx04\Documents\New project\exports\usfr-ui-local-release-evidence.json' --output 'C:\Users\zhaocx04\Documents\New project\exports\usfr-video-service-2026-07-29-r2-ui-full-deploy-with-manual.zip'
  ```

- [ ] **Step 2: 校验最终 ZIP 不是空包**

  接受条件：ZIP 大小大于 500 KB、文件数大于 100、所有条目解压后非空、包含 `server/ui_interaction_contract.py`、`server/on_demand_ui_sidecar.py`、`sidecars/usfr-ui-render-sidecar/dist/`、Sidecar 锁文件与 extractor、完整 `server/`、`scripts/`、四个 bundled skills、Seedance runtime skills、deployment、tests、中文手册和 `RELEASE-MANIFEST.json`；不得包含 `node_modules/`、`.venv/`、Chromium 缓存或渲染缓存。

- [ ] **Step 3: 写发布报告**

  报告必须明确区分：

  - 已通过的本地功能测试；
  - 已通过的容器无付费 E2E；
  - 已通过的真实 API 样例；
  - 尚未执行的付费全量 36 案例（如果未执行）；
  - 新旧 ZIP 的 SHA；
  - 回滚命令和旧包路径。

### Task 8: 真实服务端烟雾测试和发布判定

**Files:**
- Create: `C:/Users/zhaocx04/Documents/New project/exports/usfr-video-service-2026-07-29-r2-real-smoke-report.json`

**Interfaces:**
- Consumes: 用户配置完成的 `.env`、新 ZIP 和一组获准使用的真实测试素材。
- Produces: 服务端实际 GPT/RunningHub/UI renderer/FFmpeg/MinIO 全链路证据。

- [ ] **Step 1: 启动并检查 readiness**

  ```powershell
  docker compose --env-file .env -f deployment/docker-compose.yml up -d
  Invoke-RestMethod http://127.0.0.1:8080/healthz
  Invoke-RestMethod http://127.0.0.1:8080/readyz
  ```

  Expected: Redis、MinIO、bundle、models、capabilities 和 provider 全部 ready；UI Sidecar 显示 `installed=true, running=false, lazy_ready=true`，证明部署完整但尚未提前启动。

- [ ] **Step 2: 执行一条真实 UI 重绘任务**

  使用 Task 1 同类素材，完成上传、脚本确认、故事板确认、生成、合成和 QC。首次进入 UI 渲染时 Sidecar 才启动，服务端结果必须与本地能力使用相同路线、代码 SHA、Remotion bundle、OpenCV extractor 和合同，并输出真实 MP4；任务结束后验证空闲退出。

- [ ] **Step 3: 做发布判定**

  只有以下全部成立才标记“可部署最新全部能力”：

  - 本地冻结 SHA 与 ZIP `RELEASE-MANIFEST.json` 一致；
  - 服务端 UI 输出可播放且无黑帧；
  - 人物/商品/UI 路由正确；
  - UI 操作时间轴与源帧锁定；
  - OCR 与布局均为 100%；
  - 无 `?` 替换字符和 U+FFFD；
  - 没有全视频二次深度分析；
  - 没有新增 Seedance 任务或自动付费重试；
  - 无 UI、opaque UI 和直接 language-only 路线中 Sidecar 启动次数为 0；
  - 服务端 Sidecar 默认使用 CPU-only 软件渲染，没有 CUDA、NVENC 或 GPU 依赖；
  - Redis/临时 MinIO 对象按 TTL 清理，只保留最终 MP4。

## Release Decision

本计划采用“重新生成完整发布包”，不采用“向旧 ZIP 复制几个变更文件”。原因是当前旧 ZIP 已经缺少新建的 `server/ui_interaction_contract.py`，并且 `SKILL.md`、`packaged_stages.py`、`analysis_scope.py`、`real_capabilities.py`、`verify_bundle.py`、`bundle_manifest.json` 均已与本地版本不同。只有完整快照重建才能保证服务端得到本地 Skill 当时的全部最新能力，并可通过 SHA-256 证明两者一致。
